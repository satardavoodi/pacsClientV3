"""Update UI: notification dialog, progress dialog, download worker.

All heavy work (manifest fetch, local hashing, downloads) runs in
:class:`UpdateWorker` (QThread); dialogs only render signal payloads.
Nothing downloads or installs without an explicit user click (design §5.4).
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


# ── worker ─────────────────────────────────────────────────────────────────

class UpdateWorker(QThread):
    """Fetch manifest → diff → download changed files → staged & ready."""

    phaseChanged = Signal(str)
    prepareProgress = Signal(int, int)                     # hashed n / total
    downloadProgress = Signal(int, int, "qint64", "qint64", str)
    stagedReady = Signal(dict)                              # {staging_root, version, ...}
    installerReady = Signal(str)                            # downloaded installer path
    failed = Signal(str)

    def __init__(self, summary: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self._summary = dict(summary)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:  # noqa: D102 - QThread entry
        try:
            from modules.auto_update import client

            summary = self._summary
            core = dict(summary.get("core") or {})
            version = str(core.get("available_version") or "")

            manifest = None
            if os.getenv("AIPACS_UPDATE_DELTA", "1") != "0":
                self.phaseChanged.emit("Fetching update manifest…")
                try:
                    manifest = client.fetch_core_manifest(summary)
                except Exception as exc:  # noqa: BLE001 — fall back below
                    logger.warning("auto-update: manifest fetch failed: %s", exc)
                    manifest = None

            if manifest is None:
                self._download_full_installer(client, summary)
                return

            self.phaseChanged.emit("Comparing installed files…")
            plan = client.build_update_plan(
                manifest,
                progress_cb=lambda done, total, _label: self.prepareProgress.emit(done, total),
            )
            if not plan.get("changed"):
                self.failed.emit(
                    "The update feed reports a new version but no file differs. "
                    "Please use the full installer from the update source."
                )
                return

            if client.installer_fallback_recommended(plan, summary):
                logger.info(
                    "auto-update: delta (%s bytes) not worthwhile — using installer",
                    plan.get("stored_bytes"),
                )
                self._download_full_installer(client, summary)
                return

            self.phaseChanged.emit("Downloading changed files…")
            staging = client.download_plan_files(
                plan,
                summary,
                progress_cb=self._emit_download_progress,
                cancel_check=self._is_cancelled,
            )
            self.stagedReady.emit(
                {
                    "staging_root": str(staging),
                    "version": version,
                    "changed_count": int(plan.get("changed_count") or 0),
                    "changed_bytes": int(plan.get("changed_bytes") or 0),
                    "stored_bytes": int(plan.get("stored_bytes") or 0),
                }
            )
        except InterruptedError:
            self.failed.emit("Update cancelled.")
        except Exception as exc:  # noqa: BLE001 — surface to the dialog
            logger.exception("auto-update: worker failed")
            self.failed.emit(str(exc))

    def _emit_download_progress(
        self, files_done: int, files_total: int, bytes_done: int, bytes_total: int, label: str
    ) -> None:
        self.downloadProgress.emit(files_done, files_total, bytes_done, bytes_total, label)

    def _download_full_installer(self, client, summary: dict[str, Any]) -> None:
        if os.getenv("AIPACS_UPDATE_INSTALLER_FALLBACK", "1") == "0":
            self.failed.emit("No incremental update manifest is available for this release.")
            return
        core = dict(summary.get("core") or {})
        artifact = str(core.get("artifact_path") or "").strip()
        if not artifact:
            self.failed.emit("The update source has no installer artifact.")
            return
        self.phaseChanged.emit("Downloading full installer…")
        import aipacs_runtime
        from aipacs_runtime import resolve_update_artifact_source, updates_cache_root

        context = dict(summary.get("source") or {})
        resolved = resolve_update_artifact_source(artifact, context=context)
        target_root = updates_cache_root() / "core"
        target_root.mkdir(parents=True, exist_ok=True)
        name = Path(artifact).name or "AIPacsUpdate.exe"
        target = target_root / name
        total = int(core.get("size") or 0)
        done = 0

        def _tick(n: int) -> None:
            nonlocal done
            done += n
            self.downloadProgress.emit(0, 1, done, total, name)

        client._fetch_to_file(resolved, target, progress=_tick, cancel_check=self._is_cancelled)
        expected = str(core.get("sha256") or "")
        if expected:
            from modules.auto_update import manifest as manifest_mod

            actual = manifest_mod.sha256_file(target)
            if actual != expected.lower():
                target.unlink(missing_ok=True)
                self.failed.emit("Installer download failed verification (hash mismatch).")
                return
        self.installerReady.emit(str(target))


# ── dialogs ────────────────────────────────────────────────────────────────

class UpdateNotificationDialog(QDialog):
    def __init__(self, summary: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        core = dict(summary.get("core") or {})
        self.setWindowTitle("AI-PACS Update Available")
        self.setModal(False)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        current = core.get("current_version") or "?"
        available = core.get("available_version") or "?"
        title = QLabel(f"<b>A new version of AI-PACS is available.</b>")
        layout.addWidget(title)
        layout.addWidget(QLabel(f"Installed version: {current}    →    New version: {available}"))
        if core.get("required"):
            badge = QLabel("<b style='color:#c62828;'>This is a required update.</b>")
            layout.addWidget(badge)

        notes = str(core.get("release_notes") or "").strip()
        if notes:
            browser = QTextBrowser(self)
            browser.setPlainText(notes)
            browser.setMaximumHeight(160)
            layout.addWidget(browser)

        info = QLabel("Only the changed files will be downloaded.")
        info.setStyleSheet("color: gray;")
        layout.addWidget(info)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        later = QPushButton("Later", self)
        later.clicked.connect(self.reject)
        update_now = QPushButton("Update Now", self)
        update_now.setDefault(True)
        update_now.clicked.connect(self.accept)
        buttons.addWidget(later)
        buttons.addWidget(update_now)
        layout.addLayout(buttons)


class UpdateProgressDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Updating AI-PACS")
        self.setModal(False)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        self.phase_label = QLabel("Preparing…", self)
        layout.addWidget(self.phase_label)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 0)  # busy until first real progress
        layout.addWidget(self.bar)
        self.detail_label = QLabel("", self)
        self.detail_label.setStyleSheet("color: gray;")
        layout.addWidget(self.detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_button = QPushButton("Cancel", self)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)
        self._last_time = 0.0
        self._last_bytes = 0

    def set_phase(self, text: str) -> None:
        self.phase_label.setText(text)

    def set_prepare_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        self.detail_label.setText(f"Checked {done} of {total} files")

    def set_download_progress(
        self, files_done: int, files_total: int, bytes_done: int, bytes_total: int, label: str
    ) -> None:
        if bytes_total > 0:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(bytes_done * 1000 / max(1, bytes_total)))
        now = time.monotonic()
        speed = ""
        if self._last_time and now > self._last_time:
            rate = (bytes_done - self._last_bytes) / (now - self._last_time)
            if rate > 0:
                speed = f" — {rate / (1024 * 1024):.1f} MB/s"
        self._last_time, self._last_bytes = now, bytes_done
        self.detail_label.setText(
            f"File {min(files_done + 1, files_total)} of {files_total} — "
            f"{bytes_done / (1024 * 1024):.1f} / {bytes_total / (1024 * 1024):.1f} MB{speed}"
        )


# ── flow orchestration ─────────────────────────────────────────────────────

def _keep_ref(parent, obj) -> None:
    refs = getattr(parent, "_auto_update_ui_refs", None)
    if refs is None:
        refs = []
        setattr(parent, "_auto_update_ui_refs", refs)
    refs.append(obj)


def show_update_notification(parent, summary: dict[str, Any]) -> None:
    """Entry point wired to AutoUpdateService.updateAvailable."""
    dialog = UpdateNotificationDialog(summary, parent)
    _keep_ref(parent, dialog)
    dialog.accepted.connect(lambda: begin_update_flow(parent, summary))
    dialog.show()
    dialog.raise_()


def begin_update_flow(parent, summary: dict[str, Any]) -> None:
    progress = UpdateProgressDialog(parent)
    worker = UpdateWorker(summary, parent)
    _keep_ref(parent, progress)
    _keep_ref(parent, worker)

    worker.phaseChanged.connect(progress.set_phase)
    worker.prepareProgress.connect(progress.set_prepare_progress)
    worker.downloadProgress.connect(progress.set_download_progress)
    progress.cancel_button.clicked.connect(worker.cancel)

    def _on_failed(message: str) -> None:
        progress.close()
        QMessageBox.warning(parent, "AI-PACS Update", f"The update could not be completed:\n\n{message}")

    def _on_staged(info: dict) -> None:
        progress.close()
        _prompt_restart_and_install(parent, info)

    def _on_installer(path: str) -> None:
        progress.close()
        _launch_installer_and_quit(parent, path)

    worker.failed.connect(_on_failed)
    worker.stagedReady.connect(_on_staged)
    worker.installerReady.connect(_on_installer)
    progress.show()
    worker.start()


def _prompt_restart_and_install(parent, info: dict) -> None:
    version = info.get("version") or "?"
    size_mb = int(info.get("stored_bytes") or 0) / (1024 * 1024)
    choice = QMessageBox.question(
        parent,
        "AI-PACS Update Ready",
        (
            f"Version {version} has been downloaded ({info.get('changed_count')} files, "
            f"{size_mb:.1f} MB).\n\nRestart AI-PACS now to install it?\n\n"
            "All settings and patient data are preserved."
        ),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if choice != QMessageBox.Yes:
        logger.info("auto-update: user postponed staged install of %s", version)
        return
    try:
        from modules.auto_update import apply as apply_mod

        prepared = apply_mod.prepare_apply(
            info["staging_root"], str(version), wait_pid=os.getpid()
        )
        apply_mod.launch_apply_helper(prepared)
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto-update: failed to launch apply helper")
        QMessageBox.warning(
            parent, "AI-PACS Update", f"Could not start the update helper:\n\n{exc}"
        )
        return
    logger.info("auto-update: helper launched — exiting for update to %s", version)
    QApplication.quit()


def _launch_installer_and_quit(parent, installer_path: str) -> None:
    choice = QMessageBox.question(
        parent,
        "AI-PACS Update Ready",
        (
            "The full installer has been downloaded and verified.\n\n"
            "AI-PACS will close and the installer will start. Your settings and "
            "patient data are preserved by the installer.\n\nContinue?"
        ),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if choice != QMessageBox.Yes:
        return
    try:
        subprocess.Popen(
            [installer_path],
            cwd=str(Path(installer_path).parent),
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        QMessageBox.warning(parent, "AI-PACS Update", f"Could not start the installer:\n\n{exc}")
        return
    QApplication.quit()


__all__ = [
    "UpdateWorker",
    "UpdateNotificationDialog",
    "UpdateProgressDialog",
    "show_update_notification",
    "begin_update_flow",
]
