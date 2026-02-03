"""
Priority Configuration Module
Centralizes all priority-related constants, colors, and icons.
"""

from enum import IntEnum
from typing import Dict


class Priority(IntEnum):
    """Priority levels for downloads"""
    CRITICAL = 0  # Highest priority
    HIGH = 1
    NORMAL = 2
    LOW = 3       # Lowest priority


class PriorityConfig:
    """Centralized priority configuration"""
    
    # Priority names
    NAMES = {
        Priority.CRITICAL: "Critical",
        Priority.HIGH: "High",
        Priority.NORMAL: "Normal",
        Priority.LOW: "Low"
    }
    
    # Reverse mapping
    NAME_TO_VALUE = {v: k for k, v in NAMES.items()}
    
    # Priority colors (Modern UI palette)
    COLORS = {
        Priority.CRITICAL: "#f43f5e",  # Modern Rose Red
        Priority.HIGH: "#f97316",      # Vibrant Orange
        Priority.NORMAL: "#06b6d4",    # Modern Cyan/Teal
        Priority.LOW: "#64748b",       # Slate Gray
    }
    
    # Priority icons (Font Awesome)
    ICONS = {
        Priority.CRITICAL: "fa5s.exclamation-circle",
        Priority.HIGH: "fa5s.arrow-up",
        Priority.NORMAL: "fa5s.minus",
        Priority.LOW: "fa5s.arrow-down",
    }
    
    # Priority emojis for status display
    EMOJIS = {
        Priority.CRITICAL: "🔴",
        Priority.HIGH: "🟠",
        Priority.NORMAL: "🔵",
        Priority.LOW: "⚪",
    }
    
    # Priority order list (for iteration)
    ORDER = [Priority.CRITICAL, Priority.HIGH, Priority.NORMAL, Priority.LOW]
    
    @classmethod
    def get_name(cls, priority_value: int) -> str:
        """Get priority name from value"""
        return cls.NAMES.get(priority_value, "Normal")
    
    @classmethod
    def get_value(cls, priority_name: str) -> int:
        """Get priority value from name"""
        return cls.NAME_TO_VALUE.get(priority_name, Priority.NORMAL)
    
    @classmethod
    def get_color(cls, priority_value: int) -> str:
        """Get priority color"""
        return cls.COLORS.get(priority_value, cls.COLORS[Priority.NORMAL])
    
    @classmethod
    def get_icon(cls, priority_value: int) -> str:
        """Get priority icon name"""
        return cls.ICONS.get(priority_value, cls.ICONS[Priority.NORMAL])
    
    @classmethod
    def get_emoji(cls, priority_value: int) -> str:
        """Get priority emoji"""
        return cls.EMOJIS.get(priority_value, cls.EMOJIS[Priority.NORMAL])
    
    @classmethod
    def is_higher_priority(cls, priority1: int, priority2: int) -> bool:
        """Check if priority1 is higher than priority2 (lower number = higher priority)"""
        return priority1 < priority2
    
    @classmethod
    def should_preempt(cls, new_priority: int, current_priority: int) -> bool:
        """Check if new priority should preempt current"""
        return cls.is_higher_priority(new_priority, current_priority)


class PriorityRules:
    """Priority rules and behaviors"""
    
    # Maximum concurrent downloads (1 = strict sequential)
    MAX_CONCURRENT = 1
    
    # Auto-resume behavior
    AUTO_RESUME_PAUSED = True  # Auto-resume paused downloads when higher priority completes
    MANUAL_PAUSE_NO_RESUME = True  # Manually paused downloads don't auto-resume
    
    # Preemption rules
    CRITICAL_PAUSES_ALL = True  # Critical priority pauses ALL other downloads
    HIGH_PREEMPTS_NORMAL_LOW = True  # High priority preempts Normal/Low
    
    # Queue behavior
    LIFO_WITHIN_PRIORITY = True  # Last In First Out within same priority
    STRICT_PRIORITY_GROUPS = True  # Lower priority groups wait for higher to complete
    
    # UI update behavior
    PRIORITY_CHANGE_DEBOUNCE_MS = 150  # Delay before refreshing UI after priority change
    PROGRESS_UPDATE_MAX_HZ = 10  # Maximum progress updates per second
    
    @classmethod
    def get_preemption_action(cls, new_priority: int) -> str:
        """
        Get preemption action for a priority level
        
        Returns:
            'pause_all' - Pause all other downloads
            'preempt_lower' - Preempt lower priority only
            'queue' - Add to queue, no preemption
        """
        if new_priority == Priority.CRITICAL:
            return 'pause_all'
        elif new_priority == Priority.HIGH:
            return 'preempt_lower'
        else:
            return 'queue'
