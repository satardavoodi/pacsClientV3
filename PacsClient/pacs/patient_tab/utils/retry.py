"""
Retry logic with exponential backoff for network operations
Provides decorators and utilities for automatic retries
"""
import time
import functools
import logging
from typing import Callable, TypeVar, Optional, Tuple, Type, Union
from dataclasses import dataclass

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    backoff_multiplier: float = 2.0
    jitter: bool = True
    retry_on_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number"""
        import random
        
        # Exponential backoff
        delay = min(
            self.initial_delay * (self.backoff_multiplier ** attempt),
            self.max_delay
        )
        
        # Add jitter to avoid thundering herd
        if self.jitter:
            delay = delay * (0.5 + random.random() * 0.5)
        
        return delay


class RetryError(Exception):
    """Raised when all retry attempts have been exhausted"""
    
    def __init__(
        self,
        message: str,
        attempts: int,
        last_exception: Optional[Exception] = None
    ):
        super().__init__(message)
        self.attempts = attempts
        self.last_exception = last_exception
    
    def __str__(self) -> str:
        msg = f"{self.args[0]} (attempted {self.attempts} times)"
        if self.last_exception:
            msg += f" - Last error: {type(self.last_exception).__name__}: {self.last_exception}"
        return msg


def retry(
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_multiplier: float = 2.0,
    jitter: bool = True,
    retry_on: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception,
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """
    Decorator for retrying a function with exponential backoff
    
    Args:
        max_attempts: Maximum number of attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_multiplier: Multiplier for exponential backoff
        jitter: Add random jitter to delays
        retry_on: Exception type(s) to retry on
        on_retry: Optional callback called on each retry attempt
    
    Example:
        @retry(max_attempts=3, initial_delay=2.0)
        def download_file(url):
            response = requests.get(url)
            response.raise_for_status()
            return response.content
    """
    if isinstance(retry_on, type):
        retry_on = (retry_on,)
    
    config = RetryConfig(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        max_delay=max_delay,
        backoff_multiplier=backoff_multiplier,
        jitter=jitter,
        retry_on_exceptions=retry_on
    )
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except config.retry_on_exceptions as e:
                    last_exception = e
                    
                    # Last attempt - don't retry
                    if attempt == config.max_attempts - 1:
                        logger.error(
                            f"Function {func.__name__} failed after {config.max_attempts} attempts",
                            exc_info=True
                        )
                        raise RetryError(
                            f"Failed after {config.max_attempts} attempts",
                            attempts=config.max_attempts,
                            last_exception=e
                        ) from e
                    
                    # Calculate delay
                    delay = config.calculate_delay(attempt)
                    
                    logger.warning(
                        f"Attempt {attempt + 1}/{config.max_attempts} failed for {func.__name__}: "
                        f"{type(e).__name__}: {e}. Retrying in {delay:.2f}s..."
                    )
                    
                    # Call retry callback if provided
                    if on_retry:
                        try:
                            on_retry(e, attempt + 1)
                        except Exception as callback_error:
                            logger.error(f"Error in retry callback: {callback_error}")
                    
                    # Wait before retry
                    time.sleep(delay)
                    
                except Exception as e:
                    # Not a retryable exception - re-raise immediately
                    logger.error(
                        f"Non-retryable exception in {func.__name__}: {type(e).__name__}: {e}",
                        exc_info=True
                    )
                    raise
            
            # Should never reach here, but just in case
            raise RetryError(
                f"Unexpected retry exhaustion",
                attempts=config.max_attempts,
                last_exception=last_exception
            )
        
        return wrapper
    return decorator


class RetryContext:
    """
    Context manager for retry logic
    
    Example:
        with RetryContext(max_attempts=3) as retry:
            for attempt in retry:
                try:
                    result = download_file(url)
                    retry.success()
                    break
                except ConnectionError as e:
                    retry.failure(e)
    """
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
        jitter: bool = True,
        retry_on: Union[Type[Exception], Tuple[Type[Exception], ...]] = Exception
    ):
        if isinstance(retry_on, type):
            retry_on = (retry_on,)
        
        self.config = RetryConfig(
            max_attempts=max_attempts,
            initial_delay=initial_delay,
            max_delay=max_delay,
            backoff_multiplier=backoff_multiplier,
            jitter=jitter,
            retry_on_exceptions=retry_on
        )
        
        self.current_attempt = 0
        self.succeeded = False
        self.last_exception: Optional[Exception] = None
    
    def __enter__(self) -> 'RetryContext':
        """Enter context"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context"""
        if not self.succeeded and exc_type is not None:
            logger.error(
                f"Retry context exited with failure after {self.current_attempt} attempts",
                exc_info=(exc_type, exc_val, exc_tb)
            )
        return False  # Don't suppress exceptions
    
    def __iter__(self):
        """Iterate over attempts"""
        self.current_attempt = 0
        return self
    
    def __next__(self) -> int:
        """Get next attempt"""
        if self.succeeded:
            raise StopIteration
        
        if self.current_attempt >= self.config.max_attempts:
            raise RetryError(
                f"Maximum retry attempts ({self.config.max_attempts}) exceeded",
                attempts=self.current_attempt,
                last_exception=self.last_exception
            )
        
        # Wait before retry (except for first attempt)
        if self.current_attempt > 0:
            delay = self.config.calculate_delay(self.current_attempt - 1)
            logger.info(f"Retrying in {delay:.2f}s... (attempt {self.current_attempt + 1}/{self.config.max_attempts})")
            time.sleep(delay)
        
        self.current_attempt += 1
        return self.current_attempt
    
    def success(self):
        """Mark attempt as successful"""
        self.succeeded = True
        logger.debug(f"Operation succeeded on attempt {self.current_attempt}")
    
    def failure(self, exception: Exception):
        """Mark attempt as failed"""
        self.last_exception = exception
        
        if self.current_attempt >= self.config.max_attempts:
            logger.error(
                f"All {self.config.max_attempts} attempts failed. Last error: {type(exception).__name__}: {exception}"
            )
        else:
            logger.warning(
                f"Attempt {self.current_attempt}/{self.config.max_attempts} failed: {type(exception).__name__}: {exception}"
            )


# Specialized retry decorators for common use cases

def retry_on_connection_error(
    max_attempts: int = 3,
    initial_delay: float = 2.0
):
    """Retry decorator specifically for connection errors"""
    try:
        import requests
        from urllib3.exceptions import NewConnectionError, MaxRetryError
        retry_exceptions = (
            ConnectionError,
            TimeoutError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            NewConnectionError,
            MaxRetryError
        )
    except ImportError:
        retry_exceptions = (ConnectionError, TimeoutError)
    
    return retry(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        retry_on=retry_exceptions
    )


def retry_on_grpc_error(
    max_attempts: int = 3,
    initial_delay: float = 1.0
):
    """Retry decorator for gRPC errors"""
    try:
        import grpc
        
        def is_retryable_grpc_error(e: Exception) -> bool:
            if not isinstance(e, grpc.RpcError):
                return False
            
            retryable_codes = {
                grpc.StatusCode.UNAVAILABLE,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                grpc.StatusCode.ABORTED
            }
            
            return hasattr(e, 'code') and e.code() in retryable_codes
        
        # Custom wrapper since we can't directly filter gRPC errors
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                config = RetryConfig(
                    max_attempts=max_attempts,
                    initial_delay=initial_delay
                )
                
                for attempt in range(config.max_attempts):
                    try:
                        return func(*args, **kwargs)
                    except grpc.RpcError as e:
                        if not is_retryable_grpc_error(e) or attempt == config.max_attempts - 1:
                            raise
                        
                        delay = config.calculate_delay(attempt)
                        logger.warning(f"gRPC error (code: {e.code()}), retrying in {delay:.2f}s...")
                        time.sleep(delay)
                
                raise RetryError(f"Failed after {config.max_attempts} attempts", attempts=config.max_attempts)
            
            return wrapper
        return decorator
        
    except ImportError:
        logger.warning("grpc not available, using generic retry")
        return retry(max_attempts=max_attempts, initial_delay=initial_delay)


def retry_on_file_error(
    max_attempts: int = 3,
    initial_delay: float = 0.5
):
    """Retry decorator for file I/O errors"""
    return retry(
        max_attempts=max_attempts,
        initial_delay=initial_delay,
        retry_on=(IOError, OSError, PermissionError)
    )

