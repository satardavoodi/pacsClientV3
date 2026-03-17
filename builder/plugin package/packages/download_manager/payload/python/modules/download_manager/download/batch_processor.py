"""
Batch Processor - Batch download processing with adaptive sizing (R29, R32)

Handles batch-level download operations with adaptive batch sizing
based on network health.
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..core.constants import BATCH_SIZE
from ..network.health_monitor import ConnectionHealthMonitor

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Batch download processor with adaptive sizing
    
    Features:
    - Adaptive batch size based on network health (R29)
    - Batch-level retry logic
    - Progress tracking per batch
    """
    
    def __init__(self, health_monitor: ConnectionHealthMonitor):
        """
        Initialize batch processor
        
        Args:
            health_monitor: Health monitor instance
        """
        self.health_monitor = health_monitor
        self.base_batch_size = BATCH_SIZE
        
        logger.info("✅ BatchProcessor initialized")
    
    def get_adaptive_batch_size(self) -> int:
        """
        Get adaptive batch size based on network health (R29)
        
        Returns:
            Adapted batch size
        """
        return self.health_monitor.get_adaptive_batch_size(self.base_batch_size)
    
    def create_batches(
        self,
        instances: List[Dict[str, Any]],
        batch_size: Optional[int] = None
    ) -> List[List[Dict[str, Any]]]:
        """
        Split instances into batches
        
        Args:
            instances: List of instance metadata
            batch_size: Batch size (if None, uses adaptive size)
            
        Returns:
            List of batches
        """
        if batch_size is None:
            batch_size = self.get_adaptive_batch_size()
        
        batches = []
        for i in range(0, len(instances), batch_size):
            batch = instances[i:i + batch_size]
            batches.append(batch)
        
        logger.debug(f"📦 Created {len(batches)} batches (size: {batch_size})")
        
        return batches
    
    def should_reduce_batch_size(self, consecutive_failures: int) -> bool:
        """
        Check if batch size should be reduced
        
        Args:
            consecutive_failures: Number of consecutive failures
            
        Returns:
            True if should reduce, False otherwise
        """
        # Reduce batch size after 2 consecutive failures
        return consecutive_failures >= 2
