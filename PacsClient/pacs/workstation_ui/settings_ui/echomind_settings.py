from __future__ import annotations

from datetime import datetime
from pathlib import Path
import typing as t

import requests
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from modules.EchoMind.api_manager import APIKeyManager, Manage
from modules.EchoMind.llm_client import get_active_backend_display_name, is_active_backend_configured
from modules.EchoMind.settings_store import (
    get_echomind_api_key,
    get_llm_backend,
    get_openai_settings,
    get_prompt_settings,
    get_proxy_settings,
    get_secretary_stt_route,
    save_openai_settings,
    save_prompt_settings,
    save_proxy_settings,
    set_echomind_api_key,
    set_llm_backend,
    set_secretary_stt_route,
)
from PacsClient.utils.database import get_api_usage_rows_for_key, load_api_transcript_usage_for_key


def _mask_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return "-"
    if len(key) <= 10:
        return key[:2] + "..." + key[-2:]
    return key[:4] + "..." + key[-4:]


class EchoMindSettingsWidget(QWidget):
    _OPENAI_CHAT_MODELS = [
        "gpt-5.4",
        "gpt-5.1",
        "gpt-5",
        "gpt-5-mini",
    ]
    _OPENAI_TRANSCRIPTION_MODELS = [
        "gpt-4o-transcribe",
        "gpt-4o-mini-transcribe",
        "gpt-4o-transcribe-diarize",
        "whisper-1",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_initial_state()

    def _build_ui(self):
        self.setObjectName("EchoMindSettingsWidget")
        arrow_icon = Path("Qss/icons/fefefe/material_design/keyboard_arrow_down.png").resolve().as_posix()
        style = """
            QWidget#EchoMindSettingsWidget {
                background-color: #0b0d10;
                color: #e5e7eb;
            }
            QWidget#EchoMindSettingsWidget QGroupBox {
                background-color: #10141a;
                border: 1px solid #232a33;
                border-radius: 12px;
                margin-top: 32px;
                padding: 18px 20px 18px 20px;
                padding-top: 46px;
                font-weight: 700;
            }
            QWidget#EchoMindSettingsWidget QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 18px;
                top: 2px;
                padding: 7px 18px;
                color: #f3f4f6;
                font-size: 28px;
                font-weight: 900;
                background-color: #0f1319;
                border: 1px solid #232a33;
                border-radius: 11px;
            }
            QWidget#EchoMindSettingsWidget QLabel {
                font-size: 14px;
            }
            QWidget#EchoMindSettingsWidget QLabel[valueLabel="true"] {
                font-size: 15px;
                font-weight: 600;
                color: #93c5fd;
                background-color: #0f1319;
                border: 1px solid #232a33;
                border-radius: 6px;
                padding: 8px 12px;
                min-height: 34px;
            }
            QWidget#EchoMindSettingsWidget QLabel[sectionNote="true"] {
                color: #94a3b8;
                font-size: 13px;
                line-height: 1.4;
            }
            QWidget#EchoMindSettingsWidget QLineEdit,
            QWidget#EchoMindSettingsWidget QComboBox,
            QWidget#EchoMindSettingsWidget QTextEdit,
            QWidget#EchoMindSettingsWidget QSpinBox,
            QWidget#EchoMindSettingsWidget QDoubleSpinBox {
                background-color: #1b2230;
                color: #e2e8f0;
                border: 1px solid #2b313b;
                border-radius: 6px;
                padding: 7px 11px;
                min-height: 34px;
                font-size: 14px;
            }
            QWidget#EchoMindSettingsWidget QComboBox {
                padding-right: 34px;
            }
            QWidget#EchoMindSettingsWidget QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid #2b313b;
            }
            QWidget#EchoMindSettingsWidget QComboBox::down-arrow {
                image: url(__ARROW__);
                width: 14px;
                height: 14px;
            }
            QWidget#EchoMindSettingsWidget QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #1e40af;
                border-radius: 8px;
                padding: 9px 14px;
                min-height: 36px;
                font-size: 14px;
                font-weight: 600;
            }
            QWidget#EchoMindSettingsWidget QPushButton:hover {
                background-color: #1d4ed8;
            }
            QWidget#EchoMindSettingsWidget QPushButton[role="secondary"] {
                background-color: #1b2230;
                border: 1px solid #2b313b;
            }
            QWidget#EchoMindSettingsWidget QPushButton[role="secondary"]:hover {
                background-color: #252d3d;
            }
            QWidget#EchoMindSettingsWidget QPushButton[role="success"] {
                background-color: #16a34a;
                border: 1px solid #15803d;
                font-weight: 700;
            }
            QWidget#EchoMindSettingsWidget QPushButton[role="success"]:hover {
                background-color: #15803d;
            }
            QWidget#EchoMindSettingsWidget QLabel[state="success"] {
                color: #10b981;
                border-color: #065f46;
                background-color: #064e3b;
            }
            QWidget#EchoMindSettingsWidget QLabel[state="warning"] {
                color: #f59e0b;
                border-color: #92400e;
                background-color: rgba(245, 158, 11, 0.12);
            }
            QWidget#EchoMindSettingsWidget QLabel[state="error"] {
                color: #fca5a5;
                border-color: #991b1b;
                background-color: rgba(220, 38, 38, 0.14);
            }
            QWidget#EchoMindSettingsWidget QScrollArea {
                border: none;
                background: transparent;
            }
            """
        self.setStyleSheet(style.replace("__ARROW__", arrow_icon))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        self._body = QWidget()
        scroll.setWidget(self._body)

        self._root = QVBoxLayout(self._body)
        self._root.setContentsMargins(14, 14, 14, 14)
        self._root.setSpacing(14)

        self._build_header()
        self._build_backend_group()
        self._build_proxy_group()
        self._build_company_auth_group()
        self._build_openai_group()
        self._build_prompt_group()
        self._build_usage_group()
        self._build_stt_group()
        self._root.addStretch(1)

    def _note_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setProperty("sectionNote", True)
        return label

    def _compact_value(self, label: QLabel, width: int):
        label.setMaximumWidth(width)

    def _build_header(self):
        title = QLabel("EchoMind Settings")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f3f4f6;")
        self._root.addWidget(title)

        subtitle = QLabel(
            "Configure EchoMind authentication, backend selection, OpenAI direct connection, prompts, and Secretary voice-to-text."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #9ca3af; font-size: 14px; margin-bottom: 6px;")
        self._root.addWidget(subtitle)

    def _build_backend_group(self):
        self.backend_group = QGroupBox("AI Backend")
        group = self.backend_group
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(12)

        self.backend_combo = QComboBox()
        self.backend_combo.addItem("AI PACS Ecomind Backend", userData="company")
        self.backend_combo.addItem("OpenAI Direct Backend", userData="openai")
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self.backend_combo.setMaximumWidth(340)

        self.backend_status = QLabel("Backend not configured")
        self.backend_status.setProperty("valueLabel", True)
        self.backend_status.setProperty("state", "warning")
        self.backend_status.setWordWrap(True)
        self.backend_status.setMinimumWidth(280)
        self.backend_status.setMaximumWidth(440)

        self.backend_help = self._note_label("")

        self.backend_save_btn = QPushButton("Save Backend Selection")
        self.backend_save_btn.setProperty("role", "success")
        self.backend_save_btn.setMaximumWidth(220)
        self.backend_save_btn.clicked.connect(self._on_save_backend_clicked)

        self.backend_saved_label = QLabel("")
        self.backend_saved_label.setProperty("valueLabel", True)
        self.backend_saved_label.setProperty("state", "success")
        self.backend_saved_label.setVisible(False)

        layout.addWidget(QLabel("Backend Provider:"), 0, 0)
        layout.addWidget(self.backend_combo, 0, 1)
        layout.addWidget(QLabel("Current Status:"), 0, 2)
        layout.addWidget(self.backend_status, 0, 3)
        layout.addWidget(self.backend_help, 1, 0, 1, 4)

        save_row = QHBoxLayout()
        save_row.addWidget(self.backend_save_btn)
        save_row.addWidget(self.backend_saved_label)
        save_row.addStretch(1)
        layout.addLayout(save_row, 2, 0, 1, 4)

        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        self._root.addWidget(group)

    def _build_proxy_group(self):
        self.proxy_group = QGroupBox("Network / Proxy")
        group = self.proxy_group
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(12)

        layout.addWidget(
            self._note_label(
                "Applies to both AI PACS EchoMind and OpenAI Direct backend connections. "
                "When SOCKS5 is selected, all EchoMind API calls are tunnelled through the local proxy at 127.0.0.1. "
                "Requires the requests[socks] package (PySocks) to be installed."
            ),
            0, 0, 1, 4,
        )

        self.proxy_type_combo = QComboBox()
        self.proxy_type_combo.addItem("Direct (No Proxy)", userData="direct")
        self.proxy_type_combo.addItem("SOCKS5 Proxy \u2014 127.0.0.1", userData="socks5")
        self.proxy_type_combo.setMaximumWidth(300)
        self.proxy_type_combo.currentIndexChanged.connect(self._on_proxy_type_changed)

        self.proxy_port_label = QLabel("Port:")
        self.proxy_port_combo = QComboBox()
        self.proxy_port_combo.addItem("2080", userData=2080)
        self.proxy_port_combo.addItem("2081", userData=2081)
        self.proxy_port_combo.addItem("2082", userData=2082)
        self.proxy_port_combo.setMaximumWidth(120)

        layout.addWidget(QLabel("Connection:"), 1, 0)
        layout.addWidget(self.proxy_type_combo, 1, 1)
        layout.addWidget(self.proxy_port_label, 1, 2)
        layout.addWidget(self.proxy_port_combo, 1, 3)

        self.proxy_save_btn = QPushButton("Save Proxy Settings")
        self.proxy_save_btn.setProperty("role", "success")
        self.proxy_save_btn.setMaximumWidth(200)
        self.proxy_save_btn.clicked.connect(self._on_save_proxy_clicked)

        self.proxy_saved_label = QLabel("")
        self.proxy_saved_label.setProperty("valueLabel", True)
        self.proxy_saved_label.setProperty("state", "success")
        self.proxy_saved_label.setVisible(False)

        save_row = QHBoxLayout()
        save_row.addWidget(self.proxy_save_btn)
        save_row.addWidget(self.proxy_saved_label)
        save_row.addStretch(1)
        layout.addLayout(save_row, 2, 0, 1, 4)

        layout.setColumnStretch(1, 1)
        self._root.addWidget(group)

    def _build_company_auth_group(self):
        self.company_auth_group = QGroupBox("Company Authentication")
        group = self.company_auth_group
        layout = QVBoxLayout(group)
        layout.setSpacing(12)

        layout.addWidget(
            self._note_label(
                "Used only for the current AI PACS EchoMind / GapGPT backend. This section is hidden when OpenAI direct mode is selected."
            )
        )

        row = QHBoxLayout()
        row.setSpacing(10)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("Enter EchoMind credential / access key")
        row.addWidget(self.key_input, 1)

        self.auth_btn = QPushButton("Authenticate")
        self.auth_btn.setProperty("role", "success")
        self.auth_btn.setMaximumWidth(160)
        self.auth_btn.clicked.connect(self._on_authenticate_clicked)
        row.addWidget(self.auth_btn)

        self.auth_status = QLabel("Not authenticated")
        self.auth_status.setProperty("valueLabel", True)
        self.auth_status.setProperty("state", "warning")
        self.auth_status.setMaximumWidth(360)

        layout.addLayout(row)
        layout.addWidget(self.auth_status)
        self._root.addWidget(group)

    def _new_prompt_editor(self, placeholder: str) -> QTextEdit:
        edit = QTextEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMinimumHeight(88)
        return edit

    def _new_model_combo(self, options: list[str], *, width: int = 320) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(options)
        combo.setMaximumWidth(width)
        return combo

    def _set_combo_value(self, combo: QComboBox, value: str):
        normalized = (value or "").strip()
        if not normalized:
            combo.setCurrentIndex(0)
            return
        idx = combo.findText(normalized, Qt.MatchFixedString)
        if idx < 0:
            combo.addItem(normalized)
            idx = combo.findText(normalized, Qt.MatchFixedString)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _build_openai_group(self):
        self.openai_group = QGroupBox("OpenAI Direct Connection")
        group = self.openai_group
        layout = QVBoxLayout(group)
        layout.setSpacing(14)

        layout.addWidget(
            self._note_label(
                "Use an OpenAI API key from your own platform account with API billing enabled. "
                "A ChatGPT subscription alone does not create API access. Organization and Project "
                "headers are optional. This EchoMind path lists chat-completions-compatible OpenAI models."
            )
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        self.openai_api_key_input = QLineEdit()
        self.openai_api_key_input.setEchoMode(QLineEdit.Password)
        self.openai_api_key_input.setPlaceholderText("sk-...")
        grid.addWidget(QLabel("OpenAI API Key *"), 0, 0)
        grid.addWidget(self.openai_api_key_input, 0, 1, 1, 3)

        self.openai_base_url_input = QLineEdit()
        self.openai_base_url_input.setPlaceholderText("https://api.openai.com/v1")
        grid.addWidget(QLabel("Base URL (Optional)"), 1, 0)
        grid.addWidget(self.openai_base_url_input, 1, 1, 1, 3)

        self.openai_org_input = QLineEdit()
        self.openai_org_input.setPlaceholderText("Optional organization header")
        self.openai_org_input.setMaximumWidth(320)
        self.openai_project_input = QLineEdit()
        self.openai_project_input.setPlaceholderText("Optional project header")
        self.openai_project_input.setMaximumWidth(320)
        grid.addWidget(QLabel("Organization ID (Optional)"), 2, 0)
        grid.addWidget(self.openai_org_input, 2, 1)
        grid.addWidget(QLabel("Project ID (Optional)"), 2, 2)
        grid.addWidget(self.openai_project_input, 2, 3)

        self.openai_text_model_input = self._new_model_combo(self._OPENAI_CHAT_MODELS)
        self.openai_report_model_input = self._new_model_combo(self._OPENAI_CHAT_MODELS)
        self.openai_vision_model_input = self._new_model_combo(self._OPENAI_CHAT_MODELS)
        self.openai_secretary_model_input = self._new_model_combo(self._OPENAI_CHAT_MODELS)
        self.openai_transcription_model_input = self._new_model_combo(self._OPENAI_TRANSCRIPTION_MODELS)

        grid.addWidget(QLabel("Text Model (Optional)"), 3, 0)
        grid.addWidget(self.openai_text_model_input, 3, 1)
        grid.addWidget(QLabel("Report Model (Optional)"), 3, 2)
        grid.addWidget(self.openai_report_model_input, 3, 3)
        grid.addWidget(QLabel("Vision Model (Optional)"), 4, 0)
        grid.addWidget(self.openai_vision_model_input, 4, 1)
        grid.addWidget(QLabel("Secretary Model (Optional)"), 4, 2)
        grid.addWidget(self.openai_secretary_model_input, 4, 3)
        grid.addWidget(QLabel("Transcription Model (Optional)"), 5, 0)
        grid.addWidget(self.openai_transcription_model_input, 5, 1)

        self.openai_reasoning_combo = QComboBox()
        self.openai_reasoning_combo.addItem("Default", userData="")
        self.openai_reasoning_combo.addItem("None", userData="none")
        self.openai_reasoning_combo.addItem("Minimal", userData="minimal")
        self.openai_reasoning_combo.addItem("Low", userData="low")
        self.openai_reasoning_combo.addItem("Medium", userData="medium")
        self.openai_reasoning_combo.addItem("High", userData="high")
        self.openai_reasoning_combo.addItem("XHigh", userData="xhigh")
        self.openai_reasoning_combo.setMaximumWidth(180)
        grid.addWidget(QLabel("Reasoning Effort (Optional)"), 5, 2)
        grid.addWidget(self.openai_reasoning_combo, 5, 3)

        self.openai_temperature_spin = QDoubleSpinBox()
        self.openai_temperature_spin.setRange(0.0, 2.0)
        self.openai_temperature_spin.setSingleStep(0.1)
        self.openai_temperature_spin.setDecimals(2)
        self.openai_temperature_spin.setMaximumWidth(140)

        self.openai_max_tokens_spin = QSpinBox()
        self.openai_max_tokens_spin.setRange(1, 32000)
        self.openai_max_tokens_spin.setMaximumWidth(160)

        self.openai_timeout_spin = QSpinBox()
        self.openai_timeout_spin.setRange(5, 600)
        self.openai_timeout_spin.setMaximumWidth(140)

        grid.addWidget(QLabel("Temperature (Optional)"), 6, 0)
        grid.addWidget(self.openai_temperature_spin, 6, 1)
        grid.addWidget(QLabel("Max Output Tokens (Optional)"), 6, 2)
        grid.addWidget(self.openai_max_tokens_spin, 6, 3)
        grid.addWidget(QLabel("Timeout (sec) (Optional)"), 7, 0)
        grid.addWidget(self.openai_timeout_spin, 7, 1)

        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)

        requirement_note = self._note_label(
            "* Required for connection. All other OpenAI fields are optional because this page provides default "
            "models and default connection values. OpenAI currently recommends GPT-5.4 for highest capability "
            "and GPT-5-mini for lower cost and latency. Reasoning effort support depends on the selected model."
        )
        layout.addWidget(requirement_note)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        self.openai_save_btn = QPushButton("Save OpenAI Settings")
        self.openai_save_btn.setProperty("role", "success")
        self.openai_save_btn.clicked.connect(self._on_save_openai_clicked)
        btn_row.addWidget(self.openai_save_btn)

        self.openai_test_btn = QPushButton("Test OpenAI Connection")
        self.openai_test_btn.setProperty("role", "secondary")
        self.openai_test_btn.clicked.connect(self._on_test_openai_clicked)
        btn_row.addWidget(self.openai_test_btn)
        layout.addLayout(btn_row)

        self.openai_status = QLabel("OpenAI backend not saved")
        self.openai_status.setProperty("valueLabel", True)
        self.openai_status.setProperty("state", "warning")
        self.openai_status.setMaximumWidth(480)
        layout.addWidget(self.openai_status)
        self._root.addWidget(group)

    def _build_prompt_group(self):
        self.prompt_group = QGroupBox("Prompt Configuration")
        group = self.prompt_group
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(12)
        layout.addWidget(
            self._note_label(
                "Prompt fields are used by the OpenAI direct backend. They are hidden when the company backend is selected."
            ),
            0,
            0,
            1,
            2,
        )

        self.prompt_report_edit = self._new_prompt_editor("Prompt for OpenAI report generation")
        self.prompt_breast_edit = self._new_prompt_editor("Prompt for Breast module / assistant")
        self.prompt_secretary_routing_edit = self._new_prompt_editor("Prompt for Secretary routing")
        self.prompt_secretary_action_edit = self._new_prompt_editor("Prompt for Secretary action planning")
        self.prompt_transcript_cleanup_edit = self._new_prompt_editor("Prompt for transcript cleanup after OpenAI transcription")
        self.prompt_image_artifact_edit = self._new_prompt_editor("Prompt for image artifact / quality analysis")

        layout.addWidget(QLabel("Report Generation Prompt:"), 1, 0)
        layout.addWidget(self.prompt_report_edit, 2, 0)
        layout.addWidget(QLabel("Breast Prompt:"), 1, 1)
        layout.addWidget(self.prompt_breast_edit, 2, 1)
        layout.addWidget(QLabel("Secretary Routing Prompt:"), 3, 0)
        layout.addWidget(self.prompt_secretary_routing_edit, 4, 0)
        layout.addWidget(QLabel("Secretary Action Prompt:"), 3, 1)
        layout.addWidget(self.prompt_secretary_action_edit, 4, 1)
        layout.addWidget(QLabel("Transcript Cleanup Prompt:"), 5, 0)
        layout.addWidget(self.prompt_transcript_cleanup_edit, 6, 0)
        layout.addWidget(QLabel("Image Artifact Prompt:"), 5, 1)
        layout.addWidget(self.prompt_image_artifact_edit, 6, 1)

        self.prompt_save_btn = QPushButton("Save Prompt Settings")
        self.prompt_save_btn.setProperty("role", "success")
        self.prompt_save_btn.clicked.connect(self._on_save_prompts_clicked)
        layout.addWidget(self.prompt_save_btn, 7, 1, alignment=Qt.AlignRight)
        self._root.addWidget(group)

    def _build_usage_group(self):
        self.usage_group = QGroupBox("Account / Usage")
        group = self.usage_group
        layout = QVBoxLayout(group)
        layout.setSpacing(12)

        layout.addWidget(
            self._note_label(
                "Read-only summary for whichever backend is currently selected above."
            )
        )

        header = QHBoxLayout()
        header.addStretch(1)
        self.refresh_usage_btn = QPushButton("Refresh Usage")
        self.refresh_usage_btn.setProperty("role", "secondary")
        self.refresh_usage_btn.clicked.connect(self._on_refresh_clicked)
        header.addWidget(self.refresh_usage_btn)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setContentsMargins(8, 8, 8, 8)

        self.center_value = QLabel("-")
        self.center_value.setProperty("valueLabel", True)
        self.center_code_value = QLabel("-")
        self.center_code_value.setProperty("valueLabel", True)
        self.key_mask_value = QLabel("-")
        self.key_mask_value.setProperty("valueLabel", True)
        self.total_tokens_value = QLabel("0")
        self.total_tokens_value.setProperty("valueLabel", True)
        self.total_transcript_value = QLabel("0 min")
        self.total_transcript_value.setProperty("valueLabel", True)
        self.usage_entries_value = QLabel("0")
        self.usage_entries_value.setProperty("valueLabel", True)
        self.token_models_value = QLabel("0")
        self.token_models_value.setProperty("valueLabel", True)
        self.transcript_models_value = QLabel("0")
        self.transcript_models_value.setProperty("valueLabel", True)
        self.top_token_model_value = QLabel("-")
        self.top_token_model_value.setProperty("valueLabel", True)
        self.top_transcript_model_value = QLabel("-")
        self.top_transcript_model_value.setProperty("valueLabel", True)
        self.last_used_value = QLabel("-")
        self.last_used_value.setProperty("valueLabel", True)
        self.last_refresh_value = QLabel("-")
        self.last_refresh_value.setProperty("valueLabel", True)

        for label, width in (
            (self.center_value, 260),
            (self.center_code_value, 180),
            (self.key_mask_value, 220),
            (self.total_tokens_value, 180),
            (self.total_transcript_value, 180),
            (self.usage_entries_value, 140),
            (self.token_models_value, 140),
            (self.transcript_models_value, 160),
            (self.last_refresh_value, 220),
        ):
            self._compact_value(label, width)

        grid.addWidget(QLabel("Provider / Center:"), 0, 0)
        grid.addWidget(self.center_value, 0, 1)
        grid.addWidget(QLabel("Backend Code:"), 1, 0)
        grid.addWidget(self.center_code_value, 1, 1)
        grid.addWidget(QLabel("API Key:"), 2, 0)
        grid.addWidget(self.key_mask_value, 2, 1)
        grid.addWidget(QLabel("Tokens Consumed:"), 3, 0)
        grid.addWidget(self.total_tokens_value, 3, 1)
        grid.addWidget(QLabel("Transcript Consumed:"), 4, 0)
        grid.addWidget(self.total_transcript_value, 4, 1)
        grid.addWidget(QLabel("Usage Entries:"), 5, 0)
        grid.addWidget(self.usage_entries_value, 5, 1)

        grid.addWidget(QLabel("Token Models:"), 0, 2)
        grid.addWidget(self.token_models_value, 0, 3)
        grid.addWidget(QLabel("Transcript Models:"), 1, 2)
        grid.addWidget(self.transcript_models_value, 1, 3)
        grid.addWidget(QLabel("Top Token Model:"), 2, 2)
        grid.addWidget(self.top_token_model_value, 2, 3)
        grid.addWidget(QLabel("Top Transcript Model:"), 3, 2)
        grid.addWidget(self.top_transcript_model_value, 3, 3)
        grid.addWidget(QLabel("Last Used:"), 4, 2)
        grid.addWidget(self.last_used_value, 4, 3)
        grid.addWidget(QLabel("Last Refresh:"), 5, 2)
        grid.addWidget(self.last_refresh_value, 5, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addLayout(grid)

        self.metadata_box = QTextEdit()
        self.metadata_box.setReadOnly(True)
        self.metadata_box.setMinimumHeight(130)
        layout.addWidget(self.metadata_box)
        self._root.addWidget(group)

    def _build_stt_group(self):
        self.stt_group = QGroupBox("Secretary Voice-to-Text")
        group = self.stt_group
        layout = QVBoxLayout(group)
        layout.setSpacing(12)
        layout.addWidget(
            self._note_label(
                "Shared Secretary speech-to-text settings. OpenAI transcription uses the OpenAI configuration from this page."
            )
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setContentsMargins(8, 8, 8, 8)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Server model (IranNevis)", userData="native")
        self.provider_combo.addItem("V2T model (Google Speech)", userData="v2t")
        self.provider_combo.addItem("OpenAI Transcription", userData="openai")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.setMaximumWidth(320)

        self.provider_help = self._note_label("")

        grid.addWidget(QLabel("Model:"), 0, 0)
        grid.addWidget(self.provider_combo, 0, 1)
        grid.addWidget(self.provider_help, 1, 0, 1, 2)
        grid.setColumnStretch(1, 1)

        layout.addLayout(grid)
        self._root.addWidget(group)

    def _update_backend_visibility(self):
        backend = str(self.backend_combo.currentData() or "company")
        is_openai = backend == "openai"

        self.company_auth_group.setVisible(not is_openai)
        self.openai_group.setVisible(is_openai)
        self.prompt_group.setVisible(is_openai)

    def _load_initial_state(self):
        saved_key = get_echomind_api_key()
        if saved_key:
            self.key_input.setText(saved_key)

        backend = get_llm_backend()
        idx = self.backend_combo.findData(backend)
        if idx >= 0:
            self.backend_combo.setCurrentIndex(idx)

        route = get_secretary_stt_route()
        idx = self.provider_combo.findData(route)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

        self._load_openai_state()
        self._load_prompt_state()
        self._load_proxy_state()
        self._update_provider_help()
        self._update_backend_help()
        self._update_backend_visibility()

        if saved_key:
            self._authenticate_and_refresh(saved_key, silent=True)
        else:
            self._set_not_authenticated_state("No credential saved. Enter your key and click Authenticate.")

        self._refresh_usage_for_active_backend()

    def _load_proxy_state(self):
        cfg = get_proxy_settings()
        idx = self.proxy_type_combo.findData(str(cfg.get("connection_type") or "direct"))
        if idx >= 0:
            self.proxy_type_combo.setCurrentIndex(idx)
        port = int(cfg.get("proxy_port") or 2080)
        idx = self.proxy_port_combo.findData(port)
        if idx >= 0:
            self.proxy_port_combo.setCurrentIndex(idx)
        self._on_proxy_type_changed(0)

    def _on_proxy_type_changed(self, _index: int):
        is_socks5 = str(self.proxy_type_combo.currentData() or "direct") == "socks5"
        self.proxy_port_label.setVisible(is_socks5)
        self.proxy_port_combo.setVisible(is_socks5)
        self.proxy_saved_label.setVisible(False)

    def _on_save_proxy_clicked(self):
        conn_type = str(self.proxy_type_combo.currentData() or "direct")
        port = int(self.proxy_port_combo.currentData() or 2080)
        save_proxy_settings({"connection_type": conn_type, "proxy_port": port})
        if conn_type == "socks5":
            label_text = f"SOCKS5 proxy saved: 127.0.0.1:{port}"
        else:
            label_text = "Direct connection saved (no proxy)."
        self.proxy_saved_label.setText(label_text)
        self.proxy_saved_label.setVisible(True)

    def _load_openai_state(self):
        cfg = get_openai_settings()
        self.openai_api_key_input.setText(str(cfg.get("api_key") or ""))
        self.openai_base_url_input.setText(str(cfg.get("base_url") or "https://api.openai.com/v1"))
        self.openai_org_input.setText(str(cfg.get("organization") or ""))
        self.openai_project_input.setText(str(cfg.get("project") or ""))
        self._set_combo_value(self.openai_text_model_input, str(cfg.get("text_model") or "gpt-5-mini"))
        self._set_combo_value(self.openai_report_model_input, str(cfg.get("report_model") or "gpt-5.4"))
        self._set_combo_value(self.openai_vision_model_input, str(cfg.get("vision_model") or "gpt-5.4"))
        self._set_combo_value(self.openai_secretary_model_input, str(cfg.get("secretary_model") or "gpt-5-mini"))
        self._set_combo_value(
            self.openai_transcription_model_input,
            str(cfg.get("transcription_model") or "gpt-4o-transcribe"),
        )
        self.openai_temperature_spin.setValue(float(cfg.get("temperature") or 0.2))
        self.openai_max_tokens_spin.setValue(int(cfg.get("max_output_tokens") or 4096))
        self.openai_timeout_spin.setValue(int(cfg.get("timeout_seconds") or 60))
        reasoning = str(cfg.get("reasoning_effort") or "")
        idx = self.openai_reasoning_combo.findData(reasoning)
        self.openai_reasoning_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._update_openai_status()

    def _load_prompt_state(self):
        prompts = get_prompt_settings()
        self.prompt_report_edit.setPlainText(str(prompts.get("report_generation") or ""))
        self.prompt_breast_edit.setPlainText(str(prompts.get("breast_assistant") or ""))
        self.prompt_secretary_routing_edit.setPlainText(str(prompts.get("secretary_routing") or ""))
        self.prompt_secretary_action_edit.setPlainText(str(prompts.get("secretary_action") or ""))
        self.prompt_transcript_cleanup_edit.setPlainText(str(prompts.get("transcript_cleanup") or ""))
        self.prompt_image_artifact_edit.setPlainText(str(prompts.get("image_artifact") or ""))

    def _openai_form_patch(self) -> dict[str, t.Any]:
        return {
            "api_key": (self.openai_api_key_input.text() or "").strip(),
            "base_url": (self.openai_base_url_input.text() or "").strip(),
            "organization": (self.openai_org_input.text() or "").strip(),
            "project": (self.openai_project_input.text() or "").strip(),
            "text_model": (self.openai_text_model_input.currentText() or "").strip(),
            "report_model": (self.openai_report_model_input.currentText() or "").strip(),
            "vision_model": (self.openai_vision_model_input.currentText() or "").strip(),
            "secretary_model": (self.openai_secretary_model_input.currentText() or "").strip(),
            "transcription_model": (self.openai_transcription_model_input.currentText() or "").strip(),
            "reasoning_effort": str(self.openai_reasoning_combo.currentData() or "").strip(),
            "temperature": float(self.openai_temperature_spin.value()),
            "max_output_tokens": int(self.openai_max_tokens_spin.value()),
            "timeout_seconds": int(self.openai_timeout_spin.value()),
        }

    def _prompt_patch(self) -> dict[str, str]:
        return {
            "report_generation": self.prompt_report_edit.toPlainText().strip(),
            "breast_assistant": self.prompt_breast_edit.toPlainText().strip(),
            "secretary_routing": self.prompt_secretary_routing_edit.toPlainText().strip(),
            "secretary_action": self.prompt_secretary_action_edit.toPlainText().strip(),
            "transcript_cleanup": self.prompt_transcript_cleanup_edit.toPlainText().strip(),
            "image_artifact": self.prompt_image_artifact_edit.toPlainText().strip(),
        }

    def _set_not_authenticated_state(self, reason: str):
        self.auth_status.setText(reason)
        self.auth_status.setProperty("state", "warning")
        self.style().unpolish(self.auth_status)
        self.style().polish(self.auth_status)

    def _update_backend_help(self):
        backend = str(self.backend_combo.currentData() or "company")
        if backend == "openai":
            self.backend_help.setText(
                "OpenAI direct mode uses your own API key, optional Organization/Project headers, and the "
                "GPT-5-era model settings and prompts from this page."
            )
        else:
            self.backend_help.setText(
                "AI PACS mode keeps the current EchoMind / GapGPT structure exactly as before."
            )
        self._update_backend_status()

    def _update_backend_status(self):
        backend = str(self.backend_combo.currentData() or "company")
        if backend == "openai":
            if (self.openai_api_key_input.text() or "").strip():
                self.backend_status.setText("OpenAI direct backend is selected and configured.")
            else:
                self.backend_status.setText("OpenAI direct backend is selected but no API key is saved.")
            return

        manager = APIKeyManager.instance()
        if manager.is_validated():
            self.backend_status.setText(f"AI PACS backend active: {manager.get_current_center() or 'EchoMind'}")
        elif (self.key_input.text() or "").strip():
            self.backend_status.setText("AI PACS backend selected. Authenticate to enable it.")
        else:
            self.backend_status.setText("AI PACS backend selected but no EchoMind credential is saved.")

    def _update_openai_status(self, message: str | None = None, *, ok: bool | None = None):
        if ok is True:
            self.openai_status.setProperty("state", "success")
            self.openai_status.setText(message or "OpenAI settings saved and ready.")
            self.style().unpolish(self.openai_status)
            self.style().polish(self.openai_status)
            return
        if ok is False:
            self.openai_status.setProperty("state", "error")
            self.openai_status.setText(message or "OpenAI configuration failed.")
            self.style().unpolish(self.openai_status)
            self.style().polish(self.openai_status)
            return
        if (self.openai_api_key_input.text() or "").strip():
            self.openai_status.setProperty("state", "warning")
            self.openai_status.setText("OpenAI settings are present. Test connection after saving.")
        else:
            self.openai_status.setProperty("state", "warning")
            self.openai_status.setText("OpenAI backend not configured yet.")
        self.style().unpolish(self.openai_status)
        self.style().polish(self.openai_status)

    def _on_backend_changed(self, _index: int):
        self._update_backend_help()
        self._update_backend_visibility()
        self.backend_saved_label.setVisible(False)

    def _on_save_backend_clicked(self):
        backend = str(self.backend_combo.currentData() or "company")
        set_llm_backend(backend)
        self._update_backend_status()
        self._refresh_usage_for_active_backend()
        name = "AI PACS EchoMind" if backend == "company" else "OpenAI Direct"
        self.backend_saved_label.setText(f"{name} backend saved and active.")
        self.backend_saved_label.setVisible(True)

    def _on_provider_changed(self, _index: int):
        set_secretary_stt_route(str(self.provider_combo.currentData() or "native"))
        self._update_provider_help()

    def _update_provider_help(self):
        route = str(self.provider_combo.currentData() or "native").lower()
        if route == "v2t":
            text = "V2T runs locally with Google Speech (requires speech_recognition and internet)."
        elif route == "openai":
            text = "OpenAI Transcription uses the saved OpenAI API key and transcription model from this page."
        else:
            text = "Server model uses the EchoMind IranNevis transcription service."
        self.provider_help.setText(text)

    def _on_authenticate_clicked(self):
        key = (self.key_input.text() or "").strip()
        if not key:
            QMessageBox.warning(self, "EchoMind", "Please enter a credential/access key.")
            return
        self._authenticate_and_refresh(key, silent=False)

    def _on_save_openai_clicked(self):
        save_openai_settings(self._openai_form_patch())
        self._update_openai_status("OpenAI settings saved.", ok=True)
        self._update_backend_help()
        self._refresh_usage_for_active_backend()

    def _on_save_prompts_clicked(self):
        save_prompt_settings(self._prompt_patch())
        QMessageBox.information(self, "EchoMind Prompt Settings", "Prompt settings saved successfully.")

    def _on_test_openai_clicked(self):
        patch = self._openai_form_patch()
        api_key = str(patch.get("api_key") or "").strip()
        base_url = str(patch.get("base_url") or "").strip().rstrip("/") or "https://api.openai.com/v1"
        if not api_key:
            QMessageBox.warning(self, "OpenAI", "Please enter an OpenAI API key first.")
            return

        headers = {"Authorization": f"Bearer {api_key}"}
        org_id = str(patch.get("organization") or "").strip()
        project_id = str(patch.get("project") or "").strip()
        if org_id:
            headers["OpenAI-Organization"] = org_id
        if project_id:
            headers["OpenAI-Project"] = project_id

        try:
            resp = requests.get(f"{base_url}/models", headers=headers, timeout=int(patch.get("timeout_seconds") or 60))
            if resp.status_code in (401, 403):
                raise RuntimeError("Authentication failed. Check the API key, organization, and project fields.")
            resp.raise_for_status()
        except Exception as exc:
            self._update_openai_status(str(exc), ok=False)
            QMessageBox.critical(self, "OpenAI Connection Test", f"OpenAI connection failed:\n\n{exc}")
            return

        save_openai_settings(patch)
        self._update_openai_status("OpenAI connection succeeded.", ok=True)
        self._refresh_usage_for_active_backend()
        QMessageBox.information(self, "OpenAI Connection Test", "OpenAI connection succeeded.")

    def _on_refresh_clicked(self):
        backend = str(self.backend_combo.currentData() or "company")
        if backend == "company":
            key = (self.key_input.text() or "").strip() or (get_echomind_api_key() or "").strip()
            if key:
                self._authenticate_and_refresh(key, silent=True)
                return
        self._refresh_usage_for_active_backend()

    def _authenticate_and_refresh(self, key: str, silent: bool):
        mgr = APIKeyManager.instance()
        ok, center_code, error = mgr.validate_key(key)
        if not ok:
            self._set_not_authenticated_state(error or "Authentication failed.")
            self._update_backend_status()
            if not silent:
                QMessageBox.critical(self, "EchoMind Authentication", error or "Invalid key.")
            return

        set_echomind_api_key(key)

        center_display = center_code or "-"
        try:
            info = Manage.instance().detect_center(key)
            center_display = info.center_display
            center_code = info.center_code
        except Exception:
            pass

        self.auth_status.setText("Authenticated successfully")
        self.auth_status.setProperty("state", "success")
        self.style().unpolish(self.auth_status)
        self.style().polish(self.auth_status)
        self._update_backend_status()
        self._refresh_usage(api_key=key, display_name=center_display or "EchoMind", backend_code=(center_code or "company").upper())

        if not silent:
            QMessageBox.information(self, "EchoMind Authentication", "Authentication successful.")

    def _refresh_usage_for_active_backend(self):
        backend = str(self.backend_combo.currentData() or "company")
        if backend == "openai":
            api_key = (self.openai_api_key_input.text() or "").strip()
            self._refresh_usage(api_key=api_key, display_name="OpenAI", backend_code="OPENAI")
            return

        api_key = (self.key_input.text() or "").strip() or (get_echomind_api_key() or "").strip()
        display_name = get_active_backend_display_name() if is_active_backend_configured() else "EchoMind"
        self._refresh_usage(api_key=api_key, display_name=display_name, backend_code="COMPANY")

    def _refresh_usage(self, api_key: str, display_name: str, backend_code: str):
        api_key = (api_key or "").strip()
        if not api_key:
            self.center_value.setText(display_name or "-")
            self.center_code_value.setText(backend_code or "-")
            self.key_mask_value.setText("-")
            self.total_tokens_value.setText("0")
            self.total_transcript_value.setText("0 min")
            self.usage_entries_value.setText("0")
            self.token_models_value.setText("0")
            self.transcript_models_value.setText("0")
            self.top_token_model_value.setText("-")
            self.top_transcript_model_value.setText("-")
            self.last_used_value.setText("-")
            self.last_refresh_value.setText("-")
            self.metadata_box.setPlainText("")
            return

        rows = get_api_usage_rows_for_key(api_key, limit=200) or []
        tr_models = load_api_transcript_usage_for_key(api_key) or {}

        total_tokens = sum(int(row.get("tokens") or 0) for row in rows)
        total_transcript_min = 0.0
        for _model, val in tr_models.items():
            try:
                total_transcript_min += float(val or 0.0)
            except Exception:
                pass

        last_used = "-"
        for row in rows:
            if row.get("last_used_at"):
                last_used = str(row.get("last_used_at"))
                break

        token_by_model: dict[str, int] = {}
        for row in rows:
            model_name = str(row.get("model") or "Unknown")
            token_by_model[model_name] = token_by_model.get(model_name, 0) + int(row.get("tokens") or 0)

        def _safe_float(val: t.Any) -> float:
            try:
                return float(val or 0.0)
            except Exception:
                return 0.0

        top_token_model = max(token_by_model.items(), key=lambda kv: kv[1])[0] if token_by_model else "-"
        top_transcript_model = max(tr_models.items(), key=lambda kv: _safe_float(kv[1]))[0] if tr_models else "-"

        self.center_value.setText(display_name or "-")
        self.center_code_value.setText((backend_code or "-").upper())
        self.key_mask_value.setText(_mask_key(api_key))
        self.total_tokens_value.setText(f"{total_tokens:,}")
        if 0 < total_transcript_min < 0.1:
            self.total_transcript_value.setText(f"{max(1, int(round(total_transcript_min * 60.0)))} sec")
        else:
            self.total_transcript_value.setText(f"{total_transcript_min:.1f} min")
        self.usage_entries_value.setText(str(len(rows)))
        self.token_models_value.setText(str(len(token_by_model)))
        self.transcript_models_value.setText(str(len(tr_models)))
        self.top_token_model_value.setText(top_token_model)
        self.top_transcript_model_value.setText(top_transcript_model)
        self.last_used_value.setText(last_used)
        self.last_refresh_value.setText(datetime.now().strftime("%Y-%m-%d %H:%M"))

        token_lines = [f"- {name}: {count:,} tokens" for name, count in sorted(token_by_model.items(), key=lambda kv: kv[0].lower())]
        transcript_lines = []
        for name, minutes in sorted(tr_models.items(), key=lambda kv: str(kv[0]).lower()):
            value = _safe_float(minutes)
            if 0 < value < 0.1:
                amount = f"{max(1, int(round(value * 60.0)))} sec"
            else:
                amount = f"{value:.1f} min"
            transcript_lines.append(f"- {name}: {amount}")

        summary = [
            f"Provider: {display_name}",
            f"Backend: {backend_code}",
            f"Usage entries: {len(rows)}",
            f"Token models: {len(token_by_model)}",
            f"Transcript models: {len(tr_models)}",
            f"Top token model: {top_token_model}",
            f"Top transcript model: {top_transcript_model}",
            "",
            "Token usage by model:",
            *(token_lines or ["- No token usage yet."]),
            "",
            "Transcript usage by model:",
            *(transcript_lines or ["- No transcript usage yet."]),
        ]
        self.metadata_box.setPlainText("\n".join(summary))
