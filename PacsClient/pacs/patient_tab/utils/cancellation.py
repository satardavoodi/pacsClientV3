"""
Cancellation support for long-running operations
Provides cancellation tokens and cooperative cancellation
"""
import threading
import time
from typing import Optional, Callable
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class CancellationToken:
    """
    Token for cancellation signaling
    Thread-safe cancellation mechanism
    """
    _cancelled: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cancel_callbacks: list = field(default_factory=list)
    _reason: Optional[str] = None
    
    def cancel(self, reason: str = "Operation cancelled by user"):
        """
        Cancel the operation
        
        Args:
            reason: Reason for cancellation
        """
        with self._lock:
            if self._cancelled.is_set():
                logger.debug("Already cancelled")
                return
            
            self._reason = reason
            self._cancelled.set()
            logger.info(f"Cancellation requested: {reason}")
            
            # Call all registered callbacks
            for callback in self._cancel_callbacks:
                try:
                    callback(reason)
                except Exception as e:
                    logger.error(f"Error in cancellation callback: {e}")
    
    def is_cancelled(self) -> bool:
        """Check if cancelled"""
        return self._cancelled.is_set()
    
    def throw_if_cancelled(self):
        """Raise exception if cancelled"""
        if self.is_cancelled():
            raise CancellationError(self._reason or "Operation cancelled")
    
    def wait(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for cancellation
        
        Args:
            timeout: Maximum time to wait in seconds
        
        Returns:
            True if cancelled, False if timeout
        """
        return self._cancelled.wait(timeout=timeout)
    
    def register_callback(self, callback: Callable[[str], None]):
        """
        Register a callback to be called when cancelled
        
        Args:
            callback: Function to call with cancellation reason
        """
        with self._lock:
            self._cancel_callbacks.append(callback)
    
    def unregister_callback(self, callback: Callable[[str], None]):
        """Unregister a callback"""
        with self._lock:
            if callback in self._cancel_callbacks:
                self._cancel_callbacks.remove(callback)
    
    def reset(self):
        """Reset cancellation state (use with caution)"""
        with self._lock:
            self._cancelled.clear()
            self._reason = None
            logger.debug("Cancellation token reset")
    
    def __bool__(self) -> bool:
        """Boolean value is cancellation status"""
        return self.is_cancelled()


class CancellationError(Exception):
    """Raised when operation is cancelled"""
    pass


class CancellableOperation:
    """
    Base class for cancellable long-running operations
    
    Example:
        class DownloadOperation(CancellableOperation):
            def run(self):
                for i in range(100):
                    self.check_cancelled()
                    # Do work
                    time.sleep(0.1)
    """
    
    def __init__(self, cancellation_token: Optional[CancellationToken] = None):
        """
        Args:
            cancellation_token: Optional existing token, or create new one
        """
        self.cancellation_token = cancellation_token or CancellationToken()
        self._is_running = False
        self._lock = threading.Lock()
    
    def cancel(self, reason: str = "Operation cancelled"):
        """Cancel the operation"""
        self.cancellation_token.cancel(reason)
    
    def is_cancelled(self) -> bool:
        """Check if cancelled"""
        return self.cancellation_token.is_cancelled()
    
    def check_cancelled(self):
        """Check and raise if cancelled"""
        self.cancellation_token.throw_if_cancelled()
    
    def is_running(self) -> bool:
        """Check if operation is running"""
        with self._lock:
            return self._is_running
    
    def _set_running(self, running: bool):
        """Set running state"""
        with self._lock:
            self._is_running = running
    
    def run(self):
        """Override this method to implement the operation"""
        raise NotImplementedError("Subclasses must implement run()")
    
    def execute(self):
        """Execute the operation"""
        try:
            self._set_running(True)
            return self.run()
        except CancellationError:
            logger.info("Operation was cancelled")
            raise
        except Exception as e:
            logger.error(f"Operation failed: {e}", exc_info=True)
            raise
        finally:
            self._set_running(False)


class CancellableDownload(CancellableOperation):
    """
    Example implementation of cancellable download
    """
    
    def __init__(
        self,
        study_uid: str,
        output_dir: str,
        cancellation_token: Optional[CancellationToken] = None
    ):
        super().__init__(cancellation_token)
        self.study_uid = study_uid
        self.output_dir = output_dir
        self.progress = 0
        self.total = 0
    
    def run(self):
        """Run the download with cancellation support"""
        logger.info(f"Starting download: {self.study_uid}")
        
        try:
            # Simulate download
            self.total = 100
            for i in range(self.total):
                # Check for cancellation at regular intervals
                self.check_cancelled()
                
                # Do actual download work here
                time.sleep(0.1)
                self.progress = i + 1
                
                if i % 10 == 0:
                    logger.debug(f"Download progress: {self.progress}/{self.total}")
            
            logger.info("Download completed successfully")
            return True
            
        except CancellationError:
            logger.info(f"Download cancelled: {self.study_uid}")
            # Cleanup partial downloads
            self._cleanup()
            raise
    
    def _cleanup(self):
        """Cleanup partial downloads"""
        logger.info("Cleaning up partial downloads")
        # Implement cleanup logic here


class TimeoutCancellationToken(CancellationToken):
    """
    Cancellation token that auto-cancels after a timeout
    """
    
    def __init__(self, timeout_seconds: float):
        """
        Args:
            timeout_seconds: Timeout in seconds
        """
        super().__init__()
        self.timeout_seconds = timeout_seconds
        self._timeout_thread: Optional[threading.Thread] = None
        self._start_timeout()
    
    def _start_timeout(self):
        """Start timeout timer"""
        def timeout_func():
            if self.wait(self.timeout_seconds):
                # Already cancelled
                return
            self.cancel(f"Operation timed out after {self.timeout_seconds}s")
        
        self._timeout_thread = threading.Thread(
            target=timeout_func,
            daemon=True,
            name="cancellation-timeout"
        )
        self._timeout_thread.start()


class CancellationTokenSource:
    """
    Manages multiple cancellation tokens
    Useful for cancelling related operations together
    """
    
    def __init__(self):
        self._tokens: list[CancellationToken] = []
        self._lock = threading.Lock()
    
    def create_token(self) -> CancellationToken:
        """
        Create a new cancellation token
        
        Returns:
            New cancellation token
        """
        token = CancellationToken()
        with self._lock:
            self._tokens.append(token)
        return token
    
    def cancel_all(self, reason: str = "All operations cancelled"):
        """Cancel all tokens"""
        with self._lock:
            tokens = self._tokens.copy()
        
        for token in tokens:
            token.cancel(reason)
        
        logger.info(f"Cancelled {len(tokens)} operations")
    
    def get_active_count(self) -> int:
        """Get number of non-cancelled tokens"""
        with self._lock:
            return sum(1 for token in self._tokens if not token.is_cancelled())
    
    def clear_cancelled(self):
        """Remove cancelled tokens from list"""
        with self._lock:
            self._tokens = [token for token in self._tokens if not token.is_cancelled()]


def with_cancellation(func: Callable):
    """
    Decorator to add cancellation support to a function
    
    Example:
        @with_cancellation
        def long_running_task(data, cancellation_token=None):
            for item in data:
                if cancellation_token and cancellation_token.is_cancelled():
                    raise CancellationError()
                process(item)
    """
    def wrapper(*args, cancellation_token: Optional[CancellationToken] = None, **kwargs):
        if cancellation_token is None:
            cancellation_token = CancellationToken()
        
        # Add cancellation_token to kwargs if function accepts it
        import inspect
        sig = inspect.signature(func)
        if 'cancellation_token' in sig.parameters:
            kwargs['cancellation_token'] = cancellation_token
        
        return func(*args, **kwargs)
    
    return wrapper


# Context manager for auto-cancellation

class AutoCancelContext:
    """
    Context manager that auto-cancels on exit
    
    Example:
        with AutoCancelContext() as token:
            download_data(token)
    """
    
    def __init__(self, timeout: Optional[float] = None):
        """
        Args:
            timeout: Optional timeout in seconds
        """
        if timeout:
            self.token = TimeoutCancellationToken(timeout)
        else:
            self.token = CancellationToken()
    
    def __enter__(self) -> CancellationToken:
        """Enter context"""
        return self.token
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context - cancel if not already cancelled"""
        if not self.token.is_cancelled():
            self.token.cancel("Context exited")
        return False  # Don't suppress exceptions

