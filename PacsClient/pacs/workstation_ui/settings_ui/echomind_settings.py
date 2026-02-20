from __future__ import annotations

from datetime import datetime
import typing as t
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QFormLayout,
    QComboBox,
    QTextEdit,
)

from EchoMind.api_manager import APIKeyManager, Manage
from EchoMind.settings_store import (
    get_echomind_api_key,
    set_echomind_api_key,
    get_secretary_stt_route,
    set_secretary_stt_route,
)
from PacsClient.utils.database import (
    get_api_usage_rows_for_key,
    load_api_transcript_usage_for_key,
)


def _mask_key(api_key: str) -> str:
    k = (api_key or "").strip()
    if not k:
        return "-"
    if len(k) <= 10:
        return k[:2] + "…" + k[-2:]
    return k[:4] + "…" + k[-4:]


class EchoMindSettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_initial_state()

    def _build_ui(self):
        self.setObjectName("EchoMindSettingsWidget")
        self.setStyleSheet(
            """
            QWidget#EchoMindSettingsWidget {
                background-color: #1a202c;
                color: #e2e8f0;
            }
            QWidget#EchoMindSettingsWidget QGroupBox {
                background-color: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 8px;
                margin-top: 12px;
                padding: 12px;
                font-weight: 700;
            }
            QWidget#EchoMindSettingsWidget QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QWidget#EchoMindSettingsWidget QLineEdit,
            QWidget#EchoMindSettingsWidget QComboBox,
            QWidget#EchoMindSettingsWidget QTextEdit {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QWidget#EchoMindSettingsWidget QPushButton {
                background-color: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-weight: 600;
            }
            QWidget#EchoMindSettingsWidget QPushButton:hover {
                background-color: #2c5aa0;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        title = QLabel("EchoMind Settings")
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        root.addWidget(title)

        subtitle = QLabel(
            "Configure EchoMind account authentication and Secretary voice-to-text provider."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #a0aec0;")
        root.addWidget(subtitle)

        auth_group = QGroupBox("Authentication")
        auth_layout = QVBoxLayout(auth_group)

        row = QHBoxLayout()
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("Enter EchoMind credential / access key")
        row.addWidget(self.key_input, 1)

        self.auth_btn = QPushButton("Authenticate")
        self.auth_btn.clicked.connect(self._on_authenticate_clicked)
        row.addWidget(self.auth_btn)

        auth_layout.addLayout(row)

        self.auth_status = QLabel("Not authenticated")
        self.auth_status.setStyleSheet("color: #fbbf24; font-weight: 600;")
        auth_layout.addWidget(self.auth_status)

        root.addWidget(auth_group)

        usage_group = QGroupBox("Account / Usage (Read-only)")
        usage_layout = QVBoxLayout(usage_group)

        usage_header = QHBoxLayout()
        usage_header.addStretch(1)
        self.refresh_usage_btn = QPushButton("Refresh Usage")
        self.refresh_usage_btn.clicked.connect(self._on_refresh_clicked)
        usage_header.addWidget(self.refresh_usage_btn)
        usage_layout.addLayout(usage_header)

        form = QFormLayout()

        self.center_value = QLabel("-")
        self.center_code_value = QLabel("-")
        self.key_mask_value = QLabel("-")
        self.total_tokens_value = QLabel("0")
        self.total_transcript_value = QLabel("0 min")
        self.usage_entries_value = QLabel("0")
        self.token_models_value = QLabel("0")
        self.transcript_models_value = QLabel("0")
        self.top_token_model_value = QLabel("-")
        self.top_transcript_model_value = QLabel("-")
        self.last_used_value = QLabel("-")
        self.last_refresh_value = QLabel("-")

        form.addRow("Organization / Center:", self.center_value)
        form.addRow("Center Code:", self.center_code_value)
        form.addRow("API Key:", self.key_mask_value)
        form.addRow("Tokens Consumed:", self.total_tokens_value)
        form.addRow("Transcript Consumed:", self.total_transcript_value)
        form.addRow("Usage Entries:", self.usage_entries_value)
        form.addRow("Token Models:", self.token_models_value)
        form.addRow("Transcript Models:", self.transcript_models_value)
        form.addRow("Top Token Model:", self.top_token_model_value)
        form.addRow("Top Transcript Model:", self.top_transcript_model_value)
        form.addRow("Last Used:", self.last_used_value)
        form.addRow("Last Refresh:", self.last_refresh_value)
        usage_layout.addLayout(form)

        self.metadata_box = QTextEdit()
        self.metadata_box.setReadOnly(True)
        self.metadata_box.setPlaceholderText("Additional usage metadata will appear here.")
        self.metadata_box.setMinimumHeight(130)
        usage_layout.addWidget(self.metadata_box)

        root.addWidget(usage_group)

        stt_group = QGroupBox("EchoMind Secretary Voice-to-Text Model")
        stt_layout = QFormLayout(stt_group)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Server model (IranNevis)", userData="native")
        self.provider_combo.addItem("V2T model (Google Speech)", userData="v2t")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        stt_layout.addRow("Model:", self.provider_combo)

        self.provider_help = QLabel("")
        self.provider_help.setWordWrap(True)
        self.provider_help.setStyleSheet("color: #94a3b8; font-size: 12px;")
        stt_layout.addRow("", self.provider_help)

        root.addWidget(stt_group)
        root.addStretch(1)

    def _load_initial_state(self):
        saved_key = get_echomind_api_key()
        if saved_key:
            self.key_input.setText(saved_key)

        route = get_secretary_stt_route()
        idx = self.provider_combo.findData(route)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        self._update_provider_help()

        if saved_key:
            self._authenticate_and_refresh(saved_key, silent=True)
        else:
            self._set_not_authenticated_state("No credential saved. Enter your key and click Authenticate.")

    def _set_not_authenticated_state(self, reason: str):
        self.auth_status.setText(reason)
        self.auth_status.setStyleSheet("color: #fbbf24; font-weight: 600;")
        self.center_value.setText("-")
        self.center_code_value.setText("-")
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

    def _on_provider_changed(self, _index: int):
        route = self.provider_combo.currentData()
        set_secretary_stt_route(str(route or "native"))
        self._update_provider_help()

    def _update_provider_help(self):
        route = str(self.provider_combo.currentData() or "native").lower()
        if route == "v2t":
            self.provider_help.setText(
                "V2T runs locally with Google Speech (requires speech_recognition and internet)."
            )
        else:
            self.provider_help.setText(
                "Server model uses the EchoMind IranNevis transcription service."
            )

    def _on_authenticate_clicked(self):
        key = (self.key_input.text() or "").strip()
        if not key:
            QMessageBox.warning(self, "EchoMind", "Please enter a credential/access key.")
            return
        self._authenticate_and_refresh(key, silent=False)

    def _on_refresh_clicked(self):
        key = (self.key_input.text() or "").strip() or (get_echomind_api_key() or "").strip()
        if not key:
            QMessageBox.warning(self, "EchoMind", "No saved key found. Please authenticate first.")
            return
        self._authenticate_and_refresh(key, silent=True)

    def _authenticate_and_refresh(self, key: str, silent: bool):
        mgr = APIKeyManager.instance()
        ok, center_code, error = mgr.validate_key(key)
        if not ok:
            self._set_not_authenticated_state(error or "Authentication failed.")
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

        rows = get_api_usage_rows_for_key(key, limit=200) or []
        tr_models = load_api_transcript_usage_for_key(key) or {}

        total_tokens = sum(int(r.get("tokens") or 0) for r in rows)
        total_transcript_min = 0.0
        for _model, val in tr_models.items():
            try:
                total_transcript_min += float(val or 0.0)
            except Exception:
                pass

        last_used = "-"
        for r in rows:
            lu = r.get("last_used_at")
            if lu:
                last_used = str(lu)
                break

        token_by_model = {}
        for r in rows:
            m = str(r.get("model") or "Unknown")
            token_by_model[m] = token_by_model.get(m, 0) + int(r.get("tokens") or 0)

        top_token_model = "-"
        if token_by_model:
            top_token_model = max(token_by_model.items(), key=lambda kv: kv[1])[0]

        def _safe_float(val: t.Any) -> float:
            try:
                return float(val or 0.0)
            except Exception:
                return 0.0

        top_transcript_model = "-"
        if tr_models:
            top_transcript_model = max(tr_models.items(), key=lambda kv: _safe_float(kv[1]))[0]

        now_label = datetime.now().strftime("%Y-%m-%d %H:%M")

        self.auth_status.setText("Authenticated successfully")
        self.auth_status.setStyleSheet("color: #48bb78; font-weight: 700;")
        self.center_value.setText(center_display or "-")
        self.center_code_value.setText((center_code or "-").upper())
        self.key_mask_value.setText(_mask_key(key))
        self.total_tokens_value.setText(f"{total_tokens:,}")
        if total_transcript_min < 0.1 and total_transcript_min > 0:
            total_transcript_text = f"{max(1, int(round(total_transcript_min * 60.0)))} sec"
        else:
            total_transcript_text = f"{total_transcript_min:.1f} min"
        self.total_transcript_value.setText(total_transcript_text)
        self.usage_entries_value.setText(str(len(rows)))
        self.token_models_value.setText(str(len(token_by_model)))
        self.transcript_models_value.setText(str(len(tr_models)))
        self.top_token_model_value.setText(top_token_model)
        self.top_transcript_model_value.setText(top_transcript_model)
        self.last_used_value.setText(last_used)
        self.last_refresh_value.setText(now_label)

        model_lines = []
        for model, tokens in sorted(token_by_model.items(), key=lambda kv: kv[0].lower()):
            model_lines.append(f"• {model}: {tokens:,} tokens")

        tr_lines = []
        for model, mins in sorted(tr_models.items(), key=lambda kv: str(kv[0]).lower()):
            try:
                m = float(mins or 0.0)
            except Exception:
                m = 0.0
            if m < 0.1 and m > 0:
                m_txt = f"{max(1, int(round(m * 60.0)))} sec"
            else:
                m_txt = f"{m:.1f} min"
            tr_lines.append(f"• {model}: {m_txt}")

        text = []
        text.append("Usage summary:")
        text.append(f"• Usage entries: {len(rows)}")
        text.append(f"• Token models: {len(token_by_model)}")
        text.append(f"• Transcript models: {len(tr_models)}")
        text.append(f"• Top token model: {top_token_model}")
        text.append(f"• Top transcript model: {top_transcript_model}")
        text.append("")
        text.append("Token usage by model:")
        text.extend(model_lines or ["• No token usage yet."])
        text.append("")
        text.append("Transcript usage by model:")
        text.extend(tr_lines or ["• No transcript usage yet."])
        self.metadata_box.setPlainText("\n".join(text))

        if not silent:
            QMessageBox.information(self, "EchoMind Authentication", "Authentication successful.")
