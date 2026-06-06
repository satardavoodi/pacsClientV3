"""
Light Viewer Settings UI Panel
User interface for configuring Light Viewer executable path for CD burning
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QGroupBox, QLineEdit, QFileDialog, QFormLayout,
                               QMessageBox, QFrame, QRadioButton, QButtonGroup,
                               QScrollArea)
from PySide6.QtCore import Qt, Signal
import os
import json
from pathlib import Path

from aipacs_runtime import roaming_config_root
from modules.cd_burner.cd_burn_manager import inspect_viewer_portability
from modules.cd_burner.viewer_locator import default_viewer_hint, resolve_default_viewer

# Viewer-mode values persisted in lightviewer_settings.json
VIEWER_MODE_DEFAULT = "default"   # bundled AI-PACS portable viewer
VIEWER_MODE_CUSTOM = "custom"     # user-selected portable viewer .exe

class LightViewerSettingsWidget(QWidget):
    """Settings widget for Light Viewer configuration"""
    
    # Signal emitted when settings are saved
    settingsSaved = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_file = self._get_config_path()
        self.setup_ui()
        self.load_settings()
    
    def _get_config_path(self) -> Path:
        """Get path to the config file"""
        config_dir = roaming_config_root()
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / 'lightviewer_settings.json'
    
    def setup_ui(self):
        """Setup the main UI"""
        # Apply dark theme
        self.setStyleSheet("""
            QWidget {
                background-color: #0b0d10;
                color: #e5e7eb;
            }
            QGroupBox {
                background-color: #10141a;
                border: 1px solid #232a33;
                border-radius: 10px;
                /* Reserve room for the title so the first child widget
                   never overlaps it. margin-top is the gap between the
                   parent and the box outline; padding-top is the gap
                   between the outline and the first child widget. */
                margin-top: 14px;
                padding: 22px 16px 14px 16px;
                font-weight: 700;
                color: #e5e7eb;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                top: 0px;
                padding: 2px 10px;
                /* Match the body font-size so the title sits flush above the
                   content. The previous 28px font + thick padding overlapped
                   the path-input row below. */
                font-size: 14px;
                font-weight: 700;
                color: #f3f4f6;
                background-color: #10141a;
            }
            QLabel {
                color: #e5e7eb;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 7px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #0f1319;
            }
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #1d4ed8;
                border-radius: 8px;
                padding: 8px 14px;
                min-height: 36px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
            /* Radio indicators need explicit colors — the default Qt
               indicator renders dark-on-dark and the checked dot is
               invisible (same family as the MPR dropdown fix). */
            QRadioButton {
                color: #e5e7eb;
                font-size: 14px;
                spacing: 8px;
                padding: 2px 0;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
                border-radius: 9px;
                border: 2px solid #64748b;
                background-color: #1b2230;
            }
            QRadioButton::indicator:hover {
                border-color: #93c5fd;
            }
            QRadioButton::indicator:checked {
                border: 2px solid #3b82f6;
                background-color: qradialgradient(
                    cx: 0.5, cy: 0.5, radius: 0.55, fx: 0.5, fy: 0.5,
                    stop: 0 #60a5fa, stop: 0.55 #3b82f6, stop: 0.62 #1b2230, stop: 1 #1b2230
                );
            }
        """)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title_label = QLabel("Light Viewer Settings")
        title_label.setStyleSheet(
            "font-size: 20px; font-weight: 800; padding: 10px; color: #f3f4f6;"
        )
        main_layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel(
            "Configure the DICOM viewer that will be included when burning CDs.\n"
            "AI-PACS ships its own portable Lite Viewer (recommended); alternatively\n"
            "select your own portable viewer executable. The viewer lets patients\n"
            "view their images on any Windows computer without installing software."
        )
        desc_label.setStyleSheet("color: #94a3b8; padding: 5px 10px; font-size: 14px;")
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #232a33;")
        main_layout.addWidget(separator)
        
        # Viewer selection group (default AI-PACS viewer vs custom executable)
        viewer_group = QGroupBox("CD Viewer Selection")
        viewer_layout = QVBoxLayout()
        viewer_layout.setSpacing(12)

        self.mode_group = QButtonGroup(self)
        self.default_viewer_rb = QRadioButton("Use the default AI-PACS portable viewer (recommended)")
        self.custom_viewer_rb = QRadioButton("Use a custom portable viewer executable")
        self.mode_group.addButton(self.default_viewer_rb)
        self.mode_group.addButton(self.custom_viewer_rb)
        self.default_viewer_rb.toggled.connect(self._on_mode_changed)
        viewer_layout.addWidget(self.default_viewer_rb)

        # Default-viewer availability status (resolved via viewer_locator)
        self.default_status_label = QLabel("")
        self.default_status_label.setWordWrap(True)
        self.default_status_label.setStyleSheet(
            "color: #94a3b8; font-size: 12px; padding: 0 2px 6px 22px;"
            "background: transparent; border: none;"
        )
        viewer_layout.addWidget(self.default_status_label)

        viewer_layout.addWidget(self.custom_viewer_rb)

        # Path input with browse button
        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select the Light Viewer executable (.exe)")
        self.path_edit.setReadOnly(True)
        # Explicit read-only styling so the field reads as a value-display
        # rather than an editable input — and so the inner padding matches
        # the surrounding Browse... button height (Archetype 5).
        try:
            from PacsClient.utils.responsive_layout import set_form_field_size
            set_form_field_size(self.path_edit, min_height=30, expanding=True)
        except Exception:  # pragma: no cover — defensive
            self.path_edit.setMinimumHeight(30)
        self.path_edit.setStyleSheet(
            "QLineEdit {"
            "  background-color: #1b2230;"
            "  color: #e5e7eb;"
            "  border: 1px solid #2b313b;"
            "  border-radius: 6px;"
            "  padding: 4px 10px;"
            "  selection-background-color: #2563eb;"
            "}"
            "QLineEdit:read-only {"
            # Match the editable look so the read-only state doesn't render
            # as a flat black strip next to the Browse... button.
            "  background-color: #1b2230;"
            "  color: #e5e7eb;"
            "}"
            "QLineEdit:focus {"
            "  border-color: #3b82f6;"
            "}"
        )
        path_layout.addWidget(self.path_edit, 1)
        
        self.browse_btn = QPushButton("Browse...")
        # Archetype 5: keep the 100 px floor but let the button grow with font /
        # DPI so the label can never be hard-clipped. See
        # docs/conventions/RESPONSIVE_UI_CONVENTION.md.
        try:
            from PacsClient.utils.responsive_layout import set_form_field_size
            set_form_field_size(self.browse_btn, min_height=30, min_width=100)
        except Exception:  # pragma: no cover — defensive
            self.browse_btn.setMinimumWidth(100)
        self.browse_btn.clicked.connect(self.browse_for_viewer)
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        path_layout.addWidget(self.browse_btn)
        
        viewer_layout.addLayout(path_layout)

        # Status label (single-line summary like "⚠ File does not exist").
        # Lives BELOW the path field on its own row — never overlaps the field.
        # Transparent background prevents the "black artifact" appearance
        # the user observed when the field and the label sat against each
        # other with different default backgrounds.
        self.viewer_status_label = QLabel("")
        self.viewer_status_label.setStyleSheet(
            "color: #94a3b8; font-size: 13px; padding: 4px 2px;"
            "background: transparent; border: none;"
        )
        viewer_layout.addWidget(self.viewer_status_label)

        # Details label (multi-line warnings, sizing info, etc.).
        self.viewer_details_label = QLabel("")
        self.viewer_details_label.setWordWrap(True)
        self.viewer_details_label.setStyleSheet(
            "color: #94a3b8; font-size: 12px; padding: 0 2px 4px 2px;"
            "background: transparent; border: none;"
        )
        # Archetype 2: explicit MinimumExpanding vertical policy so the
        # wrapped detail block can grow when the column narrows.
        try:
            from PySide6.QtWidgets import QSizePolicy as _QSP
            self.viewer_details_label.setSizePolicy(_QSP.Preferred, _QSP.MinimumExpanding)
        except Exception:  # pragma: no cover — defensive
            pass
        viewer_layout.addWidget(self.viewer_details_label)
        
        # Clear button
        clear_layout = QHBoxLayout()
        clear_layout.addStretch()
        self.clear_btn = QPushButton("Clear Path")
        # Archetype 5 — same rationale as browse_btn above.
        try:
            from PacsClient.utils.responsive_layout import set_form_field_size
            set_form_field_size(self.clear_btn, min_height=30, min_width=100)
        except Exception:  # pragma: no cover — defensive
            self.clear_btn.setMinimumWidth(100)
        self.clear_btn.clicked.connect(self.clear_viewer_path)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
            }
            QPushButton:hover {
                background-color: #252d3d;
                border-color: #3b82f6;
            }
        """)
        clear_layout.addWidget(self.clear_btn)
        viewer_layout.addLayout(clear_layout)
        
        viewer_group.setLayout(viewer_layout)
        main_layout.addWidget(viewer_group)
        
        # CD Burn Settings Group
        cd_group = QGroupBox("CD/DVD Burn Settings")
        cd_layout = QFormLayout()
        cd_layout.setSpacing(12)
        
        # Disc label
        self.disc_label_edit = QLineEdit()
        self.disc_label_edit.setPlaceholderText("DICOM_IMAGES")
        self.disc_label_edit.setText("DICOM_IMAGES")
        self.disc_label_edit.setMaxLength(32)  # ISO9660 limit
        cd_layout.addRow("Default Disc Label:", self.disc_label_edit)
        
        # Auto-eject checkbox would go here if needed
        
        cd_group.setLayout(cd_layout)
        main_layout.addWidget(cd_group)

        # Recommended Viewers Group
        info_group = QGroupBox("Recommended DICOM Viewers")
        info_layout = QVBoxLayout()
        
        info_text = QLabel(
            "Popular free DICOM viewers that work well for CD distribution:\n\n"
            "• RadiAnt DICOM Viewer - Lightweight, fast, no installation required\n"
            "• MicroDicom - Small footprint, portable version available\n"
            "• Horos - Full-featured viewer (macOS only)\n\n"
            "Make sure to use the portable/standalone version of the viewer."
        )
        info_text.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 10px;")
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        
        info_group.setLayout(info_layout)
        main_layout.addWidget(info_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setMinimumWidth(150)  # Archetype 5: floor, can grow with font
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #16a34a;
                color: #ffffff;
                font-weight: 800;
                padding: 10px;
                border: 1px solid #15803d;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #15803d;
                border-color: #10b981;
            }
        """)
        save_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(save_btn)
        
        main_layout.addLayout(button_layout)
        
        # Status label for save operations
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #10b981; padding: 5px 10px; font-weight: 700;")
        main_layout.addWidget(self.status_label)

        main_layout.addStretch()

        # Wrap the page in a QScrollArea (same pattern as the other settings
        # tabs — see installation_module_settings / echomind_settings) so the
        # full content stays reachable on short displays. Without this the
        # page clipped its lower groups on 1280x1024 monitors.
        content = QWidget()
        content.setLayout(main_layout)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setWidget(content)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(scroll)
    
    def browse_for_viewer(self):
        """Open file dialog to select viewer executable"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DICOM Light Viewer Executable",
            "",
            "Executable Files (*.exe);;All Files (*.*)"
        )
        
        if file_path:
            self.path_edit.setText(file_path)
            self._validate_viewer_path(file_path)
    
    def _validate_viewer_path(self, path: str):
        """Validate the selected viewer path"""
        if not path:
            self.viewer_status_label.setText("")
            self.viewer_details_label.setText("")
            return False
        
        if not os.path.exists(path):
            self.viewer_status_label.setText("⚠ File does not exist")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px; font-weight: 700;")
            self.viewer_details_label.setText("")
            return False
        
        if not path.lower().endswith('.exe'):
            self.viewer_status_label.setText("⚠ File is not an executable (.exe)")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px; font-weight: 700;")
            self.viewer_details_label.setText("")
            return False
        
        # Get file size
        file_size = os.path.getsize(path)
        size_mb = file_size / (1024 * 1024)
        
        analysis = inspect_viewer_portability(path)
        if not analysis["ok"]:
            self.viewer_status_label.setText("✗ Viewer is not portable-ready")
            self.viewer_status_label.setStyleSheet("color: #ef4444; font-size: 12px; padding: 5px; font-weight: 700;")
        elif analysis["warnings"]:
            self.viewer_status_label.setText(f"⚠ Viewer selected ({size_mb:.1f} MB) — portability warnings")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px; font-weight: 700;")
        else:
            self.viewer_status_label.setText(f"✓ Portable viewer looks usable ({size_mb:.1f} MB)")
            self.viewer_status_label.setStyleSheet("color: #10b981; font-size: 12px; padding: 5px; font-weight: 700;")

        detail_lines = list(analysis.get("details", []))
        if analysis["warnings"]:
            detail_lines.extend([f"Warning: {warning}" for warning in analysis["warnings"]])
        self.viewer_details_label.setText("\n".join(detail_lines))
        return analysis["ok"]
    
    def clear_viewer_path(self):
        """Clear the viewer path"""
        self.path_edit.clear()
        self.viewer_status_label.setText("")
        self.viewer_details_label.setText("")

    def _on_mode_changed(self, _checked: bool = False):
        """Enable/disable the custom-path row to match the selected mode."""
        use_custom = self.custom_viewer_rb.isChecked()
        self.path_edit.setEnabled(use_custom)
        self.browse_btn.setEnabled(use_custom)
        self.clear_btn.setEnabled(use_custom)
        self._refresh_default_status()

    def _refresh_default_status(self):
        """Show whether the bundled default viewer is available."""
        try:
            info = resolve_default_viewer()
            hint = default_viewer_hint()
        except Exception as e:  # defensive — settings page must never crash
            info, hint = None, f"Could not check default viewer: {e}"

        if info is not None:
            color = "#10b981" if info.get("kind") in ("lite", "override") else "#f59e0b"
            self.default_status_label.setText(f"✓ {hint}")
        else:
            color = "#f59e0b"
            self.default_status_label.setText(f"⚠ {hint}")
        self.default_status_label.setStyleSheet(
            f"color: {color}; font-size: 12px; padding: 0 2px 6px 22px;"
            "background: transparent; border: none;"
        )

    def save_settings(self):
        """Save settings to config file"""
        try:
            settings = {
                'viewer_mode': (
                    VIEWER_MODE_CUSTOM if self.custom_viewer_rb.isChecked()
                    else VIEWER_MODE_DEFAULT
                ),
                'light_viewer_path': self.path_edit.text(),
                'disc_label': self.disc_label_edit.text() or 'DICOM_IMAGES'
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            
            self.status_label.setText("✓ Settings saved successfully!")
            self.status_label.setStyleSheet("color: #10b981; padding: 5px 10px; font-weight: 800;")
            
            self.settingsSaved.emit()
            
            print(f"💾 Light Viewer settings saved to: {self.config_file}")
            
        except Exception as e:
            self.status_label.setText(f"✗ Error saving settings: {str(e)}")
            self.status_label.setStyleSheet("color: #f59e0b; padding: 5px 10px; font-weight: 800;")
            
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save settings:\n{str(e)}"
            )
    
    def load_settings(self):
        """Load settings from config file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)

                viewer_path = settings.get('light_viewer_path', '')
                disc_label = settings.get('disc_label', 'DICOM_IMAGES')
                mode = self._normalize_mode(settings.get('viewer_mode'), viewer_path)

                self.path_edit.setText(viewer_path)
                self.disc_label_edit.setText(disc_label)

                if mode == VIEWER_MODE_CUSTOM:
                    self.custom_viewer_rb.setChecked(True)
                else:
                    self.default_viewer_rb.setChecked(True)

                if viewer_path:
                    self._validate_viewer_path(viewer_path)

                print(f"📂 Light Viewer settings loaded from: {self.config_file}")
            else:
                self.default_viewer_rb.setChecked(True)

        except Exception as e:
            print(f"⚠ Error loading Light Viewer settings: {e}")

        self._on_mode_changed()

    @staticmethod
    def _normalize_mode(raw_mode, viewer_path: str) -> str:
        """Back-compat: configs predating viewer_mode keep their old meaning —
        a configured custom path meant 'use the custom viewer'."""
        if raw_mode in (VIEWER_MODE_DEFAULT, VIEWER_MODE_CUSTOM):
            return raw_mode
        return VIEWER_MODE_CUSTOM if viewer_path else VIEWER_MODE_DEFAULT
    
    @staticmethod
    def get_light_viewer_path() -> str:
        """Static method to get the configured light viewer path"""
        try:
            config_file = roaming_config_root() / 'lightviewer_settings.json'
            
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return settings.get('light_viewer_path', '')
        except Exception as e:
            print(f"Error reading light viewer path: {e}")
        return ''
    
    @staticmethod
    def get_viewer_mode() -> str:
        """Configured viewer mode ('default' or 'custom'), with back-compat."""
        try:
            config_file = roaming_config_root() / 'lightviewer_settings.json'
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return LightViewerSettingsWidget._normalize_mode(
                    settings.get('viewer_mode'),
                    settings.get('light_viewer_path', ''),
                )
        except Exception as e:
            print(f"Error reading viewer mode: {e}")
        return VIEWER_MODE_DEFAULT

    @staticmethod
    def get_viewer_selection() -> dict:
        """Resolve the viewer the CD burner should bundle.

        Returns a dict:
            mode: 'default' | 'custom'
            path: str | None      — executable to bundle (None = no viewer available)
            display_name: str
            kind: 'lite' | 'legacy' | 'override' | 'custom' | 'none'
        """
        mode = LightViewerSettingsWidget.get_viewer_mode()

        if mode == VIEWER_MODE_CUSTOM:
            path = LightViewerSettingsWidget.get_light_viewer_path()
            if path and os.path.isfile(path):
                return {
                    'mode': mode,
                    'path': path,
                    'display_name': Path(path).stem,
                    'kind': 'custom',
                }
            return {'mode': mode, 'path': None, 'display_name': 'Custom viewer (missing)', 'kind': 'none'}

        try:
            info = resolve_default_viewer()
        except Exception as e:
            print(f"Error resolving default viewer: {e}")
            info = None
        if info is not None:
            return {
                'mode': VIEWER_MODE_DEFAULT,
                'path': info['path'],
                'display_name': info['display_name'],
                'kind': info['kind'],
            }
        return {
            'mode': VIEWER_MODE_DEFAULT,
            'path': None,
            'display_name': 'Default viewer (not built)',
            'kind': 'none',
        }

    @staticmethod
    def get_disc_label() -> str:
        """Static method to get the configured disc label"""
        try:
            config_file = roaming_config_root() / 'lightviewer_settings.json'
            
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return settings.get('disc_label', 'DICOM_IMAGES')
        except Exception as e:
            print(f"Error reading disc label: {e}")
        return 'DICOM_IMAGES'
