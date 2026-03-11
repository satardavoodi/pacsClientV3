def __getattr__(name):
    if name == "AppHandler":
        from .app_handler import AppHandler
        return AppHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")