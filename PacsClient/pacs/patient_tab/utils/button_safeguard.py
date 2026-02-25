"""
Button Safeguard Utility
========================

Prevents multiple simultaneous button clicks that could cause the application
to hang or become unresponsive. This module provides:

1. ButtonSafeguard class - manages button state during async operations
2. @safeguard_action decorator - wraps click handlers with automatic protection
3. Context manager support - for manual control over button states

Usage Examples:
--------------

Basic decorator usage:
    @safeguard_action
    def _on_button_clicked(self):
        # Heavy operation
        pass

With custom error handling:
    @safeguard_action(show_error_dialog=True)
    async def _on_async_button_clicked(self):
        # Async operation
        pass

Manual control:
    with self.button_safeguard:
        # Do work
        pass
"""

import functools
import logging
import traceback
from typing import Optional, Callable, List, Any
from PySide6.QtWidgets import QWidget, QPushButton, QToolButton, QMessageBox
from PySide6.QtCore import QObject, Signal, QTimer

logger = logging.getLogger(__name__)


class ButtonSafeguard(QObject):
    """
    Manages button states to prevent multiple concurrent operations.
    
    This class tracks all interactive buttons in a widget and provides
    thread-safe methods to disable/enable them during async operations.
    """
    
    # Signals
    operation_started = Signal()
    operation_completed = Signal(bool)  # success/failure
    
    def __init__(self, parent_widget: QWidget):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self._operation_in_progress = False
        self._registered_buttons: List[QWidget] = []
        self._original_button_states: dict = {}
        self._operation_count = 0
        
        logger.info(f"[ButtonSafeguard] Initialized for {parent_widget.__class__.__name__}")
    
    def register_button(self, button: QWidget) -> None:
        """
        Register a button to be managed by this safeguard.
        
        Args:
            button: QWidget (typically QPushButton or QToolButton) to manage
        """
        if button and button not in self._registered_buttons:
            self._registered_buttons.append(button)
            logger.debug(f"[ButtonSafeguard] Registered button: {getattr(button, 'text', lambda: 'Unknown')()}")
    
    def register_buttons(self, buttons: List[QWidget]) -> None:
        """
        Register multiple buttons at once.
        
        Args:
            buttons: List of QWidget buttons to manage
        """
        for button in buttons:
            self.register_button(button)
    
    def auto_discover_buttons(self) -> None:
        """
        Automatically discover and register all QPushButton and QToolButton
        widgets in the parent widget and its children.
        """
        discovered_count = 0
        for child in self.parent_widget.findChildren(QPushButton):
            if child not in self._registered_buttons:
                self.register_button(child)
                discovered_count += 1
        
        for child in self.parent_widget.findChildren(QToolButton):
            if child not in self._registered_buttons:
                self.register_button(child)
                discovered_count += 1
        
        logger.info(f"[ButtonSafeguard] Auto-discovered {discovered_count} buttons")
    
    def is_operation_in_progress(self) -> bool:
        """Check if an operation is currently in progress."""
        return self._operation_in_progress
    
    def start_operation(self, operation_name: str = "Operation") -> bool:
        """
        Start a protected operation. Disables all registered buttons.
        
        Args:
            operation_name: Name of the operation for logging
            
        Returns:
            bool: True if operation started, False if another operation is already running
        """
        if self._operation_in_progress:
            logger.warning(
                f"[ButtonSafeguard] Operation '{operation_name}' blocked - "
                f"another operation is in progress"
            )
            return False
        
        self._operation_in_progress = True
        self._operation_count += 1
        logger.info(f"[ButtonSafeguard] Starting operation: {operation_name} (#{self._operation_count})")
        
        # Save and disable all buttons
        self._original_button_states.clear()
        for button in self._registered_buttons:
            if button and not button.isHidden():
                try:
                    self._original_button_states[button] = button.isEnabled()
                    button.setEnabled(False)
                except RuntimeError:
                    # Button was deleted
                    pass
        
        self.operation_started.emit()
        return True
    
    def end_operation(self, success: bool = True, operation_name: str = "Operation") -> None:
        """
        End a protected operation. Re-enables all registered buttons.
        
        Args:
            success: Whether the operation completed successfully
            operation_name: Name of the operation for logging
        """
        if not self._operation_in_progress:
            logger.warning(f"[ButtonSafeguard] end_operation called but no operation in progress")
            return
        
        logger.info(
            f"[ButtonSafeguard] Ending operation: {operation_name} "
            f"(success={success}, #{self._operation_count})"
        )
        
        # Restore button states
        for button, original_state in self._original_button_states.items():
            try:
                if button and not button.isHidden():
                    button.setEnabled(original_state)
            except RuntimeError:
                # Button was deleted
                pass
        
        self._original_button_states.clear()
        self._operation_in_progress = False
        self.operation_completed.emit(success)
    
    def force_end_operation(self) -> None:
        """
        Force end the current operation (emergency use only).
        Use this if an operation failed to call end_operation properly.
        """
        logger.warning("[ButtonSafeguard] Force ending operation")
        if self._operation_in_progress:
            self.end_operation(success=False, operation_name="Force-ended")
    
    # Context manager support
    def __enter__(self):
        """Context manager entry - start operation."""
        if not self.start_operation("Context-managed operation"):
            raise RuntimeError("Another operation is already in progress")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - end operation."""
        success = exc_type is None
        self.end_operation(success=success)
        return False  # Don't suppress exceptions


def safeguard_action(
    func: Optional[Callable] = None,
    *,
    show_error_dialog: bool = False,
    error_title: str = "Operation Failed",
    operation_name: Optional[str] = None
):
    """
    Decorator to protect button click handlers from concurrent execution.
    
    This decorator automatically manages button states during the execution
    of the wrapped function. It prevents users from clicking other buttons
    while an operation is in progress.
    
    Args:
        func: The function to wrap (provided automatically when used as @safeguard_action)
        show_error_dialog: If True, shows a QMessageBox on errors
        error_title: Title for the error dialog
        operation_name: Custom name for logging (defaults to function name)
    
    Usage:
        @safeguard_action
        def _on_button_clicked(self):
            # Your code here
            pass
        
        @safeguard_action(show_error_dialog=True)
        def _on_important_button_clicked(self):
            # Your code here
            pass
    """
    
    def decorator(f: Callable) -> Callable:
        @functools.wraps(f)
        def sync_wrapper(self, *args, **kwargs):
            # Get the safeguard from the widget
            safeguard: Optional[ButtonSafeguard] = getattr(self, 'button_safeguard', None)
            
            if safeguard is None:
                logger.warning(
                    f"[ButtonSafeguard] No safeguard found on {self.__class__.__name__}, "
                    f"executing {f.__name__} without protection"
                )
                return f(self, *args, **kwargs)
            
            op_name = operation_name or f.__name__
            
            # Check if operation can start
            if not safeguard.start_operation(op_name):
                logger.info(f"[ButtonSafeguard] Blocking duplicate call to {op_name}")
                return None
            
            try:
                result = f(self, *args, **kwargs)
                safeguard.end_operation(success=True, operation_name=op_name)
                return result
            
            except Exception as e:
                logger.error(
                    f"[ButtonSafeguard] Error in {op_name}: {e}\n{traceback.format_exc()}"
                )
                safeguard.end_operation(success=False, operation_name=op_name)
                
                if show_error_dialog and hasattr(self, 'window'):
                    QMessageBox.critical(
                        self.window(),
                        error_title,
                        f"An error occurred:\n\n{str(e)}"
                    )
                
                raise
        
        @functools.wraps(f)
        async def async_wrapper(self, *args, **kwargs):
            # Get the safeguard from the widget
            safeguard: Optional[ButtonSafeguard] = getattr(self, 'button_safeguard', None)
            
            if safeguard is None:
                logger.warning(
                    f"[ButtonSafeguard] No safeguard found on {self.__class__.__name__}, "
                    f"executing {f.__name__} without protection"
                )
                return await f(self, *args, **kwargs)
            
            op_name = operation_name or f.__name__
            
            # Check if operation can start
            if not safeguard.start_operation(op_name):
                logger.info(f"[ButtonSafeguard] Blocking duplicate call to {op_name}")
                return None
            
            try:
                result = await f(self, *args, **kwargs)
                safeguard.end_operation(success=True, operation_name=op_name)
                return result
            
            except Exception as e:
                logger.error(
                    f"[ButtonSafeguard] Error in {op_name}: {e}\n{traceback.format_exc()}"
                )
                safeguard.end_operation(success=False, operation_name=op_name)
                
                if show_error_dialog and hasattr(self, 'window'):
                    QMessageBox.critical(
                        self.window(),
                        error_title,
                        f"An error occurred:\n\n{str(e)}"
                    )
                
                raise
        
        # Return the appropriate wrapper based on whether the function is async
        import asyncio
        if asyncio.iscoroutinefunction(f):
            return async_wrapper
        else:
            return sync_wrapper
    
    # Handle both @safeguard_action and @safeguard_action() syntax
    if func is None:
        return decorator
    else:
        return decorator(func)


def delayed_safeguard_wrapper(
    widget,
    func: Callable,
    delay_ms: int = 500,
    operation_name: Optional[str] = None
):
    """
    Wraps a function to be called after a delay, with safeguard protection.
    
    This is useful for operations that show a loading overlay and need to
    ensure the overlay is rendered before the heavy work begins.
    
    Args:
        widget: The widget containing the button_safeguard
        func: The function to call after delay
        delay_ms: Delay in milliseconds
        operation_name: Name for logging
    
    Returns:
        A function that can be called to start the delayed operation
    """
    def wrapper(*args, **kwargs):
        safeguard: Optional[ButtonSafeguard] = getattr(widget, 'button_safeguard', None)
        
        if safeguard is None:
            logger.warning(f"[ButtonSafeguard] No safeguard found, executing without protection")
            return func(*args, **kwargs)
        
        op_name = operation_name or func.__name__
        
        if not safeguard.start_operation(op_name):
            logger.info(f"[ButtonSafeguard] Blocking duplicate delayed call to {op_name}")
            return
        
        def delayed_execution():
            try:
                result = func(*args, **kwargs)
                safeguard.end_operation(success=True, operation_name=op_name)
                return result
            except Exception as e:
                logger.error(f"[ButtonSafeguard] Error in delayed {op_name}: {e}")
                safeguard.end_operation(success=False, operation_name=op_name)
                raise
        
        QTimer.singleShot(delay_ms, delayed_execution)
    
    return wrapper
