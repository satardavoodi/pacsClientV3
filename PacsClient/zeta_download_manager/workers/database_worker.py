"""
Database Worker - Async database operations

Handles database operations in background to avoid blocking UI.
"""

import logging
import asyncio
from typing import Any, Callable, Optional
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


class DatabaseWorker(QThread):
    """
    Qt worker thread for database operations
    
    Features:
    - Async database operations
    - Non-blocking UI
    - Error handling
    - Completion signals
    
    Signals:
        completed: (success, result)
        error: (error_message)
    """
    
    # Signals
    completed = Signal(bool, object)  # success, result
    error = Signal(str)  # error_message
    
    def __init__(
        self,
        operation: Callable,
        args: tuple = (),
        kwargs: dict = None,
        parent=None
    ):
        """
        Initialize database worker
        
        Args:
            operation: Database operation to execute
            args: Positional arguments for operation
            kwargs: Keyword arguments for operation
            parent: Parent QObject
        """
        super().__init__(parent)
        self.setObjectName("DatabaseWorker")
        
        self.operation = operation
        self.args = args
        self.kwargs = kwargs or {}
        
        logger.debug("✅ DatabaseWorker created")
    
    def run(self) -> None:
        """Execute database operation in background thread"""
        try:
            result = self.operation(*self.args, **self.kwargs)
            self.completed.emit(True, result)
            logger.debug("✅ DatabaseWorker completed")
        
        except Exception as e:
            logger.error(f"❌ DatabaseWorker error: {e}")
            self.error.emit(str(e))
            self.completed.emit(False, None)
