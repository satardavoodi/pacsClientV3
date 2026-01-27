"""
State management system for viewer
Provides clean state machine for viewer operations
"""
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Callable, Dict, Any
import threading
import logging

logger = logging.getLogger(__name__)


class ViewerState(Enum):
    """Viewer state machine states"""
    INITIALIZING = auto()
    READY = auto()
    LOADING = auto()
    RENDERING = auto()
    ERROR = auto()
    DISPOSED = auto()


class ViewerEvent(Enum):
    """Events that trigger state transitions"""
    INITIALIZED = auto()
    LOAD_REQUESTED = auto()
    LOAD_COMPLETED = auto()
    RENDER_REQUESTED = auto()
    RENDER_COMPLETED = auto()
    ERROR_OCCURRED = auto()
    CLEANUP_REQUESTED = auto()


@dataclass
class ViewerStateData:
    """Data associated with viewer state"""
    current_slice: int = 0
    total_slices: int = 0
    zoom_level: float = 1.0
    window_width: Optional[float] = None
    window_level: Optional[float] = None
    custom_window_level: bool = False
    overlays: List[Any] = field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class ViewerStateMachine:
    """
    State machine for viewer operations
    Ensures valid state transitions and consistency
    """
    
    # Define valid state transitions
    TRANSITIONS = {
        ViewerState.INITIALIZING: {
            ViewerEvent.INITIALIZED: ViewerState.READY,
            ViewerEvent.ERROR_OCCURRED: ViewerState.ERROR,
        },
        ViewerState.READY: {
            ViewerEvent.LOAD_REQUESTED: ViewerState.LOADING,
            ViewerEvent.RENDER_REQUESTED: ViewerState.RENDERING,
            ViewerEvent.CLEANUP_REQUESTED: ViewerState.DISPOSED,
            ViewerEvent.ERROR_OCCURRED: ViewerState.ERROR,
        },
        ViewerState.LOADING: {
            ViewerEvent.LOAD_COMPLETED: ViewerState.READY,
            ViewerEvent.ERROR_OCCURRED: ViewerState.ERROR,
        },
        ViewerState.RENDERING: {
            ViewerEvent.RENDER_COMPLETED: ViewerState.READY,
            ViewerEvent.ERROR_OCCURRED: ViewerState.ERROR,
        },
        ViewerState.ERROR: {
            ViewerEvent.LOAD_REQUESTED: ViewerState.LOADING,  # Allow retry
            ViewerEvent.CLEANUP_REQUESTED: ViewerState.DISPOSED,
        },
        ViewerState.DISPOSED: {
            # Terminal state - no transitions
        },
    }
    
    def __init__(self):
        """Initialize state machine"""
        self._state = ViewerState.INITIALIZING
        self._state_data = ViewerStateData()
        self._lock = threading.RLock()
        self._callbacks: Dict[ViewerState, List[Callable]] = {}
        self._transition_history: List[Tuple[ViewerState, ViewerState, ViewerEvent]] = []
    
    @property
    def state(self) -> ViewerState:
        """Get current state"""
        with self._lock:
            return self._state
    
    @property
    def data(self) -> ViewerStateData:
        """Get state data"""
        with self._lock:
            return self._state_data
    
    def can_transition(self, event: ViewerEvent) -> bool:
        """
        Check if event can trigger transition from current state
        
        Args:
            event: Event to check
        
        Returns:
            True if transition is valid
        """
        with self._lock:
            transitions = self.TRANSITIONS.get(self._state, {})
            return event in transitions
    
    def transition(self, event: ViewerEvent, data_updates: Optional[Dict[str, Any]] = None) -> bool:
        """
        Attempt state transition
        
        Args:
            event: Event triggering transition
            data_updates: Optional updates to state data
        
        Returns:
            True if transition successful
        
        Raises:
            ValueError: If transition is invalid
        """
        with self._lock:
            if not self.can_transition(event):
                raise ValueError(
                    f"Invalid transition: {self._state.name} -> {event.name}"
                )
            
            old_state = self._state
            new_state = self.TRANSITIONS[self._state][event]
            
            # Update state
            self._state = new_state
            
            # Update state data
            if data_updates:
                for key, value in data_updates.items():
                    if hasattr(self._state_data, key):
                        setattr(self._state_data, key, value)
            
            # Record transition
            self._transition_history.append((old_state, new_state, event))
            
            # Call callbacks
            self._call_callbacks(new_state)
            
            logger.info(f"State transition: {old_state.name} -> {new_state.name} (event: {event.name})")
            return True
    
    def register_callback(self, state: ViewerState, callback: Callable):
        """
        Register callback for state entry
        
        Args:
            state: State to watch
            callback: Function to call when entering state
        """
        with self._lock:
            if state not in self._callbacks:
                self._callbacks[state] = []
            self._callbacks[state].append(callback)
    
    def _call_callbacks(self, state: ViewerState):
        """Call callbacks for state"""
        callbacks = self._callbacks.get(state, [])
        for callback in callbacks:
            try:
                callback(self._state_data)
            except Exception as e:
                logger.error(f"Error in state callback: {e}")
    
    def is_ready(self) -> bool:
        """Check if viewer is ready"""
        return self._state == ViewerState.READY
    
    def is_loading(self) -> bool:
        """Check if viewer is loading"""
        return self._state == ViewerState.LOADING
    
    def is_error(self) -> bool:
        """Check if viewer is in error state"""
        return self._state == ViewerState.ERROR
    
    def is_disposed(self) -> bool:
        """Check if viewer is disposed"""
        return self._state == ViewerState.DISPOSED
    
    def get_history(self) -> List[Tuple[ViewerState, ViewerState, ViewerEvent]]:
        """Get transition history"""
        with self._lock:
            return self._transition_history.copy()
    
    def reset(self):
        """Reset to initial state (use with caution)"""
        with self._lock:
            self._state = ViewerState.INITIALIZING
            self._state_data = ViewerStateData()
            self._transition_history.clear()
            logger.warning("State machine reset")


# Convenience decorators

def require_state(*allowed_states: ViewerState):
    """
    Decorator to require specific viewer state
    
    Example:
        @require_state(ViewerState.READY, ViewerState.RENDERING)
        def render(self):
            ...
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            if not hasattr(self, 'state_machine'):
                raise AttributeError("Object must have state_machine attribute")
            
            current_state = self.state_machine.state
            if current_state not in allowed_states:
                raise RuntimeError(
                    f"Operation '{func.__name__}' requires state {[s.name for s in allowed_states]}, "
                    f"but current state is {current_state.name}"
                )
            
            return func(self, *args, **kwargs)
        return wrapper
    return decorator


def transition_on_success(event: ViewerEvent, **data_updates):
    """
    Decorator to transition state on successful function execution
    
    Example:
        @transition_on_success(ViewerEvent.LOAD_COMPLETED, total_slices=100)
        def load_images(self):
            ...
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            
            if hasattr(self, 'state_machine'):
                try:
                    self.state_machine.transition(event, data_updates)
                except Exception as e:
                    logger.error(f"Failed to transition after {func.__name__}: {e}")
            
            return result
        return wrapper
    return decorator


def transition_on_error(event: ViewerEvent = ViewerEvent.ERROR_OCCURRED):
    """
    Decorator to transition to error state on exception
    
    Example:
        @transition_on_error()
        def risky_operation(self):
            ...
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}", exc_info=True)
                
                if hasattr(self, 'state_machine'):
                    try:
                        self.state_machine.transition(
                            event,
                            {'error_message': str(e)}
                        )
                    except Exception as trans_error:
                        logger.error(f"Failed to transition to error state: {trans_error}")
                
                raise
        return wrapper
    return decorator


# Example usage in ImageViewer2D

class StatefulViewerMixin:
    """
    Mixin to add state management to ImageViewer2D
    Add this to your ImageViewer2D class
    """
    
    def __init__(self, *args, **kwargs):
        """Initialize state machine"""
        super().__init__(*args, **kwargs)
        self.state_machine = ViewerStateMachine()
        
        # Register callbacks
        self.state_machine.register_callback(
            ViewerState.ERROR,
            self._on_error_state
        )
        self.state_machine.register_callback(
            ViewerState.READY,
            self._on_ready_state
        )
        
        # Mark as initialized
        self.state_machine.transition(ViewerEvent.INITIALIZED)
    
    def _on_error_state(self, data: ViewerStateData):
        """Called when entering error state"""
        logger.error(f"Viewer entered error state: {data.error_message}")
        # Show error UI, etc.
    
    def _on_ready_state(self, data: ViewerStateData):
        """Called when entering ready state"""
        logger.info("Viewer ready")
        # Update UI, etc.
    
    @require_state(ViewerState.READY)
    @transition_on_error()
    def set_slice_stateful(self, slice_index: int):
        """Set slice with state management"""
        # Transition to rendering
        self.state_machine.transition(
            ViewerEvent.RENDER_REQUESTED,
            {'current_slice': slice_index}
        )
        
        try:
            # Do actual rendering
            self.SetSlice(slice_index)
            self.Render()
            
            # Transition back to ready
            self.state_machine.transition(ViewerEvent.RENDER_COMPLETED)
            
        except Exception as e:
            # Automatic transition to error via decorator
            raise
    
    def get_viewer_state(self) -> Dict[str, Any]:
        """Get viewer state information"""
        return {
            'state': self.state_machine.state.name,
            'data': {
                'current_slice': self.state_machine.data.current_slice,
                'total_slices': self.state_machine.data.total_slices,
                'zoom_level': self.state_machine.data.zoom_level,
                'has_custom_wl': self.state_machine.data.custom_window_level,
                'overlay_count': len(self.state_machine.data.overlays),
            },
            'is_ready': self.state_machine.is_ready(),
            'is_loading': self.state_machine.is_loading(),
            'is_error': self.state_machine.is_error(),
        }

