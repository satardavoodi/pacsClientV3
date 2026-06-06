"""EchoMindCommandAdapter — voice-command access to the reporting workflow.

Phase 2 of the orchestrator→CommandBus bridge (2026-06-06): exposes the
EchoMind chat/report flows as bus actions so "start a report", "transcribe
this voice report", "generate the report" and "send the report to PACS" work
by voice. Every action drives the SAME production UI objects the user clicks:

* window  = patient_tab.ai_chat_layout_ui()          (the EchoMind window)
* page    = window._page after _open_mode_page('report')
* attach  = page.composer._choose_file(<audio>)       (same as the audio
            attachments "Report" button → open_report_in_echo_mind)
* generate= page.composer.btn_send.click()            (same as pressing Send)
* send    = page._send_to_reception(<latest AI bubble>) — which opens the
            interactive reception dialog. That dialog IS the clinical human
            gate (validate + choose reception ID); this adapter never
            bypasses it, so voice cannot silently push a report to PACS.

All failures return typed, recoverable error envelopes; nothing raises.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from ..command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)

_AUDIO_EXTS = (".wav", ".mp3", ".m4a", ".ogg", ".webm")


def _err(action: str, code: str, msg: str) -> CommandResult:
    return CommandResult(ok=False, action=action, error_code=code, message=msg)


class EchoMindCommandAdapter:
    """Reporting-workflow commands bound to the ACTIVE patient tab."""

    def __init__(
        self,
        get_active_patient_tab: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._get_tab = get_active_patient_tab or (lambda: None)

    # ── helpers ──────────────────────────────────────────────────────
    def _tab(self):
        try:
            return self._get_tab()
        except Exception:
            return None

    def _open_report_window(self, tab) -> tuple[Any, Any, str]:
        """(window, report_page, error_code) — opens/raises the EchoMind
        window on the report page for *tab*. error_code is '' on success."""
        opener = getattr(tab, "ai_chat_layout_ui", None)
        if not callable(opener):
            return None, None, "NO_ECHOMIND"
        try:
            window = opener()
        except Exception:
            logger.exception("echomind adapter: ai_chat_layout_ui failed")
            return None, None, "OPEN_FAILED"
        if window is None:
            return None, None, "OPEN_FAILED"
        try:
            window.show()
            window.raise_()
        except Exception:
            pass
        try:
            window._open_mode_page("report")
        except Exception:
            logger.exception("echomind adapter: _open_mode_page('report') failed")
            return window, None, "NO_REPORT_PAGE"
        page = getattr(window, "_page", None)
        if page is None:
            return window, None, "NO_REPORT_PAGE"
        return window, page, ""

    @staticmethod
    def _latest_audio_for(tab) -> str:
        """Newest audio attachment path for the tab's study, or ''."""
        try:
            from PacsClient.utils.config import ATTACHMENT_PATH
            study_uid = str(getattr(tab, "study_uid", "") or "")
            if not study_uid:
                return ""
            attach_dir = Path(ATTACHMENT_PATH) / study_uid
            if not attach_dir.exists():
                return ""
            files = [p for ext in _AUDIO_EXTS for p in attach_dir.glob(f"*{ext}")]
            if not files:
                return ""
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return str(files[0])
        except Exception:
            return ""

    @staticmethod
    def _attach_audio(page, audio_path: str) -> bool:
        try:
            composer = getattr(page, "composer", None)
            chooser = getattr(composer, "_choose_file", None)
            if not callable(chooser) or not audio_path or not os.path.exists(audio_path):
                return False
            chooser(audio_path)
            return True
        except Exception:
            logger.exception("echomind adapter: attaching audio failed")
            return False

    # ── action: start_report ─────────────────────────────────────────
    def start_report(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Open EchoMind on the report page for the active patient; attach
        the newest voice recording when one exists (entities.attach_audio
        defaults True)."""
        tab = self._tab()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB",
                        "Open a patient first — reports are per patient tab.")
        window, page, code = self._open_report_window(tab)
        if code:
            return _err(plan.action, code, "Could not open the EchoMind report page.")
        attached = ""
        if bool((plan.entities or {}).get("attach_audio", True)):
            audio = self._latest_audio_for(tab)
            if audio and self._attach_audio(page, audio):
                attached = os.path.basename(audio)
        return CommandResult(
            ok=True, action=plan.action,
            message=("Report page opened"
                     + (f" with voice file {attached} attached." if attached else ".")),
            data={"study_uid": str(getattr(tab, "study_uid", "") or ""),
                  "audio_attached": attached or None},
        )

    # ── action: transcribe_voice ─────────────────────────────────────
    def transcribe_voice(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Open the report page and attach the patient's newest voice
        recording for transcription. Fails typed when no recording exists."""
        tab = self._tab()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB",
                        "Open a patient first — transcription needs a patient tab.")
        audio = self._latest_audio_for(tab)
        if not audio:
            return _err(plan.action, "NO_AUDIO",
                        "No voice recording found for this patient's study.")
        window, page, code = self._open_report_window(tab)
        if code:
            return _err(plan.action, code, "Could not open the EchoMind report page.")
        if not self._attach_audio(page, audio):
            return _err(plan.action, "ATTACH_FAILED",
                        "Could not hand the voice file to the report composer.")
        # Prefer the Transcribe composer tab when present (best-effort).
        try:
            composer = page.composer
            idx = composer._tab_index_by_key.get("transcribe")
            if idx is not None:
                composer.mode_tabs.setCurrentIndex(int(idx))
        except Exception:
            pass
        return CommandResult(
            ok=True, action=plan.action,
            message=f"Voice file {os.path.basename(audio)} loaded for transcription.",
            data={"audio": os.path.basename(audio)},
        )

    # ── action: generate_report ──────────────────────────────────────
    def generate_report(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Press Send on the report composer — identical to the user click."""
        tab = self._tab()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB", "Open a patient first.")
        window, page, code = self._open_report_window(tab)
        if code:
            return _err(plan.action, code, "Could not open the EchoMind report page.")
        try:
            btn = page.composer.btn_send
        except Exception:
            return _err(plan.action, "NO_COMPOSER", "Report composer is unavailable.")
        try:
            if not btn.isVisible() or not btn.isEnabled():
                return _err(plan.action, "NOT_READY",
                            "Nothing to generate yet — dictate, type, or attach "
                            "a voice file first.")
            btn.click()
        except Exception as exc:  # noqa: BLE001
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(
            ok=True, action=plan.action,
            message="Report generation triggered — the result will appear in EchoMind.",
            data=None,
        )

    # ── action: send_report_to_pacs ──────────────────────────────────
    def send_report_to_pacs(self, plan: CommandPlan, state: dict) -> CommandResult:
        """Invoke the SAME send flow as the report bubble's send button for
        the newest AI report bubble. The interactive reception dialog (choose
        / confirm reception ID, server-side patient validation) remains the
        clinical human gate — voice cannot bypass it."""
        tab = self._tab()
        if tab is None:
            return _err(plan.action, "NO_ACTIVE_TAB", "Open a patient first.")
        window, page, code = self._open_report_window(tab)
        if code:
            return _err(plan.action, code, "Could not open the EchoMind report page.")
        bubble = self._latest_sendable_bubble(page)
        if bubble is None:
            return _err(plan.action, "NO_REPORT",
                        "No generated report found — say 'generate the report' first.")
        sender = getattr(page, "_send_to_reception", None)
        if not callable(sender):
            sender = getattr(bubble, "_on_send_reception_cb", None)
        if not callable(sender):
            return _err(plan.action, "NO_SEND_PATH",
                        "This report bubble has no reception-send handler.")
        try:
            sender(bubble)
        except Exception as exc:  # noqa: BLE001
            logger.exception("echomind adapter: send_to_reception raised")
            return _err(plan.action, "DISPATCH_FAILED", str(exc))
        return CommandResult(
            ok=True, action=plan.action,
            message=("Send dialog opened — confirm the reception ID to deliver "
                     "the report."),
            data=None,
        )

    @staticmethod
    def _latest_sendable_bubble(page):
        """Newest non-user bubble that carries the reception-send affordance."""
        try:
            history = getattr(page, "history", None)
            vbox = getattr(history, "vbox", None)
            if vbox is None:
                return None
            for i in range(vbox.count() - 1, -1, -1):
                item = vbox.itemAt(i)
                w = item.widget() if item is not None else None
                if w is None:
                    continue
                if bool(getattr(w, "_is_user", False)):
                    continue
                if getattr(w, "_on_send_reception_cb", None) is not None:
                    return w
            return None
        except Exception:
            return None


ECHOMIND_ACTIONS = {
    "start_report":        "start_report",
    "transcribe_voice":    "transcribe_voice",
    "generate_report":     "generate_report",
    "send_report_to_pacs": "send_report_to_pacs",
}

__all__ = ["EchoMindCommandAdapter", "ECHOMIND_ACTIONS"]
