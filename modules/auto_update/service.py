"""Startup update-check service (Qt layer, GUI thread never blocked).

Wired from ``main.py`` AFTER the main window is shown.  The check runs on a
daemon thread after a delay (OPT-22 lesson: never add startup work to the GUI
thread); results come back via Qt signals (queued into the GUI thread).

Flags:
- ``AIPACS_AUTO_UPDATE_CHECK``  — "0" kill switch, "1" force-on (also in dev).
  Unset: enabled only for FROZEN builds, honoring the
  ``auto_check_on_startup`` key (default true) in ``update_sources.json``.
- ``AIPACS_UPDATE_CHECK_DELAY_S`` — seconds before the startup check (default 20).
"""

from __future__ import annotations

import logging
import os
import threading

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

_DEFAULT_DELAY_S = 20.0


def auto_update_check_enabled() -> bool:
    env = os.getenv("AIPACS_AUTO_UPDATE_CHECK", "").strip()
    if env == "0":
        return False
    if env == "1":
        return True
    try:
        import aipacs_runtime

        if not aipacs_runtime.is_frozen():
            return False  # dev runs stay quiet unless forced
        payload = aipacs_runtime.load_update_sources()
        return bool(payload.get("auto_check_on_startup", True))
    except Exception:
        return False


def startup_check_delay_s() -> float:
    try:
        return max(1.0, float(os.getenv("AIPACS_UPDATE_CHECK_DELAY_S", "") or _DEFAULT_DELAY_S))
    except Exception:
        return _DEFAULT_DELAY_S


def _attach_update_log_handler() -> None:
    """Route modules.auto_update logs to user_data/logs/auto_update.log too."""
    try:
        from PacsClient.utils.data_paths import LOGS_DIR

        root = logging.getLogger("modules.auto_update")
        if any(getattr(h, "_aipacs_auto_update", False) for h in root.handlers):
            return
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(str(LOGS_DIR / "auto_update.log"), encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler._aipacs_auto_update = True  # type: ignore[attr-defined]
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    except Exception:
        pass  # logging must never break startup


class AutoUpdateService(QObject):
    """Delayed startup check + manual re-check. Emits into the GUI thread."""

    updateAvailable = Signal(dict)   # summary from client.check_for_core_update()
    upToDate = Signal()              # manual checks only
    checkFailed = Signal(str)        # manual checks only

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._started = False

    # ── startup path ───────────────────────────────────────────────────
    def start(self, delay_ms: int | None = None) -> None:
        if self._started:
            return
        self._started = True
        effective = int(delay_ms if delay_ms is not None else startup_check_delay_s() * 1000)
        QTimer.singleShot(effective, self._spawn_startup_thread)

    def _spawn_startup_thread(self) -> None:
        threading.Thread(
            target=self._startup_worker, name="aipacs-auto-update-check", daemon=True
        ).start()

    def _startup_worker(self) -> None:
        _attach_update_log_handler()
        # Always run the cheap post-update housekeeping, even when checks are off:
        # version reconcile after a delta apply + health marker + prune.
        try:
            from modules.auto_update import apply as apply_mod

            apply_mod.reconcile_version_on_boot()
            apply_mod.post_boot_maintenance()
        except Exception as exc:  # noqa: BLE001 — never break startup
            logger.warning("auto-update: boot maintenance failed: %s", exc)

        if not auto_update_check_enabled():
            logger.info("auto-update: startup check disabled")
            return
        self._run_check(silent=True)

    # ── manual path (Settings) ─────────────────────────────────────────
    def check_now(self) -> None:
        threading.Thread(
            target=self._run_check, kwargs={"silent": False},
            name="aipacs-auto-update-manual", daemon=True,
        ).start()

    # ── shared ─────────────────────────────────────────────────────────
    def _run_check(self, *, silent: bool) -> None:
        try:
            from modules.auto_update import client

            summary = client.check_for_core_update()
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto-update: check failed: %s", exc)
            if not silent:
                self.checkFailed.emit(str(exc))
            return
        if summary:
            self.updateAvailable.emit(dict(summary))
        elif not silent:
            self.upToDate.emit()


__all__ = ["AutoUpdateService", "auto_update_check_enabled", "startup_check_delay_s"]
