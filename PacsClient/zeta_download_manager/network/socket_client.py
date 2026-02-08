"""
Socket DICOM Client - Socket-based DICOM image download (Port 50052)

Handles DICOM file downloads via custom socket protocol with:
- Batch processing (100 instances per batch)
- GZIP compression support
- Connection pooling
- Retry with exponential backoff
- JWT authentication support
"""

import socket
import asyncio
import json
import gzip
import base64
import logging
import threading
import time
import random
import os
from typing import Dict, List, Any, Optional, Callable, Tuple
from pathlib import Path

from ..core.models import SeriesInfo, SeriesDownloadResult
from ..core.exceptions import NetworkError
from ..core.constants import (
    DEFAULT_SOCKET_HOST,
    DEFAULT_SOCKET_PORT,
    CONNECTION_TIMEOUT,
    SOCKET_CHUNK_SIZE,
    BATCH_SIZE,
    MAX_RETRIES,
    RETRY_DELAY,
)
from .health_monitor import ConnectionHealthMonitor

# Import token manager for authentication
from PacsClient.utils.socket_token_manager import get_socket_token_manager

logger = logging.getLogger(__name__)

# Singleton health monitor instance (shared across all socket clients)
_health_monitor: Optional[ConnectionHealthMonitor] = None

def get_health_monitor() -> ConnectionHealthMonitor:
    """Get singleton health monitor instance"""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = ConnectionHealthMonitor()
    return _health_monitor


class SocketDicomClient:
    """
    Socket-based DICOM image download client
    
    Protocol: Custom binary protocol with JSON envelope
    - [4 bytes: Message Length (Big Endian)]
    - [N bytes: JSON Payload]
    
    Features:
    - Connection pooling
    - Automatic retry with backoff
    - GZIP compression
    - Progress callbacks
    - JWT authentication
    """

    # Global adaptive batch size to persist across client instances
    _global_adaptive_batch_size: int = BATCH_SIZE
    
    def __init__(
        self,
        host: str = None,
        port: int = None,
        timeout: float = None,
        token_manager = None,
        auth_token: str = None,
        health_monitor: ConnectionHealthMonitor = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ):
        """
        Initialize socket client
        
        Args:
            host: Server host
            port: Server port
            timeout: Connection timeout
            token_manager: Token manager for authentication (uses global if not provided)
            auth_token: Optional explicit auth token (overrides token_manager)
            health_monitor: Connection health monitor (uses global if not provided)
            cancel_check: Callable that returns True if download should be cancelled (R25 preemption)
        """
        self.host = host or DEFAULT_SOCKET_HOST
        self.port = port or DEFAULT_SOCKET_PORT
        self.timeout = timeout or CONNECTION_TIMEOUT
        
        # Use provided token_manager or fall back to global singleton
        self.token_manager = token_manager or get_socket_token_manager()
        
        # Explicit auth token takes priority
        self.auth_token = auth_token
        
        # R30: Connection health monitoring
        self.health_monitor = health_monitor or get_health_monitor()
        
        self.socket = None
        self.connected = False
        self.lock = threading.Lock()
        
        # Cancellation for preemption checks (R25)
        # Can use external cancel_check callback or internal flag
        self._cancel_check = cancel_check  # External callback (from worker)
        self._cancelled = False  # Internal flag
        self._cancel_lock = threading.Lock()

        # Adaptive batch size (persists across series to avoid repeated oversized requests)
        self._adaptive_batch_size = SocketDicomClient._global_adaptive_batch_size
        
        logger.info(f"🔌 SocketDicomClient initialized ({self.host}:{self.port})")
    
    def connect(self) -> bool:
        """
        Connect to socket server with TCP optimizations
        
        Returns:
            True if connected, False otherwise
        """
        with self.lock:
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(self.timeout)
                
                # TCP optimizations
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)  # 128KB
                
                self.socket.connect((self.host, self.port))
                self.connected = True
                
                logger.info(f"✅ Connected to {self.host}:{self.port}")
                return True
            
            except Exception as e:
                logger.error(f"❌ Connection failed: {e}")
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                return False
    
    def disconnect(self) -> None:
        """Disconnect from server"""
        with self.lock:
            if self.socket:
                try:
                    # Shutdown the socket to prevent further sends/receives
                    try:
                        self.socket.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        # Socket may already be closed, ignore error
                        pass
                    self.socket.close()
                except Exception as e:
                    logger.warning(f"⚠️ Error closing socket: {e}")
                finally:
                    self.socket = None
                    self.connected = False
                    logger.info("🔌 Disconnected from socket server")
    
    def is_connected(self) -> bool:
        """Check if connected to server"""
        return self.connected and self.socket is not None
    
    def request_cancel(self) -> None:
        """Request cancellation of current operation (R25: Preemption support)"""
        with self._cancel_lock:
            self._cancelled = True
            logger.info("⏸️ Cancellation requested for socket client")
    
    def is_cancelled(self) -> bool:
        """
        Check if cancellation has been requested (R25)
        
        Checks both:
        1. External cancel_check callback (from worker/executor)
        2. Internal _cancelled flag (from request_cancel())
        """
        # Check external callback first (worker preemption)
        if self._cancel_check is not None:
            try:
                if self._cancel_check():
                    logger.debug("⏸️ External cancel check returned True")
                    return True
            except Exception as e:
                logger.warning(f"⚠️ Cancel check callback error: {e}")
        
        # Check internal flag
        with self._cancel_lock:
            return self._cancelled
    
    def reset_cancel(self) -> None:
        """Reset cancellation flag"""
        with self._cancel_lock:
            self._cancelled = False
    
    def connect_with_retry(self, max_retries: int = 3, retry_delay: float = 1.0) -> bool:
        """
        Connect to socket server with retry logic
        
        Args:
            max_retries: Maximum number of connection attempts
            retry_delay: Delay between retries in seconds
            
        Returns:
            True if connected, False otherwise
        """
        for attempt in range(max_retries):
            if self.connect():
                return True
            
            if attempt < max_retries - 1:
                logger.warning(f"⚠️ Connection attempt {attempt + 1} failed, retrying in {retry_delay}s...")
                time.sleep(retry_delay)
        
        logger.error(f"❌ Failed to connect after {max_retries} attempts")
        return False
    
    def login(self, username: str, password: str) -> Tuple[bool, str, Optional[str], Optional[Dict[str, Any]]]:
        """
        Login to socket server and get JWT token
        
        Args:
            username: Username for authentication
            password: Password for authentication
            
        Returns:
            Tuple of (success, message, token, user_info)
        """
        logger.info(f"🔐 Attempting login for user: {username}")
        
        try:
            response = self.send_request('Login', {
                'username': username,
                'password': password
            })
            
            if not response:
                logger.error("❌ Login failed: No response from server")
                return False, "No response from server", None, None
            
            status = response.get('status', '')
            success = response.get('success', False)
            message = response.get('message', response.get('error', 'Unknown error'))
            
            if status == 'success' or success:
                # Token can be at root level OR in data.token
                token = response.get('token')
                if not token:
                    data = response.get('data', {})
                    token = data.get('token') if isinstance(data, dict) else None
                
                # User info can be at root level OR in data.user
                user = response.get('user')
                if not user:
                    data = response.get('data', {})
                    user = data.get('user') if isinstance(data, dict) else None
                
                # Try to extract user info from other fields if not in 'user'
                if not user:
                    # Build user dict from response fields
                    user = {}
                    if 'fullName' in response or 'full_name' in response:
                        user['full_name'] = response.get('fullName') or response.get('full_name')
                    if 'username' in response:
                        user['username'] = response.get('username')
                    if 'roles' in response:
                        user['role'] = response.get('roles', {}).get('Name', 'user')
                    if not user:
                        user = None
                
                if token:
                    # Store token in token manager
                    self.token_manager.set_token(token, user)
                    self.auth_token = token
                    logger.info(f"✅ Login successful for {username}")
                    return True, message, token, user
                else:
                    logger.error("❌ Login response missing token")
                    return False, "Login response missing token", None, None
            else:
                logger.error(f"❌ Login failed: {message}")
                return False, message, None, None
                
        except Exception as e:
            logger.error(f"❌ Login exception: {e}")
            return False, str(e), None, None
    
    def verify_token(self, token: str = None) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Verify JWT token validity
        
        Args:
            token: Token to verify (uses stored token if not provided)
            
        Returns:
            Tuple of (valid, message, user_info)
        """
        token_to_verify = token or self.auth_token or self.token_manager.get_token()
        
        if not token_to_verify:
            logger.warning("⚠️ No token to verify")
            return False, "No token available", None
        
        logger.info("🔐 Verifying token...")
        
        try:
            response = self.send_request('VerifyToken', {
                'token': token_to_verify
            })
            
            if not response:
                logger.error("❌ Token verification failed: No response")
                return False, "No response from server", None
            
            status = response.get('status', '')
            message = response.get('message', response.get('error', 'Unknown error'))
            
            if status == 'success':
                data = response.get('data', {})
                user = data.get('user')
                logger.info("✅ Token is valid")
                return True, "Token is valid", user
            else:
                logger.warning(f"⚠️ Token invalid: {message}")
                return False, message, None
                
        except Exception as e:
            logger.error(f"❌ Token verification exception: {e}")
            return False, str(e), None
    
    def ensure_authenticated(self) -> bool:
        """
        Ensure the client is authenticated (has valid token)
        
        Returns:
            True if authenticated or token is available
        """
        # Check if we have a token from any source
        token = self.auth_token or self.token_manager.get_token()
        
        if not token:
            logger.warning("⚠️ No authentication token available")
            return False
        
        logger.info("✅ Authentication token available")
        return True
    
    def send_request(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Send request to server with authentication

        Args:
            endpoint: Endpoint name
            params: Request parameters

        Returns:
            Response dict or None on error
        """
        logger.info(f"📤 send_request: {endpoint} - acquiring lock...")

        with self.lock:
            logger.info(f"📤 send_request: {endpoint} - lock acquired")

            if not self.connected:
                logger.info(f"📤 send_request: Not connected, attempting connection...")
                if not self.connect():
                    logger.error(f"❌ send_request: Connection failed!")
                    return None
                logger.info(f"📤 send_request: Connected successfully")

            try:
                # Build request
                request = {
                    "endpoint": endpoint,
                    "params": params
                }

                # Add authentication token (priority: explicit > token_manager)
                # Skip token for Login endpoint to avoid circular dependency
                if endpoint != 'Login':
                    if self.auth_token:
                        request["token"] = self.auth_token
                        logger.info(f"🔐 Added explicit auth token to {endpoint} request")
                    elif self.token_manager and self.token_manager.has_token():
                        request = self.token_manager.add_token_to_request(request)
                        logger.info(f"🔐 Added token from manager to {endpoint} request")
                    else:
                        logger.warning(f"⚠️ No auth token available for {endpoint}")

                # Serialize to JSON
                request_json = json.dumps(request, ensure_ascii=False)
                request_bytes = request_json.encode('utf-8')

                logger.info(f"📤 Sending {endpoint} request ({len(request_bytes)} bytes)...")

                # Send length prefix (4 bytes, big endian)
                length_bytes = len(request_bytes).to_bytes(4, byteorder='big')
                self.socket.sendall(length_bytes)

                # Send request data
                self.socket.sendall(request_bytes)
                logger.info(f"📤 Request sent, waiting for response...")

                # Receive response length
                logger.info(f"📥 Waiting for response header (4 bytes)...")
                response_length_bytes = self._safe_recv(4)
                if not response_length_bytes:
                    raise NetworkError("Connection closed by server")

                response_length = int.from_bytes(response_length_bytes, byteorder='big')
                
                # Validate response length to prevent extremely large allocations
                if response_length > 50 * 1024 * 1024:  # 50MB limit
                    raise NetworkError(f"Response too large: {response_length} bytes")

                logger.info(f"📥 Receiving response body ({response_length} bytes)...")

                # Receive response data
                response_data = b''
                while len(response_data) < response_length:
                    chunk_size = min(SOCKET_CHUNK_SIZE, response_length - len(response_data))
                    chunk = self._safe_recv(chunk_size)
                    if not chunk:
                        raise NetworkError("Connection lost while receiving data")
                    response_data += chunk
                    if response_length > 100000:  # Log progress for large responses
                        logger.info(f"📥 Received {len(response_data)}/{response_length} bytes ({100*len(response_data)//response_length}%)")

                logger.info(f"📥 Response received completely ({len(response_data)} bytes)")

                # Parse response
                response = json.loads(response_data.decode('utf-8'))
                logger.info(f"📥 Response parsed: status={response.get('status', 'unknown')}")
                return response

            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                logger.error(f"❌ Connection reset error for {endpoint}: {e}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                # Mark connection as broken and clean up
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                # R30: Record failure for health monitoring
                self.health_monitor.record_failure()
                return None
            except Exception as e:
                logger.error(f"❌ Request error for {endpoint}: {e}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                # Handle other socket errors that indicate connection problems
                if isinstance(e, (socket.error, OSError)) or "forcibly closed" in str(e):
                    self.connected = False
                    if self.socket:
                        try:
                            self.socket.close()
                        except:
                            pass
                        self.socket = None
                    # R30: Record failure for health monitoring
                    self.health_monitor.record_failure()
                return None

    def _safe_recv(self, size: int) -> bytes:
        """
        Safely receive data with timeout handling and connection checking
        
        Args:
            size: Number of bytes to receive
            
        Returns:
            Bytes received or empty bytes if connection closed
        """
        try:
            return self.socket.recv(size)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            logger.warning(f"⚠️ Connection reset during recv: {e}")
            self.connected = False
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            return b""
        except socket.timeout:
            logger.warning(f"⚠️ Socket timeout during recv")
            return b""
        except OSError as e:
            if e.errno == 10054:  # Connection reset by peer
                logger.warning(f"⚠️ Connection forcibly closed during recv: {e}")
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except:
                        pass
                    self.socket = None
                return b""
            else:
                logger.error(f"❌ OSError during recv: {e}")
                raise
    
    def download_batch(
        self,
        study_uid: str,
        series_uid: str,
        batch_start: int,
        batch_size: int = None
    ) -> Optional[Dict[str, Any]]:
        """
        Download batch of DICOM instances using GetSeriesImages endpoint
        
        Args:
            study_uid: Study UID
            series_uid: Series UID
            batch_start: Starting instance index (converted to batch_index)
            batch_size: Number of instances to download
            
        Returns:
            Response dict with instance data or None on error
        """
        batch_size = batch_size or BATCH_SIZE
        
        # Convert batch_start to batch_index (batch_start / batch_size)
        batch_index = batch_start // batch_size if batch_size > 0 else 0
        
        logger.info(f"📥 download_batch: series={series_uid[:40]}..., batch_index={batch_index}, size={batch_size}")
        logger.info(f"📥 Sending GetSeriesImages request...")
        
        # Use correct endpoint: GetSeriesImages (not DownloadDicomBatch)
        response = self.send_request('GetSeriesImages', {
            'series_uid': series_uid,
            'batch_size': batch_size,
            'batch_index': batch_index,
            'metadata_only': False
        })
        
        if response:
            logger.info(f"📥 download_batch: Got response with status={response.get('status', 'unknown')}")
        else:
            logger.warning(f"📥 download_batch: No response received!")
        
        return response
    
    async def download_series(
        self,
        study_uid: str,
        series_info: SeriesInfo,
        output_dir: Path,
        progress_callback: Optional[Callable] = None
    ) -> SeriesDownloadResult:
        """
        Download complete series with batch processing
        
        Args:
            study_uid: Study UID
            series_info: Series metadata
            output_dir: Output directory for series
            progress_callback: Progress callback function
            
        Returns:
            SeriesDownloadResult
        """
        series_uid = series_info.series_uid
        series_number = series_info.series_number
        expected_count = series_info.image_count
        
        logger.info(f"📥 Downloading series {series_number} ({expected_count} images)")
        
        # Create output directory
        logger.info(f"📁 Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"✅ Output directory ready")
        
        # Check for existing files (R19: file-level resume)
        logger.info(f"🔍 Scanning for existing files...")
        existing_files = self._scan_existing_files(output_dir)
        skipped_count = len(existing_files)
        logger.info(f"📊 Found {skipped_count} existing files")
        
        # Calculate batches (adaptive)
        batch_size = min(self._adaptive_batch_size, 10)
        min_batch_size = 1
        total_batches = (expected_count + batch_size - 1) // batch_size
        downloaded_count = 0
        
        logger.info(f"📦 Will download in {total_batches} batches (batch size: {batch_size})")
        
        start_time = time.time()
        
        # Ensure we're connected before starting batches
        logger.info(f"🔌 Ensuring socket connection...")
        if not self.connected:
            logger.info(f"🔌 Not connected, attempting connection...")
            if not self.connect():
                logger.error(f"❌ Failed to connect to server!")
                return SeriesDownloadResult(
                    success=False,
                    series_uid=series_uid,
                    series_number=series_number,
                    downloaded=0,
                    skipped=skipped_count,
                    total=expected_count,
                    elapsed_seconds=time.time() - start_time,
                    error_message="Failed to connect to download server"
                )
        logger.info(f"✅ Socket connected")
        
        # Download in batches (adaptive batch size)
        batch_start = 0
        batch_idx = 0
        while batch_start < expected_count:
            # R25: Check for preemption between batches
            if self.is_cancelled():
                logger.info(f"⏸️ Download cancelled - stopping at batch {batch_idx + 1}/{total_batches}")
                return SeriesDownloadResult(
                    success=False,
                    series_uid=series_uid,
                    series_number=series_number,
                    downloaded=downloaded_count,
                    skipped=skipped_count,
                    total=expected_count,
                    elapsed_seconds=time.time() - start_time,
                    error_message="Download cancelled (preemption)"
                )
            
            logger.info(f"📦 Starting batch {batch_idx + 1}/{total_batches} (start: {batch_start}, size: {batch_size})")
            
            # R33: Check connection health before operation
            if self.health_monitor.should_test_connection():
                logger.info(f"🔍 Testing connection health before batch...")
                if not self.connected:
                    if not self.connect():
                        logger.error(f"❌ Health check failed - connection lost")
                        self.health_monitor.record_failure()
                        continue
            
            # Download batch with retry
            response = await self._download_batch_with_retry(
                study_uid,
                series_uid,
                batch_start,
                batch_size
            )
            
            logger.info(f"📦 Batch {batch_idx + 1} response received: {response is not None}")
            
            if not response or response.get('status') != 'success':
                error_msg = response.get('error') or response.get('message', 'Unknown error') if response else 'No response'
                logger.error(f"❌ Batch {batch_idx + 1} failed: {error_msg}")

                if "Response too large" in str(error_msg) and batch_size > min_batch_size:
                    batch_size = max(min_batch_size, batch_size // 2)
                    self._adaptive_batch_size = batch_size
                    SocketDicomClient._global_adaptive_batch_size = batch_size
                    total_batches = (expected_count + batch_size - 1) // batch_size
                    logger.warning(
                        f"⚠️ Response too large - reducing batch size to {batch_size} and retrying batch"
                    )
                    continue

                return SeriesDownloadResult(
                    success=False,
                    series_uid=series_uid,
                    series_number=series_number,
                    downloaded=downloaded_count,
                    skipped=skipped_count,
                    total=expected_count,
                    elapsed_seconds=time.time() - start_time,
                    error_message=error_msg
                )
            
            # Process instances in batch (using GetSeriesImages response format)
            data = response.get('data', {})
            instances = data.get('instances', [])
            
            logger.info(f"📦 Batch {batch_idx + 1}: Got {len(instances)} instances")
            
            for instance_data in instances:
                # GetSeriesImages format uses 'dicom_data' and 'is_compressed'
                dicom_data_b64 = instance_data.get('dicom_data', '')
                is_compressed = instance_data.get('is_compressed', False)
                instance_number = instance_data.get('instance_number', downloaded_count + 1)
                
                # Generate file name from instance number
                try:
                    instance_num_int = int(instance_number)
                except (ValueError, TypeError):
                    instance_num_int = downloaded_count + 1
                
                file_name = f"Instance_{instance_num_int:04d}.dcm"
                file_path = output_dir / file_name
                
                # Skip if exists (R19: file-level resume)
                if file_path.exists():
                    skipped_count += 1
                    continue
                
                if not dicom_data_b64:
                    logger.warning(f"⚠️ Empty DICOM data for instance {instance_number}")
                    continue
                
                try:
                    # Decode base64
                    dicom_bytes = base64.b64decode(dicom_data_b64)
                    
                    # Decompress if needed
                    if is_compressed:
                        dicom_bytes = gzip.decompress(dicom_bytes)
                    
                    # Save file
                    with open(file_path, 'wb') as f:
                        f.write(dicom_bytes)
                    
                    downloaded_count += 1
                    
                except Exception as e:
                    logger.error(f"❌ Error saving instance {instance_number}: {e}")
                    continue
                
                # Progress callback
                if progress_callback:
                    progress_pct = ((downloaded_count + skipped_count) / expected_count) * 100
                    progress_callback(
                        'instance_downloaded',
                        series_number,
                        progress_pct,
                        downloaded_count + skipped_count,
                        expected_count
                    )
            
            # Check if more batches are needed (server pagination)
            has_more = data.get('has_more', False)
            if not has_more:
                logger.info(f"📦 Server indicates no more batches")
                break

            batch_idx += 1
            batch_start += batch_size
        
        elapsed = time.time() - start_time
        
        logger.info(
            f"✅ Series {series_number} complete: "
            f"{downloaded_count} downloaded, {skipped_count} skipped ({elapsed:.1f}s)"
        )
        
        return SeriesDownloadResult(
            success=True,
            series_uid=series_uid,
            series_number=series_number,
            downloaded=downloaded_count,
            skipped=skipped_count,
            total=expected_count,
            elapsed_seconds=elapsed
        )
    
    def _scan_existing_files(self, output_dir: Path) -> List[str]:
        """
        Scan for existing DICOM files
        
        Args:
            output_dir: Directory to scan
            
        Returns:
            List of existing file names
        """
        if not output_dir.exists():
            return []
        
        try:
            return [f for f in os.listdir(output_dir) if f.endswith('.dcm')]
        except Exception as e:
            logger.warning(f"⚠️ Could not scan directory: {e}")
            return []
    
    async def _download_batch_with_retry(
        self,
        study_uid: str,
        series_uid: str,
        batch_start: int,
        batch_size: int
    ) -> Optional[Dict[str, Any]]:
        """
        Download batch with retry logic (R27, R28, R31)
        
        Implements:
        - R27: Exponential backoff retry
        - R28: Max 3 retry attempts
        - R30: Connection health tracking
        - R31: Retry with jitter
        
        Args:
            study_uid: Study UID
            series_uid: Series UID
            batch_start: Batch starting index
            batch_size: Batch size
            
        Returns:
            Response dict or None on failure
        """
        logger.info(f"🔄 _download_batch_with_retry called: series={series_uid[:30]}..., start={batch_start}, size={batch_size}")
        
        for attempt in range(MAX_RETRIES):
            # R25: Check for cancellation before each attempt
            if self.is_cancelled():
                logger.info(f"⏸️ Batch download cancelled")
                return None
            
            request_start = time.time()
            
            try:
                logger.info(f"🔄 Attempt {attempt + 1}/{MAX_RETRIES}: Calling download_batch...")
                response = self.download_batch(study_uid, series_uid, batch_start, batch_size)
                logger.info(f"🔄 Attempt {attempt + 1}: Got response: {response is not None}")
                
                if response:
                    status = response.get('status', 'unknown')
                    logger.info(f"🔄 Response status: {status}")
                    
                    # R30: Record success with latency
                    latency_ms = (time.time() - request_start) * 1000
                    self.health_monitor.record_success(latency_ms)
                    
                    return response
                else:
                    logger.warning(f"⚠️ Attempt {attempt + 1}: Empty response")
                    # R30: Record failure
                    self.health_monitor.record_failure()
            
            except Exception as e:
                logger.warning(f"⚠️ Batch download attempt {attempt + 1} failed: {e}")
                import traceback
                logger.warning(f"⚠️ Traceback: {traceback.format_exc()}")
                
                # R30: Record failure
                self.health_monitor.record_failure()
                
                if attempt < MAX_RETRIES - 1:
                    # R27, R31: Exponential backoff with jitter
                    jitter = random.uniform(0, 0.5)
                    delay = RETRY_DELAY * (2 ** attempt) + jitter
                    
                    # R32: Adaptive throttling based on health
                    if not self.health_monitor.is_healthy():
                        delay *= 2  # Double delay if connection unhealthy
                        logger.info(f"⚠️ Unhealthy connection - doubling retry delay")
                    
                    logger.info(f"⏳ Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    
                    # Reconnect
                    logger.info(f"🔌 Reconnecting...")
                    self.disconnect()
                    if not self.connect():
                        logger.error(f"❌ Reconnection failed")
                        continue
                    logger.info(f"✅ Reconnected")
        
        # All retries failed
        logger.error(f"❌ Batch download failed after {MAX_RETRIES} attempts")
        return None
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()

    def __del__(self):
        """Destructor to ensure socket cleanup"""
        try:
            self.disconnect()
        except:
            # Don't raise exceptions in destructor
            pass
