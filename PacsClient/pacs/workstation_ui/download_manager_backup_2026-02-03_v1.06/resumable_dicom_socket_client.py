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
import random  # For retry jitter to prevent thundering herd
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
        
        # === ENDPOINT CACHING ===
        # Cache which endpoint configuration works to avoid trial-and-error on every request
        self._cached_endpoint_config = None  # Tuple of (endpoint, params_template)
        self._endpoint_cache_hits = 0
        self._endpoint_cache_misses = 0
        
        # === SERIES INFO CACHING ===
        # Cache series info to avoid repeated gRPC calls (expensive on slow networks)
        # Key: study_uid, Value: series_list
        self._series_info_cache = {}
        
    def _get_cached_series_info(self, study_uid: str) -> list:
        """Get cached series info for a study, or None if not cached."""
        return self._series_info_cache.get(study_uid)
    
    def _cache_series_info(self, study_uid: str, series_list: list):
        """Cache series info for a study."""
        self._series_info_cache[study_uid] = series_list
    
    def _clear_series_cache(self, study_uid: str = None):
        """Clear series info cache. If study_uid is None, clear all."""
        if study_uid:
            self._series_info_cache.pop(study_uid, None)
        else:
            self._series_info_cache.clear()
        
    def connect(self):
        """
        Connect to the Socket server
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        with self.lock:
            try:
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
                        # Exponential backoff WITH JITTER to prevent thundering herd
                        jitter = random.uniform(0, 0.5)
                        time.sleep(self.retry_delay * (2 ** attempt) + jitter)
            except Exception as e:
                logger.error(f"❌ Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    # Exponential backoff WITH JITTER
                    jitter = random.uniform(0, 0.5)
                    time.sleep(self.retry_delay * (2 ** attempt) + jitter)
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
            if not self.connected:
                if not self.connect():
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
            
            self.socket.sendall(length + message)
            
            # Receive response length
            length_data = self.socket.recv(4)
            if not length_data:
                logger.error("❌ Connection closed by server")
                return None
                
            response_length = int.from_bytes(length_data, byteorder='big')
            response_data = b''
            
            # Receive response data
            while len(response_data) < response_length:
                chunk = self.socket.recv(min(4096, response_length - len(response_data)))
                if not chunk:
                    logger.error("❌ Connection lost while receiving data")
                    return None
                response_data += chunk
            
            response = json.loads(response_data.decode('utf-8'))
            return response
            
        except Exception as e:
            logger.error(f"❌ Request error: {e}")
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
        
        try:
            if not self.send_request("GetStudyInfo", {"study_instance_uid": study_uid}):
                logger.error(f"❌ Failed to send GetStudyInfo request")
                return None
            
            logger.info(f"📡 GetStudyInfo request sent, waiting for response...")
            
            # Add timeout wrapper for receive_response
            import threading
            response_holder = [None]
            error_holder = [None]
            
            def receive_with_timeout():
                try:
                    response_holder[0] = self.receive_response()
                except Exception as e:
                    error_holder[0] = e
                    logger.error(f"❌ Error in receive_response: {e}")
            
            # Run receive in a thread with timeout
            recv_thread = threading.Thread(target=receive_with_timeout, daemon=True)
            recv_thread.start()
            recv_thread.join(timeout=60)  # 60 second timeout
            
            if recv_thread.is_alive():
                logger.error(f"❌ GetStudyInfo response TIMEOUT after 60 seconds - server not responding!")
                logger.error(f"⚠️ The server may not support 'GetStudyInfo' endpoint")
                # Try to create dummy study info from study UID
                logger.info(f"🔄 Creating fallback study info without server response...")
                return {
                    "patient_id": "Unknown",
                    "patient_name": "Unknown Patient",
                    "study_date": "",
                    "study_description": "",
                    "modality": "Unknown",
                    "total_instances": 0,  # Will be determined during download
                    "total_series": 0,
                    "study_instance_uid": study_uid
                }
            
            if error_holder[0]:
                logger.error(f"❌ Receive error: {error_holder[0]}")
                return None
            
            response = response_holder[0]
            if not response:
                logger.error(f"❌ No response received from server")
                return None
            
            logger.info(f"✅ GetStudyInfo response received")
            
            if response.get("status") != "success":
                error_msg = response.get("error", "Unknown error")
                logger.error(f"❌ Request failed: {error_msg}")
                return None
            
            return response.get("data", {})
            
        except Exception as e:
            logger.error(f"❌ Error in get_study_info: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def get_study_dicom_files_batch(self, study_uid: str, batch_size: int = 10, 
                                   offset: int = 0, compression: str = "gzip") -> Optional[Dict[str, Any]]:
        """
        Get a batch of DICOM files for a study with retry mechanism
        
        OPTIMIZED: Uses endpoint caching to avoid trial-and-error on every request.
        
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
        
        # === ENDPOINT CACHING: Try cached endpoint first ===
        if self._cached_endpoint_config:
            cached_endpoint, params_template = self._cached_endpoint_config
            # Build params from template
            params = self._build_params_from_template(params_template, study_uid, batch_size, offset, compression)
            
            result = self._try_single_endpoint(cached_endpoint, params)
            if result is not None:
                self._endpoint_cache_hits += 1
                if self._endpoint_cache_hits % 50 == 0:
                    logger.info(f"📊 Endpoint cache stats: hits={self._endpoint_cache_hits}, misses={self._endpoint_cache_misses}")
                return result
            else:
                # Cached endpoint failed - clear cache and try all
                logger.warning(f"⚠️ Cached endpoint {cached_endpoint} failed, trying all endpoints")
                self._cached_endpoint_config = None
        
        self._endpoint_cache_misses += 1
        
        # Try different endpoint names and parameter combinations
        endpoint_configs = [
            ("GetStudyDicomFiles", "study_instance_uid_limit"),
            ("GetStudyDicomFiles", "study_instance_uid_batch"),
            ("GetStudyDicomFilesBatch", "study_uid_batch"),
            ("GetStudyDicomFiles", "study_instance_uid_offset"),
        ]
        
        # Retry mechanism for each endpoint
        for endpoint, params_template in endpoint_configs:
            params = self._build_params_from_template(params_template, study_uid, batch_size, offset, compression)
            logger.info(f"🧪 Trying endpoint: {endpoint}")
            
            result = self._try_single_endpoint(endpoint, params)
            if result is not None:
                # Cache this working endpoint for future requests
                self._cached_endpoint_config = (endpoint, params_template)
                logger.info(f"💾 Cached working endpoint: {endpoint}")
                return result
        
        logger.error(f"❌ All batch request attempts failed after {self.max_retries} retries")
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        return None
    
    def _build_params_from_template(self, template: str, study_uid: str, batch_size: int, 
                                    offset: int, compression: str) -> dict:
        """Build request parameters from a template name"""
        if template == "study_instance_uid_limit":
            return {
                "study_instance_uid": study_uid,
                "instance_limit": batch_size,
                "compression": compression
            }
        elif template == "study_instance_uid_batch":
            return {
                "study_instance_uid": study_uid,
                "batch_size": batch_size,
                "offset": offset,
                "compression": compression
            }
        elif template == "study_uid_batch":
            return {
                "study_uid": study_uid,
                "batch_size": batch_size,
                "offset": offset,
                "compression": compression
            }
        elif template == "study_instance_uid_offset":
            return {
                "study_instance_uid": study_uid,
                "limit": batch_size,
                "offset": offset
            }
        else:
            # Fallback
            return {
                "study_instance_uid": study_uid,
                "batch_size": batch_size,
                "offset": offset,
                "compression": compression
            }
    
    def _try_single_endpoint(self, endpoint: str, params: dict) -> dict:
        """Try a single endpoint with retries. Returns data dict or None."""
        for retry_attempt in range(self.max_retries):
            try:
                if not self.send_request(endpoint, params):
                    if retry_attempt < self.max_retries - 1:
                        logger.warning(f"⚠️ Send request failed, retry {retry_attempt + 1}/{self.max_retries}")
                        jitter = random.uniform(0, 0.5)
                        time.sleep(self.retry_delay * (2 ** retry_attempt) + jitter)
                        continue
                    else:
                        return None
                
                response = self.receive_response()
                
                if response.get("status") == "success":
                    logger.info(f"✅ Success with endpoint: {endpoint}")
                    self.consecutive_failures = 0
                    self.consecutive_successes += 1
                    return response.get("data", {})
                else:
                    error_msg = response.get("error", "Unknown error")
                    logger.warning(f"⚠️ {endpoint} failed: {error_msg}")
                    
                    # If it's "Response too large", return None to try next endpoint
                    if "too large" in error_msg.lower():
                        return None
                    
                    # For other errors, retry
                    if retry_attempt < self.max_retries - 1:
                        logger.warning(f"⚠️ Retrying {endpoint}, attempt {retry_attempt + 1}/{self.max_retries}")
                        jitter = random.uniform(0, 0.5)
                        time.sleep(self.retry_delay * (2 ** retry_attempt) + jitter)
                    else:
                        return None
                        
            except Exception as e:
                logger.error(f"❌ Exception in batch request: {e}")
                if retry_attempt < self.max_retries - 1:
                    logger.warning(f"⚠️ Retrying due to exception, attempt {retry_attempt + 1}/{self.max_retries}")
                    jitter = random.uniform(0, 0.5)
                    time.sleep(self.retry_delay * (2 ** retry_attempt) + jitter)
                else:
                    return None
        
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
                                             resume: bool = True, progress_callback: Optional[Callable] = None,
                                             patient_info: Optional[Dict[str, Any]] = None,
                                             cancellation_callback: Optional[Callable] = None) -> bool:
        """
        Download study using gRPC for series list + RobustSeriesDownloader for files.
        This mirrors the working double-click download approach.
        
        ENHANCED: Added cancellation_callback parameter for preemption support.
        
        Args:
            study_uid: The study instance UID
            output_dir: Output directory for downloaded files
            batch_size: Number of instances per batch
            compression: Compression type
            resume: Whether to resume from previous progress
            progress_callback: Callback for progress updates
            patient_info: Optional dict with patient info (patient_id, patient_name, study_date, etc.)
                         to avoid "Unknown Patient" entries
        """
        logger.info(f"📥 Starting download for study: {study_uid}")
        
        # Import required modules
        try:
            from PacsClient.utils.config import SOURCE_PATH
        except Exception as e:
            logger.error(f"Failed to import SOURCE_PATH: {e}")
            return False
            
        try:
            from PacsClient.utils import insert_patient, insert_study, insert_series, insert_instance
        except Exception as e:
            logger.debug(f"Database functions not available: {e}")
            insert_patient = insert_study = insert_series = insert_instance = None
        
        # Create study directory
        study_path = SOURCE_PATH / study_uid
        study_path.mkdir(parents=True, exist_ok=True)
        
        # Use provided patient_info or create minimal fallback
        # IMPORTANT: Prefer passed patient_info to avoid "Unknown Patient" entries
        if patient_info and patient_info.get('patient_id') and patient_info.get('patient_name'):
            study_info = {
                "patient_id": patient_info.get('patient_id', ''),
                "patient_name": patient_info.get('patient_name', ''),
                "study_date": patient_info.get('study_date', ''),
                "study_description": patient_info.get('study_description', patient_info.get('description', '')),
                "modality": patient_info.get('modality', ''),
                "total_instances": patient_info.get('images_count', 0),
                "total_series": patient_info.get('series_count', 0),
                "study_instance_uid": study_uid
            }
            logger.info(f"📋 Using provided patient info: {study_info.get('patient_name', 'N/A')}")
        else:
            # Fallback to minimal info - will be updated from DICOM headers during download
            # Log a warning so we can track when this fallback is used
            logger.warning(f"⚠️ No patient_info provided for {study_uid[:40]}... - will extract from DICOM headers")
            study_info = {
                "patient_id": "",  # Empty instead of "Unknown" - will be filled from DICOM
                "patient_name": "",  # Empty instead of "Unknown Patient" - will be filled from DICOM
                "study_date": "",
                "study_description": "",
                "modality": "",
                "total_instances": 0,
                "total_series": 0,
                "study_instance_uid": study_uid
            }
        
        # Save to database if available AND we have valid patient info
        # CRITICAL: Skip database insert if patient info is missing to avoid "Unknown" entries
        study_pk = None
        patient_id = study_info.get('patient_id', '')
        patient_name = study_info.get('patient_name', '')
        
        # DIAGNOSTIC: Log patient info before database insert attempt
        logger.info(f"📋 Preparing database insert:")
        logger.info(f"   patient_id: '{patient_id}' (empty: {not bool(patient_id)})")
        logger.info(f"   patient_name: '{patient_name}' (empty: {not bool(patient_name)})")
        logger.info(f"   Database functions available: {insert_patient is not None and insert_study is not None}")
        
        if insert_patient and insert_study and patient_id and patient_name:
            try:
                from PacsClient.utils.database import init_database
                init_database()
                
                # Use INSERT OR IGNORE - if patient exists, it won't error
                patient_pk = insert_patient(
                    patient_id=patient_id,
                    name=patient_name,
                    birth_date=study_info.get('patient_birth_date'),
                    sex=study_info.get('patient_sex'),
                    age=study_info.get('patient_age')
                )
                logger.info(f"✅ Patient in database: {patient_name} (ID: {patient_id}, PK: {patient_pk})")
                
                study_pk = insert_study(
                    study_uid=study_uid,
                    patient_fk=patient_pk,
                    study_date=study_info.get('study_date', ''),
                    study_description=study_info.get('study_description', ''),
                    modality=study_info.get('modality', ''),
                    number_of_series=0,
                    number_of_instances=0,
                    study_path=str(study_path)
                )
                logger.info(f"✅ Study in database: {study_uid[:40]}... (PK: {study_pk})")
                logger.info(f"   📊 This will enable download persistence after restart")
                
            except Exception as e:
                logger.error(f"❌ CRITICAL: Failed to save patient/study to database: {e}")
                logger.error(f"   Patient: {patient_name} (ID: {patient_id})")
                logger.error(f"   ⚠️ THIS DOWNLOAD WILL NOT BE REMEMBERED AFTER RESTART!")
                import traceback
                logger.error(traceback.format_exc())
                study_pk = None
        elif insert_patient and insert_study:
            if not patient_id or not patient_name:
                logger.warning(f"⚠️ Missing patient info - ID: '{patient_id}', Name: '{patient_name}'")
                logger.warning(f"   Download will NOT be remembered after restart!")
            else:
                logger.info(f"📋 Skipping database insert - patient info will be extracted from DICOM files")
        else:
            logger.warning(f"⚠️ Database functions not available - download will NOT be persisted")
        
        try:
            # Step 1: Get series list via gRPC WITH TIMEOUT
            # This is critical for slow networks - prevents indefinite hanging
            from PacsClient.components.grpc_client import DicomGrpcClient
            
            # Check cache first to avoid repeated gRPC calls
            series_list = self._get_cached_series_info(study_uid)
            
            if not series_list:
                logger.info(f"📡 Fetching series info for {study_uid[:40]}... (30s timeout)")
                
                # Use timeout-enabled method - critical for slow networks
                grpc_client = DicomGrpcClient(host=self.host, port=50051, timeout=30.0)
                result = grpc_client.get_study_thumbnails_with_timeout(study_uid, timeout=30.0)
                grpc_client.close()
                
                if result and result.get('series_list'):
                    series_list = result['series_list']
                    # Cache for future use (e.g., if download is paused and resumed)
                    self._cache_series_info(study_uid, series_list)
                    logger.info(f"✅ Cached series info: {len(series_list)} series")
                else:
                    logger.error(f"No series found or timeout for study {study_uid}")
                    return False
            else:
                logger.info(f"📋 Using cached series info: {len(series_list)} series")
            
            if not series_list:
                logger.error(f"No series found in study {study_uid}")
                return False
            
            logger.info(f"Found {len(series_list)} series, starting download...")
            
            # Register series with priority manager
            try:
                from PacsClient.components.download_priority_manager import get_download_priority_manager
                priority_manager = get_download_priority_manager()
                priority_manager.register_patient_download(
                    study_uid=study_uid,
                    patient_id=study_info.get('patient_id', 'Unknown'),
                    patient_name=study_info.get('patient_name', 'Unknown'),
                    series_list=series_list
                )
            except Exception:
                pass  # Priority manager is optional
            
            # Step 2: Download using RobustSeriesDownloader
            from PacsClient.components.robust_series_downloader import RobustSeriesDownloader
            
            robust_downloader = RobustSeriesDownloader(
                host=self.host,
                port=50052,
                max_retries=3,
                retry_delay=2.0,
                connection_timeout=30.0,
                reconnect_delay=1.0
            )
            
            # Progress callback wrapper - tracks overall download progress across ALL series
            # Pre-calculate total_count from all series upfront
            total_images_in_study = sum(s.get('image_count', 0) for s in series_list)
            
            download_state = {
                'downloaded_count': 0,  # Total images downloaded across all series
                'total_count': total_images_in_study,  # Pre-calculated total images in all series combined
                'series_completed': 0,  # Number of completed series
                'total_series': len(series_list),
                'series_progress': {},  # Track progress per series: {series_number: downloaded_count}
                'series_totals': {},  # Track total images per series: {series_number: total_count}
            }
            
            logger.info(f"📊 [DIAG-STUDY-INIT] Download initialized: {len(series_list)} series, {total_images_in_study} total images")
            logger.info(f"   Series breakdown: {[(s.get('series_number'), s.get('image_count', 0)) for s in series_list]}")
            
            # Initialize download progress in database
            if insert_download_progress:
                try:
                    insert_download_progress(
                        study_uid=study_uid,
                        downloaded_count=0,
                        total_instances=total_images_in_study,
                        progress_percent=0.0,
                        status='in_progress'
                    )
                    logger.info(f"📊 Initialized download progress in database: 0/{total_images_in_study}")
                except Exception as db_error:
                    logger.warning(f"⚠️ Failed to initialize download progress in database: {db_error}")
            
            def robust_progress_callback(event_type, series_number, progress_percent, current_count=0, total_count=0, **kwargs):
                """Unified progress callback that aggregates progress across ALL series for overall study progress"""
                series_key = str(series_number)
                
                if event_type == 'series_started':
                    logger.info(f"📥 Starting series {series_number}")
                    # Initialize tracking for this series ONLY if it doesn't exist
                    # This prevents progress reset on retries, ensuring monotonic progress
                    if series_key not in download_state['series_progress']:
                        download_state['series_progress'][series_key] = 0
                    if total_count > 0:
                        download_state['series_totals'][series_key] = total_count
                        # Note: total_count is already pre-calculated, no need to increment here
                    
                    # DEBUG: Log download state
                    logger.debug(f"🔍 [series_started] Series {series_number}: series_total={total_count}, overall_total={download_state['total_count']}, downloaded={download_state['downloaded_count']}")
                    
                    if progress_callback:
                        # Forward aggregated progress
                        overall_percent = (download_state['downloaded_count'] / download_state['total_count'] * 100) if download_state['total_count'] > 0 else 0
                        progress_callback(
                            download_state['downloaded_count'], 
                            download_state['total_count'] or 1, 
                            overall_percent,
                            event_type='series_started',
                            series_number=series_number,
                            series_uid=kwargs.get('series_uid', str(series_number)),
                            series_description=kwargs.get('series_description', '')
                        )
                        
                elif event_type == 'series_progress':
                    # Update this series' downloaded count
                    old_count = download_state['series_progress'].get(series_key, 0)
                    download_state['series_progress'][series_key] = current_count
                    
                    # Calculate cumulative downloaded count across ALL series
                    download_state['downloaded_count'] = sum(download_state['series_progress'].values())
                    
                    # DEBUG: Log aggregation
                    logger.debug(f"🔍 [series_progress] Series {series_number}: current={current_count}, series_total={total_count}, overall_downloaded={download_state['downloaded_count']}, overall_total={download_state['total_count']}")
                    
                    if progress_callback:
                        # Calculate overall progress across all series
                        overall_total = download_state['total_count'] or 1
                        overall_percent = (download_state['downloaded_count'] / overall_total * 100) if overall_total > 0 else 0
                        
                        progress_callback(
                            download_state['downloaded_count'],  # Total images downloaded so far
                            overall_total,  # Total images in all series
                            overall_percent,  # Overall percentage
                            event_type='series_progress',
                            series_number=series_number,
                            series_uid=kwargs.get('series_uid', str(series_number)),
                            series_current=current_count,  # Current series progress
                            series_total=total_count  # Current series total
                        )
                        
                elif event_type == 'series_complete':
                    # Mark series as complete - ensure its full count is in downloaded
                    series_total = download_state['series_totals'].get(series_key, total_count)
                    download_state['series_progress'][series_key] = series_total
                    download_state['downloaded_count'] = sum(download_state['series_progress'].values())
                    download_state['series_completed'] += 1
                    
                    logger.info(f"✅ Series {series_number} completed ({download_state['series_completed']}/{download_state['total_series']})")
                    # DEBUG: Log aggregation at series completion
                    logger.debug(f"🔍 [series_complete] Series {series_number}: overall_downloaded={download_state['downloaded_count']}, overall_total={download_state['total_count']}, percent={download_state['downloaded_count']/download_state['total_count']*100:.1f}%")
                    
                    # Update database progress after each series
                    if insert_download_progress:
                        try:
                            overall_percent = (download_state['downloaded_count'] / download_state['total_count'] * 100) if download_state['total_count'] > 0 else 0
                            insert_download_progress(
                                study_uid=study_uid,
                                downloaded_count=download_state['downloaded_count'],
                                total_instances=download_state['total_count'],
                                progress_percent=overall_percent,
                                status='in_progress'
                            )
                            logger.debug(f"📊 Updated progress in database: {download_state['downloaded_count']}/{download_state['total_count']} ({overall_percent:.1f}%)")
                        except Exception as db_error:
                            logger.warning(f"⚠️ Failed to update download progress: {db_error}")
                    
                    if progress_callback:
                        # Report overall progress after this series completion
                        overall_total = download_state['total_count'] or 1
                        overall_percent = (download_state['downloaded_count'] / overall_total * 100) if overall_total > 0 else 0
                        
                        progress_callback(
                            download_state['downloaded_count'], 
                            overall_total, 
                            overall_percent,
                            event_type='series_complete',
                            series_number=series_number,
                            series_uid=kwargs.get('series_uid', str(series_number))
                        )
                        
                elif event_type == 'series_failed':
                    logger.warning(f"❌ Series {series_number} failed")
                    
            # Check if this is a high priority patient (from priority manager)
            is_high_priority = False
            try:
                from PacsClient.components.download_priority_manager import get_download_priority_manager
                priority_manager = get_download_priority_manager()
                if priority_manager.is_tab_open(study_uid):
                    is_high_priority = True  # Patient tab is open = HIGH/CRITICAL priority
                    logger.info(f"🎯 High priority patient detected - may use parallel series download")
            except:
                pass
            
            # Store reference for cancellation support
            self._active_robust_downloader = robust_downloader
            
            # ENHANCED: Pass cancellation callback to check before each series
            results = robust_downloader.download_all_series_with_priority(
                series_list=series_list,
                base_output_dir=str(study_path),
                priority_series=None,
                progress_callback=robust_progress_callback,
                widget_ref=None,
                is_high_priority_patient=is_high_priority,
                cancellation_callback=cancellation_callback
            )
            
            # Cleanup
            robust_downloader.disconnect()
            
            # Check results
            completed_series = len(results.get('completed', []))
            skipped_series = len(results.get('skipped', []))
            failed_series = len(results.get('failed', []))
            total_series = results.get('total', len(series_list))
            
            # SUCCESS if all series are either completed or skipped (already complete)
            successful_series = completed_series + skipped_series
            
            if successful_series == 0:
                logger.error(f"No series downloaded for study {study_uid}")
                return False
            
            # Log detailed results
            if skipped_series > 0:
                logger.info(f"✅ Download completed: {completed_series} new, {skipped_series} already complete, {failed_series} failed (Total: {total_series})")
            else:
                logger.info(f"Download completed: {completed_series}/{total_series} series")
            
            # Mark download as completed in database (if any series succeeded or were already complete)
            if complete_download_progress and successful_series > 0:
                try:
                    complete_download_progress(study_uid)
                    logger.info(f"✅ Marked download as completed in database for {study_uid[:40]}...")
                except Exception as db_error:
                    logger.warning(f"⚠️ Failed to mark download as completed in database: {db_error}")
            
            # Send final progress callback with completed state
            if progress_callback:
                try:
                    final_count = download_state.get('downloaded_count', 0)
                    final_total = download_state.get('total_count', 0) or final_count or 1
                    logger.debug(f"📊 Final progress: {final_count}/{final_total} (100%)")
                    progress_callback(final_count, final_total, 100)
                except Exception as cb_error:
                    logger.warning(f"⚠️ Final progress callback error (non-fatal): {cb_error}")
            
            return True
            
        except Exception as e:
            logger.error(f"Download error for study {study_uid}: {e}")
            import traceback
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            return False
    
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
                               progress_callback: Optional[Callable] = None,
                               patient_info: Optional[Dict[str, Any]] = None,
                               cancellation_callback: Optional[Callable] = None) -> bool:
        """
        Download study with resumable capability (wrapper for UI compatibility)
        
        Args:
            study_uid (str): Study Instance UID
            batch_size (int): Number of instances per batch
            compression (str): Compression type
            resume (bool): Whether to resume existing download
            progress_callback (callable): Progress callback function
            patient_info (dict): Optional patient info to avoid "Unknown Patient" entries
            cancellation_callback (callable): Callback that returns True if download should stop
            
        Returns:
            bool: True if download successful, False otherwise
        """
        logger.info(f"🔄 Starting resumable download for study: {study_uid}")
        if patient_info:
            logger.info(f"   Patient info provided: {patient_info.get('patient_name', 'N/A')}")
        
        # Use the working batch download method
        return self.download_study_batch_like_working_code(
            study_uid=study_uid,
            output_dir="./downloads",
            batch_size=batch_size,
            compression=compression,
            resume=resume,
            progress_callback=progress_callback,
            patient_info=patient_info,
            cancellation_callback=cancellation_callback
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
