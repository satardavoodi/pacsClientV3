"""
Connection Health Monitor - Network health tracking and adaptation (R30, R32, R33, R34)

Monitors connection health and adapts download behavior based on network conditions.
"""

import logging
import time
import threading
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class HealthMetrics:
    """Connection health metrics"""
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    average_latency_ms: float = 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        if self.total_requests == 0:
            return 100.0
        return ((self.total_requests - self.failed_requests) / self.total_requests) * 100
    
    @property
    def is_healthy(self) -> bool:
        """Check if connection is healthy"""
        # Consider healthy if success rate > 80% and < 3 consecutive failures
        return self.success_rate > 80.0 and self.consecutive_failures < 3


class ConnectionHealthMonitor:
    """
    Monitor connection health and adapt behavior
    
    Rules enforced:
    - R30: Connection health monitoring
    - R32: Adaptive throttling by priority and health
    - R33: Connection test before operations
    - R34: Graceful degradation on poor network
    """
    
    def __init__(self):
        """Initialize health monitor"""
        self.metrics = HealthMetrics()
        self.lock = threading.Lock()
        self._latency_samples = []
        
        logger.info("✅ ConnectionHealthMonitor initialized")
    
    def record_success(self, latency_ms: float = 0) -> None:
        """
        Record successful operation
        
        Args:
            latency_ms: Operation latency in milliseconds
        """
        with self.lock:
            self.metrics.last_success = datetime.now()
            self.metrics.consecutive_successes += 1
            self.metrics.consecutive_failures = 0
            self.metrics.total_requests += 1
            
            # Update average latency
            self._latency_samples.append(latency_ms)
            if len(self._latency_samples) > 100:
                self._latency_samples.pop(0)
            
            if self._latency_samples:
                self.metrics.average_latency_ms = sum(self._latency_samples) / len(self._latency_samples)
    
    def record_failure(self) -> None:
        """Record failed operation"""
        with self.lock:
            self.metrics.last_failure = datetime.now()
            self.metrics.consecutive_failures += 1
            self.metrics.consecutive_successes = 0
            self.metrics.total_requests += 1
            self.metrics.failed_requests += 1
    
    def is_healthy(self) -> bool:
        """
        Check if connection is healthy (R30)
        
        Returns:
            True if healthy, False otherwise
        """
        with self.lock:
            return self.metrics.is_healthy
    
    def should_test_connection(self) -> bool:
        """
        Check if connection test is needed (R33)
        
        Returns:
            True if should test connection, False otherwise
        """
        with self.lock:
            # Test if consecutive failures > 2
            if self.metrics.consecutive_failures > 2:
                return True
            
            # Test if no recent success (> 60 seconds)
            if self.metrics.last_success:
                time_since_success = datetime.now() - self.metrics.last_success
                if time_since_success > timedelta(seconds=60):
                    return True
            
            return False
    
    def get_adaptive_batch_size(self, base_batch_size: int = 100) -> int:
        """
        Get adaptive batch size based on connection health (R32, R34)
        
        Args:
            base_batch_size: Base batch size
            
        Returns:
            Adapted batch size
        """
        with self.lock:
            if not self.metrics.is_healthy:
                # Poor connection - reduce batch size for graceful degradation (R34)
                if self.metrics.consecutive_failures >= 3:
                    return max(10, base_batch_size // 4)  # Reduce to 25%
                elif self.metrics.consecutive_failures >= 2:
                    return max(25, base_batch_size // 2)  # Reduce to 50%
            
            # Healthy connection - use base batch size
            return base_batch_size
    
    def get_recommended_throttle_ms(self, priority: 'DownloadPriority') -> int:
        """
        Get recommended throttle delay based on health and priority (R32)
        
        Args:
            priority: Download priority
            
        Returns:
            Throttle delay in milliseconds
        """
        with self.lock:
            # Base throttle by priority
            from ..core.enums import DownloadPriority
            
            base_throttle = {
                DownloadPriority.CRITICAL: 0,    # No throttle
                DownloadPriority.HIGH: 10,       # 10ms
                DownloadPriority.NORMAL: 50,     # 50ms
                DownloadPriority.LOW: 100,       # 100ms
            }.get(priority, 50)
            
            # Increase throttle if connection unhealthy
            if not self.metrics.is_healthy:
                base_throttle *= 2  # Double the throttle
            
            return base_throttle
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get current health status
        
        Returns:
            Health status dictionary
        """
        with self.lock:
            return {
                'is_healthy': self.metrics.is_healthy,
                'success_rate': self.metrics.success_rate,
                'consecutive_successes': self.metrics.consecutive_successes,
                'consecutive_failures': self.metrics.consecutive_failures,
                'total_requests': self.metrics.total_requests,
                'failed_requests': self.metrics.failed_requests,
                'average_latency_ms': self.metrics.average_latency_ms,
                'last_success': self.metrics.last_success.isoformat() if self.metrics.last_success else None,
                'last_failure': self.metrics.last_failure.isoformat() if self.metrics.last_failure else None,
            }
    
    def reset(self) -> None:
        """Reset health metrics"""
        with self.lock:
            self.metrics = HealthMetrics()
            self._latency_samples = []
            logger.info("🔄 Health metrics reset")
