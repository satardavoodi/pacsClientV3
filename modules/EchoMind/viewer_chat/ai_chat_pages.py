from __future__ import annotations

import typing as t
import logging
import os, json, tempfile, time
import base64
import hashlib
import requests
import uuid
from datetime import datetime
from PySide6.QtCore import Qt, QSize, QTimer, QEvent, Signal
from PySide6.QtGui import QIcon, QAction, QPixmap, QPainter, QFont, QTextCursor, QColor, QPen, QTextDocument,QFontMetrics, QGuiApplication, QTextOption, QCursor, QTextBlockFormat
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QInputDialog, QLineEdit, QMessageBox, QMenu, QToolButton, QLabel, QSlider, QSizePolicy, QStyle,
    QDialog, QTreeWidget, QTreeWidgetItem, QProgressDialog, QHeaderView
)
from PacsClient import utils as U
from PacsClient.utils.database import (
    load_token_usage,
    save_token_usage,
    get_db_connection,
    add_token_usage_delta,
    add_api_token_usage_delta,
    add_transcript_usage_delta,
    add_api_transcript_usage_delta,
    load_api_transcript_usage_for_key,
    ai_save_reception_report,
)

from .openai_reporter import reporter, translate_report, standardize, standard_assist_search, correction, translate_text_to_persian
from . import openai_parallel_backend as openai_direct
from . import openai_reporter as company_direct
import re
try:
    from PacsClient.utils import ICON_PATH
except Exception:
    ICON_PATH = "."
from dataclasses import dataclass
from html import escape
from .api_manager import  APIKeyManager,Manage


safe = escape("<div>")
from PySide6.QtCore import QObject, Signal, Slot, QThread
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QPushButton,
    QPlainTextEdit, QScrollArea, QMenu, QFileDialog, QSpacerItem,QFrame,QSizePolicy,
    QDialog, QDialogButtonBox, QTextEdit,QComboBox, QMenu,QGraphicsOpacityEffect

)

from .ai_chat_helpers import _set_icon, _safe_fa_connection_error, extract_plain_text_from_html, style_popup, themed_message_box, themed_input_text
from .ai_chat_api import ChatApiClient, ChatController, ApiWorker
from .ai_chat_widgets import ChatHistory, UnifiedComposer, MessageBubble, PATIENT_SCROLLBAR_QSS
from .ai_chat_config import CLR_BG, CLR_BG_PANEL, CLR_TEXT, CLR_BORDER, CLR_ACCENT,URL_GEN_TRANSCRIPT,URL_GEN_REPORT,URL_CHAT,URL_GEN_ASSISTANT,URL_STATUS,URL_SESSIONS,URL_HEALTH,URL_EXPORT_ALL,URL_SEARCH,URL_SESSION_GET,REPORT_MODALITIES,TURBO_BACKEND
from modules.EchoMind import echomind_http
from modules.EchoMind.llm_client import get_active_backend_display_name, is_active_backend_configured
from modules.EchoMind.settings_store import get_echomind_api_key, get_llm_backend, get_openai_model_for_feature, get_openai_settings


def _resolve_active_ai_identity() -> tuple[str, str | None, str | None]:
    if get_llm_backend() == "openai":
        cfg = get_openai_settings()
        api_key = str(cfg.get("api_key") or "").strip()
        return "openai", "OpenAI", api_key or None

    # 2026-08-09: one authority for both paths. This used to test the in-memory
    # manager only, so a licensed user whose key was on disk but not yet re-validated
    # this session looked unlicensed to Send while Turbo self-healed. Same question,
    # same answer, asked once.
    from modules.EchoMind.entitlement import company_entitled
    if not company_entitled():
        return "company", None, None
    try:
        info = Manage.instance().ensure_detected()
        return "company", getattr(info, "center_display", None) or "EchoMind", getattr(info, "irannobat_key", None)
    except Exception:
        return "company", None, None


def _log_usage_for_ui(api_key: str | None, usage: dict | None) -> None:
    if not usage:
        return
    if str(usage.get("provider") or "").strip().lower() == "openai":
        return

    center = str(usage.get("center") or "Unknown").strip() or "Unknown"
    model_name = str(usage.get("model") or "Unknown").strip() or "Unknown"
    total = int(usage.get("total_tokens") or 0)
    if total <= 0:
        return

    add_token_usage_delta(center, model_name, total)
    if api_key:
        add_api_token_usage_delta(
            api_key=api_key,
            center_name=center,
            model_name=model_name,
            tokens_delta=total,
        )


#: The two things that can go wrong before a transcript exists, and they are not
#: the same thing. Kept apart so the message always matches the cause.
_VOICE_RETRY_LOW_QUALITY = (
    "Voice quality seems low — automatically retrying in noisy-voice mode..."
)
_VOICE_RETRY_SERVER = (
    "The transcription server did not respond — retrying once..."
)


def _transcribe_with_active_backend(paths: list[str], quality_mode: str = "clear") -> dict:
    """Transcribe via the provider configured in Settings ▸ EchoMind ▸ Voice to Text.

    (Historically this hard-coded a POST to ``{AI_BASE}/generate_transcript`` for the
    "company" backend. The endpoint now lives in Settings — see
    ``modules/EchoMind/voice_transcription.py``.)
    """
    from modules.EchoMind.voice_transcription import VoiceTranscriptionService

    return VoiceTranscriptionService().transcribe(paths, quality_mode=quality_mode)


# ── F1 (2026-07-28): "Send to Reception" must not block the GUI thread ───────
# `_send_to_reception` used to call its nested `_send_with_patient_id` inline:
# a `requests.get(timeout=20)`, a `requests.post(timeout=30)` and a DB write, all
# on the Qt main thread with no spinner, no wait cursor and no cancel. On a slow
# or unreachable reception server that is a ~50 s hard freeze of the entire
# workstation. The work now runs on an `ApiWorker`; every Qt touch is returned to
# the GUI thread as data (see `_deliver_reception_result`).
#
# `AIPACS_ECHOMIND_RECEPTION_ASYNC=0` restores the fully-synchronous legacy path.
_ENV_RECEPTION_ASYNC = "AIPACS_ECHOMIND_RECEPTION_ASYNC"


def _reception_send_async_enabled() -> bool:
    """Kill switch for the off-GUI-thread reception send (default ON)."""
    raw = os.environ.get(_ENV_RECEPTION_ASYNC)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


# ── 2026-07-31: Send-with-a-voice-attachment never actually sent ─────────────
# `_upload_voices_then` documents "Always calls: cont(transcript_text,
# session_id)" and its error path does exactly that. Its SUCCESS path did not —
# the call was commented out, and `git blame` puts that comment in the initial
# commit, so this has never run in this repository's history.
#
# `cont` IS the send. All four call sites pass a continuation that runs
# `_send_with_mode(...)` or `_on_send_chatgpt(...)`. Without it, pressing Send
# with a voice chip queued uploaded the audio, transcribed it, drew a bubble and
# stopped: no report, no error, and the transcript stranded in read-only history
# where the user cannot even re-send it without copying it out by hand.
#
# Reachability: the ordinary mic flow does NOT come through here — recording
# auto-emits `transcribeRequested` -> `_transcribe_now`, which drops the chip on
# success. This path is reached when a transcription failed or was cancelled and
# the chip survived, or when an audio file was attached by hand.
#
# `AIPACS_ECHOMIND_VOICE_SEND_CONT=0` restores the byte-identical legacy
# behaviour (transcript shown as a bubble, nothing sent).
_ENV_VOICE_SEND_CONT = "AIPACS_ECHOMIND_VOICE_SEND_CONT"


def _voice_send_cont_enabled() -> bool:
    """Kill switch for issuing the queued send after a voice upload (default ON)."""
    raw = os.environ.get(_ENV_VOICE_SEND_CONT)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


# ── F8 (2026-07-28): stop printing clinical content to stdout ────────────────
# The four chat modes used to `print()` the FULL outgoing payload — the
# physician's dictated text — and the FULL response body — the generated
# report — on every request. That is patient content on stdout: unconditional,
# not gated by any log level, impossible to switch off, and captured by any
# shell transcript or console log. Serialising a large report to stdout on every
# request also costs real time on the worker thread.
#
# These helpers keep the diagnostics that were actually useful (which endpoint,
# what status, how big, how long) and drop the bodies. Set the `echomind.chat`
# logger to DEBUG to see sizes; the content itself is never logged.
_log = logging.getLogger("echomind.chat")


def _dbg_request(tag: str, url: str, payload: dict) -> None:
    """Log an outbound chat request WITHOUT its clinical content.

    2026-07-31 — both measurements used to run BEFORE the level check, so the
    work happened on every request even with debug logging off. `payload`
    carries base64 DICOM->PNG attachments, so a three-image request built and
    threw away a multi-megabyte JSON string every time. The F8 fix stopped the
    bodies being EMITTED; this stops them being MATERIALISED.
    """
    # Local import on purpose: `test_no_clinical_content_on_stdout` extracts
    # these two helpers with ast and execs them in a bare namespace that has
    # `_log` but not the `logging` module.
    import logging as _logging
    if not _log.isEnabledFor(_logging.DEBUG):
        return
    try:
        keys = sorted(payload.keys()) if isinstance(payload, dict) else []
        size = len(json.dumps(payload, ensure_ascii=False)) if payload else 0
        _log.debug("[%s] POST %s keys=%s payload_bytes=%d", tag, url, keys, size)
    except Exception:
        pass


def _dbg_response(tag: str, resp) -> None:
    """Log an inbound chat response WITHOUT its clinical content.

    2026-07-31 — `requests` does NOT cache `.text`: every access re-decodes the
    whole body, and with no charset in the header it runs full charset
    detection over a 100-500 KB report. Prefer the Content-Length header, and
    do nothing at all when debug logging is off.
    """
    # Local import on purpose: `test_no_clinical_content_on_stdout` extracts
    # these two helpers with ast and execs them in a bare namespace that has
    # `_log` but not the `logging` module.
    import logging as _logging
    if not _log.isEnabledFor(_logging.DEBUG):
        return
    try:
        body_len = -1
        try:                                  # cheap: header, then raw bytes
            hdr = getattr(resp, "headers", None)
            if hdr is not None:
                body_len = int(hdr.get("Content-Length", -1))
        except Exception:
            body_len = -1
        if body_len < 0:
            raw = getattr(resp, "content", None)
            body_len = len(raw) if raw is not None else len(getattr(resp, "text", "") or "")
        _log.debug(
            "[%s] status=%s body_bytes=%d", tag, getattr(resp, "status_code", "?"), body_len
        )
    except Exception:
        pass


# ── F7 (2026-07-28): ONE place decides which LLM backend serves a feature ────
# The choice `X if backend == "openai" else Y` was written out at TWELVE call
# sites in this file (Turbo report, correction ×2, standardize, assist/search,
# translate ×2, breast, image-quality, ChatGPT modes…). Each one is correct
# today, but the pattern means a NEW EchoMind feature that forgets the ternary
# silently ignores the user's LLM selection — with no test that would catch it.
# `openai_reporter._openai_result` was an abandoned attempt at exactly this
# unification: fully implemented, never called.
#
# These two helpers are the authority. Call sites ask WHICH MODULE and WHICH
# MODEL; they never re-derive the backend. This is the standing project
# directive: route decisions through the one authority, not bespoke checks.
def _ai_backend() -> str:
    """``"openai"`` or ``"company"`` — the single read of the setting."""
    return "openai" if get_llm_backend() == "openai" else "company"


def _ai_module(backend: str | None = None):
    """The module implementing the AI features for the ACTIVE backend.

    * ``openai``  -> ``openai_parallel_backend`` (provider-aware, via
      ``llm_client.chat_completion``);
    * ``company`` -> ``openai_reporter`` (the GapGPT implementation).

    Both expose the same function names — `reporter`, `correction`,
    `standardize`, `standard_assist_search`, `translate_text_to_persian`,
    `translate_report`, `BreastExpertAssistant`, `ImageQualityAnalyzer`.
    """
    resolved = backend or _ai_backend()
    return openai_direct if resolved == "openai" else company_direct


def _ai_model(feature: str, company_default: str, backend: str | None = None) -> str:
    """The model for `feature` on the active backend.

    The company path keeps its historical hard-coded default; the OpenAI path
    reads the per-feature model from Settings ▸ EchoMind.
    """
    resolved = backend or _ai_backend()
    if resolved == "openai":
        return get_openai_model_for_feature(feature, company_default)
    return company_default


# ── In-flight ApiWorker QThreads that must OUTLIVE their page ────────────────
# THE close-while-transcribing CRASH (2026-07-12).
#
# ApiWorker is a **QThread** (ai_chat_api.py:64) and is created with
# ``parent=<the page>``. The EchoMind window is ``WA_DeleteOnClose``, so closing it
# deletes the page — and Qt deletes the page's children with it, including that
# QThread. If a request (transcription!) is still running, Qt aborts the WHOLE
# process:
#
#     QThread: Destroyed while thread is still running   ->  qFatal -> abort()
#
# abort() gives NO Python traceback and NO faulthandler entry — app.log simply
# STOPS. That is exactly what the logs show: at 2026-07-12 23:47:01 the teardown
# logged "page teardown DONE" and the log ends on the very next line. It only ever
# happens while a request is in flight, i.e. while transcribing.
#
# We cannot just wait for the worker (the HTTP call can take minutes and would
# freeze the GUI). Instead we DETACH it on teardown: disconnect its signals so its
# result can never reach the dying page, reparent it to None so Qt will NOT delete
# it, and hold a reference here until it finishes and deletes itself.
_ORPHANED_WORKERS: list = []


def _release_orphan_worker(w) -> None:
    """A detached worker finished on its own — drop our ref and let Qt free it."""
    try:
        _ORPHANED_WORKERS.remove(w)
    except Exception:
        pass
    try:
        w.deleteLater()
    except Exception:
        pass


class _ReceptionIdDialog(QDialog):
    """Prompt the user for the reception ID a report should be sent to.

    Offers the current study's patient as a one-click choice and also
    accepts a manually entered reception ID for a different patient.
    After ``exec()`` returns ``QDialog.Accepted``, ``selected_patient_id``
    holds the chosen ID and ``mode`` is either ``"current"`` or ``"other"``.
    """

    def __init__(self, parent=None, current_patient_id: str | None = None,
                 current_status: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Select Reception ID")
        self.setMinimumWidth(420)
        # Explicit, theme-independent colours so the confirmation text is
        # readable on every Windows light/dark theme (never inherits the
        # system palette). Gated by AIPACS_ECHO_POPUP_THEME (default on).
        style_popup(self)
        self.selected_patient_id: str | None = None
        self.mode: str | None = None
        self.selected_status: str = "pending"

        layout = QVBoxLayout(self)

        title = QLabel("Select the reception ID this report should be sent to:")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Report status to set alongside the report text (same status model
        # as the patient sync workflow — modules.network.socket_report_status_service).
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Report status:"))
        self._status_combo = QComboBox()
        try:
            from modules.network.socket_report_status_service import REPORT_STATUSES
            for status_key, status_label in REPORT_STATUSES.items():
                self._status_combo.addItem(status_label, status_key)
        except Exception:
            self._status_combo.addItem("Pending", "pending")
        if current_status is not None:
            idx = self._status_combo.findData(current_status)
            if idx >= 0:
                self._status_combo.setCurrentIndex(idx)
        status_row.addWidget(self._status_combo, 1)
        layout.addLayout(status_row)

        if current_patient_id:
            btn_current = QPushButton(f"Send to current patient  ({current_patient_id})")
            btn_current.setObjectName("ReceptionIdPrimaryButton")
            btn_current.setDefault(True)
            btn_current.clicked.connect(
                lambda: self._choose(current_patient_id, "current")
            )
            layout.addWidget(btn_current)

        layout.addWidget(QLabel("Or send to another reception ID:"))

        row = QHBoxLayout()
        self._other_input = QLineEdit()
        self._other_input.setPlaceholderText("Enter reception ID...")
        self._other_input.returnPressed.connect(self._choose_other)
        row.addWidget(self._other_input)
        btn_other = QPushButton("Send")
        btn_other.clicked.connect(self._choose_other)
        row.addWidget(btn_other)
        layout.addLayout(row)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _choose(self, patient_id: str, mode: str) -> None:
        self.selected_patient_id = str(patient_id or "").strip()
        self.mode = mode
        try:
            self.selected_status = self._status_combo.currentData() or "pending"
        except Exception:
            self.selected_status = "pending"
        self.accept()

    def _choose_other(self) -> None:
        other_id = (self._other_input.text() or "").strip()
        if not other_id:
            themed_message_box(
                self, QMessageBox.Icon.Warning, "Invalid Input",
                "Please enter a valid reception ID."
            )
            return
        self._choose(other_id, "other")


class _ImageSourceDialog(QDialog):
    """Select source for image attachments."""

    def __init__(self, parent=None, current_patient_id: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Attach Image Source")
        self.setMinimumWidth(460)
        # Explicit popup colours (see _ReceptionIdDialog) — readable on any
        # Windows theme; AIPACS_ECHO_POPUP_THEME=0 restores legacy.
        style_popup(self)
        self.selected_source: str | None = None

        layout = QVBoxLayout(self)
        title = QLabel("Choose image source:")
        title.setWordWrap(True)
        layout.addWidget(title)

        btn_local = QPushButton("From this system")
        btn_local.clicked.connect(lambda: self._select("local"))
        layout.addWidget(btn_local)

        if current_patient_id:
            btn_current = QPushButton(f"From current patient ({current_patient_id})")
            btn_current.clicked.connect(lambda: self._select("current"))
            layout.addWidget(btn_current)

        btn_other = QPushButton("From another patient (enter patient id)")
        btn_other.clicked.connect(lambda: self._select("other"))
        layout.addWidget(btn_other)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _select(self, source: str) -> None:
        self.selected_source = source
        self.accept()


class _PatientSeriesImagePickerDialog(QDialog):
    """Series selector + image preview selector for patient images."""

    def __init__(self, parent=None, patient_id: str | None = None, records: list[dict] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Select Patient Images")
        self.resize(980, 640)
        self.patient_id = (patient_id or "").strip()
        self.records = records or []
        self.selected_paths: list[str] = []

        self.setStyleSheet(
            """
            QDialog {
                background-color: #e9eef4;
                color: #162536;
            }
            QLabel {
                color: #0f2235;
                font-weight: 600;
            }
            QPushButton {
                background-color: #2f80c9;
                color: #ffffff;
                border: 1px solid #1f5f98;
                border-radius: 7px;
                padding: 6px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #246fae;
            }
            QTreeWidget {
                background: #f8fbff;
                color: #102132;
                border: 1px solid #b7c7d7;
                border-radius: 8px;
                alternate-background-color: #edf4fb;
                selection-background-color: #b8dcff;
                selection-color: #081521;
                outline: 0;
            }
            QTreeWidget::item {
                min-height: 26px;
                border-bottom: 1px solid #dce6f0;
                padding: 2px 3px;
            }
            QTreeWidget::indicator {
                width: 16px;
                height: 16px;
            }
            QTreeWidget::indicator:unchecked {
                border: 1px solid #486581;
                background: #ffffff;
            }
            QTreeWidget::indicator:checked {
                border: 1px solid #1d5f98;
                background: #2f80c9;
            }
            QHeaderView::section {
                background: #d7e6f4;
                color: #0f2235;
                font-weight: 700;
                border: 1px solid #b7c7d7;
                padding: 6px;
            }
            QListWidget {
                background: #f8fbff;
                color: #102132;
                border: 1px solid #b7c7d7;
                border-radius: 8px;
                selection-background-color: #b8dcff;
                selection-color: #081521;
                outline: 0;
            }
            QListWidget::item {
                border: 1px solid #d0deec;
                border-radius: 8px;
                margin: 5px;
                padding: 6px;
                background: #ffffff;
            }
            QListWidget::item:selected {
                border: 2px solid #2f80c9;
                background: #dff0ff;
            }
            QListWidget::indicator {
                width: 16px;
                height: 16px;
            }
            QListWidget::indicator:unchecked {
                border: 1px solid #486581;
                background: #ffffff;
            }
            QListWidget::indicator:checked {
                border: 1px solid #1d5f98;
                background: #2f80c9;
            }
            """
        )

        root = QVBoxLayout(self)
        lbl = QLabel(f"Patient ID: {self.patient_id}")
        root.addWidget(lbl)

        split = QHBoxLayout()
        root.addLayout(split, 1)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Study / Series", "Count"])
        self.tree.setMinimumWidth(360)
        self.tree.setAlternatingRowColors(True)
        self.tree.setIndentation(22)
        self.tree.setRootIsDecorated(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        split.addWidget(self.tree, 0)

        right = QVBoxLayout()
        split.addLayout(right, 1)

        self.preview = QListWidget(self)
        self.preview.setViewMode(QListWidget.IconMode)
        self.preview.setIconSize(QSize(128, 128))
        self.preview.setGridSize(QSize(164, 176))
        self.preview.setSpacing(8)
        self.preview.setUniformItemSizes(True)
        self.preview.setResizeMode(QListWidget.Adjust)
        self.preview.setSelectionMode(QListWidget.MultiSelection)
        right.addWidget(self.preview, 1)

        actions = QHBoxLayout()
        right.addLayout(actions)
        self.btn_load_preview = QPushButton("Load Preview")
        self.btn_select_all = QPushButton("Select All Visible")
        self.btn_clear_sel = QPushButton("Clear Selection")
        actions.addWidget(self.btn_load_preview)
        actions.addWidget(self.btn_select_all)
        actions.addWidget(self.btn_clear_sel)
        actions.addStretch(1)

        footer = QHBoxLayout()
        root.addLayout(footer)
        self.btn_attach = QPushButton("Attach Selected")
        self.btn_cancel = QPushButton("Cancel")
        footer.addStretch(1)
        footer.addWidget(self.btn_attach)
        footer.addWidget(self.btn_cancel)

        self.btn_load_preview.clicked.connect(self._load_preview_from_checked_series)
        self.btn_select_all.clicked.connect(self._select_all_visible)
        self.btn_clear_sel.clicked.connect(self.preview.clearSelection)
        self.btn_attach.clicked.connect(self._accept_selection)
        self.btn_cancel.clicked.connect(self.reject)

        self._populate_tree()

    def _populate_tree(self) -> None:
        self.tree.clear()
        for rec in self.records:
            study_uid = rec.get("study_uid") or ""
            study_desc = rec.get("study_description") or ""
            study_label = f"Study {study_uid}" if not study_desc else f"{study_desc} ({study_uid})"
            parent = QTreeWidgetItem([study_label, str(len(rec.get("series", [])))])
            parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
            parent.setCheckState(0, Qt.Unchecked)
            parent_font = parent.font(0)
            parent_font.setBold(True)
            parent.setFont(0, parent_font)
            parent.setData(0, Qt.UserRole, {"kind": "study", "study_uid": study_uid})

            for ser in rec.get("series", []):
                series_number = str(ser.get("series_number") or "?")
                series_desc = ser.get("series_description") or ""
                count = len(ser.get("images", []))
                txt = f"Series {series_number}" if not series_desc else f"Series {series_number}: {series_desc}"
                child = QTreeWidgetItem([txt, str(count)])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.Unchecked)
                child.setToolTip(0, txt)
                child.setData(
                    0,
                    Qt.UserRole,
                    {
                        "kind": "series",
                        "study_uid": study_uid,
                        "series_pk": ser.get("series_pk"),
                        "series_number": series_number,
                        "images": ser.get("images", []),
                    },
                )
                parent.addChild(child)
            self.tree.addTopLevelItem(parent)
        self.tree.expandAll()

    def _checked_series_images(self) -> list[str]:
        paths: list[str] = []
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                child = parent.child(j)
                if child.checkState(0) == Qt.Checked:
                    data = child.data(0, Qt.UserRole) or {}
                    if data.get("kind") == "series":
                        paths.extend(data.get("images", []))
        seen = set()
        uniq = []
        for p in paths:
            if p and p not in seen:
                seen.add(p)
                uniq.append(p)
        return uniq

    def _load_preview_from_checked_series(self) -> None:
        self.preview.clear()
        paths = self._checked_series_images()
        if not paths:
            themed_message_box(self, QMessageBox.Icon.Information, "No Series Selected", "Please check at least one series.")
            return

        max_preview = 300
        if len(paths) > max_preview:
            paths = paths[:max_preview]

        for p in paths:
            item = QListWidgetItem(os.path.basename(p) or p)
            item.setData(Qt.UserRole, p)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setToolTip(p)

            pix = self._build_preview_pixmap(p)
            if not pix.isNull():
                item.setIcon(QIcon(pix))
            self.preview.addItem(item)

        if self.preview.count() == 0:
            themed_message_box(self, QMessageBox.Icon.Warning, "No Preview", "No readable image could be previewed.")

    def _build_preview_pixmap(self, path: str) -> QPixmap:
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".dcm":
                import numpy as _np
                import pydicom
                from PIL import Image

                ds = pydicom.dcmread(path, force=True)
                arr = _np.asarray(ds.pixel_array)
                if arr.ndim > 2:
                    if arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
                        arr = _np.moveaxis(arr, 0, -1)
                    else:
                        arr = arr[..., 0]
                arr = arr.astype(_np.float32)
                lo, hi = float(_np.min(arr)), float(_np.max(arr))
                if hi <= lo:
                    hi = lo + 1.0
                arr = _np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
                arr8 = (arr * 255.0).astype(_np.uint8)

                pil = Image.fromarray(arr8)
                if pil.mode != "RGB":
                    pil = pil.convert("RGB")

                import io as _io

                bio = _io.BytesIO()
                pil.save(bio, format="PNG")
                qpix = QPixmap()
                qpix.loadFromData(bio.getvalue(), "PNG")
                return qpix.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)

            qpix = QPixmap(path)
            if qpix.isNull():
                return QPixmap()
            return qpix.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            return QPixmap()

    def _select_all_visible(self) -> None:
        for i in range(self.preview.count()):
            it = self.preview.item(i)
            it.setCheckState(Qt.Checked)

    def _accept_selection(self) -> None:
        out: list[str] = []
        for i in range(self.preview.count()):
            it = self.preview.item(i)
            if it.checkState() == Qt.Checked:
                p = it.data(Qt.UserRole)
                if p:
                    out.append(p)

        if not out:
            themed_message_box(self, QMessageBox.Icon.Information, "No Images Selected", "Please select at least one image.")
            return

        self.selected_paths = out
        self.accept()


class ModePickerPage(QWidget):
    chosen = Signal(str)  # "Chat" | "Report" | "Assist" | "ChatGPT"

    def __init__(self, parent=None, *, left_offset: int = 85, top_offset: int = 129, gap: int = 32):
        super().__init__(parent)

        self._api_checked = False
        self._api_retry_count = 0
        self._api_prompt_cancelled = False
        self._api_prompt_inflight = False

        self._left_px = int(left_offset)
        self._top_px  = int(top_offset)
        self._gap_px  = int(gap)

        self._left_ratio = None
        self._top_ratio  = None
        self._gap_ratio  = None

        self.setStyleSheet(f"""
            QWidget {{ background: transparent; }}
            QPushButton#modeBtn {{
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 12px;
                padding: 14px 16px;
                font-size: 18px;
                font-weight: 600;
                text-align: center;
                background-color: rgba(255,255,255,0.06);
            }}
            QPushButton#modeBtn:hover {{
                border-color: {CLR_ACCENT};
                background-color: rgba(255,255,255,0.10);
            }}
            QPushButton#modeBtn:disabled {{
                color: rgba(220,220,220,0.35);
                border-color: rgba(68,68,68,0.45);
                background-color: rgba(255,255,255,0.02);
            }}
        """)

        # ریشه: ستون چپ + فضای کشسان راست
        self._root = QHBoxLayout(self)
        self._root.setContentsMargins(self._left_px, 16, 16, 16)
        self._root.setSpacing(0)

        # ستون چپ
        self.left_wrap = QWidget(self)
        self.left_wrap.setFixedWidth(260)
        self.left = QVBoxLayout(self.left_wrap)
        self.left.setContentsMargins(8, 8, 8, 8)
        self.left.setSpacing(12)

        def mk_btn(text: str) -> QPushButton:
            b = QPushButton(text, self.left_wrap)
            b.setObjectName("modeBtn")
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(54)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda: self.chosen.emit(text))
            return b

        self.btn_chat   = mk_btn("Chat")
        self.btn_report = mk_btn("Report")
        self.btn_assist = mk_btn("Assist")
        self.btn_chatgpt = mk_btn("ChatGPT")

        # --- فاصله‌ها و ترتیب ---
        self.spacer_top = QWidget(self.left_wrap); self.spacer_top.setFixedHeight(self._top_px)
        self.gap_1 = QWidget(self.left_wrap); self.gap_1.setFixedHeight(self._gap_px)
        self.gap_2 = QWidget(self.left_wrap); self.gap_2.setFixedHeight(self._gap_px)
        self.gap_3 = QWidget(self.left_wrap); self.gap_3.setFixedHeight(self._gap_px)

        self.left.addWidget(self.spacer_top)
        self.left.addWidget(self.btn_chat)
        self.left.addWidget(self.gap_1)
        self.left.addWidget(self.btn_report)
        self.left.addWidget(self.gap_2)
        self.left.addWidget(self.btn_assist)
        self.left.addWidget(self.gap_3)
        self.left.addWidget(self.btn_chatgpt)
        self.left.addStretch(1)

        # راست: پیام قفل/راهنما
        right_spacer = QWidget(self)
        self._right_layout = QVBoxLayout(right_spacer)
        self._right_layout.setContentsMargins(0, 0, 0, 0)
        self._right_layout.addStretch(1)

        self._lock_lbl = QLabel(right_spacer)
        self._lock_lbl.setWordWrap(True)
        self._lock_lbl.setAlignment(Qt.AlignCenter)
        self._lock_lbl.setStyleSheet("""
            QLabel{
                color: rgba(230,230,230,0.85);
                padding: 18px;
                border: 1px dashed rgba(150,150,150,0.35);
                border-radius: 14px;
                background: rgba(255,255,255,0.03);
                font-size: 13px;
                line-height: 1.25;
            }
        """)
        self._lock_lbl.setVisible(False)
        self._right_layout.addWidget(self._lock_lbl, 0, Qt.AlignCenter)

        self._usage_lbl = QLabel(right_spacer)
        self._usage_lbl.setWordWrap(True)
        self._usage_lbl.setAlignment(Qt.AlignCenter)
        self._usage_lbl.setStyleSheet("""
            QLabel{
                color: rgba(220,220,220,0.90);
                padding: 16px;
                border: 1px solid rgba(150,150,150,0.25);
                border-radius: 12px;
                background: rgba(10,10,10,0.35);
                font-size: 12px;
                line-height: 1.35;
            }
        """)
        self._usage_lbl.setVisible(False)
        # Usage panel deliberately not added to layout — removed from UI.
        self._right_layout.addStretch(1)

        self._root.addWidget(self.left_wrap, 0, Qt.AlignTop | Qt.AlignLeft)
        self._root.addWidget(right_spacer, 1)

        # وضعیت اولیه: تا validate نشده، قفل
        self._apply_access_state()

    # امکان تغییر فاصله‌ی افقی از چپ در زمان اجرا (مانند قبل)
    def set_left_offset(self, px: int):
        self._left_px = max(0, int(px))
        m = self._root.contentsMargins()
        self._root.setContentsMargins(self._left_px, m.top(), m.right(), m.bottom())
        # اگر نسبت قبلاً محاسبه شده، آن را هم بروز کنیم تا ریسپانسیو بماند
        if self.width() > 0:
            self._left_ratio = self._left_px / float(self.width())

    # در اولین نمایش، نسبت‌ها را از اندازه‌های فعلی می‌گیریم
    def showEvent(self, e):
        super().showEvent(e)

        # هر بار نمایش: وضعیت دسترسی را سینک کن
        self._apply_access_state()
        self._refresh_usage_panel()

        if not self._api_checked:
            self._api_checked = True
            QTimer.singleShot(100, self._prompt_api_key)

        try:
            if self.width() > 0:
                self._left_ratio = self._left_px / float(self.width())
            if self.left_wrap.height() > 0:
                h = float(self.left_wrap.height())
                self._top_ratio = self.spacer_top.height() / h
                self._gap_ratio = self.gap_1.height() / h
        except Exception:
            pass


    def _set_modes_enabled(self, enabled: bool, *, tooltip: str = ""):
        """Enable/disable all mode buttons as a single access gate."""
        try:
            for b in getattr(self, "_mode_buttons", []) or []:
                b.setEnabled(bool(enabled))
                if tooltip:
                    b.setToolTip(tooltip)
        except Exception:
            pass

    def _hard_lock_api(self, reason: str):
        """
        Hard lock: triggered after Cancel or 3 invalid attempts.
        The user must restart the app to try again (as requested: NO access at all).
        """
        from PySide6.QtWidgets import QMessageBox, QApplication

        self._api_hard_locked = True
        self._api_prompt_cancelled = True  # keep the existing guard behavior
        self._set_modes_enabled(False, tooltip=reason)

        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Critical)
        mb.setWindowTitle("⛔ Access Blocked")
        mb.setText(
            "Because you cancelled the API key entry or entered an invalid API key 3 times, "
            "access to the application has been blocked.\n\n"
            "To try again, you must close the application and restart it."
        )
        btn_exit = mb.addButton("Exit Application", QMessageBox.DestructiveRole)
        mb.exec()

        if mb.clickedButton() == btn_exit:
            QApplication.instance().quit()


    def _on_mode_clicked(self, mode: str):
        """
        Single entry point for ALL mode buttons.
        If the API key is not validated -> do not navigate.
        If hard-locked -> do nothing except show an access denied message.
        """
        from PySide6.QtWidgets import QMessageBox
        from .api_manager import APIKeyManager

        # If already hard-locked (Cancel or 3 failed attempts), deny access
        if getattr(self, "_api_hard_locked", False) or getattr(self, "_api_prompt_cancelled", False):
            mb = QMessageBox(self)
            mb.setIcon(QMessageBox.Critical)
            mb.setWindowTitle("⛔ Access Denied")
            mb.setText("Access to AI features is blocked. Please restart the application.")
            mb.exec()
            return

    def _set_ai_enabled(self, enabled: bool, reason: str | None = None) -> None:
        """
        When enabled=False:
        - all AI modes are locked (disabled)
        - the lock reason message is shown
        """
        for btn in (self.btn_chat, self.btn_report, self.btn_assist, self.btn_chatgpt):
            try:
                btn.setEnabled(bool(enabled))
            except Exception:
                pass

        if enabled:
            self._lock_lbl.setVisible(False)
            self._lock_lbl.setText("")
        else:
            self._lock_lbl.setVisible(True)
            self._lock_lbl.setText(
                reason
                or "🔒 A valid API key is required to use AI features.\n"
                "Please go back to the login page and enter the correct key."
            )

    def _refresh_usage_panel(self, api_key: str | None = None) -> None:
        # Usage panel removed from UI — keep the method as a no-op so callers don't crash.
        return

        def _mask_key(k: str) -> str:
            k = (k or "").strip()
            if not k:
                return "-"
            if len(k) <= 10:
                return k[:2] + "..." + k[-2:]
            return k[:4] + "..." + k[-4:]

        key = (api_key or "").strip()
        if not key:
            try:
                from .api_manager import Manage
                key = (Manage.instance().get_irannobat_key() or "").strip()
            except Exception:
                try:
                    key = (Manage.instance().get_last_api_key() or "").strip()
                except Exception:
                    key = ""

        if not key:
            self._usage_lbl.setVisible(False)
            self._usage_lbl.setText("")
            return

        rows = []
        tr_models = {}
        try:
            from PacsClient.utils.database import (
                get_api_usage_rows_for_key,
                load_api_transcript_usage_for_key,
            )
            rows = get_api_usage_rows_for_key(key, limit=200) or []
            tr_models = load_api_transcript_usage_for_key(key) or {}
        except Exception:
            rows = []
            tr_models = {}

        api_mask = rows[0].get("api") if rows else _mask_key(key)
        last_model = rows[0].get("model") if rows else "-"
        last_used = rows[0].get("last_used_at") if rows else "-"
        total_tokens = sum(int(r.get("tokens") or 0) for r in rows)

        total_transcript_min = 0.0
        for _m, val in tr_models.items():
            try:
                total_transcript_min += float(val or 0.0)
            except Exception:
                pass

        if total_transcript_min < 0.1 and total_transcript_min > 0:
            transcript_text = f"{max(1, int(round(total_transcript_min * 60.0)))} sec"
        else:
            transcript_text = f"{total_transcript_min:.1f} min"

        if not rows and not tr_models:
            body = "No usage data found for this API key yet."
        else:
            body = (
                f"<b>API:</b> {api_mask}<br>"
                f"<b>Last model:</b> {last_model}<br>"
                f"<b>Total tokens:</b> {total_tokens:,}<br>"
                f"<b>Total transcript:</b> {transcript_text}<br>"
                f"<b>Last used:</b> {last_used}"
            )

        self._usage_lbl.setText(
            "<div style='font-size:12px;line-height:1.35'>"
            "<div style='font-size:13px;font-weight:700;margin:0 0 6px 0'>Usage</div>"
            f"{body}"
            "</div>"
        )
        self._usage_lbl.setVisible(True)


    def _apply_access_state(self) -> None:
        """
        Sync the UI state based on whether the API key is validated.
        """
        try:
            if is_active_backend_configured():
                self._set_ai_enabled(True)
            else:
                # If previously cancelled/locked, keep the existing lock message (if any)
                if getattr(self, "_api_prompt_cancelled", False):
                    self._set_ai_enabled(False, self._lock_lbl.text() or None)
                else:
                    self._set_ai_enabled(False, "🔑 Please enter a valid API key to enable AI features.")
        except Exception:
            self._set_ai_enabled(False, "🔒 Unable to verify the API key status. Please try again.")


    def _apply_access_state(self) -> None:
        """
        Sync the UI access state based on whether the API key is validated.
        """
        try:
            if is_active_backend_configured():
                self._set_ai_enabled(True)
            else:
                # If previously cancelled/locked, keep the existing lock message (if any)
                if getattr(self, "_api_prompt_cancelled", False):
                    self._set_ai_enabled(False, self._lock_lbl.text() or None)
                else:
                    self._set_ai_enabled(False, "🔑 Please enter a valid API key to enable AI features.")
        except Exception:
            self._set_ai_enabled(False, "🔒 Unable to verify the API key status. Please try again.")


    def _prompt_api_key(self):
        """Resolve API key only from Settings (no extra login prompt)."""
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QTimer
        from .api_manager import APIKeyManager

        # --- anti-loop / anti re-entry guards ---
        if getattr(self, "_api_prompt_cancelled", False):
            return
        if getattr(self, "_api_prompt_inflight", False):
            return
        self._api_prompt_inflight = True

        try:
            backend, center_name, api_key = _resolve_active_ai_identity()
            if backend == "openai":
                if api_key:
                    self._set_ai_enabled(True)
                    self._show_welcome(center_name or "OpenAI", api_key=api_key)
                    self._refresh_usage_panel(api_key=api_key)
                else:
                    self._set_ai_enabled(False, "Please set your OpenAI API key in Settings -> EchoMind.")
                return

            manager = APIKeyManager.instance()

            # If already validated: unlock UI and show welcome
            if manager.is_validated():
                self._set_ai_enabled(True)
                center = manager.get_current_center()
                api_key = None
                try:
                    for attr in (
                        "get_current_key", "get_current_api_key", "current_key",
                        "api_key", "_current_key", "_api_key"
                    ):
                        if hasattr(manager, attr):
                            v = getattr(manager, attr)
                            api_key = v() if callable(v) else v
                            if api_key:
                                break
                except Exception:
                    api_key = None

                self._show_welcome(center, api_key=api_key)
                self._refresh_usage_panel(api_key=api_key)
                return

            # No stored validation yet: try to load from modules.EchoMind Settings (single source of truth)
            saved_key = ""
            try:
                from modules.EchoMind.settings_store import get_echomind_api_key
                saved_key = (get_echomind_api_key() or "").strip()
            except Exception:
                saved_key = ""

            if saved_key:
                success, center, error = manager.validate_key(saved_key)
                if success:
                    self._api_retry_count = 0
                    self._api_prompt_cancelled = False
                    self._set_ai_enabled(True)
                    self._show_welcome(center, api_key=saved_key)
                    self._refresh_usage_panel(api_key=saved_key)
                    return

                # If saved key is invalid, block AI and ask user to fix in Settings
                self._api_prompt_cancelled = True
                self._set_ai_enabled(
                    False,
                    "🔒 The saved API key is invalid. Please update it in Settings → modules.EchoMind."
                )
                if error:
                    mb = QMessageBox(self)
                    mb.setIcon(QMessageBox.Critical)
                    mb.setWindowTitle("❌ Invalid API Key")
                    mb.setText(
                        f"{error}\n\n"
                        "Please open Settings → EchoMind and update your API key."
                    )
                    mb.exec()
                return

            # No saved key: keep UI locked and ask user to configure Settings
            self._set_ai_enabled(False, "🔑 Please set your API key in Settings → modules.EchoMind.")

        finally:
            self._api_prompt_inflight = False

    def _show_welcome(self, center: str, api_key: t.Optional[str] = None):
        from PySide6.QtWidgets import QMessageBox

        usage_html = "<i>No usage data available.</i>"
        real_api_key = None

        try:
            from .api_manager import Manage
            m = Manage.instance()
            if api_key and isinstance(api_key, str) and api_key.strip():
                real_api_key = api_key.strip()
            else:
                real_api_key = (m.get_irannobat_key() or "").strip()
        except Exception:
            try:
                real_api_key = Manage.instance().get_last_api_key()
            except Exception:
                real_api_key = None

        if real_api_key:
            try:
                from PacsClient.utils.database import get_api_usage_summary_html
                usage_html = get_api_usage_summary_html(real_api_key)
            except Exception as e:
                usage_html = f"<i>Error loading usage summary: {str(e)}</i>"
        else:
            usage_html = "<i>API key is not available for usage lookup.</i>"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("✅ API Key Validated - AIPacs")

        msg.setText(
            f"<div style='font-size:12px;line-height:1.25'>"
            f"<div style='font-size:14px;font-weight:700;margin:0 0 4px 0'>"
            f"Welcome to {center} Center"
            f"</div>"
            f"<div style='color:#bbb;margin:0 0 8px 0'>API key validated. AI features are enabled.</div>"

            f"<div style='font-weight:700;margin:0 0 4px 0'>Usage Summary</div>"
            f"{usage_html}"

            f"<div style='color:#aaa;margin-top:6px'>"

            f"<hr>"
            f"<div><b>Enabled features:</b></div>"
            f"<ul style='margin:6px 0 0 18px'>"
            f"<li>💬 Chat</li>"
            f"<li>📄 Report Generation</li>"
            f"<li>🤖 Assistant</li>"
            f"<li>🔍 Search</li>"
            f"<li>🌟 ChatGPT</li>"
            f"</ul>"
            )

        msg.setStandardButtons(QMessageBox.Ok)
        msg.exec()


    def resizeEvent(self, e):
        super().resizeEvent(e)
        lw_h = max(1, self.left_wrap.height())

        # اگر نسبت‌ها هنوز محاسبه نشده‌اند، از مقادیر پیکسلی اولیه استفاده کن
        top_h = int((self._top_ratio or (self._top_px / lw_h)) * lw_h)
        gap_h = int((self._gap_ratio or (self._gap_px / lw_h)) * lw_h)
        left_m = int((self._left_ratio or (self._left_px / max(1, self.width()))) * max(1, self.width()))

        self.spacer_top.setFixedHeight(top_h)
        self.gap_1.setFixedHeight(gap_h)
        self.gap_2.setFixedHeight(gap_h)

        m = self._root.contentsMargins()
        self._root.setContentsMargins(left_m, m.top(), m.right(), m.bottom())

class OneChatPage(QWidget):
    """
    Locked-to-mode page:
      page_mode in {"Chat","Report","Assist"}
      - Chat: send => Chat
      - Report: send => Report
      - Assist: send => small menu [Assist | Search]
    """

    # ✅ سیگنال درست در سطح کلاس
    backRequested = Signal()

    def __init__(self, study_uid: str = None, page_mode: str = "Chat"):
        super().__init__()
        if not hasattr(OneChatPage, "last_selected_modality"):
            OneChatPage.last_selected_modality = None
        self.controller = ChatController(ChatApiClient())
        self._bubble_origin_hint = None
        self.study_uid = study_uid
        pm = (page_mode or "Chat").strip()
        pm_l = pm.lower()
        if pm_l == "chatgpt" or pm_l == "chat-gpt" or pm_l == "chat_gpt":
            pm = "ChatGPT"
        elif pm_l == "chat":
            pm = "Chat"
        elif pm_l == "report":
            pm = "Report"
        elif pm_l in ("assist", "assistant"):
            pm = "Assist"
        elif pm_l == "search":
            pm = "Search"
        else:
            # keep as-is (preserve casing), but normalize first letter
            pm = pm[:1].upper() + pm[1:]
        self.page_mode = pm

        # --- runtime state ---
        self._busy_count = 0  # ← برای قفل/آنلاک دکمه‌ها در _run_async
        self._workers = []  # ← لیست نخ‌های فعال
        self.sessions = {}  # sid -> [(who, html)]
        self.current_session_id = None

        # --- namespace per page (to isolate sessions per page) ---
        # هر صفحه سشن‌های خودش را خواهد داشت: chat-*, report-*, assist-*
        self.ns = self.page_mode.lower()  # "chat" | "report" | "assist"

        # ----- LEFT -----
        self.left = QVBoxLayout()
        self.btn_back = QPushButton(" ← Back")
        self.btn_back.setCursor(Qt.PointingHandCursor)
        self.btn_back.setStyleSheet(
            "QPushButton{"
            f"background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(236,243,252,0.14),stop:1 rgba(183,196,214,0.08));"
            f"color:{CLR_TEXT};"
            "border:1px solid rgba(143,152,164,0.45);"
            "border-radius:12px;padding:10px 14px;margin:6px;font-weight:600;}"
            "QPushButton:hover{border-color:rgba(114,190,255,0.95);background:rgba(99,179,237,0.20);}"
            "QPushButton:pressed{background:rgba(99,179,237,0.30);}"
        )

        self.btn_new = QPushButton()
        _set_icon(self.btn_new, "newchat.png", 18, "New Chat")
        self.btn_new.setText(" New Chat")
        self.btn_new.setCursor(Qt.PointingHandCursor)
        self.btn_new.setStyleSheet(
            "QPushButton{"
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(46,139,87,0.65),stop:1 rgba(36,121,162,0.62));"
            "color:#ffffff;"
            "border:1px solid rgba(140,208,228,0.65);"
            "border-radius:12px;padding:10px 14px;margin:6px;font-weight:700;}"
            "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(52,158,99,0.78),stop:1 rgba(42,137,184,0.74));}"
            "QPushButton:pressed{background:rgba(38,126,167,0.82);}"
        )

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget{"
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 rgba(31,35,42,0.95),stop:1 rgba(24,27,33,0.95));"
            f"color:{CLR_TEXT};"
            "border:1px solid rgba(143,152,164,0.34);"
            "border-radius:12px;margin:6px;padding:4px;}"
            "QListWidget::item{padding:11px 10px;border-bottom:1px solid rgba(255,255,255,0.08);border-radius:8px;}"
            "QListWidget::item:hover{background:rgba(99,179,237,0.16);}"
            "QListWidget::item:selected{background:rgba(99,179,237,0.24);color:#ffffff;border:1px solid rgba(114,190,255,0.85);}"
            f"{PATIENT_SCROLLBAR_QSS}"
        )
        self.left.addWidget(self.btn_back)
        self.left.addWidget(self.btn_new)
        self.left.addWidget(self.list, 1)

        left_wrap = QWidget(); left_wrap.setLayout(self.left)
        left_wrap.setFixedWidth(260)
        left_wrap.setStyleSheet(
            "background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(33,37,44,0.98),stop:1 rgba(22,25,31,0.98));"
            "border-right:1px solid rgba(143,152,164,0.35);"
        )

        # ----- RIGHT -----
        self.history = ChatHistory()
        ph = {
            "Chat":   "Write your message…",
            "Report": "Write/paste report text",
            "Assist": "Write clinical text to analyze or search…",
        }.get(self.page_mode, "Write your message…")

        self.composer = UnifiedComposer(ph)

        self.composer.sendClicked.connect(self._on_send_clicked)
        self.composer.transcribeRequested.connect(self._transcribe_now)
        self.composer.recordingStarted.connect(self._prefetch_reception)
        self.composer.standardizeClicked.connect(self._standardize_now)
        self.composer.apply_side_padding(16, 16)

        # Route attach button to source-selection flow (system/current patient/other patient).
        try:
            self.composer.btn_plus.clicked.disconnect()
        except Exception:
            pass
        self.composer.btn_plus.clicked.connect(self._on_attach_plus_clicked)

        self.composer.btn_modality.clicked.connect(self._show_modality_menu)

        right = QVBoxLayout(); right.setContentsMargins(0,0,0,10); right.setSpacing(0)
        right.addWidget(self.history, 1); right.addWidget(self.composer, 0)
        right_wrap = QWidget(); right_wrap.setLayout(right)
        right_wrap.setStyleSheet(f"background:{CLR_BG};")

        # 2026-08-08: per-chat case metadata as the FIRST CARD INSIDE the chat.
        # NOT a sidebar. Case metadata is conversation context, so it belongs in the
        # conversation: in the scroll area with the other cards, scrolling with them,
        # wearing their visual language, and taking no permanent horizontal space
        # away from the report. ChatHistory pins it at index 0 and keeps it across
        # clear(), so every re-render path preserves it without knowing it exists.
        try:
            from .metadata_panel import CaseMetadataCard
            self.meta_card = CaseMetadataCard(self.history.container)
            self.history.set_lead_widget(self.meta_card)
        except Exception as _mc_exc:
            self.meta_card = None
            _log.warning("[EchoMind-meta] metadata card unavailable: %s", _mc_exc)

        root = QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(left_wrap, 0); root.addWidget(right_wrap, 1)

        # متغیر کلاسی برای نگهداری مودالیتی انتخاب شده (persistent در سطح کلاس)
        if not hasattr(OneChatPage, "last_selected_modality"):
            OneChatPage.last_selected_modality = None
            
        # نمایش دکمه مودالیتی فقط در حالت Report
        self.composer.btn_modality.setVisible(self.page_mode in ["Report", "ChatGPT"])
        # تنظیم مودالیتی ذخیره شده
        if OneChatPage.last_selected_modality:
            self._set_modality_text(OneChatPage.last_selected_modality)
        
        try:
            self.composer.btn_all_modality_hq.setVisible(self.page_mode in ["Report", "ChatGPT"])
            self.composer.btn_all_modality_hq.clicked.connect(self._on_hq_all_modality_clicked)
        except Exception:
            pass        
        # اتصال سیگنال جدید
        self.composer.modalitySelected.connect(self._on_modality_selected)
        
        try:
            self.composer.install_attachment_overlay(self.history.scroll.viewport())
            self.history.scroll.viewport().installEventFilter(self)
        except Exception:
            pass
        
        self._current_modality = OneChatPage.last_selected_modality

        self.controller.messageReady.connect(self._append_bubble)
        self.controller.sessionChanged.connect(self._on_session_changed)
        self.btn_new.clicked.connect(self._new_chat)
        self.list.itemClicked.connect(self._open_session)
        self._pending_retry: dict | None = None  # {'mode': str, 'text': str, 'bubble': MessageBubble|None}

        # ✅ اتصال صحیح دکمه Back
        self.btn_back.clicked.connect(self.backRequested.emit)

        # === DB bootstrap ===
        U.ai_ensure_schema()
        self._loaded_any = self._load_from_db_and_render()
        if not self._loaded_any:
            welcome = {
                "Chat":   "Ready. Type and press Send to Chat.",
                "Report": "Ready. Paste report text then Send to generate Report.",
                "Assist": "Ready. Type and press Send. Use the dropdown to run Assist or Search.",
            }.get(self.page_mode, "Ready.")
            self.controller.bubble("AI ChatBot", welcome)
    # --- new: handle send depending on locked page_mode ---

    # ====== OneChatPage: helpers for AI-Chat persistence ======
    def _open_report_modality_menu(self, text: str):
        """Show dropdown for selecting modality before sending report."""
        menu = QMenu(self)
        modalities = list(REPORT_MODALITIES)   # ONE list — ai_chat_config
        for mod in modalities:
            act = QAction(mod, menu)
            act.triggered.connect(
                lambda checked, m=mod, t=text: self._send_with_mode(t, "Report", modality=m)
            )
            menu.addAction(act)
        # Position menu under the Send button
        btn = self.composer.btn_send
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _on_attach_plus_clicked(self) -> None:
        """Attach flow with source selection and patient-series image picking."""
        current_patient_id = self._get_current_patient_id()
        dlg = _ImageSourceDialog(self, current_patient_id=current_patient_id)
        if dlg.exec() != QDialog.Accepted:
            return

        source = dlg.selected_source
        if source == "local":
            # Preserve legacy local attach behavior (audio/image from system).
            self.composer._choose_file()
            return

        if source == "current":
            if not current_patient_id:
                themed_message_box(self, QMessageBox.Icon.Warning, "Patient Not Found", "Current patient id is not available.")
                return
            patient_id = current_patient_id
        else:
            patient_id, ok = themed_input_text(
                self,
                "Other Patient",
                "Enter patient id:",
                "",
                QLineEdit.Normal,
            )
            if not ok:
                return
            patient_id = (patient_id or "").strip()
            if not patient_id:
                themed_message_box(self, QMessageBox.Icon.Warning, "Invalid Patient ID", "Patient id cannot be empty.")
                return

        records = self._fetch_patient_image_records(patient_id)
        if not records:
            themed_message_box(self, QMessageBox.Icon.Information, "No Images", f"No image series found for patient id: {patient_id}")
            return

        picker = _PatientSeriesImagePickerDialog(self, patient_id=patient_id, records=records)
        if picker.exec() != QDialog.Accepted:
            return

        selected_paths = picker.selected_paths or []
        if not selected_paths:
            return

        png_paths = self._convert_selected_images_to_png(selected_paths)
        if not png_paths:
            themed_message_box(self, QMessageBox.Icon.Warning, "Attach Failed", "No image could be converted and attached.")
            return

        for p in png_paths:
            try:
                self.composer.add_image_attachment(p)
            except Exception:
                pass

        self.controller.bubble(
            "AI ChatBot",
            f"Attached {len(png_paths)} image(s) from patient source.",
        )

    def _get_current_patient_id(self) -> str | None:
        if not self.study_uid:
            return None
        try:
            from PacsClient.utils import db_manager as db

            st = db.get_study_by_study_uid(self.study_uid)
            if not st:
                return None
            patient_fk = st.get("patient_fk")
            if not patient_fk:
                return None
            p = db.get_patient_by_patient_pk(patient_fk)
            if not p:
                return None
            return (p.get("patient_id") or "").strip() or None
        except Exception:
            return None

    def _fetch_patient_image_records(self, patient_id: str) -> list[dict]:
        """Return study/series/image paths for a patient id."""
        patient_id = (patient_id or "").strip()
        if not patient_id:
            return []

        rows: list[tuple] = []
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT st.study_uid, st.study_description
                    FROM studies AS st
                    JOIN patients AS p ON p.patient_pk = st.patient_fk
                    WHERE p.patient_id = ?
                    ORDER BY st.study_date DESC, st.study_time DESC
                    """,
                    (patient_id,),
                )
                rows = cur.fetchall() or []
        except Exception:
            return []

        try:
            from PacsClient.utils import db_manager as db
        except Exception:
            return []

        out: list[dict] = []
        for study_uid, study_description in rows:
            series_items = []
            series_rows = db.get_series_by_study_uid(study_uid) or []
            for se in series_rows:
                series_pk = se.get("series_pk")
                if not series_pk:
                    continue

                img_paths = []
                try:
                    with get_db_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            """
                            SELECT instance_path
                            FROM instances
                            WHERE series_fk = ?
                            ORDER BY instance_number, instance_pk
                            """,
                            (series_pk,),
                        )
                        for (p,) in (cur.fetchall() or []):
                            if p and os.path.exists(p):
                                img_paths.append(p)
                except Exception:
                    continue

                if not img_paths:
                    continue

                series_items.append(
                    {
                        "series_pk": series_pk,
                        "series_number": se.get("series_number") or "",
                        "series_description": se.get("series_description") or "",
                        "images": img_paths,
                    }
                )

            if series_items:
                out.append(
                    {
                        "study_uid": study_uid,
                        "study_description": study_description or "",
                        "series": series_items,
                    }
                )
        return out

    def _convert_selected_images_to_png(self, paths: list[str]) -> list[str]:
        """Convert selected images to PNG and return output paths."""
        if not paths:
            return []

        out_dir = os.path.join(self._ai_chat_dir(), "attached_png")
        os.makedirs(out_dir, exist_ok=True)

        progress = QProgressDialog("Converting selected images to PNG...", "Cancel", 0, len(paths), self)
        progress.setWindowTitle("Image Conversion")
        progress.setMinimumDuration(0)
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)
        progress.setStyleSheet(
            """
            QProgressDialog { background-color: #2b2f33; color: #f0f3f6; }
            QProgressBar {
                border: 1px solid #1f2226;
                border-radius: 6px;
                background: #1b1f24;
                color: #f0f3f6;
                text-align: center;
                min-height: 18px;
            }
            QProgressBar::chunk {
                background-color: #4a90e2;
                border-radius: 6px;
            }
            QPushButton {
                background-color: #3a4148;
                color: #f7f9fb;
                border: 1px solid #1f2226;
                border-radius: 6px;
                padding: 5px 12px;
            }
            """
        )

        ok_paths: list[str] = []
        for idx, src in enumerate(paths, start=1):
            if progress.wasCanceled():
                break
            png = self._convert_image_to_png(src, out_dir)
            if png:
                ok_paths.append(png)
            progress.setValue(idx)
            QGuiApplication.processEvents()

        progress.close()
        return ok_paths

    def _convert_image_to_png(self, src_path: str, out_dir: str) -> str | None:
        """Convert a single image (including DICOM) to PNG path."""
        try:
            ext = os.path.splitext(src_path)[1].lower()
            src_norm = os.path.normpath(src_path)
            base_hash = hashlib.sha1(src_norm.encode("utf-8", errors="ignore")).hexdigest()[:16]
            out_path = os.path.join(out_dir, f"img_{base_hash}.png")
            if os.path.exists(out_path):
                return out_path

            if ext == ".dcm":
                import numpy as _np
                import pydicom
                from PIL import Image

                ds = pydicom.dcmread(src_path, force=True)
                arr = _np.asarray(ds.pixel_array)

                if arr.ndim > 2:
                    if arr.shape[0] in (3, 4) and arr.shape[-1] not in (3, 4):
                        arr = _np.moveaxis(arr, 0, -1)
                    else:
                        arr = arr[..., 0]

                arr = arr.astype(_np.float32)
                slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
                intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
                arr = arr * slope + intercept

                lo = float(_np.percentile(arr, 1))
                hi = float(_np.percentile(arr, 99))
                if hi <= lo:
                    lo = float(_np.min(arr))
                    hi = float(_np.max(arr))
                if hi <= lo:
                    hi = lo + 1.0

                arr = _np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
                arr8 = (arr * 255.0).astype(_np.uint8)
                pil = Image.fromarray(arr8)
                if pil.mode != "RGB":
                    pil = pil.convert("RGB")
                pil.save(out_path, format="PNG")
                return out_path

            from PIL import Image

            with Image.open(src_path) as im:
                if im.mode != "RGB":
                    im = im.convert("RGB")
                im.save(out_path, format="PNG")
            return out_path
        except Exception:
            return None

    def _read_json_file(self, path: str) -> dict:
        """خواندن امن JSON؛ در خطا خروجی خالی می‌دهد."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                import json
                return json.load(f) or {}
        except Exception:
            return {}

    def eventFilter(self, obj, ev):
        """Keep the floating attachment bar pinned to the bottom of the chat viewport."""
        try:
            vp = getattr(getattr(self, "history", None), "scroll", None)
            vp = vp.viewport() if vp is not None else None
            if vp is not None and obj is vp:
                if ev.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
                    QTimer.singleShot(0, self.composer._reposition_attachment_overlay)
        except Exception:
            pass
        return super().eventFilter(obj, ev)


    def _load_saved_ai_chat_texts(self, sid: str):
        """
        اگر فایل‌های <AI-Chat>/<sid>-standard.json و/یا <sid>-transcribe.json وجود داشته باشند،
        محتوا را داخل تب‌های مربوطه می‌ریزد و تب مناسب را انتخاب می‌کند.

        Fix:
        - Load BOTH standard languages (text_en/text_fa) if available.
        - Legacy fallback: if only "text" exists, detect FA vs EN and place into correct buffer.
        """
        import os, re
        if not sid:
            return

        def _looks_persian(s: str) -> bool:
            s = s or ""
            # Arabic/Persian blocks
            return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", s))

        base = self._ai_chat_dir()
        std_file = os.path.join(base, f"{sid}-standard.json")
        tr_file  = os.path.join(base, f"{sid}-transcribe.json")
        tpl_file = os.path.join(base, f"{sid}-normal_template.json")

        std_data = {}
        std_txt = ""
        tr_txt  = ""
        tpl_txt = ""

        if os.path.exists(std_file):
            std_data = self._read_json_file(std_file) or {}
            std_txt = (std_data.get("text") or "").strip()

        if os.path.exists(tr_file):
            tr_data = self._read_json_file(tr_file) or {}
            tr_txt = (tr_data.get("text") or "").strip()

        if os.path.exists(tpl_file):
            tpl_data = self._read_json_file(tpl_file) or {}
            tpl_txt = (tpl_data.get("text") or "").strip()

        # ---------- Standard: load both langs ----------
        en_std = (std_data.get("text_en") or "").strip()
        fa_std = (std_data.get("text_fa") or "").strip()

        # Legacy fallback: only "text" existed (old files)
        if not en_std and not fa_std and std_txt:
            if _looks_persian(std_txt):
                fa_std = std_txt
            else:
                en_std = std_txt

        if en_std or fa_std:
            self.composer.install_lang_buttons()
            self.composer.set_standard_result(
                en_text=(en_std or None),
                fa_text=(fa_std or None),
            )
        else:
            self.composer.set_tab_text("standard", "")

        # Transcribe tab
        self.composer.set_tab_text("transcribe", tr_txt or "")

        # Normal Template tab
        self.composer.set_tab_text("normal_template", tpl_txt or "")

        if en_std or fa_std:
            self.composer.switch_tab("standard")
        elif tr_txt:
            self.composer.switch_tab("transcribe")
        elif tpl_txt:
            self.composer.switch_tab("normal_template")

        # cursor to end
        c = self.composer.box.textCursor()
        c.movePosition(QTextCursor.End)
        self.composer.box.setTextCursor(c)

        def _extract_display_text(raw_output, lang: str) -> str:
            """
            Minimal extractor (same spirit as _standardize_now) for disk-loaded raw/parsed.
            lang: 'en' or 'fa'
            """
            obj = _try_json(raw_output)

            if isinstance(obj, str):
                return obj.strip()

            if isinstance(obj, list):
                parts = [str(x).strip() for x in obj if str(x).strip()]
                return "\n".join(parts).strip()

            if isinstance(obj, dict):
                # nested "english"/"persian"
                if lang == "en" and "english" in obj:
                    return _extract_display_text(obj["english"], "en")
                if lang == "fa" and "persian" in obj:
                    return _extract_display_text(obj["persian"], "fa")

                # language-specific finals
                en_keys = ("final_report_english", "final_report_en", "report_english", "standard_report_english")
                fa_keys = ("final_report_persian", "final_report_fa", "final_report_pa", "report_persian", "standard_report_persian")

                for k in (en_keys if lang == "en" else fa_keys):
                    v = obj.get(k, None)
                    if isinstance(v, str) and v.strip():
                        return v.replace("\\n", "\n").strip()

                # final_report could be dict with langs
                final = obj.get("final_report", None)
                if isinstance(final, dict):
                    cand = None
                    if lang == "en":
                        cand = final.get("english") or final.get("en")
                    else:
                        cand = final.get("persian") or final.get("fa") or final.get("pa")
                    if isinstance(cand, str) and cand.strip():
                        return cand.replace("\\n", "\n").strip()

                # cleaned sentences
                arr = obj.get("cleaned_sentences_english" if lang == "en" else "cleaned_sentences_persian", None)
                if isinstance(arr, list):
                    parts = [str(x).strip() for x in arr if str(x).strip()]
                    base = "\n".join(parts).strip()
                    if base:
                        return base

                # last: generic final_report string
                if isinstance(final, str) and final.strip():
                    return final.replace("\\n", "\n").strip()

            return ""

        base = self._ai_chat_dir()
        std_file = os.path.join(base, f"{sid}-standard.json")
        tr_file  = os.path.join(base, f"{sid}-transcribe.json")
        tpl_file = os.path.join(base, f"{sid}-normal_template.json")

        std_txt = ""
        tr_txt  = ""
        tpl_txt = ""

        std_data = {}
        if os.path.exists(std_file):
            std_data = self._read_json_file(std_file) or {}
            std_txt = (std_data.get("text") or "").strip()

        if os.path.exists(tr_file):
            tr_data = self._read_json_file(tr_file) or {}
            tr_txt = (tr_data.get("text") or "").strip()

        if os.path.exists(tpl_file):
            tpl_data = self._read_json_file(tpl_file) or {}
            tpl_txt = (tpl_data.get("text") or "").strip()

        # ---------- Standard: load both langs ----------
        en_std = (std_data.get("text_en") or "").strip()
        fa_std = (std_data.get("text_fa") or "").strip()

        # If not present, try reconstruct from parsed/raw
        if not en_std and not fa_std and std_data:
            parsed = std_data.get("parsed", None)
            raw_s = std_data.get("raw_standardize_output", None)

            # 1) parsed preferred (already dict)
            if isinstance(parsed, dict):
                en_raw = parsed.get("english") or parsed.get("en")
                fa_raw = parsed.get("persian") or parsed.get("fa") or parsed.get("pa")
                en_std = _extract_display_text(en_raw, "en").strip()
                fa_std = _extract_display_text(fa_raw, "fa").strip()

            # 2) raw string next (json-dumps({"en":..., "fa":...}))
            if (not en_std and not fa_std) and isinstance(raw_s, str) and raw_s.strip():
                try:
                    raw_obj = json.loads(_strip_fences(raw_s))
                except Exception:
                    raw_obj = None
                if isinstance(raw_obj, dict):
                    en_std = _extract_display_text(raw_obj.get("en"), "en").strip()
                    fa_std = _extract_display_text(raw_obj.get("fa"), "fa").strip()

        # Legacy fallback: only "text" existed
        if not en_std and not fa_std and std_txt:
            if _looks_persian(std_txt):
                fa_std = std_txt
            else:
                en_std = std_txt

        # Apply to composer
        if en_std or fa_std:
            self.composer.install_lang_buttons()
            self.composer.set_standard_result(en_text=(en_std or None), fa_text=(fa_std or None))
        else:
            self.composer.set_tab_text("standard", "")

        # ---------- Transcribe ----------
        self.composer.set_tab_text("transcribe", tr_txt or "")

        # ---------- Normal Template ----------
        self.composer.set_tab_text("normal_template", tpl_txt or "")

        # Select best tab
        if en_std or fa_std:
            self.composer.switch_tab("standard")
        elif tr_txt:
            self.composer.switch_tab("transcribe")
        elif tpl_txt:
            self.composer.switch_tab("normal_template")

        # cursor end
        c = self.composer.box.textCursor()
        c.movePosition(QTextCursor.End)
        self.composer.box.setTextCursor(c)


    def _show_modality_menu(self):
        """Open the modality dropdown.

        Allowed in:
        - Report pages (page_mode == "Report")
        - ChatGPT page only when ChatGPT sub-mode == "report" (page_mode == "ChatGPT")
        """
        allow = False
        try:
            if str(getattr(self, "page_mode", "")).lower() == "report":
                allow = True
            elif str(getattr(self, "page_mode", "")).lower() == "chatgpt" and getattr(self, "_chatgpt_mode", None) == "report":
                allow = True
        except Exception:
            allow = False

        if not allow:
            return

        menu = QMenu(self)
        # Match the style/appearance used in other dropdowns (e.g., Report quality menu)
        try:
            menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 16px;
                color: #ddd;
                background-color: transparent;
                border-radius: 4px;
                margin: 2px;
            }
            QMenu::item:selected {
                background-color: #3a3a3a;
                color: #fff;
            }
            QMenu::item:hover {
                background-color: #4a4a4a;
            }
        """)
        except Exception:
            pass

        current_mod = getattr(self, "_current_modality", None)
        for mod in REPORT_MODALITIES:   # ONE list — ai_chat_config
            act = QAction(mod, menu)
            act.setCheckable(True)
            if mod == current_mod:
                act.setChecked(True)
            act.triggered.connect(lambda checked, m=mod: self._select_modality(m))
            menu.addAction(act)

        # Use the same popup behavior everywhere (Report + ChatGPT) for identical UX
        try:
            anchor = self.composer.btn_modality
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            try:
                menu.exec(QCursor.pos())
            except Exception:
                pass


    def _is_network_or_server_down(self, raw: str) -> bool:
        s = (raw or "").lower()
        markers = [
            "httpconnectionpool", "httpsconnectionpool",
            "max retries exceeded",
            "failed to establish a new connection",
            "connection refused", "winerror 10061",
            "a socket operation was attempted to an unreachable host", "winerror 10065",
            "timed out", "timeout", "connecttimeout", "readtimeout",
            "name resolution error", "failed to resolve", "getaddrinfo failed", "errno 11001",
            "temporary failure in name resolution",
            "bad gateway", "service unavailable", "gateway time-out",
            "502", "503", "504",
        ]
        return any(m in s for m in markers)

    def _scrub_sensitive_net_info(self, raw: str) -> str:
        import re
        s = raw or ""
        # hide full URLs
        s = re.sub(r"(?i)https?://[^\s'\"<>]+", "<URL>", s)
        # hide host/port patterns from urllib3
        s = re.sub(r"host='[^']+'", "host='<hidden>'", s)
        s = re.sub(r"port=\d+", "port=<hidden>", s)
        # hide endpoint in "with url: /xxx"
        s = re.sub(r"with url:\s*/[^\s)]+", "with url:<hidden>", s)
        # hide naked IPs if any appear
        s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "<IP>", s)
        return s

    def _safe_user_error(self, raw: str) -> str:
        if self._is_network_or_server_down(raw):
            return "❌ Connection failed. Please check your internet connection or contact support."
        return self._scrub_sensitive_net_info(raw)

    def _refresh_correction_reports_dropdown(self):
        """
        پر کردن dropdown ریپورت‌های Correction برای سشن فعلی،
        بدون نیاز به ترک چت / تعویض سشن.
        """
        sid = getattr(self, "current_session_id", None) or getattr(self.controller, "session_id", None)
        if not sid:
            return

        # preserve current selection if any
        try:
            prev = (self.composer.get_selected_correction_report_text() or "").strip()
        except Exception:
            prev = ""

        report_items: list[tuple[str, str | None]] = []

        # 1) Prefer ai_reports
        try:
            fn = getattr(U, "ai_fetch_reports_for_session", None)
            if callable(fn):
                for _, msg_id, label, raw_en, _ in (fn(sid) or []):
                    if isinstance(raw_en, str) and raw_en.strip():
                        report_items.append((raw_en, label if isinstance(label, str) else None))
        except Exception:
            pass

        # 2) Fallback: derive from report bubbles in ai_messages (old sessions)
        if not report_items:
            try:
                rows = U.ai_fetch_messages_full(sid) or []
            except Exception:
                rows = []

            try:
                insert_fn = getattr(U, "ai_insert_report", None)
            except Exception:
                insert_fn = None

            n = 0
            for msg_id, who, html, origin in (rows or []):
                if origin != "report":
                    continue
                if not isinstance(html, str) or not html.strip():
                    continue

                n += 1
                raw = html.strip()

                try:
                    plain = self._html_to_plain_text(raw) if raw else ""
                    first_line = next((ln.strip() for ln in (plain or "").splitlines() if ln.strip()), "")
                    label = (first_line[:80] if first_line else f"Report {n}")
                except Exception:
                    label = f"Report {n}"

                report_items.append((raw, label))

                # backfill so next time dropdown works directly from ai_reports too
                if callable(insert_fn):
                    try:
                        insert_fn(
                            sid,
                            int(msg_id) if msg_id is not None else None,
                            raw,
                            study_uid=getattr(self, "study_uid", None),
                            label=label,
                            kind="report",
                        )
                    except Exception:
                        pass

        # 3) Fill dropdown
        try:
            self.composer.clear_correction_reports()
            for raw, label in report_items:
                self.composer.register_correction_report(raw, label=label)
        except Exception:
            return

        # 4) restore previous selection if possible
        if prev:
            try:
                cmb = self.composer.cmb_corr_reports
                for i in range(1, cmb.count()):
                    if (cmb.itemData(i) or "").strip() == prev:
                        cmb.setCurrentIndex(i)
                        break
            except Exception:
                pass


    def _session_roles(self):
        """Custom roles for sidebar items."""
        base_title_role = int(Qt.UserRole) + 10
        pinned_role = int(Qt.UserRole) + 11
        return base_title_role, pinned_role

    def _session_pins_path(self) -> str:
        import os
        return os.path.join(self._ai_chat_dir(), "_session_pins.json")

    def _load_pinned_sids(self) -> list[str]:
        """
        NEW: pinned state comes from DB (ai_sessions.pinned).
        Fallback: if DB has no pins but legacy _session_pins.json exists, migrate it into DB once.
        """
        # 1) DB pins (persistent across restarts / cwd changes)
        try:
            study_uid = getattr(self, "study_uid", None)
            pins = U.ai_fetch_pinned_sids(study_uid) if study_uid else U.ai_fetch_pinned_sids(None)
            if isinstance(pins, list) and pins:
                return [str(x) for x in pins if str(x).strip()]
        except Exception:
            pins = []

        # 2) Legacy file fallback + one-time migration to DB
        try:
            path = self._session_pins_path()
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            legacy = data.get("pinned", [])
            if isinstance(legacy, list):
                legacy = [str(x) for x in legacy if str(x).strip()]
            else:
                legacy = []
            if legacy:
                try:
                    study_uid = getattr(self, "study_uid", None)
                    U.ai_set_pinned_bulk(study_uid if study_uid else None, legacy)
                except Exception:
                    pass
            return legacy
        except Exception:
            return []


    def _save_pinned_sids(self, pinned: list[str]) -> None:
        """
        NEW: persist pins into DB.
        (Optional) keeps writing legacy file only if DB update fails.
        """
        pinned = [str(x) for x in (pinned or []) if str(x).strip()]

        # DB persist (preferred)
        try:
            study_uid = getattr(self, "study_uid", None)
            U.ai_set_pinned_bulk(study_uid if study_uid else None, pinned)
            return
        except Exception:
            pass

        # Legacy file fallback (best-effort)
        import time
        payload = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pinned": pinned,
        }
        try:
            self._atomic_write_json(self._session_pins_path(), payload)
        except Exception:
            try:
                with open(self._session_pins_path(), "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception:
                pass


    def _is_session_pinned(self, sid: str) -> bool:
        if not sid:
            return False
        pins = getattr(self, "_pinned_sids", None)
        if not isinstance(pins, list):
            pins = self._load_pinned_sids()
            self._pinned_sids = pins
        return sid in set(pins)

    def _set_session_pinned(self, sid: str, pinned: bool) -> None:
        if not sid:
            return
        pins = getattr(self, "_pinned_sids", None)
        if not isinstance(pins, list):
            pins = self._load_pinned_sids()
        pins = [x for x in pins if x != sid]
        if pinned:
            pins.insert(0, sid)  # newest pin on top
        self._pinned_sids = pins
        self._save_pinned_sids(pins)

    def _find_sidebar_item_by_sid(self, sid: str) -> QListWidgetItem | None:
        if not sid:
            return None
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it and it.data(Qt.UserRole) == sid:
                return it
        return None

    def _get_item_base_title(self, it: QListWidgetItem) -> str:
        base_title_role, _ = self._session_roles()
        try:
            v = it.data(base_title_role)
            if isinstance(v, str) and v.strip():
                return v.strip()
        except Exception:
            pass
        # fallback: strip pin prefix
        t = (it.text() or "").strip()
        if t.startswith("📌 "):
            t = t[2:].strip()
        return t or "New Chat"

    def _apply_item_title_and_style(self, it: QListWidgetItem, base_title: str, *, sid: str | None = None):
        """Set displayed title with pin prefix (if pinned) and keep base title in item data."""
        base_title_role, pinned_role = self._session_roles()
        base_title = (base_title or "").strip() or "New Chat"

        if sid is None:
            sid = it.data(Qt.UserRole)

        pinned = self._is_session_pinned(str(sid)) if sid else False

        try:
            it.setData(base_title_role, base_title)
            it.setData(pinned_role, bool(pinned))
        except Exception:
            pass

        shown = f"📌 {base_title}" if pinned else base_title
        it.setText(shown)

        # subtle emphasis for pinned (bold)
        try:
            from PySide6.QtGui import QFont
            f = it.font()
            f.setBold(bool(pinned))
            it.setFont(f)
        except Exception:
            pass

    def _ensure_sessions_context_menu(self):
        """Bind context menu once."""
        if getattr(self, "_session_ctx_bound", False):
            return
        self._session_ctx_bound = True
        try:
            self.list.setContextMenuPolicy(Qt.CustomContextMenu)
            self.list.customContextMenuRequested.connect(self._on_sessions_context_menu)
        except Exception:
            pass

    def _on_sessions_context_menu(self, pos):
        """Right-click on chat list => Pin/Unpin, Rename, Delete."""
        try:
            it = self.list.itemAt(pos)
            if not it:
                return
            sid = it.data(Qt.UserRole)
            if not sid:
                return

            pinned = self._is_session_pinned(sid)

            menu = QMenu(self)
            act_pin = QAction("📌 Pin" if not pinned else "📌 Unpin", menu)
            act_ren = QAction("✏️ Rename", menu)
            act_del = QAction("🗑️ Delete", menu)

            act_pin.triggered.connect(lambda _=False, s=sid: self._toggle_pin_session(s))
            act_ren.triggered.connect(lambda _=False, s=sid: self._rename_session_by_sid(s))
            act_del.triggered.connect(lambda _=False, s=sid: self._delete_session_by_sid(s))

            menu.addAction(act_pin)
            menu.addSeparator()
            menu.addAction(act_ren)
            menu.addAction(act_del)

            menu.exec(self.list.viewport().mapToGlobal(pos))
        except Exception:
            pass

    def _toggle_pin_session(self, sid: str):
        cur_sid = getattr(self, "current_session_id", None)
        new_state = not self._is_session_pinned(sid)
        self._set_session_pinned(sid, new_state)
        self._rebuild_sidebar_only(keep_selected_sid=cur_sid)

    def _rename_session_by_sid(self, sid: str):
        it = self._find_sidebar_item_by_sid(sid)
        if not it:
            return

        old = self._get_item_base_title(it)

        try:
            from PySide6.QtWidgets import QInputDialog, QLineEdit
            new_title, ok = themed_input_text(
                self,
                "Rename chat",
                "New name:",
                old,
                QLineEdit.Normal,
            )
        except Exception:
            return

        if not ok:
            return
        new_title = (new_title or "").strip()
        if not new_title:
            return

        # persist to DB (best-effort)
        try:
            U.ai_upsert_session(sid, new_title, getattr(self, "study_uid", None))
        except Exception:
            pass

        # update UI item (keeps pin prefix)
        self._apply_item_title_and_style(it, new_title, sid=sid)

    def _delete_session_by_sid(self, sid: str):
        if not sid:
            return
        try:
            from PySide6.QtWidgets import QMessageBox
            ans = themed_message_box(
                self,
                QMessageBox.Icon.Question,
                "Delete chat",
                "Are you sure you want to delete this chat?\n(This cannot be undone)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if ans != QMessageBox.Yes:
                return
        except Exception:
            return

        # 1) try DB delete if available in U (best-effort, safe)
        deleted_db = False
        for fn_name in (
            "ai_delete_session_and_messages",
            "ai_delete_session",
            "ai_remove_session",
            "ai_purge_session",
        ):
            fn = getattr(U, fn_name, None)
            if callable(fn):
                try:
                    fn(sid, getattr(self, "study_uid", None))
                    deleted_db = True
                    break
                except TypeError:
                    try:
                        fn(sid)
                        deleted_db = True
                        break
                    except Exception:
                        pass
                except Exception:
                    pass

        if not deleted_db:
            # try separate message purge + session row (still best-effort)
            for fn_name in ("ai_delete_messages_for_session", "ai_purge_session_messages", "ai_delete_messages"):
                fn = getattr(U, fn_name, None)
                if callable(fn):
                    try:
                        fn(sid)
                    except Exception:
                        pass
            for fn_name in ("ai_delete_session_row", "ai_delete_session_only"):
                fn = getattr(U, fn_name, None)
                if callable(fn):
                    try:
                        fn(sid, getattr(self, "study_uid", None))
                    except TypeError:
                        try:
                            fn(sid)
                        except Exception:
                            pass
                    except Exception:
                        pass

        # 2) delete persisted side files for that session (AI-Chat/<sid>-*.json)
        try:
            import os, glob
            pat = os.path.join(self._ai_chat_dir(), f"{sid}-*.json")
            for fp in glob.glob(pat):
                try:
                    os.remove(fp)
                except Exception:
                    pass
        except Exception:
            pass

        # 3) remove from pins
        try:
            pins = getattr(self, "_pinned_sids", None)
            if not isinstance(pins, list):
                pins = self._load_pinned_sids()
            pins = [x for x in pins if x != sid]
            self._pinned_sids = pins
            self._save_pinned_sids(pins)
        except Exception:
            pass

        # 4) remove from UI + cache
        try:
            self.sessions.pop(sid, None)
        except Exception:
            pass

        # if deleting current open session => switch to another
        was_current = (getattr(self, "current_session_id", None) == sid)

        # remove list item
        try:
            it = self._find_sidebar_item_by_sid(sid)
            if it:
                row = self.list.row(it)
                self.list.takeItem(row)
        except Exception:
            pass

        if was_current:
            # pick next available
            if self.list.count() > 0:
                self.list.setCurrentRow(0)
                nxt = self.list.currentItem()
                if nxt:
                    self._open_session(nxt)
            else:
                # no session left => create new
                try:
                    self._new_session()
                except Exception:
                    self.controller.reset_session()
                    self.history.clear()


    def _rebuild_sidebar_only(self, *, keep_selected_sid: str | None = None):
        """Rebuild only the left list (does NOT re-render history)."""
        self._ensure_sessions_context_menu()

        # fetch sessions
        try:
            if getattr(self, "study_uid", None):
                sessions = U.ai_fetch_sessions_by_study(self.study_uid) or []
            else:
                sessions = U.ai_fetch_all_sessions() or []
            sessions = [(sid, title) for (sid, title) in sessions
                        if isinstance(sid, str) and sid.startswith(f"{self.ns}-")]
        except Exception:
            sessions = []

        # apply pin ordering
        pins = getattr(self, "_pinned_sids", None)
        if not isinstance(pins, list):
            pins = self._load_pinned_sids()
        sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}

        cleaned_pins = [p for p in pins if p in sid_to_title]
        if cleaned_pins != pins:
            self._pinned_sids = cleaned_pins
            self._save_pinned_sids(cleaned_pins)

        ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
        pinned_set = set(cleaned_pins)
        ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

        # rebuild list without firing open_session
        try:
            self.list.blockSignals(True)
            self.list.clear()
            for sid, title in ordered:
                it = QListWidgetItem()
                it.setData(Qt.UserRole, sid)
                self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
                self.list.addItem(it)
        finally:
            try:
                self.list.blockSignals(False)
            except Exception:
                pass

        # restore selection (no open)
        target = keep_selected_sid or getattr(self, "current_session_id", None)
        if target:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it and it.data(Qt.UserRole) == target:
                    self.list.setCurrentItem(it)
                    break


    def _ai_chat_dir(self) -> str:
        """This study's AI-Chat folder: ``<ATTACHMENTS_DIR>/<study_uid>/AI-Chat``.

        2026-07-31 — this used to be ``Path(os.getcwd()) / "attachment" / ...``,
        which is wrong three separate ways:

        * it depends on the directory the process happened to be launched from;
        * `data_paths.migrate_legacy_data()` MOVES ``<PROJECT_ROOT>/attachment``
          into ``ATTACHMENTS_DIR`` on **every** startup — so EchoMind was
          re-creating, every session, the exact tree the migration relocates.
          A self-inflicted move loop: next launch relocates the files, EchoMind
          looks in the old place, finds nothing, and the Standard tab silently
          loads empty;
        * under PyInstaller the CWD is ``sys._MEIPASS``, a temp directory
          deleted on exit — 100% silent loss in a frozen build.

        `data_paths` declares itself the authority ("every module that writes or
        reads user data MUST import paths from here"). EchoMind never did.

        Nothing already saved is abandoned: if the legacy folder still holds
        this study's data and the new one does not, the legacy folder is used
        and a warning names both, so a radiologist's saved work cannot vanish
        because of this change.
        """
        from pathlib import Path
        import os

        study_uid = getattr(self, "study_uid", None) or "unknown"
        legacy = Path(os.getcwd()) / "attachment" / study_uid / "AI-Chat"
        try:
            from PacsClient.utils.data_paths import ATTACHMENTS_DIR
            base = Path(ATTACHMENTS_DIR) / study_uid / "AI-Chat"
        except Exception:
            base = legacy

        try:
            if (base != legacy and not base.exists()
                    and legacy.is_dir() and any(legacy.iterdir())):
                _log.warning(
                    "[AI-Chat] reading the legacy attachment folder %s; "
                    "move it under %s so the startup migration stops relocating it",
                    legacy, base.parent.parent,
                )
                return str(legacy)
        except Exception:
            pass

        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def _atomic_write_json(self, file_path: str, data: dict):
        """
        Atomically writes JSON to file_path (UTF-8, pretty, safe replace).
        """
        import json, tempfile, shutil, os

        parent = os.path.dirname(file_path)
        os.makedirs(parent, exist_ok=True)

        fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            # 2026-07-31 — this function is docstring'd "Atomically writes JSON"
            # but `shutil.move` is NOT atomic on Windows: it tries `os.rename`
            # and falls back to `copy2 + unlink` on OSError, and on Windows
            # `os.rename` raises FileExistsError whenever the destination
            # exists -- i.e. on every re-save. So it degraded to a
            # truncate-then-refill copy, and a crash mid-write left a half
            # file that `_read_json_file`'s bare `except` turns into a silently
            # blank Standard tab, with the previous good version already gone.
            # `os.replace` is a real atomic rename-over on NTFS and POSIX; the
            # rest of this codebase already uses it (settings_store,
            # api_manager). The fsync above adds power-loss durability.
            os.replace(tmp, file_path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _persist_transcribe(self, tr_text: str):
        """
        Saves the transcribe text to:
          <AI-Chat>/<session_id>-transcribe.json
        """
        import time, os
        sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
        study_uid = getattr(self, "study_uid", None) or "unknown"
        data = {
            "session_id": sid,
            "study_uid": study_uid,
            "type": "transcribe",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "text": tr_text or ""
        }
        dst = os.path.join(self._ai_chat_dir(), f"{sid}-transcribe.json")
        self._atomic_write_json(dst, data)

        # The prefetch started when recording did, so by now the reception services
        # are usually cached. Re-seed from the warm cache and re-read the card — one
        # SQLite round trip on the UI thread, and the only place the physician sees
        # the Service field fill itself in. Swallowed: a transcript is already saved
        # above and must not be jeopardised by a metadata refresh.
        try:
            if sid and sid != "local":
                self._seed_session_metadata(sid)
                self._sync_metadata_card(sid)
        except Exception as exc:
            _log.debug("[EchoMind-meta] post-transcribe refresh skipped: %s", exc)


    def _persist_normal_template(self, tpl_text: str):
        """
        Saves the normal template text to:
          <AI-Chat>/<session_id>-normal_template.json
        """
        import time, os
        sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
        study_uid = getattr(self, "study_uid", None) or "unknown"
        data = {
            "session_id": sid,
            "study_uid": study_uid,
            "type": "normal_template",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "text": tpl_text or ""
        }
        dst = os.path.join(self._ai_chat_dir(), f"{sid}-normal_template.json")
        self._atomic_write_json(dst, data)

    def _persist_standard(
        self,
        std_text: str,
        *,
        text_en: str | None = None,
        text_fa: str | None = None,
        raw: str | None = None,
        parsed: dict | None = None
    ):
        """
        Saves the standard structured text and optional raw/parsed fields to:
        <AI-Chat>/<session_id>-standard.json

        Fix:
        - also store text_en / text_fa explicitly so EN/FA never collapse after reload.
        - keep legacy "text" for backward compatibility / quick preview.
        """
        import time, os
        sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
        study_uid = getattr(self, "study_uid", None) or "unknown"

        data = {
            "session_id": sid,
            "study_uid": study_uid,
            "type": "standard",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "text": std_text or "",
        }

        # ✅ store BOTH language buffers (even if empty) so reload is deterministic
        if text_en is not None:
            data["text_en"] = text_en or ""
        if text_fa is not None:
            data["text_fa"] = text_fa or ""

        if raw is not None:
            data["raw_standardize_output"] = raw
        if parsed is not None:
            data["parsed"] = parsed

        dst = os.path.join(self._ai_chat_dir(), f"{sid}-standard.json")
        self._atomic_write_json(dst, data)


    def _continue_send_after_voices(self, user_text: str, tr_text: str, server_sid: t.Optional[str], mode: str):
        """
        بعد از آپلود چند ویس و دریافت متن ترنسکرایب:
          - متن‌های user و transcript را با هم merge می‌کنیم
          - در حالت Report طبق سیاست جدید: همان merged مستقیماً ارسال می‌شود (بدون استانداردسازی)
          - در حالت Assist/Chat مثل قبل
        """
        merged = (user_text or "").strip()
        tr = (tr_text or "").strip()

        if merged and tr:
            merged = f"{merged}\n{tr}"
        elif tr and not merged:
            merged = tr

        if mode == "Assist":
            self._open_assist_menu(merged)
            return

        if mode == "Report":
            # سیاست جدید: مستقیم همان متن را برای ساخت گزارش بفرست
            self._send_with_mode(merged, "Report")
            return

        # Chat و سایر
        self._send_with_mode(merged, "Chat")


    # متد جدید برای انتخاب مودالیتی
    def _select_modality(self, modality):
        self._current_modality = modality
        OneChatPage.last_selected_modality = modality  # class-level persistence
        self._set_modality_text(modality)

    def _set_modality_text(self, modality):
        short_text = modality[:4] + "..." if len(modality) > 4 else modality
        self.composer.btn_modality.setText(f"{short_text}")



    def _upload_voices_then(self, file_paths: t.List[str],
                            cont: t.Callable[[str, t.Optional[str]], None]):
        """
        Upload queued voice files as a multi-file request to the transcript API.
        Always calls: cont(transcript_text, session_id).
        """
        # ⬅️ همین که تایپینگ/بابل جدیدی قرار است اضافه شود، خوشامد را حذف کن
        self._drop_welcome_if_any()

        if not file_paths:
            cont("", None)
            return

        typing_b = self.history.add_typing("AI ChatBot", "Uploading voices")
        try:
            self.composer.set_enabled(False)
        except Exception:
            pass

        def cleanup_ui():
            try:
                self.history.remove_widget(typing_b)
            except Exception:
                pass
            try:
                self.composer.set_enabled(True)
            except Exception:
                pass

        def work():
            # Queued/multi-file voice upload. Same change as _transcribe_now: the
            # destination comes from Settings ▸ EchoMind ▸ Voice to Text via the
            # shared service, never from the hard-coded URL_GEN_TRANSCRIPT constant.
            from modules.EchoMind.voice_transcription import VoiceTranscriptionService

            valid = [p for p in (file_paths or []) if p and os.path.exists(p)]
            if not valid:
                raise Exception("No valid audio files to upload.")
            resp = VoiceTranscriptionService().transcribe(
                valid,
                quality_mode=getattr(self.composer, "_transcribe_quality_mode", "clear"),
            )
            if not resp.get("ok", True) and not str(resp.get("transcript") or "").strip():
                raise Exception(str(resp.get("error") or "Transcription failed."))
            return resp

        worker = ApiWorker(work, parent=self)
        if not hasattr(self, "_workers"):
            self._workers = []
        self._workers.append(worker)

        def _finish_worker():
            try:
                if worker in self._workers:
                    self._workers.remove(worker)
            except Exception:
                pass
            try:
                worker.deleteLater()
            except Exception:
                pass

        def ok(resp: dict):
            # ✅ Track transcript minutes for multi-file transcription
            try:
                self._log_irannobat_transcript_usage(resp, file_paths)
            except Exception:
                pass
            server_sid = resp.get("session_id")
            tr_text = (resp.get("transcript") or "").strip()

            if server_sid:
                try:
                    self.controller.switch_session(server_sid)
                except Exception:
                    pass

            try:
                self.composer.clear_pending_voices()
            except Exception:
                try:
                    self.composer.clear_attachment()
                except Exception:
                    pass

            # ------ 🔥 Bubble واقعی ویس (اصلاح اصلی) ------
            for p in file_paths:
                try:
                    self.history.add_voice("You", p)
                except Exception as e:
                    print("VoiceMessageBubble error:", e)

            # پس اگر ترنسکریپت از AI آمد → متنش را هم نشان بده
            # When the continuation runs it merges this transcript into the
            # outgoing "You" bubble, so printing it here as well would show the
            # same text twice. Only the legacy (kill-switched) path needs it.
            if tr_text and not _voice_send_cont_enabled():
                self.controller.bubble("AI ChatBot", tr_text)

            cleanup_ui()
            _finish_worker()

            # ── the send. See `_ENV_VOICE_SEND_CONT` at the top of this module
            # for why this was missing. `cont` is what actually issues the
            # request; without it Send-with-a-voice-chip was a no-op.
            if _voice_send_cont_enabled():
                try:
                    cont(tr_text, server_sid)
                except Exception as exc:
                    _log.warning("[VOICE-SEND] continuation failed: %s", exc, exc_info=True)

        def er(msg: str):
            try:
                safe = self._safe_user_error(msg)
                # اگر اینترنت/سرور قطع باشد، safe خودش پیام فارسی ثابت است
                self.controller.bubble("AI ChatBot", f"⚠️ <i>{safe}</i>")
            except Exception:
                pass
            cleanup_ui()
            _finish_worker()
            cont("", None)


        worker.done.connect(ok)
        worker.failed.connect(er)
        worker.start()


    def _send_report_correction(self, correction_note: str, *,
                                system_prompt_prefix: str = "",
                                force_backend: str = "",
                                turbo: bool = False):
        """Correction tab: apply user's correction note to a selected report and display corrected report."""
        backend_name = get_active_backend_display_name()
        backend, _center_name, center_key = _resolve_active_ai_identity()
        if force_backend:
            # Turbo is pinned to the company pipeline like every other Turbo
            # action; the llm_backend setting switches Send, not Turbo.
            backend = force_backend
        if not center_key:
            print("[Correction] blocked: AI backend not configured")
            self.controller.bubble("AI ChatBot", f"❌ {backend_name} is not configured. Access denied.")
            return
        
        note = (correction_note or "").strip()
        try:
            # Get the ENTIRE original JSON report (not just plain text)
            report_text = (self.composer.get_selected_correction_report_text() or "").strip()
        except Exception:
            report_text = ""
        
        if not report_text:
            print("[Correction] blocked: report not selected")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a report from the Correction dropdown.</i>")
            return
        
        if not note:
            print("[Correction] blocked: empty note")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please write your correction notes in the box below.</i>")
            return

        print(f"[Correction] sending note_len={len(note)} report_len={len(report_text)}")
        
        # Show user's correction note
        # 2026-08-06: mark the NEXT persisted report as a correction, so
        # correction history stays separable from fresh generations. A
        # correction is the physician saying "not that — this", which is the
        # highest-signal record we keep.
        self._pending_report_kind = "correction"
        self._pending_corrects_msg_id = self._resolve_corrected_msg_id(report_text)
        self.controller.bubble(
            "You (⚡Turbo · ✅ Correction)" if turbo else "You (✅ Correction)", note)
        
        def work():
            # Correction is the final targeted-revision step → use the dedicated (stronger)
            # correction model. On the company/GapGPT path this is gpt-5.4 (was gpt-4.1-mini);
            # on the OpenAI path it resolves via the "correction" feature in Settings.
            return _ai_module(backend).correction(
                user_report=report_text,  # Full JSON report
                correction_note=note,
                CENTER_Key=center_key,
                model=_ai_model("correction", company_direct.PRIMARY_REPORT_MODEL, backend),
                # A PREFIX on the shared correction prompt, never an override: the
                # response is parsed and the shared prompt carries the key contract
                # (a mammography report has eleven keys, not five).
                system_prompt_prefix=system_prompt_prefix,
            )
        
        def ok(res):
            try:
                # Handle result
                sid_new = res.get("session_id") if isinstance(res, dict) else None
                if sid_new:
                    try:
                        self.controller.switch_session(sid_new)
                    except Exception:
                        pass
                
                # Extract corrected report
                corrected_text = res["content"].strip() if isinstance(res, dict) else str(res).strip()

                # ── 2026-08-01: use the shared cleaner ────────────────────────
                # This used to strip the code fence ONLY INSIDE `if "<|end|>" in
                # corrected_text`, so a model that returned ```json {...} ```
                # without the sentinel fell straight through to json.loads and
                # failed. The OpenAI twin's correction prompt asks for neither a
                # fence nor the sentinel, so on that backend the failure was the
                # normal case. (The old `.strip('```json')` was also a character-
                # set strip, not a prefix strip — it removed any of ` j s o n
                # from both ends, which is not what it reads as.)
                # `_clean_model_json_text` strips <|end|> FIRST and then both
                # fences, unconditionally.
                try:
                    from .openai_reporter import _clean_model_json_text as _clean
                    corrected_text = (_clean(corrected_text) or "").strip()
                except Exception:
                    if "<|end|>" in corrected_text:
                        corrected_text = corrected_text.split("<|end|>", 1)[0].strip()

                # Parse the JSON to ensure it's valid
                import json
                try:
                    corrected_json = json.loads(corrected_text)

                    # ── 2026-08-01: a correction is a PATCH; verify it patched ──
                    # The only check here used to be "does it parse". A response
                    # that dropped Normal Findings, invented an Impression, or
                    # emptied a section parsed fine and rendered as a normal
                    # report — and `_send_to_reception` builds its payload from
                    # the rendered bubble, so it shipped.
                    try:
                        original_json = json.loads(_clean(report_text))
                    except Exception:
                        original_json = None

                    if isinstance(original_json, dict) and isinstance(corrected_json, dict):
                        dropped = [k for k in original_json if k not in corrected_json]
                        invented = [k for k in corrected_json if k not in original_json]
                        emptied = [k for k, v in corrected_json.items()
                                   if original_json.get(k) and not v]
                        if dropped or invented or emptied:
                            parts = []
                            if dropped:
                                parts.append("removed: " + ", ".join(map(str, dropped)))
                            if invented:
                                parts.append("added: " + ", ".join(map(str, invented)))
                            if emptied:
                                parts.append("emptied: " + ", ".join(map(str, emptied)))
                            _log.warning("[CORRECTION] rejected — %s", "; ".join(parts))
                            self.controller.bubble(
                                "AI ChatBot",
                                "❌ <b>Correction rejected — the result did not match the "
                                "original report's structure.</b><br>"
                                + "<br>".join(escape(p) for p in parts)
                                + "<br><i>Your original report is unchanged. Please try "
                                  "rephrasing the correction.</i>",
                            )
                            return

                    # Render as HTML report
                    html = self._render_kv_report_html([corrected_json])
                    self._bubble_origin_hint = "report"
                    raw_json = json.dumps(corrected_json, ensure_ascii=False, indent=2)
                    # 2026-08-01 — set the pending raw BEFORE bubbling so
                    # `_append_bubble` persists the CORRECTED report to the DB.
                    # Without this the correction lived only in the in-memory
                    # dropdown: one refresh and the dropdown silently reverted to
                    # the uncorrected text, so the next correction was applied to
                    # a report that still had the old value.
                    self._pending_report_raw_en = raw_json
                    self.controller.bubble("AI ChatBot", html)

                    # Register corrected report for further corrections
                    self.composer.register_correction_report(raw_json)
                except json.JSONDecodeError as e:
                    # 2026-08-01 — do NOT bubble the raw text. It was interpolated
                    # unescaped, so a finding like "lesion <8 mm" was parsed as
                    # markup and truncated on screen; and every non-user bubble
                    # carries a live "Send to reception" button, so an unparseable
                    # dump was shippable. Log it, tell the user plainly.
                    _log.error("[CORRECTION] unparseable response: %s | %s",
                               e, (corrected_text or "")[:2000])
                    self.controller.bubble(
                        "AI ChatBot",
                        "⚠️ <i>The correction response was not a valid report and was "
                        "discarded. Your original report is unchanged — please retry.</i>",
                    )
            
            except Exception as e:
                self.controller.bubble("AI ChatBot", f"❌ Error processing correction: {str(e)}")
        
        def er(msg: str):
            self.controller.bubble("AI ChatBot", f"❌ Correction failed: {self._safe_user_error(msg)}")
        
        self._run_async(work, ok, er, lock_btn=getattr(self.composer, "btn_send", None), typing="Applying corrections...")
        
    def _on_send_clicked(self, text: str):
        """
        رفتار جدید Send:
          - در حالت Report:
              * اگر تب فعال 'standard' و متن استاندارد داریم → همان را بفرست
              * اگر تب فعال 'transcribe' و متن ترنسکرایب داریم → همان را بفرست (بدون استانداردسازی)
              * در غیر این صورت، اگر ویس در صف است → اول ترنسکرایب، بعد «همان متن ترنسکرایب شده» را بفرست
              * اگر هیچ‌کدام نبودند → مثل قبل، متن جعبه را بفرست
          - سایر مودها (Chat / Assist / Search) مثل قبل با یک تفاوت: تغییری ندادیم
        """
        txt = text or ""
        mode = self.page_mode
        
        # متن‌های هر تب (و سینک بافر تب فعال)
        std_text, tr_text = self.composer.get_tab_texts()
        std_text = (std_text or "").strip()
        tr_text = (tr_text or "").strip()
        active_tab = self.composer.get_active_tab()
        
        # صف ویس‌ها
        try:
            voices = self.composer.get_pending_voices()
        except Exception:
            voices = []

        # ✅ Correction tab override (no voice support here)
        try:
            active_tab = self.composer.get_active_tab()
        except Exception:
            active_tab = ""

        if active_tab == "correction":
            if voices:
                self.controller.bubble(
                    "AI ChatBot",
                    "⚠️ <i>Correction does not support voice input. Please remove voice chips or switch tab.</i>",
                )
                return

            # Correction is a Report-tab feature (report selected from dropdown + note in textbox)
            if mode == "Report":
                self._send_report_correction(txt)
            else:
                self.controller.bubble("AI ChatBot", "⚠️ <i>Correction is only available in Report mode.</i>")
            return

            
        # --- منطق ویژه برای Report ---
        if mode == "Report":
            # ✅ Correction tab: user selects report from dropdown + writes correction note.
            if active_tab == "correction":
                self._send_report_correction(txt)
                return

            # Always use the persisted modality — no menu anymore
            modality = getattr(self, "_current_modality", None)
            if not modality:
                self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a modality first.</i>")
                return

            if active_tab == "standard" and std_text:
                self._send_with_mode(std_text, "Report", modality=modality)
                return
            if active_tab == "transcribe" and tr_text:
                self._send_with_mode(tr_text, "Report", modality=modality)
                return
            if active_tab == "normal_template":
                if tr_text:
                    self._send_with_mode(tr_text, "Report", modality=modality)
                    return
                if std_text:
                    self._send_with_mode(std_text, "Report", modality=modality)
                    return

            if voices:
                def cont_with_modality(tr, sid):
                    merged = (txt or "").strip()
                    tr = (tr or "").strip()
                    if merged and tr:
                        merged = f"{merged}\n{tr}"
                    elif tr:
                        merged = tr
                    self._send_with_mode(merged, "Report", modality=modality)
                self._upload_voices_then(file_paths=voices, cont=cont_with_modality)
                return
            self._send_with_mode(txt.strip(), "Report", modality=modality)
            return
                    
            # اگر مودالیتی انتخاب نشده باشد، منوی انتخاب نمایش داده شود
            if active_tab == "standard" and std_text:
                self._open_report_modality_menu(std_text)
                return
            if active_tab == "transcribe" and tr_text:
                self._open_report_modality_menu(tr_text)
                return
            if voices:
                def cont_with_menu(tr, sid):
                    merged = (txt or "").strip()
                    tr = (tr or "").strip()
                    if merged and tr:
                        merged = f"{merged}\n{tr}"
                    elif tr:
                        merged = tr
                    self._open_report_modality_menu(merged)
                self._upload_voices_then(file_paths=voices, cont=cont_with_menu)
                return
            self._open_report_modality_menu(txt.strip())
            return
        
        # --- سایر مودها مثل قبل ---
        if voices:
            self._upload_voices_then(
                file_paths=voices,
                cont=lambda tr_text2, server_sid: self._continue_send_after_voices(
                    user_text=txt, tr_text=tr_text2, server_sid=server_sid, mode=mode
                )
            )
            return
        if mode == "Assist":
            self._open_assist_menu(txt)
        elif mode in ("Chat", "Report"):
            self._send_with_mode(txt, mode)
        else:
            self._send_with_mode(txt, "Chat")


    def _on_hq_all_modality_clicked(self):
        from .api_manager import APIKeyManager
        # ── Turbo is PINNED to the company GapGPT pipeline (owner decision 2026-08-02).
        # A fixed company-controlled workflow: hardcoded connection (GapGPT), hardcoded
        # prompts (build_report_system_prompt), authorized centers only (the CENTERS
        # registry in api_manager.py), company-selected model (PRIMARY_REPORT_MODEL).
        # `llm_backend` is a SEND-backend switch and must NOT reroute Turbo — switching
        # Send to the user's OpenAI key no longer moves Turbo onto the user's
        # key/model/endpoint (it used to; that was the scoping leak).
        backend = TURBO_BACKEND   # fixed company config — never a Settings value
        # ── ENTITLEMENT. Turbo is technically separate from the AI-PACS backend now
        # (its own hardcoded GapGPT configuration, a direct connection), but it must
        # NOT be separate for licensing: one company authorisation entitles both, and
        # its absence disables both. The hardcoded credentials Turbo carries are
        # plumbing, never permission — `company_entitled()` is the permission.
        from modules.EchoMind.entitlement import company_entitled, ENTITLEMENT_DENIED
        if not company_entitled():
            _log.warning("[Turbo] blocked: installation is not company-entitled")
            self.controller.bubble("AI ChatBot", ENTITLEMENT_DENIED)
            return
        manager = APIKeyManager.instance()
        center_key = manager.get_current_key() or ""
        if not center_key:
            _log.warning("[Turbo] blocked: entitled but no centre key resolved")
            self.controller.bubble("AI ChatBot", ENTITLEMENT_DENIED)
            return

        if str(getattr(self, "page_mode", "")).lower() not in ("report", "chatgpt"):
            _log.warning("[Turbo] blocked: invalid page_mode page_mode=%s", getattr(self, "page_mode", None))
            return

        # ── Correction tab: Turbo EDITS the selected report ─────────────────
        # Observed 2026-08-09: with the Correction tab active, Turbo fell through
        # to the `else` branch below, took the correction INSTRUCTION as if it were
        # a dictation and called reporter(). The physician got a brand-new report
        # generated from his own edit note, and the report he had selected was
        # never sent at all. Correction is an EDIT, and it needs a different
        # function, a different model and a different prompt.
        try:
            _tab = str(self.composer.get_active_tab() or "").strip().lower()
        except Exception:
            _tab = ""
        if _tab == "correction":
            self._turbo_correction(backend, center_key)
            return

        # متن را مشابه منطق Send انتخاب کن
        std_text, tr_text = self.composer.get_tab_texts()
        std_text = (std_text or "").strip()
        tr_text  = (tr_text  or "").strip()
        active_tab = self.composer.get_active_tab()

        if active_tab == "standard" and std_text:
            user_msg = std_text
        elif active_tab == "transcribe" and tr_text:
            user_msg = tr_text
        elif active_tab == "normal_template":
            # هنگام ادیت Template، متن اصلی را از Transcribe (یا Standard) بگیر
            if tr_text:
                user_msg = tr_text
            elif std_text:
                user_msg = std_text
            else:
                user_msg = ""
        else:
            user_msg = (self.composer.box.toPlainText() or "").strip()

        # Always use the persisted modality — no menu anymore
        modality = getattr(self, "_current_modality", None)
        if not modality:
            _log.warning("[Turbo] blocked: modality not selected")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a modality first.</i>")
            return
        try:
            normal_template = (self.composer.get_normal_template_plain_text() or "").strip() or None
        except Exception:
            normal_template = None

        # برای لاگ/تاریخچه
        self.controller.bubble("You (⚡Turbo Mode)", user_msg or "(session-based)")
        # 2026-08-06: logger, not print — a Turbo run must be greppable in
        # app.log. `model` is logged too: verifying the last live run meant
        # inferring it from the token-usage record.
        _log.info(
            "[Turbo] sending backend=%s model=%s text_len=%d modality=%s normal_template=%s",
            backend, company_direct.PRIMARY_REPORT_MODEL,
            len((user_msg or "").strip()), modality,
            # 2026-08-07: which REGISTER the report comes back in — definitive normals
            # vs hedged "no gross abnormality" — depends entirely on whether a template
            # was attached. Diagnosing the 53516 report meant inferring that from the
            # output's wording, because the run itself never recorded it.
            (f"{len(normal_template)}ch" if normal_template else "none"),
        )

        def work():
            # ── Turbo's OWN prompt (owner decision 2026-08-08) ──────────────
            # reporter() is shared: Turbo always, and Send whenever the backend is
            # `company` (the default). So the Turbo/Send split has to be made HERE —
            # this is the only place that knows the request is Turbo. Send calls the
            # same function without an override and keeps the shared prompt.
            # Fully swallowed: None means "use the shared builder", so a failure in
            # the Turbo prompt costs a divergence, never a report.
            _turbo_sys = None
            _gate = None
            try:
                from .turbo_prompt import build_turbo_system_prompt
                _gate = self._build_gate_profile(user_msg)
                _turbo_sys = build_turbo_system_prompt(
                    modality, normal_template or "",
                    profile=_gate,
                )
            except Exception as _tp_exc:
                _log.warning("[Turbo] own prompt unavailable, using the shared "
                             "builder: %s", _tp_exc)
            # 2026-08-09: `ctx=` is the gate indicator, and `_gate` is now the SAME
            # object the prompt was built from.
            #
            # The previous version of this line called _build_gate_profile() a SECOND
            # time purely to format the message, so it always printed the regions the
            # run SHOULD have used -- never the ones it did. Every Turbo run on
            # 2026-08-09 between 14:41 and 16:46 logged a different, correct-looking
            # region (['brain'], ['pelvis'], ['abdomen'] ...) next to len=35754 every
            # single time. 35754 is the UNGATED RADIOLOGY prompt: the gate was dead in
            # that process, and the log read as perfectly healthy.
            #
            # So count the artifact instead of restating the intent. The region-major
            # renderer emits "# REPORTING CONTEXT" only when the gate actually
            # narrowed, and never on the ungated path. ctx=0 next to a non-empty
            # regions= is exactly the failure above.
            _ctx = _turbo_sys.count("# REPORTING CONTEXT") if _turbo_sys else 0
            _log.info("[Turbo] prompt source=%s len=%s ctx=%d regions=%s",
                      "turbo" if _turbo_sys else "shared",
                      len(_turbo_sys) if _turbo_sys else "-",
                      _ctx,
                      (_gate or {}).get("regions") or "none")

            return _ai_module(backend).reporter(
                user_msg=user_msg,
                modality=modality,
                normal_template=(normal_template or None),
                CENTER_Key=center_key,
                # pinned: Turbo always runs the company report model
                model=company_direct.PRIMARY_REPORT_MODEL,
                system_prompt_override=_turbo_sys,
            )

        def ok(res):
            try:
                if isinstance(res, dict) and "usage" in res:
                    sid_new = res.get("session_id")
                    if sid_new:
                        try:
                            self.controller.switch_session(sid_new)
                        except Exception:
                            pass

                rep_raw_clean = self._normalize_report_like_payload(res)

                if not rep_raw_clean.strip():
                    self.controller.bubble("AI ChatBot", "⚠️ Empty output.")
                    return

                self._pending_report_raw_en = rep_raw_clean
                items = self._parse_jsonish_list(rep_raw_clean)

                # ── 2026-08-01: this was a WHITELIST, and it deleted report sections ──
                # It kept ONLY the keys named below. "Report Title" is in every
                # report, so `any(k in d for k in keep_keys)` was always true, so
                # the whitelist branch ALWAYS ran — and every key not on the list
                # was dropped before rendering.
                #
                # The keys it dropped are the ones that carry the clinical answer:
                #   mammography → "BI-RADS Category", "Breast Composition",
                #                 "Axillary Evaluation"
                #   obstetric   → "Gestational Age & Dating", "Biometry",
                #                 "Amniotic Fluid", "Placenta & Umbilical Cord",
                #                 "Fetal Presentation", "Anatomy Survey", "Doppler"
                # A mammogram rendered with no BI-RADS category at all, and
                # `_send_to_reception` builds its payload from the rendered bubble,
                # so the referring clinician received it that way too. The raw JSON
                # stored in the DB was complete, which is why this was invisible.
                #
                # The intent was only ever to strip reasoning/meta keys, and the
                # blacklist below already did that. So: blacklist only, anchored so
                # a legitimate section (e.g. "Clinical Correlation") cannot be eaten
                # by a loose substring.
                try:
                    import re
                    noisy_pat = re.compile(
                        r"(?i)^(step_\d+.*|reasoning.*|knowledge.*|mode|clinical|"
                        r"primary diagnoses.*|terminology.*|differential.*|"
                        r"note|notes|changes|changes made|explanation|"
                        r"summary of changes|what i did)$"
                    )
                    filtered_items = []
                    for d in (items or []):
                        if not isinstance(d, dict):
                            continue
                        nd = {k: v for k, v in d.items()
                              if not noisy_pat.match(str(k).strip())}
                        filtered_items.append(nd if nd else d)
                    items = filtered_items or items
                except Exception as exc:
                    _log.warning("[REPORT] section filter failed, rendering unfiltered: %s", exc)
                html = self._render_kv_report_html(items)
                self._bubble_origin_hint = "report"
                self.controller.bubble("AI ChatBot", html)

            except Exception as e:
                self.controller.bubble("AI ChatBot", f"❌ Render error: {e}")

        def er(msg: str):
            # msg از _run_async از قبل امن شده
            self.controller.bubble("AI ChatBot", msg)



        QTimer.singleShot(
            0,
            lambda: self._run_async(
                work, ok, er,
                lock_btn=getattr(self.composer, "btn_send", None),
                typing="HQ Model…"
            )
        )


    def _assist_menu_icon(self, kind: str):
        """Icon for the Assistant/Search chooser. QtAwesome when available,
        else a Qt standard icon, else none. Never raises."""
        color = CLR_TEXT if str(CLR_TEXT).startswith("#") else "#e5e7eb"
        try:
            import qtawesome as qta
            return qta.icon(
                {"Assistant": "fa5s.robot", "Search": "fa5s.search"}.get(kind, "fa5s.circle"),
                color=color,
            )
        except Exception:
            try:
                sp = {"Assistant": QStyle.SP_MessageBoxInformation,
                      "Search": QStyle.SP_FileDialogContentsView}.get(kind)
                if sp is not None:
                    return self.style().standardIcon(sp)
            except Exception:
                pass
        return None

    def _open_assist_menu(self, text: str):
        menu = QMenu(self)
        menu.setObjectName("assistSearchMenu")
        menu.setCursor(Qt.PointingHandCursor)
        # Clean, theme-aligned styling (matches the EchoMind chat surfaces):
        # rounded card, comfortable hit targets, real accent on hover, muted
        # disabled state. Uses the same design tokens as the chat bubbles/composer.
        menu.setStyleSheet(f"""
            QMenu#assistSearchMenu {{
                background: {CLR_BG_PANEL};
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 12px;
                padding: 8px;
            }}
            QMenu#assistSearchMenu::item {{
                background: transparent;
                padding: 10px 22px 10px 14px;
                margin: 3px 4px;
                border-radius: 9px;
                min-width: 168px;
                font-size: 14px;
                font-weight: 600;
                icon-size: 18px;
            }}
            QMenu#assistSearchMenu::item:selected {{
                background: {CLR_ACCENT};
                color: #ffffff;
            }}
            QMenu#assistSearchMenu::item:disabled {{
                color: rgba(148, 163, 184, 0.55);
            }}
            QMenu#assistSearchMenu::icon {{
                padding-left: 10px;
            }}
        """)

        has_text = bool(text.strip()) or bool(self.controller.session_id)
        items = [
            ("Assistant", has_text, "Enter some text or use an existing session."),
            ("Search", bool(text.strip()), "For Search, you must enter text."),
        ]

        for name, enabled, tip in items:
            act = QAction(name, menu)
            icon = self._assist_menu_icon(name)
            if icon is not None:
                act.setIcon(icon)
            act.setEnabled(enabled)
            act.setToolTip("" if enabled else tip)
            if enabled:
                act.triggered.connect(
                    lambda _=False, n=name, t=text:
                    self._send_with_mode(t, "Assistant" if n == "Assistant" else "Search")
                )
            menu.addAction(act)

        btn = self.composer.btn_send
        # Show just above the Send button, right-aligned to it — reads as a
        # clean popover attached to the action rather than a bare native menu.
        menu.adjustSize()
        pos = btn.mapToGlobal(btn.rect().topRight())
        pos.setX(pos.x() - menu.sizeHint().width())
        pos.setY(pos.y() - menu.sizeHint().height() - 6)
        menu.exec(pos)

    def _log_irannobat_usage_from_resp(self, resp: object, model_name: str = "Irannobat") -> None:
        """
        Count + persist token usage for responses coming from the local IRANNOBAT server
        (e.g., 87.236.166.66 endpoints). Server responses typically include:
            prompt_tokens, completion_tokens, total_tokens
        This updates BOTH:
        - api_usage.json (via Manage)
        - SQLite token tables (for Welcome UI)
        """
        try:
            if not isinstance(resp, dict):
                return

            prompt_keys = {
                "prompt_tokens", "input_tokens", "input_token", "prompt_token", "prompt",
            }
            completion_keys = {
                "completion_tokens", "output_tokens", "output_token", "completion_token", "completion",
            }
            total_keys = {
                "total_tokens", "total_token", "total", "tokens", "token_total",
            }
            model_keys = {"model", "model_name", "model_id"}

            found = {"prompt": None, "completion": None, "total": None, "model": None}

            def _as_int(x) -> int:
                try:
                    return int(x)
                except Exception:
                    return 0

            def _as_str(x) -> str:
                return "" if x is None else str(x)

            def _scan(node):
                if isinstance(node, dict):
                    for k, v in node.items():
                        kl = str(k).lower()
                        if kl in prompt_keys and found["prompt"] is None:
                            found["prompt"] = _as_int(v)
                        elif kl in completion_keys and found["completion"] is None:
                            found["completion"] = _as_int(v)
                        elif kl in total_keys and found["total"] is None:
                            found["total"] = _as_int(v)
                        elif kl in model_keys and found["model"] is None:
                            mv = _as_str(v).strip()
                            if mv:
                                found["model"] = mv
                        _scan(v)
                elif isinstance(node, list):
                    for it in node:
                        _scan(it)

            _scan(resp)

            p = found["prompt"] or 0
            c = found["completion"] or 0
            t = found["total"] or 0

            if t <= 0 and (p > 0 or c > 0):
                t = p + c
            if t <= 0:
                return

            resolved_model = (found["model"] or model_name or "Irannobat").strip()

            api_key = ""
            center = "<unknown>"
            try:
                m = Manage.instance()
                if m.is_validated():
                    info = m.ensure_detected()
                    api_key = (info.irannobat_key or "").strip()
                    center = (info.center_display or info.center_code or center).strip()
            except Exception:
                pass

            try:
                add_token_usage_delta(center, resolved_model, t)
            except Exception:
                pass
            if api_key:
                try:
                    add_api_token_usage_delta(
                        api_key=api_key,
                        center_name=center,
                        model_name=resolved_model,
                        tokens_delta=t,
                    )
                except Exception:
                    pass

            try:
                if api_key:
                    m = Manage.instance()
                    if p > 0 or c > 0:
                        m.update_usage(model=resolved_model, prompt_tokens=p, completion_tokens=c)
                    else:
                        m.update_usage_total(model=resolved_model, total_tokens=t)
            except Exception:
                pass

        except Exception:
            return


    def _log_irannobat_transcript_usage(
        self,
        resp: dict | None,
        file_paths: list[str] | None,
    ) -> None:
        """
        FIX: Do NOT use quality_report.criteria.* for duration (it's usually a constant threshold).
        We log usage from local audio duration; response duration is fallback only.
        """
        try:
            import os, re
        except Exception:
            return

        try:
            import soundfile as sf
        except Exception:
            sf = None

        center = (
            getattr(self, "center", None)
            or getattr(self, "center_name", None)
            or getattr(self, "current_center", None)
            or "<unknown>"
        )
        model_name = "irannobat transcriptmodel"

        # Use the same key source as Welcome (avoid mismatch)
        api_key = ""
        try:
            from .api_manager import Manage
            m = Manage.instance()
            api_key = (m.get_irannobat_key() or "").strip() or (m.get_last_api_key() or "").strip()
            try:
                info = m.ensure_detected()
                center = (getattr(info, "center_display", None) or getattr(info, "center_code", None) or center)
            except Exception:
                pass
        except Exception:
            api_key = ""
        if not api_key:
            api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            return

        def _duration_seconds_from_file(path: str) -> float:
            try:
                if not path or not os.path.exists(path):
                    return 0.0

                # soundfile (wav/flac/ogg/…)
                if sf is not None:
                    try:
                        info = sf.info(path)
                        dur = float(getattr(info, "duration", 0.0) or 0.0)
                        if dur > 0:
                            return dur
                        frames = float(getattr(info, "frames", 0.0) or 0.0)
                        sr = float(getattr(info, "samplerate", 0.0) or 0.0)
                        if frames > 0 and sr > 0:
                            return frames / sr
                    except Exception:
                        pass

                # built-in WAV fallback
                if str(path).lower().endswith(".wav"):
                    try:
                        import wave
                        with wave.open(path, "rb") as wf:
                            frames = wf.getnframes()
                            rate = wf.getframerate()
                            if frames > 0 and rate > 0:
                                return float(frames) / float(rate)
                    except Exception:
                        pass

                # optional pydub fallback (mp3/m4a/…)
                try:
                    from pydub import AudioSegment
                    seg = AudioSegment.from_file(path)
                    return float(len(seg)) / 1000.0
                except Exception:
                    return 0.0
            except Exception:
                return 0.0

        # 1) Prefer local duration (REAL duration)
        local_total = 0.0
        if file_paths:
            for p in list(file_paths):
                local_total += _duration_seconds_from_file(p)

        total_seconds = int(round(local_total)) if local_total > 0 else 0

        # 2) Fallback: derive from response, but IGNORE quality_report.criteria
        if total_seconds <= 0:
            resp = resp or {}
            target_keys = {
                "duration", "duration_s", "duration_sec", "duration_secs", "duration_seconds",
                "speech_seconds", "audio_seconds", "seconds",
                "duration_ms", "audio_ms", "speech_ms", "audio_duration_ms", "total_duration_ms",
            }

            def _as_seconds(v) -> float:
                try:
                    if v is None:
                        return 0.0
                    if isinstance(v, (int, float)):
                        x = float(v)
                    elif isinstance(v, str):
                        m = re.search(r"[-+]?\d*\.?\d+", v.strip())
                        if not m:
                            return 0.0
                        x = float(m.group(0))
                    else:
                        return 0.0
                    return (x / 1000.0) if x > 200 else x  # heuristic: big numbers are ms
                except Exception:
                    return 0.0

            def _best_or_sum(node) -> float:
                # dict: take max best duration found (avoid double-count keys)
                # list: sum best duration per item (for per-file lists)
                try:
                    if isinstance(node, dict):
                        best = 0.0
                        for k, vv in node.items():
                            kl = str(k).lower()
                            if kl == "criteria":  # <-- critical: ignore thresholds
                                continue
                            if kl in target_keys:
                                best = max(best, _as_seconds(vv))
                            else:
                                best = max(best, _best_or_sum(vv))
                        return best
                    if isinstance(node, list):
                        return sum(_best_or_sum(it) for it in node)
                    return 0.0
                except Exception:
                    return 0.0

            resp_seconds = _best_or_sum(resp)
            if resp_seconds > 0:
                total_seconds = int(round(resp_seconds))

        if total_seconds <= 0:
            return

        # persist
        try:
            add_transcript_usage_delta(center, model_name, total_seconds)
        except Exception:
            pass
        try:
            add_api_transcript_usage_delta(
                api_key=api_key,
                center_name=center,
                model_name=model_name,
                seconds_delta=total_seconds,
            )
        except Exception:
            pass


    def _refresh_sessions_for_current_study(self):
        self._ensure_sessions_context_menu()
        self.list.clear()

        # fallback
        if not self.study_uid:
            try:
                sessions = U.ai_fetch_all_sessions() or []
            except Exception:
                sessions = []
            sessions = [(sid, title) for (sid, title) in sessions
                        if isinstance(sid, str) and sid.startswith(f"{self.ns}-")]

            self._pinned_sids = self._load_pinned_sids()
            # order pins
            sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}
            cleaned_pins = [p for p in self._pinned_sids if p in sid_to_title]
            if cleaned_pins != self._pinned_sids:
                self._pinned_sids = cleaned_pins
                self._save_pinned_sids(cleaned_pins)

            ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
            pinned_set = set(cleaned_pins)
            ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

            for sid, title in ordered:
                it = QListWidgetItem()
                it.setData(Qt.UserRole, sid)
                self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
                self.list.addItem(it)
            return

        # study-specific
        sessions = U.ai_fetch_sessions_by_study(self.study_uid) or []
        if not sessions:
            sid = f"local-{uuid.uuid4().hex[:8]}"
            U.ai_upsert_session(sid, "New Chat", study_uid=self.study_uid)
            U.ai_set_last_session_for_study(self.study_uid, sid)
            # 2026-08-08: the third mint site — the first chat auto-created for a
            # study. All three now seed, so the invariant is "mint a session ->
            # seed its metadata" with no exceptions to remember.
            self._seed_session_metadata(sid)
            sessions = [(sid, "New Chat")]

        # order pins
        self._pinned_sids = self._load_pinned_sids()
        sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}
        cleaned_pins = [p for p in self._pinned_sids if p in sid_to_title]
        if cleaned_pins != self._pinned_sids:
            self._pinned_sids = cleaned_pins
            self._save_pinned_sids(cleaned_pins)

        ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
        pinned_set = set(cleaned_pins)
        ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

        for sid, title in ordered:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, sid)
            self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
            self.list.addItem(it)

        # select last
        last_sid = U.ai_get_last_session_for_study(self.study_uid)
        if last_sid:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.UserRole) == last_sid:
                    self.list.setCurrentItem(it)
                    self._open_session(it)
                    break
                
    def _make_title_from_text(self, text: str, max_len: int = 28) -> str:
        """
        از اولین خطِ متن، یک عنوان کوتاه می‌سازد.
        اگر طول بیشتر از max_len باشد، با «…» کوتاه می‌کند.
        برای متون فارسی/RTL هم مشکلی ندارد.
        """
        if not text:
            return "New Chat"
        first_line = text.strip().splitlines()[0]
        # حذف فاصله‌های اضافی ابتدا/انتها
        s = first_line.strip()
        return (s if len(s) <= max_len else (s[:max_len].rstrip() + "…"))

    def _html_to_plain_text(self, html: str) -> str:
        """Convert stored bubble HTML to plain text suitable for correction dropdown."""
        s = (html or "").strip()
        if not s:
            return ""
        try:
            from PySide6.QtGui import QTextDocument
            doc = QTextDocument()
            doc.setHtml(s)
            out = (doc.toPlainText() or "").strip()
            return out
        except Exception:
            import re
            return re.sub(r"<[^>]+>", "", s).strip()

    def _encode_image_file_to_base64(self, path: str) -> str | None:
        """Encode an image file to base64 for backend multimodal endpoints."""
        try:
            if not path:
                return None
            ext = os.path.splitext(path)[1].lower()
            # Backend image parser expects standard raster formats.
            allowed_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
            if ext not in allowed_exts:
                self.controller.bubble(
                    "AI ChatBot",
                    f"⚠️ Unsupported image format for backend multimodal API: {os.path.basename(path)}"
                )
                return None
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            self.controller.bubble("AI ChatBot", f"⚠️ Failed to read image attachment: {e}")
            return None

    def _collect_request_images_base64(self) -> list[str]:
        """Collect and encode currently attached images from composer."""
        try:
            if not hasattr(self.composer, "get_all_image_attachments"):
                return []
            paths = self.composer.get_all_image_attachments() or []
        except Exception:
            return []

        encoded: list[str] = []
        for path in paths:
            b64 = self._encode_image_file_to_base64(path)
            if b64:
                encoded.append(b64)
        return encoded


    def _retry_last_send(self):
        """Re-send the last failed user message with its original mode."""
        try:
            if not self._pending_retry:
                return
            mode = self._pending_retry.get("mode")
            text = self._pending_retry.get("text", "")
            images = self._pending_retry.get("images") or []
            bub = self._pending_retry.get("bubble")
            if bub:
                bub.clear_retry()
            # reset so در _append_bubble دوباره bubble نگه‌داری شود
            self._pending_retry = {"mode": mode, "text": text, "images": images, "bubble": None}
            self._send_with_mode(text, mode, retry_images=images)
        except Exception:
            pass

    def _ensure_local_session(self, title_hint: str = "New Chat") -> str:
        import uuid, time
        if self.current_session_id and str(self.current_session_id).startswith("local-"):
            return self.current_session_id

        local_sid = f"{self.ns}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        self.current_session_id = local_sid
        self.sessions.setdefault(local_sid, [])

        it = QListWidgetItem(self._make_title_from_text(title_hint or "New Chat", max_len=28))
        it.setData(Qt.UserRole, local_sid)
        self.list.insertItem(0, it)
        self.list.setCurrentItem(it)

        try:
            # ⬅️ study_uid هم ذخیره می‌شود
            U.ai_upsert_session(local_sid, title_hint or "New Chat", self.study_uid)
            if self.study_uid:
                U.ai_set_last_session_for_study(self.study_uid, local_sid)
            else:
                U.ai_set_last_session(local_sid)
        except Exception:
            pass

        # 2026-08-08: seed case metadata HERE too. `_new_session` (the "New chat"
        # button) already did, but THIS is the path that mints a session during
        # normal reporting — `report-<epoch>-<hex6>`, the format of every session
        # in the database. Seeding therefore never ran in the real workflow and
        # `ai_session_meta` was never even created. Same swallowed, local-only
        # call: it cannot stop a session from being created.
        self._seed_session_metadata(local_sid)
        self._sync_metadata_card(local_sid)

        return local_sid

    def _standardize_now(self, text: str):
        """
        Standardize current text and show both EN/FA in Standard tab.

        Fixes:
        - Use the real text to send (to_send), not the raw 'text' arg.
        - Support BOTH response schemas:
            A) {"standardize_output_english": "<json>", "standardize_output_persian": "<json>", ...}
            B) {"content": {... or "<json>"}, "usage": {...}}
        - If final_report is missing but cleaned_sentences_* exists, join them.
        - ✅ Robustness: if server swaps EN/FA occasionally, detect by charset and auto-swap.
        - ✅ Persist BOTH langs (text_en/text_fa) so reload never mixes them.
        """
        import json, re

        std_text, tr_text = self.composer.get_tab_texts()
        to_send = (tr_text or text or "").strip()
        if not to_send:
            print("[Standardize] blocked: empty text")
            self.controller.bubble("AI ChatBot", "⚠️ <i>No text to standardize.</i>")
            return
        print(f"[Standardize] sending text_len={len(to_send)}")

        def _strip_fences(s: str) -> str:
            s = (s or "").strip()
            s = re.sub(r"^\s*```(?:json)?\s*", "", s, flags=re.I)
            s = re.sub(r"\s*```\s*$", "", s)
            return s.strip()

        def _try_json(x):
            if x is None:
                return None
            if isinstance(x, (dict, list)):
                return x
            if not isinstance(x, str):
                return x
            s = _strip_fences(x)
            if not s:
                return ""
            try:
                return json.loads(s)
            except Exception:
                return s  # raw string

        def _looks_persian(s: str) -> bool:
            s = s or ""
            return bool(re.search(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]", s))

        def _looks_english(s: str) -> bool:
            s = s or ""
            return bool(re.search(r"[A-Za-z]", s)) and not _looks_persian(s)

        def _unpack_raw_outputs(resp: dict):
            """
            Returns: (en_raw, fa_raw) where each can be dict/list/str.
            """
            if not isinstance(resp, dict):
                return resp, resp

            # Schema A
            if ("standardize_output_english" in resp) or ("standardize_output_persian" in resp):
                return resp.get("standardize_output_english", "{}"), resp.get("standardize_output_persian", "{}")

            # Schema B
            content = resp.get("content", None)
            content = _try_json(content)

            if isinstance(content, dict):
                if ("english" in content) or ("persian" in content):
                    return content.get("english", ""), content.get("persian", "")
                if ("cleaned_sentences_english" in content) or ("cleaned_sentences_persian" in content):
                    return content, content
                if "final_report" in content:
                    return content, content

            if ("cleaned_sentences_english" in resp) or ("cleaned_sentences_persian" in resp) or ("final_report" in resp):
                return resp, resp

            return content if content is not None else resp, content if content is not None else resp

        def _extract_display_text(raw_output, lang: str) -> str:
            """
            lang: 'en' or 'fa'
            """
            obj = _try_json(raw_output)

            if isinstance(obj, str):
                return obj.strip()

            if isinstance(obj, list):
                parts = [str(x).strip() for x in obj if str(x).strip()]
                return "\n".join(parts).strip()

            if isinstance(obj, dict):
                if lang == "en" and "english" in obj:
                    return _extract_display_text(obj["english"], "en")
                if lang == "fa" and "persian" in obj:
                    return _extract_display_text(obj["persian"], "fa")

                base = ""
                final = obj.get("final_report", None)
                if isinstance(final, str) and final.strip():
                    base = final.replace("\\n", "\n").strip()
                else:
                    arr = obj.get("cleaned_sentences_english" if lang == "en" else "cleaned_sentences_persian", None)
                    if isinstance(arr, list):
                        parts = [str(x).strip() for x in arr if str(x).strip()]
                        base = "\n".join(parts).strip()

                if lang == "en":
                    impr = obj.get("impression_english", None)
                    reco = obj.get("recommendation_english", None)
                    impr_label = "Impression"
                    reco_label = "Recommendations"
                else:
                    impr = obj.get("impression_persian", None)
                    reco = obj.get("recommendation_persian", None)
                    impr_label = "نتیجه‌گیری"
                    reco_label = "توصیه‌ها"

                def _join_block(x):
                    if x is None:
                        return ""
                    if isinstance(x, list):
                        xs = [str(t).strip() for t in x if str(t).strip()]
                        return "\n".join(xs).strip()
                    if isinstance(x, str):
                        return x.strip()
                    return str(x).strip()

                impr_txt = _join_block(impr)
                reco_txt = _join_block(reco)

                extra = []
                if impr_txt:
                    extra.append(f"{impr_label}:\n{impr_txt}")
                if reco_txt:
                    extra.append(f"{reco_label}:\n{reco_txt}")

                if extra:
                    base = (base.strip() + "\n\n" + "\n\n".join(extra)).strip() if base else "\n\n".join(extra).strip()

                return base.strip()

            return ""

        def work():
            backend, _center_name, center_key = _resolve_active_ai_identity()
            if not center_key:
                print("[Standardize] blocked: AI backend not configured")
                raise RuntimeError("❌ AI backend is not configured. Please complete EchoMind Settings.")

            if self.page_mode in ("Assist", "Search") and callable(globals().get("standard_assist_search", None)):
                _log.debug("[Standardize] using standard_assist_search")
                return _ai_module(backend).standard_assist_search(
                    user_msg=to_send, CENTER_Key=center_key
                )
            _log.debug("[Standardize] using standardize")
            return _ai_module(backend).standardize(user_msg=to_send, CENTER_Key=center_key)

        def ok(resp: dict):
            print(f"\n{'='*80}")
            print("[STD] ✅ SUCCESS - Response received")
            print(f"{'='*80}")
            print(f"[STD] Response keys: {list(resp.keys()) if isinstance(resp, dict) else type(resp)}")

            en_raw, fa_raw = _unpack_raw_outputs(resp)

            en_final_text = _extract_display_text(en_raw, "en")
            fa_final_text = _extract_display_text(fa_raw, "fa")

            if not en_final_text and not fa_final_text:
                raw_preview = ""
                try:
                    raw_preview = json.dumps(resp, ensure_ascii=False)[:1200]
                except Exception:
                    raw_preview = str(resp)[:1200]
                self.controller.bubble(
                    "AI ChatBot",
                    "⚠️ <i>Standardization returned empty output.</i>\n\n"
                    f"<pre>{raw_preview}</pre>"
                )
                return

            # ---------------------------
            # ✅ AUTO-SWAP if server mixed EN/FA
            # ---------------------------
            en_is_fa = _looks_persian(en_final_text)
            fa_is_fa = _looks_persian(fa_final_text)
            en_is_en = _looks_english(en_final_text)
            fa_is_en = _looks_english(fa_final_text)

            # Case 1: both present but swapped by charset
            if en_final_text and fa_final_text and en_is_fa and fa_is_en:
                print("[STD] ⚠️ Detected swapped EN/FA by charset -> swapping.")
                en_final_text, fa_final_text = fa_final_text, en_final_text
                en_raw, fa_raw = fa_raw, en_raw

            # Case 2: only one present but clearly belongs to the other slot
            elif en_final_text and not fa_final_text and en_is_fa:
                print("[STD] ⚠️ EN slot contains Persian while FA empty -> moving to FA.")
                fa_final_text, en_final_text = en_final_text, ""
                fa_raw, en_raw = en_raw, ""
            elif fa_final_text and not en_final_text and fa_is_en:
                print("[STD] ⚠️ FA slot contains English while EN empty -> moving to EN.")
                en_final_text, fa_final_text = fa_final_text, ""
                en_raw, fa_raw = fa_raw, ""

            # (If both are Persian or both are English, we don't guess; we keep as-is.)

            # --- set into composer (both langs) ---
            self.composer.set_standard_result(en_text=en_final_text, fa_text=fa_final_text)
            self.composer._is_standardized = True
            self.composer.switch_tab("standard")

            # --- persist: ✅ store BOTH langs so EN/FA never collapse after reload ---
            preferred_lang = getattr(self.composer, "_std_lang", "pa")
            text_to_persist = fa_final_text if preferred_lang == "pa" and fa_final_text else (en_final_text or "")

            try:
                self._persist_standard(
                    text_to_persist,
                    text_en=en_final_text,
                    text_fa=fa_final_text,
                    raw=json.dumps({"en": en_raw, "fa": fa_raw}, ensure_ascii=False),
                    parsed={"english": _try_json(en_raw), "persian": _try_json(fa_raw)},
                )
            except Exception as e:
                print(f"[STD-PERSIST] ❌ Persist failed: {type(e).__name__}: {e}")

            print(f"\n{'='*80}")
            print("[STD] ✅✅✅ STANDARDIZATION COMPLETE")
            print(f"{'='*80}\n")

        def er(msg: str):
            print(f"\n{'='*80}")
            print(f"[STD] ❌❌❌ ERROR: {msg}")
            print(f"{'='*80}\n")
            self.controller.bubble("AI ChatBot", f"⚠️ <i>{msg}</i>")

        QTimer.singleShot(
            0,
            lambda: self._run_async(
                work, ok, er,
                lock_btn=getattr(self, "composer", None) and getattr(self.composer, "btn_send", None),
                typing="Standardizing…"
            )
        )

    def _load_from_db_and_render(self) -> bool:
        loaded_any = False
        self._ensure_sessions_context_menu()

        try:
            try:
                U.ai_backfill_sessions_from_messages()
            except Exception:
                pass

            # 1) sessions
            try:
                if getattr(self, "study_uid", None):
                    sessions = U.ai_fetch_sessions_by_study(self.study_uid) or []
                else:
                    sessions = U.ai_fetch_all_sessions() or []

                # keep only our namespace sessions (e.g. "AIChat-...")
                try:
                    sessions = [(sid, title) for (sid, title) in (sessions or [])
                                if isinstance(sid, str) and sid.startswith(f"{self.ns}-")]
                except Exception:
                    sessions = []
            except Exception:
                sessions = []

            # 1.5) apply pin ordering (persist pins under AI-Chat)
            self._pinned_sids = self._load_pinned_sids()
            sid_to_title = {sid: (title or "New Chat") for sid, title in sessions}
            cleaned_pins = [p for p in self._pinned_sids if p in sid_to_title]
            if cleaned_pins != self._pinned_sids:
                self._pinned_sids = cleaned_pins
                self._save_pinned_sids(cleaned_pins)

            ordered = [(sid, sid_to_title[sid]) for sid in cleaned_pins]
            pinned_set = set(cleaned_pins)
            ordered += [(sid, title) for sid, title in sessions if sid not in pinned_set]

            # 2) reset UI/cache
            self.sessions = {}
            self.list.clear()
            self.history.clear()

            # 3) build list
            # ── 2026-07-31: this loop used to be an N+1 ───────────────────────
            # It called `ai_fetch_messages_full(sid)` for EVERY session — a
            # `SELECT id, who, html, origin` with no LIMIT — to fill
            # `self.sessions[sid]` and to set `loaded_any`. With 40 sessions x
            # 30 messages x ~15 KB of report HTML that is ~18 MB read and
            # retained over 40+ sequential round-trips, inside the mode
            # button's click handler, before the first bubble paints — to
            # display exactly ONE session.
            #
            # And the payload was never used: every read of `self.sessions` in
            # this file wants the KEYS (membership at "last in self.sessions",
            # the first-key fallback) or appends to it. `_open_session` refetches
            # the messages it renders anyway.
            #
            # One GROUP BY replaces the whole loop's I/O.
            try:
                _msg_counts = U.ai_count_messages_by_session() or {}
            except Exception:
                _msg_counts = {}

            for sid, title in ordered:
                # keys only — the message bodies are fetched on demand by
                # `_open_session`, which is the only thing that renders them.
                self.sessions[sid] = []
                if _msg_counts.get(sid):
                    loaded_any = True

                it = QListWidgetItem()
                it.setData(Qt.UserRole, sid)
                self._apply_item_title_and_style(it, title or "New Chat", sid=sid)
                self.list.addItem(it)

            # 4) pick target
            try:
                if getattr(self, "study_uid", None):
                    last = U.ai_get_last_session_for_study(self.study_uid)
                else:
                    last = U.ai_get_last_session()
            except Exception:
                last = None

            target_sid = None
            if last and (last in self.sessions):
                target_sid = last
            elif self.sessions:
                target_sid = next(iter(self.sessions.keys()))

            if not target_sid:
                self.current_session_id = None
                self.controller.reset_session()
                return loaded_any

            # 5) select item
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.UserRole) == target_sid:
                    self.list.setCurrentItem(it)
                    break

            # 6) set current sid
            self.current_session_id = target_sid
            self.controller.switch_session(target_sid)

            # 7) load reports (raw EN) -> correction dropdown + attach to report bubbles
            report_map: dict[int, str] = {}
            report_list: list[str] = []
            try:
                fn = getattr(U, "ai_fetch_reports_for_session", None)
                if callable(fn):
                    for _, msg_id, _, raw_en, _ in (fn(target_sid) or []):
                        if isinstance(raw_en, str) and raw_en.strip():
                            report_list.append(raw_en)
                        try:
                            if msg_id is not None:
                                report_map[int(msg_id)] = raw_en
                        except Exception:
                            pass
            except Exception:
                pass

            try:
                self.composer.clear_correction_reports()
                for raw in report_list:
                    self.composer.register_correction_report(raw)
            except Exception:
                pass

            # 8) render bubbles
            self.history.clear()
            try:
                rows = U.ai_fetch_messages_full(target_sid)
            except Exception:
                rows = []

            for msg_id, who, html, origin in rows:
                if not html:
                    continue
                is_user = who.strip().lower().startswith("you")
                # Enable buttons for all reports (not just origin=="report"), read from database
                on_edit = self._edit_bubble if (origin in ("report", "assistant") and not is_user) else None
                on_persian = self._persian_bubble if (origin in ("report", "assistant") and not is_user) else None
                # Enable send_to_reception for all non-user messages that have content
                on_send_reception = self._send_to_reception if (not is_user and html) else None

                b = self.history.add_bubble(who, html, on_edit=on_edit, on_persian=on_persian, on_send_reception=on_send_reception)
                b._origin = origin 
                try:
                    b._msg_id = int(msg_id)
                except Exception:
                    b._msg_id = msg_id

                # ✅ attach raw JSON to report bubbles so Persian/Edit works for old sessions
                try:
                    if origin == "report" and (not is_user):
                        raw = report_map.get(int(msg_id))
                        if raw:
                            b.raw_report_json = raw
                except Exception:
                    pass

            return loaded_any

        except Exception:
            return loaded_any

    def _propagate_reception_status_to_pacs(self, new_status: str, send_mode):
        """Mirror the Send-to-Reception status onto the PACS status pipeline.

        Reuses the SAME mechanism as the patient sync workflow (socket
        ``update_report_status``) — no new status pipeline. Only runs when
        the report was sent for the CURRENT study (``send_mode == "current"``);
        sending to another reception ID must never touch this study's status.
        Best-effort: failures are logged, never raised.
        """
        import logging
        import threading
        logger = logging.getLogger(__name__)

        if send_mode != "current":
            return
        study_uid = str(getattr(self, "study_uid", "") or "").strip()
        if not study_uid:
            return
        try:
            from modules.network.socket_report_status_service import VALID_STATUSES
            if new_status not in VALID_STATUSES:
                logger.warning(
                    f"[RECEPTION_SERVER] Invalid status {new_status!r}; PACS sync skipped"
                )
                return
        except Exception:
            return

        # Prefer the owning patient widget's pipeline (it also refreshes the
        # toolbar badge and the home table, and runs off the GUI thread).
        widget = self.parent()
        while widget is not None and not (
            hasattr(widget, "_change_report_status") and hasattr(widget, "study_uid")
        ):
            widget = widget.parent()
        if widget is not None and str(getattr(widget, "study_uid", "") or "") == study_uid:
            old_status = str(getattr(widget, "report_status", "pending") or "pending")
            if old_status != new_status:
                logger.info(
                    f"[RECEPTION_SERVER] PACS status via patient widget: "
                    f"{old_status} -> {new_status} (study={study_uid})"
                )
                widget._change_report_status(
                    study_uid=study_uid,
                    old_status=old_status,
                    new_status=new_status,
                    comment="",
                )
            return

        # Fallback: direct socket status service, off the GUI thread.
        def _update():
            try:
                from modules.network.socket_report_status_service import (
                    get_report_status_service,
                )
                service = get_report_status_service()
                service.update_report_status(study_uid, new_status)
                logger.info(
                    f"[RECEPTION_SERVER] PACS status updated via service: "
                    f"{new_status} (study={study_uid})"
                )
            except Exception as exc:
                logger.warning(f"[RECEPTION_SERVER] PACS status sync failed: {exc}")

        threading.Thread(target=_update, daemon=True).start()

    def _send_to_reception(self, bubble: "MessageBubble"):
        """Send report to reception - reads from database for persistence."""
        import logging
        from datetime import datetime
        logger = logging.getLogger(__name__)
        
        # Print to console for visibility
        print("\n" + "="*100)
        print("🔴 USER CLICKED 'SEND TO RECEPTION' BUTTON")
        print("="*100)
        print(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
        
        # Logging
        logger.info("\n" + "="*100)
        logger.info("🔴 USER CLICKED 'SEND TO RECEPTION' BUTTON")
        logger.info("="*100)
        logger.info(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
        logger.info(f"Study UID: {self.study_uid}")
        
        # Get HTML from bubble
        html_content = ""
        try:
            html_content = (bubble.get_html() or "").strip()
            logger.info("HTML content extracted: %d characters", len(html_content))
        except Exception as e:
            print(f"❌ Error extracting HTML: {e}")
            logger.error(f"❌ Error extracting HTML: {e}")
            return

        # The OUTGOING copy is built here, on the GUI thread, because it reads
        # the bubble's font (see F1: the worker must not touch a Qt object).
        #
        # `get_html()` returns the hand-built markup, where the assistant
        # renderer and the RTL wrapper keep their styling in `<style>` blocks
        # addressed by CSS class. `prepare_report_html_for_server()` is
        # inline-only by contract and strips those, which is why colours, fonts
        # and sizes vanished on the way to Reception while the Medical Report
        # Editor — which sends fully-inline `QTextEdit.toHtml()` — kept them.
        # `get_export_html()` produces that same fully-inline shape.
        # The LOCAL DB copy below deliberately still stores `html_content`.
        try:
            server_source = (bubble.get_export_html() or "").strip() or html_content
        except Exception as exc:
            logger.warning("[RECEPTION_SERVER] export HTML failed; using raw: %s", exc)
            server_source = html_content

        if not html_content:
            print("❌ Report content is empty!")
            logger.error("❌ Report content is empty!")
            themed_message_box(self, QMessageBox.Icon.Warning, "Error", "Report content is empty!")
            return

        # Get patient ID from database
        print("\n📊 Fetching patient information from database...")
        logger.info("📊 Fetching patient information from database...")
        
        patient_id = None
        if self.study_uid:
            try:
                from PacsClient.utils import db_manager as db

                study_data = db.get_study_by_study_uid(self.study_uid)
                if study_data:
                    patient_fk = study_data.get('patient_fk')
                    print(f"✅ Found - patient_fk: {patient_fk}")
                    logger.info(f"✅ Found - patient_fk: {patient_fk}")
                    
                    if patient_fk:
                        patient_data = db.get_patient_by_patient_pk(patient_fk)
                        if patient_data:
                            patient_id = patient_data.get('patient_id') or patient_data.get('patient_pk')
                            print(f"✅ Patient ID from database: {patient_id}")
                            logger.info(f"✅ Patient ID from database: {patient_id}")
            except Exception as e:
                print(f"❌ Error fetching patient: {e}")
                logger.error(f"❌ Error fetching patient: {e}")

        # Let the user confirm the current patient or enter a different
        # reception ID before the report is sent.
        current_patient_id = (patient_id or "").strip() or None
        # Prefill the status combo with the current study's PACS status.
        current_status = None
        try:
            _w = self.parent()
            while _w is not None and not hasattr(_w, "report_status"):
                _w = _w.parent()
            if _w is not None:
                current_status = str(getattr(_w, "report_status", "") or "") or None
        except Exception:
            current_status = None
        dialog = _ReceptionIdDialog(self, current_patient_id, current_status=current_status)
        if dialog.exec() != QDialog.Accepted:
            logger.info("Reception send: patient selection canceled by user.")
            return

        patient_id = (dialog.selected_patient_id or "").strip()
        selected_status = str(getattr(dialog, "selected_status", "") or "pending")
        send_mode = getattr(dialog, "mode", None)
        if not patient_id:
            logger.error("Reception send: no reception ID selected.")
            themed_message_box(
                self,
                QMessageBox.Icon.Warning,
                "Reception ID Required",
                "A reception ID is required to send the report.",
            )
            return

        # ── F1 (2026-07-28): this runs on a WORKER thread ────────────────────
        # It used to run inline on the GUI thread and issue a 20 s GET plus a
        # 30 s POST plus a DB write, with no spinner, no wait cursor and no
        # cancel — so a slow or unreachable reception server froze the whole
        # workstation for up to ~50 s ("Not Responding").
        #
        # THE RULE THAT MAKES THIS SAFE: **this function must not touch a single
        # Qt object.** It therefore no longer calls `themed_message_box` and no
        # longer calls `_propagate_reception_status_to_pacs` (that helper walks
        # `self.parent()` and may invoke `widget._change_report_status`, i.e.
        # GUI work). Instead it RETURNS a description of what should be shown /
        # done, and `_deliver_reception_result` — which always runs on the GUI
        # thread, in both the async and the legacy path — performs it.
        #
        # Return contract: {"ok": bool, "icon", "title", "text",
        #                   "propagate": (status, send_mode) | None}
        def _send_with_patient_id(target_patient_id: str) -> dict:
            patient_validated = False
            propagate_request = None
            try:
                # Reception/Workflow API base URL - configurable, not hard-coded.
                from modules.network.reception_api_config import get_reception_api_base_url
                base_url = get_reception_api_base_url()
                validate_url = f"{base_url}/api/pacs/patients/{target_patient_id}"
                masked_url = "http://<host>/api/pacs/patients/<patient_id>"
                masked_id = "<patient_id>"
                t0 = time.perf_counter()
                logger.info(f"[RECEPTION_SERVER] → GET {masked_url} id={masked_id}")
                response = requests.get(validate_url, timeout=20)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                logger.info(
                    f"[RECEPTION_SERVER] ← status={response.status_code} elapsed_ms={elapsed_ms} content_type={response.headers.get('Content-Type')} content_length={response.headers.get('Content-Length')}"
                )

                if not response.ok:
                    logger.warning("[RECEPTION_SERVER] ❌ Patient ID not found: <patient_id>")
                    return {
                        "ok": False,
                        "icon": QMessageBox.Icon.Warning,
                        "title": "Patient ID Not Found",
                        "text": "The patient ID was not found on the server.\nPlease check and try again.",
                    }

                patient_validated = True
                try:
                    response_json = response.json()
                    logger.info(f"[RECEPTION_SERVER]   patient_json_keys={list(response_json.keys()) if isinstance(response_json, dict) else type(response_json)}")
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"[RECEPTION_SERVER] ❌ Patient validation failed: {e}")
                return {
                    "ok": False,
                    "icon": QMessageBox.Icon.Warning,
                    "title": "Patient ID Validation Failed",
                    "text": "Unable to validate the patient ID with the server.\nPlease try again.",
                }

            # Save to database
            # 2026-07-31 — the stdout copies are dropped; the logger below is
            # the one diagnostic channel, and it is rotated and access-controlled.
            logger.info(f"💾 Saving report to database...")
            logger.info(f"   Patient ID: {target_patient_id}")

            try:
                session_id = self.controller.session_id if hasattr(self, 'controller') else None
                msg_id = getattr(bubble, '_msg_id', None)
                modality = getattr(self, '_current_modality', 'Unknown')
                sender_info = f"Modality: {modality}, Mode: {getattr(self, 'page_mode', 'Report')}"

                print(f"   Session ID: {session_id}")
                print(f"   Message ID: {msg_id}")
                print(f"   Modality: {modality}")
                logger.info(f"   Session ID: {session_id}")
                logger.info(f"   Message ID: {msg_id}")
                logger.info(f"   Modality: {modality}")

                # Call save function
                print(f"→ Calling ai_save_reception_report...")
                logger.info(f"→ Calling ai_save_reception_report...")

                report_id = ai_save_reception_report(
                    patient_id=target_patient_id,
                    html_content=html_content,
                    study_uid=self.study_uid or target_patient_id,
                    session_id=session_id,
                    msg_id=msg_id,
                    sender_info=sender_info
                )

                if report_id:
                    # --- Send to Reception Server (same server) ---
                    server_sent = False
                    server_status = None
                    server_message = "Not sent"
                    try:
                        from modules.network.socket_token_manager import get_socket_token_manager

                        token_manager = get_socket_token_manager()
                        token = token_manager.get_token() if token_manager else None

                        if not token:
                            server_message = "Missing auth token"
                            logger.warning("[RECEPTION_SERVER] ❌ Missing auth token; skipping server send")
                        else:
                            # Reception/Workflow API base URL - configurable, not hard-coded.
                            from modules.network.reception_api_config import get_reception_api_base_url
                            base_url = get_reception_api_base_url()
                            url = f"{base_url}/api/pacs/update-report"

                            reception_id = target_patient_id
                            try:
                                reception_id = int(target_patient_id) if str(target_patient_id).isdigit() else target_patient_id
                            except Exception:
                                reception_id = target_patient_id

                            # Normalize the OUTGOING HTML only (local DB save
                            # above keeps the original): inline styles, per-
                            # block RTL/LTR dir + alignment, LRM fix — so the
                            # server preserves EchoMind formatting and renders
                            # Persian RTL / English LTR correctly. See
                            # PacsClient/utils/report_server_html.py.
                            try:
                                from PacsClient.utils.report_server_html import (
                                    prepare_report_html_for_server,
                                )
                                server_html = prepare_report_html_for_server(server_source)
                            except Exception as exc:
                                logger.warning(
                                    f"[RECEPTION_SERVER] HTML normalization failed; sending raw: {exc}"
                                )
                                server_html = server_source

                            payload = {
                                "receptionId": reception_id,
                                "content": server_html,
                                "findings": server_html,
                                "status": selected_status,
                            }

                            # Send approvalFlags consistent with the chosen
                            # status — INO renders the patient/report status from
                            # report.approvalFlags, not the raw status string, so
                            # a downgrade otherwise doesn't reflect. Flag-gated
                            # (AIPACS_UPDATE_REPORT_APPROVAL_FLAGS, default ON).
                            try:
                                from modules.network.socket_report_status_service import (
                                    UPDATE_REPORT_APPROVAL_FLAGS,
                                    approval_flags_for_status,
                                )
                                if UPDATE_REPORT_APPROVAL_FLAGS:
                                    payload["approvalFlags"] = approval_flags_for_status(selected_status)
                            except Exception:
                                pass

                            logger.info(f"[RECEPTION_SERVER] → POST {url}")
                            logger.info(
                                f"[RECEPTION_SERVER]   receptionId={reception_id}, "
                                f"content_len={len(server_html)}, status={selected_status}"
                            )

                            response = requests.post(
                                url,
                                json=payload,
                                headers={
                                    "Content-Type": "application/json",
                                    "Authorization": f"Bearer {token}",
                                },
                                timeout=30,
                            )

                            server_status = response.status_code
                            response_text = (response.text or "").strip()

                            logger.info(f"[RECEPTION_SERVER] ← status={server_status}")
                            try:
                                logger.info(f"[RECEPTION_SERVER]   headers={dict(response.headers)}")
                            except Exception:
                                pass
                            if response_text:
                                # F8: was a 2000-char dump of the echoed report.
                                logger.info(
                                    "[RECEPTION_SERVER]   body_bytes=%d", len(response_text)
                                )

                            response_json = None
                            try:
                                response_json = response.json()
                                # F8: the reception response echoes report
                                # content — log the SHAPE, not the body.
                                logger.info(
                                    "[RECEPTION_SERVER]   json_keys=%s",
                                    sorted(response_json.keys())
                                    if isinstance(response_json, dict)
                                    else type(response_json).__name__,
                                )
                            except Exception:
                                response_json = None

                            if response.ok and (response_json is None or response_json.get("success", True)):
                                server_sent = True
                                server_message = (response_json or {}).get("message", "OK") if response_json else "OK"
                                # Mirror the chosen status onto the PACS
                                # report-status pipeline (same mechanism as
                                # the patient sync workflow).
                                #
                                # DEFERRED TO THE GUI THREAD (F1): the helper
                                # walks `self.parent()` and may call
                                # `widget._change_report_status(...)`. Doing that
                                # from this worker thread would be a Qt
                                # violation. The request is handed back and
                                # `_deliver_reception_result` performs it.
                                propagate_request = (selected_status, send_mode)
                                # Sync the INO reception APPROVAL FLAGS to match
                                # the status. update-report only writes
                                # report.status; INO shows the patient state from
                                # report.approvalFlags, set by a SEPARATE workflow
                                # endpoint (resolve workflow id → PATCH
                                # approval-flags). Fire-and-forget, best-effort.
                                try:
                                    from modules.network.ino_report_workflow import (
                                        sync_report_approval_for_status_async,
                                    )
                                    sync_report_approval_for_status_async(
                                        reception_id, selected_status
                                    )
                                except Exception:
                                    pass
                            else:
                                server_message = (response_json or {}).get("message", response_text[:200]) if response_text else "Server error"

                    except Exception as e:
                        server_message = f"Exception: {e}"
                        logger.error(f"[RECEPTION_SERVER] ❌ Exception while sending: {e}")

                    # 2026-07-31 — stdout copies dropped (see the logger block
                    # just below, which records the same fields).

                    logger.info("="*100)
                    logger.info("✅ ✅ ✅ SUCCESS! Report saved to database")
                    logger.info("="*100)
                    logger.info(f"📌 Report ID: {report_id}")
                    logger.info(f"👤 Patient ID: {target_patient_id}")
                    logger.info(f"🔬 Modality: {modality}")
                    logger.info(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
                    logger.info("="*100)

                    return {
                        "ok": True,
                        "icon": QMessageBox.Icon.Information,
                        "title": "✅ Report Saved Successfully",
                        "text": (
                            f"📝 The report has been saved successfully.\n\n"
                            f"📌 Report ID: {report_id}\n"
                            f"👤 Patient ID: {target_patient_id}\n"
                            f"⏱️ Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            f"📨 Status:\n"
                            f"• Saved to database\n"
                            f"• Patient ID validated: {'✅' if patient_validated else '❌'}\n"
                            f"• Sent to reception: {'✅' if server_sent else '❌'}\n"
                            f"• Server status: {server_status if server_status is not None else 'N/A'}\n"
                        ),
                        "propagate": propagate_request,
                    }

                print("\n" + "="*100)
                print("❌ ❌ ❌ FAILED! Database save failed")
                print("="*100 + "\n")

                logger.error("="*100)
                logger.error("❌ ❌ ❌ FAILED! Database save failed")
                logger.error("="*100)

                return {
                    "ok": False,
                    "icon": QMessageBox.Icon.Warning,
                    "title": "Error",
                    "text": "Failed to save report!",
                }

            except Exception as e:
                print("\n" + "="*100)
                print(f"❌ ❌ ❌ Exception Occurred!")
                print(f"Error: {str(e)}")
                print("="*100 + "\n")

                logger.error("="*100)
                logger.error(f"❌ ❌ ❌ Exception Occurred!")
                logger.error(f"Error: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                logger.error("="*100)

                return {
                    "ok": False,
                    "icon": QMessageBox.Icon.Critical,
                    "title": "Error",
                    "text": f"Error: {str(e)}",
                }

        # ── GUI-thread consumer, shared by BOTH paths ────────────────────────
        def _deliver_reception_result(result) -> None:
            """Perform the GUI work the worker deliberately did not do.

            Runs on the GUI thread in both modes: as the `_run_async` success
            callback when threaded, and inline when the kill switch is set.
            """
            if not isinstance(result, dict):
                _set_bubble_status("Failed", "❌", "#ff6b6b")
                return
            if result.get("ok"):
                _set_bubble_status("Sent", "✅", "#5cd18e")
            else:
                _set_bubble_status("Failed", "❌", "#ff6b6b")
            propagate = result.get("propagate")
            if propagate:
                try:
                    self._propagate_reception_status_to_pacs(propagate[0], propagate[1])
                except Exception as exc:
                    logger.warning(f"[RECEPTION_SERVER] PACS status sync skipped: {exc}")
            title = result.get("title")
            if title:
                themed_message_box(
                    self,
                    result.get("icon", QMessageBox.Icon.Information),
                    title,
                    str(result.get("text") or ""),
                )

        # 2026-07-31 — `update_reception_status` / `reset_reception_status`
        # were written, styled and wired to a real QLabel on the bubble, and had
        # ZERO call sites. The progress bubble sits at the bottom of the chat,
        # which the user may have scrolled away from; this is the feedback that
        # appears next to the button they actually pressed.
        def _set_bubble_status(status: str, icon: str, color: str) -> None:
            try:
                bubble.update_reception_status(status, icon, color)
            except Exception:
                pass

        _set_bubble_status("Sending…", "⏳", "#ffb366")

        if _reception_send_async_enabled():
            # Off the GUI thread. `_run_async` also shows a progress bubble,
            # locks the composer for the duration, and registers the worker in
            # `self._workers` so the close-while-in-flight teardown
            # (`cleanup()` / `_ORPHANED_WORKERS`) can detach it safely.
            def _reception_error(msg: str) -> None:
                _set_bubble_status("Failed", "❌", "#ff6b6b")
                themed_message_box(
                    self,
                    QMessageBox.Icon.Critical,
                    "Send to Reception Failed",
                    str(msg or "The report could not be sent."),
                )

            # ── 2026-07-31 ───────────────────────────────────────────────
            # `lock_btn` disables the button for the duration and re-enables it
            # in `cleanup()`. It was never passed, so the ONE control the user
            # had just pressed stayed live for the whole 20 s GET + 30 s POST:
            # a second click re-opened the reception-ID dialog and started a
            # second send, giving reception two records for one study.
            #
            # `cancel_text` is honest: this work writes to the reception server
            # AND the local DB, and an in-flight request cannot be interrupted.
            self._run_async(
                lambda: _send_with_patient_id(patient_id),
                _deliver_reception_result,
                _reception_error,
                lock_btn=getattr(bubble, "btnSendReception", None),
                typing="Sending to reception…",
                cancel_text=(
                    "⏹️ <i>Stopped waiting for reception. The send may already "
                    "have completed on the server — check reception before "
                    "sending again, or you may create a duplicate report.</i>"
                ),
            )
            return

        # Kill switch: fully synchronous, exactly as before this fix.
        _deliver_reception_result(_send_with_patient_id(patient_id))

    def _persian_bubble(self, bubble: "MessageBubble"):
        import logging
        from datetime import datetime
        logger = logging.getLogger(__name__)
        
        print("\n" + "="*100)
        print("🔵 USER CLICKED 'PERSIAN TRANSLATE' BUTTON")
        print("="*100)
        print(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")
        
        logger.info("\n" + "="*100)
        logger.info("🔵 USER CLICKED 'PERSIAN TRANSLATE' BUTTON")
        logger.info("="*100)
        logger.info(f"⏱️  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')}")

        origin = getattr(bubble, "_origin", None)
        is_assistant = (origin == "assistant")

        # server-side session (فعلاً نگه می‌داریم برای سازگاری)
        server_sid = self.controller.session_id
        modality = getattr(self, "_current_modality", None)

        # ─────────────────────────────────────────────
        # 1) Get the EN payload from this bubble (RAW if exists, else from HTML snapshot)
        # ─────────────────────────────────────────────
        english_payload = ""
        src = ""

        # ✅ FIX: For assistant bubbles, prefer the exact assistant text stored in raw_report_json.
        #         For report bubbles, prefer raw_report_json if available.
        if is_assistant:
            # Assistant => MUST send the exact assistant text (no HTML extraction)
            raw = getattr(bubble, "raw_report_json", None)
            if isinstance(raw, str) and raw.strip():
                raw_text = raw.strip()
                parsed = None
                try:
                    parsed = self._parse_assistant_dict(raw_text)
                except Exception:
                    parsed = None

                # If the payload is JSON-like/structured, translate the rendered assistant text
                if isinstance(parsed, dict) and not (len(parsed) == 1 and "Raw" in parsed):
                    try:
                        rendered_html = self._render_assistant_html(parsed)
                        plain = extract_plain_text_from_html(rendered_html).strip()
                    except Exception:
                        plain = ""

                    if plain:
                        english_payload = plain
                        src = "assistant_rendered_text [from raw_json]"
                    else:
                        english_payload = raw_text
                        src = "bubble.raw_report_json [assistant]"
                else:
                    english_payload = raw_text
                    src = "bubble.raw_report_json [assistant]"

                print(f"✅ Content extracted from: {src}")
                logger.info(f"✅ Content extracted from: {src}")
            else:
                # Fallback: extract from HTML/text if raw text is missing
                html = ""
                try:
                    html = (bubble.get_html() or "").strip()
                except Exception:
                    html = (getattr(bubble, "_raw_text", "") or "").strip()

                if not html:
                    msg = "⚠ Cannot translate to Persian: this bubble has no content."
                    print(f"❌ {msg}")
                    logger.error(f"❌ {msg}")
                    self.controller.bubble("AI ChatBot", msg)
                    return

                try:
                    english_payload = extract_plain_text_from_html(html).strip()
                except Exception:
                    english_payload = ""

                if not english_payload:
                    english_payload = html  # last resort
                src = "bubble.get_html() [assistant-fallback]"
                print(f"✅ Content extracted from: {src}")
                logger.info(f"✅ Content extracted from: {src}")
        else:
            # Report => prefer raw_report_json if available
            raw = getattr(bubble, "raw_report_json", None)
            if isinstance(raw, str) and raw.strip():
                english_payload = raw.strip()
                src = "bubble.raw_report_json [report]"
                print(f"✅ Content extracted from: {src}")
                logger.info(f"✅ Content extracted from: {src}")
            else:
                html = ""
                try:
                    html = (bubble.get_html() or "").strip()
                except Exception:
                    html = (getattr(bubble, "_raw_text", "") or "").strip()

                if not html:
                    msg = "⚠ Cannot translate to Persian: this bubble has no content."
                    print(f"❌ {msg}")
                    logger.error(f"❌ {msg}")
                    self.controller.bubble("AI ChatBot", msg)
                    return

                try:
                    english_payload = extract_plain_text_from_html(html).strip()
                except Exception:
                    english_payload = ""

                if not english_payload:
                    english_payload = html  # last resort
                src = "bubble.get_html() [report]"
                print(f"✅ Content extracted from: {src}")
                logger.info(f"✅ Content extracted from: {src}")

                try:
                    bubble.raw_report_json = english_payload
                except Exception:
                    pass

        if not english_payload.strip():
            msg = "⚠ Cannot translate to Persian: extracted content is empty."
            print(f"❌ {msg}")
            logger.error(f"❌ {msg}")
            self.controller.bubble("AI ChatBot", msg)
            return

        print(f"→ English content extracted: {len(english_payload)} characters")
        logger.info(f"→ English content extracted: {len(english_payload)} characters")

        # ─────────────────────────────────────────────
        # 2) Worker (API call)
        # ─────────────────────────────────────────────
        print("→ Translating to Persian...")
        logger.info("→ Translating to Persian...")
        
        def work():
            backend, _center_name, center_key = _resolve_active_ai_identity()
            if not center_key:
                # 2026-07-31 — this used to call `self.history.add_bubble(...)`
                # RIGHT HERE, inside `work()`, which `ApiWorker.run` executes on
                # the QThread. That builds a MessageBubble (a QLabel, six
                # QToolButtons, layouts, stylesheets) and splices it into the
                # live layout from a non-GUI thread — undefined behaviour, and
                # on Windows typically a silent access violation with no Python
                # frame. Reachable through ordinary configuration: any time the
                # OpenAI key is empty or the backend has not been validated yet.
                #
                # The rule this file already states for the reception worker
                # applies here too: the worker returns DATA, the GUI thread
                # renders it. `_run_async`'s error callback is on the GUI
                # thread, so raising is the correct way out.
                raise RuntimeError(
                    "❌ AI backend is not configured. Please complete EchoMind Settings."
                )

            # ✅ Assistant => translate free text
            if is_assistant:
                return _ai_module(backend).translate_text_to_persian(
                    user_msg=english_payload, CENTER_Key=center_key
                )
            # ✅ Report => translate structured report
            return _ai_module(backend).translate_report(
                user_msg=english_payload, CENTER_Key=center_key
            )

        # ─────────────────────────────────────────────
        # 3) Handle success
        # ─────────────────────────────────────────────
        def ok(resp: dict):
            print("\n" + "="*100)
            print("✅ ✅ ✅ SUCCESS! Persian translation received")
            print("="*100 + "\n")
            logger.info("="*100)
            logger.info("✅ ✅ ✅ SUCCESS! Persian translation received")
            logger.info("="*100)

            # (translate_text_to_persian معمولاً session_id ندارد، ولی برای سازگاری نگه می‌داریم)
            new_sid = resp.get("session_id") if isinstance(resp, dict) else None
            if new_sid:
                try:
                    self.controller.switch_session(new_sid)
                except Exception:
                    pass

            if is_assistant:
                # ✅ plain text rendering
                from html import escape
                txt = (resp.get("content") if isinstance(resp, dict) else "") or ""
                txt = txt.strip()
                if not txt:
                    self.controller.bubble("AI ChatBot", "⚠ Empty Persian assistant translation.")
                    logger.warning("⚠ Empty Persian assistant translation.")
                    return

                # Persian assist output log (length + preview)
                try:
                    # 2026-07-31 — this logged 400 characters of the PERSIAN
                    # REPORT at INFO (a level that reaches the collected app
                    # log) and printed it as well. The length is the diagnostic
                    # signal; the body is patient content.
                    _log.debug("[ASSISTANT-FA] chars=%d", len(txt))
                except Exception:
                    pass

                html = (
                    "<div dir='rtl' style='direction: rtl; text-align: right;'>"
                    "<pre style='white-space: pre-wrap; margin:0;'>"
                    f"{escape(txt)}"
                    "</pre></div>"
                )
                self._bubble_origin_hint = "assistant"
                self.controller.bubble("AI ChatBot (Persian)", html)
                logger.info("✅ Persian assistant translation displayed")
                return

            # ✅ report-style rendering (مثل قبل)
            rep_raw_clean = self._normalize_report_like_payload(resp)
            if not (rep_raw_clean or "").strip():
                print("[REPORT-FA] Empty translation payload. keys=", list(resp.keys()) if isinstance(resp, dict) else type(resp))
                logger.error("[REPORT-FA] Empty translation payload.")
                self.controller.bubble("AI ChatBot", "⚠ Empty Persian report.")
                return

            items = self._parse_jsonish_list(rep_raw_clean)
            inner_html = self._render_kv_report_html(items)

            html = (
                "<div dir='rtl' style='direction: rtl; text-align: right;'>"
                f"{inner_html}"
                "</div>"
            )

            self._bubble_origin_hint = "report"
            self.controller.bubble("AI ChatBot (Persian)", html)
            logger.info("✅ Persian report translation displayed")

        # ─────────────────────────────────────────────
        # 4) Handle error
        # ─────────────────────────────────────────────
        def er(msg: str):
            print(f"\n❌ Translation error: {msg}")
            print("="*100 + "\n")
            logger.error(f"❌ Translation error: {msg}")
            self.controller.bubble("AI ChatBot", f"❌ Persian translation failed: {msg}")

        self._run_async(work, ok, er, typing="Translating to Persian…")

    def _edit_bubble(self, bubble: MessageBubble):
        """
        بدون سیگنال: یک دیالوگ ساده باز می‌کنیم، HTML را ادیت می‌گیریم،
        Bubble را آپدیت می‌کنیم و همان رکورد DB را به‌روزرسانی می‌کنیم.
        فقط برای پیام‌های Report فعال است (origin='report').
        """
        if bubble is None:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit message")
        # Explicit dark editor colours (matches the chat the report was authored
        # for) so the text never becomes light-on-light on a light Windows theme,
        # and the right-click context menu is themed too. AIPACS_ECHO_POPUP_THEME=0
        # restores the legacy unstyled editor.
        style_popup(dlg)
        v = QVBoxLayout(dlg)
        te = QTextEdit(dlg)
        te.setAcceptRichText(True)
        te.setHtml(bubble.get_html() or "")
        te.setMinimumSize(720, 420)
        v.addWidget(te, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        v.addWidget(btns, 0)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec() == QDialog.Accepted:
            new_html = te.toHtml().strip()
            old_html = bubble.get_html().strip()
            if new_html and (new_html != old_html):
                # 1) UI
                bubble.set_html(new_html)
                # 2) DB (با استفاده از دیتابیس اصلی)
                try:
                    if getattr(bubble, "_msg_id", None) is not None:

                        U.ai_update_message(int(bubble._msg_id), new_html)  # ⬅️ جایگزین self.store.update_message
                    # 3) کش درون‌حافظه‌ای را بی‌اعتبار کن تا باز کردن مجدد سشن از DB بخواند
                    if self.current_session_id:
                        self.sessions.pop(self.current_session_id, None)
                except Exception:
                    pass

    def cleanup(self):
        """Detach in-flight ApiWorker QThreads BEFORE this page is destroyed.

        THE close-while-transcribing crash: ApiWorker is a QThread parented to this
        page, so WA_DeleteOnClose destroys it mid-run and Qt aborts the process with
        "QThread: Destroyed while thread is still running" (no traceback, app.log
        just stops). See _ORPHANED_WORKERS above. Called by
        AIChatViewer._teardown_page. Idempotent; never raises.
        """
        import logging
        lg = logging.getLogger("echomind.teardown")

        workers = list(getattr(self, "_workers", []) or [])
        try:
            from PySide6.QtCore import QThread
            for w in self.findChildren(QThread):   # catch any we did not track
                if w not in workers:
                    workers.append(w)
        except Exception:
            pass

        detached = 0
        for w in workers:
            try:
                if not w.isRunning():
                    continue
                # Its result must NEVER be delivered to this dying page.
                for _sig in ("done", "failed", "finished"):
                    try:
                        getattr(w, _sig).disconnect()
                    except Exception:
                        pass
                w.setParent(None)              # Qt must NOT delete it with the page
                _ORPHANED_WORKERS.append(w)    # keep a Python ref so it is not GC'd
                try:
                    w.finished.connect(lambda _w=w: _release_orphan_worker(_w))
                except Exception:
                    pass
                detached += 1
            except Exception as exc:
                lg.warning("[ECHO-TEARDOWN] worker detach failed: %s", exc)

        self._workers = []
        lg.info("[ECHO-TEARDOWN] page.cleanup detached %d running ApiWorker(s)",
                detached)

    def _run_async(self, work: t.Callable, ok: t.Callable[[dict], None],
                   err: t.Callable[[str], None] | None = None,
                   lock_btn: QPushButton | None = None, typing="Thinking",
                   cancel_text: str | None = None):
        # `cancel_text` — what to tell the user when they press Cancel.
        # The default ("Request cancelled") is TRUE for a read-only AI call:
        # detaching the worker means the answer never reaches the UI and
        # nothing changed anywhere. It is FALSE for work with side effects — an
        # in-flight `requests` call cannot be interrupted, so a reception send
        # that has already POSTed still writes the report and still updates the
        # DB. Telling the user it was cancelled invites them to press Send
        # again and create a duplicate clinical record. Callers whose work
        # mutates server or DB state MUST pass an honest string.
        # ⬅️ مهم: هر بابل جدیدی (حتی تایپینگ) می‌آید، خوشامد را بردار
        self._drop_welcome_if_any()

        typing_b = self.history.add_typing("AI ChatBot", typing)
        if lock_btn: lock_btn.setEnabled(False)
        self._busy_count += 1
        try:
            self.btn_new.setEnabled(False)
            self.composer.set_enabled(False)
        except Exception:
            pass

        worker = ApiWorker(work)
        self._workers = getattr(self, "_workers", [])
        self._workers.append(worker)

        # F5 (2026-07-28): a cancel affordance. There was none — the composer
        # stayed locked until the request returned, and the chat modes used a
        # 300 s timeout, so a hung server locked the composer for FIVE MINUTES
        # with no way out but closing the window. `_transcribe_now` already had
        # a cancel button; `_run_async` did not.
        cancelled = {"flag": False}
        # Only ONE owner of the shared cancel button at a time. A transcription
        # already wires `cancelClicked` to its own handler and drives
        # `show_cancel`; if one is in flight we leave the button alone rather
        # than have a single click cancel two unrelated requests.
        owns_cancel = {"flag": not getattr(self, "_tr_in_flight", False)}

        def _stop_cancel_wiring():
            if not owns_cancel["flag"]:
                return
            owns_cancel["flag"] = False
            try:
                self.composer.cancelClicked.disconnect(_on_cancel)
            except Exception:
                pass
            try:
                self.composer.show_cancel(False)
            except Exception:
                pass

        def cleanup():
            self.history.remove_widget(typing_b)
            typing_b.stop()
            if lock_btn: lock_btn.setEnabled(True)
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            self._busy_count = max(0, self._busy_count - 1)
            _stop_cancel_wiring()
            # Do NOT re-enable the composer while a transcription is still in
            # flight. `_transcribe_now` locks btn_mic/btn_send/btn_plus through
            # its OWN mechanism, and `composer.set_enabled(True)` re-enables all
            # three — so finishing a bubble-triggered translate/correction used
            # to unlock the mic mid-transcription and let a second request fire.
            if self._busy_count == 0 and not getattr(self, "_tr_in_flight", False):
                try:
                    self.btn_new.setEnabled(True)
                    self.composer.set_enabled(True)
                except Exception:
                    pass

        def _on_cancel():
            """Stop WAITING for this request; never leave a live QThread parentless.

            An in-flight `requests` call cannot be interrupted, so we use the
            same proven "detach, don't wait" contract as the close-teardown:
            disconnect the signals so the result can never reach the UI, keep a
            module-level reference so Python does not GC a running QThread (that
            aborts the process), and let it finish harmlessly.
            """
            if cancelled["flag"]:
                return
            cancelled["flag"] = True
            try:
                worker.done.disconnect(_ok)
            except Exception:
                pass
            try:
                worker.failed.disconnect(_er)
            except Exception:
                pass
            cleanup()
            try:
                if worker.isRunning():
                    worker.setParent(None)
                    _ORPHANED_WORKERS.append(worker)
                    worker.finished.connect(lambda _w=worker: _release_orphan_worker(_w))
            except Exception:
                pass
            self.controller.bubble(
                "AI ChatBot",
                cancel_text or "⏹️ <i>Request cancelled.</i>",
            )

        def _ok(res: dict):
            if cancelled["flag"]:
                return
            cleanup()
            ok(res)

        def _er(msg: str):
            if cancelled["flag"]:
                return
            cleanup()
            safe = _safe_fa_connection_error(msg)
            (err(safe) if err else self.controller.bubble("AI ChatBot", safe))

        worker.done.connect(_ok)
        worker.failed.connect(_er)
        if owns_cancel["flag"]:
            try:
                self.composer.cancelClicked.connect(_on_cancel)
                self.composer.show_cancel(True)
            except Exception:
                owns_cancel["flag"] = False
        worker.start()

    @Slot(str, str)
    def _append_bubble(self, who: str, text: str) -> None:
        """
        Adds a chat bubble and persists it, with a special rule for the very first
        welcome bubble:
          - Welcome bubbles are shown but NOT persisted (no DB / no cache).
          - As soon as ANY new bubble (user or bot) is added, the welcome bubble
            is removed from the UI.
        """
        # --- 0) اگر قبلاً یک خوش‌آمد نمایش داده‌ایم و الان هر پیام جدیدی می‌آید، حذفش کن
        try:
            if getattr(self, "_welcome_bubble", None) is not None:
                self.history.remove_widget(self._welcome_bubble)
                self._welcome_bubble = None
        except Exception:
            pass

        # --- 1) تشخیص خوش‌آمد ---
        norm = (text or "").strip().lower()
        welcome_texts = {
            "ready. type and press send to chat.",
            "ready. paste report text then send to generate report.",
            "ready. type and press send. use the dropdown to run assist or search.",
            "new chat. choose a mode on send.",
        }
        is_welcome = (who.strip() == "AI ChatBot") and (norm in welcome_texts)

        # اگر خوش‌آمد است: فقط نشان بده، ذخیره/کش نکن و رفرنس نگه‌دار تا بعداً حذف شود
        if is_welcome:
            b = self.history.add_bubble(who, text, on_edit=None)
            self._welcome_bubble = b
            # اگر هنوز سشن محلی نداریم یکی بساز تا سایدبار خالی نباشد
            if not self.current_session_id:
                sid = self._ensure_local_session("New Chat")
                self.current_session_id = sid
            return

        # --- 2) تعیین sid ---
        sid = self.current_session_id or self.controller.session_id
        if not sid:
            is_user = who.strip().lower().startswith("you")
            hint = (text.strip().splitlines()[0][:40] if (is_user and text) else "New Chat")
            sid = self._ensure_local_session(hint)

        # --- 3) منبع پاسخ غیرکاربر (برای فعال شدن Edit در Report) ---
        origin = None
        is_user = who.strip().lower().startswith("you")
        if not is_user:
            origin = getattr(self, "_bubble_origin_hint", None)
            self._bubble_origin_hint = None
            # Fallback: if hint is missing, infer from pending raw payloads
            if not origin:
                if getattr(self, "_pending_assistant_raw_en", None):
                    origin = "assistant"
                elif getattr(self, "_pending_report_raw_en", None):
                    origin = "report"

        # --- 3.5) report raw (for DB persistence) ---
        raw_report_for_db: str | None = None
        # --- 4) کش درون‌حافظه‌ای ---
        self.sessions.setdefault(sid, [])
        self.sessions[sid].append((who, text))

        # --- 5) نمایش UI ---
        on_edit = self._edit_bubble if (origin in ("report", "assistant") and not is_user) else None
        on_persian = self._persian_bubble if (origin in ("report", "assistant") and not is_user) else None
        # Enable send_to_reception for all non-user messages
        on_send_reception = self._send_to_reception if (not is_user and text) else None

        b = self.history.add_bubble(
            who,
            text,
            on_edit=on_edit,
            on_persian=on_persian,
            on_send_reception=on_send_reception,
        )
        # ── 2026-07-31: the Retry chip could never appear ────────────────────
        # `_send_with_mode` seeds `_pending_retry` with {"bubble": None} and
        # NOTHING ever wrote a bubble back into it, so `_er_for`'s `if bub:` was
        # always false and `MessageBubble.btnRetry` (built hidden) was never
        # shown. The whole preserved-text / preserved-images retry path was
        # unreachable. In Chat mode that also means the dictated text is gone
        # from the composer (it is cleared on send) and survives only inside a
        # chat bubble the user has to copy out by hand.
        #
        # The user bubble created for THIS send is the one the chip belongs on,
        # and it is created before `_run_async` is scheduled, so it is always in
        # place before the error callback can fire.
        try:
            if (
                is_user
                and isinstance(getattr(self, "_pending_retry", None), dict)
                and self._pending_retry.get("bubble") is None
            ):
                self._pending_retry["bubble"] = b
        except Exception:
            pass

        # Keep origin on live bubbles (used by Persian/Edit)
        try:
            b._origin = origin
        except Exception:
            pass

        # 🔹 If this is a freshly generated report bubble, attach the raw EN JSON
        if origin == "report" and not is_user:
            raw_en = getattr(self, "_pending_report_raw_en", None)
            raw_report_for_db = raw_en if isinstance(raw_en, str) else None
            if raw_en:
                try:
                    b.raw_report_json = raw_en
                except Exception:
                    pass
                # Add to Correction dropdown
                try:
                    self.composer.register_correction_report(raw_en)
                except Exception:
                    pass

                # consume it so it won't leak to later bubbles
                self._pending_report_raw_en = None

        # 🔹 If this is a freshly generated assistant bubble, attach the raw EN "report JSON"
        if origin == "assistant" and not is_user:
            raw_en = getattr(self, "_pending_assistant_raw_en", None)
            if raw_en:
                try:
                    b.raw_report_json = raw_en
                except Exception:
                    pass
                # consume it so it won't leak to later bubbles
                self._pending_assistant_raw_en = None

        # --- 6) سشن در UI ---
        try:
            if not self.current_session_id:
                self.current_session_id = sid
        except Exception:
            self.current_session_id = sid

        # --- 7) ذخیره در DB ---
        try:
            U.ai_upsert_session(sid, None, self.study_uid)
            msg_id = U.ai_append_message(sid, who, text, origin=origin)
            b._msg_id = msg_id
            # ✅ persist report JSON separately (collections/corrections must not depend on UI bubbles)
            try:
                if origin == "report" and (not is_user) and raw_report_for_db:
                    fn = getattr(U, "ai_insert_report", None) or getattr(U, "ai_upsert_report", None)
                    if callable(fn):
                        # 2026-08-06: this call used to be DEAD — `fn` was always None
                        # because the export chain was broken, so no report was ever
                        # persisted. With the chain fixed it fires, and it now records
                        # who/which-model/which-modality for the audit trail.
                        from modules.EchoMind import session_metadata as _meta
                        _kind = getattr(self, "_pending_report_kind", None) or "report"
                        _corrects = getattr(self, "_pending_corrects_msg_id", None)
                        try:
                            self._pending_report_kind = None
                            self._pending_corrects_msg_id = None
                        except Exception:
                            pass
                        fn(
                            sid, int(msg_id), raw_report_for_db,
                            study_uid=getattr(self, "study_uid", None),
                            kind=_kind,
                            corrects_msg_id=_corrects,
                            physician_id=_meta.resolve_physician_id(),
                            model=getattr(company_direct, "PRIMARY_REPORT_MODEL", None),
                            modality=getattr(self, "_current_modality", None),
                        )
            except Exception:
                pass
            if getattr(self, "study_uid", None):
                U.ai_set_last_session_for_study(self.study_uid, sid)
            U.ai_set_last_session(sid)
        except Exception:
            pass

        # --- 8) عنوان سشن از اولین پیام کاربر ---
        try:
            sid = getattr(self.controller, "session_id", None) or getattr(self, "current_session_id", None) or "local"
            if who.strip().lower().startswith("you"):
                item = self._find_sidebar_item_by_sid(sid)
                if item:
                    base = self._get_item_base_title(item)
                    if (not base) or (base == "New Chat"):
                        snippet = self._make_title_from_text(text, max_len=28)
                        if snippet:
                            self._apply_item_title_and_style(item, snippet, sid=sid)
                            try:
                                U.ai_upsert_session(sid, snippet, getattr(self, "study_uid", None))
                            except Exception:
                                pass
        except Exception:
            pass

    def _on_session_changed(self, server_sid: str):
        """
        سرور آیدیِ سشن خودش را اعلام کرده است.
        نگاشت (local sid -> server_sid) را در DB اصلی ذخیره می‌کنیم.
        """
        if not server_sid:
            return
        local_sid = self.current_session_id
        if not local_sid:
            return
        try:
            U.ai_upsert_session(local_sid)  # ensure exists
            U.ai_set_server_sid(local_sid, server_sid)
            U.ai_set_last_session(local_sid)
        except Exception:
            pass

    # تغییر در متد _new_chat برای حفظ مودالیتی
    def _new_chat(self):
        # 1) Reset session
        self.controller.reset_session()
        self.current_session_id = None

        # 2) Clear history
        self.history.clear()

        # 3) Reset composer
        try:
            self.composer.clear_attachment()
            self.composer.set_tab_text("standard", "")
            self.composer.set_tab_text("transcribe", "")
            self.composer.set_tab_text("normal_template", "")
            self.composer.set_tab_text("correction", "")  # ← این خط جدید
            if hasattr(self.composer, "_std_lang_texts"):
                self.composer._std_lang_texts = {"en": "", "fa": ""}
            if hasattr(self.composer, "_std_lang"):
                self.composer._std_lang = "fa"
            self.composer._update_lang_buttons_visibility()
            self.composer.switch_tab("transcribe")
            self.composer.box.clear()
        except Exception:
            pass

        # ── 2026-07-31: images must NOT survive a session boundary ───────────
        # The attachment picker explicitly offers "Other Patient -> Enter
        # patient id", so `_image_attachments` can hold another patient's
        # slices. It was cleared in exactly two places, both success-only
        # callbacks: `clear_attachment()` above clears the VOICE queue only.
        # So: attach 3 images from patient B -> send fails -> New Chat ->
        # dictate patient A -> Send, and B's images are POSTed as the basis for
        # A's report, with the bubble saying only "Attached image(s): 3".
        try:
            self.composer.clear_image_attachments()
        except Exception:
            pass

        # ✅ Correction: clear dropdown for new chat
        try:
            self.composer.clear_correction_reports() 
        except Exception:
            pass


        # 4) Restore modality in Report mode
        if str(getattr(self, "page_mode", "")).lower() == "report":
            if OneChatPage.last_selected_modality:
                self._current_modality = OneChatPage.last_selected_modality
                self._set_modality_text(OneChatPage.last_selected_modality)
            else:
                # Clear if none was ever selected
                if hasattr(self, "_current_modality"):
                    delattr(self, "_current_modality")

        # 5) Create new local session
        local_sid = self._ensure_local_session("New Chat")
        self.sessions[local_sid] = []

        # 6) Show welcome message
        if str(getattr(self, "page_mode", "")).lower() == "report":
            mod = getattr(self, "_current_modality", "Not selected")
            welcome_msg = f"Ready. Selected modality: {mod}. Paste report text then Send."
        else:
            welcome_msg = "New chat. Choose a mode on Send."
        self.controller.bubble("AI ChatBot", welcome_msg)
        
    # متد جدید برای پاسخ به انتخاب مودالیتی
    def _on_modality_selected(self, modality):
        self._current_modality = modality
        OneChatPage.last_selected_modality = modality  # ذخیره در سطح کلاس
        self._set_modality_text(modality)

    def _resolve_corrected_msg_id(self, report_text: str):
        """Which stored report is this correction correcting?

        The Correction dropdown carries the report TEXT and a display label — never a
        msg_id — so the link has to be recovered by matching that text back to
        `ai_reports.raw_en`. Whitespace-normalised, because the text round-trips
        through a widget on the way here.

        Returns None when the match is absent OR ambiguous. An unlinked correction is
        still a useful record; a WRONGLY linked one corrupts the correction history,
        which is the one thing this column exists to make analysable.
        """
        try:
            norm = " ".join((report_text or "").split())
            if not norm:
                return None
            fn = getattr(U, "ai_fetch_reports_for_session", None)
            if not callable(fn):
                return None
            rows = fn(getattr(self, "current_session_id", None)) or []
            hits = {r[1] for r in rows
                    if r[1] is not None and " ".join((r[3] or "").split()) == norm}
            return hits.pop() if len(hits) == 1 else None
        except Exception:
            return None

    def _build_gate_profile(self, transcript: str = ""):
        """The study profile the Turbo prompt narrows on, or None to send everything.

        Read straight from the chat's own metadata — the card the physician can see and
        correct — so what the gate acts on is exactly what he was shown. If he corrected
        the region, the correction is already in the effective record and wins here.

        Returns None on anything uncertain: no chat, no record, no regions. The prompt
        builder treats None as "send the full prompt", which is today's behaviour.
        """
        try:
            from modules.EchoMind import session_metadata as _meta
            sid = getattr(self, "current_session_id", None)
            if not sid:
                return None
            rec = _meta.load(sid) or {}
            case = rec.get("case") or {}
            regions = [str(r).strip() for r in (case.get("regions") or []) if str(r).strip()]
            if not regions:
                return None
            # The dictation may NARROW the gate, never widen it (owner decision
            # 2026-08-09). Widening is already the prompt's job — "If the transcript
            # describes anatomy outside it, report that finding normally and place it
            # correctly" — and the transcript arrives through an STT that mangles
            # Persian. So a narrowing is only accepted when what he named is a
            # non-empty subset of what was booked and scanned; anything else leaves
            # the gate alone. Logged either way: a region that silently disappears is
            # indistinguishable from one that was never detected.
            if transcript and _meta.region_text_enabled():
                spoken = [r for r in _meta.detect_regions_from_text(transcript)
                          if r in regions]
                if spoken and len(spoken) < len(regions):
                    # ...but only if the narrowed set still HAS reporting content for
                    # this modality. 2026-08-11: ['brain','temporal_bone'] narrowed to
                    # ['temporal_bone'], radiography has no temporal_bone package, and
                    # the prompt fell all the way back to the 35 754-char ungated one —
                    # ctx=0. Narrowing that destroys the gate is worse than not
                    # narrowing.
                    keeps_gate = True
                    try:
                        from .turbo_modules import modules_for as _mods_for
                        _mod = getattr(self, "_current_modality", None) or ""
                        keeps_gate = bool(_mods_for(_mod, spoken)) or not _mods_for(_mod, regions)
                    except Exception:
                        keeps_gate = True
                    if keeps_gate:
                        _log.info("[Turbo] regions %s -> %s (narrowed by the dictation)",
                                  regions, spoken)
                        regions = spoken
                    else:
                        _log.warning("[Turbo] not narrowing %s -> %s: no %s package for "
                                     "the narrowed set, the gate would be lost",
                                     regions, spoken, _mod)
            patient = rec.get("patient") or {}
            study = (rec.get("studies") or [{}])[0]
            bits = [str(patient.get(k) or "").strip()
                    for k in ("patient_id", "sex", "age")]
            return {
                "regions": regions,
                "contrast": case.get("contrast") or "",
                "procedure": case.get("procedure") or "",
                "subtype": case.get("subtype") or "",
                # Facts for the template's STUDY CONTEXT slot. Absent keys simply do
                # not render — the block only shows what is actually known.
                "patient": " · ".join(b for b in bits if b),
                "service": (rec.get("reception") or {}).get("service") or "",
                "protocol": study.get("study_description") or "",
            }
        except Exception as exc:
            _log.debug("[Turbo] gate profile unavailable: %s", exc)
            return None

    def _correction_gate_profile(self):
        """The gate profile for a CORRECTION — regions only, no dictation narrowing.

        The correction note is an instruction ("split the normals into knee and
        calcaneus"), not a dictation, so it must never be mined for regions: the words
        it contains describe the edit, not the study. The study's own region set is
        what the correction needs in order to add anatomy correctly.
        """
        prof = self._build_gate_profile() or {}
        if prof:
            prof = dict(prof)
            prof["modality"] = getattr(self, "_current_modality", None) or ""
        return prof or None

    def _turbo_correction(self, backend, center_key) -> None:
        """Turbo in the Correction tab: edit the SELECTED report, never write a new one.

        Delegates to _send_report_correction, which already owns the report lookup, the
        two guards, the correction-history bookkeeping and the result rendering. Turbo
        differs in exactly two ways and passes exactly two arguments: it is pinned to the
        company backend, and it prepends its editing frame to the shared correction prompt.

        Observed 2026-08-09: with the Correction tab active, Turbo fell through to the
        report branch, took the correction INSTRUCTION as if it were a dictation and
        called reporter(). The physician got a brand-new report generated from his own
        edit note, and the report he had selected was never sent at all.
        """
        prefix = ""
        try:
            from .turbo_prompt import build_turbo_correction_prefix
            prefix = build_turbo_correction_prefix(self._correction_gate_profile()) or ""
        except Exception as exc:                      # pragma: no cover - defensive
            _log.warning("[Turbo-correction] frame unavailable, shared prompt only: %s",
                         exc)
        note = (self.composer.box.toPlainText() or "").strip()
        _log.info("[Turbo-correction] note_len=%d frame=%s backend=%s",
                  len(note), "turbo" if prefix else "shared", backend)
        self._send_report_correction(note, system_prompt_prefix=prefix,
                                     force_backend=backend, turbo=True)

    def _prefetch_reception(self) -> None:
        """Warm the reception cache while the physician dictates.

        Recording and transcription are the only part of a session where the network
        is idle and nobody is waiting on us, so this is where the reception round trip
        belongs. By the time the report chat is minted the service list is already
        local, instead of the metadata card reading "not detected" until somebody
        happens to open the reception tab.

        Returns immediately: the work is on a daemon thread, deduplicated per patient,
        and skipped entirely when the cache is still fresh. Fully swallowed — this is
        called while an audio stream is being opened.
        """
        try:
            from modules.EchoMind import reception_prefetch
            reception_prefetch.prefetch(study_uid=getattr(self, "study_uid", None))
        except Exception as exc:
            _log.debug("[EchoMind-prefetch] skipped: %s", exc)

    def _sync_metadata_card(self, sid=None) -> None:
        """Point the in-conversation metadata card at a chat. Fully swallowed.

        The card is a read-out of storage, never a source of truth, so a failure here
        must cost the physician a card refresh and nothing else.
        """
        try:
            card = getattr(self, "meta_card", None)
            if card is not None:
                card.bind(sid or getattr(self, "current_session_id", None))
        except Exception as exc:
            _log.warning("[EchoMind-meta] card sync failed: %s", exc)

    def _seed_session_metadata(self, sid: str) -> None:
        """Seed this chat's case metadata from local DICOM rows (2026-08-06).

        Foundation layer only — NOTHING reads this into a prompt yet. It gives the
        chat a persistent, correctable case context (patient, study, modality,
        regions) that later steps can consume once detection accuracy has been
        measured on real cases.

        Best-effort and fully swallowed: a metadata failure must never stop a chat
        from opening. Local SQLite reads only — no network, no LLM, no blocking.
        """
        try:
            from modules.EchoMind import session_metadata as _meta
            _meta.populate_for_chat(
                sid,
                study_uid=getattr(self, "study_uid", None),
                modality_selected=getattr(self, "_current_modality", None),
            )
        except Exception as exc:
            _log.debug("[EchoMind-meta] seed skipped for %s: %s", sid, exc)

    def _new_session(self):
        sid = f"{self.ns}-{uuid.uuid4().hex[:8]}"
        title = "New Chat"
        U.ai_upsert_session(sid, title, study_uid=getattr(self, "study_uid", None))
        self._seed_session_metadata(sid)

        it = QListWidgetItem()
        it.setData(Qt.UserRole, sid)
        self._apply_item_title_and_style(it, title, sid=sid)

        self.list.addItem(it)
        self.list.setCurrentItem(it)
        self._open_session(it)


    def _open_session(self, item):
        sid = item.data(Qt.UserRole)

        # 0) set local current sid
        self.current_session_id = sid
        self.controller.switch_session(sid)
        self._sync_metadata_card(sid)

        # 2026-07-31 — see `_new_chat`: attachments queued against the previous
        # session (possibly a different patient) must not follow the user here.
        try:
            self.composer.clear_image_attachments()
        except Exception:
            pass

        # 1) persist last session (per-study + global)
        try:
            if getattr(self, "study_uid", None):
                U.ai_set_last_session_for_study(self.study_uid, sid)
            U.ai_set_last_session(sid)
        except Exception:
            pass

        # 2) update sidebar title style (pin prefix)
        try:
            base = self._get_item_base_title(item)
            self._apply_item_title_and_style(item, base, sid=sid)
        except Exception:
            pass

        # 3) if empty => show welcome
        rows = []
        try:
            rows = U.ai_fetch_messages_full(sid)
        except Exception:
            rows = []

        if not rows:
            try:
                self.history.clear()
                self.controller.bubble("AI ChatBot", "New chat. Choose a mode on Send.")
                return
            except Exception:
                return

        def _looks_like_json_payload(s: str) -> bool:
            s = (s or "").lstrip()
            if not s:
                return False
            if s.startswith("{") or s.startswith("["):
                return True
            if "```" in s and ("{" in s or "[" in s):
                return True
            if '"Report Title"' in s or '"عنوان گزارش"' in s:
                return True
            return False

        # 4) Load persisted reports (raw EN JSON) from DB
        #    + Fallback for old sessions: derive from report bubbles HTML and backfill ai_reports
        report_map: dict[int, str] = {}
        report_items: list[tuple[str, str | None]] = []  # (raw, label)

        try:
            fn = getattr(U, "ai_fetch_reports_for_session", None)
            if callable(fn):
                for _, msg_id, label, raw_en, _ in (fn(sid) or []):
                    if isinstance(raw_en, str) and raw_en.strip():
                        report_items.append((raw_en, label if isinstance(label, str) else None))
                    # keep map (but we'll attach to bubble only if JSON-like)
                    try:
                        if msg_id is not None:
                            report_map[int(msg_id)] = raw_en
                    except Exception:
                        pass
        except Exception:
            pass

        # ✅ Fallback: if DB has no reports (old sessions), use ai_messages report bubbles
        if not report_items:
            try:
                insert_fn = getattr(U, "ai_insert_report", None)
            except Exception:
                insert_fn = None

            n = 0
            for msg_id, who, html, origin in (rows or []):
                if origin != "report":
                    continue
                if not isinstance(html, str) or not html.strip():
                    continue

                n += 1
                raw = html.strip()

                # label from plain text (better than "<div ...")
                try:
                    plain = self._html_to_plain_text(raw) if raw else ""
                    first_line = next((ln.strip() for ln in (plain or "").splitlines() if ln.strip()), "")
                    label = (first_line[:80] if first_line else f"Report {n}")
                except Exception:
                    label = f"Report {n}"

                report_items.append((raw, label))

                # backfill into ai_reports so next time dropdown works from DB too
                if callable(insert_fn):
                    try:
                        insert_fn(
                            sid,
                            int(msg_id) if msg_id is not None else None,
                            raw,
                            study_uid=getattr(self, "study_uid", None),
                            label=label,
                            kind="report",
                        )
                    except Exception:
                        pass

        # 4.5) Fill Correction dropdown
        try:
            self.composer.clear_correction_reports()
            for raw, label in report_items:
                self.composer.register_correction_report(raw, label=label)
        except Exception:
            pass

        # 4.6) Render history from DB
        self.history.clear()
        try:
            rows = U.ai_fetch_messages_full(sid)  # [(id, who, html, origin)]
        except Exception:
            rows = []

        for msg_id, who, html, origin in rows:
            if not html:
                continue

            is_user = who.strip().lower().startswith("you")
            on_edit = self._edit_bubble if (origin in ("report", "assistant") and not is_user) else None
            on_persian = self._persian_bubble if (origin in ("report", "assistant") and not is_user) else None
            # Enable send_to_reception for all non-user messages
            on_send_reception = self._send_to_reception if (not is_user and html) else None

            b = self.history.add_bubble(
                who,
                html,
                on_edit=on_edit,
                on_persian=on_persian,
                on_send_reception=on_send_reception,
            )
            try:
                b._msg_id = int(msg_id)
            except Exception:
                b._msg_id = msg_id

            # ✅ attach raw EN JSON only if it looks JSON-like (avoid attaching fallback HTML)
            try:
                if origin == "report" and (not is_user):
                    raw = report_map.get(int(msg_id))
                    if raw and _looks_like_json_payload(raw):
                        b.raw_report_json = raw
            except Exception:
                pass

        # 5) ثبت آخرین سشن (per-study + global)
        try:
            if getattr(self, "study_uid", None):
                U.ai_set_last_session_for_study(self.study_uid, sid)
            U.ai_set_last_session(sid)
        except Exception:
            pass

        # 6) اگر عنوان سشن هنوز "New Chat" است و اولین پیام کاربر داریم، عنوان را آپدیت کن
        try:
            base = self._get_item_base_title(item)
            if (not base) or (base == "New Chat"):
                for _, who, html, origin in rows:
                    if who and str(who).strip().lower().startswith("you"):
                        plain = self._html_to_plain_text(html) if html else ""
                        snippet = self._make_title_from_text(plain or html or "", max_len=28)
                        if snippet:
                            self._apply_item_title_and_style(item, snippet, sid=sid)
                            try:
                                U.ai_upsert_session(sid, snippet, getattr(self, "study_uid", None))
                            except Exception:
                                pass
                        break
        except Exception:
            pass


    def _first_nonempty_line(s: str) -> str:
        s = (s or "").strip()
        for ln in s.splitlines():
            ln = (ln or "").strip()
            if ln:
                return ln
        return ""

        def _try_load_dict(s: str) -> dict | None:
            import json as _json
            try:
                obj = _json.loads(s)
                return obj if isinstance(obj, dict) else None
            except Exception:
                return None

        def _try_load_fenced_json(s: str) -> dict | None:
            s = s or ""
            import re as _re
            m = _re.search(r"```(?:json)?\s*({.*?})\s*```", s, flags=_re.S)
            if not m:
                return None
            return _try_load_dict(m.group(1))

        def _coerce_to_dict(payload: str) -> dict:
            s = (payload or "").strip()

            # 1) اگر fenced بود
            obj = _try_load_fenced_json(s)
            if obj is not None:
                return obj

            # 2) اگر با { شروع می‌شد
            if s.startswith("{") and s.endswith("}"):
                obj = _try_load_dict(s)
                if obj is not None:
                    return obj

            # 3) اگر کل خروجی JSON تمیز بود
            obj = _try_load_dict(s)
            if obj is not None:
                return obj

            # 4) اگر "Final Output" داشت، از همان بخش به بعد تلاش کن (معمولاً JSON نهایی آنجاست)
            low = s.lower()
            idx = low.rfind("final output")
            if idx != -1:
                tail = s[idx:]
                obj = _try_load_dict(tail)
                if obj is not None:
                    return obj

            # 5) اگر آخرین بلاک JSON را می‌خواهی:
            try:
                import re as _re
                matches = list(_re.finditer(r"{", s))
                for m in reversed(matches):
                    cand = s[m.start():]
                    obj = _try_load_dict(cand)
                    if obj is not None:
                        return obj
            except Exception:
                pass

            # 6) fallback: به جای regex greedy، از استخراج‌گر بالانس‌شده‌ی خودت استفاده کن
            # (این کمک می‌کند اگر متن دور JSON زیاد باشد)
            try:
                # توجه: _normalize_report_like_payload «اولین» JSON را ترجیح می‌دهد،
                # اما ما اینجا بعد از امتحانِ "آخرین fenced" از آن استفاده می‌کنیم.
                norm = self._normalize_report_like_payload(s)
                obj = _try_load_dict(norm)
                if obj is not None:
                    return obj
            except Exception:
                pass

            # 7) ناامید شدیم → Raw
            return {"Raw": s}


    # ===== composer actions =====
    def _open_mode_menu(self, text: str):
        menu = QMenu(self)

        has_text = bool(text.strip())
        has_session = bool(self.controller.session_id)

        items = [
            ("Chat", has_text, "For Chat, you must enter some text."),
            ("Report", has_text or has_session, "Enter text or use an existing session."),
            ("Assistant", has_text or has_session, "Provide text/report or use an existing session."),
            ("Search", has_text, "For Search, enter text or keywords."),
        ]


        for name, enabled, tip in items:
            act = QAction(name, menu)
            act.setEnabled(enabled)
            if not enabled:
                act.setToolTip(tip)
            # فقط وقتی فعال است، ارسال را انجام بده
            if enabled:
                act.triggered.connect(lambda _=False, n=name, t=text: self._send_with_mode(t, n))
            menu.addAction(act)

        btn = self.composer.btn_send
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _transcribe_now(self, payload: dict, *, quality_mode: str = "clear", _is_retry: bool = False):
        """
        Immediate transcription with full numerical quality-report support.
        Handles:
        • accepted audio
        • rejected audio + detailed criteria
        • silence
        • automatic one-shot fallback: a "clear"-mode failure (rejection,
          silence, or network error) is auto-resent once in "noisy" mode
        • displays metrics bubble
        • removes voice chip only when success

        quality_mode : "clear" (default, first attempt) or "noisy" (retry).
        _is_retry    : internal — True only for the auto-fallback resend.
        """
        # Also warm the reception cache here: an audio file dropped straight into the
        # composer never passes through _start_record, so it would otherwise miss the
        # one idle window we have. A duplicate call costs nothing — prefetch() is
        # deduplicated per patient and gated on cache freshness.
        self._prefetch_reception()

        # --- helper: normalize path from payload (file_path OR paths[0]) ---
        def _extract_file_path(pl: dict) -> t.Optional[str]:
            try:
                if not pl:
                    return None
                fp = pl.get("file_path")
                if fp:
                    return fp
                paths = pl.get("paths")
                if isinstance(paths, (list, tuple)) and paths:
                    return paths[0]
            except Exception:
                pass
            return None

        # ✅ keep the requested file path so we can remove exactly THIS attachment on success
        requested_path = _extract_file_path(payload)

        # --- ذخیره تب فعلی قبل از شروع ترنسکریپت ---
        current_tab = self.composer.get_active_tab()

        # --- Remove welcome (if exists) ---
        self._drop_welcome_if_any()

        # --- Create typing bubble ---
        typing_b = self.history.add_typing("AI ChatBot", "Transcribing…")
        self._tr_typing = typing_b
        # ── 2026-07-31: cancellation must be PER REQUEST ─────────────────────
        # `self._tr_cancelled` is page-level, but `_transcribe_now` can be
        # re-entered while a previous worker is still running (the noisy-mode
        # auto-retry does exactly that, and the user can simply dictate again).
        # Re-entry reset the flag to False, so the OLD worker then tested the
        # NEW call's flag: dictate A -> cancel -> dictate B, and worker A comes
        # back, sees "not cancelled", and inserts transcript A into the report
        # box next to B. A dictation the user explicitly cancelled ends up in
        # the report. The token below belongs to THIS call and nothing else can
        # reset it. `self._tr_cancelled` is kept in sync for any other reader.
        _tr_token = {"cancelled": False}
        self._tr_token = _tr_token
        self._tr_cancelled = False
        _cancel_wiring = {"fn": None}
        # F5: tells `_run_async`'s cleanup not to re-enable the composer while
        # this transcription is still running (its buttons are locked below by a
        # SEPARATE mechanism, and composer.set_enabled(True) would unlock them).
        self._tr_in_flight = True

        # --- Disable UI (except cancel) ---
        self.composer.show_cancel(True)
        self.composer.btn_plus.setEnabled(False)
        self.composer.btn_mic.setEnabled(False)
        self.composer.btn_send.setEnabled(False)

        # -----------------------------
        # Cleanup helper (UI restore)
        # -----------------------------
        def cleanup_ui():
            self._tr_in_flight = False   # F5: transcription no longer holds the composer
            # 2026-07-31 — drop THIS call's cancel wiring on EVERY exit path.
            # It used to be disconnected only inside `on_cancel`, so every
            # SUCCESSFUL transcription left a live stale handler behind. Three
            # successful dictations then one Cancel click ran four handlers,
            # each closing over its own `current_tab` — yanking the composer to
            # a tab the user never chose, and each marking its own token.
            fn = _cancel_wiring.get("fn")
            if fn is not None:
                _cancel_wiring["fn"] = None
                try:
                    self.composer.cancelClicked.disconnect(fn)
                except Exception:
                    pass
            if self._tr_typing:
                try:
                    self._tr_typing.stop()
                except Exception:
                    pass
                self.history.remove_widget(self._tr_typing)
                self._tr_typing = None
            # 2026-07-31 — do NOT unlock the composer while a `_run_async`
            # request is still in flight. `_run_async` deliberately declines to
            # wire the cancel button while a transcription is running
            # (`owns_cancel`), so hiding it here left that request with NO
            # cancel affordance at all, and re-enabling Send let a second
            # request start on top of it. This is the exact mirror of the guard
            # `_run_async.cleanup` already carries in the other direction.
            if self._busy_count == 0:
                self.composer.btn_plus.setEnabled(True)
                self.composer.btn_mic.setEnabled(True)
                self.composer.btn_send.setEnabled(True)
                self.composer.show_cancel(False)
            try:
                self.composer._apply_mic_mode("record")
            except Exception:
                pass

            # --- بازگشت به تب اصلی در صورتی که در تب Correction بودیم ---
            if current_tab == "correction":
                try:
                    self.composer.switch_tab("correction")
                except Exception:
                    pass

        # -----------------------------
        # One-shot automatic quality fallback
        # -----------------------------
        def _retry_once(reason: str = "quality") -> bool:
            """Auto-resend this exact voice once, and say WHY.

            ``reason`` is "quality" when the server rejected the audio or returned no
            speech, and "transport" when the request itself failed — a timeout, a
            connection error, or an HTTP 5xx.

            These are different events and the physician must not be told his
            microphone was quiet because the server returned a 500. He will re-record,
            speak louder and check his input device, and none of it can help. Observed
            2026-08-09: Server 3 returned HTTP 500 and the chat said "Voice quality
            seems low", twice.

            The retry only switches to "noisy" when the active provider honours it.
            Server 3 is an OpenAI-compatible Whisper endpoint that takes no
            ``quality_mode``, so a noisy resend there is a byte-identical request. It
            still gets one PLAIN retry after a transport failure, because a 5xx is
            often transient.

            Returns True if a retry was scheduled (the caller must stop and return).
            """
            if _is_retry or quality_mode != "clear":
                return False
            if _tr_token["cancelled"]:      # THIS request, not "the newest one"
                return False
            try:
                from modules.EchoMind.voice_transcription import quality_mode_supported
                noisy_helps = bool(quality_mode_supported())
            except Exception:               # pragma: no cover - defensive
                noisy_helps = True
            if reason == "quality" and not noisy_helps:
                # Nothing a resend could change: same file, same request, same answer.
                return False
            next_mode = "noisy" if (reason == "quality" and noisy_helps) else "clear"
            cleanup_ui()
            self.controller.bubble(
                "AI ChatBot",
                _VOICE_RETRY_LOW_QUALITY if next_mode == "noisy" else _VOICE_RETRY_SERVER,
            )
            QTimer.singleShot(
                400,
                lambda: self._transcribe_now(payload, quality_mode=next_mode,
                                             _is_retry=True),
            )
            return True

        # -----------------------------
        # Worker: network request
        # -----------------------------
        def work():
            """Upload the ALREADY-SAVED voice file for transcription.

            2026-07-13 — the destination is no longer hard-coded here. This used to
            POST directly to ``URL_GEN_TRANSCRIPT`` (``{AI_BASE}/generate_transcript``,
            a constant frozen at import time), which meant the chat ignored the
            Voice-to-Text provider in Settings entirely and could disagree with
            Secretary EchoMind. It now goes through the shared
            ``VoiceTranscriptionService``, which resolves the endpoint from
            **Settings ▸ EchoMind ▸ Voice to Text** ON EVERY CALL — so switching
            servers takes effect immediately, with no restart.

            Recording, the WAV location and attachment handling are unchanged; the
            service is handed the same file path as before. The returned dict is the
            server's RAW body merged with normalized keys, so the ``transcript`` /
            ``quality_report`` parsing below (and the usage logging) is untouched.
            """
            import os
            from modules.EchoMind.voice_transcription import VoiceTranscriptionService

            file_path = _extract_file_path(payload)
            if not file_path or not os.path.exists(file_path):
                raise Exception("Audio file not found for transcription.")

            resp = VoiceTranscriptionService().transcribe(
                [file_path], quality_mode=quality_mode
            )
            if not resp.get("ok", True) and not str(resp.get("transcript") or "").strip():
                raise Exception(str(resp.get("error") or "Transcription failed."))
            return resp

        # -----------------------------
        # Worker OK callback
        # -----------------------------
        def ok(resp: dict):
            # ✅ ALWAYS track transcript minutes (even if user pressed cancel; request still consumed)
            try:
                self._log_irannobat_transcript_usage(resp, [requested_path] if requested_path else None)
            except Exception:
                pass
            if _tr_token["cancelled"]:      # THIS request, not "the newest one"
                cleanup_ui()
                return

            cleanup_ui()   # stop typing bubble + unlock buttons

            tr = (resp.get("transcript") or "").strip()
            report_list = resp.get("quality_report", [])
            file_report = report_list[0] if report_list else None

            # ===========================================
            # 1. Handle REJECTED audio
            # ===========================================
            if file_report and file_report.get("accepted") is False:
                # The server rejects noisy/low-quality audio with a 200 OK
                # response (accepted=False) — NOT an HTTP error. On the first
                # ("clear") attempt, auto-resend once in noisy mode before
                # surfacing the rejection.
                if _retry_once("quality"):
                    return
                crit = file_report.get("criteria", {})
                msg = (
                    "⚠ **Voice Rejected**\n"
                    f"• Reason: {crit.get('reason')}\n"
                    f"• Energy: {crit.get('energy'):.8f}\n"
                    f"• ZCR: {crit.get('zcr'):.4f}\n"
                    f"• dBFS: {crit.get('dbfs'):.1f}\n"
                    f"• Duration: {crit.get('speech_ms')} ms\n"
                )
                self.controller.bubble("AI ChatBot", msg)
                return

            # ===========================================
            # 2. Handle ACCEPTED + GOOD AUDIO
            # ===========================================
            if tr:
                # --- تعیین تب هدف بر اساس تب فعلی ---
                target_tab = "correction" if current_tab == "correction" else "transcribe"

                # ✅ FIX: read the REAL buffer of the target tab
                try:
                    existing = self.composer.get_tab_text(target_tab) or ""
                except Exception:
                    std, trans = self.composer.get_tab_texts()
                    existing = trans if target_tab == "transcribe" else ""

                # --- اضافه کردن متن ترنسکریپت به تب هدف ---
                sep = "\n" if (existing and not existing.endswith("\n")) else ""
                new_text = existing + sep + tr
                self.composer.set_tab_text(target_tab, new_text)

                # ── 2026-07-31: actually save it ─────────────────────────────
                # `_persist_transcribe` existed, wrote `<sid>-transcribe.json`,
                # and had ZERO call sites — while BOTH session-restore paths
                # read that exact file. So the only copy of a completed
                # dictation lived in a QTextEdit. Made concrete by the voice
                # adapter: say "generate the report" and
                # `EchoMindCommandAdapter` calls `_open_mode_page("report")`,
                # which `deleteLater()`s the page holding the transcript and
                # builds a fresh empty one. A four-minute dictation, gone.
                if target_tab == "transcribe":
                    try:
                        self._persist_transcribe(new_text)
                    except Exception as exc:
                        _log.warning("[AI-Chat] transcript not persisted: %s", exc)

                # ✅ NEW: after successful transcription, remove the voice attachment chip
                try:
                    if requested_path:
                        self.composer.remove_voice_attachment(requested_path)
                    else:
                        # fallback: if path is unknown, clear all pending voices
                        self.composer.clear_pending_voices()
                except Exception:
                    try:
                        self.composer.clear_attachment()
                    except Exception:
                        pass

            # ===========================================
            # 3. Handle SILENCE ONLY
            # ===========================================
            else:
                # No transcript in clear mode — auto-retry once in noisy mode
                # before telling the user no speech was detected.
                if _retry_once("quality"):
                    return
                self.controller.bubble(
                    "AI ChatBot",
                    """
                    <div style="direction:ltr;text-align:left;">
                    ⚠️ <b>No clear speech detected.</b> 🎧🗣️<br><br>

                    <b>Common causes:</b> 🔇 muted/wrong mic 🎙️, 🔉 low volume/quality, 🌪️ heavy noise, 🔐 missing mic permission.<br>
                    <b>Try:</b> 🧪 test mic, 🔧 select correct input, 📈 raise input/record louder, 🤫 reduce noise, ✅ allow mic access.
                    </div>
                    """

                )

        # -----------------------------
        # Worker Error callback (with one-shot quality fallback)
        # -----------------------------
        def err(e):
            # A clear-mode network/HTTP failure gets one automatic retry too —
            # but as a TRANSPORT failure, not a voice-quality one. A 500 is the
            # server saying it broke; blaming the physician's microphone for it
            # sends him off to fix something that is not wrong.
            if _retry_once("transport"):
                return
            cleanup_ui()
            self.controller.bubble("AI ChatBot", f"❌ Error: {e}")

        # -----------------------------
        # Start background worker
        # -----------------------------
        worker = ApiWorker(work, parent=self)
        worker.done.connect(ok)
        worker.failed.connect(err)
        worker.start()

        # -----------------------------
        # Cancel button handler
        # -----------------------------
        def on_cancel():
            _tr_token["cancelled"] = True    # THIS request only
            self._tr_cancelled = True        # legacy mirror
            cleanup_ui()                     # also drops the wiring below

        _cancel_wiring["fn"] = on_cancel
        self.composer.cancelClicked.connect(on_cancel)

    def _send_with_mode(
        self,
        text: str,
        mode: str,
        modality: str = None,
        retry_images: list[str] | None = None,
    ):
        """
        ارسال بر اساس مود انتخاب شده.
        - اگر درخواست fail شود، روی آخرین حباب کاربر دکمه Retry ظاهر می‌شود.
        - موفق که شد، حالت Retry پاک می‌شود.
        - تغییر مهم: در حالت Report هیچ‌گاه جعبهٔ متن پاک نمی‌شود (برای حفظ Transcribe/Standard).
        """

        # ✅ HARD GATE: do not allow ANY AI action without validated API key
        if mode in ("Chat", "Report", "Assistant", "Search", "ChatGPT"):
            if not is_active_backend_configured():
                self.controller.bubble("AI ChatBot", "❌ AI backend is not configured. Access denied.")
                return
        images_b64 = list(retry_images or []) if retry_images is not None else self._collect_request_images_base64()
        has_images = bool(images_b64)

        if not text and mode == "Chat" and not has_images:
            return
        if not text and mode == "Search":
            return

        sent_text = (text or "").strip()
        self._pending_retry = {"mode": mode, "text": sent_text, "images": images_b64, "bubble": None}

        # F8: the dictated text is patient content — log its SIZE, never its body.
        _log.debug(
            "[MODE] %s | session=%r | text_chars=%d | images=%d",
            mode, self.controller.session_id, len(sent_text or ""), len(images_b64),
        )

        def _er_for(target_mode: str):
            def er(msg: str):
                # msg اینجا از _run_async قبلاً sanitize شده
                if (msg or "").startswith("❌"):
                    self.controller.bubble("AI ChatBot", msg)
                else:
                    self.controller.bubble("AI ChatBot", f"⚠️ <i>{msg}</i>")

                try:
                    if self._pending_retry and self._pending_retry.get("mode") == target_mode:
                        bub = self._pending_retry.get("bubble")
                        if bub:
                            bub.show_retry(on_click=lambda: self._retry_last_send(),
                                           reason=f"{target_mode.lower()}-failed")
                except Exception:
                    pass

            return er

        def _clear_retry_if(target_mode: str):
            try:
                if self._pending_retry and self._pending_retry.get("mode") == target_mode:
                    bub = self._pending_retry.get("bubble")
                    if bub:
                        bub.clear_retry()
                self._pending_retry = None
            except Exception:
                pass

        # ---------- CHAT ----------
        def ok_chat(resp: dict):
            _dbg_response("CHAT-parsed", None)
            self._log_irannobat_usage_from_resp(resp)   # ✅ NEW
            _clear_retry_if("Chat")
            if has_images and hasattr(self.composer, "clear_image_attachments"):
                self.composer.clear_image_attachments()
            self.controller.handle_chat_response(resp)


        if mode == "Chat":
            if not sent_text and not has_images:
                return
            user_line = sent_text if sent_text else "(image only)"
            if has_images:
                user_line = f"{user_line}\n🖼️ Attached image(s): {len(images_b64)}"
            self.controller.bubble("You", user_line)
            # پاک‌کردن جعبه در Chat
            self.composer.box.clear()

            def work():
                if self.controller.session_id:
                    payload = {"session_id": self.controller.session_id, "user_message": sent_text}
                else:
                    payload = {"user_message": sent_text}
                if has_images:
                    payload["images"] = images_b64
                _dbg_request("CHAT", URL_CHAT, payload)
                r = echomind_http.post(URL_CHAT, json=payload)
                _dbg_response("CHAT", r)
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_chat, _er_for("Chat"), typing="Thinking"))
            return

        # ---------- REPORT ----------
        def ok_report(resp: dict):
            _dbg_response("REPORT-parsed", None)
            self._log_irannobat_usage_from_resp(resp)   # ✅ NEW
            _clear_retry_if("Report")
            if has_images and hasattr(self.composer, "clear_image_attachments"):
                self.composer.clear_image_attachments()

            sid_new = resp.get("session_id")
            if sid_new:
                self.controller.switch_session(sid_new)

            rep_raw_clean = self._normalize_report_like_payload(resp)

            if not (rep_raw_clean or "").strip():
                self.controller.bubble("AI ChatBot", "⚠️ Empty report output.")
                return

            # ✅ store normalized JSON for bubble attachment + later Persian translation
            self._pending_report_raw_en = rep_raw_clean

            items = self._parse_jsonish_list(rep_raw_clean)
            html = self._render_kv_report_html(items)
            self._bubble_origin_hint = "report"
            self.controller.bubble("AI ChatBot", html)



        if mode == "Report":
            report_user_line = sent_text or "(session-based)"
            if has_images:
                report_user_line = f"{report_user_line}\n🖼️ Attached image(s): {len(images_b64)}"
            self.controller.bubble("You (Report)", report_user_line)


            # Inside the if mode == "Report": section of _send_with_mode
            def work():
                payload = {}
                if sent_text:
                    payload["text"] = sent_text
                if modality:  # ← critical
                    payload["modality"] = modality
                # Optional normal template (send only when non-empty)
                try:
                    normal_template_plain = (self.composer.get_normal_template_plain_text() or "").strip()
                except Exception:
                    normal_template_plain = ""

                if normal_template_plain:
                    payload["normal_template"] = normal_template_plain
                    # persist plain text (keeps sessions clean; avoids saving HTML skeleton/style)
                    try:
                        self._persist_normal_template(normal_template_plain)
                    except Exception:
                        pass
                    except Exception:
                        pass
                if self.controller.session_id:
                    payload["session_id"] = self.controller.session_id
                if has_images:
                    payload["images"] = images_b64
                try:
                    gpu_id = int(os.environ.get("PACS_AI_GPU", "").strip() or 0)
                    payload["gpu_id"] = gpu_id
                except Exception:
                    pass
                _dbg_request("REPORT", URL_GEN_REPORT, payload)
                r = echomind_http.post(URL_GEN_REPORT, json=payload)
                _dbg_response("REPORT", r)
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_report, _er_for("Report"),
                                                         typing="Generating report"))
            return

        # ---------- ASSISTANT ----------
        def ok_assistant(resp: dict):
            _dbg_response("ASSISTANT-parsed", None)
            self._log_irannobat_usage_from_resp(resp)   # ✅ NEW

            sid_new = resp.get("session_id")
            if sid_new:
                self.controller.switch_session(sid_new)

            out = (resp.get("assistant_output") or resp.get("assistant") or resp.get("data") or resp)
            _clear_retry_if("Assistant")

            data = self._parse_assistant_dict(out)
            html = self._render_assistant_html(data)

            # ✅ برای Persian ترجمهٔ "متن آزاد" لازم داریم، نه report-json
            try:
                if isinstance(out, str):
                    plain_out = out.strip()
                else:
                    plain_out = json.dumps(out, ensure_ascii=False, indent=2).strip()
            except Exception:
                plain_out = ("" if out is None else str(out)).strip()

            self._bubble_origin_hint = "assistant"
            self._pending_assistant_raw_en = plain_out or None  # ✅ plain text (assistant output)

            self.controller.bubble("AI ChatBot", html)

        if mode == "Assistant":
            if not (sent_text or self.controller.session_id):
                self.controller.bubble("AI ChatBot", "⚠️ <i>Please provide text or open a session first.</i>")
                return
            self.controller.bubble("You (Assistant)", sent_text or "(session-based)")
            if sent_text:
                self.composer.box.clear()

            def work():
                payload = {}
                if sent_text:
                    payload["text"] = sent_text
                if self.controller.session_id:
                    payload["session_id"] = self.controller.session_id

                _dbg_request("ASSISTANT", URL_GEN_ASSISTANT, payload)
                r = echomind_http.post(URL_GEN_ASSISTANT, json=payload)
                _dbg_response("ASSISTANT", r)
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_assistant, _er_for("Assistant"),
                                                         typing="Generating assistant output"))
            return

        # ---------- SEARCH ----------
        def ok_search(resp: dict):
            _dbg_response("SEARCH-parsed", None)
            self._log_irannobat_usage_from_resp(resp) 
            _clear_retry_if("Search")

            # /search typically returns an envelope:
            #   {"response": "<json string OR dict>", "prompt_tokens":..., "completion_tokens":..., "total_tokens":...}
            try:
                if isinstance(resp, dict):
                    # take tokens (optional)
                    tok = {}
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        if k in resp:
                            tok[k] = resp.get(k)

                    # unwrap payload
                    payload = None
                    for key in ("response", "result", "data", "output"):
                        if key in resp:
                            payload = resp.get(key)
                            break
                    if payload is None:
                        payload = resp

                    # parse inner JSON robustly (handles dict, json-string, fenced json, double-encoded json, etc.)
                    parsed = self._parse_assistant_dict(payload)

                    data = parsed if isinstance(parsed, dict) else {"Raw": parsed}

                    # attach tokens as extras (so they show at bottom)
                    for k, v in tok.items():
                        if v is not None and k not in data:
                            data[k] = v
                else:
                    parsed = self._parse_assistant_dict(resp)
                    data = parsed if isinstance(parsed, dict) else {"Raw": str(resp)}

            except Exception as e:
                print("[SEARCH] Failed to unwrap/parse search response:", e)
                data = resp if isinstance(resp, dict) else {"Raw": str(resp)}

            html = self._render_search_html(data)
            self.controller.bubble("AI ChatBot", html)


        if mode == "Search":
            if not sent_text:
                return
            self.controller.bubble("You (Search)", sent_text)
            self.composer.box.clear()

            def work():
                payload = {"user_query": sent_text}
                _dbg_request("SEARCH", URL_SEARCH, payload)
                r = echomind_http.post(URL_SEARCH, json=payload)
                _dbg_response("SEARCH", r)
                r.raise_for_status()
                return r.json()

            QTimer.singleShot(0, lambda: self._run_async(work, ok_search, _er_for("Search"), typing="Searching"))
            return

    # pretty printer
    def _pretty_jsonish(self, s: str) -> str:
        try:
            obj = json.loads(s)
            if isinstance(obj, str):
                try:
                    return json.dumps(json.loads(obj), ensure_ascii=False, indent=2)
                except Exception:
                    return obj
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except Exception:
            return s

    def _parse_assistant_dict(self, out) -> dict:
        import json, ast, re

        if isinstance(out, dict):
            return out

        if isinstance(out, list):
            return {"Items": out}

        s = "" if out is None else str(out)
        s = s.strip()
        if not s:
            return {"Raw": ""}

        def _try_load_dict(text: str):
            """Try JSON -> double-encoded JSON -> python-literal. Return dict or None."""
            if not text:
                return None
            t = text.strip()

            # strip outer fences if user pasted them
            t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.I)
            t = re.sub(r"\s*```\s*$", "", t)

            # JSON
            try:
                obj = json.loads(t)
                if isinstance(obj, dict):
                    return obj
                if isinstance(obj, str):  # دوبار رشته شده
                    try:
                        obj2 = json.loads(obj)
                        if isinstance(obj2, dict):
                            return obj2
                    except Exception:
                        pass
            except Exception:
                pass

            # Python-literal (single quotes, etc.)
            try:
                obj = ast.literal_eval(t)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                pass

            return None

        # 3) اگر کل خروجی JSON تمیز بود
        obj = _try_load_dict(s)
        if obj is not None:
            return obj

        # 4) اگر "Final Output" داشت، از همان بخش به بعد تلاش کن (معمولاً JSON نهایی آنجاست)
        low = s.lower()
        idx = low.rfind("final output")
        if idx != -1:
            tail = s[idx:]
            obj = _try_load_dict(tail)
            if obj is not None:
                return obj

        # 5) مهم‌ترین: همه code-fenceهای ```json ...``` را پیدا کن و از آخری به اولی parse کن
        fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
        for block in reversed(fenced):
            obj = _try_load_dict(block)
            if obj is not None:
                return obj

        # 6) fallback: به جای regex greedy، از استخراج‌گر بالانس‌شده‌ی خودت استفاده کن
        # (این کمک می‌کند اگر متن دور JSON زیاد باشد)
        try:
            # توجه: _normalize_report_like_payload «اولین» JSON را ترجیح می‌دهد،
            # اما ما اینجا بعد از امتحانِ "آخرین fenced" از آن استفاده می‌کنیم.
            norm = self._normalize_report_like_payload(s)
            obj = _try_load_dict(norm)
            if obj is not None:
                return obj
        except Exception:
            pass

        # 7) ناامید شدیم → Raw
        return {"Raw": s}


    def _drop_welcome_if_any(self):
        """Remove the initial welcome bubble if it's on screen."""
        try:
            if getattr(self, "_welcome_bubble", None) is not None:
                self.history.remove_widget(self._welcome_bubble)
                self._welcome_bubble = None
        except Exception:
            pass

    # --- داخل کلاس OneChatPage ---
    def _parse_jsonish_list(self, value) -> list[dict]:

        import json

        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)] or [{"Raw": json.dumps(value, ensure_ascii=False)}]

        if isinstance(value, dict):
            return [value]

        # assume string
        s = self._normalize_report_like_payload(value)

        # try JSON loads (single or double encoded)
        try:
            obj = json.loads(s)
            if isinstance(obj, str):
                try:
                    obj = json.loads(obj)
                except Exception:
                    return [{"Raw": s}]
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)] or [{"Raw": s}]
            if isinstance(obj, dict):
                return [obj]
            return [{"Raw": s}]
        except Exception:
            return [{"Raw": s}]


    def _extract_first_json_block(self, s: str) -> str:
        """
        Extract the first balanced JSON object/array from a messy string.
        Handles text around JSON and ignores braces inside quoted strings.
        Returns original string if no JSON start found.
        """
        import re

        if not s:
            return ""

        # If there's a fenced block anywhere, prefer its inside content
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
        if m:
            s = (m.group(1) or "").strip()

        # Find first '{' or '['
        i_obj = s.find("{")
        i_arr = s.find("[")
        if i_obj == -1 and i_arr == -1:
            return s

        if i_obj == -1:
            start = i_arr
        elif i_arr == -1:
            start = i_obj
        else:
            start = min(i_obj, i_arr)

        # Scan for matching close using a stack, while respecting JSON strings
        stack = []
        in_str = False
        esc = False

        for i in range(start, len(s)):
            ch = s[i]

            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue

            # not in string
            if ch == '"':
                in_str = True
                continue

            if ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack:
                    continue
                opener = stack.pop()
                # best-effort match (ignore mismatch silently)
                if not stack:
                    return s[start:i + 1]

        # If not fully closed, return from start (best effort)
        return s[start:].strip()


    def _normalize_report_like_payload(self, raw) -> str:
        """Normalize HQ/Report/Translate payloads into a clean JSON-ish string.

        Used for report, HQ, and Persian translation parsing.
        It:
        - unwraps common wrapper keys: content/report/response/message/result/output/data
        - strips fenced code blocks
        - fixes broken HTML entities like '& q u o t ;'
        - removes invisible separators (ZW chars, U+2028/2029)
        - extracts the first balanced JSON object/array when possible
        """
        import json
        import re
        from html import unescape

        if raw is None:
            return ""

        def _unwrap(obj):
            for _ in range(6):
                if isinstance(obj, dict):
                    for k in ("content", "report", "response", "message", "result", "output", "data"):
                        if k in obj and obj[k] is not None:
                            obj = obj[k]
                            break
                    else:
                        return obj
                else:
                    return obj
            return obj

        raw = _unwrap(raw)

        # stringify dict/list
        if isinstance(raw, (dict, list)):
            try:
                s = json.dumps(raw, ensure_ascii=False)
            except Exception:
                s = str(raw)
        else:
            s = str(raw)

        s = (s or "").strip()
        if not s:
            return ""

        # Prefer fenced payload if present
        m = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
        if m:
            s = (m.group(1) or "").strip()

        # Remove nasty separators / zero-width chars
        s = s.replace("\ufeff", "").replace("\u2028", "").replace("\u2029", "")
        s = re.sub(r"[\u200b\u200c\u200d\u2060]", "", s)

        # Fix broken HTML entities where characters are separated by whitespace/LS/ZW
        def _fix_entity(m):
            body = m.group(1) or ""
            body = re.sub(r"[\s\u200b\u2028\u2029\u2060]+", "", body)
            return "&" + body + ";"

        s = re.sub(r"&\s*([A-Za-z](?:[A-Za-z\s\u200b\u2028\u2029\u2060]*[A-Za-z])?)\s*;", _fix_entity, s)
        s = re.sub(
            r"&#\s*([0-9][0-9\s\u200b\u2028\u2029\u2060]*)\s*;",
            lambda m: "&#" + re.sub(r"[\s\u200b\u2028\u2029\u2060]+", "", m.group(1)) + ";",
            s,
        )

        # Unescape HTML entities
        try:
            s = unescape(s)
        except Exception:
            pass

        s = s.strip()

        # Extract first JSON block (handles extra text)
        s2 = self._extract_first_json_block(s).strip()
        return s2 or s

    def _render_kv_report_html(self, items: list[dict]) -> str:
        import re, json, ast

        # --------- RTL auto-detect (برای اینکه indent ها RTL درست شوند) ---------
        try:
            flat = []
            for obj in items:
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        flat.append("" if k is None else str(k))
                        flat.append("" if v is None else str(v))
            is_rtl = MessageBubble._has_rtl_chars(" ".join(flat))
        except Exception:
            is_rtl = False

        # Indent styles (LTR vs RTL)
        ul_margin_0 = "margin:0 16px 4px 0; padding:0;" if is_rtl else "margin:0 0 4px 16px; padding:0;"
        ul_margin_4 = "margin:4px 16px 4px 0; padding:0;" if is_rtl else "margin:4px 0 4px 16px; padding:0;"
        inner_margin = "margin-right:4px; margin-left:0; line-height:1.5;" if is_rtl else "margin-left:4px; line-height:1.5;"

        # --------- helpers ---------
        def _strip_unwanted_punct(s: str) -> str:
            if not s:
                return ""
            return (
                s.replace("{", "")
                .replace("}", "")
                .replace(";", "")
                .replace("؛", "")
                .replace("•", "")
            )

        def esc(s: str) -> str:
            s = s or ""
            s = _strip_unwanted_punct(s)
            return (
                s.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )

        _bullet_pat = re.compile(r"^\s*(?:[\u2022\u25CF\-\*\u00B7]|\d+[.)])\s*")

        def _normalize_quotes(s: str) -> str:
            # handle smart quotes that may come from model/server
            return (s or "").replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

        def _maybe_parse_listish(v: object) -> list[str] | None:
            """Parse python-list-like or json-array-like payloads into list[str]."""
            if v is None:
                return None

            if isinstance(v, (list, tuple, set)):
                out = []
                for x in v:
                    xs = "" if x is None else str(x).strip()
                    if xs:
                        out.append(xs)
                return out

            if not isinstance(v, str):
                return None

            s = _normalize_quotes(v).strip()
            if not s:
                return None

            # Strong heuristics to avoid touching normal "(2.3 cm)" style parentheses.
            looks_like_json_array = (s.startswith("[") and s.endswith("]"))
            looks_like_py_collection = (
                (s.startswith("[") and s.endswith("]")) or
                (s.startswith("(") and s.endswith(")") and re.search(r"['\"]\s*,\s*['\"]", s))
            )

            if not (looks_like_json_array or looks_like_py_collection):
                return None

            # Try JSON first for arrays
            if looks_like_json_array:
                try:
                    obj = json.loads(s)
                    if isinstance(obj, list):
                        out = []
                        for x in obj:
                            xs = "" if x is None else str(x).strip()
                            if xs:
                                out.append(xs)
                        return out
                except Exception:
                    pass

            # Fallback: python literal (safe)
            try:
                obj = ast.literal_eval(s)
                if isinstance(obj, (list, tuple, set)):
                    out = []
                    for x in obj:
                        xs = "" if x is None else str(x).strip()
                        if xs:
                            out.append(xs)
                    return out
            except Exception:
                pass

            return None

        def _strip_list_syntax_line(s: str) -> str:
            """Remove only edge list-syntax artifacts like [ '  ,  ] without harming inner parentheses."""
            s = (s or "").strip()
            if not s:
                return ""

            # If the whole line is just wrappers/commas/quotes -> drop it
            if re.fullmatch(r"[\s\[\]\(\)\{\},;'\"]+", s):
                return ""

            # strip leading artifacts
            while True:
                before = s
                s = s.lstrip()

                if s and s[0] in "[{(":
                    s = s[1:]
                    continue
                if s and s[0] in "\"'":
                    s = s[1:]
                    continue
                if s and s[0] in ",;":
                    s = s[1:]
                    continue

                if s == before:
                    break

            # strip trailing artifacts
            while True:
                before = s
                s = s.rstrip()

                if s and s[-1] in "]})":
                    s = s[:-1]
                    continue
                if s and s[-1] in "\"'":
                    s = s[:-1]
                    continue
                if s and s[-1] in ",;":
                    s = s[:-1]
                    continue

                if s == before:
                    break

            return s.strip()

        def _clean_line(s: str) -> str:
            s = _normalize_quotes(s or "")
            s = _strip_list_syntax_line(s)
            s = _bullet_pat.sub("", s).strip()
            s = _strip_unwanted_punct(s)

            # remove invisible separators (just in case)
            s = (
                s.replace("\ufeff", "")
                .replace("\u2028", "")
                .replace("\u2029", "")
            )
            s = re.sub(r"[\u200b\u200c\u200d\u2060]", "", s)

            s = _strip_list_syntax_line(s)
            return s.strip()

        def _split_lines_or_sentences(raw: object) -> list[str]:
            # If it is list / list-like string, normalize to lines first
            seq = _maybe_parse_listish(raw)
            if seq is not None:
                out: list[str] = []
                for x in seq:
                    x = (x or "").replace("\\n", "\n").strip()
                    if not x:
                        continue
                    out.extend([ln.strip() for ln in x.split("\n") if ln.strip()])
                return out

            raw_s = "" if raw is None else str(raw)
            raw_s = _normalize_quotes(raw_s).replace("\\n", "\n").strip()
            if not raw_s:
                return []

            lines = [ln.strip() for ln in raw_s.split("\n") if ln.strip()]
            if len(lines) > 1:
                return lines

            parts = [p.strip() for p in re.split(r"\.(?!\d)", raw_s) if p.strip()]
            if parts:
                fixed = []
                for p in parts:
                    fixed.append(p if p.endswith(".") else (p + "."))
                return fixed

            return [raw_s]

        def to_items(val: object) -> list[str]:
            out: list[str] = []
            for ln in _split_lines_or_sentences(val):
                cl = _clean_line(ln)
                if not cl:
                    continue
                e = esc(cl)
                # drop pure punctuation artifacts
                if e.strip() in (",", "،", "'", '"'):
                    continue
                out.append(e)
            return out

        def to_paragraph_with_breaks(val: object) -> str:
            items2 = to_items(val)
            return "<br>".join(items2) if items2 else ""

        def parse_headed_bullets(val: object):
            groups: list[tuple[str, list[str]]] = []
            lone: list[str] = []
            current_title = None
            bucket: list[str] = []

            for raw_ln in _split_lines_or_sentences(val):
                raw_ln = _strip_unwanted_punct(_normalize_quotes(raw_ln))
                raw_ln = _strip_list_syntax_line(raw_ln)

                # عنوان اگر با ":" تمام شود (و طولش خیلی بلند نباشد)
                is_title = raw_ln.strip().endswith(":") and len(raw_ln.strip()) <= 80

                if is_title:
                    # flush قبلی
                    if current_title is None:
                        lone.extend(esc(_clean_line(x)) for x in bucket)
                    else:
                        groups.append((esc(_clean_line(current_title)), [esc(_clean_line(x)) for x in bucket]))
                    current_title = raw_ln.strip().rstrip(":")
                    bucket = []
                else:
                    cl = _clean_line(raw_ln)
                    if cl:
                        bucket.append(cl)

            # flush آخر
            if bucket:
                if current_title is None:
                    lone.extend(esc(_clean_line(x)) for x in bucket)
                else:
                    groups.append((esc(_clean_line(current_title)), [esc(_clean_line(x)) for x in bucket]))

            return groups, lone

        html_parts: list[str] = []

        for obj in items:
            if not isinstance(obj, dict):
                continue

            for key, val in obj.items():
                if val is None:
                    continue

                # اگر مقدار dict باشد: تبدیل به خطوط "Title: text"
                if isinstance(val, dict):
                    lines = []
                    for subk, subv in val.items():
                        if subv is None:
                            continue
                        subv_str = _strip_unwanted_punct(str(subv).strip())
                        subk_str = _strip_unwanted_punct(str(subk).strip())
                        if not subv_str and not subk_str:
                            continue
                        lines.append(f"{subk_str}: {subv_str}")
                    raw_val = "\n".join(lines).strip()

                # ✅ FIX: اگر لیست واقعی بود، به جای str(list) آن را line-by-line کنیم
                elif isinstance(val, (list, tuple, set)):
                    parts = [str(x).strip() for x in val if str(x).strip()]
                    raw_val = "\n".join(parts).strip()

                else:
                    raw_val = str(val).strip()

                if not raw_val:
                    continue

                key_norm = (key or "").lower().strip()

                # --- Report Title ---
                if key_norm in ("report title", "title"):
                    html_parts.append(
                        "<h2 style='margin:0 0 8px 0; font-size:20px; color:#1f3b77;'>"
                        f"{esc(raw_val)}</h2>"
                    )
                    continue

                # --- Pathological Findings ---
                if key_norm.startswith("pathological"):
                    inner = to_paragraph_with_breaks(raw_val)
                    if not inner:
                        continue
                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#b00020;'>"
                        f"{esc(str(key))}:</div>"
                        f"<div style='{inner_margin}'>{inner}</div>"
                        "</div>"
                    )
                    continue

                # --- Normal Findings ---
                if key_norm.startswith("normal"):
                    groups, lone = parse_headed_bullets(raw_val)
                    section: list[str] = [
                        "<div style='margin-top:8px;'>",
                        "<div style='font-weight:bold; margin-bottom:4px; color:#00695c;'>"
                        f"{esc(str(key))}:</div>",
                    ]

                    for title, bullets in groups:
                        section.append(f"<div style='margin:4px 0 0 0;'><b>{title}</b></div>")
                        if bullets:
                            section.append(f"<ul style='{ul_margin_0}'>")
                            for b in bullets:
                                section.append(f"<li>{b}</li>")
                            section.append("</ul>")

                    if lone:
                        section.append(f"<ul style='{ul_margin_4}'>")
                        for b in lone:
                            section.append(f"<li>{b}</li>")
                        section.append("</ul>")

                    section.append("</div>")
                    html_parts.append("".join(section))
                    continue

                # --- Recommendations (optional) ---
                if (
                    key_norm.startswith("recommend")
                    or key_norm.startswith("follow-up")
                    or key_norm.startswith("follow up")
                    or ("recommend" in key_norm)
                ):
                    low = (raw_val or "").strip().lower()
                    if low in ("none", "n/a", "na", "null", "-"):
                        continue
                    items_clean = to_items(raw_val)
                    if not items_clean:
                        continue

                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#6d4c41;'>"
                        f"{esc(str(key))}:</div>"
                    )
                    if len(items_clean) == 1:
                        html_parts.append(f"<div style='{inner_margin}'>{items_clean[0]}</div></div>")
                    else:
                        html_parts.append(f"<ul style='{ul_margin_0}'>")
                        for line in items_clean:
                            html_parts.append(f"<li>{line}</li>")
                        html_parts.append("</ul></div>")
                    continue

                # --- Impression (optional) ---
                if key_norm.startswith("impression") or key_norm == "impressions":
                    low = (raw_val or "").strip().lower()
                    if low in ("none", "n/a", "na", "null", "-"):
                        continue
                    inner = to_paragraph_with_breaks(raw_val)
                    if not inner:
                        continue

                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#283593;'>"
                        f"{esc(str(key))}:</div>"
                        f"<div style='{inner_margin}'>{inner}</div>"
                        "</div>"
                    )
                    continue

                # --- سایر فیلدها ---
                items_clean = to_items(raw_val)
                if not items_clean:
                    continue

                if len(items_clean) == 1:
                    html_parts.append(
                        "<p style='margin:6px 0 4px 0;'>"
                        "<b style='color:#37474f;'>"
                        f"{esc(str(key))}:</b> {items_clean[0]}"
                        "</p>"
                    )
                else:
                    html_parts.append(
                        "<div style='margin-top:8px;'>"
                        "<div style='font-weight:bold; margin-bottom:4px; color:#37474f;'>"
                        f"{esc(str(key))}:</div>"
                        f"<ul style='{ul_margin_0}'>"
                    )
                    for line in items_clean:
                        html_parts.append(f"<li>{line}</li>")
                    html_parts.append("</ul></div>")

        if not html_parts:
            return "<p><i>No structured report content.</i></p>"

        # root: اگر RTL است، direction/align را همینجا هم enforce کن
        root_style = "line-height:1.5; font-size:15px;"
        if is_rtl:
            root_style += " direction: rtl; text-align: right; unicode-bidi: plaintext;"

        return "<div style='" + root_style + "'>" + "\n".join(html_parts) + "</div>"


    def _render_assistant_html(self, data: dict) -> str:
        import typing as t, re

        def esc(s: t.Any) -> str:
            return ("" if s is None else str(s)).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def is_long_paragraph(s: str) -> bool:
            return isinstance(s, str) and (len(s) > 160 or "\n" in s)

        def render_list(items: list) -> str:
            if not items:
                return ""
            lis = []
            for x in items:
                if isinstance(x, (list, dict)):
                    lis.append(f"<li>{render_value(x)}</li>")
                else:
                    lis.append(f"<li>{esc(x)}</li>")
            return "<ul class='bullets'>" + "".join(lis) + "</ul>"

        def render_kv(d: dict) -> str:
            if not d:
                return ""
            out = []
            for k, v in d.items():
                out.append(f"<div class='minihead'>{esc(k)}</div>")
                out.append(render_value(v))
            return "".join(out)

        def render_imaging(v: t.Union[dict, list, str]) -> str:
            if isinstance(v, dict):
                order = [
                    "General Features",
                    "Ultrasound Findings",
                    "Radiologic Findings",
                    "CT Scan Findings",
                    "MRI Findings",
                ]
                html = []
                for key in order:
                    if key in v:
                        html.append(f"<div class='minihead'>{esc(key)}</div>")
                        html.append(render_value(v[key]))
                for k, vv in v.items():
                    if k not in order:
                        html.append(f"<div class='minihead'>{esc(k)}</div>")
                        html.append(render_value(vv))
                return "".join(html) if html else render_value(v)
            return render_value(v)

        def render_value(v) -> str:
            if v is None:
                return ""
            if isinstance(v, dict):
                return render_kv(v)
            if isinstance(v, list):
                return render_list(v)
            if isinstance(v, str):
                if is_long_paragraph(v):
                    parts = [p.strip() for p in re.split(r"\n{2,}", v.strip()) if p.strip()]
                    if len(parts) > 1:
                        return "".join(f"<p class='para'>{esc(p)}</p>" for p in parts)
                    return f"<p class='para'>{esc(v)}</p>"
                return f"<p class='para'>{esc(v)}</p>"
            return f"<p class='para'>{esc(v)}</p>"

        title = esc(data.get("Mode") or data.get("Title") or "Assistant Analysis")
        context = esc(data.get("Clinical and Radiologic Context") or data.get("Context") or "")
        prim = data.get("Primary Diagnoses") or data.get("Primary Diagnosis")
        step1 = data.get("Step_1_From_Input") or data.get("Step1") or {}
        step2 = data.get("Step_2_Knowledge_Retrieved") or data.get("Step2") or {}
        step3 = data.get("Step_3_Summary") or data.get("Step3") or {}

        step1_html = ""
        if isinstance(step1, dict):
            if step1.get("Extracted_Main_Context"):
                step1_html += f"<div class='minihead'>Extracted Main Context</div>{render_value(step1['Extracted_Main_Context'])}"
            if step1.get("Reasoning"):
                step1_html += f"<div class='minihead'>Reasoning</div>{render_value(step1['Reasoning'])}"
            for k, v in step1.items():
                if k in ("Extracted_Main_Context", "Reasoning"):
                    continue
                step1_html += f"<div class='minihead'>{esc(k)}</div>{render_value(v)}"
        else:
            step1_html = render_value(step1)

        step2_html = ""
        if isinstance(step2, dict):
            ordered = [
                "Diagnosis", "Terminology", "Clinical Findings",
                "Imaging Findings", "Differential Diagnosis",
                "Pathology", "Clinical Issues"
            ]
            for k in ordered:
                if k in step2:
                    if k == "Imaging Findings":
                        step2_html += f"<div class='minihead'>{k}</div>{render_imaging(step2[k])}"
                    else:
                        step2_html += f"<div class='minihead'>{k}</div>{render_value(step2[k])}"
            for k, v in step2.items():
                if k not in ordered:
                    step2_html += f"<div class='minihead'>{esc(k)}</div>{render_value(v)}"
        else:
            step2_html = render_value(step2)

        step3_html = ""
        if isinstance(step3, dict):
            if step3.get("Summary"):
                step3_html += f"<div class='minihead'>Summary</div>{render_value(step3['Summary'])}"
            if step3.get("Follow_up_Recommendations"):
                step3_html += f"<div class='minihead'>Follow-up Recommendations</div>{render_value(step3['Follow_up_Recommendations'])}"
            for k, v in step3.items():
                if k in ("Summary", "Follow_up_Recommendations"):
                    continue
                step3_html += f"<div class='minihead'>{esc(k)}</div>{render_value(v)}"
        else:
            step3_html = render_value(step3)

        used_top = {
            "Mode", "Title", "Clinical and Radiologic Context", "Context",
            "Primary Diagnoses", "Primary Diagnosis",
            "Step_1_From_Input", "Step1", "Step_2_Knowledge_Retrieved", "Step2",
            "Step_3_Summary", "Step3"
        }
        extras_html = []
        for k, v in data.items():
            if k in used_top:
                continue
            extras_html.append(f"<div class='subttl'>{esc(k)}</div>{render_value(v)}")

        html = [
            "<style>",
            ".assistant-card{max-width:900px;width:100%;margin:12px 0;background:#1e1f22;border:1px solid #2e2e2e;border-radius:10px;padding:16px 18px;font-size:15px;}",
            ".title{font-weight:800;color:#eaeaea;margin:0 0 8px;letter-spacing:.3px;font-size:16px;}",
            ".subttl{font-weight:800;margin:12px 0 8px;color:#e0e0e0;font-size:15px;}",
            ".minihead{font-weight:700;margin:8px 0 4px;color:#d0d0d0;font-size:14px;}",
            ".stephdr{font-weight:900;font-size:17px;letter-spacing:.2px;margin:14px 0 6px;}",
            ".para{color:#ddd;line-height:1.6;margin:0 0 8px;font-size:15px;}",
            ".bullets{list-style:disc;list-style-position:inside;margin:0 0 6px 2px;padding:0;color:#dddddd;line-height:1.6;font-size:15px;}",
            ".bullets li{margin:2px 0}",
            ".hr{border-top:1px solid rgba(255,255,255,.08);margin:12px 0}",
            ".step1{color:#e6e6e6;} .step1 .para,.step1 .bullets{color:#dddddd;}"
            ".step1-h{color:#e0e0e0;}"

            ".step2{color:#86b7ff;} .step2 .para,.step2 .bullets{color:#86b7ff;}"
            ".step2-h{color:#93c1ff;}"

            ".step3{color:#ff9b9b;} .step3 .para,.step3 .bullets{color:#ff9b9b;}"
            ".step3-h{color:#ffa6a6;}"
            "</style>",
            "<div class='assistant-card'>",
            f"<div class='title'>{title}</div>",
        ]
        if context:
            html += ["<div class='subttl'>Clinical/Radiologic Context</div>", f"<p class='para'>{context}</p>",
                     "<div class='hr'></div>"]
        if prim:
            html += ["<div class='subttl'>Primary Diagnoses</div>", render_value(prim)]

        if step1_html:
            html += [f"<div class='stephdr step1-h'>Step 1 — From Input</div>",
                     f"<div class='step step1'>{step1_html}</div>"]
        if step2_html:
            html += [f"<div class='stephdr step2-h'>Step 2 — Knowledge Retrieved</div>",
                     f"<div class='step step2'>{step2_html}</div>"]
        if step3_html:
            html += [f"<div class='stephdr step3-h'>Step 3 — Summary</div>",
                     f"<div class='step step3'>{step3_html}</div>"]

        if extras_html:
            html += ["<div class='hr'></div>"] + extras_html
        html.append("</div>")
        return "".join(html)

    def _render_search_html(self, data: dict) -> str:
        """
        Render nice HTML card for /search JSON:
          - Original/Rewritten question
          - Relevant sections
          - Relevant imaging modalities (CT/MRI/US/Radiographic ...)
          - Short answer + reasoning
          - Any extra keys not covered -> at bottom
        """
        import typing as t

        def esc(s: t.Any) -> str:
            s = "" if s is None else str(s)
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def bullets(items: t.Iterable) -> str:
            if not items:
                return ""
            lis = []
            for it in items:
                if isinstance(it, (list, dict)):
                    lis.append(f"<li>{kv(it)}</li>")
                else:
                    lis.append(f"<li>{esc(it)}</li>")
            return "<ul class='bullets'>" + "".join(lis) + "</ul>"

        def kv(d: dict) -> str:
            if not isinstance(d, dict) or not d:
                return ""
            out = []
            for k, v in d.items():
                out.append(f"<div class='minihead'>{esc(k)}</div>")
                out.append(render(v))
            return "".join(out)

        def render(v) -> str:
            if v is None:
                return ""
            if isinstance(v, dict):
                return kv(v)
            if isinstance(v, list):
                return bullets(v)
            return f"<p class='para'>{esc(v)}</p>"

        # known top-level keys
        orig_q = data.get("Original_Question")
        rew_q = data.get("Rewritten_Question")
        rel_sec = data.get("Relevant_Sections")
        rel_modal = data.get("Relevant_Imaging_Modalities") or {}
        short_ans = data.get("Short_Answer")
        reasoning = data.get("Reasoning_and_Summary")

        used = {
            "Original_Question", "Rewritten_Question", "Relevant_Sections",
            "Relevant_Imaging_Modalities", "Short_Answer", "Reasoning_and_Summary"
        }

        # modalities pretty order (then any others)
        mod_order = ["General", "CT Scan", "MRI", "Ultrasound", "Radiographic"]
        mod_html = []
        if isinstance(rel_modal, dict):
            # ordered known
            for m in mod_order:
                if m in rel_modal:
                    mod_html.append(f"<div class='subttl'>{esc(m)}</div>")
                    mod_html.append(render(rel_modal[m]))
            # remaining
            for k, v in rel_modal.items():
                if k not in mod_order:
                    mod_html.append(f"<div class='subttl'>{esc(k)}</div>")
                    mod_html.append(render(v))

        # extras
        extras = []
        for k, v in data.items():
            if k in used:
                continue
            extras.append(f"<div class='subttl'>{esc(k)}</div>{render(v)}")

        html = [
            "<style>",
            ".search-card{max-width:900px;width:100%;margin:12px 0;background:#1e1f22;",
            "border:1px solid #2e2e2e;border-radius:10px;padding:16px 18px}",
            ".title{font-weight:800;color:#e6e6e6;margin:0 0 6px;letter-spacing:.3px}",
            ".subttl{font-weight:700;margin:10px 0 6px;color:#d9d9d9}",
            ".minihead{font-weight:600;margin:8px 0 4px;color:#cfcfcf}",
            ".bullets{list-style:disc;list-style-position:inside;margin:0 0 4px 2px;padding:0;color:#dddddd;line-height:1.55}",
            ".bullets li{margin:1px 0}",
            ".para{color:#ddd;line-height:1.55;margin:0 0 8px}",
            ".hr{border-top:1px solid rgba(255,255,255,.07);margin:12px 0}",
            "</style>",
            "<div class='search-card'>",
            "<div class='title'>Search Results</div>",
        ]
        if orig_q:
            html += ["<div class='subttl'>Original Question</div>", f"<p class='para'>{esc(orig_q)}</p>"]
        if rew_q:
            html += ["<div class='subttl'>Rewritten Question</div>", f"<p class='para'>{esc(rew_q)}</p>"]
        if rel_sec:
            html += ["<div class='subttl'>Relevant Sections</div>", render(rel_sec)]
        if mod_html:
            html += ["<div class='subttl'>Relevant Imaging Modalities</div>"] + mod_html
        if short_ans:
            html += ["<div class='subttl'>Short Answer</div>", f"<p class='para'>{esc(short_ans)}</p>"]
        if reasoning:
            html += ["<div class='subttl'>Reasoning & Summary</div>", f"<p class='para'>{esc(reasoning)}</p>"]
        if extras:
            html += ["<div class='hr'></div>"] + extras

        html.append("</div>")
        return "".join(html)

class ChatGPTPage(OneChatPage):
    """ChatGPT mode — now fully uses global API from input page and never prompts for API."""
    GPT_MODELS = [
        "gpt-5.4",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
        "gpt-4o",
        "gpt-4o-mini",
    ]

    def __init__(self, study_uid: str = None, initial_mode: str = "chat"):
        super().__init__(study_uid=study_uid, page_mode="ChatGPT")
        self.setWindowTitle("AI Chat – ChatGPT")
        self._chatgpt_mode = (initial_mode or "chat").strip().lower() or "chat"
        self._current_model = self._default_model_for_mode(self._chatgpt_mode)
        print(
            f"[ChatGPT] init study_uid={study_uid!r} model={self._current_model} mode={self._chatgpt_mode}"
        )

        # --- Load global API ---
        _backend, self.global_center, self.global_api_key = _resolve_active_ai_identity()
        print(
            f"[ChatGPT] init api_valid={bool(self.global_api_key)} center={self.global_center!r}"
        )

        # --- Layout Setup ---
        right_panel = self.layout().itemAt(1).widget()
        right_layout = right_panel.layout()

        self.model_selector_container = QWidget(self)
        model_layout = QHBoxLayout(self.model_selector_container)
        model_layout.setContentsMargins(12, 6, 12, 6)
        model_layout.setSpacing(8)

        # MODE TOGGLE BUTTON
        button_style = f"""
            QToolButton {{
                background:#3a3a3a;
                color:{CLR_TEXT};
                border:1px solid {CLR_BORDER};
                border-radius:12px;
                padding:4px 10px;
                min-height:32px;
                font-size:13px;
                font-weight:500;
            }}
            QToolButton:hover {{
                background:#4a4a4a;
                border-color:{CLR_ACCENT};
            }}
        """

        self.btn_mode_toggle = QToolButton(self.model_selector_container)
        self.btn_mode_toggle.setText("💬 Chat")
        self.btn_mode_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_mode_toggle.setPopupMode(QToolButton.InstantPopup)
        self.btn_mode_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_mode_toggle.setArrowType(Qt.DownArrow)
        self.btn_mode_toggle.setStyleSheet(button_style)
        menu_mode = QMenu(self)

        from PySide6.QtGui import QPixmap, QPainter, QFont

        # --- ایموجی -> آیکون (برای align شدن) ---
        def _emoji_icon(emoji: str, size: int = 18) -> QIcon:
            pm = QPixmap(size, size)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            f = QFont("Segoe UI Emoji")
            f.setPixelSize(int(size * 0.90))
            p.setFont(f)
            p.drawText(pm.rect(), Qt.AlignCenter, emoji)
            p.end()
            return QIcon(pm)

        menu_mode.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
                padding: 4px;
            }

            QMenu::icon {
                width: 18px;
                height: 18px;
                margin-left: 8px;
                margin-right: 6px;
            }

            QMenu::item {
                padding: 7px 12px 7px 36px;   
                color: #ddd;
                background-color: transparent;
                border-radius: 6px;
                margin: 2px;
            }
            QMenu::item:selected { background-color: #3a3a3a; color: #fff; }
            QMenu::item:hover    { background-color: #4a4a4a; }
        """)

        items = [
            ("💬", "Chat", "chat"),
            ("📄", "Report", "report"),
            ("🖼️", "Image Artifact Analyzer", "image"),
            (None, "Breast Expert Assistant", "breast"),
        ]

        for emoji, text, mode in items:
            if mode == "breast":
                # ✅ دقیقا استفاده از همان تابع _set_icon
                tmp = QPushButton()
                _set_icon(tmp, "breast.jpeg", size=18, tooltip=text)
                act = QAction(tmp.icon(), text, menu_mode)
            else:
                act = QAction(_emoji_icon(emoji, 18), text, menu_mode)

            act.setIconVisibleInMenu(True)
            act.triggered.connect(lambda _, m=mode: self._set_chatgpt_mode(m))
            menu_mode.addAction(act)

        self.btn_mode_toggle.setMenu(menu_mode)

        # MODEL SELECTOR
        self.btn_model = QToolButton(self.model_selector_container)
        self.btn_model.setText(self._current_model)
        self.btn_model.setCursor(Qt.PointingHandCursor)
        self.btn_model.setPopupMode(QToolButton.InstantPopup)
        self.btn_model.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_model.setArrowType(Qt.DownArrow)
        self.btn_model.setStyleSheet(button_style)
        self.btn_model.clicked.connect(self._show_model_menu)

        model_layout.addWidget(self.btn_mode_toggle)
        model_layout.addWidget(self.btn_model)
        model_layout.addStretch(1)

        right_layout.insertWidget(right_layout.count() - 1, self.model_selector_container)

        # TOKEN LABEL
        self.lbl_tokens = QLabel("Tokens: –")
        self.lbl_tokens.setStyleSheet("""
            QLabel {
                color: #888;
                font-size: 11px;
                padding: 4px 8px;
            }
        """)
        self.lbl_tokens.setAlignment(Qt.AlignRight)
        right_layout.insertWidget(right_layout.count() - 1, self.lbl_tokens)

        self._token_usage = load_token_usage()
        self._update_token_display()

        # Ensure UI matches current ChatGPT sub-mode (default: chat)
        try:
            self._set_chatgpt_mode(self._chatgpt_mode)
        except Exception:
            pass

    def _default_model_for_mode(self, mode: str) -> str:
        normalized = str(mode or "chat").strip().lower()
        # 2026-08-02: BACKEND-GATED. This used to read the OpenAI per-feature models
        # UNCONDITIONALLY, so the user's OpenAI model choice leaked into the
        # company/GapGPT pipeline whenever this page ran in company mode. Company
        # mode now uses the company defaults (matching the company functions' own
        # per-function defaults); the OpenAI settings apply only on the OpenAI backend.
        if _ai_backend() != "openai":
            if normalized in ("report",):
                return company_direct.PRIMARY_REPORT_MODEL
            if normalized in ("image", "breast"):
                return "gpt-4.1"
            return "gpt-4.1-mini"
        if normalized == "report":
            return get_openai_model_for_feature("report", company_direct.PRIMARY_REPORT_MODEL)
        if normalized == "image":
            return get_openai_model_for_feature("vision", "gpt-5.4")
        if normalized == "breast":
            return get_openai_model_for_feature("report", company_direct.PRIMARY_REPORT_MODEL)
        return get_openai_model_for_feature("text", "gpt-5-mini")

    def _norm_center_name(self, center: str | None) -> str:
        if not center:
            return "Unknown"
        c = center.strip()
        if c.upper() == "RAZI":
            return "Razi"
        if c.upper() == "MEHR":
            return "Mehr"
        return c

    def _load_global_api(self) -> tuple[str | None, str | None]:
        _backend, center, api_key = _resolve_active_ai_identity()
        return center, api_key

    def _set_chatgpt_mode(self, mode):
        self._chatgpt_mode = mode
        self._current_model = self._default_model_for_mode(mode)
        print(f"[ChatGPT] mode set -> {mode}")

        labels = {
            "chat":   "Chat",
            "report": "Report",
            "image":  "Image Artifact Analyzer",
            "breast": "Breast Expert Assistant",
        }

        label_text = labels.get(mode, "Chat")
        self.btn_mode_toggle.setText(label_text)
        try:
            self.btn_model.setText(self._current_model)
        except Exception:
            pass

        # سپس آیکون (فقط برای breast)
        try:
            if mode == "breast":
                # روش 1: استفاده از مسیر کامل
                icon_path = os.path.join(ICON_PATH, "feather", "breast.jpeg")
                
                # بررسی وجود فایل
                if os.path.exists(icon_path):
                    icon = QIcon(icon_path)
                    if not icon.isNull():
                        self.btn_mode_toggle.setIcon(icon)
                        self.btn_mode_toggle.setIconSize(QSize(18, 18))
                        self.btn_mode_toggle.setText(label_text)
                        self.btn_mode_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
                    else:
                        print(f"[ICON] Icon is null: {icon_path}")
                        self.btn_mode_toggle.setIcon(QIcon())  # پاک کردن آیکون
                else:
                    print(f"[ICON] File not found: {icon_path}")
                    self.btn_mode_toggle.setIcon(QIcon())  # پاک کردن آیکون
            else:
                # برای مودهای دیگر، آیکون را پاک کن
                self.btn_mode_toggle.setIcon(QIcon())
                self.btn_mode_toggle.setIconSize(QSize(0, 0))
        except Exception as e:
            print(f"[ICON] Error loading icon: {e}")
            import traceback
            traceback.print_exc()
            self.btn_mode_toggle.setIcon(QIcon())

        # باقی کدها (بدون تغییر)
        try:
            if hasattr(self.composer, "attach_frame"):
                self.composer.attach_frame.setVisible(mode != "breast")
            if hasattr(self.composer, "_image_attachments") and mode == "breast":
                self.composer._image_attachments.clear()
        except Exception:
            pass

        try:
            show_modality = (mode == "report")
            if hasattr(self.composer, "btn_modality"):
                self.composer.btn_modality.setVisible(show_modality)
            if hasattr(self.composer, "btn_all_modality_hq"):
                self.composer.btn_all_modality_hq.setVisible(show_modality)
        except Exception:
            pass

    def _init_api_key_input(self):
        self._global_center, self._global_key = self._load_global_api()
        if self._global_key:
            self._show_welcome_message()
        else:
            try:
                self.history.add_bubble("AI ChatBot", "❌ API key is not set. Please enter it on the login page only.")
            except Exception:
                pass


    def _prompt_for_api_key(self):
        try:
            self.history.add_bubble("AI ChatBot", "❌ The API key can only be set on the login page.")
        except Exception:
            pass


    def _detect_and_set_center(self, api_key=None):
        self._global_center, self._global_key = self._load_global_api()
        if self._global_key:
            self._show_welcome_message()


    def _show_welcome_message(self):
        center = getattr(self, "_global_center", None) or "Unknown"
        api_key = getattr(self, "_global_key", None) or ""
        api_key = (api_key or "").strip()

        total_tokens = 0
        total_transcript_minutes = 0.0
        usage_html = "<i>No usage data.</i>"

        try:
            from PacsClient.utils.database import (
                get_api_usage_summary_html,
                load_api_token_usage_for_key,
                load_api_transcript_usage_for_key,
            )
            if api_key:
                models = load_api_token_usage_for_key(api_key)
                total_tokens = sum(int(v or 0) for v in models.values())

                tr_models = load_api_transcript_usage_for_key(api_key)  # ✅ minutes
                total_transcript_minutes = sum(float(v or 0.0) for v in tr_models.values())

                usage_html = get_api_usage_summary_html(api_key)
        except Exception:
            pass

        current_model = getattr(self, "_current_model_name", None) or getattr(self, "current_model", None) or "<unknown>"

        msg = (
            f"🎉 <b>Welcome to {center} Center ChatGPT</b><br>"
            f"<b>Current model:</b> {current_model}<br>"
            f"<b>Total tokens (this API):</b> {total_tokens:,}<br><br>"
        )
        if total_transcript_minutes > 0:
            msg += f"<b>Total transcript (this API):</b> {total_transcript_minutes:.1f} min<br><br>"
        msg += f"{usage_html}"

        self.history.clear()
        self.history.add_bubble("AI ChatBot", msg)

    def _update_token_display(self):
        # ✅ robust center name resolver (no get_detected_center_display)
        center = getattr(self, "_global_center", None)

        if not center and get_llm_backend() == "openai":
            center = "OpenAI"

        if not center:
            try:
                info = Manage.instance().ensure_detected()
                center = getattr(info, "center_display", None) or getattr(info, "center", None)
            except Exception:
                center = None

        center = self._norm_center_name(center)
        model = self._current_model
        tokens = self._token_usage.get(center, {}).get(model, 0)
        self.lbl_tokens.setText(f"📊 {model}: {tokens:,} tokens")


    def _show_model_menu(self):
        print("[ChatGPT] open model menu")
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2a2a2a;
                border: 1px solid #4a4a4a;
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 16px;
                color: #ddd;
                background-color: transparent;
                border-radius: 4px;
                margin: 2px;
            }
            QMenu::item:selected {
                background-color: #3a3a3a;
                color: #fff;
            }
            QMenu::item:hover {
                background-color: #4a4a4a;
            }
            QMenu::item:checked {
                background-color: #505050;
                color: #ffd48a;
                font-weight: 600;
            }
        """)

        for model in self.GPT_MODELS:
            act = QAction(model, menu)
            act.setCheckable(True)
            if model == self._current_model:
                act.setChecked(True)
            act.triggered.connect(lambda checked, m=model: self._select_model(m))
            menu.addAction(act)

        menu.exec(self.btn_model.mapToGlobal(self.btn_model.rect().bottomLeft()))

    def _select_model(self, model):
        self._current_model = model
        self.btn_model.setText(model)
        self._update_token_display()
        print(f"[ChatGPT] model set -> {model}")

    def _show_modality_menu(self):
        print("[ChatGPT] open modality menu")
        return super()._show_modality_menu()


    def _send_correction(self, text: str):
        """Correction tab in ChatGPT mode: apply note to selected report."""
        print("[ChatGPT] correction send")
        note = (text or "").strip()
        try:
            report_text = (self.composer.get_selected_correction_report_text() or "").strip()
        except Exception:
            report_text = ""

        if not report_text:
            print("[ChatGPT] correction blocked: report not selected")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please select a report from the Correction dropdown.</i>")
            return
        if not note:
            print("[ChatGPT] correction blocked: empty note")
            self.controller.bubble("AI ChatBot", "⚠️ <i>Please write your correction notes in the box below.</i>")
            return

        self.controller.bubble("You (✅ Correction)", note)

        backend, _center_name, center_key = _resolve_active_ai_identity()
        if not center_key:
            self.controller.bubble("AI ChatBot", "❌ AI backend is not configured. Please complete EchoMind Settings.")
            return
        # Correction is the final targeted-revision step; default to the dedicated (stronger)
        # correction model unless the user explicitly selected a model in ChatGPT mode.
        model = getattr(self, "_current_model", None) or _ai_model("correction", company_direct.PRIMARY_REPORT_MODEL, backend)

        def work():
            return _ai_module(backend).correction(
                user_report=report_text,
                correction_note=note,
                CENTER_Key=center_key,
                model=model,
            )

        def ok(res):
            try:
                rep_raw_clean = self._normalize_report_like_payload(res)
                if not rep_raw_clean.strip():
                    self.controller.bubble("AI ChatBot", "⚠️ Empty output.")
                    return

                self._pending_report_raw_en = rep_raw_clean
                items = self._parse_jsonish_list(rep_raw_clean)
                html = self._render_kv_report_html(items)
                self._bubble_origin_hint = "report"
                self.controller.bubble("AI ChatBot", html)
            except Exception as e:
                self.controller.bubble("AI ChatBot", f"❌ Render error: {e}")

        def er(msg: str):
            self.controller.bubble("AI ChatBot", msg)

        QTimer.singleShot(
            0,
            lambda: self._run_async(
                work, ok, er,
                lock_btn=getattr(self.composer, "btn_send", None),
                typing="Correcting…"
            )
        )



    def _on_send_clicked(self, text: str):
        """Handle text and voice input (override parent)"""
        try:
            voices = self.composer.get_pending_voices()
        except Exception:
            voices = []
        print(
            f"[ChatGPT] send_clicked voices={len(voices)} text_len={len((text or '').strip())} mode={self._chatgpt_mode}"
        )

        if voices:
            current_tab = self.composer.get_active_tab()
            typing_b = self.history.add_typing("AI ChatBot", "Transcribing…")
            self.composer.set_enabled(False)

            def cleanup_ui():
                try:
                    self.history.remove_widget(typing_b)
                    typing_b.stop()
                except Exception:
                    pass
                try:
                    self.composer.set_enabled(True)
                except Exception:
                    pass


            def cont_with_transcript(tr_text: str, server_sid: str | None):
                cleanup_ui()
                merged = (text or "").strip()
                tr_text = (tr_text or "").strip()

                if merged and tr_text:
                    merged = f"{merged}\n{tr_text}"
                elif tr_text:
                    merged = tr_text
                elif not tr_text:
                    self.controller.bubble(
                        "AI ChatBot",
                        """
                        <div style="direction:ltr;text-align:left;">
                        ⚠️ <b>No clear speech detected.</b> 🎧🗣️<br><br>

                        <b>Common causes:</b> 🔇 muted/wrong mic 🎙️, 🔉 low volume/quality, 🌪️ heavy noise, 🔐 missing mic permission.<br>
                        <b>Try:</b> 🧪 test mic, 🔧 select correct input, 📈 raise input/record louder, 🤫 reduce noise, ✅ allow mic access.<br><br>

                        If needed, use <b>Noisy Voice</b> 🟡 from the lower menu 👇
                        </div>
                        """

                    )

                    return

                self._on_send_chatgpt(merged)

            self._upload_voices_then(file_paths=voices, cont=cont_with_transcript)
        else:
            self._on_send_chatgpt(text)

    def _on_send_chatgpt(self, text: str):
        """Send message and track token usage (Chat / Report / Image / Breast modes)"""

        print(
            f"[ChatGPT] send mode={getattr(self, '_chatgpt_mode', None)} model={getattr(self, '_current_model', None)} text_len={len((text or '').strip())}"
        )

        backend, center_name, center_key = _resolve_active_ai_identity()
        if not center_key:
            print("[ChatGPT] blocked: AI backend not configured")
            self.history.add_bubble("AI ChatBot", "❌ AI backend is not configured. Please complete EchoMind Settings first.")
            return
        print(f"[ChatGPT] detected backend={backend} center={center_name!r} key_valid=1")

        # 🔹 Breast Expert Assistant (TEXT-ONLY, NO IMAGE)
        if self._chatgpt_mode == "breast":
            user_text = (text or "").strip()
            if not user_text:
                print("[ChatGPT] breast blocked: empty text")
                return

            self.history.add_bubble("You", f" Breast Question:\n{user_text}")
            self.composer.box.clear()

            typing = self.history.add_typing("ChatGPT", "Consulting Breast Expert.")
            model = self._current_model

            def work():
                try:
                    return _ai_module(backend).BreastExpertAssistant(
                        user_msg=user_text,
                        CENTER_Key=center_key,
                        model=model,
                    )
                except Exception as e:
                    return {"content": f"❌ Breast Expert Error: {str(e)}", "usage": None}

            def done(result: dict):
                self.history.remove_widget(typing)
                typing.stop()

                content = result.get("content", "")
                usage = result.get("usage")

                if usage:
                    _log_usage_for_ui(center_key, usage)
                    self._token_usage = load_token_usage()
                    self._update_token_display()

                if content.startswith("❌"):
                    self.history.add_bubble("ChatGPT", self._safe_user_error(content))
                else:
                    html = f"""
                    <div style='border-left: 3px solid #ff6f61; padding-left: 12px; margin: 10px 0;'>
                        <h3 style='color: #ff6f61'> Breast Expert Assistant</h3>
                        <div style='background: #2b2b2b; padding: 12px; border-radius: 6px; margin-top: 8px;'>
                            {content.replace(chr(10), '<br>')}
                        </div>
                    </div>
                    """
                    self.history.add_bubble("ChatGPT", html)

            worker = ApiWorker(work, parent=self)
            worker.done.connect(done)
            worker.failed.connect(lambda msg: done({"content": _safe_fa_connection_error(msg), "usage": None}))
            worker.start()
            return

        # -----------------------------
        # Image Analyzer (WITH IMAGE UPLOAD)
        # -----------------------------
        if self._chatgpt_mode == "image":
            file_path = None
            if hasattr(self.composer, "get_last_image_attachment"):
                file_path = self.composer.get_last_image_attachment()

            if not file_path:
                file_path, _ = QFileDialog.getOpenFileName(
                    self,
                    "Select Image for Analysis",
                    "",
                    "Images (*.png *.jpg *.jpeg *.bmp *.dcm);All Files (*.*)",
                )
                if not file_path:
                    print("[ChatGPT] image blocked: no file selected")
                    return

            filename = os.path.basename(file_path)
            user_note = (text or "").strip()

            display_msg = f"🖼️ Analyzing: {filename}" + (f"\n📝 Note: {user_note}" if user_note else "")
            self._append_bubble("You", display_msg)

            if hasattr(self.composer, "clear_image_attachments"):
                self.composer.clear_image_attachments()

            typing = self.history.add_typing("ChatGPT", "Analyzing Image Quality.")
            model = self._current_model

            def work():
                try:
                    return _ai_module(backend).ImageQualityAnalyzer(
                        user_msg=user_note,
                        CENTER_Key=center_key,
                        model=model,
                        image_path=file_path,
                    )
                except Exception as e:
                    return {"content": f"❌ Error: {str(e)}", "usage": None}

            def done(result: dict):
                self.history.remove_widget(typing)
                typing.stop()

                content = result.get("content", "")
                usage = result.get("usage")

                if usage:
                    _log_usage_for_ui(center_key, usage)
                    self._token_usage = load_token_usage()
                    self._update_token_display()

                if content.startswith("❌"):
                    self._append_bubble("ChatGPT", self._safe_user_error(content))
                else:
                    html = f"""
                    <div style='border-left: 3px solid #4a90e2; padding-left: 12px; margin: 10px 0;'>
                        <h3 style='color: #4a90e2'>🖼️ Image Quality Analysis</h3>
                        <div style='background: #2b2b2b; padding: 12px; border-radius: 6px; margin-top: 8px;'>
                            {content.replace(chr(10), '<br>')}
                        </div>
                    </div>
                    """
                    self._bubble_origin_hint = "image"
                    self._append_bubble("ChatGPT", html)

            worker = ApiWorker(work, parent=self)
            worker.done.connect(done)
            worker.failed.connect(lambda msg: done({"content": _safe_fa_connection_error(msg), "usage": None}))
            worker.start()
            return

        # -----------------------------
        # Chat / Report (NO IMAGE)
        # -----------------------------
        # In ChatGPT report mode, enforce selecting modality before sending
        modality = None
        normal_template = None
        if self._chatgpt_mode == "report":
            modality = getattr(self, "_current_modality", None)
            if not modality:
                print("[ChatGPT] report blocked: modality not selected")
                self.history.add_bubble("ChatGPT", "⚠️ <i>Please select a modality first.</i>")
                try:
                    # Open dropdown immediately to match Report pages UX
                    self._show_modality_menu()
                except Exception:
                    pass
                return
            try:
                # 2026-08-01: was `get_normal_template_text()`, which returns
                # `QTextEdit.toHtml()` — a full HTML document with a <style>
                # block, <meta>, and a font-family span on every paragraph. The
                # physician's template reached the model buried in Qt CSS, and
                # differently from the Turbo path, which has always sent plain
                # text. Same feature, same shape, on every path.
                normal_template = (self.composer.get_normal_template_plain_text() or "").strip() or None
            except Exception:
                normal_template = None

        user_text = (text or "").strip()
        if not user_text:
            print("[ChatGPT] blocked: empty text")
            return

        self.history.add_bubble("You", user_text)
        self.composer.box.clear()

        typing = self.history.add_typing("ChatGPT", "Thinking.")
        model = self._current_model
        mode = self._chatgpt_mode  # "chat" | "report"

        # In ChatGPT "Report" sub-mode we require a modality selection before sending
        modality = None
        normal_template = None
        if mode == "report":
            modality = getattr(self, "_current_modality", None)
            if not modality:
                print("[ChatGPT] report blocked: modality not selected (late check)")
                # Ask user to select modality first (same behavior as Report pages)
                try:
                    self.history.add_bubble("ChatGPT", "⚠️ <i>Please select a modality first.</i>")
                except Exception:
                    pass
                try:
                    self._show_modality_menu()
                except Exception:
                    pass
                return
            try:
                # 2026-08-01: was `get_normal_template_text()`, which returns
                # `QTextEdit.toHtml()` — a full HTML document with a <style>
                # block, <meta>, and a font-family span on every paragraph. The
                # physician's template reached the model buried in Qt CSS, and
                # differently from the Turbo path, which has always sent plain
                # text. Same feature, same shape, on every path.
                normal_template = (self.composer.get_normal_template_plain_text() or "").strip() or None
            except Exception:
                normal_template = None

        def work():
            try:
                if mode == "chat":
                    _log.debug("[ChatGPT] chat backend=%s model=%s", backend, model)
                    return _ai_module(backend).chat(
                        user_msg=user_text, CENTER_Key=center_key, model=model
                    )
                else:
                    _log.debug(
                        "[ChatGPT] report backend=%s model=%s modality=%s",
                        backend, model, modality,
                    )
                    return _ai_module(backend).reporter(
                        user_msg=user_text,
                        modality=modality,
                        normal_template=normal_template,
                        CENTER_Key=center_key,
                        model=model,
                    )
            except Exception as e:
                return {"content": f"❌ Error: {str(e)}", "usage": None}

        def done(result: dict):
            self.history.remove_widget(typing)
            typing.stop()

            content = result.get("content", "")
            usage = result.get("usage")
            # 2026-07-31 — this printed the ENTIRE generated report, and the
            # usage object, to stdout on every ChatGPT-page response. Same rule
            # as F8: record the SIZE, never the body.
            _dbg_response("CHATGPT-parsed", None)
            _log.debug("[CHATGPT] content_chars=%d usage=%s",
                       len(content or ""), bool(usage))
            if usage:
                _log_usage_for_ui(center_key, usage)
                self._token_usage = load_token_usage()
                self._update_token_display()

            if content.startswith("❌"):
                self._append_bubble("ChatGPT", self._safe_user_error(content))
                return

            cleaned = (content or "").strip()
            if "<|end|>" in cleaned:
                cleaned = cleaned.split("<|end|>", 1)[0].strip()

            if mode == "report":
                try:
                    # ✅ دقیقا مثل صفحه Report: normalize → parse → render
                    rep_raw_clean = self._normalize_report_like_payload(result)

                    # fallback (اگر به هر دلیلی result چیزی نداد)
                    if not (rep_raw_clean or "").strip():
                        rep_raw_clean = self._normalize_report_like_payload(cleaned)

                    if not (rep_raw_clean or "").strip():
                        self.history.add_bubble("ChatGPT", "⚠️ <i>Empty report output.</i>")
                        return

                    # برای Persian/Edit (اگر داری) ذخیره کن
                    self._pending_report_raw_en = rep_raw_clean
                    items = self._parse_jsonish_list(rep_raw_clean)
                    html = self._render_kv_report_html(items)

                    self._bubble_origin_hint = "report"

                    on_edit = getattr(self, "_edit_bubble", None)
                    on_persian = getattr(self, "_persian_bubble", None)
                    on_send_reception = getattr(self, "_send_to_reception", None)

                    bub = self.history.add_bubble("ChatGPT", html, on_edit=on_edit, on_persian=on_persian, on_send_reception=on_send_reception)
                    try:
                        bub.raw_report_json = rep_raw_clean
                    except Exception:
                        pass

                except Exception:
                    from html import escape
                    self.history.add_bubble(
                        "ChatGPT",
                        f"<pre style='background:#2b2b2b;padding:12px;border-radius:6px;'>{escape(cleaned)}</pre>"
                    )
            else:
                self.history.add_bubble("ChatGPT", cleaned)


        worker = ApiWorker(work, parent=self)
        worker.done.connect(done)
        worker.failed.connect(lambda msg: done({"content": _safe_fa_connection_error(msg), "usage": None}))
        worker.start()
