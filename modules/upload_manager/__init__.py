"""AI-PACS Consultation Upload Manager (ADR-0009).

A right-sized, queued, progress-tracked manager for External Consultation uploads
that MIRRORS the Download Manager's UX while REUSING the existing resumable
``CloudSyncEngine`` + ``consultation_db`` state as its transfer engine. It is a
SEPARATE module — it never imports ``modules.download_manager`` internals, so the
download regression-guards are untouched.

Public surface is intentionally lazy: importing this package pulls in no Qt and no
heavy deps until a symbol is used, so it is safe to import from gating code.
"""

__all__ = ["get_upload_manager"]


def get_upload_manager():
    """Return the process-wide UploadManager singleton (lazy import)."""
    from .manager import get_upload_manager as _g
    return _g()
