"""
Custom Exceptions - Clear error types for better error handling
"""


class DownloadError(Exception):
    """Base exception for all download-related errors"""
    pass


class NetworkError(DownloadError):
    """Network communication errors (socket, gRPC)"""
    pass


class DatabaseError(DownloadError):
    """Database operation errors"""
    pass


class ValidationError(DownloadError):
    """Validation errors (invalid data, failed validation)"""
    pass


class StateError(DownloadError):
    """State management errors (invalid transition, missing state)"""
    pass


class RuleViolationError(DownloadError):
    """Rule engine errors (rule violated, invalid action)"""
    pass


class WorkerError(DownloadError):
    """Worker thread errors"""
    pass


class ConfigurationError(DownloadError):
    """Configuration errors (missing config, invalid values)"""
    pass


class FileSystemError(DownloadError):
    """File system operation errors"""
    pass
