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
from ..core import constants as _dm_consts   # module ref for monkey-patchable defaults
from ..core.constants import (
    DEFAULT_SOCKET_HOST,
    DEFAULT_SOCKET_PORT,
    CONNECTION_TIMEOUT,
    SOCKET_CHUNK_SIZE,
    BATCH_SIZE,
    MAX_RETRIES,
    RETRY_DELAY,
    RECONNECT_MAX_RETRIES,
    RECONNECT_BASE_DELAY,
    RECONNECT_MAX_DELAY,
    RECONNECT_BACKOFF_FACTOR,
    RECONNECT_JITTER_MAX,
    REQUEST_MAX_RETRIES,
    REQUEST_RETRY_BASE_DELAY,
)
from .health_monitor import ConnectionHealthMonitor
from PacsClient.utils.diagnostic_logging import DownloadProgressAggregator, set_log_context, now_ms, log_stage_timing

# Import token manager for authentication
from modules.network.socket_token_manager import get_socket_token_manager

logger = logging.getLogger(__name__)
_download_progress_aggregator = DownloadProgressAggregator(logger, interval_seconds=2.0)


def _decode_socket_payload(data: bytes) -> str:
    """Decode a socket JSON payload tolerantly.

    The payload is normally UTF-8 JSON, but a single field (a patient name or
    description) can carry non-UTF-8 bytes — Persian / Western-European source data
    that was encoded Windows-1256 / Latin-1 by the modality and forwarded verbatim.
    A strict ``decode('utf-8')`` then raises ``UnicodeDecodeError`` and aborts the
    ENTIRE download (observed on a client PC: bytes 0xe7/0xf6/0xed/0xfb at
    ``_send_request_once``). Try strict UTF-8 first (the normal case — zero change),
    then fall back to UTF-8 with replacement so ``json.loads`` still succeeds and the
    download proceeds; only the offending text field degrades to a placeholder, never
    the image data.
    """
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError as exc:
        logger.warning(
            "Socket payload had non-UTF-8 byte(s) (%s); decoding with replacement so "
            "the download proceeds (a name/description field may show a placeholder).",
            exc,
        )
        return data.decode('utf-8', errors='replace')


# Max server broadcast messages to skip while waiting for a request's own response.
# On a busy PACS the server interleaves legitimate `type='broadcast'` events on the
# shared socket; a low cap (was 10) made GetSeriesImages fail with "Too many broadcast
# messages, no response received" during normal multi-workstation use (observed 43x on
# a client PC). These are valid broadcasts (not a stream desync — desync raises length
# errors, not parseable broadcasts), so skipping more of them is safe: each recv is
# socket-timeout-bounded, so a genuinely-lost response still fails, just after more
# skips. Configurable via AIPACS_MAX_BROADCAST_RETRIES.
try:
    _MAX_BROADCAST_RETRIES = max(10, int(os.getenv('AIPACS_MAX_BROADCAST_RETRIES', '50') or '50'))
except (TypeError, ValueError):
    _MAX_BROADCAST_RETRIES = 50

# Distinct non-failure marker for the same-study critical yield (2026-06-05):
# a SeriesDownloadResult carrying this error_message means "stopped cleanly at
# a batch boundary so a dragged CRITICAL series can go first" — the series is
# NOT failed; SeriesDownloader re-queues it right after the critical one.
YIELDED_TO_CRITICAL = "Yielded to critical series (batch boundary)"


def _cancelled_response(message: str = "Download cancelled (preemption)") -> Dict[str, Any]:
    """Build a normalized response for expected cancellation/preemption."""
    return {
        "status": "cancelled",
        "message": message,
        "cancelled": True,
    }


def _is_expected_preemption(exc_or_message: Any) -> bool:
    """Return True when the exception/message represents expected cancellation."""
    text = str(exc_or_message or "").lower()
    if not text:
        return False
    return (
        "preemption" in text
        or "cancelled via process cancel event" in text
        or "download cancelled" in text
    )


def _is_transient_connection_drop(exc_or_message: Any) -> bool:
    """Return True when error text indicates a dropped/broken socket that should reconnect."""
    text = str(exc_or_message or "").lower()
    if not text:
        return False
    return (
        "connection closed by server" in text
        or "connection lost while receiving data" in text
        or "forcibly closed" in text
        or "broken pipe" in text
        or "connection reset" in text
    )


_SERIES_FORCE_BATCH_ONE_MODALITIES = {
    "CR",  # Computed radiography
    "DR",  # Digital radiography (vendor variant code)
    "DX",  # Digital radiography
    "MG",  # Mammography
    "PX",  # Panoramic X-Ray
    "RADIOLOGY",
    "RF",  # Radiofluoroscopy (multi-frame, very large)
    "XA",  # X-Ray angiography (multi-frame, very large)
    "XR",
    "X-RAY",
    "XRAY",
}

# Soft byte budget per batch response (2026-06-05, large-radiology stalls):
# when a successful batch's payload exceeds this, the NEXT batches of the
# same series halve their instance count. Catches huge-frame series that the
# modality list above does not enumerate (e.g. multi-frame SC/OT, oversized
# alignment/view images) without slowing normal CT/MR batches. Per-series
# only — never persisted to the global adaptive batch size.
_BATCH_BYTES_SOFT_CAP = 64 * 1024 * 1024

# First-image prime (2026-06-17, slow/unstable-link drag-drop perception).
# On a freshly-viewed / drag-dropped series (nothing on disk yet) fetch the FIRST
# batch as a single image so the progressive feed can paint one slice in a single
# round-trip instead of waiting for a whole 10-image batch — the dominant perceived
# latency on a slow/dropping link (where first-batch time is dominated by the socket
# timeout, not transfer). After that first image is written the full adaptive batch
# size is restored, so a healthy LAN pays at most one extra round-trip for the whole
# series and bulk transfer speed is unchanged. Default on; kill switch = set
# AIPACS_FIRST_IMAGE_PRIME=0. Skipped on resume (skipped_count>0, so the R19b
# leading-batch skip is unaffected) and when batches are already forced to 1.
_FIRST_IMAGE_PRIME = (os.getenv("AIPACS_FIRST_IMAGE_PRIME", "1") or "1").strip() != "0"


def _grow_batch_size(current, max_size, consecutive_ok, growth_after, step):
    """Pure helper for adaptive batch GROWTH (2026-06-16, download speed).

    On a stable connection the download is round-trip-bound (telemetry: ~90% of
    per-series time on a LAN is request/response wait, not transfer/disk/decode),
    so fewer, larger batches = fewer round-trips = faster. Given a just-completed
    CLEAN batch, return ``(new_batch_size, new_consecutive_ok)``: after
    ``growth_after`` consecutive clean batches, grow ``current`` by ``step`` up to
    ``max_size`` and reset the streak; otherwise keep ``current`` and carry the
    incremented streak. Never exceeds ``max_size``. The caller resets the streak
    on any shrink (server "Response too large" or the 64 MB byte budget), so this
    is self-tuning and safe on a flaky link (it simply never ramps up there).
    """
    consecutive_ok += 1
    if consecutive_ok >= growth_after and current < max_size:
        return min(max_size, current + step), 0
    return current, consecutive_ok


def _first_image_prime_size(enabled, skipped_count, batch_size, force_single):
    """Pure helper for the first-image prime (2026-06-17, slow-link drag-drop).

    Return ``(first_batch_size, restore_size)``. On a freshly-viewed series (nothing
    on disk) with a multi-image batch, return ``(1, batch_size)`` so the first batch
    fetches a single slice — the viewer paints one image in one round-trip instead of
    waiting for a whole batch on a slow/dropping link — and the caller restores
    ``restore_size`` after that batch. Otherwise return ``(batch_size, None)`` (no
    prime): on resume (``skipped_count > 0`` → the R19b leading-batch skip is
    unaffected), when the modality already forces single-image batches, when the batch
    is already 1, or when disabled. ``restore_size is None`` means "no restore needed".
    """
    if enabled and skipped_count == 0 and batch_size > 1 and not force_single:
        return 1, batch_size
    return batch_size, None


_SERIES_FORCE_BATCH_ONE_DESC_KEYWORDS = (
    "PANORAM",
    "MAMMO",
    "MAMMOGRAPH",
    "RADIOGRAPH",
    "X-RAY",
    "XRAY",
)


def _should_force_single_instance_batches(series_info: SeriesInfo) -> bool:
    """Return True when a series should download one image per batch."""
    modality_raw = (getattr(series_info, "modality", "") or "").strip().upper()
    if modality_raw in {"CT", "MR", "MRI"}:
        return False
    if modality_raw in _SERIES_FORCE_BATCH_ONE_MODALITIES:
        return True

    desc_raw = (getattr(series_info, "series_description", "") or "").strip().upper()
    if not desc_raw:
        return False
    return any(token in desc_raw for token in _SERIES_FORCE_BATCH_ONE_DESC_KEYWORDS)

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
        # Read host/port from module object so subprocess constant-patching is visible
        self.host = host or _dm_consts.DEFAULT_SOCKET_HOST
        self.port = port or _dm_consts.DEFAULT_SOCKET_PORT
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

        # Same-study critical yield hook (2026-06-05): optional callable set
        # by SeriesDownloader before each series; returns the series_number
        # that should go FIRST (or None). Consulted only BETWEEN batches.
        self.yield_check = None

        # Adaptive batch size (persists across series to avoid repeated oversized requests)
        self._adaptive_batch_size = SocketDicomClient._global_adaptive_batch_size
        self._last_retry_count = 0

        # Reversible load-shaping knobs (weak-hardware friendly).
        # Set to 0 to disable pacing behavior immediately.
        self._batch_size_cap = max(1, int(os.getenv("AIPACS_DOWNLOAD_BATCH_SIZE_CAP", "10") or "10"))
        # Adaptive batch GROWTH (2026-06-16, download speed). The batch size used
        # to start at BATCH_SIZE (10) and only ever SHRINK (on "Response too large"
        # or the 64 MB byte budget) — so even a rock-solid link kept paying the
        # round-trip overhead of tiny batches (the dominant cost). Now it ramps UP
        # toward _batch_size_max after consecutive clean batches and shrinks back
        # on any error, i.e. fast on good links and safe on the flaky client.
        # Disable: AIPACS_DOWNLOAD_BATCH_GROWTH=0. Ceiling: AIPACS_DOWNLOAD_BATCH_SIZE_MAX
        # (default 40). Cadence: AIPACS_DOWNLOAD_BATCH_GROWTH_AFTER (default 2). An
        # explicitly-set AIPACS_DOWNLOAD_BATCH_SIZE_CAP still hard-caps growth.
        self._batch_growth_enabled = (os.getenv("AIPACS_DOWNLOAD_BATCH_GROWTH", "1") or "1").strip() != "0"
        _bmax = max(1, int(os.getenv("AIPACS_DOWNLOAD_BATCH_SIZE_MAX", "40") or "40"))
        if os.getenv("AIPACS_DOWNLOAD_BATCH_SIZE_CAP") is not None:
            _bmax = min(_bmax, self._batch_size_cap)  # honor an explicit operator cap
        self._batch_size_max = max(1, _bmax)
        self._batch_growth_after = max(1, int(os.getenv("AIPACS_DOWNLOAD_BATCH_GROWTH_AFTER", "2") or "2"))
        self._consecutive_ok_batches = 0
        self._inter_batch_pause_s = max(0.0, float(os.getenv("AIPACS_DOWNLOAD_INTER_BATCH_PAUSE_MS", "3") or "3") / 1000.0)
        self._post_request_yield_s = max(0.0, float(os.getenv("AIPACS_DOWNLOAD_POST_REQUEST_YIELD_MS", "5") or "5") / 1000.0)
        self._last_resource_probe_ts = 0.0
        
        logger.debug(
            f"🔌 SocketDicomClient initialized ({self.host}:{self.port})",
            extra={"component": "download"},
        )
    
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
                logger.error(f"❌ Connection failed to {self.host}:{self.port}: {e}")
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                    self.socket = None
                return False

    def _normalize_login_error_message(self, message: str) -> str:
        if not message:
            return message

        if "خطا در احراز هویت" in message:
            parts = message.split(":", 1)
            detail = parts[1].strip() if len(parts) > 1 else ""
            return f"Authentication error: {detail}" if detail else "Authentication error"

        if any(ord(ch) > 127 for ch in message):
            ascii_only = "".join(ch for ch in message if ord(ch) < 128).strip(" :")
            return f"Authentication error: {ascii_only}" if ascii_only else "Authentication error"

        return message

    def _emit_resource_probe(self, *, viewer_mode: str = "Shared", level: int = logging.WARNING) -> None:
        """Emit lightweight resource probe samples at most once per 5 seconds."""
        now_monotonic = time.monotonic()
        if now_monotonic - self._last_resource_probe_ts < 5.0:
            return
        self._last_resource_probe_ts = now_monotonic

        try:
            import psutil  # local import to keep startup path lean

            proc = psutil.Process()
            rss_mb = proc.memory_info().rss / (1024.0 * 1024.0)
            available_ram_mb = psutil.virtual_memory().available / (1024.0 * 1024.0)
            subprocess_count = len(proc.children(recursive=True))
            thread_count = proc.num_threads()

            log_stage_timing(
                logger,
                component="download",
                function="SocketDicomClient.download_series",
                stage="resource_probe",
                start_ms=now_ms(),
                process_rss_mb=f"{rss_mb:.2f}",
                available_ram_mb=f"{available_ram_mb:.2f}",
                subprocess_count=subprocess_count,
                thread_count=thread_count,
                viewer_mode=viewer_mode,
                query_type="resource_probe",
                level=level,
                min_ms=0.0,
            )
        except Exception:
            # Probe failures must never affect download behavior.
            return
    
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

    def _sleep_with_cancel(self, total_delay: float, interval_s: float = 0.1) -> bool:
        """
        Sleep in small slices so preemption can interrupt reconnect/backoff waits.

        Returns:
            True if the full delay elapsed, False if cancellation was requested.
        """
        if total_delay <= 0:
            return not self.is_cancelled()

        deadline = time.monotonic() + total_delay
        while True:
            if self.is_cancelled():
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True

            time.sleep(min(interval_s, remaining))

    async def _async_sleep_with_cancel(self, total_delay: float, interval_s: float = 0.1) -> bool:
        """
        Async variant of `_sleep_with_cancel` for retry paths inside coroutines.

        Returns:
            True if the full delay elapsed, False if cancellation was requested.
        """
        if total_delay <= 0:
            return not self.is_cancelled()

        deadline = time.monotonic() + total_delay
        while True:
            if self.is_cancelled():
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True

            await asyncio.sleep(min(interval_s, remaining))
    
    def connect_with_retry(self, max_retries: int = None, retry_delay: float = None) -> bool:
        """
        Connect to socket server with exponential backoff retry logic
        
        Args:
            max_retries: Maximum number of connection attempts (default: RECONNECT_MAX_RETRIES)
            retry_delay: Base delay between retries in seconds (default: RECONNECT_BASE_DELAY)
            
        Returns:
            True if connected, False otherwise
        """
        max_retries = max_retries if max_retries is not None else RECONNECT_MAX_RETRIES
        base_delay = retry_delay if retry_delay is not None else RECONNECT_BASE_DELAY

        for attempt in range(max_retries):
            if self.is_cancelled():
                logger.info("⏸️ connect_with_retry cancelled before attempt %s", attempt + 1)
                return False

            if self.connect():
                if attempt > 0:
                    logger.info(f"✅ Connected after {attempt + 1} attempts")
                return True
            
            if attempt < max_retries - 1:
                # Exponential backoff with jitter, capped at RECONNECT_MAX_DELAY
                delay = min(
                    base_delay * (RECONNECT_BACKOFF_FACTOR ** attempt),
                    RECONNECT_MAX_DELAY,
                )
                jitter = random.uniform(0, RECONNECT_JITTER_MAX)
                total_delay = delay + jitter
                logger.warning(
                    f"⚠️ Connection attempt {attempt + 1}/{max_retries} failed, "
                    f"retrying in {total_delay:.1f}s (backoff={delay:.1f}s + jitter={jitter:.1f}s)..."
                )
                if not self._sleep_with_cancel(total_delay):
                    logger.info("⏸️ connect_with_retry cancelled during backoff")
                    return False
        
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
                message = self._normalize_login_error_message(message)
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
        Send request to server with authentication and automatic retry on
        connection errors.  Retries use exponential backoff with jitter.

        Login requests are NOT retried (auth failures should surface immediately).

        Args:
            endpoint: Endpoint name
            params: Request parameters

        Returns:
            Response dict or None on error
        """
        # Login should not be retried automatically
        max_attempts = 1 if endpoint == 'Login' else REQUEST_MAX_RETRIES

        for attempt in range(max_attempts):
            result = self._send_request_once(endpoint, params, attempt, max_attempts)
            if result is not None:
                return result

            # If more attempts remain, wait with exponential backoff then reconnect
            if attempt < max_attempts - 1:
                # R25: never retry if download was cancelled (fast preemption path)
                if self.is_cancelled():
                    logger.info(
                        f"⏸️ send_request({endpoint}) cancelled — skipping retry"
                    )
                    return None
                jitter = random.uniform(0, RECONNECT_JITTER_MAX)
                delay = min(
                    REQUEST_RETRY_BASE_DELAY * (RECONNECT_BACKOFF_FACTOR ** attempt),
                    RECONNECT_MAX_DELAY,
                )
                total_delay = delay + jitter
                logger.warning(
                    f"⚠️ send_request({endpoint}) attempt {attempt + 1}/{max_attempts} failed, "
                    f"retrying in {total_delay:.1f}s..."
                )
                if not self._sleep_with_cancel(total_delay):
                    logger.info(
                        f"⏸️ send_request({endpoint}) cancelled during retry backoff"
                    )
                    return None

                # Reconnect before next attempt
                self.disconnect()
                if self.is_cancelled():
                    logger.info(
                        f"⏸️ send_request({endpoint}) cancelled before reconnect"
                    )
                    return None
                if not self.connect():
                    logger.error(f"❌ Reconnect failed before retry {attempt + 2}")
                    # Continue loop – connect() will be retried inside _send_request_once

        if max_attempts > 1:
            logger.error(f"❌ send_request({endpoint}) failed after {max_attempts} attempts")
        return None

    def _send_request_once(
        self, endpoint: str, params: Dict[str, Any],
        attempt: int = 0, max_attempts: int = 1,
    ) -> Optional[Dict[str, Any]]:
        """Single attempt of send_request (internal helper)."""
        logger.debug(f"📤 send_request: {endpoint} attempt {attempt+1}/{max_attempts} - acquiring lock...")
        t_req_total = now_ms()
        t_lock_wait = now_ms()
        self.lock.acquire()
        log_stage_timing(
            logger,
            component="ipc",
            function="SocketDicomClient.send_request",
            stage="request_lock_wait",
            start_ms=t_lock_wait,
            endpoint=endpoint,
        )

        try:
            logger.debug(f"📤 send_request: {endpoint} - lock acquired")

            if not self.connected:
                logger.debug(f"📤 send_request: Not connected, attempting connection...")
                if not self.connect():
                    logger.error(f"❌ send_request: Connection failed!")
                    return None
                logger.debug(f"📤 send_request: Connected successfully")

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
                        logger.debug(f"🔐 Added explicit auth token to {endpoint} request")
                    elif self.token_manager and self.token_manager.has_token():
                        request = self.token_manager.add_token_to_request(request)
                        logger.debug(f"🔐 Added token from manager to {endpoint} request")
                    else:
                        logger.warning(f"⚠️ No auth token available for {endpoint}")

                # Serialize to JSON
                t_serialize = now_ms()
                request_json = json.dumps(request, ensure_ascii=False)
                request_bytes = request_json.encode('utf-8')
                log_stage_timing(
                    logger,
                    component="ipc",
                    function="SocketDicomClient.send_request",
                    stage="request_serialize",
                    start_ms=t_serialize,
                    endpoint=endpoint,
                )

                logger.info(
                    f"📤 Sending {endpoint} request ({len(request_bytes)} bytes)",
                    extra={"component": "ipc"},
                )

                # Send length prefix (4 bytes, big endian)
                t_send = now_ms()
                length_bytes = len(request_bytes).to_bytes(4, byteorder='big')
                self.socket.sendall(length_bytes)

                # Send request data
                self.socket.sendall(request_bytes)
                log_stage_timing(
                    logger,
                    component="ipc",
                    function="SocketDicomClient.send_request",
                    stage="request_send",
                    start_ms=t_send,
                    endpoint=endpoint,
                    request_bytes=str(len(request_bytes)),
                )
                logger.debug(f"📤 Request sent, waiting for response...")

                # Loop to handle broadcasts and wait for actual response. Cap raised
                # + made configurable (was a hard 10) — see _MAX_BROADCAST_RETRIES.
                max_broadcast_retries = _MAX_BROADCAST_RETRIES
                broadcast_count = 0
                
                while broadcast_count < max_broadcast_retries:
                    # Receive response length
                    logger.debug(f"📥 Waiting for response header (4 bytes)...")
                    t_recv_header = now_ms()
                    response_length_bytes = self._safe_recv(4)
                    if not response_length_bytes:
                        raise NetworkError("Connection closed by server")
                    log_stage_timing(
                        logger,
                        component="ipc",
                        function="SocketDicomClient.send_request",
                        stage="response_header_recv",
                        start_ms=t_recv_header,
                        endpoint=endpoint,
                    )

                    response_length = int.from_bytes(response_length_bytes, byteorder='big')

                    # Validate response length to prevent extremely large allocations.
                    # An implausibly large length means the socket stream has
                    # desynchronized — the 4 "length" bytes are really payload
                    # bytes. The generic except handler below does NOT treat
                    # "Response too large" as a transient drop, so without this
                    # the corrupt socket would be reused and keep mis-reading
                    # garbage lengths on every subsequent request. Drop the
                    # socket here so the next request reconnects on a clean
                    # stream instead of cascading the same error.
                    if response_length > 500 * 1024 * 1024:  # 500MB limit
                        try:
                            if self.socket:
                                self.socket.close()
                        except Exception:
                            pass
                        self.socket = None
                        self.connected = False
                        raise NetworkError(f"Response too large: {response_length} bytes")

                    logger.debug(
                        f"📥 Receiving response body ({response_length} bytes)",
                        extra={"component": "download"},
                    )

                    # Receive response data.
                    # bytearray + extend is amortized O(n); the previous
                    # ``bytes += chunk`` was O(n²) — for a 300 MB radiology
                    # batch in 64 KB chunks that is terabytes of memcpy and
                    # minutes of CPU, which presented as a "stuck" download
                    # (large-batch stall, 2026-06-05).
                    t_body_recv = now_ms()
                    response_data = bytearray()
                    summary_key = (
                        f"{endpoint}:{str(params.get('series_uid', 'na'))[:24]}:"
                        f"{params.get('batch_index', 'na')}"
                    )
                    while len(response_data) < response_length:
                        # R25: fast preemption — check cancel before every chunk so a
                        # 37-second batch can be interrupted within a single chunk recv
                        # instead of waiting for the entire batch to complete.
                        if self.is_cancelled():
                            try:
                                if self.socket:
                                    self.socket.close()
                            except Exception:
                                pass
                            self.socket = None
                            self.connected = False
                            raise NetworkError("Download cancelled during receive (preemption)")
                        chunk_size = min(SOCKET_CHUNK_SIZE, response_length - len(response_data))
                        chunk = self._safe_recv(chunk_size)
                        if not chunk:
                            raise NetworkError("Connection lost while receiving data")
                        response_data.extend(chunk)
                        if response_length > 100000:
                            _download_progress_aggregator.update(
                                key=summary_key,
                                response_length=response_length,
                                bytes_received=len(response_data),
                                retries=0,
                                study_uid="-",
                                series_uid=str(params.get("series_uid", "-")),
                            )

                    logger.debug(
                        f"📥 Response received completely ({len(response_data)} bytes)",
                        extra={"component": "download", "series_uid": str(params.get("series_uid", "-"))},
                    )
                    log_stage_timing(
                        logger,
                        component="download",
                        function="SocketDicomClient.send_request",
                        stage="response_body_recv",
                        start_ms=t_body_recv,
                        endpoint=endpoint,
                        response_bytes=str(len(response_data)),
                    )

                    # Parse response (tolerant decode: a non-UTF-8 byte in a name/
                    # description field must not crash the whole download).
                    t_parse = now_ms()
                    response = json.loads(_decode_socket_payload(response_data))
                    log_stage_timing(
                        logger,
                        component="ipc",
                        function="SocketDicomClient.send_request",
                        stage="response_parse",
                        start_ms=t_parse,
                        endpoint=endpoint,
                    )
                    
                    # Check if this is a broadcast message
                    if response.get('type') == 'broadcast':
                        broadcast_count += 1
                        event_type = response.get('event_type', 'unknown')
                        logger.debug(
                            f"📡 Received broadcast message (type: {event_type}), continuing to wait for actual response... ({broadcast_count}/{max_broadcast_retries})"
                        )
                        continue  # Skip this broadcast and wait for the actual response
                    
                    # This is the actual response
                    logger.info(
                        f"📥 Response parsed: status={response.get('status', 'unknown')}",
                        extra={"component": "ipc"},
                    )
                    log_stage_timing(
                        logger,
                        component="ipc",
                        function="SocketDicomClient.send_request",
                        stage="request_total",
                        start_ms=t_req_total,
                        endpoint=endpoint,
                        result=str(response.get("status", "unknown")),
                    )
                    return response
                
                # If we exit the loop, we received too many broadcasts without a response
                logger.error(f"❌ Received {broadcast_count} broadcasts without getting actual response")
                raise NetworkError(f"Too many broadcast messages, no response received")

            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
                if self.is_cancelled() or _is_expected_preemption(e):
                    logger.info(f"⏸️ Request cancelled for {endpoint}: {e}")
                    self.connected = False
                    if self.socket:
                        try:
                            self.socket.close()
                        except Exception:
                            pass
                        self.socket = None
                    return _cancelled_response()
                logger.error(f"❌ Connection reset error for {endpoint}: {e}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                # Mark connection as broken and clean up
                self.connected = False
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                    self.socket = None
                # R30: Record failure for health monitoring
                self.health_monitor.record_failure()
                return None
            except Exception as e:
                if self.is_cancelled() or _is_expected_preemption(e):
                    logger.info(f"⏸️ Request cancelled for {endpoint}: {e}")
                    self.connected = False
                    if self.socket:
                        try:
                            self.socket.close()
                        except Exception:
                            pass
                        self.socket = None
                    return _cancelled_response()
                logger.error(f"❌ Request error for {endpoint}: {e}")
                import traceback
                logger.error(f"❌ Traceback: {traceback.format_exc()}")
                # U1 (other-PC production logs, 2026-06-05): surface
                # "Response too large" to the batch-download caller instead of
                # collapsing it to None. The socket has already been dropped at
                # the raise site (clean reconnect on the next request);
                # returning None here made download_series see only
                # 'No response', so its adaptive batch-halving branch never
                # fired and the series failed outright (16 production
                # failures). Scoped to GetSeriesImages so every other
                # endpoint's None-on-error contract is unchanged.
                if endpoint == 'GetSeriesImages' and "Response too large" in str(e):
                    return {'status': 'error', 'error': str(e), 'message': str(e)}
                # Handle other socket errors that indicate connection problems
                if (
                    isinstance(e, (socket.error, OSError, NetworkError))
                    and _is_transient_connection_drop(e)
                ):
                    self.connected = False
                    if self.socket:
                        try:
                            self.socket.close()
                        except Exception:
                            pass
                        self.socket = None
                    # R30: Record failure for health monitoring
                    self.health_monitor.record_failure()
                return None
        finally:
            try:
                self.lock.release()
            except Exception:
                pass

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
                except Exception:
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
                    except Exception:
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
        
        set_log_context(study_uid=study_uid, series_uid=series_uid)
        logger.debug(
            f"📥 download_batch: series={series_uid[:40]}..., batch_index={batch_index}, size={batch_size}",
            extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
        )
        
        # Use correct endpoint: GetSeriesImages (not DownloadDicomBatch)
        response = self.send_request('GetSeriesImages', {
            'series_uid': series_uid,
            'batch_size': batch_size,
            'batch_index': batch_index,
            'metadata_only': False
        })
        
        if response:
            status = response.get('status', 'unknown')
            if status == 'cancelled':
                logger.warning(
                    f"⏸️ download_batch cancelled: {response.get('message', 'preemption')}",
                    extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
                )
            else:
                logger.debug(
                    f"📥 download_batch: status={status}",
                    extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
                )
        else:
            if self.is_cancelled():
                logger.info(f"⏸️ download_batch cancelled before response")
            else:
                logger.warning(f"📥 download_batch: No response received!")

        return response

    def _poor_connectivity_active(self) -> bool:
        """Is the active download server in "Poor Connectivity" / unstable-internet
        single-image download mode?

        Resolved from ``config/servers.json`` (per-server ``poor_connectivity`` flag,
        matched by the active socket host) or the ``AIPACS_POOR_CONNECTIVITY`` env
        override — see ``modules.network.socket_config.is_poor_connectivity_enabled``.

        Cached per client instance: the flag is per-server and the client is built
        per download task, so it is stable for this client's lifetime and this avoids
        re-reading config on every series. Any failure resolves to ``False`` so a
        config/import problem can never break downloading.
        """
        cached = getattr(self, "_poor_conn_cached", None)
        if cached is not None:
            return cached
        val = False
        try:
            from modules.network.socket_config import (
                is_poor_connectivity_enabled as _ipc,
            )
            val = bool(_ipc())
        except Exception:
            val = False
        self._poor_conn_cached = val
        return val

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
        
        set_log_context(study_uid=study_uid, series_uid=series_uid)
        logger.warning(
            f"📥 Downloading series {series_number} ({expected_count} images)",
            extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
        )
        
        # Create output directory
        logger.info(f"📁 Creating output directory: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"✅ Output directory ready")
        
        # Check for existing files (R19: file-level resume)
        logger.info(f"🔍 Scanning for existing files...")
        existing_files = self._scan_existing_files(output_dir)
        existing_files_set = set(existing_files)  # for O(1) lookup in per-instance skip
        skipped_count = len(existing_files)
        logger.info(f"📊 Found {skipped_count} existing files")
        
        # Calculate batches (adaptive + configurable cap). Ceiling is
        # _batch_size_max so a stable connection can ramp UP (see _grow_batch_size);
        # _adaptive_batch_size still starts conservative and shrinks on errors.
        batch_size = min(self._adaptive_batch_size, self._batch_size_max)
        _modality_force_single = _should_force_single_instance_batches(series_info)
        if _modality_force_single:
            batch_size = 1
            logger.info(
                "📦 Using single-image batches for large-frame modality/series type "
                f"(series={series_number}, modality={series_info.modality or 'N/A'})"
            )
        # Per-server "Poor Connectivity" mode (config/servers.json `poor_connectivity`,
        # resolved by the active socket host): force single-image batches and disable
        # adaptive growth so a flaky/unstable link retries at the IMAGE level and keeps
        # every image already on disk, instead of failing/re-fetching a whole batch.
        # Same proven mechanism as the large-frame modality force above.
        _poor_conn = self._poor_connectivity_active()
        if _poor_conn:
            batch_size = 1
            logger.warning(
                "🐢 [POOR_CONN] server flagged poor-connectivity/unstable-internet → "
                "single-image batches (batch_size=1), adaptive growth disabled, "
                "image-level retry + resume "
                f"(series={series_number}, modality={series_info.modality or 'N/A'}, "
                f"expected={expected_count})"
            )
        # Either condition pins the series to one image per batch (no ramp-up below).
        _force_single = _modality_force_single or _poor_conn
        min_batch_size = 1
        # First-image prime: on a fresh series (nothing on disk) fetch slice 1 as a
        # single-image batch so the viewer paints one image in one round-trip, then
        # restore the full adaptive size after that batch (see the advance below).
        # Skipped on resume (skipped_count>0 → R19b leading-batch skip unaffected) and
        # when the modality already forces single-image batches. _prime_restore_size is
        # the size to jump back to; None means "no prime active for this series".
        # _prime_restore_size is the size to jump back to after the size-1 first
        # batch; None means "no prime active for this series" (see the advance below).
        batch_size, _prime_restore_size = _first_image_prime_size(
            _FIRST_IMAGE_PRIME,
            skipped_count,
            batch_size,
            _force_single,
        )
        if _prime_restore_size is not None:  # total_batches is computed from batch_size below
            # WARNING level (not info) so this is captured in download_diagnostics.log:
            # socket_client INFO is filtered there, which previously made the prime
            # impossible to observe at runtime (2026-06-18 review). Behaviour unchanged.
            logger.warning(
                f"⚡ First-image prime: fetching slice 1 of series {series_number} as a "
                f"single-image batch, then resuming batch size {_prime_restore_size}"
            )
        # U1: bounded same-size retries once the batch can't shrink further.
        # An implausible declared length (>500MB) usually means the socket
        # stream desynchronized, not real payload size — the socket has been
        # dropped, so retrying the same batch on a fresh connection is the
        # correct recovery. Reset on every successful batch.
        _TOO_LARGE_MIN_BATCH_RETRIES = 2
        too_large_retries = 0
        _batch_payload_bytes = 0  # set per successful batch (byte-budget cap)
        total_batches = (expected_count + batch_size - 1) // batch_size
        downloaded_count = 0
        # DL-9: file names written by this run. Together with existing_files_set
        # (the pre-download os.listdir snapshot) this resolves file presence in
        # memory, removing one stat() syscall per instance in the loop below.
        written_this_run = set()

        logger.info(f"📦 Will download in {total_batches} batches (batch size: {batch_size})")
        
        start_time = time.time()
        summary_last_t = time.monotonic()
        summary_last_count = 0
        total_disk_write_ms = 0.0
        total_decode_ms = 0.0
        total_decompress_ms = 0.0
        total_write_bytes = 0
        
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
        # R19b: Skip leading complete batches — avoids re-transferring data
        # for images already on disk (e.g. resuming a partially-downloaded series).
        # Verifies actual sequential file existence to avoid skipping batches
        # that have gaps (v2.2.7.3 fix).
        batch_start = 0
        if skipped_count >= batch_size:
            # Verify leading batches by checking that sequential Instance files exist.
            # Only skip a batch if ALL its expected instance files are on disk.
            verified_batch_start = 0
            while verified_batch_start + batch_size <= expected_count:
                batch_end = verified_batch_start + batch_size
                batch_complete = all(
                    f"Instance_{i:04d}.dcm" in existing_files_set
                    for i in range(verified_batch_start + 1, batch_end + 1)
                )
                if not batch_complete:
                    break
                verified_batch_start += batch_size
            batch_start = verified_batch_start
            if batch_start > 0:
                remaining = expected_count - batch_start
                total_batches = (remaining + batch_size - 1) // batch_size if remaining > 0 else 0
                logger.info(
                    f"⏩ Verified {batch_start // batch_size} complete leading batches "
                    f"({batch_start} sequential instances on disk), {total_batches} batches remaining"
                )
            else:
                logger.info(
                    f"⚠️ {skipped_count} files on disk but leading batch incomplete — "
                    f"downloading from batch 0 (file-level skip will handle existing files)"
                )
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

            # Same-study critical yield (2026-06-05, drag-drop priority):
            # between batches — never mid-batch — ask the owner whether a
            # DIFFERENT series of this study has been promoted to CRITICAL
            # (viewer drag-drop). If so, stop cleanly AFTER the just-finished
            # batch with a distinct, non-failure marker. Files already on
            # disk are kept (R19 resume skips them when this series gets its
            # turn again). The current batch always completes; no new batch
            # for this series is requested past this point. The hook is
            # best-effort: any exception keeps the normal flow.
            if getattr(self, "yield_check", None) is not None:
                try:
                    _yield_target = self.yield_check()
                except Exception:
                    _yield_target = None
                if _yield_target and str(_yield_target) != str(series_number):
                    logger.info(
                        f"⚡ Yielding after batch {batch_idx}/{total_batches} of series "
                        f"{series_number} — critical series {_yield_target} is waiting"
                    )
                    return SeriesDownloadResult(
                        success=False,
                        series_uid=series_uid,
                        series_number=series_number,
                        downloaded=downloaded_count,
                        skipped=skipped_count,
                        total=expected_count,
                        elapsed_seconds=time.time() - start_time,
                        error_message=YIELDED_TO_CRITICAL,
                    )
            
            logger.debug(
                f"📦 Starting batch {batch_idx + 1}/{total_batches} (start: {batch_start}, size: {batch_size})",
                extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
            )
            
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
            
            logger.debug(f"📦 Batch {batch_idx + 1} response received: {response is not None}")

            if response and response.get('status') == 'cancelled':
                logger.info(f"⏸️ Batch {batch_idx + 1} cancelled by preemption")
                return SeriesDownloadResult(
                    success=False,
                    series_uid=series_uid,
                    series_number=series_number,
                    downloaded=downloaded_count,
                    skipped=skipped_count,
                    total=expected_count,
                    elapsed_seconds=time.time() - start_time,
                    error_message=response.get('message', 'Download cancelled (preemption)')
                )
            
            if not response or response.get('status') != 'success':
                # Better error extraction with full response logging
                if response:
                    error_msg = response.get('error') or response.get('message') or response.get('msg', 'Unknown error')
                    logger.error(f"❌ Batch {batch_idx + 1} failed: {error_msg}")
                    logger.error(f"❌ Full response for debugging: {response}")
                else:
                    error_msg = 'No response'
                    logger.error(f"❌ Batch {batch_idx + 1} failed: {error_msg}")

                if "Response too large" in str(error_msg):
                    if batch_size > min_batch_size:
                        batch_size = max(min_batch_size, batch_size // 2)
                        self._adaptive_batch_size = batch_size
                        SocketDicomClient._global_adaptive_batch_size = batch_size
                        self._consecutive_ok_batches = 0  # reset growth streak on shrink
                        total_batches = (expected_count + batch_size - 1) // batch_size
                        logger.warning(
                            f"⚠️ Response too large - reducing batch size to {batch_size} and retrying batch"
                        )
                        continue
                    if too_large_retries < _TOO_LARGE_MIN_BATCH_RETRIES:
                        too_large_retries += 1
                        logger.warning(
                            f"⚠️ Response too large at minimum batch size — retrying "
                            f"batch {batch_idx + 1} on a fresh socket "
                            f"({too_large_retries}/{_TOO_LARGE_MIN_BATCH_RETRIES}, "
                            f"stream-desync recovery)"
                        )
                        continue
                    # Exhausted: fall through to the failure result below —
                    # error_msg now carries the real reason ("Response too
                    # large: N bytes"), which surfaces in the DM badge
                    # instead of the former opaque 'No response'.

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
            
            # Successful batch → reset the U1 desync-retry budget so it is
            # per-incident, not per-series.
            too_large_retries = 0

            # Process instances in batch (using GetSeriesImages response format)
            data = response.get('data', {})
            instances = data.get('instances', [])
            # Payload estimate (base64 chars ≈ bytes) for the byte-budget
            # soft cap applied after this batch's advance.
            _batch_payload_bytes = sum(
                len(inst.get('dicom_data') or '') for inst in instances
            )
            
            logger.debug(
                f"📦 Batch {batch_idx + 1}: Got {len(instances)} instances",
                extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
            )
            
            batch_write_stage_start = now_ms()
            batch_disk_write_ms = 0.0
            batch_write_bytes = 0
            batch_files_written = 0

            for _inst_idx, instance_data in enumerate(instances):
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
                
                # Skip if exists (R19: file-level resume).
                # DL-9: resolved in memory instead of a per-instance exists()
                # syscall. existing_files_set is the authoritative pre-download
                # snapshot; written_this_run tracks files saved by this run.
                if file_name in existing_files_set:
                    continue  # pre-existing file, already counted in skipped_count
                if file_name in written_this_run:
                    # Duplicate instance within this run — not in the initial
                    # scan, so count it as newly skipped (matches prior behavior).
                    skipped_count += 1
                    continue
                
                if not dicom_data_b64:
                    logger.warning(f"⚠️ Empty DICOM data for instance {instance_number}")
                    continue
                
                try:
                    # Decode base64
                    t_decode = now_ms()
                    dicom_bytes = base64.b64decode(dicom_data_b64)
                    total_decode_ms += max(0.0, now_ms() - t_decode)
                    
                    # Decompress if needed
                    if is_compressed:
                        t_decompress = now_ms()
                        dicom_bytes = gzip.decompress(dicom_bytes)
                        total_decompress_ms += max(0.0, now_ms() - t_decompress)
                    
                    # Ensure directory exists (defensive check for preemption recovery)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Save file ATOMICALLY (DM-H2): write to a .part temp then
                    # os.replace() onto the final name. os.replace is atomic on
                    # the same volume, so a crash/preemption mid-write can only
                    # ever leave a *.dcm.part file — never a truncated
                    # Instance_NNNN.dcm that the name-based resume scan would
                    # wrongly treat as a complete instance.
                    t_write = time.monotonic()
                    tmp_path = file_path.with_name(file_path.name + '.part')
                    with open(tmp_path, 'wb') as f:
                        f.write(dicom_bytes)
                    os.replace(tmp_path, file_path)
                    write_elapsed_ms = (time.monotonic() - t_write) * 1000.0
                    
                    downloaded_count += 1
                    written_this_run.add(file_name)  # DL-9: track for in-memory skip
                    total_disk_write_ms += write_elapsed_ms
                    batch_disk_write_ms += write_elapsed_ms
                    batch_write_bytes += len(dicom_bytes)
                    total_write_bytes += len(dicom_bytes)
                    batch_files_written += 1

                    # ── Issue A (46472 DX) — surface header-only image stubs ──────
                    # The server can return a DICOM whose header is intact but whose
                    # PixelData element is EMPTY. It decodes to non-empty bytes (so the
                    # `if not dicom_data_b64` guard above misses it), is written as a
                    # normal .dcm, and the name+128B resume scan (DM-L4) then treats it
                    # as a COMPLETE instance — so it is never re-fetched and renders
                    # blank, which makes the study look "missing". Surface it loudly so
                    # the condition is never silent again; the actual display fix is
                    # server-side (the pixel data must be re-sent). LOGGING ONLY — no
                    # change to download/resume control flow. Bounded + precise: only
                    # inspect small payloads (real images are far larger) and only flag
                    # a dataset that DECLARES image pixels but carries none (SR/PDF/PR
                    # have no Rows/Columns and are never flagged). Disable with
                    # AIPACS_PIXELLESS_STUB_PROBE=0.
                    try:
                        if (os.environ.get('AIPACS_PIXELLESS_STUB_PROBE', '1') != '0'
                                and len(dicom_bytes) < 32768):
                            import pydicom as _pydicom
                            from io import BytesIO as _BytesIO
                            _ds = _pydicom.dcmread(_BytesIO(dicom_bytes), force=True)
                            _rows = getattr(_ds, 'Rows', None)
                            _cols = getattr(_ds, 'Columns', None)
                            _bits = getattr(_ds, 'BitsAllocated', None)
                            _declares_image = bool(_rows) and bool(_cols) and bool(_bits)
                            _pixels_present = bool(_ds.get('PixelData', None))
                            if _declares_image and not _pixels_present:
                                logger.warning(
                                    "[DOWNLOAD][pixelless-stub] header-only image written "
                                    "(empty PixelData) — renders blank and the name/128B "
                                    "resume scan treats it as complete (DM-L4); pixel data "
                                    "must be re-sent server-side. file=%s series=%s "
                                    "instance=%s bytes=%d dims=%sx%sx%s",
                                    file_path, series_number, instance_number,
                                    len(dicom_bytes), _rows, _cols, _bits,
                                )
                    except Exception:
                        pass

                except Exception as e:
                    logger.error(f"❌ Error saving instance {instance_number}: {e}")
                    # Log the full path for debugging
                    logger.error(f"   File path: {file_path}")
                    logger.error(f"   Directory exists: {file_path.parent.exists()}")
                    # DM-H2: drop any partial .part temp so it cannot linger and
                    # so the next attempt starts clean.
                    try:
                        _tmp = file_path.with_name(file_path.name + '.part')
                        if _tmp.exists():
                            _tmp.unlink()
                    except Exception:
                        pass
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

                    now = time.monotonic()
                    if (downloaded_count + skipped_count == expected_count) or (now - summary_last_t >= 2.0):
                        delta_items = (downloaded_count + skipped_count) - summary_last_count
                        delta_t = max(now - summary_last_t, 1e-6)
                        throughput_items = delta_items / delta_t
                        logger.warning(
                            "series-summary series=%s downloaded=%d skipped=%d total=%d throughput_items=%.2f/s queue=%d active=%d disk_write_ms=%.2f decode_ms=%.2f decompress_ms=%.2f retries=%d",
                            series_number,
                            downloaded_count,
                            skipped_count,
                            expected_count,
                            throughput_items,
                            max(total_batches - (batch_idx + 1), 0),
                            1,
                            total_disk_write_ms,
                            total_decode_ms,
                            total_decompress_ms,
                            int(getattr(self, "_last_retry_count", 0)),
                            extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
                        )
                        summary_last_t = now
                        summary_last_count = downloaded_count + skipped_count

                # Yield GIL every 3 instances: a real 2 ms OS sleep releases
                # the Python GIL so the Qt viewer thread can render between
                # consecutive base64 decode calls without stalling ~50 ms.
                if _inst_idx > 0 and _inst_idx % 3 == 0:
                    await asyncio.sleep(0.002)

            if batch_files_written:
                log_stage_timing(
                    logger,
                    component="download",
                    function="SocketDicomClient.download_series",
                    stage="dicom_file_write_batch",
                    start_ms=batch_write_stage_start,
                    files=batch_files_written,
                    bytes=batch_write_bytes,
                    disk_write_ms=f"{batch_disk_write_ms:.2f}",
                    query_type="disk_write",
                    viewer_mode="Shared",
                    level=logging.INFO,
                    min_ms=0.0,
                )
            
            # Check if more batches are needed (server pagination)
            has_more = data.get('has_more', False)
            if not has_more:
                logger.info(f"📦 Server indicates no more batches")
                break

            # Small paced gap between batches to reduce burst CPU/network pressure
            # on low-end systems while preserving steady download progress.
            if self._inter_batch_pause_s > 0:
                await asyncio.sleep(self._inter_batch_pause_s)

            batch_idx += 1
            batch_start += batch_size

            # First-image prime restore: the priming size-1 batch (batch_idx 0) has
            # now been written and its progress emitted, so restore the full adaptive
            # batch size for the remainder — bulk transfer speed is unchanged. The
            # advance above used the OLD size (1), so batch_start is now exactly 1 and
            # the next request is correctly aligned to slice index 1. Run before the
            # shrink/grow block below so adaptive tuning continues from the full size.
            if _prime_restore_size is not None and batch_idx == 1:
                batch_size = _prime_restore_size
                total_batches = (expected_count + batch_size - 1) // batch_size
                _prime_restore_size = None

            # Byte-budget soft cap: halve the NEXT batches when this one's
            # payload was oversized. Applied AFTER the advance so the just-
            # received window is never re-requested; halving keeps
            # batch_start aligned to the new size (start = k*old = 2k*new),
            # so the server's batch_index mapping stays exact.
            _payload_oversized = _batch_payload_bytes > _BATCH_BYTES_SOFT_CAP
            if _payload_oversized and batch_size > min_batch_size:
                batch_size = max(min_batch_size, batch_size // 2)
                total_batches = (expected_count + batch_size - 1) // batch_size
                self._consecutive_ok_batches = 0  # reset growth streak on shrink
                logger.warning(
                    f"📉 Batch payload {_batch_payload_bytes / (1024*1024):.0f} MB "
                    f"exceeds {_BATCH_BYTES_SOFT_CAP // (1024*1024)} MB soft cap — "
                    f"halving subsequent batches of series {series_number} to "
                    f"{batch_size} instance(s)"
                )
            elif _payload_oversized:
                # Already at the minimum batch size — cannot shrink further, but a
                # large payload means we must NOT grow either.
                self._consecutive_ok_batches = 0
            elif (
                self._batch_growth_enabled
                and batch_size < self._batch_size_max
                and not _force_single
            ):
                # Adaptive batch GROWTH (2026-06-16, download speed): on a stable
                # connection ramp the batch size UP so a healthy link pays fewer
                # round-trips (the dominant cost). Bounded by _batch_size_max and
                # reset by either shrink path above, so it is self-tuning and safe
                # on the flaky client.
                _new, self._consecutive_ok_batches = _grow_batch_size(
                    batch_size, self._batch_size_max, self._consecutive_ok_batches,
                    self._batch_growth_after, BATCH_SIZE,
                )
                if _new != batch_size:
                    batch_size = _new
                    self._adaptive_batch_size = batch_size
                    SocketDicomClient._global_adaptive_batch_size = batch_size
                    total_batches = (expected_count + batch_size - 1) // batch_size
                    logger.info(
                        f"⏫ Stable connection — grew batch size to {batch_size} "
                        f"(max {self._batch_size_max}) for series {series_number}"
                    )

        # Download diagnostics default to WARNING threshold. Emit one summary
        # write-stage sample per series at WARNING so KPI parsers can
        # consistently observe disk write telemetry in canonical logs.
        if total_disk_write_ms > 0.0 and downloaded_count > 0:
            synthetic_start_ms = now_ms() - total_disk_write_ms
            log_stage_timing(
                logger,
                component="download",
                function="SocketDicomClient.download_series",
                stage="dicom_file_write_batch",
                start_ms=synthetic_start_ms,
                files=downloaded_count,
                bytes=total_write_bytes,
                disk_write_ms=f"{total_disk_write_ms:.2f}",
                query_type="disk_write",
                viewer_mode="Shared",
                level=logging.WARNING,
                min_ms=0.0,
            )
            self._emit_resource_probe(viewer_mode="Shared", level=logging.WARNING)
        
        elapsed = time.time() - start_time
        
        logger.warning(
            f"✅ Series {series_number} complete: "
            f"{downloaded_count} downloaded, {skipped_count} skipped ({elapsed:.1f}s)",
            extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
        )
        logger.warning(
            "download-pipeline-summary series=%s elapsed_s=%.2f disk_write_ms=%.2f decode_ms=%.2f decompress_ms=%.2f",
            series_number,
            elapsed,
            total_disk_write_ms,
            total_decode_ms,
            total_decompress_ms,
            extra={"component": "download", "study_uid": study_uid, "series_uid": series_uid},
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
            valid = []
            for name in os.listdir(output_dir):
                # endswith('.dcm') also excludes leftover *.dcm.part temp files
                # written by the atomic-write path (DM-H2).
                if not name.endswith('.dcm'):
                    continue
                try:
                    # DM-H2: a file shorter than the 128-byte DICOM preamble
                    # cannot be a complete instance — treat it as a partial
                    # write and leave it out so the downloader re-fetches it
                    # instead of skipping it as "already present".
                    if os.path.getsize(os.path.join(output_dir, name)) < 128:
                        logger.warning(f"⚠️ Ignoring incomplete DICOM on resume: {name}")
                        continue
                except OSError:
                    continue
                valid.append(name)
            return valid
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
        logger.debug(f"🔄 _download_batch_with_retry called: series={series_uid[:30]}..., start={batch_start}, size={batch_size}")
        self._last_retry_count = 0
        
        for attempt in range(MAX_RETRIES):
            # R25: Check for cancellation before each attempt
            if self.is_cancelled():
                logger.info(f"⏸️ Batch download cancelled")
                return _cancelled_response()
            
            request_start = time.time()
            
            try:
                logger.debug(f"🔄 Attempt {attempt + 1}/{MAX_RETRIES}: Calling download_batch...")
                response = self.download_batch(study_uid, series_uid, batch_start, batch_size)
                logger.debug(f"🔄 Attempt {attempt + 1}: Got response: {response is not None}")

                # Yield GIL immediately after the blocking recv+json.loads call
                # so the Qt main thread can advance its render loop before we
                # start processing the batch payload.
                # sleep(0.005) is a real OS sleep that releases the GIL to
                # other threads (viewer, warmup); sleep(0) only yields within
                # the same event-loop and does NOT reliably free the GIL.
                if self._post_request_yield_s > 0:
                    await asyncio.sleep(self._post_request_yield_s)

                if response:
                    status = response.get('status', 'unknown')
                    if status == 'cancelled':
                        logger.info(f"⏸️ Batch attempt {attempt + 1} cancelled")
                        return response
                    logger.debug(f"🔄 Response status: {status}")
                    
                    # R30: Record success with latency
                    latency_ms = (time.time() - request_start) * 1000
                    self.health_monitor.record_success(latency_ms)
                    
                    return response
                else:
                    if self.is_cancelled():
                        logger.info(f"⏸️ Attempt {attempt + 1}: Cancelled before response")
                        return _cancelled_response()
                    logger.warning(f"⚠️ Attempt {attempt + 1}: Empty response")
                    # R30: Record failure
                    self.health_monitor.record_failure()
            
            except Exception as e:
                if self.is_cancelled() or _is_expected_preemption(e):
                    logger.info(f"⏸️ Batch download attempt {attempt + 1} cancelled: {e}")
                    return _cancelled_response()
                logger.warning(f"⚠️ Batch download attempt {attempt + 1} failed: {e}")
                self._last_retry_count = attempt + 1
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
                        logger.warning(f"⚠️ Unhealthy connection - doubling retry delay", extra={"component": "download"})
                    
                    logger.warning(f"⏳ Retrying in {delay:.1f}s...", extra={"component": "download"})
                    if not await self._async_sleep_with_cancel(delay):
                        logger.debug("⏸️ Batch retry cancelled during backoff")
                        return None

                    if self.is_cancelled():
                        logger.debug("⏸️ Batch retry cancelled before reconnect")
                        return None
                    
                    # Reconnect with backoff
                    logger.warning(f"🔌 Reconnecting...", extra={"component": "download"})
                    self.disconnect()
                    if not self.connect_with_retry(max_retries=3):
                        if self.is_cancelled():
                            logger.debug("⏸️ Batch retry reconnect cancelled")
                            return None
                        logger.error(f"❌ Reconnection failed")
                        continue
                    logger.warning(f"✅ Reconnected", extra={"component": "download"})
        
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
        except Exception:
            # Don't raise exceptions in destructor
            pass
