"""Schedule optional Slicer startup without filesystem work or native imports in Qt."""
import logging
import os
import threading


def install(app):
    from PySide6.QtCore import QTimer
    if getattr(app, "_advanced_analysis_warmup_installed", False):
        return
    app._advanced_analysis_warmup_installed = True
    stopping = threading.Event()
    shutdown = [None]
    def prepare():
        try:
            import aipacs_runtime
            if stopping.is_set() or not aipacs_runtime.is_module_enabled("advanced_mpr"):
                return
            from modules.mpr.advanced_3d_slicer.resident_service import get_service, resident_enabled
            from modules.mpr.advanced_3d_slicer.resident_service import stop_services
            shutdown[0] = stop_services
            if not resident_enabled() or os.environ.get("AIPACS_SLICER_PREWARM", "1").lower() in {"0", "off", "false"}:
                return
            import psutil
            if psutil.virtual_memory().available < 2 * 1024**3:
                logging.getLogger(__name__).info("Advanced Analysis warmup deferred: low available memory")
                return
            if not stopping.is_set():
                get_service().warmup().result(timeout=125)
        except Exception as exc:
            logging.getLogger(__name__).warning("Advanced Analysis warmup unavailable (%s)", type(exc).__name__)
    def launch():
        if not stopping.is_set():
            threading.Thread(target=prepare, name="AdvancedAnalysisStartup", daemon=True).start()
    def stop():
        stopping.set()
        if shutdown[0]:
            shutdown[0]()
    app.aboutToQuit.connect(stop)
    QTimer.singleShot(0, launch)
