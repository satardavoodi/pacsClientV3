"""
diagnostic_hooks/hook_manager.py
==================================
Entry point for real-app diagnostics (AIPACS_DIAG_MODE=1).

attach_to_app() is called once from main.py after AppHandler is created.
It:
  1. Creates the run directory under user_data/diagnostics/<timestamp>/
  2. Initialises a RealRunWriter.
  3. Monkey-patches ViewerController to install hooks on every new controller
     instance (via the existing ``_on_patient_opened`` signal if available,
     or a simple __init__ wrapper).
  4. Registers a finalise() callback so artifacts are written on shutdown.

Lifecycle
---------
    AIPACS_DIAG_MODE=1 → main.py → hook_manager.attach_to_app(app_handler)
    → HookManager._on_patient_tab_opened(patient_widget)
      → install_all(patient_widget, log.append)
    → app exit → HookManager._on_app_shutdown() → writer.finalize()
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from typing import Any, Optional


_manager_instance: Optional["HookManager"] = None


def attach_to_app(app_handler: Any) -> "HookManager":
    """Create the global HookManager and wire it to app_handler.

    Safe to call multiple times (idempotent — returns existing instance).
    """
    global _manager_instance
    if _manager_instance is not None:
        return _manager_instance

    mgr = HookManager(app_handler=app_handler)
    mgr.start()
    _manager_instance = mgr
    return mgr


def get_manager() -> Optional["HookManager"]:
    return _manager_instance


class HookManager:
    """Coordinates all real-app diagnostic hooks.

    Parameters
    ----------
    app_handler : Any
        The top-level AppHandler object returned by PacsClient.app_handler.
    run_dir : Path | None
        Override run directory (default: user_data/diagnostics/<timestamp>).
    """

    def __init__(
        self,
        app_handler: Any,
        run_dir: Optional[Path] = None,
    ) -> None:
        self._app_handler = app_handler
        self._started = False

        if run_dir is None:
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
            try:
                from PacsClient.utils.data_paths import USER_DATA_ROOT
                base = Path(USER_DATA_ROOT) / "diagnostics"
            except ImportError:
                base = Path("user_data") / "diagnostics"
            run_dir = base / f"real_run_{ts}"

        run_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir = run_dir

        from diagnostic_hooks.real_run_writer import RealRunWriter
        self._writer = RealRunWriter(
            run_dir=run_dir,
            scenario_name="real_run",
            modality="CT",
            slice_count=0,
        )

    def start(self) -> None:
        """Wire hooks to the application."""
        if self._started:
            return
        self._started = True

        self._wire_mainwindow()
        self._register_shutdown()

    def _wire_mainwindow(self) -> None:
        """Try to wire to the main window's patient-opened signal."""
        try:
            main_win = self._app_handler.main_window
        except AttributeError:
            return

        try:
            # HomePanelWidget emits this after a patient tab is opened
            main_win.patient_tab_opened.connect(self._on_patient_tab_opened)
        except AttributeError:
            pass  # signal not present in this version — hooks won't auto-attach

    def _on_patient_tab_opened(self, patient_widget: Any) -> None:
        """Install hooks on a newly opened PatientWidget."""
        from diagnostic_hooks.hooks import install_all

        log_append = self._writer.log.append
        try:
            install_all(patient_widget, log_append)
        except Exception as exc:
            print(f"[DiagHooks] install_all failed: {exc}", file=sys.stderr)

        # Update modality/slice from the first series info available
        try:
            modality = patient_widget.current_modality or "CT"
            self._writer.update_modality(modality)
        except AttributeError:
            pass

    def _register_shutdown(self) -> None:
        """Register cleanup for app shutdown."""
        try:
            from PacsClient.components.lifecycle_manager import LifecycleManager
            LifecycleManager.register_shutdown_callback(self._on_app_shutdown)
        except (ImportError, AttributeError):
            import atexit
            atexit.register(self._on_app_shutdown)

    def _on_app_shutdown(self) -> None:
        """Write final diagnostic artifacts."""
        try:
            self._writer.finalize()
            print(
                f"[DiagHooks] Artifacts written to: {self.run_dir}",
                file=sys.stderr,
            )
        except Exception as exc:
            print(
                f"[DiagHooks] finalize() failed: {exc}",
                file=sys.stderr,
            )
