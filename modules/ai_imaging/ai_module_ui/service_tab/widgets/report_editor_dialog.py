"""
Report Editor Dialog Widget

A professional dialog for viewing and editing medical report HTML content
with full RTL support, rich text editing capabilities, and maximize/minimize.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QTextEdit, QMessageBox, QComboBox, QToolButton,
    QFrame, QSplitter, QSizePolicy, QColorDialog, QFontComboBox,
    QSpinBox, QToolBar, QWidgetAction, QMenu, QInputDialog
)
from PySide6.QtCore import Qt, Signal, QTimer, QSize
from PySide6.QtGui import (
    QFont, QTextCharFormat, QTextCursor, QColor, 
    QTextListFormat, QTextBlockFormat, QTextFrameFormat,
    QTextTableFormat, QTextLength, QKeySequence, QShortcut,
    QIcon
)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog
import qtawesome as qta

from modules.network.socket_token_manager import get_socket_token_manager
from PacsClient.pacs.patient_tab.ui.patient_ui.reception_reports_viewer import ReceptionReportsViewer

from ..reception_data_styles import (
    COLORS, FONTS, FONT_SIZES, BORDER_RADIUS, SPACING,
    get_dialog_style, get_header_gradient_style, get_toolbar_style,
    get_footer_style, get_gradient_button_style, get_button_style,
    get_label_style, get_text_edit_style, get_status_badge_style,
    get_toolbar_button_style, is_rtl_content
)


class ReportEditorDialog(QDialog):
    """
    Professional dialog for viewing and editing medical reports.
    
    Features:
    - Full RTL/LTR support with toggle
    - Rich text editing tools (bold, italic, underline, strikethrough, lists)
    - Font family, size and color controls
    - Text alignment controls
    - Table insertion
    - Print and copy functionality
    - Maximize/Minimize buttons
    - Auto-save indicator
    """
    
    report_saved = Signal(str, str)  # Emits (content, status) when saved
    
    def __init__(self, report: dict, patient_data: dict, parent=None):
        """
        Initialize the Report Editor Dialog.
        
        Args:
            report: Report dictionary with content/findings
            patient_data: Patient data dictionary
            parent: Parent widget
        """
        super().__init__(parent)
        
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[REPORT_EDITOR] Initializing ReportEditorDialog")
        logger.info(f"[REPORT_EDITOR] Report ID: {report.get('_id', 'N/A')}")
        logger.info(f"[REPORT_EDITOR] Patient: {patient_data.get('patient', {}).get('Name', 'N/A')}")
        
        self.report = report
        self.patient_data = patient_data
        self.original_content = report.get("content", "") or report.get("findings", "")
        
        logger.info(f"[REPORT_EDITOR] Original content length: {len(self.original_content)} characters")
        
        self.is_rtl = is_rtl_content(self.original_content)
        self.is_maximized = False
        self.normal_geometry = None
        
        # Check login status
        self.token_manager = get_socket_token_manager()
        self.is_logged_in = self.token_manager.has_token()
        
        logger.info(f"[REPORT_EDITOR] Is logged in: {self.is_logged_in}")
        
        # Store current status
        self.current_status = report.get("status", "pending")
        
        # Valid status options
        self.status_options = {
            "pending": "در انتظار",
            "awaiting_physician_approval": "در انتظار تایید پزشک",
            "awaiting_secretary_approval": "در انتظار تایید منشی",
            "awaiting_approval": "در انتظار تایید",
            "physician_approved": "تایید شده توسط پزشک",
            "secretary_approved": "تایید شده توسط منشی",
            "completed": "تکمیل شده",
            "archived": "آرشیو شده",
        }
        
        logger.info("[REPORT_EDITOR] Setting up UI components")
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_connections()
        self._apply_initial_content()
        logger.info("[REPORT_EDITOR] Initialization complete")
    
    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Medical Report Editor")
        self.resize(1100, 800)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(get_dialog_style())
        
        # Remove default window frame for custom title bar
        # self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create sections
        main_layout.addWidget(self._create_header())
        main_layout.addWidget(self._create_main_toolbar())
        main_layout.addWidget(self._create_format_toolbar())
        main_layout.addWidget(self._create_editor_area(), 1)
        main_layout.addWidget(self._create_footer())
    
    def _create_header(self) -> QWidget:
        """Create the header section with patient info and window controls."""
        header = QWidget()
        header.setStyleSheet(get_header_gradient_style())
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 10, 20, 10)
        
        # Title with icon
        title_icon = QLabel()
        title_icon.setPixmap(qta.icon('fa5s.file-medical-alt', color='white').pixmap(24, 24))
        title_icon.setStyleSheet("background: transparent;")
        layout.addWidget(title_icon)
        
        title = QLabel("Medical Report Editor")
        title.setStyleSheet(f"""
            QLabel {{
                color: white;
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['title']}px;
                font-weight: bold;
                background: transparent;
            }}
        """)
        layout.addWidget(title)
        layout.addStretch()
        
        # Patient info
        patient = self.patient_data.get("patient", {})
        patient_name = patient.get("Name", "Unknown")
        reception_id = self.patient_data.get("receptionId") or self.patient_data.get("ReceptionID", "")
        
        patient_icon = QLabel()
        patient_icon.setPixmap(qta.icon('fa5s.user', color='white').pixmap(14, 14))
        patient_icon.setStyleSheet("background: transparent;")
        layout.addWidget(patient_icon)
        
        patient_info = QLabel(f" {patient_name}  |  Reception: {reception_id}")
        patient_info.setStyleSheet(f"""
            QLabel {{
                color: rgba(255, 255, 255, 0.9);
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['md']}px;
                background: transparent;
            }}
        """)
        layout.addWidget(patient_info)
        
        # Status badge
        status = self.report.get("status", "pending")
        status_texts = {"completed": "Completed", "in_progress": "In Progress", "pending": "Pending"}
        
        self.status_badge = QLabel(f"  {status_texts.get(status, status)}  ")
        self.status_badge.setStyleSheet(get_status_badge_style(status))
        layout.addWidget(self.status_badge)
        
        # Spacer
        layout.addSpacing(20)
        
        # Window control buttons
        self.btn_minimize = QToolButton()
        self.btn_minimize.setIcon(qta.icon('fa5s.window-minimize', color='white'))
        self.btn_minimize.setToolTip("Minimize")
        self.btn_minimize.setStyleSheet(self._get_window_btn_style())
        layout.addWidget(self.btn_minimize)
        
        self.btn_maximize = QToolButton()
        self.btn_maximize.setIcon(qta.icon('fa5s.window-maximize', color='white'))
        self.btn_maximize.setToolTip("Maximize")
        self.btn_maximize.setStyleSheet(self._get_window_btn_style())
        layout.addWidget(self.btn_maximize)
        
        return header
    
    def _get_window_btn_style(self) -> str:
        """Get style for window control buttons."""
        return f"""
            QToolButton {{
                background: rgba(255, 255, 255, 0.1);
                border: none;
                border-radius: 4px;
                padding: 6px;
                margin-left: 4px;
            }}
            QToolButton:hover {{
                background: rgba(255, 255, 255, 0.2);
            }}
            QToolButton:pressed {{
                background: rgba(255, 255, 255, 0.3);
            }}
        """
    
    def _create_main_toolbar(self) -> QWidget:
        """Create the main action toolbar."""
        toolbar = QWidget()
        toolbar.setStyleSheet(get_toolbar_style())
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)
        
        # File actions
        self.btn_print = self._create_action_button('fa5s.print', "Print", COLORS['secondary'])
        self.btn_copy = self._create_action_button('fa5s.copy', "Copy HTML", COLORS['info'])
        self.btn_paste = self._create_action_button('fa5s.paste', "Paste", COLORS['info'])
        
        layout.addWidget(self.btn_print)
        layout.addWidget(self.btn_copy)
        layout.addWidget(self.btn_paste)
        
        layout.addWidget(self._create_separator())
        
        # View Reception Reports button
        self.btn_view_reception_reports = self._create_action_button(
            'fa5s.file-medical', 
            "Reception Reports", 
            '#4caf50'  # Green
        )
        self.btn_view_reception_reports.setToolTip("View all reception reports for this patient")
        layout.addWidget(self.btn_view_reception_reports)
        
        layout.addWidget(self._create_separator())
        
        # Undo/Redo
        self.btn_undo = self._create_tool_button('fa5s.undo', "Undo (Ctrl+Z)")
        self.btn_redo = self._create_tool_button('fa5s.redo', "Redo (Ctrl+Y)")
        layout.addWidget(self.btn_undo)
        layout.addWidget(self.btn_redo)
        
        layout.addWidget(self._create_separator())
        
        # Find & Replace
        self.btn_find = self._create_tool_button('fa5s.search', "Find (Ctrl+F)")
        layout.addWidget(self.btn_find)
        
        layout.addStretch()
        
        # RTL/LTR toggle
        self.btn_rtl = self._create_tool_button(
            'fa5s.align-right' if self.is_rtl else 'fa5s.align-left',
            "Toggle RTL/LTR"
        )
        self.btn_rtl.setCheckable(True)
        self.btn_rtl.setChecked(self.is_rtl)
        layout.addWidget(self.btn_rtl)
        
        self.rtl_label = QLabel("RTL" if self.is_rtl else "LTR")
        self.rtl_label.setStyleSheet(get_label_style("warning", "sm"))
        layout.addWidget(self.rtl_label)
        
        layout.addWidget(self._create_separator())
        
        # Word count
        self.word_count_label = QLabel("Words: 0")
        self.word_count_label.setStyleSheet(get_label_style("secondary", "sm"))
        layout.addWidget(self.word_count_label)
        
        return toolbar
    
    def _create_format_toolbar(self) -> QWidget:
        """Create the text formatting toolbar with all editing tools."""
        toolbar = QWidget()
        toolbar.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_light']};
                border-bottom: 1px solid {COLORS['border_medium']};
            }}
        """)
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)
        
        # Font Family
        self.font_combo = QFontComboBox()
        self.font_combo.setFixedWidth(150)
        self.font_combo.setCurrentFont(QFont("Tahoma"))
        self.font_combo.setStyleSheet(self._get_combo_style())
        layout.addWidget(self.font_combo)
        
        # Font Size
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 72)
        self.font_size_spin.setValue(12)
        self.font_size_spin.setFixedWidth(55)
        self.font_size_spin.setStyleSheet(self._get_spin_style())
        layout.addWidget(self.font_size_spin)
        
        layout.addWidget(self._create_separator())
        
        # Text formatting buttons
        self.btn_bold = self._create_format_button('fa5s.bold', "Bold (Ctrl+B)", checkable=True)
        self.btn_italic = self._create_format_button('fa5s.italic', "Italic (Ctrl+I)", checkable=True)
        self.btn_underline = self._create_format_button('fa5s.underline', "Underline (Ctrl+U)", checkable=True)
        self.btn_strikethrough = self._create_format_button('fa5s.strikethrough', "Strikethrough", checkable=True)
        
        layout.addWidget(self.btn_bold)
        layout.addWidget(self.btn_italic)
        layout.addWidget(self.btn_underline)
        layout.addWidget(self.btn_strikethrough)
        
        layout.addWidget(self._create_separator())
        
        # Subscript/Superscript
        self.btn_subscript = self._create_format_button('fa5s.subscript', "Subscript", checkable=True)
        self.btn_superscript = self._create_format_button('fa5s.superscript', "Superscript", checkable=True)
        layout.addWidget(self.btn_subscript)
        layout.addWidget(self.btn_superscript)
        
        layout.addWidget(self._create_separator())
        
        # Text color
        self.btn_text_color = self._create_format_button('fa5s.palette', "Text Color")
        self.btn_highlight = self._create_format_button('fa5s.highlighter', "Highlight Color")
        layout.addWidget(self.btn_text_color)
        layout.addWidget(self.btn_highlight)
        
        layout.addWidget(self._create_separator())
        
        # Alignment
        self.btn_align_left = self._create_format_button('fa5s.align-left', "Align Left", checkable=True)
        self.btn_align_center = self._create_format_button('fa5s.align-center', "Align Center", checkable=True)
        self.btn_align_right = self._create_format_button('fa5s.align-right', "Align Right", checkable=True)
        self.btn_align_justify = self._create_format_button('fa5s.align-justify', "Justify", checkable=True)
        
        layout.addWidget(self.btn_align_left)
        layout.addWidget(self.btn_align_center)
        layout.addWidget(self.btn_align_right)
        layout.addWidget(self.btn_align_justify)
        
        layout.addWidget(self._create_separator())
        
        # Lists
        self.btn_bullet_list = self._create_format_button('fa5s.list-ul', "Bullet List")
        self.btn_number_list = self._create_format_button('fa5s.list-ol', "Numbered List")
        layout.addWidget(self.btn_bullet_list)
        layout.addWidget(self.btn_number_list)
        
        layout.addWidget(self._create_separator())
        
        # Indent
        self.btn_indent = self._create_format_button('fa5s.indent', "Increase Indent")
        self.btn_outdent = self._create_format_button('fa5s.outdent', "Decrease Indent")
        layout.addWidget(self.btn_indent)
        layout.addWidget(self.btn_outdent)
        
        layout.addWidget(self._create_separator())
        
        # Insert actions
        self.btn_link = self._create_format_button('fa5s.link', "Insert Link")
        self.btn_table = self._create_format_button('fa5s.table', "Insert Table")
        self.btn_hr = self._create_format_button('fa5s.minus', "Horizontal Line")
        layout.addWidget(self.btn_link)
        layout.addWidget(self.btn_table)
        layout.addWidget(self.btn_hr)
        
        layout.addWidget(self._create_separator())
        
        # Clear formatting
        self.btn_clear_format = self._create_format_button('fa5s.eraser', "Clear Formatting")
        layout.addWidget(self.btn_clear_format)
        
        layout.addStretch()
        
        # Heading dropdown
        heading_label = QLabel("Heading:")
        heading_label.setStyleSheet(get_label_style("secondary", "sm"))
        layout.addWidget(heading_label)
        
        self.heading_combo = QComboBox()
        self.heading_combo.addItems(["Normal", "Heading 1", "Heading 2", "Heading 3", "Heading 4"])
        self.heading_combo.setFixedWidth(100)
        self.heading_combo.setStyleSheet(self._get_combo_style())
        layout.addWidget(self.heading_combo)
        
        return toolbar
    
    def _create_action_button(self, icon_name: str, text: str, color: str) -> QPushButton:
        """Create an action button with icon and text."""
        btn = QPushButton(f" {text}")
        btn.setIcon(qta.icon(icon_name, color='white'))
        btn.setStyleSheet(get_toolbar_button_style(color))
        return btn
    
    def _create_tool_button(self, icon_name: str, tooltip: str) -> QToolButton:
        """Create a tool button."""
        btn = QToolButton()
        btn.setIcon(qta.icon(icon_name, color=COLORS['text_primary']))
        btn.setToolTip(tooltip)
        btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 5px;
                min-width: 28px;
                min-height: 28px;
            }}
            QToolButton:hover {{
                background-color: {COLORS['bg_card']};
            }}
            QToolButton:pressed {{
                background-color: {COLORS['border_medium']};
            }}
        """)
        return btn
    
    def _create_format_button(self, icon_name: str, tooltip: str, checkable: bool = False) -> QToolButton:
        """Create a formatting tool button."""
        btn = QToolButton()
        btn.setIcon(qta.icon(icon_name, color=COLORS['text_primary']))
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: 1px solid transparent;
                border-radius: 3px;
                padding: 4px;
                min-width: 26px;
                min-height: 26px;
            }}
            QToolButton:hover {{
                background-color: {COLORS['bg_card']};
                border-color: {COLORS['border_medium']};
            }}
            QToolButton:pressed {{
                background-color: {COLORS['border_medium']};
            }}
            QToolButton:checked {{
                background-color: {COLORS['info']};
                border-color: {COLORS['info']};
            }}
        """)
        return btn
    
    def _create_separator(self) -> QFrame:
        """Create a vertical separator line."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"background-color: {COLORS['border_medium']}; max-width: 1px; margin: 2px 4px;")
        return sep
    
    def _get_combo_style(self) -> str:
        """Get style for combo boxes."""
        return f"""
            QComboBox, QFontComboBox {{
                background-color: {COLORS['bg_lighter']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_medium']};
                border-radius: 3px;
                padding: 4px 8px;
                font-size: {FONT_SIZES['sm']}px;
            }}
            QComboBox:hover, QFontComboBox:hover {{
                border-color: {COLORS['info']};
            }}
            QComboBox::drop-down, QFontComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView, QFontComboBox QAbstractItemView {{
                background-color: {COLORS['bg_light']};
                color: {COLORS['text_primary']};
                selection-background-color: {COLORS['info']};
            }}
        """
    
    def _get_spin_style(self) -> str:
        """Get style for spin boxes."""
        return f"""
            QSpinBox {{
                background-color: {COLORS['bg_lighter']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_medium']};
                border-radius: 3px;
                padding: 4px;
                font-size: {FONT_SIZES['sm']}px;
            }}
            QSpinBox:hover {{
                border-color: {COLORS['info']};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                width: 16px;
                background: {COLORS['bg_card']};
                border: none;
            }}
        """
    
    def _create_editor_area(self) -> QWidget:
        """Create the main editor area."""
        container = QWidget()
        container.setStyleSheet(f"background-color: {COLORS['bg_darkest']};")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(0)
        
        # Report container with white background
        report_container = QWidget()
        report_container.setStyleSheet(f"""
            QWidget {{
                background-color: #ffffff;
                border: 2px solid {COLORS['border_dark']};
                border-radius: {BORDER_RADIUS['lg']}px;
            }}
        """)
        report_layout = QVBoxLayout(report_container)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setSpacing(0)
        
        # Editor header
        editor_header = QWidget()
        editor_header.setStyleSheet(f"""
            QWidget {{
                background-color: #f8f9fa;
                border-top-left-radius: {BORDER_RADIUS['md']}px;
                border-top-right-radius: {BORDER_RADIUS['md']}px;
                border-bottom: 1px solid #dee2e6;
            }}
        """)
        header_layout = QHBoxLayout(editor_header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        
        header_icon = QLabel()
        header_icon.setPixmap(qta.icon('fa5s.file-alt', color='#27ae60').pixmap(14, 14))
        header_icon.setStyleSheet("background: transparent;")
        header_layout.addWidget(header_icon)
        
        header_title = QLabel(" Report Content")
        header_title.setStyleSheet(f"""
            QLabel {{
                color: #27ae60;
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['md']}px;
                font-weight: bold;
                background: transparent;
            }}
        """)
        header_layout.addWidget(header_title)
        header_layout.addStretch()
        
        # Character count
        self.char_count_label = QLabel("Chars: 0")
        self.char_count_label.setStyleSheet(f"""
            QLabel {{
                color: #7f8c8d;
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['xs']}px;
                background: transparent;
            }}
        """)
        header_layout.addWidget(self.char_count_label)
        
        report_layout.addWidget(editor_header)
        
        # Text editor
        self.text_edit = QTextEdit()
        self.text_edit.setStyleSheet(get_text_edit_style(self.is_rtl))
        self.text_edit.setAcceptRichText(True)
        
        if self.is_rtl:
            self.text_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        
        # Set default font
        font = QFont()
        font.setFamily("Tahoma" if self.is_rtl else "Segoe UI")
        font.setPointSize(12)
        self.text_edit.setFont(font)
        
        report_layout.addWidget(self.text_edit)
        layout.addWidget(report_container)
        
        return container
    
    def _create_footer(self) -> QWidget:
        """Create the footer with action buttons."""
        footer = QWidget()
        footer.setStyleSheet(get_footer_style())
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(20, 10, 20, 10)
        
        # Modified indicator
        self.modified_icon = QLabel()
        self.modified_icon.setStyleSheet("background: transparent;")
        layout.addWidget(self.modified_icon)
        
        self.modified_label = QLabel("")
        self.modified_label.setStyleSheet(get_label_style("warning", "sm"))
        layout.addWidget(self.modified_label)
        
        # Login status indicator
        if not self.is_logged_in:
            login_warning_icon = QLabel()
            login_warning_icon.setPixmap(qta.icon('fa5s.lock', color=COLORS['error']).pixmap(14, 14))
            login_warning_icon.setStyleSheet("background: transparent; margin-left: 10px;")
            layout.addWidget(login_warning_icon)
            
            login_warning_label = QLabel(" برای ذخیره گزارش باید لاگین کنید")
            login_warning_label.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['error']};
                    font-family: 'Tahoma', {FONTS['primary']};
                    font-size: {FONT_SIZES['sm']}px;
                    background: transparent;
                }}
            """)
            layout.addWidget(login_warning_label)
        
        layout.addStretch()
        
        # Status dropdown
        status_label = QLabel("وضعیت:")
        status_label.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_primary']};
                font-family: 'Tahoma', {FONTS['primary']};
                font-size: {FONT_SIZES['sm']}px;
                background: transparent;
            }}
        """)
        layout.addWidget(status_label)
        
        self.status_combo = QComboBox()
        self.status_combo.setFixedWidth(180)
        self.status_combo.setStyleSheet(self._get_combo_style())
        
        # Populate status dropdown
        current_index = 0
        for idx, (status_key, status_text) in enumerate(self.status_options.items()):
            self.status_combo.addItem(status_text, status_key)
            if status_key == self.current_status:
                current_index = idx
        self.status_combo.setCurrentIndex(current_index)
        
        # Disable if not logged in
        if not self.is_logged_in:
            self.status_combo.setEnabled(False)
            self.status_combo.setToolTip("برای تغییر وضعیت باید لاگین کنید")
        
        layout.addWidget(self.status_combo)
        layout.addSpacing(10)
        
        # Reset button
        self.btn_reset = QPushButton(" Reset")
        self.btn_reset.setIcon(qta.icon('fa5s.undo-alt', color='white'))
        self.btn_reset.setStyleSheet(get_button_style("warning", "md"))
        layout.addWidget(self.btn_reset)
        
        # Save button
        self.btn_save = QPushButton(" Save Changes")
        self.btn_save.setIcon(qta.icon('fa5s.save', color='white'))
        self.btn_save.setStyleSheet(get_gradient_button_style())
        self.btn_save.setMinimumWidth(140)
        
        # Disable save if not logged in
        if not self.is_logged_in:
            self.btn_save.setEnabled(False)
            self.btn_save.setToolTip("برای ذخیره گزارش باید لاگین کنید")
            self.btn_save.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['border_medium']};
                    color: {COLORS['text_secondary']};
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-family: {FONTS['primary']};
                    font-size: {FONT_SIZES['md']}px;
                }}
            """)
        
        layout.addWidget(self.btn_save)
        
        # Close button
        self.btn_close = QPushButton(" Close")
        self.btn_close.setIcon(qta.icon('fa5s.times', color='white'))
        self.btn_close.setStyleSheet(get_button_style("error", "md"))
        self.btn_close.setMinimumWidth(100)
        layout.addWidget(self.btn_close)
        
        return footer
    
    def _setup_shortcuts(self):
        """Set up keyboard shortcuts."""
        QShortcut(QKeySequence.StandardKey.Bold, self, self._toggle_bold)
        QShortcut(QKeySequence.StandardKey.Italic, self, self._toggle_italic)
        QShortcut(QKeySequence.StandardKey.Underline, self, self._toggle_underline)
        QShortcut(QKeySequence.StandardKey.Undo, self, self.text_edit.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.text_edit.redo)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self._toggle_strikethrough)
    
    def _setup_connections(self):
        """Set up signal connections."""
        # Window controls
        self.btn_minimize.clicked.connect(self.showMinimized)
        self.btn_maximize.clicked.connect(self._toggle_maximize)
        
        # Main toolbar
        self.btn_print.clicked.connect(self._print_report)
        self.btn_copy.clicked.connect(self._copy_html)
        self.btn_paste.clicked.connect(self._paste_text)
        self.btn_view_reception_reports.clicked.connect(self._show_reception_reports_viewer)
        self.btn_undo.clicked.connect(self.text_edit.undo)
        self.btn_redo.clicked.connect(self.text_edit.redo)
        self.btn_find.clicked.connect(self._show_find_dialog)
        self.btn_rtl.clicked.connect(self._toggle_rtl)
        
        # Format toolbar - Text formatting
        self.btn_bold.clicked.connect(self._toggle_bold)
        self.btn_italic.clicked.connect(self._toggle_italic)
        self.btn_underline.clicked.connect(self._toggle_underline)
        self.btn_strikethrough.clicked.connect(self._toggle_strikethrough)
        self.btn_subscript.clicked.connect(self._toggle_subscript)
        self.btn_superscript.clicked.connect(self._toggle_superscript)
        
        # Colors
        self.btn_text_color.clicked.connect(self._change_text_color)
        self.btn_highlight.clicked.connect(self._change_highlight_color)
        
        # Alignment
        self.btn_align_left.clicked.connect(lambda: self._set_alignment(Qt.AlignmentFlag.AlignLeft))
        self.btn_align_center.clicked.connect(lambda: self._set_alignment(Qt.AlignmentFlag.AlignCenter))
        self.btn_align_right.clicked.connect(lambda: self._set_alignment(Qt.AlignmentFlag.AlignRight))
        self.btn_align_justify.clicked.connect(lambda: self._set_alignment(Qt.AlignmentFlag.AlignJustify))
        
        # Lists
        self.btn_bullet_list.clicked.connect(self._insert_bullet_list)
        self.btn_number_list.clicked.connect(self._insert_number_list)
        
        # Indent
        self.btn_indent.clicked.connect(self._increase_indent)
        self.btn_outdent.clicked.connect(self._decrease_indent)
        
        # Insert
        self.btn_link.clicked.connect(self._insert_link)
        self.btn_table.clicked.connect(self._insert_table)
        self.btn_hr.clicked.connect(self._insert_horizontal_line)
        
        # Clear formatting
        self.btn_clear_format.clicked.connect(self._clear_formatting)
        
        # Font controls
        self.font_combo.currentFontChanged.connect(self._change_font_family)
        self.font_size_spin.valueChanged.connect(self._change_font_size)
        self.heading_combo.currentIndexChanged.connect(self._apply_heading)
        
        # Footer buttons
        self.btn_reset.clicked.connect(self._reset_content)
        self.btn_save.clicked.connect(self._save_report)
        self.btn_close.clicked.connect(self.close)
        
        # Text changes
        self.text_edit.textChanged.connect(self._on_text_changed)
        self.text_edit.cursorPositionChanged.connect(self._update_format_buttons)
    
    def _apply_initial_content(self):
        """Apply the initial report content."""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info("[REPORT_EDITOR] Applying initial content to editor")
        logger.info(f"[REPORT_EDITOR] Content length: {len(self.original_content)} characters")
        logger.info(f"[REPORT_EDITOR] Is RTL: {self.is_rtl}")
        
        try:
            self.text_edit.setHtml(self.original_content)
            self.text_edit.document().setModified(False)
            self._update_counts()
            logger.info("[REPORT_EDITOR] ✅ Content applied successfully")
        except Exception as e:
            logger.error(f"[REPORT_EDITOR] ❌ Error applying content: {e}")
            import traceback
            logger.error(f"[REPORT_EDITOR] Traceback: {traceback.format_exc()}")
    
    # ═══════════════════════════════════════════════════════════════════════
    # WINDOW CONTROLS
    # ═══════════════════════════════════════════════════════════════════════
    
    def _toggle_maximize(self):
        """Toggle between maximized and normal window state."""
        if self.is_maximized:
            if self.normal_geometry:
                self.setGeometry(self.normal_geometry)
            self.btn_maximize.setIcon(qta.icon('fa5s.window-maximize', color='white'))
            self.btn_maximize.setToolTip("Maximize")
            self.is_maximized = False
        else:
            self.normal_geometry = self.geometry()
            self.showMaximized()
            self.btn_maximize.setIcon(qta.icon('fa5s.window-restore', color='white'))
            self.btn_maximize.setToolTip("Restore")
            self.is_maximized = True
    
    # ═══════════════════════════════════════════════════════════════════════
    # TEXT FORMATTING
    # ═══════════════════════════════════════════════════════════════════════
    
    def _toggle_bold(self):
        """Toggle bold formatting."""
        fmt = QTextCharFormat()
        if self.text_edit.fontWeight() == QFont.Weight.Bold:
            fmt.setFontWeight(QFont.Weight.Normal)
        else:
            fmt.setFontWeight(QFont.Weight.Bold)
        self._merge_format_on_selection(fmt)
    
    def _toggle_italic(self):
        """Toggle italic formatting."""
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.text_edit.fontItalic())
        self._merge_format_on_selection(fmt)
    
    def _toggle_underline(self):
        """Toggle underline formatting."""
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.text_edit.fontUnderline())
        self._merge_format_on_selection(fmt)
    
    def _toggle_strikethrough(self):
        """Toggle strikethrough formatting."""
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(not self.text_edit.currentCharFormat().fontStrikeOut())
        self._merge_format_on_selection(fmt)
    
    def _toggle_subscript(self):
        """Toggle subscript formatting."""
        fmt = QTextCharFormat()
        current = self.text_edit.currentCharFormat().verticalAlignment()
        if current == QTextCharFormat.VerticalAlignment.AlignSubScript:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        else:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSubScript)
        self._merge_format_on_selection(fmt)
    
    def _toggle_superscript(self):
        """Toggle superscript formatting."""
        fmt = QTextCharFormat()
        current = self.text_edit.currentCharFormat().verticalAlignment()
        if current == QTextCharFormat.VerticalAlignment.AlignSuperScript:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        else:
            fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
        self._merge_format_on_selection(fmt)
    
    def _merge_format_on_selection(self, fmt: QTextCharFormat):
        """Apply format to current selection or cursor position."""
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        cursor.mergeCharFormat(fmt)
        self.text_edit.mergeCurrentCharFormat(fmt)
    
    def _change_text_color(self):
        """Open color dialog for text color."""
        color = QColorDialog.getColor(self.text_edit.textColor(), self, "Select Text Color")
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setForeground(color)
            self._merge_format_on_selection(fmt)
    
    def _change_highlight_color(self):
        """Open color dialog for highlight/background color."""
        color = QColorDialog.getColor(Qt.GlobalColor.yellow, self, "Select Highlight Color")
        if color.isValid():
            fmt = QTextCharFormat()
            fmt.setBackground(color)
            self._merge_format_on_selection(fmt)
    
    def _change_font_family(self, font: QFont):
        """Change font family."""
        fmt = QTextCharFormat()
        fmt.setFontFamilies([font.family()])
        self._merge_format_on_selection(fmt)
    
    def _change_font_size(self, size: int):
        """Change font size."""
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self._merge_format_on_selection(fmt)
    
    def _set_alignment(self, alignment):
        """Set paragraph alignment."""
        self.text_edit.setAlignment(alignment)
        self._update_alignment_buttons()
    
    def _update_alignment_buttons(self):
        """Update alignment button states."""
        alignment = self.text_edit.alignment()
        self.btn_align_left.setChecked(alignment == Qt.AlignmentFlag.AlignLeft)
        self.btn_align_center.setChecked(alignment == Qt.AlignmentFlag.AlignCenter)
        self.btn_align_right.setChecked(alignment == Qt.AlignmentFlag.AlignRight)
        self.btn_align_justify.setChecked(alignment == Qt.AlignmentFlag.AlignJustify)
    
    def _apply_heading(self, index: int):
        """Apply heading style."""
        cursor = self.text_edit.textCursor()
        block_fmt = QTextBlockFormat()
        char_fmt = QTextCharFormat()
        
        if index == 0:  # Normal
            char_fmt.setFontPointSize(12)
            char_fmt.setFontWeight(QFont.Weight.Normal)
        elif index == 1:  # H1
            char_fmt.setFontPointSize(24)
            char_fmt.setFontWeight(QFont.Weight.Bold)
        elif index == 2:  # H2
            char_fmt.setFontPointSize(20)
            char_fmt.setFontWeight(QFont.Weight.Bold)
        elif index == 3:  # H3
            char_fmt.setFontPointSize(16)
            char_fmt.setFontWeight(QFont.Weight.Bold)
        elif index == 4:  # H4
            char_fmt.setFontPointSize(14)
            char_fmt.setFontWeight(QFont.Weight.Bold)
        
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        cursor.mergeBlockFormat(block_fmt)
        cursor.mergeCharFormat(char_fmt)
    
    # ═══════════════════════════════════════════════════════════════════════
    # LISTS AND INDENTATION
    # ═══════════════════════════════════════════════════════════════════════
    
    def _insert_bullet_list(self):
        """Insert or toggle bullet list."""
        cursor = self.text_edit.textCursor()
        list_format = QTextListFormat()
        list_format.setStyle(QTextListFormat.Style.ListDisc)
        cursor.insertList(list_format)
    
    def _insert_number_list(self):
        """Insert or toggle numbered list."""
        cursor = self.text_edit.textCursor()
        list_format = QTextListFormat()
        list_format.setStyle(QTextListFormat.Style.ListDecimal)
        cursor.insertList(list_format)
    
    def _increase_indent(self):
        """Increase paragraph indent."""
        cursor = self.text_edit.textCursor()
        block_fmt = cursor.blockFormat()
        block_fmt.setIndent(block_fmt.indent() + 1)
        cursor.setBlockFormat(block_fmt)
    
    def _decrease_indent(self):
        """Decrease paragraph indent."""
        cursor = self.text_edit.textCursor()
        block_fmt = cursor.blockFormat()
        if block_fmt.indent() > 0:
            block_fmt.setIndent(block_fmt.indent() - 1)
            cursor.setBlockFormat(block_fmt)
    
    # ═══════════════════════════════════════════════════════════════════════
    # INSERT ELEMENTS
    # ═══════════════════════════════════════════════════════════════════════
    
    def _insert_link(self):
        """Insert a hyperlink."""
        url, ok = QInputDialog.getText(self, "Insert Link", "Enter URL:")
        if ok and url:
            text, ok2 = QInputDialog.getText(self, "Link Text", "Enter link text:", text=url)
            if ok2:
                cursor = self.text_edit.textCursor()
                fmt = QTextCharFormat()
                fmt.setAnchor(True)
                fmt.setAnchorHref(url)
                fmt.setForeground(QColor(COLORS['info']))
                fmt.setFontUnderline(True)
                cursor.insertText(text or url, fmt)
    
    def _insert_table(self):
        """Insert a table."""
        rows, ok1 = QInputDialog.getInt(self, "Insert Table", "Number of rows:", 3, 1, 20)
        if ok1:
            cols, ok2 = QInputDialog.getInt(self, "Insert Table", "Number of columns:", 3, 1, 10)
            if ok2:
                cursor = self.text_edit.textCursor()
                table_fmt = QTextTableFormat()
                table_fmt.setBorder(1)
                table_fmt.setCellPadding(5)
                table_fmt.setCellSpacing(0)
                table_fmt.setBorderStyle(QTextFrameFormat.BorderStyle.BorderStyle_Solid)
                cursor.insertTable(rows, cols, table_fmt)
    
    def _insert_horizontal_line(self):
        """Insert a horizontal line."""
        cursor = self.text_edit.textCursor()
        cursor.insertHtml("<hr style='border: 1px solid #ccc; margin: 10px 0;'>")
    
    def _clear_formatting(self):
        """Clear all formatting from selection."""
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            cursor.setCharFormat(QTextCharFormat())
        else:
            self.text_edit.setCurrentCharFormat(QTextCharFormat())
    
    # ═══════════════════════════════════════════════════════════════════════
    # RTL/LTR
    # ═══════════════════════════════════════════════════════════════════════
    
    def _toggle_rtl(self):
        """Toggle RTL/LTR direction."""
        self.is_rtl = not self.is_rtl
        
        if self.is_rtl:
            self.text_edit.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            self.btn_rtl.setIcon(qta.icon('fa5s.align-right', color=COLORS['text_primary']))
            self.rtl_label.setText("RTL")
        else:
            self.text_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            self.btn_rtl.setIcon(qta.icon('fa5s.align-left', color=COLORS['text_primary']))
            self.rtl_label.setText("LTR")
        
        # Update text alignment for all blocks
        cursor = self.text_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setAlignment(
            Qt.AlignmentFlag.AlignRight if self.is_rtl else Qt.AlignmentFlag.AlignLeft
        )
        cursor.mergeBlockFormat(block_format)
    
    # ═══════════════════════════════════════════════════════════════════════
    # OTHER ACTIONS
    # ═══════════════════════════════════════════════════════════════════════
    
    def _print_report(self):
        """Print the report."""
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        print_dialog = QPrintDialog(printer, self)
        if print_dialog.exec() == QDialog.DialogCode.Accepted:
            self.text_edit.print_(printer)
    
    def _copy_html(self):
        """Copy HTML content to clipboard."""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_edit.toHtml())
        
        # Visual feedback
        self.btn_copy.setIcon(qta.icon('fa5s.check', color='white'))
        self.btn_copy.setText(" Copied!")
        QTimer.singleShot(1500, lambda: (
            self.btn_copy.setIcon(qta.icon('fa5s.copy', color='white')),
            self.btn_copy.setText(" Copy HTML")
        ))
    
    def _paste_text(self):
        """Paste from clipboard."""
        self.text_edit.paste()
    
    def _show_find_dialog(self):
        """Show find/replace dialog."""
        text, ok = QInputDialog.getText(self, "Find", "Search for:")
        if ok and text:
            if not self.text_edit.find(text):
                # Try from beginning
                cursor = self.text_edit.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                self.text_edit.setTextCursor(cursor)
                if not self.text_edit.find(text):
                    QMessageBox.information(self, "Find", f"'{text}' not found.")
    
    def _show_reception_reports_viewer(self):
        """Show reception reports viewer for this patient."""
        # Extract ALL possible patient identifiers from patient data
        patient_ids = []
        
        if self.patient_data:
            # Collect all possible identifiers
            patient = self.patient_data.get('patient', {})
            
            # Try all possible ID fields
            for field_value in [
                self.patient_data.get('receptionId'),           # Reception ID (28383)
                self.patient_data.get('nationalCode'),          # National Code (0046922229)
                patient.get('NationalID'),                      # Patient National ID
                patient.get('_id'),                             # MongoDB Patient ID
                self.patient_data.get('_id'),                   # MongoDB Reception ID
                self.patient_data.get('studyUID'),              # Study UID (if available)
            ]:
                if field_value and str(field_value) not in [str(x) for x in patient_ids]:
                    patient_ids.append(str(field_value))
        
        if not patient_ids:
            QMessageBox.warning(
                self,
                "No Patient Selected",
                "Cannot show reception reports: No patient identifiers found."
            )
            return
        
        # Create and show viewer
        viewer = ReceptionReportsViewer(parent=self)
        
        # Display first identifier as title
        display_id = patient_ids[0]
        viewer.setWindowTitle(f"Reception Reports - Patient: {display_id}")
        
        # Load reports searching with ALL patient identifiers
        viewer.load_reports_multi_id(patient_ids)
        
        # Show as modal dialog
        viewer.exec()
    
    def _reset_content(self):
        """Reset to original content."""
        reply = QMessageBox.question(
            self,
            "Reset Content",
            "Are you sure you want to reset to the original content? All changes will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.text_edit.setHtml(self.original_content)
            self.text_edit.document().setModified(False)
            self._check_modified()
    
    def _save_report(self):
        """Save the report content."""
        if not self.is_logged_in:
            QMessageBox.warning(
                self,
                "Authentication Error",
                "You must be logged in to save the report."
            )
            return

        
        new_content = self.text_edit.toHtml()
        selected_status = self.status_combo.currentData()
        self.report_saved.emit(new_content, selected_status)
        self.text_edit.document().setModified(False)
        self._check_modified()
    
    def _on_text_changed(self):
        """Handle text content changes."""
        self._check_modified()
        self._update_counts()
    
    def _check_modified(self):
        """Update the modified indicator."""
        if self.text_edit.document().isModified():
            self.modified_icon.setPixmap(
                qta.icon('fa5s.exclamation-triangle', color=COLORS['warning']).pixmap(14, 14)
            )
            self.modified_label.setText(" Unsaved changes")
        else:
            self.modified_icon.clear()
            self.modified_label.setText("")
    
    def _update_counts(self):
        """Update word and character counts."""
        text = self.text_edit.toPlainText()
        words = len(text.split()) if text.strip() else 0
        chars = len(text)
        self.word_count_label.setText(f"Words: {words}")
        self.char_count_label.setText(f"Chars: {chars}")
    
    def _update_format_buttons(self):
        """Update format button states based on current cursor position."""
        fmt = self.text_edit.currentCharFormat()
        self.btn_bold.setChecked(fmt.fontWeight() == QFont.Weight.Bold)
        self.btn_italic.setChecked(fmt.fontItalic())
        self.btn_underline.setChecked(fmt.fontUnderline())
        self.btn_strikethrough.setChecked(fmt.fontStrikeOut())
        self.btn_subscript.setChecked(fmt.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSubScript)
        self.btn_superscript.setChecked(fmt.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSuperScript)
        
        # Update alignment buttons
        self._update_alignment_buttons()
        
        # Update font controls
        self.font_combo.blockSignals(True)
        self.font_size_spin.blockSignals(True)
        
        font = fmt.font()
        self.font_combo.setCurrentFont(font)
        size = int(fmt.fontPointSize()) if fmt.fontPointSize() > 0 else 12
        self.font_size_spin.setValue(size)
        
        self.font_combo.blockSignals(False)
        self.font_size_spin.blockSignals(False)
    
    def get_html_content(self) -> str:
        """Get the current HTML content."""
        return self.text_edit.toHtml()
    
    def closeEvent(self, event):
        """Handle dialog close with unsaved changes warning."""
        if self.text_edit.document().isModified():
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before closing?",
                QMessageBox.StandardButton.Save | 
                QMessageBox.StandardButton.Discard | 
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save
            )
            
            if reply == QMessageBox.StandardButton.Save:
                self._save_report()
                event.accept()
            elif reply == QMessageBox.StandardButton.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
