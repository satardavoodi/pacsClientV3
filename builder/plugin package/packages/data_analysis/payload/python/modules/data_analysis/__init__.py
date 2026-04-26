"""Data analysis dashboard module."""

__all__ = ["DataAnalysisDashboard"]


def __getattr__(name):
    if name == "DataAnalysisDashboard":
        from .widget import DataAnalysisDashboard as _DataAnalysisDashboard
        return _DataAnalysisDashboard
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
