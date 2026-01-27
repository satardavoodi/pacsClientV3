# -*- coding: utf-8 -*-

"""
Resumable DICOM Socket Client
کلاینت سوکت DICOM با قابلیت ادامه دانلود

This module provides a resumable DICOM download client using socket communication.
It supports batch downloads, progress tracking, and resume functionality.
"""

import socket
import json
import os
import gzip
import time
import threading
import base64
import concurrent.futures
import queue
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from ..utils.socket_config import get_socket_config
from ..utils.socket_token_manager import get_socket_token_manager
import logging
from io import BytesIO
from .advanced_progress_tracker import AdvancedProgressTracker, MultiConnectionProgressTracker
from .dynamic_thread_optimizer import DynamicThreadOptimizer, AdaptiveConnectionManager

# Configure logging first
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import pydicom for reading DICOM headers
try:
    import pydicom
    from pydicom.charset import python_encoding
    import warnings
    from contextlib import contextmanager
    
    PYDICOM_AVAILABLE = True
    logger.info("✅ pydicom available for DICOM header reading")
    
    # ثبت نگاشت کُدک برای ISO 2022 IR 159 (JIS X 0213)
    try:
        ''.encode('iso2022_jp_3')
        python_encoding.setdefault('ISO 2022 IR 159', 'iso2022_jp_3')
    except LookupError:
        python_encoding.setdefault('ISO 2022 IR 159', 'iso2022_jp_ext')
    
    @contextmanager
    def _suppress_pydicom_unknown_encoding():
        """فقط هشدار «Unknown encoding …» را بی‌اثر می‌کنیم تا dcmread بیفتد"""
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Unknown encoding .* - using default encoding instead",
                category=UserWarning
            )
            yield
    
    def _safe_dcmread(path, **kwargs):
        """یک dcmread امن که هشدار charset را موقتاً خاموش می‌کند"""
        with _suppress_pydicom_unknown_encoding():
            return pydicom.dcmread(path, force=True, **kwargs)
    
except ImportError:
    PYDICOM_AVAILABLE = False
    logger.warning("⚠️ pydicom not available - series info extraction will be limited")

# Import database functions
try:
    from PacsClient.utils.database import (
        insert_patient, insert_study, insert_series, insert_instance,
        insert_download_progress, get_download_progress, complete_download_progress,
        delete_download_progress
    )
except ImportError:
    logger.warning("Database functions not available")
    insert_patient = insert_study = insert_series = insert_instance = None
    insert_download_progress = get_download_progress = complete_download_progress = delete_download_progress = None


class SocketConnectionPool:
    """
    Connection pool for parallel downloads
    """
    
    def __init__(self, host: str, port: int, pool_size: int = 4, config=None):
        self.host = host
        self.port = port
        self.pool_size = pool_size
        self.config = config or get_socket_config()
        self.connections = queue.Queue(maxsize=pool_size)
        self.lock = threading.Lock()
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize connection pool"""
        for _ in range(self.pool_size):
            # Create client without connection pool to avoid recursion
            client = ResumableDicomSocketClient(self.host, self.port, disable_pool=True)
            self.connections.put(client)
    
    def get_connection(self, timeout: float = 30) -> Optional['ResumableDicomSocketClient']:
        """Get a connection from pool"""
        try:
            client = self.connections.get(timeout=timeout)
            if not client.is_connected():
                if not client.connect():
                    # If connection failed, try to create a new one
                    client = ResumableDicomSocketClient(self.host, self.port)
                    if not client.connect():
                        self.connections.put(client)  # Put it back
                        return None
            return client
        except queue.Empty:
            logger.warning("⚠️ No available connections in pool")
            return None
    
    def return_connection(self, client: 'ResumableDicomSocketClient'):
        """Return connection to pool"""
        try:
            self.connections.put_nowait(client)
        except queue.Full:
            # Pool is full, close this connection
            client.disconnect()
    
    def close_all(self):
        """Close all connections in pool"""
        while not self.connections.empty():
            try:
                client = self.connections.get_nowait()
                client.disconnect()
            except queue.Empty:
                break


class ResumableDicomSocketClient:
    """
    Resumable DICOM Socket Client
    
    This client provides resumable DICOM download functionality with:
    - Batch downloads with configurable batch sizes
    - Progress tracking and JSON storage
    - Resume capability from interruption point
    - Compression support (gzip)
    - Error handling and retry mechanisms
    """
    
    def __init__(self, host=None, port=None, timeout=None, disable_pool=False):
        """
        Initialize the Resumable DICOM Socket client
        
        Args:
            host (str): Server host address
            port (int): Server port number
            timeout (int): Connection timeout in seconds
            disable_pool (bool): Disable connection pool to avoid recursion
        """
        config = get_socket_config()
        self.host = host if host is not None else config.get_socket_host()
        self.port = port if port is not None else config.get_socket_port()
        self.timeout = timeout if timeout is not None else config.get_connection_timeout()
        self.socket = None
        self.connected = False
        self.lock = threading.Lock()
        self.max_retries = config.get_max_retries()
        self.retry_delay = config.get_retry_delay()
        self.batch_timeout = config.get_batch_timeout()
        self.chunk_size = config.get_chunk_size()
        self.max_consecutive_failures = config.get_max_consecutive_failures()
        self.adaptive_batch_size = config.is_adaptive_batch_size_enabled()
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        
        # High bandwidth settings
        self.parallel_downloads = config.is_parallel_downloads_enabled() and not disable_pool
        self.max_parallel_batches = config.get_max_parallel_batches()
        self.tcp_nodelay = config.is_tcp_nodelay_enabled()
        self.tcp_window_size = config.get_tcp_window_size()
        self.high_bandwidth_mode = config.is_high_bandwidth_mode_enabled()
        self.prefetch_batches = config.get_prefetch_batches()
        
        # Connection pool for parallel downloads (only if not disabled)
        self.connection_pool = None
        if self.parallel_downloads and not disable_pool:
            self.connection_pool = SocketConnectionPool(
                self.host, self.port, self.max_parallel_batches, config
            )
        
        # Advanced progress tracking (pySmartDL style) - only if not disabled
        if not disable_pool:
            self.progress_tracker = MultiConnectionProgressTracker()
            self.thread_optimizer = DynamicThreadOptimizer(
                min_threads=1, 
                max_threads=self.max_parallel_batches
            )
            self.adaptive_connection_manager = AdaptiveConnectionManager(
                min_connections=1,
                max_connections=self.max_parallel_batches
            )
        else:
            # Simplified initialization for pool clients
            self.progress_tracker = None
            self.thread_optimizer = None
            self.adaptive_connection_manager = None
        
    def connect(self):
        """
        Connect to the Socket server
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        with self.lock:
            try:
                # Close existing socket if any before creating new one
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                    self.connected = False
                
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self.timeout)
                
                # Enable keep-alive
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
                # Set TCP keep-alive parameters (Windows)
                if hasattr(socket, 'TCP_KEEPIDLE'):
                    self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                if hasattr(socket, 'TCP_KEEPINTVL'):
                    self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                if hasattr(socket, 'TCP_KEEPCNT'):
                    self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                
                # High bandwidth optimizations
                if self.high_bandwidth_mode:
                    # Maximize socket buffer sizes for high bandwidth
                    max_buffer_size = max(self.tcp_window_size, self.chunk_size * 8)
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, max_buffer_size)
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, max_buffer_size // 2)
                    logger.info(f"🚀 High bandwidth mode: RCV={max_buffer_size}, SND={max_buffer_size // 2}")
                else:
                    # Standard buffer sizes
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.chunk_size * 4)
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.chunk_size * 2)
                
                # Enable TCP_NODELAY for low latency (disable Nagle's algorithm)
                if self.tcp_nodelay:
                    self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    logger.debug("✅ TCP_NODELAY enabled for low latency")
                
                # Set TCP window scaling (if supported)
                try:
                    if hasattr(socket, 'TCP_WINDOW_CLAMP'):
                        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_WINDOW_CLAMP, self.tcp_window_size)
                        logger.debug(f"✅ TCP window size set to {self.tcp_window_size}")
                except:
                    pass  # Not all systems support this
                
                self.socket.connect((self.host, self.port))
                self.connected = True
                logger.info(f"✅ Connected to Socket server at {self.host}:{self.port}")
                return True
            except Exception as e:
                logger.error(f"❌ Connection failed: {e}")
                self.connected = False
                # Close the socket if connection failed
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                return False
    
    def connect_with_retry(self):
        """
        Connect to server with retry mechanism
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        for attempt in range(self.max_retries):
            try:
                if self.connect():
                    return True
                else:
                    logger.warning(f"❌ Attempt {attempt + 1} failed")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    return False
        return False
    
    def disconnect(self):
        """
        Disconnect from the server
        """
        with self.lock:
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
                self.connected = False
                logger.info("🔌 Disconnected from Socket server")
            
            # Close connection pool if exists
            if self.connection_pool:
                try:
                    self.connection_pool.close_all()
                    logger.info("🔌 Closed connection pool")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing connection pool: {e}")
    
    def send_request_with_response(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Send a request to the server and get response (for Login, VerifyToken, etc.)
        
        Args:
            endpoint (str): The endpoint to call
            params (dict): Request parameters
            
        Returns:
            dict: Response from server or None if failed
        """
        try:
            # Check connection status without lock to avoid deadlock
            if not self.connected:
                if not self.connect_with_retry():
                    return None
            
            request = {
                "endpoint": endpoint,
                "params": params
            }
            
            # Add token to request (except for Login endpoint)
            if endpoint != "Login":
                token_manager = get_socket_token_manager()
                request = token_manager.add_token_to_request(request)
            
            message = json.dumps(request).encode('utf-8')
            length = len(message).to_bytes(4, byteorder='big')
            
            # Use lock only for socket operations
            with self.lock:
                if not self.socket or not self.connected:
                    return None
                self.socket.sendall(length + message)
            
            # Receive response length
            with self.lock:
                if not self.socket or not self.connected:
                    return None
                length_data = self.socket.recv(4)
            
            if not length_data:
                logger.error("❌ Connection closed by server")
                with self.lock:
                    self.connected = False
                    if self.socket:
                        try:
                            self.socket.close()
                        except:
                            pass
                        self.socket = None
                return None
                
            response_length = int.from_bytes(length_data, byteorder='big')
            response_data = b''
            
            # Receive response data
            while len(response_data) < response_length:
                with self.lock:
                    if not self.socket or not self.connected:
                        return None
                    chunk = self.socket.recv(min(4096, response_length - len(response_data)))
                
                if not chunk:
                    logger.error("❌ Connection lost while receiving data")
                    with self.lock:
                        self.connected = False
                        if self.socket:
                            try:
                                self.socket.close()
                            except:
                                pass
                            self.socket = None
                    return None
                response_data += chunk
            
            response = json.loads(response_data.decode('utf-8'))
            return response
            
        except Exception as e:
            logger.error(f"❌ Request error: {e}")
            with self.lock:
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
            return None
    
    def login(self, username: str, password: str) -> tuple:
        """
        Login to socket server
        
        Args:
            username (str): Username
            password (str): Password
            
        Returns:
            tuple: (success: bool, message: str, token: str or None, user: dict or None)
        """
        try:
            logger.info(f"🔐 Logging in as {username}...")
            
            response = self.send_request_with_response('Login', {
                'username': username,
                'password': password
            })
            
            if not response:
                return False, "No response from server. Please check server connection.", None, None
            
            if response.get('success'):
                token = response.get('token')
                user = response.get('user')
                
                logger.info(f"✅ Login successful!")
                logger.info(f"   User: {user.get('full_name')}")
                logger.info(f"   Role: {user.get('role')}")
                
                return True, "Login successful", token, user
            else:
                error = response.get('error', 'Unknown error')
                logger.error(f"❌ Login failed: {error}")
                return False, error, None, None
                
        except Exception as e:
            error_msg = f"Login error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None, None
    
    def verify_token(self, token: str) -> tuple:
        """
        Verify JWT token validity
        
        Args:
            token (str): JWT token to verify
            
        Returns:
            tuple: (valid: bool, message: str, user: dict or None)
        """
        try:
            response = self.send_request_with_response('VerifyToken', {
                'token': token
            })
            
            if not response:
                return False, "No response from server", None
            
            if response.get('valid'):
                user = response.get('user')
                logger.info(f"✅ Token is valid")
                logger.info(f"   User: {user.get('username')}")
                return True, "Token is valid", user
            else:
                error = response.get('error', 'Invalid token')
                logger.error(f"❌ Token invalid: {error}")
                return False, error, None
                
        except Exception as e:
            error_msg = f"Verify error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return False, error_msg, None
    
    def send_request(self, endpoint: str, params: Dict[str, Any]) -> bool:
        """
        Send a request to the server with connection health check
        
        Args:
            endpoint (str): The endpoint to call
            params (dict): Request parameters
            
        Returns:
            bool: True if request sent successfully, False otherwise
        """
        with self.lock:
            # Check connection health before sending important requests
            if self.connected and not self.check_connection_health():
                logger.warning("⚠️ Connection health check failed, reconnecting...")
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
            
            if not self.connected:
                if not self.connect_with_retry():
                    return False
            
            try:
                # Create request
                request = {
                    "endpoint": endpoint,
                    "params": params
                }
                
                # Add token to request (if available)
                token_manager = get_socket_token_manager()
                request = token_manager.add_token_to_request(request)
                
                # Convert to JSON
                request_json = json.dumps(request, ensure_ascii=False)
                request_bytes = request_json.encode('utf-8')
                
                # Send message length (4 bytes, Big Endian)
                length_bytes = len(request_bytes).to_bytes(4, byteorder='big')
                self.socket.send(length_bytes)
                
                # Send message content
                self.socket.send(request_bytes)
                
                logger.debug(f"📤 Sent request to {endpoint} with {len(request_bytes)} bytes")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error sending request: {e}")
                self.connected = False
                # Close socket on error
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                return False
    
    def receive_response(self) -> Dict[str, Any]:
        """
        Receive response from the server
        
        Returns:
            dict: Response data or error information
        """
        with self.lock:
            try:
                if not self.socket or not self.connected:
                    return {"status": "error", "message": "Not connected to server"}
                
                # Receive message length (4 bytes, Big Endian)
                response_length_bytes = self.socket.recv(4)
                if len(response_length_bytes) != 4:
                    raise Exception("Invalid response length header")
                
                response_length = int.from_bytes(response_length_bytes, byteorder='big')
                logger.debug(f"📥 Expecting response of {response_length} bytes")
                
                # Receive message content
                response_data = b''
                start_time = time.time()
                timeout = min(self.batch_timeout, 300)  # Max 5 minutes per response
                last_progress_time = start_time
                
                while len(response_data) < response_length:
                    current_time = time.time()
                    
                    # Check timeout
                    if current_time - start_time > timeout:
                        raise Exception(f"Response timeout after {timeout} seconds")
                    
                    # Log progress every 30 seconds for long responses
                    if current_time - last_progress_time > 30:
                        progress = (len(response_data) / response_length) * 100
                        logger.info(f"📥 Receiving progress: {progress:.1f}% ({len(response_data)}/{response_length} bytes)")
                        last_progress_time = current_time
                    
                    chunk_size = min(self.chunk_size, response_length - len(response_data))
                    try:
                        # Set a shorter timeout for individual recv calls
                        self.socket.settimeout(30)  # 30 seconds for each chunk
                        chunk = self.socket.recv(chunk_size)
                        if not chunk:
                            logger.warning(f"⚠️ No data received, connection may be closed")
                            break
                        response_data += chunk
                        
                        # Log progress for large responses
                        if response_length > 1024 * 1024:  # 1MB
                            progress = (len(response_data) / response_length) * 100
                            if len(response_data) % (1024 * 1024) == 0:  # Log every MB
                                logger.debug(f"📥 Receiving: {progress:.1f}% ({len(response_data)}/{response_length} bytes)")
                                
                    except socket.timeout:
                        logger.warning(f"⚠️ Socket timeout, received {len(response_data)}/{response_length} bytes")
                        # Check if we've been waiting too long
                        if current_time - start_time > 60:  # If more than 1 minute
                            logger.error(f"❌ Extended timeout, breaking receive loop")
                            break
                        continue
                    except Exception as e:
                        logger.error(f"❌ Error receiving data: {e}")
                        break
                    finally:
                        # Restore original timeout
                        self.socket.settimeout(self.timeout)
                
                # Convert to JSON
                response = json.loads(response_data.decode('utf-8'))
                logger.debug(f"📥 Received response: {response.get('status', 'unknown')}")
                return response
            
            except Exception as e:
                logger.error(f"❌ Error receiving response: {e}")
                self.connected = False
                return {"error": str(e), "status": "error"}
    
    def validate_and_process_dicom_data(self, dicom_data: Any, instance_number: int, compression: str = "gzip") -> Optional[bytes]:
        """
        اعتبارسنجی و پردازش داده‌های DICOM
        
        Args:
            dicom_data: Raw DICOM data from server
            instance_number: Instance number for logging
            compression: Compression type
            
        Returns:
            bytes or None: Processed DICOM data or None if invalid
        """
        try:
            # بررسی وجود داده
            if not dicom_data:
                logger.warning(f"⚠️ No DICOM data for instance {instance_number}")
                return None
            
            # بررسی نوع داده
            if isinstance(dicom_data, str):
                # تلاش برای decode base64
                try:
                    processed_data = base64.b64decode(dicom_data)
                    logger.debug(f"✅ Successfully decoded base64 for instance {instance_number}")
                except Exception as e:
                    logger.error(f"❌ Base64 decode failed for instance {instance_number}: {e}")
                    return None
            elif isinstance(dicom_data, bytes):
                # داده قبلاً به صورت bytes است
                processed_data = dicom_data
                logger.debug(f"✅ Data already in bytes format for instance {instance_number}")
            else:
                logger.error(f"❌ Invalid data type for instance {instance_number}: {type(dicom_data)}")
                return None
            
            # بررسی اینکه داده خالی نباشد
            if not processed_data or len(processed_data) == 0:
                logger.warning(f"⚠️ Empty DICOM data for instance {instance_number}")
                return None
            
            # بررسی حداقل اندازه DICOM
            if len(processed_data) < 128:  # حداقل اندازه یک فایل DICOM معتبر
                logger.warning(f"⚠️ DICOM data too small for instance {instance_number}: {len(processed_data)} bytes")
                return None
            
            return processed_data
            
        except Exception as e:
            logger.error(f"❌ Error processing DICOM data for instance {instance_number}: {e}")
            return None

    def safe_save_dicom_file(self, filepath: Path, dicom_data: bytes, instance_number: int) -> bool:
        """
        ذخیره ایمن فایل DICOM
        
        Args:
            filepath: مسیر فایل
            dicom_data: داده‌های DICOM
            instance_number: شماره instance برای logging
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # اطمینان از وجود دایرکتوری والد
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            # ذخیره فایل
            with open(filepath, 'wb') as f:
                f.write(dicom_data)
            
            # بررسی اینکه فایل واقعاً ذخیره شده
            if not filepath.exists():
                logger.error(f"❌ File was not saved: {filepath}")
                return False
            
            # بررسی اندازه فایل
            saved_size = filepath.stat().st_size
            if saved_size != len(dicom_data):
                logger.error(f"❌ File size mismatch for instance {instance_number}: expected {len(dicom_data)}, got {saved_size}")
                return False
            
            logger.debug(f"✅ Successfully saved instance {instance_number}: {filepath} ({saved_size} bytes)")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error saving instance {instance_number} to {filepath}: {e}")
            return False
    
    def get_study_info(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get study information including total instances
        
        Args:
            study_uid (str): Study Instance UID
            
        Returns:
            dict or None: Study information or None if not found
        """
        logger.info(f"🔍 Getting study info for: {study_uid}")
        
        if not self.send_request("GetStudyInfo", {"study_instance_uid": study_uid}):
            return None
        
        response = self.receive_response()
        
        if response.get("status") != "success":
            error_msg = response.get("error", "Unknown error")
            logger.error(f"❌ Request failed: {error_msg}")
            return None
        
        return response.get("data", {})
    
    def get_study_dicom_files_batch(self, study_uid: str, batch_size: int = 10, 
                                   offset: int = 0, compression: str = "gzip") -> Optional[Dict[str, Any]]:
        """
        Get a batch of DICOM files for a study with retry mechanism
        
        Args:
            study_uid (str): Study Instance UID
            batch_size (int): Number of instances to retrieve in this batch
            offset (int): Starting offset for this batch
            compression (str): Compression type ("gzip" or None)
            
        Returns:
            dict or None: Batch data or None if failed
        """
        logger.info(f"📦 Getting batch: offset={offset}, size={batch_size}")
        
        # Adaptive batch size logic
        if self.adaptive_batch_size:
            if self.consecutive_failures >= self.max_consecutive_failures and batch_size > 1:
                batch_size = max(1, batch_size // 2)
                logger.info(f"🔄 Reducing batch size due to failures: {batch_size}")
            elif self.consecutive_successes >= 5 and batch_size < 20:
                batch_size = min(20, batch_size * 2)
                logger.info(f"🔄 Increasing batch size due to successes: {batch_size}")
        
        # Try different endpoint names and parameter combinations
        endpoint_configs = [
            ("GetStudyDicomFiles", {
                "study_instance_uid": study_uid,
                "instance_limit": batch_size,
                "compression": compression
            }),
            ("GetStudyDicomFiles", {
                "study_instance_uid": study_uid,
                "batch_size": batch_size,
                "offset": offset,
                "compression": compression
            }),
            ("GetStudyDicomFilesBatch", {
                "study_uid": study_uid,
                "batch_size": batch_size,
                "offset": offset,
                "compression": compression
            }),
            ("GetStudyDicomFiles", {
                "study_instance_uid": study_uid,
                "limit": batch_size,
                "offset": offset
            }),
        ]
        
        # Retry mechanism for each endpoint
        for endpoint, params in endpoint_configs:
            logger.info(f"🧪 Trying endpoint: {endpoint}")
            
            for retry_attempt in range(self.max_retries):
                try:
                    if not self.send_request(endpoint, params):
                        if retry_attempt < self.max_retries - 1:
                            logger.warning(f"⚠️ Send request failed, retry {retry_attempt + 1}/{self.max_retries}")
                            time.sleep(self.retry_delay * (2 ** retry_attempt))
                            continue
                        else:
                            break
                    
                    response = self.receive_response()
                    
                    if response.get("status") == "success":
                        logger.info(f"✅ Success with endpoint: {endpoint}")
                        self.consecutive_failures = 0
                        self.consecutive_successes += 1
                        return response.get("data", {})
                    else:
                        error_msg = response.get("error", "Unknown error")
                        logger.warning(f"⚠️ {endpoint} failed: {error_msg}")
                        
                        # If it's "Response too large", try with smaller batch immediately
                        if "too large" in error_msg.lower() and batch_size > 1:
                            logger.info(f"🔄 Response too large, trying smaller batch size: {batch_size // 2}")
                            self.consecutive_failures += 1
                            return self.get_study_dicom_files_batch(study_uid, batch_size // 2, offset, compression)
                        
                        # For other errors, retry
                        if retry_attempt < self.max_retries - 1:
                            logger.warning(f"⚠️ Retrying {endpoint}, attempt {retry_attempt + 1}/{self.max_retries}")
                            time.sleep(self.retry_delay * (2 ** retry_attempt))
                        else:
                            break
                            
                except Exception as e:
                    logger.error(f"❌ Exception in batch request: {e}")
                    if retry_attempt < self.max_retries - 1:
                        logger.warning(f"⚠️ Retrying due to exception, attempt {retry_attempt + 1}/{self.max_retries}")
                        time.sleep(self.retry_delay * (2 ** retry_attempt))
                    else:
                        break
        
        logger.error(f"❌ All batch request attempts failed after {self.max_retries} retries")
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        return None
    
    def download_batch_by_instance_numbers(self, study_uid: str, instance_numbers: list, 
                                         compression: str = "gzip", series_uid: str = None) -> Optional[Dict[str, Any]]:
        """
        Download specific instances by their numbers (like the working code)
        
        Args:
            study_uid (str): Study Instance UID
            instance_numbers (list): List of instance numbers to download
            compression (str): Compression type
            series_uid (str): Series UID to filter instances (optional)
            
        Returns:
            dict or None: Batch data or None if failed
        """
        logger.info(f"📦 Downloading {len(instance_numbers)} specific instances")
        if series_uid:
            logger.info(f"🔍 Filtering by series UID: {series_uid[:50]}...")
        
        params = {
            "study_instance_uid": study_uid,
            "instance_limit": len(instance_numbers),
            "instance_numbers": instance_numbers
        }
        
        if series_uid:
            params["series_uid"] = series_uid
            
        if compression:
            params["compression"] = compression
            
        if not self.send_request("GetStudyDicomFiles", params):
            return None
        
        response = self.receive_response()
        
        if response.get("status") == "success":
            logger.info(f"✅ Successfully downloaded {len(instance_numbers)} instances")
            return response.get("data", {})
        else:
            error_msg = response.get("error", "Unknown error")
            logger.error(f"❌ Batch download failed: {error_msg}")
            return None
    
    def get_download_progress_path(self, study_uid: str, output_dir: str) -> Path:
        """
        Get the path to the download progress file
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            
        Returns:
            Path: Path to progress file
        """
        progress_dir = Path(output_dir) / ".download_progress"
        progress_dir.mkdir(parents=True, exist_ok=True)
        return progress_dir / f"{study_uid}_progress.json"
    
    def load_download_progress(self, study_uid: str, output_dir: str) -> Optional[Dict[str, Any]]:
        """
        Load download progress from file
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            
        Returns:
            dict or None: Progress data or None if not found
        """
        progress_file = self.get_download_progress_path(study_uid, output_dir)
        
        try:
            if progress_file.exists():
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress_data = json.load(f)
                logger.info(f"📊 Loaded progress: {progress_data.get('downloaded_count', 0)}/{progress_data.get('total_instances', 0)}")
                return progress_data
            else:
                logger.info("📊 No previous progress found")
                return None
        except Exception as e:
            logger.warning(f"⚠️ Error loading progress: {e}")
            return None
    
    def save_download_progress(self, study_uid: str, output_dir: str, progress_data: Dict[str, Any]):
        """
        Save download progress to file
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            progress_data (dict): Progress data to save
        """
        progress_file = self.get_download_progress_path(study_uid, output_dir)
        
        try:
            # Update timestamp
            progress_data["last_update"] = datetime.now().isoformat()
            
            with open(progress_file, 'w', encoding='utf-8') as f:
                json.dump(progress_data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"💾 Saved progress: {progress_data.get('downloaded_count', 0)}/{progress_data.get('total_instances', 0)}")
        except Exception as e:
            logger.error(f"❌ Error saving progress: {e}")
    
    def clear_download_progress(self, study_uid: str, output_dir: str):
        """
        Clear download progress file
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
        """
        progress_file = self.get_download_progress_path(study_uid, output_dir)
        
        try:
            if progress_file.exists():
                progress_file.unlink()
                logger.info("🗑️ Cleared download progress")
        except Exception as e:
            logger.error(f"❌ Error clearing progress: {e}")
    
    def get_download_status(self, study_uid: str, output_dir: str) -> Dict[str, Any]:
        """
        Get current download status
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            
        Returns:
            dict: Download status information
        """
        # First try to get progress from database
        progress_data = None
        if get_download_progress:
            try:
                progress_data = get_download_progress(study_uid)
                if progress_data:
                    logger.info(f"📊 Loaded progress from database: {progress_data.get('downloaded_count', 0)}/{progress_data.get('total_instances', 0)}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to get progress from database: {e}")
        
        # Fallback to file-based progress
        if not progress_data:
            progress_data = self.load_download_progress(study_uid, output_dir)
        
        if not progress_data:
            return {
                "status": "not_started",
                "progress_percent": 0,
                "downloaded_count": 0,
                "total_instances": 0
            }
        
        downloaded_count = progress_data.get("downloaded_count", 0)
        total_instances = progress_data.get("total_instances", 0)
        
        if total_instances == 0:
            progress_percent = 0
        else:
            progress_percent = (downloaded_count / total_instances) * 100
        
        if downloaded_count >= total_instances and total_instances > 0:
            status = "completed"
        elif downloaded_count > 0:
            status = "in_progress"
        else:
            status = "not_started"
        
        return {
            "status": status,
            "progress_percent": progress_percent,
            "downloaded_count": downloaded_count,
            "total_instances": total_instances,
            "last_update": progress_data.get("last_update"),
            "patient_name": progress_data.get("patient_name"),
            "study_date": progress_data.get("study_date")
        }
    
    def get_study_dicom_files_resumable(self, study_uid: str, output_dir: str = "./downloads",
                                       batch_size: int = 10, compression: str = "gzip",
                                       resume: bool = True, progress_callback: Optional[Callable] = None) -> bool:
        """
        Download DICOM files with resumable capability
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            batch_size (int): Batch size for downloads
            compression (str): Compression type ("gzip" or None)
            resume (bool): Whether to resume from previous download
            progress_callback (callable): Progress callback function
            
        Returns:
            bool: True if download successful, False otherwise
        """
        logger.info(f"🚀 Starting resumable download for study: {study_uid}")
        
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Load existing progress if resuming
        progress_data = None
        if resume:
            progress_data = self.load_download_progress(study_uid, output_dir)
        
        # Get study info if not resuming or if progress is incomplete
        if not progress_data or progress_data.get("downloaded_count", 0) < progress_data.get("total_instances", 0):
            study_info = self.get_study_info(study_uid)
            if not study_info:
                logger.error(f"❌ Failed to get study info for: {study_uid}")
                return False
            
            total_instances = study_info.get("total_instances", 0)
            patient_name = study_info.get("patient_name", "Unknown")
            study_date = study_info.get("study_date", "")
            
            if total_instances == 0:
                logger.warning(f"⚠️ No instances found for study: {study_uid}")
                return False
            
            # Initialize or update progress data
            if not progress_data:
                progress_data = {
                    "study_uid": study_uid,
                    "patient_name": patient_name,
                    "study_date": study_date,
                    "total_instances": total_instances,
                    "downloaded_count": 0,
                    "downloaded_instances": [],
                    "batch_size": batch_size,
                    "compression": compression,
                    "start_time": datetime.now().isoformat()
                }
            else:
                # Update existing progress with new info
                progress_data.update({
                    "total_instances": total_instances,
                    "patient_name": patient_name,
                    "study_date": study_date,
                    "batch_size": batch_size,
                    "compression": compression
                })
        else:
            total_instances = progress_data.get("total_instances", 0)
            logger.info(f"📊 Resuming download: {progress_data.get('downloaded_count', 0)}/{total_instances} complete")
        
        # Start download from where we left off
        downloaded_count = progress_data.get("downloaded_count", 0)
        downloaded_instances = set(progress_data.get("downloaded_instances", []))
        
        try:
            while downloaded_count < total_instances:
                # Calculate batch parameters
                remaining = total_instances - downloaded_count
                current_batch_size = min(batch_size, remaining)
                offset = downloaded_count
                
                logger.info(f"📦 Downloading batch: {offset}-{offset + current_batch_size - 1} ({current_batch_size} files)")
                
                # Get batch data
                batch_data = self.get_study_dicom_files_batch(
                    study_uid, current_batch_size, offset, compression
                )
                
                if not batch_data:
                    logger.error(f"❌ Failed to get batch at offset {offset}")
                    return False
                
                instances = batch_data.get("instances", [])
                if not instances:
                    logger.warning(f"⚠️ No instances in batch at offset {offset}")
                    break
                
                # Process each instance in the batch
                batch_downloaded = 0
                for instance in instances:
                    instance_number = instance.get("instance_number", 0)
                    sop_instance_uid = instance.get("sop_instance_uid", "")
                    
                    # Skip if already downloaded
                    if instance_number in downloaded_instances:
                        continue
                    
                    # Create filename
                    filename = f"Instance_{instance_number}.dcm"
                    filepath = output_path / filename
                    
                    # Get DICOM data
                    dicom_data = instance.get("dicom_data")
                    if not dicom_data:
                        logger.warning(f"⚠️ No DICOM data for instance {instance_number}")
                        continue
                    
                    # اعتبارسنجی و پردازش داده‌های DICOM
                    dicom_data = self.validate_and_process_dicom_data(dicom_data, instance_number, compression)
                    if dicom_data is None:
                        logger.error(f"❌ Invalid DICOM data for instance {instance_number}")
                        continue
                    
                    # Decompress if needed (only if server indicates compression)
                    if compression == "gzip" and instance.get("is_compressed", False):
                        try:
                            dicom_data = gzip.decompress(dicom_data)
                            logger.debug(f"✅ Decompressed gzip data for instance {instance_number}")
                        except Exception as e:
                            logger.warning(f"⚠️ Gzip decompression failed for instance {instance_number}: {e}")
                            # Continue without decompression - data might not actually be compressed
                            pass
                    
                    # Save DICOM file
                    if self.safe_save_dicom_file(filepath, dicom_data, instance_number):
                        # Update progress
                        downloaded_instances.add(instance_number)
                        downloaded_count += 1
                        batch_downloaded += 1
                        
                        # Save metadata
                        metadata = {
                            "sop_instance_uid": sop_instance_uid,
                            "series_description": instance.get("series_description", ""),
                            "modality": instance.get("modality", ""),
                            "instance_number": instance_number,
                            "series_number": instance.get("series_number", 0),
                            "file_size": len(dicom_data),
                            "patient_name": progress_data.get("patient_name", ""),
                            "study_date": progress_data.get("study_date", "")
                        }
                        
                        metadata_file = filepath.with_suffix('.json')
                        with open(metadata_file, 'w', encoding='utf-8') as f:
                            json.dump(metadata, f, indent=2, ensure_ascii=False)
                        
                        # Update progress data
                        progress_data["downloaded_count"] = downloaded_count
                        progress_data["downloaded_instances"] = list(downloaded_instances)
                        
                        # Save progress
                        self.save_download_progress(study_uid, output_dir, progress_data)
                        
                        # Call progress callback
                        if progress_callback:
                            progress_percent = (downloaded_count / total_instances) * 100
                            progress_callback(downloaded_count, total_instances, progress_percent)
                        
                        logger.debug(f"✅ Downloaded instance {instance_number} ({downloaded_count}/{total_instances})")
                    else:
                        logger.error(f"❌ Failed to save instance {instance_number}")
                        continue
                
                logger.info(f"📦 Batch complete: {batch_downloaded} files downloaded")
                
                # Small delay between batches to prevent overwhelming the server
                time.sleep(1.0)  # Increased delay to give server more breathing room
                
                # Additional delay for larger batches
                if len(batch) > 3:
                    time.sleep(0.5)
            
            # Download completed successfully
            logger.info(f"✅ Download completed: {downloaded_count}/{total_instances} files")
            
            # Clear progress file on successful completion
            if downloaded_count >= total_instances:
                self.clear_download_progress(study_uid, output_dir)
                logger.info("🗑️ Cleared progress file after successful completion")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Download error: {e}")
            return False
    
    def download_study_batch_like_working_code(self, study_uid: str, output_dir: str = "./downloads",
                                             batch_size: int = 10, compression: str = "gzip", 
                                             resume: bool = True, progress_callback: Optional[Callable] = None) -> bool:
        """
        Download study using the same approach as the working batch downloader
        """
        logger.info(f"🔄 Starting batch download (working code style) for study: {study_uid}")
        
        # Use SOURCE_PATH structure instead of downloads
        try:
            from PacsClient.utils.config import SOURCE_PATH
            logger.info(f"✅ Imported SOURCE_PATH: {SOURCE_PATH}")
        except Exception as e:
            logger.error(f"❌ Failed to import SOURCE_PATH: {e}")
            return False
            
        try:
            from PacsClient.utils import insert_patient, insert_study, insert_series, insert_instance
            logger.info(f"✅ Imported database functions")
        except Exception as e:
            logger.warning(f"⚠️ Failed to import database functions: {e}")
            insert_patient = insert_study = insert_series = insert_instance = None
        
        # Create study directory in SOURCE_PATH
        study_path = SOURCE_PATH / study_uid
        study_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Using SOURCE_PATH structure: {study_path}")
        
        # Get study info
        logger.info(f"🔍 Getting study info for: {study_uid}")
        study_info = self.get_study_info(study_uid)
        if not study_info:
            logger.error(f"❌ Failed to get study info for: {study_uid}")
            return False
        logger.info(f"✅ Study info retrieved successfully")
        
        logger.info(f"✅ Study info retrieved:")
        logger.info(f"   Patient: {study_info.get('patient_name', 'Unknown')}")
        logger.info(f"   Study Date: {study_info.get('study_date', 'Unknown')}")
        logger.info(f"   Total Instances: {study_info.get('total_instances', 0)}")
        logger.info(f"   Total Series: {study_info.get('total_series', 0)}")
        
        # Save patient and study to database
        study_pk = None
        if insert_patient and insert_study and insert_series and insert_instance:
            try:
                # Initialize database first
                logger.info(f"🔄 Initializing database...")
                from PacsClient.utils.database import init_database
                init_database()
                logger.info(f"✅ Database initialized successfully")
                patient_id = study_info.get('patient_id', 'Unknown')
                patient_name = study_info.get('patient_name', 'Unknown')
                study_date = study_info.get('study_date', '')
                study_description = study_info.get('study_description', '')
                modality = study_info.get('modality', '')
                
                # Insert patient (will return existing if already exists)
                patient_pk = insert_patient(
                    patient_id=patient_id,
                    name=patient_name,
                    birth_date=study_info.get('patient_birth_date'),
                    sex=study_info.get('patient_sex'),
                    age=study_info.get('patient_age')
                )
                logger.info(f"💾 Patient saved to database: {patient_name} (PK: {patient_pk})")
                
                # Insert study (will return existing if already exists)
                study_pk = insert_study(
                    study_uid=study_uid,
                    patient_fk=patient_pk,
                    study_date=study_date,
                    study_description=study_description,
                    modality=modality,
                    number_of_series=study_info.get('total_series', 0),
                    number_of_instances=study_info.get('total_instances', 0),
                    study_path=str(study_path)  # Save study path to database
                )
                logger.info(f"💾 Study saved to database: {study_uid} (PK: {study_pk})")
                logger.info(f"💾 Study path: {study_path}")
                logger.info(f"🔍 Final study_pk value: {study_pk}")
                
            except Exception as e:
                logger.warning(f"⚠️ Database initialization failed (continuing download): {e}")
                study_pk = None
        else:
            logger.info("📝 Database functions not available, skipping database operations")
        
        # Collect all instance numbers from series (simple logic like resumable_simple_downloader.py)
        all_instances = []
        
        if "series" in study_info:
            for series in study_info["series"]:
                if "instances" in series:
                    for instance in series["instances"]:
                        instance_num = int(instance["instance_number"]) if str(instance["instance_number"]).isdigit() else 0
                        instance_uid = instance.get("instance_uid", "")
                        series_uid = series.get("series_uid", "")
                        
                        # Add all instances without duplicate checking (like resumable_simple_downloader.py)
                        all_instances.append({
                            "instance_number": instance_num,
                            "instance_uid": instance_uid if instance_uid else f"{series_uid}_{instance_num}",
                            "series_uid": series_uid,
                            "series_number": series.get("series_number", 0),
                            "series_description": series.get("series_description", ""),
                            "modality": series.get("modality", "")
                        })
        
        if not all_instances:
            logger.error(f"❌ No instances found in study info")
            return False
        
        logger.info(f"📊 Total unique instances to download: {len(all_instances)}")
        
        # Resume logic: Filter out already downloaded instances (like resumable_simple_downloader.py)
        downloaded_count = 0
        downloaded_uids = set()  # Track downloaded instance UIDs to avoid re-downloading
        
        # Database progress tracking (no more .progress file)
        
        # Filter instances that haven't been downloaded yet (check by UID-based naming)
        remaining_instances = []
        for instance_data in all_instances:
            instance_number = instance_data["instance_number"]
            series_number = instance_data["series_number"]
            series_uid = instance_data.get("series_uid", "unknown")
            
            # Create expected filename (simple approach)
            instance_num_int = int(instance_number) if str(instance_number).isdigit() else instance_number
            expected_filename = f"Instance_{instance_num_int:04d}.dcm"
            
            # Check if file exists in the series directory (simple approach)
            try:
                from PacsClient.pacs.patient_tab.utils.utils import check_series_study_exist
                series_path = check_series_study_exist(study_uid, f"{series_number}")
            except Exception as e:
                # Fallback to simple path creation
                series_path = study_path / f"{series_number}"
                series_path.mkdir(parents=True, exist_ok=True)
            
            filepath = Path(series_path) / expected_filename
            file_exists = filepath.exists()
            
            if file_exists:
                downloaded_count += 1
                downloaded_uids.add(f"{series_uid}_{instance_number}")
                logger.debug(f"✅ Found existing file: {expected_filename} in series {series_number}")
            else:
                logger.debug(f"❌ Missing file: {expected_filename} in series {series_number}")
                remaining_instances.append(instance_data)
                logger.debug(f"📝 Added to remaining: Series {series_number}, Instance {instance_number}")
        
        logger.info(f"📊 Total instances: {len(all_instances)}")
        logger.info(f"📊 Already downloaded: {downloaded_count}")
        logger.info(f"📊 Remaining to download: {len(remaining_instances)}")
        
        if len(remaining_instances) == 0:
            logger.info("✅ All files already downloaded!")
            # Mark as completed in database
            if complete_download_progress:
                try:
                    complete_download_progress(study_uid)
                    logger.info(f"💾 Marked as completed in database")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to mark completed in database: {e}")
            return True
        
        if not resume:
            # Clear progress from database if not resuming
            if delete_download_progress:
                try:
                    delete_download_progress(study_uid)
                    logger.info(f"🗑️ Cleared progress from database (resume=False)")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to clear progress from database: {e}")
        
        total_batches = (len(remaining_instances) + batch_size - 1) // batch_size
        logger.info(f"📊 Total batches to process: {total_batches}")
        
        # Process batches sequentially (simpler approach)
        logger.info(f"🔄 Starting sequential batch processing...")
        
        # Process batches by series to avoid server confusion
        # Group remaining instances by series UID
        series_groups = {}
        for inst in remaining_instances:
            series_uid = inst.get("series_uid", "unknown")
            if series_uid not in series_groups:
                series_groups[series_uid] = []
            series_groups[series_uid].append(inst)
        
        logger.info(f"📊 Grouped instances into {len(series_groups)} series")
        for series_uid, instances in series_groups.items():
            series_num = instances[0].get("series_number", "unknown")
            logger.info(f"   Series {series_num} ({series_uid[:30]}...): {len(instances)} instances")
        
        batch_number = 0
        total_batches = sum((len(instances) + batch_size - 1) // batch_size for instances in series_groups.values())
        logger.info(f"📊 Total batches to process: {total_batches}")
        
        # Process each series separately
        for series_uid, series_instances in series_groups.items():
            series_num = series_instances[0].get("series_number", "unknown")
            logger.info(f"🔄 Processing Series {series_num} ({len(series_instances)} instances)")
            
            # Process this series in batches
            for i in range(0, len(series_instances), batch_size):
                batch = series_instances[i:i + batch_size]
                batch_number += 1
                
                logger.info(f"📦 Processing batch {batch_number}/{total_batches} - Series {series_num} ({len(batch)} instances)")
                
                # Extract instance numbers for this batch
                instance_numbers = [inst["instance_number"] for inst in batch]
                
                # Log detailed batch info for debugging
                logger.info(f"🔄 Downloading batch {batch_number} with instances: {instance_numbers} from Series {series_num}")
                for j, inst in enumerate(batch):
                    logger.debug(f"   Batch item {j+1}: Instance {inst['instance_number']} from Series {inst['series_number']}")
                
                # Download batch using series UID to avoid confusion
                batch_data = self.download_batch_by_instance_numbers(study_uid, instance_numbers, compression, series_uid)
                
                if not batch_data or "instances" not in batch_data:
                    logger.error(f"❌ Batch {batch_number} failed - no instances returned")
                    
                    # Handle potential connection issues
                    if not self.check_connection_health():
                        logger.warning("⚠️ Connection health check failed after batch failure")
                        self.handle_connection_loss()
                        
                        # Try to reconnect for next batch
                        if not self.connect_with_retry():
                            logger.error("❌ Failed to reconnect after connection loss")
                            break
                    
                    continue
                
                batch_instances = batch_data["instances"]
                logger.info(f"✅ Batch {batch_number} received {len(batch_instances)} instances")
                
                # Process instances in batch
                for j, instance_data in enumerate(batch_instances):
                    try:
                        if not instance_data.get("dicom_data"):
                            logger.warning(f"⚠️ No data for instance {j+1}")
                            continue
                        
                        # Use requested instance number for naming
                        requested_instance_num = instance_numbers[j] if j < len(instance_numbers) else j + 1
                        
                        # اعتبارسنجی و پردازش داده‌های DICOM
                        dicom_data = self.validate_and_process_dicom_data(
                            instance_data.get("dicom_data"), 
                            requested_instance_num, 
                            compression
                        )
                        if dicom_data is None:
                            logger.error(f"❌ Invalid DICOM data for instance {requested_instance_num}")
                            continue
                        
                        # Decompress if needed
                        if instance_data.get("is_compressed", False) and compression == "gzip":
                            try:
                                dicom_data = gzip.decompress(dicom_data)
                            except Exception as e:
                                logger.warning(f"⚠️ Gzip decompression failed: {e}")
                                pass
                        
                        # Extract series info from DICOM data first
                        series_info = None
                        
                        if PYDICOM_AVAILABLE:
                            try:
                                # Read DICOM header to get series information
                                dicom_stream = BytesIO(dicom_data)
                                ds = _safe_dcmread(dicom_stream, stop_before_pixels=True)
                                
                                actual_instance_num = getattr(ds, 'InstanceNumber', requested_instance_num)
                                
                                # Extract comprehensive series metadata
                                series_info = {
                                    "series_number": getattr(ds, 'SeriesNumber', 0),
                                    "series_uid": getattr(ds, 'SeriesInstanceUID', ''),
                                    "series_description": getattr(ds, 'SeriesDescription', ''),
                                    "modality": getattr(ds, 'Modality', ''),
                                    "instance_number": actual_instance_num,
                                    "protocol_name": getattr(ds, 'ProtocolName', ''),
                                    "body_part_examined": getattr(ds, 'BodyPartExamined', ''),
                                    "manufacturer": getattr(ds, 'Manufacturer', ''),
                                    "institution_name": getattr(ds, 'InstitutionName', ''),
                                    "slice_thickness": getattr(ds, 'SliceThickness', None)
                                }
                                
                                logger.debug(f"✅ Extracted complete series info from DICOM:")
                                logger.debug(f"   Series: {series_info['series_number']} - {series_info['series_description']}")
                                logger.debug(f"   Modality: {series_info['modality']}")
                                logger.debug(f"   Protocol: {series_info['protocol_name']}")
                                logger.debug(f"   Body Part: {series_info['body_part_examined']}")
                                
                            except Exception as e:
                                logger.warning(f"⚠️ Could not read DICOM header for instance {requested_instance_num}: {e}")
                                series_info = None  # Only reset if reading failed
                        
                        # Fallback to batch data if DICOM reading failed or pydicom not available
                        if not series_info:
                            logger.debug(f"🔄 Falling back to batch data for instance {requested_instance_num}")
                            for inst in batch:
                                if inst["instance_number"] == requested_instance_num:
                                    series_info = inst
                                    logger.debug(f"✅ Found series info in unique batch data for instance {requested_instance_num}")
                                    break
                        
                        if not series_info:
                            # Last resort: use default values
                            series_info = {
                                "series_number": 1,  # Default to series 1
                                "series_uid": f"unknown_series_{requested_instance_num}",
                                "series_description": "",
                                "modality": "",
                                "instance_number": requested_instance_num
                            }
                            logger.warning(f"⚠️ Using default series info for instance {requested_instance_num}")
                        
                        if not series_info:
                            logger.error(f"❌ Could not determine series info for instance {requested_instance_num}")
                            continue
                        
                        # Simple filename generation (like working code)
                        actual_instance_num = series_info.get("instance_number", requested_instance_num)
                        filename = f"Instance_{actual_instance_num:04d}.dcm"
                        logger.debug(f"📝 Generated filename: {filename} (Instance: {actual_instance_num})")
                        
                        # Simple series directory structure (like working code)
                        series_num = int(series_info["series_number"]) if series_info["series_number"] else 0
                        
                        # Create simple series directory (just the number)
                        try:
                            from PacsClient.pacs.patient_tab.utils.utils import check_series_study_exist
                            series_path = check_series_study_exist(study_uid, f"{series_num}")
                            logger.debug(f"✅ Series path for {series_num}: {series_path}")
                        except Exception as e:
                            logger.error(f"❌ Error with check_series_study_exist for series {series_num}: {e}")
                            # Fallback to simple path creation
                            series_path = study_path / f"{series_num}"
                            series_path.mkdir(parents=True, exist_ok=True)
                            logger.debug(f"📁 Created simple series directory: {series_path}")
                        
                        filepath = Path(series_path) / filename
                        
                        # Save DICOM file
                        if self.safe_save_dicom_file(filepath, dicom_data, requested_instance_num):
                            # Update counters
                            downloaded_uids.add(f"{series_info['series_uid']}_{requested_instance_num}")
                            downloaded_count += 1
                            
                            logger.info(f"✅ Saved: {filename} ({len(dicom_data)} bytes)")
                            
                            # Call progress callback
                            if progress_callback:
                                try:
                                    progress_percent = (downloaded_count / len(all_instances)) * 100
                                    progress_callback(downloaded_count, len(all_instances), progress_percent)
                                except Exception as e:
                                    logger.warning(f"⚠️ Progress callback error: {e}")
                            
                            # # Save series and instance to database
                            # if study_pk and insert_series and insert_instance:
                            #     try:
                            #         # Extract ALL series metadata from series_info (extracted from DICOM)
                            #         series_description = series_info.get('series_description', '') if series_info else ''
                            #         series_modality = series_info.get('modality', '') if series_info else ''
                            #         protocol_name = series_info.get('protocol_name', '') if series_info else ''
                            #         body_part_examined = series_info.get('body_part_examined', '') if series_info else ''
                            #         manufacturer = series_info.get('manufacturer', '') if series_info else ''
                            #         institution_name = series_info.get('institution_name', '') if series_info else ''
                            #         slice_thickness = series_info.get('slice_thickness', None) if series_info else None
                            #
                            #         # Convert slice_thickness to string if it exists
                            #         series_thk = str(slice_thickness) if slice_thickness is not None else None
                            #
                            #         # Insert series with COMPLETE metadata (will return existing if already exists)
                            #         series_pk = insert_series(
                            #             series_uid=series_info['series_uid'],
                            #             study_fk=study_pk,
                            #             series_number=str(series_num),
                            #             series_description=series_description,
                            #             modality=series_modality,
                            #             protocol_name=protocol_name,
                            #             body_part_examined=body_part_examined,
                            #             manufacturer=manufacturer,
                            #             institution_name=institution_name,
                            #             series_thk=series_thk,
                            #             image_count=1,
                            #             series_path=str(series_path)  # Save series path
                            #         )
                            #         logger.debug(f"💾 Series saved with complete metadata:")
                            #         logger.debug(f"   UID: {series_info['series_uid']}")
                            #         logger.debug(f"   Description: {series_description}")
                            #         logger.debug(f"   Modality: {series_modality}")
                            #         logger.debug(f"   Protocol: {protocol_name}")
                            #
                            #         # Extract COMPLETE DICOM metadata from saved file
                            #         rows, columns = None, None
                            #         window_width, window_center = 127.5, 255.0
                            #         image_position_patient = None
                            #         image_orientation_patient = None
                            #         pixel_spacing = None
                            #
                            #         try:
                            #             import pydicom
                            #             dcm = pydicom.dcmread(filepath, stop_before_pixels=True)
                            #
                            #             # ✅ Extract image dimensions
                            #             if hasattr(dcm, 'Rows'):
                            #                 rows = int(dcm.Rows)
                            #             if hasattr(dcm, 'Columns'):
                            #                 columns = int(dcm.Columns)
                            #
                            #             # ✅ Extract window level settings (WW/WL)
                            #             if hasattr(dcm, 'WindowWidth'):
                            #                 ww = dcm.WindowWidth
                            #                 window_width = float(ww[0]) if isinstance(ww, (list, tuple)) else float(ww)
                            #
                            #             if hasattr(dcm, 'WindowCenter'):
                            #                 wc = dcm.WindowCenter
                            #                 window_center = float(wc[0]) if isinstance(wc, (list, tuple)) else float(wc)
                            #
                            #             # ✅ Extract Image Orientation Patient (CRITICAL for 3D reconstruction)
                            #             if hasattr(dcm, 'ImageOrientationPatient'):
                            #                 # This is a list of 6 values: [row_x, row_y, row_z, col_x, col_y, col_z]
                            #                 image_orientation_patient = list(dcm.ImageOrientationPatient)
                            #                 logger.debug(f"📐 Image Orientation: {image_orientation_patient}")
                            #
                            #             # ✅ Extract Image Position Patient (for slice location)
                            #             if hasattr(dcm, 'ImagePositionPatient'):
                            #                 # This is a list of 3 values: [x, y, z]
                            #                 image_position_patient = list(dcm.ImagePositionPatient)
                            #
                            #             # ✅ Extract Pixel Spacing (for real-world measurements)
                            #             if hasattr(dcm, 'PixelSpacing'):
                            #                 # This is a list of 2 values: [row_spacing, col_spacing]
                            #                 pixel_spacing = list(dcm.PixelSpacing)
                            #
                            #             logger.debug(f"📊 Complete metadata extracted:")
                            #             logger.debug(f"   Size: {rows}x{columns}")
                            #             logger.debug(f"   WW/WL: {window_width}/{window_center}")
                            #             logger.debug(f"   Orientation: {image_orientation_patient}")
                            #             logger.debug(f"   Position: {image_position_patient}")
                            #             logger.debug(f"   Spacing: {pixel_spacing}")
                            #
                            #         except Exception as e:
                            #             logger.warning(f"⚠️ Could not extract complete DICOM metadata: {e}")
                            #             import traceback
                            #             logger.debug(traceback.format_exc())
                            #
                            #         # ✅ Insert instance with COMPLETE metadata
                            #         insert_instance(
                            #             sop_uid=f"{series_info['series_uid']}_{requested_instance_num}",
                            #             series_fk=series_pk,
                            #             instance_path=str(filepath),
                            #             instance_number=requested_instance_num,
                            #             rows=rows,
                            #             columns=columns,
                            #             window_width=window_width,
                            #             window_center=window_center,
                            #             image_position_patient=image_position_patient,
                            #             image_orientation_patient=image_orientation_patient,
                            #             pixel_spacing=pixel_spacing
                            #         )
                            #
                            #     except Exception as e:
                            #         logger.warning(f"⚠️ Database save failed for instance {requested_instance_num}: {e}")
                        else:
                            logger.error(f"❌ Failed to save: {filename}")
                            continue
                    
                    except Exception as e:
                        logger.error(f"❌ Error processing instance {j+1}: {e}")
                        continue
                
                logger.info(f"📦 Batch {batch_number} completed")
                
                # Debug: Check what files were actually saved after this batch
                logger.info(f"🔍 Checking files saved after batch {batch_number}:")
                try:
                    for series_dir in sorted(study_path.iterdir()):
                        if series_dir.is_dir():
                            dcm_files = list(series_dir.glob('*.dcm'))
                            if dcm_files:
                                logger.info(f"   📁 {series_dir.name}: {len(dcm_files)} files")
                                # Show first few files in each directory
                                for dcm_file in sorted(dcm_files)[:3]:
                                    try:
                                        import pydicom
                                        ds = _safe_dcmread(dcm_file, stop_before_pixels=True)
                                        actual_instance = getattr(ds, 'InstanceNumber', 'N/A')
                                        actual_series = getattr(ds, 'SeriesNumber', 'N/A')
                                        logger.info(f"      {dcm_file.name}: Instance={actual_instance}, Series={actual_series}")
                                    except Exception as e:
                                        logger.warning(f"      {dcm_file.name}: Error reading - {e}")
                                if len(dcm_files) > 3:
                                    logger.info(f"      ... and {len(dcm_files) - 3} more files")
                except Exception as e:
                    logger.warning(f"⚠️ Error checking saved files: {e}")
        
        logger.info(f"✅ All batches processed successfully")
        
        # Final count of downloaded files
        final_downloaded = downloaded_count  # This is the actual count of downloaded files
        logger.info(f"✅ Download completed: {final_downloaded}/{len(all_instances)} files")
        
        # Save final progress to database
        if insert_download_progress:
            try:
                progress_percent = (final_downloaded / len(all_instances)) * 100
                status = 'completed' if final_downloaded >= len(all_instances) else 'in_progress'
                insert_download_progress(
                    study_uid=study_uid,
                    downloaded_count=final_downloaded,
                    total_instances=len(all_instances),
                    progress_percent=progress_percent,
                    current_batch=total_batches,
                    total_batches=total_batches,
                    status=status
                )
                logger.info(f"💾 Final progress saved to database: {final_downloaded}/{len(all_instances)} ({status})")
            except Exception as e:
                logger.warning(f"⚠️ Failed to save final progress to database: {e}")
        
        # Mark as completed in database if download is complete
        if final_downloaded >= len(all_instances):
            if complete_download_progress:
                try:
                    complete_download_progress(study_uid)
                    logger.info(f"💾 Marked as completed in database (download complete)")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to mark completed in database: {e}")
            
            # Generate thumbnails after download completion
            try:
                logger.info(f"🎨 Starting thumbnail generation for study: {study_uid}")
                self._generate_thumbnails_for_study(study_uid, study_path)
                logger.info(f"✅ Thumbnail generation completed for study: {study_uid}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to generate thumbnails: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        
        return final_downloaded > 0
    
    def _generate_thumbnails_for_study(self, study_uid: str, study_path: Path):
        """
        Generate thumbnails for all series in a study after download completion.
        
        Args:
            study_uid: Study Instance UID
            study_path: Path to downloaded study directory
        """
        try:
            import numpy as np
            from PIL import Image
            from pathlib import Path
            
            # Get thumbnails directory
            try:
                from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
            except ImportError:
                # Fallback to local thumbnails directory
                THUMBNAIL_PATH = Path("./thumbnails")
            
            thumbnails_dir = THUMBNAIL_PATH / study_uid
            thumbnails_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"📁 Thumbnails directory: {thumbnails_dir}")
            logger.info(f"📁 Study path: {study_path}")
            
            # Get all series directories
            series_dirs = [d for d in study_path.iterdir() if d.is_dir()]
            logger.info(f"🔍 Found {len(series_dirs)} series directories")
            
            generated_count = 0
            for series_dir in sorted(series_dirs):
                try:
                    # Get series number from directory name
                    series_num = series_dir.name
                    logger.debug(f"📸 Processing series: {series_num}")
                    
                    # Get all DICOM files in this series
                    dcm_files = sorted(list(series_dir.glob('*.dcm')))
                    if not dcm_files:
                        logger.warning(f"⚠️ No DICOM files found in {series_dir}")
                        continue
                    
                    logger.debug(f"   Found {len(dcm_files)} DICOM files")
                    
                    # Get middle file for thumbnail
                    middle_index = len(dcm_files) // 2
                    middle_file = dcm_files[middle_index]
                    
                    # Generate thumbnail from middle slice
                    thumbnail_path = self._generate_thumbnail_from_dicom(
                        middle_file, 
                        thumbnails_dir, 
                        series_num
                    )
                    
                    if thumbnail_path:
                        generated_count += 1
                        logger.info(f"✅ Generated thumbnail for series {series_num}: {thumbnail_path}")
                        
                        # Update database with thumbnail path
                        try:
                            from PacsClient.utils.db_manager import update_series_thumbnail_path, find_series_pk
                            
                            # Find series_pk by querying with study_uid and series_number
                            from PacsClient.utils.database import get_connection_database
                            conn = get_connection_database()
                            cur = conn.cursor()
                            cur.execute("""
                                SELECT s.series_pk 
                                FROM series s
                                JOIN studies st ON s.study_fk = st.study_pk
                                WHERE st.study_uid = ? AND s.series_number = ?
                            """, (study_uid, series_num))
                            result = cur.fetchone()
                            
                            if result:
                                series_pk = result[0]
                                update_series_thumbnail_path(series_pk, str(thumbnail_path))
                                logger.debug(f"💾 Updated database with thumbnail path for series_pk {series_pk}")
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to update thumbnail path in database: {e}")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Failed to generate thumbnail for series {series_dir.name}: {e}")
                    continue
            
            logger.info(f"✅ Generated {generated_count}/{len(series_dirs)} thumbnails")
            return generated_count > 0
            
        except Exception as e:
            logger.error(f"❌ Error in thumbnail generation: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return False
    
    def _generate_thumbnail_from_dicom(self, dcm_file: Path, output_dir: Path, series_name: str) -> Path:
        return
        # """
        # Generate a thumbnail image from a DICOM file.
        #
        # Args:
        #     dcm_file: Path to DICOM file
        #     output_dir: Directory to save thumbnail
        #     series_name: Name for the thumbnail file
        #
        # Returns:
        #     Path to generated thumbnail or None if failed
        # """
        # try:
        #     import pydicom
        #     import numpy as np
        #     from PIL import Image
        #
        #     # Read DICOM file (force=True to handle files without standard DICOM header)
        #     ds = pydicom.dcmread(dcm_file, force=True)
        #
        #     # Get pixel data
        #     pixel_array = ds.pixel_array
        #
        #     # Apply window/level if available
        #     if hasattr(ds, 'WindowWidth') and hasattr(ds, 'WindowCenter'):
        #         ww = ds.WindowWidth
        #         wc = ds.WindowCenter
        #
        #         # Handle multiple window values (take first)
        #         if isinstance(ww, (list, tuple)):
        #             ww = float(ww[0])
        #         else:
        #             ww = float(ww)
        #
        #         if isinstance(wc, (list, tuple)):
        #             wc = float(wc[0])
        #         else:
        #             wc = float(wc)
        #
        #         # Apply window/level
        #         lower = wc - 0.5 - (ww - 1) / 2
        #         upper = wc - 0.5 + (ww - 1) / 2
        #         pixel_array = np.clip(pixel_array, lower, upper)
        #         pixel_array = ((pixel_array - lower) / (upper - lower)) * 255.0
        #     else:
        #         # Auto-scale to 0-255
        #         pixel_array = pixel_array - pixel_array.min()
        #         if pixel_array.max() > 0:
        #             pixel_array = (pixel_array / pixel_array.max()) * 255.0
        #
        #     # Convert to uint8
        #     pixel_array = pixel_array.astype(np.uint8)
        #
        #     # Create PIL image
        #     img = Image.fromarray(pixel_array)
        #
        #     # Resize to thumbnail size (256x256)
        #     img.thumbnail((256, 256), Image.Resampling.LANCZOS)
        #
        #     # Save thumbnail
        #     thumbnail_path = output_dir / f"{series_name}.jpg"
        #     img.save(thumbnail_path, "JPEG", quality=85, optimize=True)
        #
        #     return thumbnail_path
        #
        # except Exception as e:
        #     logger.warning(f"⚠️ Failed to generate thumbnail from {dcm_file.name}: {e}")
        #     return None
    
    def download_study_resumable(self, study_uid: str, batch_size: int = 10,
                               compression: str = "gzip", resume: bool = True,
                               progress_callback: Optional[Callable] = None) -> bool:
        """
        Download study with resumable capability (wrapper for UI compatibility)
        
        Args:
            study_uid (str): Study Instance UID
            batch_size (int): Number of instances per batch
            compression (str): Compression type
            resume (bool): Whether to resume existing download
            progress_callback (callable): Progress callback function
            
        Returns:
            bool: True if download successful, False otherwise
        """
        logger.info(f"🔄 Starting resumable download for study: {study_uid}")
        
        # Use the working batch download method
        return self.download_study_batch_like_working_code(
            study_uid=study_uid,
            output_dir="./downloads",
            batch_size=batch_size,
            compression=compression,
            resume=resume,
            progress_callback=progress_callback
        )
    
    def resume_download(self, study_uid: str, output_dir: str, 
                       progress_callback: Optional[Callable] = None) -> bool:
        """
        Resume a previously interrupted download
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            progress_callback (callable): Progress callback function
            
        Returns:
            bool: True if resume successful, False otherwise
        """
        logger.info(f"🔄 Resuming download for study: {study_uid}")
        
        status = self.get_download_status(study_uid, output_dir)
        
        if status["status"] == "completed":
            logger.info("✅ Download already completed")
            return True
        elif status["status"] == "not_started":
            logger.info("📝 No previous download found, starting new download")
            return self.get_study_dicom_files_resumable(
                study_uid, output_dir, resume=True, progress_callback=progress_callback
            )
        else:
            logger.info(f"🔄 Resuming from {status['progress_percent']:.1f}% complete")
            return self.get_study_dicom_files_resumable(
                study_uid, output_dir, resume=True, progress_callback=progress_callback
            )
    
    def is_connected(self) -> bool:
        """
        Check if client is connected to server
        
        Returns:
            bool: True if connected, False otherwise
        """
        return self.connected and self.socket is not None
    
    def check_connection_health(self) -> bool:
        """
        Check if connection is healthy by testing socket state
        
        Returns:
            bool: True if connection is healthy, False otherwise
        """
        if not self.is_connected():
            return False
        
        try:
            # Simple socket state check instead of sending data
            # This avoids interfering with ongoing operations
            
            # Check if socket is still connected by testing send buffer
            self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            
            # Try a non-blocking peek to see if connection is alive
            original_timeout = self.socket.gettimeout()
            self.socket.settimeout(0.1)  # Very short timeout
            
            try:
                # Try to peek at any available data without consuming it
                data = self.socket.recv(1, socket.MSG_PEEK)
                # If we get here without exception, connection seems alive
                logger.debug("✅ Connection health check passed")
                return True
            except socket.timeout:
                # Timeout is expected for healthy connection with no pending data
                logger.debug("✅ Connection health check passed (timeout expected)")
                return True
            except (ConnectionResetError, ConnectionAbortedError, OSError) as e:
                logger.warning(f"⚠️ Connection health check failed - connection lost: {e}")
                return False
            finally:
                # Restore original timeout
                self.socket.settimeout(original_timeout)
                
        except Exception as e:
            logger.warning(f"⚠️ Connection health check failed: {e}")
            return False
    
    def handle_connection_loss(self):
        """
        Handle connection loss by cleaning up and preparing for reconnection
        """
        logger.warning("🔄 Handling connection loss...")
        
        self.connected = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        # Reset failure counters
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        
        logger.info(f"🔄 Connection cleaned up, consecutive failures: {self.consecutive_failures}")
    
    def download_batch_parallel(self, study_uid: str, batch_list: List[Dict], compression: str = "gzip") -> List[Dict]:
        """
        Download multiple batches in parallel for maximum bandwidth utilization
        
        Args:
            study_uid (str): Study Instance UID
            batch_list (list): List of batch configurations
            compression (str): Compression type
            
        Returns:
            list: List of batch results
        """
        if not self.parallel_downloads or not self.connection_pool:
            logger.warning("⚠️ Parallel downloads not enabled, falling back to sequential")
            return []
        
        logger.info(f"🚀 Starting parallel download of {len(batch_list)} batches")
        
        def download_single_batch(batch_config):
            """Download a single batch using connection pool"""
            client = None
            try:
                # Get connection from pool
                client = self.connection_pool.get_connection(timeout=30)
                if not client:
                    logger.error("❌ Failed to get connection from pool")
                    return None
                
                # Download batch
                instance_numbers = batch_config['instance_numbers']
                series_uid = batch_config.get('series_uid')
                batch_number = batch_config.get('batch_number', 0)
                
                logger.debug(f"📦 Parallel batch {batch_number}: downloading {len(instance_numbers)} instances")
                
                result = client.download_batch_by_instance_numbers(
                    study_uid, instance_numbers, compression, series_uid
                )
                
                if result:
                    result['batch_number'] = batch_number
                    result['series_uid'] = series_uid
                    logger.debug(f"✅ Parallel batch {batch_number} completed")
                else:
                    logger.warning(f"⚠️ Parallel batch {batch_number} failed")
                
                return result
                
            except Exception as e:
                logger.error(f"❌ Error in parallel batch download: {e}")
                return None
            finally:
                # Return connection to pool
                if client:
                    self.connection_pool.return_connection(client)
        
        # Execute batches in parallel
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_parallel_batches) as executor:
            # Submit all batch downloads
            future_to_batch = {
                executor.submit(download_single_batch, batch_config): batch_config
                for batch_config in batch_list
            }
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_batch, timeout=self.batch_timeout):
                batch_config = future_to_batch[future]
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                        logger.debug(f"✅ Collected result for batch {batch_config.get('batch_number', '?')}")
                    else:
                        logger.warning(f"⚠️ No result for batch {batch_config.get('batch_number', '?')}")
                except Exception as e:
                    logger.error(f"❌ Batch {batch_config.get('batch_number', '?')} generated exception: {e}")
        
        logger.info(f"🎯 Parallel download completed: {len(results)}/{len(batch_list)} batches successful")
        return results
    
    def _fast_decompress(self, compressed_data: bytes) -> Optional[bytes]:
        """
        Fast decompression optimized for high bandwidth mode
        
        Args:
            compressed_data (bytes): Compressed data
            
        Returns:
            bytes or None: Decompressed data or None if failed
        """
        try:
            # Use streaming decompression for large data
            if len(compressed_data) > 1024 * 1024:  # 1MB
                decompressor = gzip.GzipFile(fileobj=BytesIO(compressed_data))
                chunks = []
                while True:
                    chunk = decompressor.read(self.chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b''.join(chunks)
            else:
                # Standard decompression for smaller data
                return gzip.decompress(compressed_data)
        except Exception as e:
            logger.warning(f"⚠️ Fast decompression failed: {e}")
            return None
    
    def monitor_bandwidth(self, start_time: float, bytes_transferred: int) -> Dict[str, float]:
        """
        Monitor bandwidth usage and performance
        
        Args:
            start_time (float): Start time of transfer
            bytes_transferred (int): Number of bytes transferred
            
        Returns:
            dict: Bandwidth statistics
        """
        elapsed_time = time.time() - start_time
        if elapsed_time > 0:
            bandwidth_bps = bytes_transferred / elapsed_time
            bandwidth_mbps = bandwidth_bps / (1024 * 1024)
            
            return {
                "elapsed_time": elapsed_time,
                "bytes_transferred": bytes_transferred,
                "bandwidth_bps": bandwidth_bps,
                "bandwidth_mbps": bandwidth_mbps,
                "efficiency": min(100, (bandwidth_mbps / 100) * 100)  # Assume 100Mbps as reference
            }
        return {"elapsed_time": 0, "bytes_transferred": 0, "bandwidth_bps": 0, "bandwidth_mbps": 0, "efficiency": 0}
    
    def download_study_with_smartdl_optimization(self, study_uid: str, output_dir: str = "./downloads",
                                                batch_size: int = 10, compression: str = "gzip",
                                                resume: bool = True, progress_callback: Optional[Callable] = None) -> bool:
        """
        Download study using pySmartDL-inspired optimizations
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            batch_size (int): Initial batch size (will be optimized)
            compression (str): Compression type
            resume (bool): Whether to resume from previous download
            progress_callback (callable): Progress callback function
            
        Returns:
            bool: True if download successful, False otherwise
        """
        logger.info(f"🚀 Starting SmartDL-optimized download for study: {study_uid}")
        
        # Get study info
        study_info = self.get_study_info(study_uid)
        if not study_info:
            logger.error(f"❌ Failed to get study info for: {study_uid}")
            return False
        
        total_instances = study_info.get('total_instances', 0)
        if total_instances == 0:
            logger.warning(f"⚠️ No instances found for study: {study_uid}")
            return False
        
        # Estimate total size (rough estimation)
        estimated_size_per_instance = 500 * 1024  # 500KB average
        estimated_total_size = total_instances * estimated_size_per_instance
        
        # Start advanced progress tracking (if available)
        if self.progress_tracker:
            self.progress_tracker.start_tracking(estimated_total_size)
            
            # Add progress callback
            if progress_callback:
                self.progress_tracker.add_callback(
                    lambda stats: progress_callback(stats.downloaded_size, stats.total_size, stats.progress_percent)
                )
        
        try:
            # Create optimized batch plan
            batch_plan = self._create_optimized_batch_plan(study_info, batch_size)
            
            if self.parallel_downloads and self.connection_pool:
                # Use parallel download with optimization
                return self._download_with_parallel_optimization(
                    study_uid, batch_plan, compression, output_dir
                )
            else:
                # Use sequential download with optimization
                return self._download_with_sequential_optimization(
                    study_uid, batch_plan, compression, output_dir
                )
                
        finally:
            # Stop progress tracking (if available)
            if self.progress_tracker:
                self.progress_tracker.stop_tracking()
    
    def _create_optimized_batch_plan(self, study_info: Dict, initial_batch_size: int) -> List[Dict]:
        """Create optimized batch plan based on study structure"""
        batch_plan = []
        batch_number = 0
        
        # Group by series for better organization
        if "series" in study_info:
            for series in study_info["series"]:
                series_uid = series.get("series_uid", "")
                series_instances = series.get("instances", [])
                
                # Create batches for this series
                for i in range(0, len(series_instances), initial_batch_size):
                    batch_instances = series_instances[i:i + initial_batch_size]
                    instance_numbers = [inst["instance_number"] for inst in batch_instances]
                    
                    batch_plan.append({
                        "batch_number": batch_number,
                        "series_uid": series_uid,
                        "instance_numbers": instance_numbers,
                        "estimated_size": len(instance_numbers) * 500 * 1024  # 500KB per instance
                    })
                    batch_number += 1
        
        logger.info(f"📋 Created optimized batch plan: {len(batch_plan)} batches")
        return batch_plan
    
    def _download_with_parallel_optimization(self, study_uid: str, batch_plan: List[Dict], 
                                           compression: str, output_dir: str) -> bool:
        """Download with parallel optimization using pySmartDL concepts"""
        logger.info(f"🚀 Starting parallel optimized download ({len(batch_plan)} batches)")
        
        downloaded_count = 0
        total_bytes = 0
        start_time = time.time()
        
        # Process batches in groups for optimal performance
        optimal_threads = self.thread_optimizer.current_thread_count if self.thread_optimizer else self.max_parallel_batches
        
        for i in range(0, len(batch_plan), optimal_threads):
            batch_group = batch_plan[i:i + optimal_threads]
            
            # Check if we should optimize thread count (if optimizer available)
            if self.thread_optimizer and self.thread_optimizer.should_optimize():
                new_thread_count, reason = self.thread_optimizer.optimize_thread_count()
                if new_thread_count != optimal_threads:
                    logger.info(f"🔧 Optimizing threads: {optimal_threads} → {new_thread_count} ({reason})")
                    optimal_threads = new_thread_count
            
            # Download batch group in parallel
            results = self.download_batch_parallel(study_uid, batch_group, compression)
            
            # Process results and update progress
            for result in results:
                if result and "instances" in result:
                    batch_downloaded = len(result["instances"])
                    downloaded_count += batch_downloaded
                    
                    # Estimate bytes (rough calculation)
                    batch_bytes = batch_downloaded * 500 * 1024
                    total_bytes += batch_bytes
                    
                    # Update progress tracker (if available)
                    if self.progress_tracker:
                        self.progress_tracker.update_progress(total_bytes)
                    
                    # Update thread optimizer (if available)
                    if self.thread_optimizer:
                        batch_number = result.get("batch_number", 0)
                        self.thread_optimizer.update_thread_performance(
                            batch_number, batch_bytes, error_occurred=False
                        )
            
            # Small delay between batch groups
            time.sleep(0.2)
        
        # Final statistics
        total_time = time.time() - start_time
        
        logger.info(f"✅ Parallel optimized download completed:")
        logger.info(f"   Downloaded: {downloaded_count} instances")
        logger.info(f"   Total time: {total_time:.2f} seconds")
        
        if self.progress_tracker:
            final_stats = self.progress_tracker.get_stats()
            logger.info(f"   Average speed: {final_stats.average_speed / (1024*1024):.2f} MB/s")
        
        return downloaded_count > 0
    
    def _download_with_sequential_optimization(self, study_uid: str, batch_plan: List[Dict], 
                                             compression: str, output_dir: str) -> bool:
        """Download with sequential optimization using pySmartDL concepts"""
        logger.info(f"🔄 Starting sequential optimized download ({len(batch_plan)} batches)")
        
        downloaded_count = 0
        total_bytes = 0
        
        for batch_config in batch_plan:
            batch_number = batch_config["batch_number"]
            instance_numbers = batch_config["instance_numbers"]
            series_uid = batch_config.get("series_uid")
            
            # Register this batch with thread optimizer (if available)
            if self.thread_optimizer:
                self.thread_optimizer.register_thread(batch_number)
            
            # Download batch
            start_time = time.time()
            result = self.download_batch_by_instance_numbers(
                study_uid, instance_numbers, compression, series_uid
            )
            
            if result and "instances" in result:
                batch_downloaded = len(result["instances"])
                downloaded_count += batch_downloaded
                
                # Calculate performance metrics
                batch_time = time.time() - start_time
                batch_bytes = batch_downloaded * 500 * 1024  # Estimate
                total_bytes += batch_bytes
                
                # Update progress tracker (if available)
                if self.progress_tracker:
                    self.progress_tracker.update_progress(total_bytes)
                
                # Update thread optimizer (if available)
                if self.thread_optimizer:
                    self.thread_optimizer.update_thread_performance(
                        batch_number, batch_bytes, error_occurred=False
                    )
                
                logger.info(f"✅ Batch {batch_number}: {batch_downloaded} instances in {batch_time:.2f}s")
            else:
                # Mark as error (if optimizer available)
                if self.thread_optimizer:
                    self.thread_optimizer.update_thread_performance(
                        batch_number, 0, error_occurred=True
                    )
                logger.error(f"❌ Batch {batch_number} failed")
        
        return downloaded_count > 0
    
    def is_connected(self) -> bool:
        """
        Check if connected to the server
        
        Returns:
            bool: True if connected, False otherwise
        """
        with self.lock:
            return self.connected and self.socket is not None
    
    def get_connection_info(self) -> Dict[str, Any]:
        """
        Get connection information
        
        Returns:
            dict: Connection information
        """
        return {
            "host": self.host,
            "port": self.port,
            "connected": self.connected,
            "timeout": self.timeout
        }
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()
    
    def __del__(self):
        """Destructor to ensure socket is closed"""
        try:
            self.disconnect()
        except:
            pass


# Global instance for UI integration
_global_download_manager = None

def get_download_manager():
    """
    Get or create global download manager instance for UI integration
    
    Returns:
        ResumableDicomSocketClient: Global download manager instance
    """
    global _global_download_manager
    
    if _global_download_manager is None:
        logger.info("🔧 Creating new global download manager instance")
        _global_download_manager = ResumableDicomSocketClient()
        
        # Try to connect
        if not _global_download_manager.connect():
            logger.warning("⚠️ Failed to connect global download manager to server")
        else:
            logger.info("✅ Global download manager connected successfully")
    
    return _global_download_manager


# # Example usage and testing
# if __name__ == "__main__":
#     import argparse
#
#     def progress_callback(downloaded, total, percent):
#         """Example progress callback"""
#         print(f"📊 Progress: {downloaded}/{total} ({percent:.1f}%)")
#
#     def main():
#         parser = argparse.ArgumentParser(description="Resumable DICOM Download Client")
#         parser.add_argument("study_uid", help="Study Instance UID")
#         parser.add_argument("--output_dir", default="./downloads", help="Output directory")
#         parser.add_argument("--batch_size", type=int, default=10, help="Batch size")
#         parser.add_argument("--compression", default="gzip", help="Compression type")
#         parser.add_argument("--resume_only", action="store_true", help="Only resume existing download")
#         parser.add_argument("--no_resume", action="store_true", help="Don't resume, start fresh")
#         parser.add_argument("--status", action="store_true", help="Check download status only")
#
#         args = parser.parse_args()
#
#         client = ResumableDicomSocketClient()
#
#         try:
#             if not client.connect():
#                 print("❌ Failed to connect to server")
#                 return False
#
#             if args.status:
#                 # Check status only
#                 status = client.get_download_status(args.study_uid, args.output_dir)
#                 print(f"📊 Status: {status['status']}")
#                 print(f"📊 Progress: {status['progress_percent']:.1f}%")
#                 print(f"📊 Downloaded: {status['downloaded_count']}/{status['total_instances']}")
#                 if status.get('last_update'):
#                     print(f"📊 Last update: {status['last_update']}")
#                 return True
#
#             if args.resume_only:
#                 # Resume only
#                 success = client.resume_download(args.study_uid, args.output_dir, progress_callback)
#             else:
#                 # Full download with resume option
#                 resume = not args.no_resume
#                 success = client.get_study_dicom_files_resumable(
#                     args.study_uid, args.output_dir, args.batch_size,
#                     args.compression, resume, progress_callback
#                 )
#
#             if success:
#                 print("✅ Download completed successfully")
#                 return True
#             else:
#                 print("❌ Download failed")
#                 return False
#
#         finally:
#             client.disconnect()
#
#     if main():
#         exit(0)
#     else:
#         exit(1)
