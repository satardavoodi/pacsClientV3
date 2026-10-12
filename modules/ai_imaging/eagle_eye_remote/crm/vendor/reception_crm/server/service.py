"""Windows service wrapper.

Registers the server with the Service Control Manager so it starts at boot,
runs with no user logged in, and restarts after a failure.

Why pywin32 and not ``sc.exe`` alone: a plain console executable is not a
service. Windows expects the process to connect back to the SCM and answer
control requests within a timeout; a normal program never does, so the SCM
kills it and reports error 1053. ``win32serviceutil.ServiceFramework`` performs
that handshake.

Install and control (all require an elevated prompt)::

    ReceptionCrmServer.exe --startup auto install
    ReceptionCrmServer.exe start
    ReceptionCrmServer.exe stop
    ReceptionCrmServer.exe remove
"""

from __future__ import annotations

import logging
import sys
import threading

from .config import load_server_config
from .runner import ServerProcess, configure_logging

logger = logging.getLogger("reception_crm.server.service")

try:
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    PYWIN32_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only on non-Windows/dev boxes
    PYWIN32_AVAILABLE = False
    win32serviceutil = object  # type: ignore[assignment]


if PYWIN32_AVAILABLE:

    class ReceptionCrmService(win32serviceutil.ServiceFramework):  # type: ignore[misc]
        _svc_name_ = "ReceptionCrmServer"
        _svc_display_name_ = "Reception CRM Server"
        _svc_description_ = (
            "Processes text commands from the Reception CRM mobile application and "
            "returns text responses. Listens on the configured local and forwarded port."
        )

        def __init__(self, args: list[str]) -> None:
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.process: ServerProcess | None = None
            self.worker: threading.Thread | None = None

        # -- SCM control ----------------------------------------------------

        def SvcStop(self) -> None:
            """Called by the SCM. Must return quickly."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            logger.info("SvcStop received")
            if self.process is not None:
                try:
                    self.process.stop()
                except Exception:
                    logger.exception("error while stopping server")
            win32event.SetEvent(self.stop_event)

        def SvcDoRun(self) -> None:
            try:
                self._run()
            except Exception:
                logger.exception("service failed")
                # Surface the failure in the Windows Event Log too; the log file
                # may be unreachable if the failure was path-related.
                servicemanager.LogErrorMsg(
                    f"Reception CRM Server failed: see log. {sys.exc_info()[1]}"
                )
                raise

        # -- actual work ----------------------------------------------------

        def _run(self) -> None:
            config = load_server_config()
            log_file = configure_logging(config, to_console=False)

            servicemanager.LogInfoMsg(
                f"Reception CRM Server starting. Log: {log_file}"
            )
            logger.info("--- service starting ---")

            self.process = ServerProcess(config)

            # serve_forever() blocks, so it runs on a worker thread and the main
            # thread stays free to answer SCM control requests.
            self.worker = threading.Thread(
                target=self._serve, name="reception-http", daemon=True
            )
            self.worker.start()

            if not self.process.wait_until_started(timeout=30):
                logger.error("server did not start within 30s")
                servicemanager.LogErrorMsg("Reception CRM Server did not start in time.")
                self.ReportServiceStatus(win32service.SERVICE_STOPPED)
                return

            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            logger.info("service running")

            win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
            logger.info("--- service stopped ---")

        def _serve(self) -> None:
            try:
                assert self.process is not None
                self.process.start()
            except Exception:
                logger.exception("serve thread crashed")
                # Let the SCM restart us according to the configured recovery
                # policy rather than sitting here doing nothing.
                win32event.SetEvent(self.stop_event)


def main() -> int:
    if not PYWIN32_AVAILABLE:
        print(
            "pywin32 is required for service mode. Install it with:\n"
            "    pip install pywin32",
            file=sys.stderr,
        )
        return 1

    if len(sys.argv) == 1:
        # Launched by the SCM (no arguments): hand control to the dispatcher.
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ReceptionCrmService)
        servicemanager.StartServiceCtrlDispatcher()
        return 0

    # Launched from a command line: install / start / stop / remove.
    win32serviceutil.HandleCommandLine(ReceptionCrmService)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
