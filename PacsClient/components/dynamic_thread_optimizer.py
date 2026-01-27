# -*- coding: utf-8 -*-

"""
Dynamic Thread Optimizer inspired by pySmartDL
بهینه‌ساز پویای Thread الهام گرفته از pySmartDL
"""

import time
import threading
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import deque
import logging

logger = logging.getLogger(__name__)

@dataclass
class ThreadPerformance:
    """Performance metrics for a thread"""
    thread_id: int
    start_time: float
    bytes_downloaded: int
    current_speed: float
    average_speed: float
    error_count: int
    last_activity: float
    status: str  # 'active', 'idle', 'error', 'completed'

class DynamicThreadOptimizer:
    """
    Dynamic thread optimizer that adjusts thread count based on performance
    """
    
    def __init__(self, min_threads: int = 1, max_threads: int = 8, 
                 optimization_interval: float = 5.0):
        self.min_threads = min_threads
        self.max_threads = max_threads
        self.optimization_interval = optimization_interval
        
        self.thread_performances: Dict[int, ThreadPerformance] = {}
        self.performance_history = deque(maxlen=20)  # Last 20 measurements
        self.lock = threading.Lock()
        
        self.current_thread_count = min_threads
        self.optimal_thread_count = min_threads
        self.last_optimization = time.time()
        
        # Performance thresholds
        self.speed_improvement_threshold = 0.1  # 10% improvement needed
        self.stagnation_threshold = 3  # 3 measurements without improvement
        self.error_rate_threshold = 0.2  # 20% error rate threshold
        
    def register_thread(self, thread_id: int) -> ThreadPerformance:
        """Register a new thread for monitoring"""
        with self.lock:
            performance = ThreadPerformance(
                thread_id=thread_id,
                start_time=time.time(),
                bytes_downloaded=0,
                current_speed=0,
                average_speed=0,
                error_count=0,
                last_activity=time.time(),
                status='active'
            )
            self.thread_performances[thread_id] = performance
            logger.debug(f"📊 Registered thread {thread_id} for monitoring")
            return performance
    
    def update_thread_performance(self, thread_id: int, bytes_downloaded: int, 
                                error_occurred: bool = False):
        """Update performance metrics for a thread"""
        with self.lock:
            if thread_id not in self.thread_performances:
                return
            
            perf = self.thread_performances[thread_id]
            current_time = time.time()
            
            # Update basic metrics
            perf.bytes_downloaded = bytes_downloaded
            perf.last_activity = current_time
            
            if error_occurred:
                perf.error_count += 1
                perf.status = 'error'
            else:
                perf.status = 'active'
            
            # Calculate speeds
            elapsed_time = current_time - perf.start_time
            if elapsed_time > 0:
                perf.current_speed = bytes_downloaded / elapsed_time
                
                # Update average speed (simple moving average)
                if perf.average_speed == 0:
                    perf.average_speed = perf.current_speed
                else:
                    perf.average_speed = (perf.average_speed * 0.8) + (perf.current_speed * 0.2)
    
    def mark_thread_completed(self, thread_id: int):
        """Mark thread as completed"""
        with self.lock:
            if thread_id in self.thread_performances:
                self.thread_performances[thread_id].status = 'completed'
                logger.debug(f"✅ Thread {thread_id} marked as completed")
    
    def mark_thread_idle(self, thread_id: int):
        """Mark thread as idle"""
        with self.lock:
            if thread_id in self.thread_performances:
                self.thread_performances[thread_id].status = 'idle'
    
    def get_overall_performance(self) -> Dict[str, float]:
        """Calculate overall performance metrics"""
        with self.lock:
            if not self.thread_performances:
                return {"total_speed": 0, "avg_speed_per_thread": 0, "error_rate": 0, "active_threads": 0}
            
            active_threads = [p for p in self.thread_performances.values() if p.status == 'active']
            total_speed = sum(p.current_speed for p in active_threads)
            avg_speed_per_thread = total_speed / len(active_threads) if active_threads else 0
            
            total_errors = sum(p.error_count for p in self.thread_performances.values())
            total_threads = len(self.thread_performances)
            error_rate = total_errors / total_threads if total_threads > 0 else 0
            
            return {
                "total_speed": total_speed,
                "avg_speed_per_thread": avg_speed_per_thread,
                "error_rate": error_rate,
                "active_threads": len(active_threads)
            }
    
    def should_optimize(self) -> bool:
        """Check if optimization should be performed"""
        current_time = time.time()
        return (current_time - self.last_optimization) >= self.optimization_interval
    
    def optimize_thread_count(self) -> Tuple[int, str]:
        """
        Optimize thread count based on performance
        
        Returns:
            Tuple of (new_thread_count, reason)
        """
        if not self.should_optimize():
            return self.current_thread_count, "not_time_yet"
        
        with self.lock:
            current_performance = self.get_overall_performance()
            self.performance_history.append(current_performance)
            self.last_optimization = time.time()
            
            # Analyze performance trend
            decision = self._analyze_performance_trend()
            new_thread_count, reason = decision
            
            # Apply constraints
            new_thread_count = max(self.min_threads, min(self.max_threads, new_thread_count))
            
            if new_thread_count != self.current_thread_count:
                logger.info(f"🔧 Thread count optimization: {self.current_thread_count} → {new_thread_count} ({reason})")
                self.current_thread_count = new_thread_count
                self.optimal_thread_count = new_thread_count
            
            return new_thread_count, reason
    
    def _analyze_performance_trend(self) -> Tuple[int, str]:
        """Analyze performance trend and decide on thread count"""
        if len(self.performance_history) < 2:
            return self.current_thread_count, "insufficient_data"
        
        current_perf = self.performance_history[-1]
        previous_perf = self.performance_history[-2]
        
        # Calculate performance change
        speed_change = current_perf["total_speed"] - previous_perf["total_speed"]
        speed_change_percent = speed_change / previous_perf["total_speed"] if previous_perf["total_speed"] > 0 else 0
        
        # Check error rate
        if current_perf["error_rate"] > self.error_rate_threshold:
            return max(self.min_threads, self.current_thread_count - 1), "high_error_rate"
        
        # Check for performance improvement
        if speed_change_percent > self.speed_improvement_threshold:
            # Performance is improving, try more threads
            return min(self.max_threads, self.current_thread_count + 1), "performance_improving"
        
        # Check for performance degradation
        if speed_change_percent < -self.speed_improvement_threshold:
            # Performance is degrading, reduce threads
            return max(self.min_threads, self.current_thread_count - 1), "performance_degrading"
        
        # Check for stagnation
        if len(self.performance_history) >= self.stagnation_threshold:
            recent_speeds = [p["total_speed"] for p in list(self.performance_history)[-self.stagnation_threshold:]]
            speed_variance = max(recent_speeds) - min(recent_speeds)
            avg_speed = sum(recent_speeds) / len(recent_speeds)
            
            if avg_speed > 0 and (speed_variance / avg_speed) < 0.05:  # Less than 5% variance
                # Performance is stagnant, try different thread count
                if self.current_thread_count < self.max_threads:
                    return self.current_thread_count + 1, "stagnation_increase"
                else:
                    return max(self.min_threads, self.current_thread_count - 1), "stagnation_decrease"
        
        return self.current_thread_count, "no_change_needed"
    
    def get_optimization_stats(self) -> Dict[str, any]:
        """Get optimization statistics"""
        with self.lock:
            current_perf = self.get_overall_performance()
            
            return {
                "current_thread_count": self.current_thread_count,
                "optimal_thread_count": self.optimal_thread_count,
                "min_threads": self.min_threads,
                "max_threads": self.max_threads,
                "current_performance": current_perf,
                "performance_history_size": len(self.performance_history),
                "last_optimization": self.last_optimization,
                "thread_performances": dict(self.thread_performances)
            }
    
    def reset_optimization(self):
        """Reset optimization state"""
        with self.lock:
            self.performance_history.clear()
            self.thread_performances.clear()
            self.current_thread_count = self.min_threads
            self.optimal_thread_count = self.min_threads
            self.last_optimization = time.time()
            logger.info("🔄 Thread optimization reset")
    
    def cleanup_completed_threads(self):
        """Clean up completed or idle threads from tracking"""
        with self.lock:
            completed_threads = [
                tid for tid, perf in self.thread_performances.items() 
                if perf.status in ['completed', 'idle'] and 
                (time.time() - perf.last_activity) > 30  # 30 seconds timeout
            ]
            
            for tid in completed_threads:
                del self.thread_performances[tid]
                logger.debug(f"🧹 Cleaned up thread {tid} from tracking")


class AdaptiveConnectionManager:
    """
    Adaptive connection manager that uses thread optimizer
    """
    
    def __init__(self, min_connections: int = 1, max_connections: int = 8):
        self.thread_optimizer = DynamicThreadOptimizer(min_connections, max_connections)
        self.active_connections: Dict[int, any] = {}
        self.connection_counter = 0
        self.lock = threading.Lock()
    
    def create_connection(self) -> int:
        """Create a new connection and register it"""
        with self.lock:
            self.connection_counter += 1
            connection_id = self.connection_counter
            
            # Register with thread optimizer
            self.thread_optimizer.register_thread(connection_id)
            self.active_connections[connection_id] = {
                "created_at": time.time(),
                "status": "active"
            }
            
            return connection_id
    
    def update_connection_stats(self, connection_id: int, bytes_downloaded: int, 
                              error_occurred: bool = False):
        """Update connection statistics"""
        self.thread_optimizer.update_thread_performance(connection_id, bytes_downloaded, error_occurred)
    
    def close_connection(self, connection_id: int):
        """Close a connection"""
        with self.lock:
            if connection_id in self.active_connections:
                self.thread_optimizer.mark_thread_completed(connection_id)
                del self.active_connections[connection_id]
    
    def optimize_connections(self) -> Tuple[int, str]:
        """Optimize number of connections"""
        return self.thread_optimizer.optimize_thread_count()
    
    def get_stats(self) -> Dict[str, any]:
        """Get connection manager statistics"""
        optimizer_stats = self.thread_optimizer.get_optimization_stats()
        
        with self.lock:
            return {
                "active_connections": len(self.active_connections),
                "total_connections_created": self.connection_counter,
                "optimizer_stats": optimizer_stats
            }
