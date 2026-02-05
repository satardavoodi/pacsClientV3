"""
Animation Manager - Smooth UI animations

Manages animations for progress bars, state changes, and transitions.
"""

import logging
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QObject, Property
from PySide6.QtWidgets import QWidget

from ...core.constants import ANIMATION_DURATION_MS, EXPAND_ANIMATION_DURATION_MS

logger = logging.getLogger(__name__)


class AnimationManager:
    """
    Animation management for UI components
    
    Features:
    - Smooth progress bar animations (300ms ease-in-out)
    - State change fade transitions (150ms)
    - Group expand/collapse (200ms)
    - Configurable durations and easing
    """
    
    @staticmethod
    def create_progress_animation(
        target: QWidget,
        property_name: bytes,
        start_value: float,
        end_value: float,
        duration: int = None
    ) -> QPropertyAnimation:
        """
        Create progress animation
        
        Args:
            target: Target widget
            property_name: Property to animate (e.g., b"progress")
            start_value: Starting value
            end_value: Ending value
            duration: Animation duration (ms)
            
        Returns:
            QPropertyAnimation
        """
        duration = duration or ANIMATION_DURATION_MS
        
        animation = QPropertyAnimation(target, property_name)
        animation.setDuration(duration)
        animation.setStartValue(start_value)
        animation.setEndValue(end_value)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        
        return animation
    
    @staticmethod
    def create_fade_animation(
        target: QWidget,
        fade_in: bool = True,
        duration: int = 150
    ) -> QPropertyAnimation:
        """
        Create fade animation
        
        Args:
            target: Target widget
            fade_in: True for fade in, False for fade out
            duration: Animation duration (ms)
            
        Returns:
            QPropertyAnimation
        """
        animation = QPropertyAnimation(target, b"windowOpacity")
        animation.setDuration(duration)
        
        if fade_in:
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
        else:
            animation.setStartValue(1.0)
            animation.setEndValue(0.0)
        
        animation.setEasingCurve(QEasingCurve.InOutQuad)
        
        return animation
    
    @staticmethod
    def create_expand_animation(
        target: QWidget,
        expand: bool = True,
        duration: int = None
    ) -> QPropertyAnimation:
        """
        Create expand/collapse animation
        
        Args:
            target: Target widget
            expand: True for expand, False for collapse
            duration: Animation duration (ms)
            
        Returns:
            QPropertyAnimation
        """
        duration = duration or EXPAND_ANIMATION_DURATION_MS
        
        animation = QPropertyAnimation(target, b"maximumHeight")
        animation.setDuration(duration)
        
        if expand:
            animation.setStartValue(0)
            animation.setEndValue(1000)  # Large enough value
        else:
            animation.setStartValue(target.height())
            animation.setEndValue(0)
        
        animation.setEasingCurve(QEasingCurve.InOutQuad)
        
        return animation
