from PySide6.QtCore import QSize, Qt, QPoint, QTimer
from PySide6.QtGui import QIcon, QPixmap, QTransform
from PySide6.QtWidgets import QPushButton, QToolBar, QToolButton, QMenu, QWidgetAction, QHBoxLayout, QVBoxLayout, \
    QLabel, QWidget, \
    QGroupBox, QApplication, QProgressDialog,QScrollArea,QFrame
import qtawesome as qta
from PySide6.QtGui import QFont
import json
import logging
import os
import random
from PacsClient.pacs.patient_tab.interactor_styles import (
    RulerInteractorStyle, EraserInteractorStyle, AngleInteractorStyle, TwoLineAngleInteractorStyle, ArrowInteractorStyle,
    TextInteractorStyle, DefaultInteractionInteractorStyle, RotateInteractorStyle, RoiInteractorStyle,
    CircleRoiInteractorStyle, ToolAccess)
from PacsClient.pacs.patient_tab.interactor_styles.ai_chat_interactorstyle import AIChatInteractorStyle

from PacsClient.pacs.patient_tab.utils import NodeViewer, MatrixSelector
from PacsClient.utils import ICON_PATH, upload_attachments_for_study
from PacsClient.utils.config import ATTACHMENT_PATH
from PacsClient.utils import list_files_in_folder
from PacsClient.utils import get_attachments_uploaded

from .voice_tool_ui import VoiceWidget
from .attachments_dropdown import AttachmentsDropdownWidget
from threading import Thread
from PacsClient.pacs.patient_tab.zeta_sync.sync_types import SyncMode


def create_dropdown_tool(text, icon_name=None, icon_color='#60a5fa'):
    """
    ساخت دکمه dropdown با UI مدرن و یکپارچه
    
    Args:
        text: متن دکمه
        icon_name: نام فایل آیکون (اختیاری)
        icon_color: رنگ آیکون fontawesome (پیش‌فرض: آبی)
    """
    btn = QPushButton(f"  {text}")  # فاصله برای آیکون
    btn.setCheckable(True)
    
    if icon_name is not None:
        if icon_name.startswith('fa'):  # fontawesome icon
            btn.setIcon(qta.icon(icon_name, color=icon_color))
        else:  # file icon
            icon = QIcon(f"{ICON_PATH}/{icon_name}")
            btn.setIcon(icon)
        btn.setIconSize(QSize(18, 18))
    
    btn.setCursor(Qt.PointingHandCursor)
    btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2d3748, stop:1 #1f2937);
            color: #f3f4f6;
            border: 1px solid #4b5563;
            border-radius: 6px;
            padding: 10px 14px;
            text-align: left;
            font-size: 13px;
            font-family: 'Roboto', sans-serif;
            font-weight: 500;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #374151, stop:1 #2d3748);
            border-color: #60a5fa;
            color: #ffffff;
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1f2937, stop:1 #111827);
            border-color: #3b82f6;
        }
        QPushButton:checked {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #059669, stop:1 #047857);
            border-color: #10b981;
            color: #ffffff;
        }
    """)
    
    return btn


def create_tool_btn(parent, name, icon_name=None, text_icon=None, icon_size: QSize | tuple[int, int] | int = 20):
    """
    icon_size:
      - عدد (مثلاً 28) → 28x28
      - tuple (w, h)  → wxh
      - QSize(...)    → همان
    """
    # نرمال‌سازی اندازه برای QSS
    if isinstance(icon_size, int):
        w = h = icon_size
    elif isinstance(icon_size, tuple):
        w, h = icon_size
    elif isinstance(icon_size, QSize):
        w, h = icon_size.width(), icon_size.height()
    else:
        w = h = 28

    btn = QPushButton(parent)
    btn.setCheckable(True)
    btn.setToolTip(name)
    btn.setCursor(Qt.PointingHandCursor)

    if icon_name is None:
        btn.setText(text_icon or "")
    else:
        icon = QIcon(f"{ICON_PATH}/{icon_name}")
        btn.setIcon(icon)
        # اگر نمی‌خواهی به setIconSize دست بزنی، این خط را می‌توانی حذف کنی
        btn.setIconSize(QSize(20, 20))  # این مقدار با qproperty-iconSize override می‌شود

    btn.setStyleSheet(f"""
        QPushButton {{
            qproperty-iconSize: {w}px {h}px;   /* ← اندازه‌ی داینامیک از پارامتر تابع */
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #374151, stop:1 #1f2937);
            color: #e5e7eb;
            border: 1px solid #4b5563;
            border-radius: 6px;
            padding: 4px 6px;
            margin: 1px;
            min-width: 36px;
            min-height: 36px;
            font-size: 13px;
            font-family: 'Roboto', sans-serif;
            font-weight: 500;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #4b5563, stop:1 #374151);
            border-color: #6b7280;
        }}
        QPushButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1f2937, stop:1 #111827);
        }}
        QPushButton:checked {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #059669, stop:1 #047857);
            border-color: #10b981;
            color: #ffffff;
        }}
        QPushButton:disabled {{
            background: #1f2937;
            border-color: #374151;
            color: #6b7280;
        }}
    """)

    return btn


class BadgeButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # برچسبِ نشان (badge)
        self._badge = QLabel(self)
        self._badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # استایل: gradient مدرن با طرح toolbar
        self._badge.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #dc2626, stop:1 #b91c1c);  /* red gradient */
                color: #ffffff;
                border: 1px solid rgba(220, 38, 38, 0.4);  /* خط دور ملایم‌تر */
                border-radius: 8px;          /* همخوانی با border-radius toolbar */
                padding: 1px 4px;            /* padding بهتر */
                font-weight: 600;
                font-family: 'Roboto', sans-serif;
            }
        """)
        f = QFont()
        f.setPointSize(7)   # کوچک‌تر برای سازگاری بهتر
        f.setFamily('Roboto')
        self._badge.setFont(f)
        self._badge.setFixedHeight(16)  # کمی کوچک‌تر برای ظاهر بهتر
        # self._badge.hide()

        self._count = 0

    def setCount(self, n: int):
        """تنظیم عدد badge؛ اگر <=0 باشد مخفی می‌شود."""
        self._count = max(0, int(n))
        if self._count <= 0:
            self._badge.hide()
        else:
            # نمایش 99+ برای اعداد بزرگ
            text = f"{self._count}" if self._count < 100 else "99+"
            self._badge.setText(text)
            
            # محاسبه عرض بر اساس طول متن
            # برای اعداد تک رقمی: 20px، دو رقمی: 24px، 99+: 28px
            text_len = len(text)
            if text_len == 1:
                min_width = 20
            elif text_len == 2:
                min_width = 24
            else:  # "99+"
                min_width = 28
            
            self._badge.setFixedWidth(min_width)
            self._badge.show()
        self._repositionBadge()

    def increment(self, step: int = 1):
        self.setCount(self._count + step)

    def decrement(self, step: int = 1):
        self.setCount(self._count - step)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._repositionBadge()

    def _repositionBadge(self):
        # if not self._badge.isVisible():
        #     return
        # موقعیت بهتر: گوشه بالا-راست با فاصله کمتر
        margin_x = 1  # فاصله از راست
        margin_y = 0  # فاصله از بالا (به خط حاشیه نزدیک‌تر)
        x = self.width() - self._badge.width() - margin_x
        y = margin_y
        self._badge.move(x, y)


class ToolbarManager:
    def __init__(self, patient_widget):
        self.patient_widget = patient_widget
        self.tool_access = ToolAccess()
        self.tool_selected = None
        self.tools_button = {}
        self.measurement_tools = {
            self.tool_access.ANGLE,
            self.tool_access.TWO_LINE_ANGLE,
            self.tool_access.ARROW,
            self.tool_access.TEXT,
            self.tool_access.ROI,
            self.tool_access.CIRCLE_ROI,
        }
        self.mpr_dropdown_tools = {
            self.tool_access.CURVED_MPR,
            self.tool_access.MIP,
            self.tool_access.MINIP,
            self.tool_access.THICK_SLAB,
        }
        
        # Track last MPR series for reopen
        self.last_mpr_series_index = None
        self.last_mpr_vtk_data = None
        self.last_mpr_dicom_directory = None
        self.last_mpr_window_width = None
        self.last_mpr_window_center = None

        # ✅ Initialize soundbox here
        # Pass the correct parent and methods
        self.__soundbox = VoiceWidget(
            patient_widget=patient_widget,
            method_update_audio_counter=self.update_audio_counter,
            method_check_status_mic_btn=self.turn_on_off_mic_btn
        )
        
        # ✅ تایمر برای به‌روزرسانی موقعیت پنل ضبط هنگام حرکت پنجره
        self._position_update_timer = QTimer()
        self._position_update_timer.setInterval(100)  # هر 100 میلی‌ثانیه
        self._position_update_timer.timeout.connect(self._update_soundbox_position)
        self._mic_button_ref = None  # رفرنس به دکمه میکروفون

        # Target debug (first-run tracing)
        self._target_debug_count = 0

    def _debug_target(self, message: str):
        if self._target_debug_count < 20:
            logging.getLogger(__name__).debug("[TARGET DEBUG] %s", message)
            self._target_debug_count += 1

    def _show_curved_mpr_panel(self):
        """Show Curved MPR control panel"""
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget
            from PySide6.QtCore import Qt
            
            selected_widget = self.patient_widget.selected_widget
            
            if not self.is_vtk_widget(selected_widget):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.patient_widget, "Error", "Please select a valid viewer first.")
                return
            
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.patient_widget, "Error", "No image loaded in viewer.")
                return
            
            # Create panel
            self._curved_mpr_panel = QDialog(self.patient_widget)
            self._curved_mpr_panel.setWindowTitle("Curved MPR")
            self._curved_mpr_panel.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
            self._curved_mpr_panel.setMinimumSize(280, 350)
            self._curved_mpr_panel.setStyleSheet("""
                QDialog {
                    background: #1f2937;
                    border: 2px solid #7c3aed;
                    border-radius: 10px;
                }
                QLabel {
                    color: #f3f4f6;
                    font-size: 13px;
                }
                QListWidget {
                    background: #111827;
                    color: #fbbf24;
                    border: 1px solid #374151;
                    border-radius: 6px;
                    font-size: 12px;
                    font-family: 'Consolas', monospace;
                }
                QPushButton {
                    background: #374151;
                    color: #f3f4f6;
                    border: 1px solid #4b5563;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 13px;
                    font-weight: 500;
                }
                QPushButton:hover {
                    background: #4b5563;
                    border-color: #6b7280;
                }
                QPushButton:checked {
                    background: #7c3aed;
                    border-color: #8b5cf6;
                }
            """)
            
            layout = QVBoxLayout(self._curved_mpr_panel)
            layout.setContentsMargins(15, 15, 15, 15)
            layout.setSpacing(10)
            
            # Header
            header = QLabel("Curved MPR Path Builder")
            header.setStyleSheet("font-size: 16px; font-weight: bold; color: #8b5cf6;")
            layout.addWidget(header)
            
            # Instructions
            instructions = QLabel("1. Click 'Start Adding Points'\n2. Click on image to add points\n3. Click 'Generate' when done")
            instructions.setStyleSheet("color: #9ca3af; font-size: 11px;")
            layout.addWidget(instructions)
            
            # Points list
            points_label = QLabel("Points:")
            layout.addWidget(points_label)
            
            self._points_list = QListWidget()
            self._points_list.setMaximumHeight(150)
            layout.addWidget(self._points_list)
            
            # Point count label
            self._point_count_label = QLabel("Points: 0")
            self._point_count_label.setStyleSheet("color: #fbbf24; font-weight: bold;")
            layout.addWidget(self._point_count_label)
            
            # Buttons
            btn_layout = QHBoxLayout()
            
            # Start/Stop adding points button
            self._add_points_btn = QPushButton("Start Adding Points")
            self._add_points_btn.setCheckable(True)
            self._add_points_btn.setStyleSheet("""
                QPushButton {
                    background: #059669;
                    border-color: #10b981;
                }
                QPushButton:checked {
                    background: #dc2626;
                    border-color: #ef4444;
                }
                QPushButton:hover {
                    background: #047857;
                }
                QPushButton:checked:hover {
                    background: #b91c1c;
                }
            """)
            self._add_points_btn.clicked.connect(self._toggle_point_adding)
            btn_layout.addWidget(self._add_points_btn)
            
            # Clear button
            clear_btn = QPushButton("Clear")
            clear_btn.clicked.connect(self._clear_curved_mpr_points)
            btn_layout.addWidget(clear_btn)
            
            layout.addLayout(btn_layout)
            
            # Generate button
            generate_btn = QPushButton("Generate Curved MPR")
            generate_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #7c3aed, stop:1 #6d28d9);
                    border-color: #8b5cf6;
                    padding: 12px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #8b5cf6, stop:1 #7c3aed);
                }
            """)
            generate_btn.clicked.connect(self._generate_curved_mpr)
            layout.addWidget(generate_btn)
            
            # Close button
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(self._close_curved_mpr_panel)
            layout.addWidget(close_btn)
            
            # Store reference to viewer
            self._curved_mpr_viewer = selected_widget.image_viewer
            
            # Clear any previous points
            self._curved_mpr_viewer.curved_mpr_points = []
            self._curved_mpr_viewer._clear_curved_mpr_visuals()
            
            self._curved_mpr_panel.show()
            
        except Exception as e:
            print(f"[CURVED MPR] Error showing panel: {e}")
            import traceback
            traceback.print_exc()
    
    def _toggle_point_adding(self):
        """Toggle point adding mode"""
        try:
            checked = self._add_points_btn.isChecked()
            
            if checked:
                self._add_points_btn.setText("Stop Adding (Click Here)")
                self._curved_mpr_viewer.enable_curved_mpr_mode(True)
                
                # Add callback to update points list
                self._original_add_point = self._curved_mpr_viewer._add_curved_mpr_point
                def new_add_point(point_3d):
                    self._original_add_point(point_3d)
                    self._update_points_list()
                self._curved_mpr_viewer._add_curved_mpr_point = new_add_point
                
            else:
                self._add_points_btn.setText("Start Adding Points")
                self._curved_mpr_viewer.enable_curved_mpr_mode(False)
                
                # Restore original method
                if hasattr(self, '_original_add_point'):
                    self._curved_mpr_viewer._add_curved_mpr_point = self._original_add_point
                    
        except Exception as e:
            print(f"[CURVED MPR] Toggle error: {e}")
    
    def _update_points_list(self):
        """Update points list in panel"""
        try:
            self._points_list.clear()
            for i, pt in enumerate(self._curved_mpr_viewer.curved_mpr_points):
                self._points_list.addItem(f"Point {i+1}: ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
            self._point_count_label.setText(f"Points: {len(self._curved_mpr_viewer.curved_mpr_points)}")
        except Exception as e:
            print(f"[CURVED MPR] Update list error: {e}")
    
    def _clear_curved_mpr_points(self):
        """Clear all curved MPR points"""
        try:
            self._curved_mpr_viewer.curved_mpr_points = []
            self._curved_mpr_viewer._clear_curved_mpr_visuals()
            self._update_points_list()
        except Exception as e:
            print(f"[CURVED MPR] Clear error: {e}")
    
    def _generate_curved_mpr(self):
        """Generate curved MPR from collected points"""
        try:
            points = self._curved_mpr_viewer.get_curved_mpr_points()
            
            if len(points) < 2:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self._curved_mpr_panel,
                    "Not Enough Points",
                    f"Need at least 2 points. You have {len(points)} points."
                )
                return
            
            # Disable point adding
            if self._add_points_btn.isChecked():
                self._add_points_btn.setChecked(False)
                self._toggle_point_adding()
            
            # Generate
            self._generate_curved_mpr_from_points(points, self._curved_mpr_viewer.vtk_image_data)
            
        except Exception as e:
            print(f"[CURVED MPR] Generate error: {e}")
            import traceback
            traceback.print_exc()
    
    def _close_curved_mpr_panel(self):
        """Close curved MPR panel"""
        try:
            # Disable point adding mode
            if hasattr(self, '_curved_mpr_viewer'):
                self._curved_mpr_viewer.enable_curved_mpr_mode(False)
            
            # Close panel
            if hasattr(self, '_curved_mpr_panel'):
                self._curved_mpr_panel.close()
                self._curved_mpr_panel = None
                
        except Exception as e:
            print(f"[CURVED MPR] Close error: {e}")
    
    def _show_orthogonal_mpr_viewer(self):
        """Show the new Orthogonal MPR Viewer with three synchronized views"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox
        from PySide6.QtCore import Qt
        import logging
        
        logger = logging.getLogger(__name__)
        logger.info("Opening Orthogonal MPR Viewer...")
        
        try:
            selected_widget = self.patient_widget.selected_widget
            
            # Check if we have a valid widget with image data
            if not self.is_vtk_widget(selected_widget):
                QMessageBox.warning(
                    self.patient_widget, 
                    "Error", 
                    "Please select a valid viewer first."
                )
                return
            
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                QMessageBox.warning(
                    self.patient_widget, 
                    "Error", 
                    "No image loaded in viewer. Please load a DICOM series first."
                )
                return
            
            # Try to get VTK image data
            vtk_image_data = None
            if hasattr(selected_widget, 'vtk_image_data') and selected_widget.vtk_image_data is not None:
                vtk_image_data = selected_widget.vtk_image_data
            elif hasattr(selected_widget.image_viewer, 'GetInput'):
                vtk_image_data = selected_widget.image_viewer.GetInput()
            
            if vtk_image_data is None:
                QMessageBox.warning(
                    self.patient_widget, 
                    "Error", 
                    "Could not get image data from viewer."
                )
                return
            
            # Import the Orthogonal MPR Widget
            from PacsClient.pacs.patient_tab.orthogonal_mpr import OrthogonalMPRWidget
            
            # Create dialog to host the MPR viewer
            dialog = QDialog(self.patient_widget)
            dialog.setWindowTitle("Orthogonal MPR Viewer - Axial / Sagittal / Coronal")
            dialog.setWindowFlags(Qt.Window)
            dialog.resize(1400, 600)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #0d0d0d;
                }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(0, 0, 0, 0)
            
            # Create and add the MPR widget
            mpr_widget = OrthogonalMPRWidget()
            layout.addWidget(mpr_widget)
            
            # Load the VTK image data
            if mpr_widget.load_vtk_image(vtk_image_data):
                logger.info("Orthogonal MPR Viewer loaded successfully")
                
                # Apply default window/level if available
                if hasattr(selected_widget, 'window_width') and hasattr(selected_widget, 'window_center'):
                    mpr_widget.set_window_level(
                        selected_widget.window_width,
                        selected_widget.window_center
                    )
                
                dialog.show()
            else:
                QMessageBox.warning(
                    self.patient_widget, 
                    "Error", 
                    "Failed to load image into MPR viewer."
                )
                dialog.close()
                
        except ImportError as e:
            logger.error(f"Failed to import OrthogonalMPRWidget: {e}")
            QMessageBox.critical(
                self.patient_widget, 
                "Import Error", 
                f"Failed to import Orthogonal MPR module:\n{e}"
            )
        except Exception as e:
            logger.error(f"Error showing Orthogonal MPR Viewer: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.patient_widget, 
                "Error", 
                f"Error opening Orthogonal MPR Viewer:\n{e}"
            )
    
    def _generate_curved_mpr_from_points(self, points, image_data):
        """Generate curved MPR from points and display it"""
        from PySide6.QtWidgets import QMessageBox, QApplication
        from PySide6.QtCore import Qt
        # Import from zeta mpr (primary MPR implementation)
        import sys
        import os
        import importlib.util
        
        # Get path to zeta mpr directory
        patient_tab_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        zeta_mpr_dir = os.path.join(patient_tab_dir, "zeta mpr")
        curved_mpr_path = os.path.join(zeta_mpr_dir, "curved_mpr.py")
        
        # Import CurvedMPRGenerator from zeta mpr
        spec = importlib.util.spec_from_file_location("zeta_curved_mpr", curved_mpr_path)
        zeta_curved_mpr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(zeta_curved_mpr)
        CurvedMPRGenerator = zeta_curved_mpr.CurvedMPRGenerator
        
        print(f"[CURVED MPR] Starting generation with {len(points)} points...")
        
        # Change cursor to wait
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        
        try:
            generator = CurvedMPRGenerator(image_data)
            generator.set_centerline(points)
            
            # Use reasonable values for speed
            slice_size = 150.0
            num_slices = min(len(points) * 15, 60)
            
            print(f"[CURVED MPR] Generating {num_slices} slices...")
            QApplication.processEvents()
            
            curved_image = generator.generate_curved_mpr(
                slice_width=slice_size,
                slice_height=slice_size,
                num_slices=num_slices
            )
            
            QApplication.restoreOverrideCursor()
            
            if curved_image:
                dims = curved_image.GetDimensions()
                print(f"[CURVED MPR] Generated! Dims: {dims}")
                # Pass the generator so we can create true panoramic view
                self._show_curved_mpr_result(curved_image, len(points), generator=generator)
            else:
                QMessageBox.warning(
                    self.patient_widget,
                    "Generation Failed",
                    "Failed to generate Curved MPR."
                )
                
        except Exception as e:
            QApplication.restoreOverrideCursor()
            print(f"[CURVED MPR] Generation error: {e}")
            import traceback
            traceback.print_exc()
            
            QMessageBox.critical(
                self.patient_widget,
                "Error",
                f"Failed to generate Curved MPR:\n{str(e)}"
            )
    
    def _show_curved_mpr_result(self, curved_image, num_points, generator=None):
        """Show curved MPR result in main viewer grid"""
        try:
            from PacsClient.pacs.patient_tab.curved_mpr_panoramic_view import CurvedMPRPanoramicView
            from PySide6.QtWidgets import QApplication
            
            dims = curved_image.GetDimensions()
            scalar_range = curved_image.GetScalarRange()
            
            print(f"[CURVED MPR] Showing result: dims={dims}, scalar_range={scalar_range}")
            
            # Generate TRUE panoramic view if generator is provided
            panoramic_image = None
            if generator is not None:
                try:
                    print("[PANORAMIC] Generating true panoramic view...")
                    QApplication.processEvents()
                    
                    panoramic_image = generator.generate_panoramic_view(
                        slice_thickness_mm=10.0,  # Radial thickness: 10mm
                        slice_height_mm=80.0,     # Vertical extent: 80mm (reduced for wider panoramic)
                        num_positions=None,       # Auto-determine based on path length
                        projection_type='mean'    # Mean intensity projection
                    )
                    
                    if panoramic_image is not None:
                        pano_dims = panoramic_image.GetDimensions()
                        pano_range = panoramic_image.GetScalarRange()
                        print(f"[PANORAMIC] ✓ Generated: {pano_dims}, range: {pano_range}")
                    
                except Exception as e:
                    print(f"[PANORAMIC] ERROR generating panoramic: {e}")
                    import traceback
                    traceback.print_exc()
                    panoramic_image = None
            
            # Create the viewer widget
            viewer_widget = CurvedMPRPanoramicView(
                curved_image, 
                num_points, 
                panoramic_image=panoramic_image,
                parent=self.patient_widget
            )
            
            # Add to patient widget's viewer grid (replace current layout with 1x1)
            # First, cleanup existing viewers
            self.patient_widget.cleanup_all_viewers()
            self.patient_widget.lst_nodes_viewer.clear()
            
            # Add the curved MPR viewer to the grid
            self.patient_widget.vtk_layout.addWidget(viewer_widget, 0, 0)
            
            # Store reference using NodeViewer (correct import)
            from PacsClient.pacs.patient_tab.utils import NodeViewer
            
            # Create a dummy NodeViewer wrapper
            node_viewer = NodeViewer(
                main_widget=viewer_widget,
                vtk_widget=viewer_widget.active_viewport,  # The active viewport acts as vtk_widget
                slider=None  # No slider for curved MPR
            )
            self.patient_widget.lst_nodes_viewer.append(node_viewer)
            
            # Set active viewport as selected widget for toolbar
            self.patient_widget.selected_widget = viewer_widget.active_viewport
            
            print("[CURVED MPR] Viewer added to main grid successfully")
            print(f"[CURVED MPR] Active viewport set to: {type(viewer_widget.active_viewport).__name__}")
            
        except Exception as e:
            print(f"[CURVED MPR] ERROR showing result: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback to old simple view
            self._show_curved_mpr_result_simple(curved_image, num_points)
    
    def _show_curved_mpr_result_simple(self, curved_image, num_points):
        """Fallback: Show curved MPR result using simple single-panel view"""
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, QFrame
            from PySide6.QtCore import Qt
            import vtkmodules.all as vtk
            from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
            
            dims = curved_image.GetDimensions()
            scalar_range = curved_image.GetScalarRange()
            
            print(f"[CURVED MPR] Showing result (simple mode): dims={dims}, scalar_range={scalar_range}")
            
            # Create dialog
            dialog = QDialog(self.patient_widget)
            dialog.setWindowTitle(f"Curved MPR - {num_points} points")
            dialog.setMinimumSize(600, 550)
            dialog.setStyleSheet("""
                QDialog { background: #1a1a1a; }
                QLabel { color: #f3f4f6; font-size: 13px; }
                QPushButton { background: #374151; color: #f3f4f6; border: 1px solid #4b5563; border-radius: 6px; padding: 8px 16px; }
                QPushButton:hover { background: #4b5563; }
                QSlider::groove:horizontal { background: #374151; height: 8px; border-radius: 4px; }
                QSlider::handle:horizontal { background: #8b5cf6; width: 18px; margin: -5px 0; border-radius: 9px; }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)
            
            # Header
            header = QLabel(f"Curved MPR - {dims[0]}x{dims[1]} | {dims[2]} slices")
            header.setStyleSheet("font-size: 14px; font-weight: bold; color: #8b5cf6;")
            layout.addWidget(header)
            
            # VTK Widget container
            container = QFrame()
            container.setFrameStyle(QFrame.Box | QFrame.Plain)
            container.setLineWidth(2)
            container.setStyleSheet("QFrame { border: 2px solid #4b5563; background: #000000; }")
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            
            # Create VTK widget
            vtk_widget = QVTKRenderWindowInteractor(container)
            container_layout.addWidget(vtk_widget)
            layout.addWidget(container)
            
            # Use vtkImageViewer2 - simple and stable
            viewer = vtk.vtkImageViewer2()
            viewer.SetInputData(curved_image)
            viewer.SetRenderWindow(vtk_widget.GetRenderWindow())
            viewer.SetupInteractor(vtk_widget.GetRenderWindow().GetInteractor())
            
            # Set window/level - UNIVERSAL approach for all modalities
            print(f"[CPR Display] Scalar range: [{scalar_range[0]:.1f}, {scalar_range[1]:.1f}]")
            
            # Check if image is empty
            if scalar_range[0] == 0 and scalar_range[1] == 0:
                print("[CPR Display] WARNING: Image is completely black (all zeros)!")
                print("[CPR Display] This usually means points are outside the volume")
                window, level = 1, 0  # Fallback values
            else:
                # UNIVERSAL: Always use full scalar range
                # Works for: CT, CBCT, MR, PET, all body parts
                window = max(scalar_range[1] - scalar_range[0], 1)
                level = (scalar_range[1] + scalar_range[0]) / 2
                print(f"[CPR Display] Auto window/level: W={window:.0f} L={level:.0f}")
            
            viewer.SetColorWindow(window)
            viewer.SetColorLevel(level)
            
            # PANORAMIC VIEW: Show straightened image along the curve
            # Instead of showing slice-by-slice, show the entire unfolded view
            
            # Create a Maximum Intensity Projection (MIP) or straightened view
            # by extracting a 2D panoramic slice from the 3D volume
            
            # For panoramic view, we want to see the YZ plane (slice along X axis)
            # This shows the "unfolded" or "straightened" path
            viewer.SetSliceOrientationToYZ()  # Show YZ plane (panoramic)
            viewer.SetSlice(dims[0] // 2)  # Middle of the straightened volume
            
            # Rotate display 90 degrees clockwise for proper orientation
            renderer = viewer.GetRenderer()
            camera = renderer.GetActiveCamera()
            camera.Roll(-90)  # Clockwise rotation
            renderer.ResetCameraClippingRange()
            
            # Setup interactive style for window/level adjustment
            # User can adjust W/L by dragging with mouse
            interactor = vtk_widget.GetRenderWindow().GetInteractor()
            style = vtk.vtkInteractorStyleImage()
            interactor.SetInteractorStyle(style)
            
            # Calculate middle slice
            mid_slice = dims[2] // 2
            
            # Slice info
            slice_label = QLabel(f"Slice: {mid_slice + 1} / {dims[2]} | W/L: {int(window)}/{int(level)}")
            slice_label.setStyleSheet("font-weight: bold;")
            layout.addWidget(slice_label)
            
            # Instruction label
            info_label = QLabel("💡 Tip: Right-click + drag to adjust Window/Level")
            info_label.setStyleSheet("color: #6b7280; font-size: 11px; font-style: italic;")
            layout.addWidget(info_label)
            
            # Slider for slice navigation
            slider = QSlider(Qt.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(dims[2] - 1)
            slider.setValue(mid_slice)
            
            def on_slider_change(value):
                viewer.SetSlice(value)
                viewer.Render()
                slice_label.setText(f"Slice: {value + 1} / {dims[2]} | W/L: {int(window)}/{int(level)}")
            
            slider.valueChanged.connect(on_slider_change)
            layout.addWidget(slider)
            
            # Buttons
            btn_layout = QHBoxLayout()
            
            prev_btn = QPushButton("< Prev")
            next_btn = QPushButton("Next >")
            close_btn = QPushButton("Close")
            close_btn.setStyleSheet("background: #dc2626; border-color: #ef4444;")
            
            def update_slice(delta):
                new_val = slider.value() + delta
                if 0 <= new_val < dims[2]:
                    slider.setValue(new_val)
            
            prev_btn.clicked.connect(lambda: update_slice(-1))
            next_btn.clicked.connect(lambda: update_slice(1))
            close_btn.clicked.connect(dialog.close)
            
            btn_layout.addWidget(prev_btn)
            btn_layout.addWidget(next_btn)
            btn_layout.addStretch()
            btn_layout.addWidget(close_btn)
            layout.addLayout(btn_layout)
            
            # Initialize
            vtk_widget.Initialize()
            viewer.Render()
            vtk_widget.Start()
            
            # Store viewer reference
            dialog._viewer = viewer
            dialog._vtk_widget = vtk_widget
            
            dialog.show()
            print(f"[CURVED MPR] Viewer opened successfully")
            
        except Exception as e:
            print(f"[CURVED MPR] Error showing result: {e}")
            import traceback
            traceback.print_exc()
    
    def is_vtk_widget(self, widget):
        """Check if widget is a VTKWidget (not MPR or other custom widgets)"""
        from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget
        from PacsClient.pacs.patient_tab.curved_mpr_panoramic_view import CurvedMPRViewport
        
        # Accept VTKWidget or CurvedMPRViewport
        return isinstance(widget, (VTKWidget, CurvedMPRViewport))

    def is_mpr_viewer(self, widget):
        """Check if widget is an MPR viewer"""
        # OLD MprViewerWrapper check removed - deprecated and unused
        # The old MprViewer module has been removed in favor of Zeta MPR
        
        # Check for Zeta MPR viewer
        # Note: Zeta MPR now uses _zeta_mpr_widget attribute, not _mpr_widget
        if hasattr(widget, '_zeta_mpr_widget') and widget._zeta_mpr_widget is not None:
            return True
        if hasattr(widget, '_new_mpr_zeta_widget') and widget._new_mpr_zeta_widget is not None:
            return True
        if hasattr(widget, '_original_widget'):
            return True
        # If the selected widget itself is the MPR widget
        if hasattr(widget, 'activate_toolbar_tool') and hasattr(widget, 'viewers'):
            return True
        
        return False
    
    def get_mpr_widget(self, widget):
        """Get the MPR widget from a VTKWidget that has MPR active"""
        if hasattr(widget, '_zeta_mpr_widget') and widget._zeta_mpr_widget is not None:
            return widget._zeta_mpr_widget
        if hasattr(widget, '_new_mpr_zeta_widget') and widget._new_mpr_zeta_widget is not None:
            return widget._new_mpr_zeta_widget
        if hasattr(widget, '_mpr_widget') and widget._mpr_widget is not None:
            return widget._mpr_widget
        if hasattr(widget, '_original_widget'):
            return widget
        return None

    def can_use_tool(self, widget):
        """Check if tool can be used on this widget"""
        # Check if it's an MPR viewer
        if self.is_mpr_viewer(widget):
            # MPR mode - measurement tools are NOW ALLOWED with VTK widgets!
            # No need to check Crosshairs status anymore
            logger = __import__('logging').getLogger(__name__)
            logger.info("✓ Measurement tools allowed in MPR (using VTK widgets)")
            return True

        # Normal VTKWidget check
        if not self.is_vtk_widget(widget):
            # Not MPR and not VTKWidget - not supported
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Tool Not Available")
            msg.setText("Measurement tools are not available on this widget")
            msg.setInformativeText(
                f"Current widget type: {type(widget).__name__}\n\n"
                "Measurement tools work on:\n"
                "  • Standard 2D viewers (VTKWidget)\n"
                "  • Zeta MPR viewers"
            )
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec()
            print(f"⚠️ Cannot use tool on {type(widget).__name__}")
            return False

        if not hasattr(widget, 'image_viewer') or widget.image_viewer is None:
            print(f"⚠️ Cannot use tool - image_viewer not initialized yet")
            return False
        return True

    def toggle_reset_all_widget(self):
        """this method run for once. we don't need to hold active """

        self.check_and_deactivate_tools()

        for node in self.patient_widget.lst_nodes_viewer:
            node: NodeViewer
            selected_widget = node.vtk_widget

            last_series_showed_on_viewer = node.vtk_widget.last_series_show

            vtk_image_data = self.patient_widget.lst_thumbnails_data[last_series_showed_on_viewer]['vtk_image_data']
            metadata = self.patient_widget.lst_thumbnails_data[last_series_showed_on_viewer]['metadata']

            node.vtk_widget.reset_image(vtk_image_data, metadata)
            ###############################################################
            # self.toggle_reset_selected_widget(node.vtk_widget)
            ###############################################################

            # this is the last series showed on selected widget
            series_index = selected_widget.last_series_show

            vtk_image_data = self.patient_widget.lst_thumbnails_data[series_index]['vtk_image_data']
            metadata = self.patient_widget.lst_thumbnails_data[series_index]['metadata']
            selected_widget.reset_image(vtk_image_data, metadata)

            selected_widget.set_new_interactorstyle(EraserInteractorStyle)
            selected_widget.current_style.delete_all_widgets()

            selected_widget.restore_default_interactorstyle()

        self.tool_selected = None
        self.handle_buttons_checked()

    def toggle_reset_selected_widget(self, selected_widget):
        print('reset!!')
        last_series_show=None
        """this method run for once. we don't need to hold active """
        # MPR mode reset
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if not mpr_widget:
                return

            if self.tool_selected == self.tool_access.RESET:
                self.tool_selected = None
                self.handle_buttons_checked()
                return

            if self.tool_selected != self.tool_access.MPR:
                self.check_and_deactivate_tools()

            try:
                mpr_widget.reset_to_initial_state()
            except Exception as e:
                print(f"[MPR] Reset failed: {e}")

            self.tool_selected = self.tool_access.RESET
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()
            return
        if self.tool_selected == self.tool_access.RESET:  # deactivate tool
            self.tool_selected = None

            # Restore default interactor style
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            print('reset selected:', selected_widget)
            self.check_and_deactivate_tools()

            vtk_image_data = None
            metadata = None

            current_slice = None
            if hasattr(selected_widget, 'image_viewer') and selected_widget.image_viewer is not None:
                try:
                    current_slice = selected_widget.image_viewer.GetSlice()
                except Exception:
                    current_slice = None

            series_uid = None
            series_number = None
            try:
                if hasattr(selected_widget, 'image_viewer') and selected_widget.image_viewer is not None:
                    series_meta = selected_widget.image_viewer.metadata.get('series', {})
                    series_uid = series_meta.get('series_uid')
                    series_number = series_meta.get('series_number')
            except Exception:
                series_uid = None

            print('len(self.patient_widget.lst_thumbnails_data):', len(self.patient_widget.lst_thumbnails_data))

            for i in range(len(self.patient_widget.lst_thumbnails_data)):
                try:
                    series_meta = self.patient_widget.lst_thumbnails_data[i]['metadata']['series']
                    if series_uid is not None and series_meta.get('series_uid') == series_uid:
                        vtk_image_data = self.patient_widget.lst_thumbnails_data[i]['vtk_image_data']
                        metadata = self.patient_widget.lst_thumbnails_data[i]['metadata']
                        break
                except Exception:
                    pass

            if vtk_image_data is None and series_number is not None:
                for i in range(len(self.patient_widget.lst_thumbnails_data)):
                    try:
                        if str(self.patient_widget.lst_thumbnails_data[i]['metadata']['series']['series_number']) == str(series_number):
                            vtk_image_data = self.patient_widget.lst_thumbnails_data[i]['vtk_image_data']
                            metadata = self.patient_widget.lst_thumbnails_data[i]['metadata']
                            break
                    except Exception:
                        pass

            print('vtkimagedata:', vtk_image_data)
            print('\nmetadata:', metadata)

            if (vtk_image_data is None) or (metadata is None):
                self.check_and_deactivate_tools()
                return

            selected_widget.reset_image(vtk_image_data, metadata)
            if current_slice is not None:
                try:
                    selected_widget.set_slice(current_slice)
                except Exception:
                    pass

            # create an eraser instance for delete widgets from image viewer
            selected_widget.set_new_interactorstyle(EraserInteractorStyle)
            selected_widget.current_style.delete_all_widgets()

            self.tool_selected = self.tool_access.RESET
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_ruler(self, selected_widget):
        """Toggle ruler tool on/off for the selected viewer"""
        import logging
        import sys
        logger = logging.getLogger(__name__)
        
        print("="*80, file=sys.stderr, flush=True)
        print("🔨 [RULER] toggle_ruler called", file=sys.stderr, flush=True)
        print(f"   selected_widget: {selected_widget}", file=sys.stderr, flush=True)
        print(f"   selected_widget type: {type(selected_widget)}", file=sys.stderr, flush=True)
        print(f"   tool_selected: {self.tool_selected}", file=sys.stderr, flush=True)
        
        logger.info("="*80)
        logger.info("🔨 [RULER] toggle_ruler called")
        logger.info(f"   selected_widget: {selected_widget}")
        logger.info(f"   selected_widget type: {type(selected_widget)}")
        logger.info(f"   tool_selected: {self.tool_selected}")
        
        # Log all attributes of selected_widget
        if selected_widget:
            print(f"   📋 [RULER] selected_widget attributes:", file=sys.stderr, flush=True)
            print(f"      has image_viewer: {hasattr(selected_widget, 'image_viewer')}", file=sys.stderr, flush=True)
            if hasattr(selected_widget, 'image_viewer'):
                print(f"      image_viewer value: {selected_widget.image_viewer}", file=sys.stderr, flush=True)
            print(f"      has current_style: {hasattr(selected_widget, 'current_style')}", file=sys.stderr, flush=True)
            print(f"      has vtk_image_data: {hasattr(selected_widget, 'vtk_image_data')}", file=sys.stderr, flush=True)
            print(f"      selected_widget class name: {selected_widget.__class__.__name__}", file=sys.stderr, flush=True)
            
            # Check what type it actually is
            from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget
            from PacsClient.pacs.patient_tab.curved_mpr_panoramic_view import CurvedMPRViewport
            print(f"      isinstance(VTKWidget): {isinstance(selected_widget, VTKWidget)}", file=sys.stderr, flush=True)
            try:
                print(f"      isinstance(CurvedMPRViewport): {isinstance(selected_widget, CurvedMPRViewport)}", file=sys.stderr, flush=True)
            except:
                print(f"      isinstance(CurvedMPRViewport): Error importing", file=sys.stderr, flush=True)
        
        # Check if we're in MPR mode
        is_mpr = self.is_mpr_viewer(selected_widget)
        print(f"   is_mpr_viewer: {is_mpr}", file=sys.stderr, flush=True)
        logger.info(f"   is_mpr_viewer: {is_mpr}")
        
        if is_mpr:
            print("   🔄 [RULER] In MPR mode", file=sys.stderr, flush=True)
            logger.info("   🔄 [RULER] In MPR mode")
            mpr_widget = self.get_mpr_widget(selected_widget)
            print(f"   mpr_widget: {mpr_widget}", file=sys.stderr, flush=True)
            logger.info(f"   mpr_widget: {mpr_widget}")
            
            if mpr_widget:
                # Check tool state
                is_ruler_active = self.tool_selected and self.tool_access.RULER in str(self.tool_selected)
                logger.info(f"   is_ruler_active: {is_ruler_active}")
                
                if is_ruler_active:
                    # Deactivate ruler
                    logger.info("   ❌ [RULER] Deactivating ruler in MPR")
                    mpr_widget.deactivate_tool()
                    self.tool_selected = self.tool_access.MPR
                    logger.info("   ✓ Ruler tool deactivated in MPR")
                else:
                    # Activate ruler
                    logger.info("   ✅ [RULER] Activating ruler in MPR")
                    if self.tool_selected != self.tool_access.MPR:
                        logger.info("   🔧 [RULER] Deactivating other tools first")
                        self.check_and_deactivate_tools()
                    mpr_widget.activate_ruler()
                    self.tool_selected = f'{self.tool_access.MPR},{self.tool_access.RULER}'
                    logger.info("   ✓ Ruler tool activated in MPR on all 2D views")
                self.handle_buttons_checked()
                logger.info("="*80)
            else:
                logger.warning("   ⚠️ [RULER] MPR mode detected but no mpr_widget found!")
                logger.info("="*80)
            return

        # Normal VTKWidget mode - original code
        print("   🔄 [RULER] In normal VTKWidget mode", file=sys.stderr, flush=True)
        logger.info("   🔄 [RULER] In normal VTKWidget mode")
        is_vtk = self.is_vtk_widget(selected_widget)
        print(f"   is_vtk_widget: {is_vtk}", file=sys.stderr, flush=True)
        logger.info(f"   is_vtk_widget: {is_vtk}")
        
        if not is_vtk:
            print("   ⚠️ [RULER] Not a VTK widget, exiting", file=sys.stderr, flush=True)
            print("="*80, file=sys.stderr, flush=True)
            logger.warning("   ⚠️ [RULER] Not a VTK widget, exiting")
            logger.info("="*80)
            return

        if self.tool_selected == self.tool_access.RULER:  # deactivate tool
            print("   ❌ [RULER] Deactivating ruler", file=sys.stderr, flush=True)
            logger.info("   ❌ [RULER] Deactivating ruler")
            # Deactivate ruler
            if hasattr(selected_widget, 'current_style'):
                logger.info("   🔧 [RULER] Deactivating current_style")
                selected_widget.current_style.deactivate()
            else:
                logger.warning("   ⚠️ [RULER] selected_widget has no 'current_style' attribute")
            
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()
            print("   ✓ [RULER] Ruler deactivated", file=sys.stderr, flush=True)
            print("="*80, file=sys.stderr, flush=True)
            logger.info("   ✓ [RULER] Ruler deactivated")

        else:  # activate tool
            print("   ✅ [RULER] Activating ruler", file=sys.stderr, flush=True)
            print("   🔧 [RULER] Checking and deactivating other tools", file=sys.stderr, flush=True)
            logger.info("   ✅ [RULER] Activating ruler")
            logger.info("   🔧 [RULER] Checking and deactivating other tools")
            self.check_and_deactivate_tools()

            print("   🔧 [RULER] Setting new RulerInteractorStyle", file=sys.stderr, flush=True)
            logger.info("   🔧 [RULER] Setting new RulerInteractorStyle")
            selected_widget.set_new_interactorstyle(RulerInteractorStyle)

            # Activate ruler
            if hasattr(selected_widget, 'current_style'):
                print("   🔧 [RULER] Activating current_style", file=sys.stderr, flush=True)
                logger.info("   🔧 [RULER] Activating current_style")
                selected_widget.current_style.activate()
            else:
                print("   ⚠️ [RULER] selected_widget has no 'current_style' attribute after set_new_interactorstyle", file=sys.stderr, flush=True)
                logger.warning("   ⚠️ [RULER] selected_widget has no 'current_style' attribute after set_new_interactorstyle")
            
            self.tool_selected = self.tool_access.RULER
            self.handle_buttons_checked()
            print("   ✓ [RULER] Ruler activated", file=sys.stderr, flush=True)
            print("="*80, file=sys.stderr, flush=True)
            logger.info("   ✓ [RULER] Ruler activated")
        
        logger.info("="*80)

    def toggle_eraser(self, selected_widget):
        # MPR mode
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if not mpr_widget:
                return
            if self.tool_selected == self.tool_access.ERASER:  # deactivate tool
                mpr_widget.deactivate_toolbar_tool()
                self.tool_selected = None
            else:
                if self.tool_selected != self.tool_access.MPR:
                    self.check_and_deactivate_tools()
                try:
                    mpr_widget.deactivate_tool()
                except Exception:
                    pass
                mpr_widget.activate_toolbar_tool(self.tool_access.ERASER)
                self.tool_selected = self.tool_access.ERASER
            self.handle_buttons_checked()
            return

        # NO can_use_tool check - let it work
        if not self.is_vtk_widget(selected_widget):
            return

        if self.tool_selected == self.tool_access.ERASER:  # deactivate tool

            self.tool_selected = None
            # Restore default interactor style
            selected_widget.restore_default_interactorstyle()

        else:
            self.check_and_deactivate_tools()

            # Create new eraser style and set it as the current interactor style
            selected_widget.set_new_interactorstyle(EraserInteractorStyle)
            self.tool_selected = self.tool_access.ERASER
            self.handle_buttons_checked()

    def toggle_angle(self, selected_widget):
        """Toggle angle tool on/off for the selected viewer"""
        # Check if we're in MPR mode
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget:
                # Check tool state
                is_angle_active = self.tool_selected and self.tool_access.ANGLE in str(self.tool_selected)
                
                if is_angle_active:
                    # Deactivate angle
                    mpr_widget.deactivate_tool()
                    self.tool_selected = self.tool_access.MPR
                    print("✓ Angle tool deactivated in MPR")
                else:
                    # Activate angle
                    if self.tool_selected != self.tool_access.MPR:
                        self.check_and_deactivate_tools()
                    mpr_widget.activate_angle()
                    self.tool_selected = f'{self.tool_access.MPR},{self.tool_access.ANGLE}'
                    print("✓ Angle tool activated in MPR on all 2D views")
                self.handle_buttons_checked()
            return

        # Normal VTKWidget mode - NO can_use_tool check
        if not self.is_vtk_widget(selected_widget):
            return

        if self.tool_selected == self.tool_access.ANGLE:  # deactivate tool
            selected_widget.current_style.deactivate()
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()

            # Create new angle style and set it as the current interactor style
            selected_widget.set_new_interactorstyle(AngleInteractorStyle)

            selected_widget.current_style.activate()
            self.tool_selected = self.tool_access.ANGLE
            self.handle_buttons_checked()

    def toggle_two_line_angle(self, selected_widget):
        """Toggle two-line angle tool on/off for the selected viewer"""
        print(f"🔧 toggle_two_line_angle called")
        print(f"  selected_widget: {selected_widget}")
        print(f"  is_vtk_widget: {self.is_vtk_widget(selected_widget)}")
        print(f"  current tool_selected: {self.tool_selected}")
        
        # Normal VTKWidget mode
        if not self.is_vtk_widget(selected_widget):
            print("  ❌ Not VTK widget, returning")
            return

        if self.tool_selected == self.tool_access.TWO_LINE_ANGLE:  # deactivate tool
            print("  ⏹️ Deactivating two-line angle")
            selected_widget.current_style.deactivate()
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            print("  ▶️ Activating two-line angle")
            self.check_and_deactivate_tools()
            print("  ✓ Deactivated previous tools")

            # Create new two-line angle style and set it as the current interactor style
            selected_widget.set_new_interactorstyle(TwoLineAngleInteractorStyle)
            print("  ✓ Created new interactor style")

            selected_widget.current_style.activate()
            print("  ✓ Activated interactor style")
            
            self.tool_selected = self.tool_access.TWO_LINE_ANGLE
            print(f"  ✓ Set tool_selected to: {self.tool_selected}")
            
            self.handle_buttons_checked()
            print("  ✓ Two-Line Angle tool activated successfully!")

    def toggle_arrow(self, selected_widget):
        """Toggle arrow tool on/off for the selected viewer"""
        # Check if we're in MPR mode
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget:
                # MPR mode - use MPR measurement tools (caption)
                is_arrow_active = self.tool_selected and self.tool_access.ARROW in str(self.tool_selected)
                if is_arrow_active:
                    # Deactivate
                    self.tool_selected = self.tool_access.MPR
                    mpr_widget.deactivate_tool()
                else:
                    # Activate on ALL 2D viewports (axial, sagittal, coronal)
                    if self.tool_selected != self.tool_access.MPR:
                        self.check_and_deactivate_tools()
                    success = mpr_widget.activate_caption()
                    if success:
                        self.tool_selected = f'{self.tool_access.MPR},{self.tool_access.ARROW}'
                        print("✓ Arrow tool activated in MPR on all 2D views")
            return

        # Normal VTKWidget mode - NO can_use_tool check
        if not self.is_vtk_widget(selected_widget):
            return

        if self.tool_selected == self.tool_access.ARROW:  # deactivate tool
            selected_widget.current_style.deactivate()
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()

            # Create new arrow style and set it as the current interactor style
            selected_widget.set_new_interactorstyle(ArrowInteractorStyle)

            selected_widget.current_style.activate()
            self.tool_selected = self.tool_access.ARROW
            self.handle_buttons_checked()

    def toggle_text(self, selected_widget):
        # Check if tool can be used on this widget
        if not self.can_use_tool(selected_widget):
            return

        if self.tool_selected == self.tool_access.TEXT:  # deactivate tool
            selected_widget.current_style.deactivate()
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()

            # Create new arrow style and set it as the current interactor style
            selected_widget.set_new_interactorstyle(TextInteractorStyle)

            selected_widget.current_style.activate()
            self.tool_selected = self.tool_access.TEXT
            self.handle_buttons_checked()

    def toggle_zoom_to_fit(self, selected_widget):
        """this method run for once. we don't need to hold active """
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget:
                if self.tool_selected == self.tool_access.ZOOM_TO_FIT:
                    self.tool_selected = None
                    mpr_widget.deactivate_toolbar_tool()
                    self.handle_buttons_checked()
                    return

                if self.tool_selected != self.tool_access.MPR:
                    self.check_and_deactivate_tools()

                mpr_widget.zoom_to_fit()
                self.tool_selected = self.tool_access.ZOOM_TO_FIT
                self.handle_buttons_checked()
                self.check_and_deactivate_tools()
            return

        if self.tool_selected == self.tool_access.ZOOM_TO_FIT:
            self.tool_selected = None

            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:

            self.check_and_deactivate_tools()

            selected_widget.set_new_interactorstyle(DefaultInteractionInteractorStyle)
            selected_widget.current_style.zoom_to_fit()

            self.tool_selected = self.tool_access.ZOOM_TO_FIT
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_zoom(self, selected_widget):
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget:
                if self.tool_selected == self.tool_access.ZOOM:  # deactivate tool
                    mpr_widget.deactivate_toolbar_tool()
                    self.tool_selected = None
                else:
                    if self.tool_selected != self.tool_access.MPR:
                        self.check_and_deactivate_tools()
                    mpr_widget.activate_toolbar_tool(self.tool_access.ZOOM)
                    self.tool_selected = self.tool_access.ZOOM
                self.handle_buttons_checked()
            return

        if self.tool_selected == self.tool_access.ZOOM:  # deactivate tool
            selected_widget.current_style.deactivate(self.tool_selected)
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(DefaultInteractionInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.ZOOM)

            self.tool_selected = self.tool_access.ZOOM
            self.handle_buttons_checked()

    def toggle_window_level(self, selected_widget):
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget:
                if self.tool_selected == self.tool_access.WINDOW_LEVEL:
                    mpr_widget.deactivate_toolbar_tool()
                    self.tool_selected = None
                else:
                    if self.tool_selected != self.tool_access.MPR:
                        self.check_and_deactivate_tools()
                    mpr_widget.activate_toolbar_tool(self.tool_access.WINDOW_LEVEL)
                    self.tool_selected = self.tool_access.WINDOW_LEVEL
                self.handle_buttons_checked()
            return

        if self.tool_selected == self.tool_access.WINDOW_LEVEL:
            selected_widget.current_style.deactivate(self.tool_selected)
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(DefaultInteractionInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.WINDOW_LEVEL)

            self.tool_selected = self.tool_access.WINDOW_LEVEL
            self.handle_buttons_checked()

    def toggle_pan(self, selected_widget):
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget:
                if self.tool_selected == self.tool_access.PAN:
                    mpr_widget.deactivate_toolbar_tool()
                    self.tool_selected = None
                else:
                    if self.tool_selected != self.tool_access.MPR:
                        self.check_and_deactivate_tools()
                    mpr_widget.activate_toolbar_tool(self.tool_access.PAN)
                    self.tool_selected = self.tool_access.PAN
                self.handle_buttons_checked()
            return

        if self.tool_selected == self.tool_access.PAN:
            selected_widget.current_style.deactivate(self.tool_selected)
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(DefaultInteractionInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.PAN)

            self.tool_selected = self.tool_access.PAN
            self.handle_buttons_checked()

    def toggle_stacked(self, selected_widget):
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget:
                if self.tool_selected == self.tool_access.STACKED:
                    mpr_widget.deactivate_toolbar_tool()
                    self.tool_selected = None
                else:
                    if self.tool_selected != self.tool_access.MPR:
                        self.check_and_deactivate_tools()
                    mpr_widget.activate_toolbar_tool(self.tool_access.STACKED)
                    self.tool_selected = self.tool_access.STACKED
                self.handle_buttons_checked()
            return

        if self.tool_selected == self.tool_access.STACKED:
            selected_widget.current_style.deactivate(self.tool_selected)
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(DefaultInteractionInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.STACKED)

            self.tool_selected = self.tool_access.STACKED
            self.handle_buttons_checked()

    def toggle_rotation_left(self, selected_widget):
        """this method run for once. we don't need to hold active """
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if not mpr_widget:
                return

            if self.tool_selected == self.tool_access.ROTATION_LEFT:
                self.tool_selected = None
                self.handle_buttons_checked()
                return

            if self.tool_selected != self.tool_access.MPR:
                self.check_and_deactivate_tools()

            mpr_widget.apply_view_transform(self.tool_access.ROTATION_LEFT)
            self.tool_selected = self.tool_access.ROTATION_LEFT
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()
            return
        if self.tool_selected == self.tool_access.ROTATION_LEFT:
            self.tool_selected = None

            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(RotateInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.ROTATION_LEFT)

            self.tool_selected = self.tool_access.ROTATION_LEFT
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_rotation_right(self, selected_widget):
        """this method run for once. we don't need to hold active """
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if not mpr_widget:
                return

            if self.tool_selected == self.tool_access.ROTATION_RIGHT:
                self.tool_selected = None
                self.handle_buttons_checked()
                return

            if self.tool_selected != self.tool_access.MPR:
                self.check_and_deactivate_tools()

            mpr_widget.apply_view_transform(self.tool_access.ROTATION_RIGHT)
            self.tool_selected = self.tool_access.ROTATION_RIGHT
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()
            return
        if self.tool_selected == self.tool_access.ROTATION_RIGHT:
            self.tool_selected = None

            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(RotateInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.ROTATION_RIGHT)

            self.tool_selected = self.tool_access.ROTATION_RIGHT
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_flip_horizontal(self, selected_widget):
        """this method run for once. we don't need to hold active """
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if not mpr_widget:
                return

            if self.tool_selected == self.tool_access.FLIP_HORIZONTAL:
                self.tool_selected = None
                self.handle_buttons_checked()
                return

            if self.tool_selected != self.tool_access.MPR:
                self.check_and_deactivate_tools()

            mpr_widget.apply_view_transform(self.tool_access.FLIP_HORIZONTAL)
            self.tool_selected = self.tool_access.FLIP_HORIZONTAL
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()
            return
        if self.tool_selected == self.tool_access.FLIP_HORIZONTAL:
            self.tool_selected = None

            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(RotateInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.FLIP_HORIZONTAL)

            self.tool_selected = self.tool_access.FLIP_HORIZONTAL
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_flip_vertical(self, selected_widget):
        """this method run for once. we don't need to hold active """
        if self.is_mpr_viewer(selected_widget):
            mpr_widget = self.get_mpr_widget(selected_widget)
            if not mpr_widget:
                return

            if self.tool_selected == self.tool_access.FLIP_VERTICAL:
                self.tool_selected = None
                self.handle_buttons_checked()
                return

            if self.tool_selected != self.tool_access.MPR:
                self.check_and_deactivate_tools()

            mpr_widget.apply_view_transform(self.tool_access.FLIP_VERTICAL)
            self.tool_selected = self.tool_access.FLIP_VERTICAL
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()
            return
        if self.tool_selected == self.tool_access.FLIP_VERTICAL:
            self.tool_selected = None

            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(RotateInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.FLIP_VERTICAL)

            self.tool_selected = self.tool_access.FLIP_VERTICAL
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_capture(self, selected_widget):
        """this method run for once. we don't need to hold active """
        if self.tool_selected == self.tool_access.CAPTURE:
            self.tool_selected = None

            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(DefaultInteractionInteractorStyle)
            selected_widget.current_style.activate(self.tool_access.CAPTURE)

            # update counter of capture
            self.update_capture_counter()

            self.tool_selected = self.tool_access.CAPTURE
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_sync_point(self, checked=None):
        enabled = bool(checked) if checked is not None else not getattr(self, '_sync_point_enabled', False)

        self._debug_target(
            f"toggle_sync_point: enabled={enabled}, prev_selected={self.tool_selected}, "
            f"prev_sync={getattr(self, '_sync_point_enabled', False)}"
        )

        if enabled:
            self.check_and_deactivate_tools()
            self._sync_point_enabled = True
            self.tool_selected = self.tool_access.TARGET
        else:
            self._sync_point_enabled = False
            if self.tool_selected == self.tool_access.TARGET:
                self.tool_selected = None

        self._debug_target(
            f"toggle_sync_point: now_selected={self.tool_selected}, "
            f"sync_enabled={self._sync_point_enabled}"
        )

        if hasattr(self.patient_widget, 'toggle_sync_point'):
            self.patient_widget.toggle_sync_point(enabled)

        self.handle_buttons_checked()

    def _show_sync_dropdown(self, button):
        """Show dropdown menu for Lock Sync option."""
        try:
            dropdown = QWidget(self.patient_widget)
            dropdown.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
            dropdown.setAttribute(Qt.WA_DeleteOnClose)
            dropdown.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1f2937, stop:1 #111827);
                    border: 2px solid #374151;
                    border-radius: 10px;
                }
            """)

            layout = QVBoxLayout(dropdown)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)

            from PySide6.QtWidgets import QLabel
            header = QLabel("🔗 Sync Options")
            header.setStyleSheet("""
                QLabel {
                    color: #f7fafc;
                    font-size: 15px;
                    font-weight: 700;
                    font-family: 'Roboto', sans-serif;
                    padding: 6px 8px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #dc2626, stop:1 #b91c1c);
                    border-radius: 6px;
                    margin-bottom: 4px;
                }
            """)
            layout.addWidget(header)

            # Lock Sync toggle button
            lock_sync_enabled = getattr(self.patient_widget, '_lock_sync_enabled', False)
            lock_icon_name = 'fa5s.lock' if lock_sync_enabled else 'fa5s.lock-open'
            lock_color = '#10b981' if lock_sync_enabled else '#f59e0b'
            lock_label = 'Lock Sync  ✓' if lock_sync_enabled else 'Lock Sync'

            lock_sync_btn = QPushButton()
            lock_sync_btn.setIcon(qta.icon(lock_icon_name, color=lock_color))
            lock_sync_btn.setIconSize(QSize(18, 18))
            lock_sync_btn.setText(lock_label)
            lock_sync_btn.setCursor(Qt.PointingHandCursor)
            lock_sync_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #374151, stop:1 #1f2937);
                    color: {lock_color};
                    border: 1px solid #4b5563;
                    border-radius: 8px;
                    padding: 8px 14px;
                    font-size: 13px;
                    font-family: 'Roboto', sans-serif;
                    font-weight: 600;
                    text-align: left;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #4b5563, stop:1 #374151);
                    border-color: #6b7280;
                }}
            """)
            lock_sync_btn.clicked.connect(lambda: [
                self._toggle_lock_sync(),
                dropdown.close()
            ])
            layout.addWidget(lock_sync_btn)

            # Position dropdown below the button
            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            dropdown.move(button_pos)
            dropdown.setFixedWidth(220)
            dropdown.raise_()
            dropdown.activateWindow()
            dropdown.show()
        except Exception as e:
            print(f"[ERROR] Failed to show sync dropdown: {e}")
            import traceback
            traceback.print_exc()

    def _toggle_lock_sync(self):
        """Toggle Lock Sync mode on patient_widget."""
        pw = self.patient_widget
        current = getattr(pw, '_lock_sync_enabled', False)
        new_state = not current

        if new_state:
            # Lock Sync needs the sync pipeline (viewer map + sync manager)
            # but NOT the click-to-target interactor/cursor.
            # Use pipeline-only registration so other tools work normally.
            pw._sync_enabled = True
            pw.sync_manager.set_mode(SyncMode.CURSOR)
            if hasattr(pw, '_register_sync_viewers_pipeline_only'):
                pw._register_sync_viewers_pipeline_only()
        else:
            # When user explicitly disables Lock Sync, tear down sync infra
            # (unless the user has Sync Image activated manually)
            if not getattr(self, '_sync_point_enabled', False):
                pw.toggle_sync_point(False)

        if hasattr(pw, 'set_lock_sync'):
            pw.set_lock_sync(new_state)

        # Update hamburger icon to reflect lock state
        self._update_sync_menu_icon(new_state)

        print(f"[LOCK SYNC] Toggled to: {new_state}")

    def _update_sync_menu_icon(self, lock_active: bool):
        """Update the hamburger button icon to show Lock Sync state."""
        btn = getattr(self, '_sync_menu_btn', None)
        if btn is None:
            return
        if lock_active:
            btn.setIcon(qta.icon('fa5s.link', color='#10b981', scale_factor=0.9))
            btn.setToolTip('Lock Sync: ON (click to open menu)')
        else:
            btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
            btn.setToolTip('Sync Options (Lock Sync)')

    def update_capture_counter(self):
        study_uid = self.patient_widget.study_uid
        if not study_uid:
            study_uid=str(random.randint(10000,100000))  
            print(f"generated study_uid is :{study_uid}")      
        attach_path = ATTACHMENT_PATH / study_uid
        lst_images = list_files_in_folder(folder_path=attach_path, patterns=["*.png", "*.jpg"])

        capture_btn: BadgeButton = self.tools_button[self.tool_access.CAPTURE]
        capture_btn.setCount(len(lst_images))

    def _update_soundbox_position(self):
        try:
            # Check if button reference exists and is valid
            if not hasattr(self, '_mic_button_ref') or not self._mic_button_ref:
                return
                
            # Check if soundbox exists and is visible
            # Note: Accessing isVisible() can raise RuntimeError if C++ object is deleted
            if not hasattr(self, '_ToolbarManager__soundbox'):
                return
                
            if not self.__soundbox.isVisible():
                return
            
            # محاسبه موقعیت دقیق دکمه به صورت گلوبال
            button_global_pos = self._mic_button_ref.mapToGlobal(QPoint(0, 0))
            button_height = self._mic_button_ref.height()
            button_width = self._mic_button_ref.width()
            
            # محاسبه موقعیت جدید پنل (زیر دکمه، با راست‌چین)
            panel_x = button_global_pos.x() + button_width - self.__soundbox.width()
            panel_y = button_global_pos.y() + button_height + 2  # 2 پیکسل فاصله
            
            # تنظیم موقعیت مستقیم
            self.__soundbox.move(panel_x, panel_y)
            
        except RuntimeError as e:
            # Handle C++ object deletion specifically
            if "already deleted" in str(e):
                print(f"[Voice Panel] VoiceWidget deleted, stopping position timer")
                self._position_update_timer.stop()
                # Optionally reset the reference so it gets recreated on next use
                if hasattr(self, '_ToolbarManager__soundbox'):
                    delattr(self, '_ToolbarManager__soundbox')
            else:
                raise  # Re-raise if it's a different RuntimeError
        except Exception as e:
            # در صورت خطا، تایمر را متوقف کن
            print(f"[Voice Panel] Error updating position: {e}")
            self._position_update_timer.stop()
    
    def _on_mic_clicked(self, mic_btn):
        selected_widget = self.patient_widget.selected_widget

        # 1. ابتدا فریم ویس را بررسی کن
        soundbox = self.get_soundbox()
        
        # ❌ تغییر: اگر در حال نمایش است و کاربر دوباره کلیک کرد، فقط hide کن
        if soundbox.isVisible():
            soundbox.hide()
            self.turn_on_off_mic_btn(False)
            # تغییر آیکون به حالت عادی
            mic_btn.setIcon(QIcon(f"{ICON_PATH}/mic.png"))
            # توقف تایمر به‌روزرسانی موقعیت
            self._position_update_timer.stop()
            return

        # 2. چک میکروفون
        if not soundbox.check_microphone_available():
            self.tools_button[self.tool_access.MICROPHONE].setChecked(False)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.patient_widget, "Microphone Not Available",
                                "No microphone device found. Please connect a microphone and try again.")
            return

        # 3. نمایش دیالوگ تأیید
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self.patient_widget,
            'Start Voice Recording',
            'Do you want to start recording audio?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            mic_btn.setChecked(False)
            return

        # 4. ذخیره رفرنس دکمه برای به‌روزرسانی موقعیت
        self._mic_button_ref = mic_btn
        
        # 5. تنظیم موقعیت فریم و نمایش
        soundbox.show_under(mic_btn)
        soundbox.activateWindow()
        soundbox.raise_()
        
        # تغییر آیکون به حالت ضبط (قرمز)
        mic_btn.setIcon(qta.icon('fa5s.microphone', color='#ef4444'))
        
        # شروع تایمر به‌روزرسانی موقعیت
        self._position_update_timer.start()

        # 6. شروع/توقف ضبط
        soundbox.toggle_recording(selected_widget)

        # 7. وضعیت دکمه
        if self.tool_selected == self.tool_access.MICROPHONE:
            self.tool_selected = None
            self.update_audio_counter()
        else:
            self.tool_selected = self.tool_access.MICROPHONE
            self.handle_buttons_checked()

    def toggle_microphone(self, selected_widget, mic_btn):
        if self.tool_selected == self.tool_access.MICROPHONE:
            # Stop recording
            self.tool_selected = None
            self.get_soundbox().toggle_recording(selected_widget)
            self.handle_buttons_checked()
            self.update_audio_counter()
        else:
            # Check microphone availability
            if not self.get_soundbox().check_microphone_available():
                self.tools_button[self.tool_access.MICROPHONE].setChecked(False)
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self.patient_widget,
                    "Microphone Not Available",
                    "No microphone device found. Please connect a microphone and try again."
                )
                return False

            # Start recording
            # First show the popup, then start recording
            self.get_soundbox().show_under(mic_btn)
            self.get_soundbox().toggle_recording(selected_widget)

            self.tool_selected = self.tool_access.MICROPHONE
            self.handle_buttons_checked()
            return True

    def update_audio_counter(self):
        study_uid = self.patient_widget.study_uid
        if not study_uid:
            study_uid=str(random.randint(10000,100000))  
            print(f"generated study_uid is : {study_uid}")
        attach_path = ATTACHMENT_PATH / study_uid
        lst_images = list_files_in_folder(folder_path=attach_path, patterns=["*.mp3", "*.wav", "*.m4a", "*.ogg", "*.webm"])

        mic_btn: BadgeButton = self.tools_button[self.tool_access.MICROPHONE]
        mic_btn.setCount(len(lst_images))

    def get_soundbox(self):
        """Get the VoiceWidget instance"""
        try:
            if hasattr(self, '_ToolbarManager__soundbox'):
                # Verify C++ object still exists by calling a harmless method
                self._ToolbarManager__soundbox.objectName()
                return self._ToolbarManager__soundbox
        except RuntimeError:
            # C++ object was deleted, will recreate below
            pass
        
        # Initialize if not exists or was deleted
        self.__soundbox = VoiceWidget(
            patient_widget=self.patient_widget,
            method_update_audio_counter=self.update_audio_counter,
            method_check_status_mic_btn=self.turn_on_off_mic_btn
        )
        return self.__soundbox

    def turn_on_off_mic_btn(self, status=None):
        # selected_widget = self.patient_widget.selected_widget
        # self.toggle_microphone(selected_widget=selected_widget, mic_btn=mic_btn)
        mic_btn: QPushButton = self.tools_button[self.tool_access.MICROPHONE]

        if status is None:  # check auto
            if mic_btn.isChecked():
                mic_btn.setChecked(False)
                self.tool_selected = None

            else:
                mic_btn.setChecked(True)
                self.tool_selected = self.tool_access.MICROPHONE

        else:  # set custom status
            if status:  # turn on
                mic_btn.setChecked(True)
                self.tool_selected = self.tool_access.MICROPHONE

            else:
                mic_btn.setChecked(False)
                self.tool_selected = None

    def _get_study_uid(self):
        """Get study UID from selected widget"""
        if not hasattr(self.patient_widget, 'selected_widget') or not self.patient_widget.selected_widget:
            return None

        selected_widget = self.patient_widget.selected_widget

        # Try to get study_uid from image_viewer
        if hasattr(selected_widget, 'image_viewer') and selected_widget.image_viewer:
            if hasattr(selected_widget.image_viewer, 'metadata_fixed'):
                return selected_widget.image_viewer.metadata_fixed.get('study_uid')

        return None

    def _show_audio_dropdown(self, button):
        """Show dropdown menu for saved audio recordings"""
        print("[DEBUG] _show_audio_dropdown called!")
        study_uid = self._get_study_uid()
        print(f"[DEBUG] Study UID: {study_uid}")
        if not study_uid:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self.patient_widget,
                "No Study Selected",
                "Please select a study to view saved recordings."
            )
            return

        try:
            dropdown = AttachmentsDropdownWidget(study_uid, 'audio', self.patient_widget,
                                                 method_update_counter=self.update_audio_counter,
                                                 method_open_report=self.patient_widget.open_report_in_echo_mind)
            print("[DEBUG] Dropdown created successfully")

            # Position dropdown below the button
            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            print(f"[DEBUG] Button position: {button_pos}")
            dropdown.move(button_pos)
            dropdown.setFixedWidth(350)  # Increased width for audio player
            dropdown.setFixedHeight(500)
            dropdown.raise_()
            dropdown.activateWindow()

            print("[DEBUG] About to show dropdown...")
            dropdown.show()
            print("[DEBUG] Dropdown shown!")
        except Exception as e:
            print(f"[ERROR] Failed to show dropdown: {e}")
            import traceback
            traceback.print_exc()

    def _show_capture_dropdown(self, button):
        """Show dropdown menu for saved captured images"""
        print("[DEBUG] _show_capture_dropdown called!")
        study_uid = self._get_study_uid()
        print(f"[DEBUG] Study UID: {study_uid}")
        if not study_uid:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self.patient_widget,
                "No Study Selected",
                "Please select a study to view saved images."
            )
            return

        try:
            dropdown = AttachmentsDropdownWidget(study_uid, 'image', self.patient_widget,
                                                 method_update_counter=self.update_capture_counter)
            print("[DEBUG] Dropdown created successfully")

            # Position dropdown below the button
            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            print(f"[DEBUG] Button position: {button_pos}")
            dropdown.move(button_pos)
            dropdown.setFixedWidth(350)
            dropdown.setFixedHeight(500)
            dropdown.raise_()
            dropdown.activateWindow()

            print("[DEBUG] About to show dropdown...")
            dropdown.show()
            print("[DEBUG] Dropdown shown!")
        except Exception as e:
            print(f"[ERROR] Failed to show dropdown: {e}")
            import traceback
            traceback.print_exc()

    def _show_measurements_dropdown(self, button):
        try:
            dropdown = QWidget(self.patient_widget)
            dropdown.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
            dropdown.setAttribute(Qt.WA_DeleteOnClose)
            dropdown.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1f2937, stop:1 #111827);
                    border: 2px solid #374151;
                    border-radius: 10px;
                }
            """)

            layout = QVBoxLayout(dropdown)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)

            # Header with icon
            from PySide6.QtWidgets import QLabel
            header = QLabel("📏 Measurement Tools")
            header.setStyleSheet("""
                QLabel {
                    color: #f7fafc;
                    font-size: 15px;
                    font-weight: 700;
                    font-family: 'Roboto', sans-serif;
                    padding: 6px 8px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #3b82f6, stop:1 #2563eb);
                    border-radius: 6px;
                    margin-bottom: 4px;
                }
            """)
            layout.addWidget(header)

            # Angle button
            angle_btn = create_dropdown_tool('Angle', 'angle.png', '#f59e0b')
            def _on_angle_clicked():
                self.toggle_angle(self.patient_widget.selected_widget)
                dropdown.close()
            angle_btn.clicked.connect(_on_angle_clicked)
            layout.addWidget(angle_btn)
            self.tools_button[self.tool_access.ANGLE] = angle_btn

            # Two-Line Angle button
            two_line_angle_btn = create_dropdown_tool('Two-Line Angle', 'fa5s.drafting-compass', '#06b6d4')
            def _on_two_line_angle_clicked():
                self.toggle_two_line_angle(self.patient_widget.selected_widget)
                dropdown.close()
            two_line_angle_btn.clicked.connect(_on_two_line_angle_clicked)
            layout.addWidget(two_line_angle_btn)
            self.tools_button[self.tool_access.TWO_LINE_ANGLE] = two_line_angle_btn

            # Arrow button
            arrow_btn = create_dropdown_tool('Arrow', 'arrow.png', '#10b981')
            def _on_arrow_clicked():
                self.toggle_arrow(self.patient_widget.selected_widget)
                dropdown.close()
            arrow_btn.clicked.connect(_on_arrow_clicked)
            layout.addWidget(arrow_btn)
            self.tools_button[self.tool_access.ARROW] = arrow_btn

            # Text button
            text_btn = create_dropdown_tool('Text', 'text.png', '#8b5cf6')
            def _on_text_clicked():
                self.toggle_text(self.patient_widget.selected_widget)
                dropdown.close()
            text_btn.clicked.connect(_on_text_clicked)
            layout.addWidget(text_btn)
            self.tools_button[self.tool_access.TEXT] = text_btn

            # ROI button
            roi_btn = create_dropdown_tool('ROI', 'Pentagon.svg', '#ec4899')
            def _on_roi_clicked():
                self.toggle_roi(self.patient_widget.selected_widget)
                dropdown.close()
            roi_btn.clicked.connect(_on_roi_clicked)
            layout.addWidget(roi_btn)
            self.tools_button[self.tool_access.ROI] = roi_btn

            # Circle ROI button
            circle_roi_btn = create_dropdown_tool('Circle ROI', 'fa5s.circle', '#f472b6')
            def _on_circle_roi_clicked():
                self.toggle_circle_roi(self.patient_widget.selected_widget)
                dropdown.close()
            circle_roi_btn.clicked.connect(_on_circle_roi_clicked)
            layout.addWidget(circle_roi_btn)
            self.tools_button[self.tool_access.CIRCLE_ROI] = circle_roi_btn

            # Position dropdown below the button
            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            dropdown.move(button_pos)
            dropdown.setFixedWidth(260)
            dropdown.raise_()
            dropdown.activateWindow()

            self.handle_buttons_checked()
            dropdown.show()
        except Exception as e:
            print(f"[ERROR] Failed to show measurements dropdown: {e}")
            import traceback
            traceback.print_exc()

    def _show_mpr_dropdown(self, button):
        """Show dropdown menu for MIP/MinIP/Thick Slab options"""
        try:
            print("[DEBUG] _show_mpr_dropdown called! Creating MPR Visualization Options dropdown...")
            dropdown = QWidget(self.patient_widget)
            dropdown.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
            dropdown.setAttribute(Qt.WA_DeleteOnClose)
            dropdown.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1f2937, stop:1 #111827);
                    border: 2px solid #374151;
                    border-radius: 10px;
                }
            """)

            layout = QVBoxLayout(dropdown)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)

            # Header with icon
            from PySide6.QtWidgets import QLabel
            header = QLabel("🎨 Visualization Options")
            header.setStyleSheet("""
                QLabel {
                    color: #f7fafc;
                    font-size: 15px;
                    font-weight: 700;
                    font-family: 'Roboto', sans-serif;
                    padding: 6px 8px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #7c3aed, stop:1 #6d28d9);
                    border-radius: 6px;
                    margin-bottom: 4px;
                }
            """)
            layout.addWidget(header)

            # Curved MPR button (Dental)
            curved_mpr_btn = create_dropdown_tool('Dental Curve MPR', 'fa5s.bezier-curve', '#8b5cf6')
            curved_mpr_btn.clicked.connect(lambda: [
                self._show_curved_mpr_panel(),
                dropdown.close()
            ])
            layout.addWidget(curved_mpr_btn)
            
            # MIP button
            mip_btn = create_dropdown_tool('MIP - Maximum Intensity', 'fa5s.layer-group', '#60a5fa')
            mip_btn.clicked.connect(lambda: [
                self.toggle_mip(self.patient_widget.selected_widget),
                dropdown.close()
            ])
            layout.addWidget(mip_btn)
            self.tools_button[self.tool_access.MIP] = mip_btn

            # MinIP button
            minip_btn = create_dropdown_tool('MinIP - Minimum Intensity', 'fa5s.layer-group', '#34d399')
            minip_btn.clicked.connect(lambda: [
                self.toggle_minip(self.patient_widget.selected_widget),
                dropdown.close()
            ])
            layout.addWidget(minip_btn)
            self.tools_button[self.tool_access.MINIP] = minip_btn

            # Thick Slab button
            thick_btn = create_dropdown_tool('Thick Slab MIP', 'fa5s.layer-group', '#f59e0b')
            thick_btn.clicked.connect(lambda: [
                self.toggle_thick_slab(self.patient_widget.selected_widget),
                dropdown.close()
            ])
            layout.addWidget(thick_btn)
            self.tools_button[self.tool_access.THICK_SLAB] = thick_btn

            # Note: Zeta MPR removed from dropdown - now the main MPR button

            # Position dropdown below the button
            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            dropdown.move(button_pos)
            dropdown.setFixedWidth(280)
            dropdown.raise_()
            dropdown.activateWindow()

            self.handle_buttons_checked()
            dropdown.show()
        except Exception as e:
            print(f"[ERROR] Failed to show MPR dropdown: {e}")
            import traceback
            traceback.print_exc()

    def _show_rotation_dropdown(self, button):
        try:
            dropdown = QWidget(self.patient_widget)
            dropdown.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
            dropdown.setAttribute(Qt.WA_DeleteOnClose)
            dropdown.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1f2937, stop:1 #111827);
                    border: 2px solid #374151;
                    border-radius: 10px;
                }
            """)

            layout = QVBoxLayout(dropdown)
            layout.setContentsMargins(10, 10, 10, 10)
            layout.setSpacing(8)

            header = QLabel("🔄 Rotate / Flip")
            header.setStyleSheet("""
                QLabel {
                    color: #f7fafc;
                    font-size: 15px;
                    font-weight: 700;
                    font-family: 'Roboto', sans-serif;
                    padding: 6px 8px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #3b82f6, stop:1 #2563eb);
                    border-radius: 6px;
                    margin-bottom: 4px;
                }
            """)
            layout.addWidget(header)

            rotate_right_btn = create_dropdown_tool('Rotate Right', 'rotate-cw.png', '#60a5fa')
            rotate_right_btn.clicked.connect(lambda: [
                self.toggle_rotation_right(self.patient_widget.selected_widget), dropdown.close()])
            layout.addWidget(rotate_right_btn)

            rotate_left_btn = create_dropdown_tool('Rotate Left', 'rotate-ccw.png', '#f59e0b')
            rotate_left_btn.clicked.connect(lambda: [
                self.toggle_rotation_left(self.patient_widget.selected_widget), dropdown.close()])
            layout.addWidget(rotate_left_btn)

            flip_updown_btn = create_dropdown_tool('Flip Upside Down', 'flip_v.png', '#10b981')
            flip_updown_btn.clicked.connect(lambda: [
                self.toggle_flip_vertical(self.patient_widget.selected_widget), dropdown.close()])
            layout.addWidget(flip_updown_btn)

            flip_lr_btn = create_dropdown_tool('Flip Left to Right', 'flip_v.png', '#10b981')
            try:
                flip_pixmap = QPixmap(f"{ICON_PATH}/flip_v.png")
                if not flip_pixmap.isNull():
                    rotated = flip_pixmap.transformed(QTransform().rotate(-90))
                    flip_lr_btn.setIcon(QIcon(rotated))
                    flip_lr_btn.setIconSize(QSize(18, 18))
            except Exception:
                pass
            flip_lr_btn.clicked.connect(lambda: [
                self.toggle_flip_horizontal(self.patient_widget.selected_widget), dropdown.close()])
            layout.addWidget(flip_lr_btn)

            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            dropdown.move(button_pos)
            dropdown.setFixedWidth(260)
            dropdown.raise_()
            dropdown.activateWindow()

            dropdown.show()
        except Exception as e:
            print(f"[ERROR] Failed to show rotation dropdown: {e}")
            import traceback
            traceback.print_exc()

    def toggle_roi(self, selected_widget):
        if selected_widget is None:
            print("⚠️ toggle_roi: selected_widget is None, ignoring")
            return
        
        if self.tool_selected == self.tool_access.ROI:  # deactivate tool
            selected_widget.current_style.deactivate()
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()

            # Create new roi style and set it as the current interactor style
            selected_widget.set_new_interactorstyle(RoiInteractorStyle)

            selected_widget.current_style.activate()
            self.tool_selected = self.tool_access.ROI
            self.handle_buttons_checked()

    def toggle_circle_roi(self, selected_widget):
        if selected_widget is None:
            print("⚠️ toggle_circle_roi: selected_widget is None, ignoring")
            return
        
        if self.tool_selected == self.tool_access.CIRCLE_ROI:  # deactivate tool
            selected_widget.current_style.deactivate()
            self.tool_selected = None
            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()

            # Create new circle roi style and set it as the current interactor style
            try:
                selected_widget.set_new_interactorstyle(CircleRoiInteractorStyle)
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self.patient_widget,
                    "Circle ROI Unavailable",
                    f"Circle ROI tool could not be initialized:\n{str(e)}"
                )
                selected_widget.restore_default_interactorstyle()
                return

            selected_widget.current_style.activate()
            self.tool_selected = self.tool_access.CIRCLE_ROI
            self.handle_buttons_checked()

    def toggle_ai_chat(self, selected_widget):
        if selected_widget is None:
            print("No widget selected.") #Debugging statement
            return  # Exit if no widget is selected


        if self.tool_selected == self.tool_access.AI_CHAT:  # deactivate tool
            self.tool_selected = None

            selected_widget.restore_default_interactorstyle()
            self.handle_buttons_checked()

        else:
            self.check_and_deactivate_tools()
            selected_widget.set_new_interactorstyle(AIChatInteractorStyle)
            selected_widget.current_style.check_status(self.patient_widget)

            self.tool_selected = self.tool_access.AI_CHAT
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

    def toggle_mip(self, selected_widget):
        """Apply Maximum Intensity Projection - Simple Pure NumPy approach"""
        import logging
        import vtkmodules.all as vtk
        from PySide6.QtWidgets import QMessageBox, QInputDialog, QProgressDialog
        from PySide6.QtCore import Qt, QCoreApplication
        import numpy as np
        from vtkmodules.util import numpy_support
        logger = logging.getLogger(__name__)

        try:
            if getattr(selected_widget, '_mip_mode', None) == 'MIP':
                self._restore_original_volume(selected_widget)
                return
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget and hasattr(mpr_widget, '_apply_mip'):
                if self.tool_selected == self.tool_access.MIP and hasattr(mpr_widget, 'reset_slab_projection'):
                    mpr_widget.reset_slab_projection()
                    self.tool_selected = None
                    self.handle_buttons_checked()
                    return
                logger.info("Applying MIP in Zeta MPR viewer")
                mpr_widget._apply_mip()
                self.tool_selected = self.tool_access.MIP
                self.handle_buttons_checked()
                return

            logger.info("=" * 60)
            logger.info("2D MIP - Pure NumPy approach")
            logger.info("=" * 60)

            # Check if widget has image data
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                logger.warning("No image loaded in selected viewport")
                QMessageBox.warning(self.patient_widget, "No Image", "Please load an image first")
                return

            # Get thickness from user
            thickness, ok = QInputDialog.getInt(
                self.patient_widget,
                "MIP Thickness",
                "Enter slab thickness (number of slices):",
                10,  # default
                1,  # min
                30  # max
            )

            if not ok:
                return

            logger.info(f"Creating MIP volume with thickness: {thickness} slices")

            # Get the original 3D volume
            image_viewer = selected_widget.image_viewer

            # Store original data - IMPORTANT: Update if series changed!
            # Check if this is a new series or if we need to update the backup
            current_series = selected_widget.last_series_show
            need_new_backup = (
                    not hasattr(selected_widget, '_original_image_data') or
                    not hasattr(selected_widget, '_mip_series') or
                    selected_widget._mip_series != current_series
            )

            if need_new_backup:
                selected_widget._original_image_data = image_viewer.vtk_image_data
                selected_widget._original_slice = image_viewer.GetSlice()
                selected_widget._mip_series = current_series
                logger.info(f"Original data stored for series {current_series}")
            else:
                logger.info(f"Using existing backup for series {current_series}")

            original_data = selected_widget._original_image_data
            dims = original_data.GetDimensions()
            spacing = original_data.GetSpacing()
            origin = original_data.GetOrigin()

            logger.info(f"Original - dims: {dims}, spacing: {spacing}, origin: {origin}")

            # Convert VTK to NumPy
            vtk_array = original_data.GetPointData().GetScalars()
            np_data = numpy_support.vtk_to_numpy(vtk_array)
            np_data = np_data.reshape(dims[2], dims[1], dims[0])  # Z, Y, X order

            logger.info(f"NumPy array shape: {np_data.shape}, dtype: {np_data.dtype}")
            logger.info(f"Data range: min={np_data.min()}, max={np_data.max()}")

            # Create progress dialog
            progress = QProgressDialog("Computing MIP...", "Cancel", 0, 100, self.patient_widget)
            progress.setWindowModality(Qt.WindowModal)
            progress.setWindowTitle("MIP Processing")
            progress.setValue(0)
            QCoreApplication.processEvents()

            # Create MIP output array - same size as input
            mip_data = np.zeros_like(np_data)

            logger.info(f"Processing MIP with thickness {thickness}...")

            # Compute MIP for each slice
            half_thick = thickness // 2
            for z in range(dims[2]):
                if progress.wasCanceled():
                    logger.info("Cancelled by user")
                    return

                # Update progress more frequently to avoid UI freeze
                if z % 5 == 0:  # Changed from 10 to 5 for more frequent updates
                    progress.setValue(int(100 * z / dims[2]))
                    QCoreApplication.processEvents()  # Keep UI responsive

                # Calculate slab range
                z_start = max(0, z - half_thick)
                z_end = min(dims[2], z + half_thick + 1)

                # Take maximum across the slab - using NumPy for speed
                mip_data[z] = np.max(np_data[z_start:z_end], axis=0)

            progress.setValue(100)

            logger.info(f"MIP computed! Output shape: {mip_data.shape}")
            logger.info(f"MIP range: min={mip_data.min()}, max={mip_data.max()}")

            # Check if MIP is different from original
            if np.array_equal(mip_data, np_data):
                logger.warning("WARNING: MIP data is identical to original! No MIP effect!")
            else:
                diff = np.abs(mip_data - np_data).sum()
                logger.info(f"MIP is different from original, total difference: {diff}")

            # Convert back to VTK
            mip_flat = mip_data.flatten()
            vtk_mip_array = numpy_support.numpy_to_vtk(mip_flat, deep=True, array_type=vtk_array.GetDataType())

            # Create new volume
            mip_volume = vtk.vtkImageData()
            mip_volume.SetDimensions(dims[0], dims[1], dims[2])
            mip_volume.SetSpacing(spacing)
            mip_volume.SetOrigin(origin)
            mip_volume.GetPointData().SetScalars(vtk_mip_array)

            logger.info(f"MIP volume created - dims: {mip_volume.GetDimensions()}")
            logger.info(f"MIP volume scalar range: {mip_volume.GetScalarRange()}")

            # Mark MIP mode
            selected_widget._mip_mode = 'MIP'
            self.tool_selected = self.tool_access.MIP
            self.handle_buttons_checked()
            selected_widget._mip_thickness = thickness

            # Update viewer
            logger.info("Updating viewer with MIP volume...")
            current_slice = selected_widget._original_slice

            # CRITICAL FIX: Update the underlying vtk_image_data reference
            # This ensures the viewer displays the MIP volume correctly
            logger.info("Step 1: Updating vtk_image_data reference")
            image_viewer.vtk_image_data = mip_volume

            # Update the reslice filter with new data
            logger.info("Step 2: Updating image_reslice filter")
            image_viewer.image_reslice.SetInputData(mip_volume)
            image_viewer.image_reslice.Update()
            logger.info(f"  Reslice output range: {image_viewer.image_reslice.GetOutput().GetScalarRange()}")

            # IMPORTANT: Update color mapper with new reslice output
            # Without this, the old data will still be displayed!
            logger.info("Step 3: Updating color_mapper")
            image_viewer.color_mapper.SetInputConnection(image_viewer.image_reslice.GetOutputPort())
            image_viewer.color_mapper.Update()
            logger.info(f"  Color mapper output range: {image_viewer.color_mapper.GetOutput().GetScalarRange()}")

            # Now update the viewer input
            logger.info("Step 4: Updating viewer input")
            image_viewer.SetInputData(image_viewer.image_reslice.GetOutput())
            image_viewer.UpdateDisplayExtent()
            image_viewer.SetSlice(current_slice)
            logger.info(f"  Current slice set to: {current_slice}")

            # Adjust window/level for MIP (typically needs wider range)
            mip_range = mip_volume.GetScalarRange()
            logger.info(f"Step 5: Adjusting window/level for MIP range: {mip_range}")
            window = mip_range[1] - mip_range[0]
            level = (mip_range[0] + mip_range[1]) / 2.0
            logger.info(f"  Setting ColorWindow={window}, ColorLevel={level}")
            image_viewer.SetColorWindow(window)
            image_viewer.SetColorLevel(level)

            # Force a complete render
            logger.info("Step 6: Rendering...")
            image_viewer.GetRenderer().ResetCameraClippingRange()
            image_viewer.Render()
            logger.info("Step 7: Render complete!")

            logger.info(f"Viewer updated! Current slice: {current_slice}")
            logger.info("=" * 60)

            QMessageBox.information(
                self.patient_widget,
                "MIP Applied",
                f"MIP applied!\n\n"
                f"Thickness: {thickness} slices\n"
                f"Data range: {mip_data.min():.0f} to {mip_data.max():.0f}\n\n"
                f"Scroll to see MIP slices.\n"
                f"Use 'Reset Selected' to restore."
            )

        except Exception as e:
            logger.error(f"ERROR in MIP: {e}", exc_info=True)
            QMessageBox.critical(self.patient_widget, "Error", f"Error: {str(e)}")

        self.handle_buttons_checked()

    def toggle_minip(self, selected_widget):
        """Apply Minimum Intensity Projection to 2D series - Scrollable"""
        import logging
        import vtkmodules.all as vtk
        from PySide6.QtWidgets import QMessageBox, QInputDialog, QProgressDialog
        from PySide6.QtCore import Qt, QCoreApplication
        import numpy as np
        from vtkmodules.util import numpy_support
        logger = logging.getLogger(__name__)

        try:
            if getattr(selected_widget, '_mip_mode', None) == 'MinIP':
                self._restore_original_volume(selected_widget)
                return
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget and hasattr(mpr_widget, '_apply_minip'):
                if self.tool_selected == self.tool_access.MINIP and hasattr(mpr_widget, 'reset_slab_projection'):
                    mpr_widget.reset_slab_projection()
                    self.tool_selected = None
                    self.handle_buttons_checked()
                    return
                logger.info("Applying MinIP in Zeta MPR viewer")
                mpr_widget._apply_minip()
                self.tool_selected = self.tool_access.MINIP
                self.handle_buttons_checked()
                return

            logger.info("=" * 60)
            logger.info("2D SCROLLABLE MinIP BUTTON CLICKED")
            logger.info("=" * 60)

            # Check if widget has image data
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                logger.warning("No image loaded in selected viewport")
                QMessageBox.warning(self.patient_widget, "No Image", "Please load an image first")
                return

            # Get thickness from user
            thickness, ok = QInputDialog.getInt(
                self.patient_widget,
                "MinIP Thickness",
                "Enter slab thickness (number of slices):",
                10,  # default
                1,  # min
                50  # max
            )

            if not ok:
                return

            logger.info(f"Creating scrollable MinIP volume with thickness: {thickness} slices")

            # Get the original 3D volume
            image_viewer = selected_widget.image_viewer

            # Store original data - IMPORTANT: Update if series changed!
            current_series = selected_widget.last_series_show
            need_new_backup = (
                    not hasattr(selected_widget, '_original_image_data') or
                    not hasattr(selected_widget, '_mip_series') or
                    selected_widget._mip_series != current_series
            )

            if need_new_backup:
                selected_widget._original_image_data = image_viewer.vtk_image_data
                selected_widget._original_slice = image_viewer.GetSlice()
                selected_widget._mip_series = current_series
                selected_widget._mip_mode = None
                logger.info(f"Original data stored for series {current_series}")
            else:
                logger.info(f"Using existing backup for series {current_series}")

            original_data = selected_widget._original_image_data
            dims = original_data.GetDimensions()

            logger.info(f"Original dimensions: {dims}")
            logger.info(f"Creating scrollable MinIP volume with thickness {thickness}")

            # OPTIMIZED: Convert to NumPy for much faster processing
            vtk_array = original_data.GetPointData().GetScalars()
            np_data = numpy_support.vtk_to_numpy(vtk_array)
            np_data = np_data.reshape(dims[2], dims[1], dims[0])  # Z, Y, X order

            logger.info("Processing MinIP with NumPy (fast)...")

            # Create progress dialog
            progress = QProgressDialog("Computing MinIP...", "Cancel", 0, 100, self.patient_widget)
            progress.setWindowModality(Qt.WindowModal)
            progress.setWindowTitle("MinIP Processing")
            progress.setValue(0)
            QCoreApplication.processEvents()

            # Create MinIP output array
            minip_data = np.zeros_like(np_data)

            half_thick = thickness // 2
            for z in range(dims[2]):
                if progress.wasCanceled():
                    logger.info("MinIP cancelled by user")
                    return

                # Update progress frequently
                if z % 5 == 0:
                    progress.setValue(int(100 * z / dims[2]))
                    QCoreApplication.processEvents()

                # Calculate slab range
                z_start = max(0, z - half_thick)
                z_end = min(dims[2], z + half_thick + 1)

                # Take minimum across the slab - NumPy is very fast!
                minip_data[z] = np.min(np_data[z_start:z_end], axis=0)

                if z % 10 == 0:
                    logger.info(f"  Processed {z}/{dims[2]} slices")

            progress.setValue(100)

            # Convert back to VTK
            minip_flat = minip_data.flatten()
            vtk_minip_array = numpy_support.numpy_to_vtk(minip_flat, deep=True,
                                                         array_type=original_data.GetScalarType())

            minip_volume = vtk.vtkImageData()
            minip_volume.SetDimensions(dims[0], dims[1], dims[2])
            minip_volume.SetSpacing(original_data.GetSpacing())
            minip_volume.SetOrigin(original_data.GetOrigin())
            minip_volume.GetPointData().SetScalars(vtk_minip_array)

            logger.info(f"MinIP volume created! Dimensions: {minip_volume.GetDimensions()}")

            # Mark that we're in MinIP mode
            selected_widget._mip_mode = 'MinIP'
            self.tool_selected = self.tool_access.MINIP
            self.handle_buttons_checked()
            selected_widget._mip_thickness = thickness

            # Update the viewer with scrollable MinIP volume
            logger.info("Updating viewer with MinIP volume...")
            current_slice = selected_widget._original_slice

            # CRITICAL FIX: Update the underlying vtk_image_data and reslice
            logger.info("Step 1: Updating vtk_image_data reference")
            image_viewer.vtk_image_data = minip_volume

            logger.info("Step 2: Updating image_reslice filter")
            image_viewer.image_reslice.SetInputData(minip_volume)
            image_viewer.image_reslice.Update()
            logger.info(f"  Reslice output range: {image_viewer.image_reslice.GetOutput().GetScalarRange()}")

            # Update color mapper
            logger.info("Step 3: Updating color_mapper")
            image_viewer.color_mapper.SetInputConnection(image_viewer.image_reslice.GetOutputPort())
            image_viewer.color_mapper.Update()
            logger.info(f"  Color mapper output range: {image_viewer.color_mapper.GetOutput().GetScalarRange()}")

            logger.info("Step 4: Updating viewer input")
            image_viewer.SetInputData(image_viewer.image_reslice.GetOutput())
            image_viewer.UpdateDisplayExtent()
            image_viewer.SetSlice(current_slice)
            logger.info(f"  Current slice set to: {current_slice}")

            # Adjust window/level for MinIP
            minip_range = minip_volume.GetScalarRange()
            logger.info(f"Step 5: Adjusting window/level for MinIP range: {minip_range}")
            window = minip_range[1] - minip_range[0]
            level = (minip_range[0] + minip_range[1]) / 2.0
            logger.info(f"  Setting ColorWindow={window}, ColorLevel={level}")
            image_viewer.SetColorWindow(window)
            image_viewer.SetColorLevel(level)

            logger.info("Step 6: Rendering...")
            image_viewer.GetRenderer().ResetCameraClippingRange()
            image_viewer.Render()
            logger.info("Step 7: Render complete!")

            logger.info("Scrollable MinIP applied successfully!")
            logger.info("=" * 60)

            QMessageBox.information(
                self.patient_widget,
                "MinIP Applied",
                f"Scrollable Minimum Intensity Projection applied!\n\n"
                f"Thickness: {thickness} slices\n"
                f"You can now scroll through MinIP slices with mouse wheel.\n\n"
                f"Tip: Use Reset tool to restore original view."
            )

        except Exception as e:
            logger.error(f"ERROR in MinIP: {e}", exc_info=True)
            QMessageBox.critical(self.patient_widget, "Error", f"Error applying MinIP:\n{str(e)}")

        self.handle_buttons_checked()

    def toggle_thick_slab(self, selected_widget):
        """Apply Thick Slab (Average) to 2D series"""
        import logging
        import vtkmodules.all as vtk
        from PySide6.QtWidgets import QMessageBox, QInputDialog, QProgressDialog
        from PySide6.QtCore import Qt, QCoreApplication
        import numpy as np
        from vtkmodules.util import numpy_support
        logger = logging.getLogger(__name__)

        try:
            if getattr(selected_widget, '_mip_mode', None) == 'ThickSlab':
                self._restore_original_volume(selected_widget)
                return
            mpr_widget = self.get_mpr_widget(selected_widget)
            if mpr_widget and hasattr(mpr_widget, '_apply_thick_slab'):
                if self.tool_selected == self.tool_access.THICK_SLAB and hasattr(mpr_widget, 'reset_slab_projection'):
                    mpr_widget.reset_slab_projection()
                    self.tool_selected = None
                    self.handle_buttons_checked()
                    return
                thickness_mm, ok = QInputDialog.getDouble(
                    self.patient_widget,
                    "Thick Slab Thickness",
                    "Enter slab thickness (mm):",
                    10.0,
                    0.1,
                    200.0,
                    1
                )
                if not ok:
                    return

                logger.info(f"Applying Thick Slab in Zeta MPR viewer (thickness={thickness_mm} mm)")
                mpr_widget._apply_thick_slab(thickness_mm)
                self.tool_selected = self.tool_access.THICK_SLAB
                self.handle_buttons_checked()
                return

            logger.info("=" * 60)
            logger.info("2D THICK SLAB BUTTON CLICKED")
            logger.info("=" * 60)

            # Check if widget has image data
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                logger.warning("No image loaded in selected viewport")
                QMessageBox.warning(self.patient_widget, "No Image", "Please load an image first")
                return

            # Get thickness from user
            thickness, ok = QInputDialog.getInt(
                self.patient_widget,
                "Thick Slab Thickness",
                "Enter slab thickness (number of slices):",
                10,  # default
                1,  # min
                100  # max
            )

            if not ok:
                return

            logger.info(f"Applying Thick Slab with thickness: {thickness} slices")

            # Get the original 3D volume
            image_viewer = selected_widget.image_viewer

            # Store original data - IMPORTANT: Update if series changed!
            current_series = selected_widget.last_series_show
            need_new_backup = (
                    not hasattr(selected_widget, '_original_image_data') or
                    not hasattr(selected_widget, '_mip_series') or
                    selected_widget._mip_series != current_series
            )

            if need_new_backup:
                selected_widget._original_image_data = image_viewer.vtk_image_data
                selected_widget._original_slice = image_viewer.GetSlice()
                selected_widget._mip_series = current_series
                selected_widget._mip_mode = None
                logger.info(f"Original data stored for series {current_series}")
            else:
                logger.info(f"Using existing backup for series {current_series}")

            original_data = selected_widget._original_image_data
            dims = original_data.GetDimensions()

            logger.info(f"Original dimensions: {dims}")
            logger.info(f"Creating Thick Slab volume with thickness {thickness}")

            # OPTIMIZED: Convert to NumPy for much faster processing
            vtk_array = original_data.GetPointData().GetScalars()
            np_data = numpy_support.vtk_to_numpy(vtk_array)
            np_data = np_data.reshape(dims[2], dims[1], dims[0])  # Z, Y, X order

            logger.info("Processing Thick Slab (Average) with NumPy (fast)...")

            # Create progress dialog
            progress = QProgressDialog("Computing Thick Slab...", "Cancel", 0, 100, self.patient_widget)
            progress.setWindowModality(Qt.WindowModal)
            progress.setWindowTitle("Thick Slab Processing")
            progress.setValue(0)
            QCoreApplication.processEvents()

            # Create Thick Slab output array
            slab_data = np.zeros_like(np_data, dtype=np.float32)  # Use float for averaging

            half_thick = thickness // 2
            for z in range(dims[2]):
                if progress.wasCanceled():
                    logger.info("Thick Slab cancelled by user")
                    return

                # Update progress frequently
                if z % 5 == 0:
                    progress.setValue(int(100 * z / dims[2]))
                    QCoreApplication.processEvents()

                # Calculate slab range
                z_start = max(0, z - half_thick)
                z_end = min(dims[2], z + half_thick + 1)

                # Take mean (average) across the slab - NumPy is very fast!
                slab_data[z] = np.mean(np_data[z_start:z_end], axis=0)

                if z % 10 == 0:
                    logger.info(f"  Processed {z}/{dims[2]} slices")

            progress.setValue(100)

            # Convert back to original data type and VTK
            slab_data = slab_data.astype(np_data.dtype)
            slab_flat = slab_data.flatten()
            vtk_slab_array = numpy_support.numpy_to_vtk(slab_flat, deep=True, array_type=original_data.GetScalarType())

            slab_volume = vtk.vtkImageData()
            slab_volume.SetDimensions(dims[0], dims[1], dims[2])
            slab_volume.SetSpacing(original_data.GetSpacing())
            slab_volume.SetOrigin(original_data.GetOrigin())
            slab_volume.GetPointData().SetScalars(vtk_slab_array)

            logger.info(f"Thick Slab volume created! Dimensions: {slab_volume.GetDimensions()}")

            # Mark that we're in Thick Slab mode
            selected_widget._mip_mode = 'ThickSlab'
            self.tool_selected = self.tool_access.THICK_SLAB
            self.handle_buttons_checked()
            selected_widget._mip_thickness = thickness

            # Update the viewer with scrollable Thick Slab volume
            logger.info("Updating viewer with Thick Slab volume...")
            current_slice = selected_widget._original_slice

            # CRITICAL FIX: Update the underlying vtk_image_data and reslice
            logger.info("Step 1: Updating vtk_image_data reference")
            image_viewer.vtk_image_data = slab_volume

            logger.info("Step 2: Updating image_reslice filter")
            image_viewer.image_reslice.SetInputData(slab_volume)
            image_viewer.image_reslice.Update()
            logger.info(f"  Reslice output range: {image_viewer.image_reslice.GetOutput().GetScalarRange()}")

            # Update color mapper
            logger.info("Step 3: Updating color_mapper")
            image_viewer.color_mapper.SetInputConnection(image_viewer.image_reslice.GetOutputPort())
            image_viewer.color_mapper.Update()
            logger.info(f"  Color mapper output range: {image_viewer.color_mapper.GetOutput().GetScalarRange()}")

            logger.info("Step 4: Updating viewer input")
            image_viewer.SetInputData(image_viewer.image_reslice.GetOutput())
            image_viewer.UpdateDisplayExtent()
            image_viewer.SetSlice(current_slice)
            logger.info(f"  Current slice set to: {current_slice}")

            # Adjust window/level for Thick Slab
            slab_range = slab_volume.GetScalarRange()
            logger.info(f"Step 5: Adjusting window/level for Thick Slab range: {slab_range}")
            window = slab_range[1] - slab_range[0]
            level = (slab_range[0] + slab_range[1]) / 2.0
            logger.info(f"  Setting ColorWindow={window}, ColorLevel={level}")
            image_viewer.SetColorWindow(window)
            image_viewer.SetColorLevel(level)

            logger.info("Step 6: Rendering...")
            image_viewer.GetRenderer().ResetCameraClippingRange()
            image_viewer.Render()
            logger.info("Step 7: Render complete!")

            logger.info("Scrollable Thick Slab applied successfully!")
            logger.info("=" * 60)

            QMessageBox.information(
                self.patient_widget,
                "Thick Slab Applied",
                f"Scrollable Thick Slab (Average) applied!\n\n"
                f"Thickness: {thickness} slices\n"
                f"You can now scroll through averaged slices with mouse wheel.\n\n"
                f"Tip: Use Reset tool to restore original view."
            )

        except Exception as e:
            logger.error(f"ERROR in Thick Slab: {e}", exc_info=True)
            QMessageBox.critical(self.patient_widget, "Error", f"Error applying Thick Slab:\n{str(e)}")

        self.handle_buttons_checked()

    def on_itk_mpr_from_dropdown_requested(self):
        """
        Handler for ITK MPR (ITK-SNAP) menu item from MPR dropdown.
        
        Retrieves the active DICOM series from the selected viewer and forwards it
        to the newmpr4 module for ITK-SNAP integration.
        """
        import logging
        from PySide6.QtWidgets import QMessageBox
        logger = logging.getLogger(__name__)
        
        try:
            logger.info("=" * 60)
            logger.info("ITK MPR (ITK-SNAP) requested from dropdown")
            logger.info("=" * 60)
            
            # Get the selected widget (active viewer)
            selected_widget = self.patient_widget.selected_widget
            
            # Check if widget is valid and has image viewer
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                logger.warning("No image viewer available in selected widget")
                QMessageBox.warning(
                    self.patient_widget,
                    "No Image Available",
                    "No active DICOM series available for ITK MPR.\n\nPlease load an image first."
                )
                return
            
            # Check if series index is available
            if not hasattr(selected_widget, 'last_series_show') or selected_widget.last_series_show is None:
                logger.warning("No active series index found")
                QMessageBox.warning(
                    self.patient_widget,
                    "No Series Available",
                    "No active DICOM series available for ITK MPR.\n\nPlease select a series first."
                )
                return
            
            # Get the active series number (not list index!)
            active_series_number = selected_widget.last_series_show
            logger.info(f"Active series number: {active_series_number}")
            
            # Find the series data by searching for matching series_number
            series_data = None
            vtk_image_data = None
            metadata = {}
            
            for i in range(len(self.patient_widget.lst_thumbnails_data)):
                try:
                    thumbnail_data = self.patient_widget.lst_thumbnails_data[i]
                    thumb_metadata = thumbnail_data.get('metadata', {})
                    series_metadata = thumb_metadata.get('series', {})
                    series_num = int(series_metadata.get('series_number', -1))
                    
                    logger.info(f"   [{i}] series_number={series_num}, looking for {active_series_number}")
                    
                    if series_num == int(active_series_number):
                        series_data = thumbnail_data
                        vtk_image_data = thumbnail_data.get('vtk_image_data')
                        metadata = thumb_metadata
                        logger.info(f"   ✅ MATCH! Found series at index {i}")
                        break
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug(f"   [ERROR] checking thumbnail data at index {i}: {e}")
                    continue
            
            if series_data is None:
                logger.error(f"Series number {active_series_number} not found in thumbnail data")
                QMessageBox.warning(
                    self.patient_widget,
                    "Invalid Series",
                    "No active DICOM series available for ITK MPR."
                )
                return
            
            if vtk_image_data is None:
                logger.warning("VTK image data is None for active series")
                QMessageBox.warning(
                    self.patient_widget,
                    "No Image Data",
                    "No active DICOM series available for ITK MPR.\n\nImage data is not loaded."
                )
                return
            
            logger.info(f"Retrieved series data - metadata keys: {list(metadata.keys())}")
            
            # Get series information from metadata
            series_metadata = metadata.get('series', {})
            series_number = series_metadata.get('series_number', 'Unknown')
            series_description = series_metadata.get('series_description', 'Unknown')
            
            logger.info(f"Series Number: {series_number}, Description: {series_description}")
            
            # NOTE: newmpr4 (ITK-SNAP integration) module has been removed
            # Use Advanced MPR (3D Slicer) instead, which provides similar functionality
            logger.warning("ITK-SNAP integration (newmpr4) has been deprecated and removed.")
            QMessageBox.information(
                self.patient_widget,
                "Feature Removed",
                "The ITK-SNAP MPR integration has been removed.\n\n"
                "Please use:\n"
                "• Zeta MPR (main MPR button)\n"
                "• Advanced MPR (3D Slicer) from the dropdown menu\n\n"
                "These provide comprehensive MPR functionality."
            )
            return
            
            # OLD CODE - newmpr4 integration removed
            # from PacsClient.pacs.patient_tab.newmpr4 import launch_itk_mpr_for_active_series
            # launch_itk_mpr_for_active_series(...)
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"ERROR in ITK MPR dropdown handler: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.patient_widget,
                "Error",
                f"Error launching ITK MPR:\n{str(e)}"
            )

    def launch_advanced_mpr_slicer(self):
        """
        Launch Advanced MPR (3D Slicer) as a popup for the active series.
        
        This opens the custom 3D Slicer application with the DICOM directory
        of the currently selected series.
        """
        import logging
        import os
        from PySide6.QtWidgets import QMessageBox
        from pathlib import Path
        logger = logging.getLogger(__name__)
        
        try:
            logger.info("=" * 60)
            logger.info("Advanced MPR (3D Slicer) requested from dropdown")
            logger.info("=" * 60)
            
            # Get the selected widget (active viewer)
            selected_widget = self.patient_widget.selected_widget
            
            # Check if widget is valid and has image viewer
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                logger.warning("No image viewer available in selected widget")
                QMessageBox.warning(
                    self.patient_widget,
                    "No Image Available",
                    "No active DICOM series available.\n\nPlease load an image first."
                )
                return
            
            # Check if series index is available
            if not hasattr(selected_widget, 'last_series_show') or selected_widget.last_series_show is None:
                logger.warning("No active series index found")
                QMessageBox.warning(
                    self.patient_widget,
                    "No Series Available",
                    "No active DICOM series available.\n\nPlease select a series first."
                )
                return
            
            # Get the active series number
            active_series_number = selected_widget.last_series_show
            logger.info(f"Active series number: {active_series_number}")
            
            # Find the series data by searching for matching series_number
            series_data = None
            dicom_directory = None
            series_uid = None
            window_width = None
            window_center = None
            
            for i in range(len(self.patient_widget.lst_thumbnails_data)):
                try:
                    thumbnail_data = self.patient_widget.lst_thumbnails_data[i]
                    thumb_metadata = thumbnail_data.get('metadata', {})
                    series_metadata = thumb_metadata.get('series', {})
                    series_num = int(series_metadata.get('series_number', -1))
                    
                    logger.info(f"   [{i}] series_number={series_num}, looking for {active_series_number}")
                    
                    if series_num == int(active_series_number):
                        series_data = thumbnail_data
                        
                        # Get DICOM directory from series path or first instance
                        dicom_directory = series_metadata.get('series_path')
                        series_uid = series_metadata.get('series_uid')
                        
                        # If no series_path, get from first instance
                        instances = thumb_metadata.get('instances', [])
                        if instances and len(instances) > 0:
                            first_instance = instances[0]
                            if not dicom_directory:
                                first_instance_path = first_instance.get('instance_path')
                                if first_instance_path:
                                    dicom_directory = os.path.dirname(first_instance_path)
                            
                            # Get window/level from first instance
                            window_width = first_instance.get('window_width')
                            window_center = first_instance.get('window_center')
                        
                        logger.info(f"   ✅ MATCH! Found series at index {i}")
                        logger.info(f"   DICOM directory: {dicom_directory}")
                        logger.info(f"   Series UID: {series_uid}")
                        break
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug(f"   [ERROR] checking thumbnail data at index {i}: {e}")
                    continue
            
            if series_data is None or not dicom_directory:
                logger.error(f"Series number {active_series_number} not found or no DICOM directory")
                QMessageBox.warning(
                    self.patient_widget,
                    "Invalid Series",
                    "Could not find DICOM directory for the active series."
                )
                return
            
            # Verify DICOM directory exists
            if not os.path.exists(dicom_directory):
                logger.error(f"DICOM directory does not exist: {dicom_directory}")
                QMessageBox.warning(
                    self.patient_widget,
                    "Directory Not Found",
                    f"DICOM directory not found:\n{dicom_directory}"
                )
                return
            
            logger.info(f"Launching Advanced MPR Slicer with DICOM directory: {dicom_directory}")
            
            # Import and use the SlicerLauncher
            from PacsClient.pacs.patient_tab.advance_mpr_3d_slicer.slicer_launcher import get_slicer_launcher
            
            launcher = get_slicer_launcher(parent_widget=self.patient_widget)
            
            # Get patient and study info
            patient_id = getattr(self.patient_widget, 'patient_id', None)
            study_uid = getattr(self.patient_widget, 'study_uid', None)
            
            # Launch Slicer with the DICOM directory
            success = launcher.launch_with_dicom(
                dicom_dir=dicom_directory,
                layout='mpr',  # Default to MPR layout
                patient_id=patient_id,
                study_id=study_uid,
                window_width=window_width,
                window_level=window_center,
                series_uid=series_uid
            )
            
            if success:
                logger.info("Advanced MPR Slicer launched successfully")
            else:
                logger.warning("Advanced MPR Slicer launch was blocked (already running)")
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"ERROR launching Advanced MPR Slicer: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.patient_widget,
                "Error",
                f"Error launching Advanced MPR Slicer:\n{str(e)}"
            )

    def toggle_zeta_mpr(self):
        """
        Toggle Zeta MPR viewer ON/OFF for the selected viewport.
        
        When ON: Replaces the current viewport with Zeta MPR viewer, button turns green.
        When OFF: Restores the original viewport, button returns to normal state.
        """
        import logging
        import sys
        from PySide6.QtWidgets import QMessageBox
        logger = logging.getLogger(__name__)
        
        logger.info("="*100)
        logger.info("🔨 [MPR] toggle_zeta_mpr called")
        logger.info(f"   patient_widget: {self.patient_widget}")
        logger.info(f"   selected_widget: {self.patient_widget.selected_widget}")
        logger.info(f"   tool_selected: {self.tool_selected}")
        logger.info(f"   lst_nodes_viewer count: {len(self.patient_widget.lst_nodes_viewer)}")
        logger.info(f"   lst_thumbnails_data count: {len(self.patient_widget.lst_thumbnails_data)}")
        
        # Check if MPR is already active - if so, close it
        active_original_widget = None
        active_mpr_widget = None

        logger.info("   🔍 [MPR] Checking if MPR is already active...")
        try:
            for idx, node in enumerate(self.patient_widget.lst_nodes_viewer):
                widget = getattr(node, 'vtk_widget', None)
                logger.info(f"   📋 [MPR] Node {idx}: widget={widget}")
                if widget is None:
                    continue
                if hasattr(widget, '_zeta_mpr_widget') and widget._zeta_mpr_widget:
                    logger.info(f"   ✅ [MPR] Found active _zeta_mpr_widget at node {idx}")
                    active_original_widget = widget
                    active_mpr_widget = widget._zeta_mpr_widget
                    break
                if hasattr(widget, '_new_mpr_zeta_widget') and widget._new_mpr_zeta_widget:
                    logger.info(f"   ✅ [MPR] Found active _new_mpr_zeta_widget at node {idx}")
                    active_original_widget = widget
                    active_mpr_widget = widget._new_mpr_zeta_widget
                    break
        except Exception as e:
            logger.error(f"   ⚠️ [MPR] Error checking active MPR: {e}")

        selected_widget = self.patient_widget.selected_widget
        logger.info(f"   📋 [MPR] selected_widget after check: {selected_widget}")
        logger.info(f"   📋 [MPR] active_mpr_widget: {active_mpr_widget}")
        
        if active_mpr_widget is None and self.is_mpr_viewer(selected_widget):
            logger.info("   🔍 [MPR] selected_widget is_mpr_viewer")
            if hasattr(selected_widget, '_original_widget'):
                logger.info("   ✅ [MPR] Found _original_widget on selected_widget")
                active_original_widget = selected_widget._original_widget
                active_mpr_widget = selected_widget

        if active_mpr_widget is not None:
            logger.info("=" * 60)
            logger.info("🔄 [MPR CLOSE] Closing Zeta MPR (toggle OFF)")
            logger.info(f"   active_original_widget: {active_original_widget}")
            logger.info(f"   active_mpr_widget: {active_mpr_widget}")
            logger.info("=" * 60)
            
            # Restore the original viewer (handles cleanup/layout)
            self._restore_selected_viewer(active_original_widget or selected_widget)

            # Ensure the original series used for MPR is restored
            try:
                original_widget = active_original_widget or selected_widget
                series_index = getattr(original_widget, '_mpr_source_series_index', None)
                if series_index is not None:
                    current_series = getattr(original_widget, 'last_series_show', None)
                    if current_series != series_index:
                        series_data = self.patient_widget.lst_thumbnails_data[series_index]
                        vtk_image_data = series_data.get('vtk_image_data')
                        metadata = series_data.get('metadata')
                        if vtk_image_data is not None and metadata is not None:
                            original_widget.reset_image(vtk_image_data, metadata)
                if hasattr(original_widget, '_mpr_source_series_index'):
                    delattr(original_widget, '_mpr_source_series_index')
            except Exception as e:
                logger.warning(f"Could not restore MPR source series: {e}")
            
            # Clear tool selection and update button state
            self.tool_selected = None
            self.handle_buttons_checked()
            logger.info("=" * 60)
            return
        
        # Otherwise, open Zeta MPR (toggle ON)
        try:
            logger.info("=" * 60)
            logger.info("🚀 [MPR OPEN] Opening Zeta MPR (toggle ON)")
            logger.info("=" * 60)
            
            # Deactivate any other active tools
            logger.info("   🔧 [MPR OPEN] Deactivating other tools...")
            self.check_and_deactivate_tools()
            
            # Get the selected widget (active viewer)
            selected_widget = self.patient_widget.selected_widget
            logger.info(f"   📋 [MPR OPEN] selected_widget: {selected_widget}")
            logger.info(f"   📋 [MPR OPEN] selected_widget type: {type(selected_widget)}")
            
            # Log all attributes of selected_widget
            if selected_widget:
                logger.info("   📋 [MPR OPEN] selected_widget attributes:")
                logger.info(f"      has image_viewer: {hasattr(selected_widget, 'image_viewer')}")
                if hasattr(selected_widget, 'image_viewer'):
                    logger.info(f"      image_viewer value: {selected_widget.image_viewer}")
                    logger.info(f"      image_viewer type: {type(selected_widget.image_viewer)}")
                logger.info(f"      has last_series_show: {hasattr(selected_widget, 'last_series_show')}")
                if hasattr(selected_widget, 'last_series_show'):
                    logger.info(f"      last_series_show value: {selected_widget.last_series_show}")
                    logger.info(f"      last_series_show type: {type(selected_widget.last_series_show)}")
                logger.info(f"      has vtk_image_data: {hasattr(selected_widget, 'vtk_image_data')}")
                logger.info(f"      has current_style: {hasattr(selected_widget, 'current_style')}")
            
            # Check if widget is valid and has image viewer
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                logger.warning("   ⚠️ [MPR OPEN] No image viewer available in selected widget")
                logger.warning(f"      hasattr(image_viewer): {hasattr(selected_widget, 'image_viewer')}")
                if hasattr(selected_widget, 'image_viewer'):
                    logger.warning(f"      image_viewer is None: {selected_widget.image_viewer is None}")
                logger.info("=" * 100)
                QMessageBox.warning(
                    self.patient_widget,
                    "No Image Available",
                    "No active DICOM series available.\n\nPlease load an image first."
                )
                return
            
            logger.info("   ✅ [MPR OPEN] image_viewer is available")
            
            # Check if series index is available
            if not hasattr(selected_widget, 'last_series_show') or selected_widget.last_series_show is None:
                logger.warning("   ⚠️ [MPR OPEN] No active series index found")
                logger.warning(f"      hasattr(last_series_show): {hasattr(selected_widget, 'last_series_show')}")
                if hasattr(selected_widget, 'last_series_show'):
                    logger.warning(f"      last_series_show is None: {selected_widget.last_series_show is None}")
                logger.info("=" * 100)
                QMessageBox.warning(
                    self.patient_widget,
                    "No Series Available",
                    "No active DICOM series available.\n\nPlease select a series first."
                )
                return
            
            logger.info("   ✅ [MPR OPEN] last_series_show is available")
            
            # ✅ FIX: last_series_show now stores the SERIES NUMBER (string), not list index
            series_number = str(selected_widget.last_series_show)
            total_thumbnails = len(self.patient_widget.lst_thumbnails_data)
            
            logger.info(f"   📊 [MPR OPEN] Active series number: {series_number} (total thumbnails: {total_thumbnails})")
            logger.info(f"   📊 [MPR OPEN] series_number type: {type(series_number)}")
            
            # Find the series data by series number
            series_data = None
            active_series_index = None
            
            for idx, thumb_data in enumerate(self.patient_widget.lst_thumbnails_data):
                thumb_meta = thumb_data.get('metadata', {})
                series_meta = thumb_meta.get('series', {})
                this_series_num = str(series_meta.get('series_number', ''))
                
                if this_series_num == series_number:
                    series_data = thumb_data
                    active_series_index = idx
                    logger.info(f"   ✅ [MPR OPEN] Found series {series_number} at index {idx}")
                    break
            
            # Validate that we found the series
            if series_data is None or active_series_index is None:
                logger.error(f"   ❌ [MPR OPEN] Could not find series number: {series_number}")
                logger.info("=" * 100)
                QMessageBox.warning(
                    self.patient_widget,
                    "Invalid Series",
                    f"Series number {series_number} not found in thumbnails data.\nAvailable series count: {total_thumbnails}"
                )
                return
            
            logger.info("   ✅ [MPR OPEN] Series data found")
            
            # ✅ Get VTK data from found series
            try:
                logger.info(f"   🔍 [MPR OPEN] Retrieving VTK data for series {series_number}...")
                logger.info(f"   📦 [MPR OPEN] series_data keys: {series_data.keys() if series_data else 'None'}")
                
                vtk_image_data = series_data.get('vtk_image_data')
                logger.info(f"   📦 [MPR OPEN] vtk_image_data: {vtk_image_data}")
                logger.info(f"   📦 [MPR OPEN] vtk_image_data type: {type(vtk_image_data) if vtk_image_data else 'None'}")
                
                thumb_metadata = series_data.get('metadata', {})
                logger.info(f"   📦 [MPR OPEN] thumb_metadata keys: {thumb_metadata.keys() if thumb_metadata else 'None'}")
                
                # series_metadata already retrieved above
                logger.info(f"   📦 [MPR OPEN] Using series_number: {series_number}")
                
                if vtk_image_data is None:
                    logger.error(f"   ❌ [MPR OPEN] No VTK image data for series {series_number}")
                    logger.info("=" * 100)
                    QMessageBox.warning(
                        self.patient_widget,
                        "No Image Data",
                        "No VTK image data available for the selected series."
                    )
                    return
                    
                logger.info(f"   ✅ Found series {series_number} at list index {active_series_index}")
                logger.info(f"   vtk_image_data dimensions: {vtk_image_data.GetDimensions()}")

                # Remember which series spawned MPR so we can restore on close (use series_number now)
                selected_widget._mpr_source_series_number = series_number
                selected_widget._mpr_source_series_index = active_series_index  # Keep for backward compatibility
                
            except Exception as e:
                logger.error(f"Error accessing series data for series {series_number}: {e}")
                import traceback
                traceback.print_exc()
                QMessageBox.warning(
                    self.patient_widget,
                    "Data Error",
                    f"Error accessing series data: {str(e)}"
                )
                return
            
            # Get parent widget and layout
            parent_widget = selected_widget.parent()
            parent_layout = parent_widget.layout()
            
            # Find the position of the selected widget in the grid layout
            grid_position = None
            if parent_layout:
                from PySide6.QtWidgets import QGridLayout
                if isinstance(parent_layout, QGridLayout):
                    for i in range(parent_layout.count()):
                        item = parent_layout.itemAt(i)
                        if item and item.widget() == selected_widget:
                            grid_position = parent_layout.getItemPosition(i)
                            break

            if grid_position:
                selected_widget._mpr_grid_position = grid_position
            
            # Hide the original widget
            selected_widget.setVisible(False)
            
            # ✅ NOTE: If "zeta mpr" folder has space in name, consider renaming to "zeta_mpr"
            # The following import logic is preserved but path handling improved
            print("Creating Zeta MPR viewer...", file=sys.stderr, flush=True)
            
            import os
            import shutil
            import importlib.util
            
            patient_tab_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            zeta_mpr_dir = os.path.join(patient_tab_dir, "zeta mpr")
            
            # Fallback if folder doesn't exist with space, try with underscore
            if not os.path.exists(zeta_mpr_dir):
                zeta_mpr_dir = os.path.join(patient_tab_dir, "zeta_mpr")
            
            if not os.path.exists(zeta_mpr_dir):
                logger.error(f"Zeta MPR directory not found: {zeta_mpr_dir}")
                QMessageBox.critical(
                    self.patient_widget,
                    "Error",
                    "Zeta MPR module not found.\n\nPlease ensure 'zeta_mpr' folder exists in patient_tab directory."
                )
                selected_widget.setVisible(True)
                return
            
            viewers_dir = os.path.join(patient_tab_dir, "viewers")
            
            # Temporarily copy vtk_3d_presets.py if needed
            vtk_presets_src = os.path.join(viewers_dir, "vtk_3d_presets.py")
            vtk_presets_dst = os.path.join(zeta_mpr_dir, "vtk_3d_presets.py")
            copied_file = False
            
            try:
                if os.path.exists(vtk_presets_src) and not os.path.exists(vtk_presets_dst):
                    shutil.copy2(vtk_presets_src, vtk_presets_dst)
                    copied_file = True
                
                # Import using importlib to handle spaces in path
                init_path = os.path.join(zeta_mpr_dir, "__init__.py")
                if not os.path.exists(init_path):
                    logger.error(f"__init__.py not found in {zeta_mpr_dir}")
                    QMessageBox.critical(self.patient_widget, "Error", "Zeta MPR module is missing __init__.py")
                    return
                    
                spec = importlib.util.spec_from_file_location("zeta_mpr_pkg", init_path)
                zeta_mpr_pkg = importlib.util.module_from_spec(spec)
                sys.modules["zeta_mpr_pkg"] = zeta_mpr_pkg
                spec.loader.exec_module(zeta_mpr_pkg)
                
                window_width = None
                window_center = None
                try:
                    if hasattr(selected_widget, 'image_viewer') and selected_widget.image_viewer:
                        image_viewer = selected_widget.image_viewer
                        if hasattr(image_viewer, 'get_window_level'):
                            window_width, window_center = image_viewer.get_window_level()
                        elif hasattr(image_viewer, 'color_mapper'):
                            window_width = image_viewer.color_mapper.GetWindow()
                            window_center = image_viewer.color_mapper.GetLevel()
                    elif hasattr(selected_widget, 'window_width') and hasattr(selected_widget, 'window_center'):
                        window_width = selected_widget.window_width
                        window_center = selected_widget.window_center
                except Exception as wl_err:
                    logger.warning(f"Could not read window/level from main viewer: {wl_err}")

                zeta_widget = zeta_mpr_pkg.StandardMPRViewer(
                    vtk_image_data=vtk_image_data,
                    parent=parent_widget,
                    window_width=window_width,
                    window_center=window_center
                )
                
                # Add to layout at the same position
                if parent_layout and grid_position:
                    from PySide6.QtWidgets import QGridLayout
                    if isinstance(parent_layout, QGridLayout):
                        row, col, rowSpan, colSpan = grid_position
                        parent_layout.addWidget(zeta_widget, row, col, rowSpan, colSpan)
                        logger.info(f"Zeta MPR added to grid at position ({row}, {col})")
                elif parent_layout:
                    parent_layout.addWidget(zeta_widget)
                
                # Store reference
                selected_widget._zeta_mpr_widget = zeta_widget
                selected_widget._original_visible = True
                zeta_widget._original_widget = selected_widget
                
                # Set tool as active and update button state (turns green)
                self.tool_selected = self.tool_access.MPR
                self.handle_buttons_checked()
                
                logger.info("✓ Zeta MPR viewer replaced viewport successfully")
                logger.info("✓ MPR button is now active (green)")
            finally:
                # Cleanup
                if "zeta_mpr_pkg" in sys.modules:
                    del sys.modules["zeta_mpr_pkg"]
                if copied_file and os.path.exists(vtk_presets_dst):
                    try:
                        os.remove(vtk_presets_dst)
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"ERROR launching Zeta MPR: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.patient_widget,
                "Error",
                f"Error launching Zeta MPR:\n{str(e)}"
            )
            # Restore original widget visibility on error
            if selected_widget:
                selected_widget.setVisible(True)

    def toggle_mpr_DEPRECATED_OLD_MPRVIEWER(self, selected_widget=None):
        """
        DEPRECATED: This method used the old MprViewer module which has been removed.
        Use toggle_zeta_mpr() instead for Zeta MPR functionality.
        
        This method is kept for reference only and will be removed in a future version.
        """
        import logging
        from PySide6.QtWidgets import QMessageBox
        logger = logging.getLogger(__name__)
        logger.warning("toggle_mpr called but this is deprecated. Use toggle_zeta_mpr() instead.")
        QMessageBox.warning(
            self.patient_widget,
            "Deprecated Feature",
            "The old MPR Viewer has been replaced by Zeta MPR.\n\nPlease use the MPR button in the toolbar."
        )
        return
        
        # ===== OLD CODE BELOW - COMMENTED OUT FOR REFERENCE =====
        # This entire method body used MprViewerWrapper which has been removed
        """
        import logging
        import sys
        import os
        logger = logging.getLogger(__name__)
        
        print("=" * 80, file=sys.stderr, flush=True)
        print("TOGGLE MPR FUNCTION STARTED", file=sys.stderr, flush=True)
        
        if selected_widget is None:
            selected_widget = self.patient_widget.selected_widget
        
        logger.info(f"selected_widget: {selected_widget}")
        logger.info(f"selected_widget type: {type(selected_widget)}")
        
        # Check if MPR is currently active on this widget
        mpr_active = False
        mpr_widget = None
        
        if hasattr(selected_widget, '_mpr_widget') and selected_widget._mpr_widget:
            mpr_active = True
            mpr_widget = selected_widget._mpr_widget
            logger.info("Found _mpr_widget on selected_widget")
        elif hasattr(selected_widget, '_zeta_mpr_widget') and selected_widget._zeta_mpr_widget:
            mpr_active = True
            mpr_widget = selected_widget._zeta_mpr_widget
            logger.info("Found _zeta_mpr_widget on selected_widget")
        elif hasattr(selected_widget, '_new_mpr_zeta_widget') and selected_widget._new_mpr_zeta_widget:
            mpr_active = True
            mpr_widget = selected_widget._new_mpr_zeta_widget
            logger.info("Found _new_mpr_zeta_widget on selected_widget")
        elif hasattr(selected_widget, '_original_widget'):
            # selected_widget itself IS the MPR widget (back-reference exists)
            mpr_active = True
            mpr_widget = selected_widget
            logger.info("selected_widget has _original_widget - it IS the MPR widget")
        
        # Also check tool_selected state
        tool_is_mpr = (self.tool_selected is not None and 
                    (self.tool_access.MPR in str(self.tool_selected) or 
                        getattr(self, '_new_mpr_zeta_active', False)))
        
        if mpr_active or tool_is_mpr:
            logger.info("Deactivating MPR (already active)")
            print("[DEACTIVATE] Closing MPR and restoring original viewer...", file=sys.stderr, flush=True)
            
            self.tool_selected = None
            if hasattr(self, '_new_mpr_zeta_active'):
                self._new_mpr_zeta_active = False
            
            try:
                # Determine the original widget to restore
                original_widget = selected_widget
                
                if hasattr(selected_widget, '_original_widget'):
                    # Case: selected_widget is the MPR widget itself
                    original_widget = selected_widget._original_widget
                    logger.info(f"Restoring from MPR widget back-reference: {original_widget}")
                elif mpr_widget and mpr_widget != selected_widget:
                    # Case: selected_widget is the original, mpr_widget is the MPR
                    original_widget = selected_widget
                    logger.info(f"Restoring using selected_widget as original: {original_widget}")
                
                # Call the restoration method
                self._restore_selected_viewer(original_widget)
                print("[DEACTIVATE] Original viewer restored successfully", file=sys.stderr, flush=True)
                
            except Exception as e:
                logger.error(f"Error restoring viewer: {e}", exc_info=True)
                print(f"[DEACTIVATE] ERROR restoring viewer: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)
                
            self.handle_buttons_checked()
            print("MPR deactivated successfully", file=sys.stderr, flush=True)
            logger.info("MPR deactivated successfully")
            logger.info("=" * 80)
            return

        # ==================== ACTIVATION CODE ====================
        logger.info("Activating MPR")
        print("[ACTIVATE] Opening MPR viewer...", file=sys.stderr, flush=True)
        self.check_and_deactivate_tools()

        if selected_widget is None:
            print("ERROR: selected_widget is None!", file=sys.stderr, flush=True)
            logger.error("selected_widget is None! Cannot open MPR viewer.")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.patient_widget, "MPR Viewer", "Please select a viewer first.")
            return

        # Get VTK image data - reuse last MPR series if available
        try:
            # PRIORITY 1: Check if we have a previous MPR series to reopen
                if self.last_mpr_series_index is not None and self.last_mpr_vtk_data is not None:
                    logger.info(f"🔄 Reopening MPR with last series: {self.last_mpr_series_index}")
                    series_index = self.last_mpr_series_index
                    vtk_image_data = self.last_mpr_vtk_data
                    dicom_directory = self.last_mpr_dicom_directory
                    window_width = self.last_mpr_window_width
                    window_center = self.last_mpr_window_center
                    
                    # Jump to creating MPR (skip series lookup)
                    logger.info(f"✓ Using cached MPR data: dir={dicom_directory}, W={window_width}, C={window_center}")
                    self._replace_selected_viewport_with_mpr(selected_widget, vtk_image_data, dicom_directory, window_width, window_center)
                    self.tool_selected = self.tool_access.MPR
                    self.handle_buttons_checked()
                    logger.info("✓ MPR reopened with last series successfully")
                    return
                
                # PRIORITY 2: No previous MPR series, use current viewport's series
                # Check if widget has image data
                logger.info(f"Checking selected_widget attributes...")
                logger.info(f"hasattr(selected_widget, 'last_series_show'): {hasattr(selected_widget, 'last_series_show')}")
                
                if not hasattr(selected_widget, 'last_series_show'):
                    logger.warning("No series loaded in selected viewport")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self.patient_widget, "MPR Viewer", "No series loaded in selected viewport.")
                    return

                series_index = selected_widget.last_series_show
                logger.info(f"Series index from viewport: {series_index}")

                # Find the VTK image data AND series path for this series
                vtk_image_data = None
                dicom_directory = None
                window_width = None
                window_center = None
                logger.info(f"🔍 Searching in {len(self.patient_widget.lst_thumbnails_data)} thumbnail data entries...")
                
                for i in range(len(self.patient_widget.lst_thumbnails_data)):
                    try:
                        thumbnail_data = self.patient_widget.lst_thumbnails_data[i]
                        metadata = thumbnail_data.get('metadata', {})
                        series_metadata = metadata.get('series', {})
                        series_num = int(series_metadata.get('series_number', -1))
                        
                        logger.info(f"   [{i}] series_number={series_num}, looking for {series_index}")
                        
                        if series_num == int(series_index):
                            vtk_image_data = thumbnail_data.get('vtk_image_data')
                            
                            # Method 1: Try to get series_path directly
                            dicom_directory = series_metadata.get('series_path')
                            logger.info(f"   ✅ MATCH! series_path from metadata: {dicom_directory}")
                            
                            # Method 2: If series_path is None, get it from first instance path
                            instances = metadata.get('instances', [])
                            if instances and len(instances) > 0:
                                first_instance = instances[0]
                                if not dicom_directory:
                                    first_instance_path = first_instance.get('instance_path')
                                    if first_instance_path:
                                        dicom_directory = os.path.dirname(first_instance_path)
                                        logger.info(f"   ✅ Got directory from instance_path: {dicom_directory}")
                                
                                # Get window/level from first instance
                                window_width = first_instance.get('window_width')
                                window_center = first_instance.get('window_center')
                                logger.info(f"   ✅ Got W/L from instance: W={window_width}, C={window_center}")
                            
                            logger.info(f"   🎯 Final DICOM directory: {dicom_directory}")
                            break
                    except (KeyError, ValueError, TypeError) as e:
                        logger.debug(f"   [ERROR] checking thumbnail data at index {i}: {e}")
                        continue

                if vtk_image_data is None:
                    logger.warning(f"No image data available for MPR viewer (series_index: {series_index})")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(self.patient_widget, "MPR Viewer", f"No image data available for series {series_index}.")
                    return

                logger.info(f"vtk_image_data found: {vtk_image_data}")
                logger.info(f"vtk_image_data type: {type(vtk_image_data)}")
                if hasattr(vtk_image_data, 'GetDimensions'):
                    logger.info(f"vtk_image_data dimensions: {vtk_image_data.GetDimensions()}")

                # Store this series data for future reopen
                self.last_mpr_series_index = series_index
                self.last_mpr_vtk_data = vtk_image_data
                self.last_mpr_dicom_directory = dicom_directory
                self.last_mpr_window_width = window_width
                self.last_mpr_window_center = window_center
                logger.info(f"✓ Stored MPR series for reopen: {series_index}")

                # Replace ONLY the selected viewport with MPR
                import sys
                print("Calling _replace_selected_viewport_with_mpr...", file=sys.stderr, flush=True)
                logger.info("Calling _replace_selected_viewport_with_mpr...")
                logger.info(f"Passing dicom_directory: {dicom_directory}")
                logger.info(f"Passing W/L: W={window_width}, C={window_center}")
                try:
                    self._replace_selected_viewport_with_mpr(selected_widget, vtk_image_data, dicom_directory, window_width, window_center)
                    print("_replace_selected_viewport_with_mpr completed successfully", file=sys.stderr, flush=True)
                    logger.info("_replace_selected_viewport_with_mpr completed")
                except Exception as e:
                    print(f"ERROR in _replace_selected_viewport_with_mpr: {e}", file=sys.stderr, flush=True)
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    raise

            except Exception as e:
                logger.error(f"Error opening MPR viewer: {e}", exc_info=True)
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self.patient_widget, "MPR Viewer Error", f"Error opening MPR viewer:\n{str(e)}")
                return

            self.tool_selected = self.tool_access.MPR
            self.handle_buttons_checked()
            logger.info("✓ MPR opened with toggle - data cached for reopen")
            logger.info("=" * 80)
        """

        try:
            if not hasattr(selected_widget, 'last_series_show') or selected_widget.last_series_show is None:
                logger.warning("No series loaded in selected viewport")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.patient_widget, "MPR Viewer", "No series loaded in selected viewport.")
                return

            # ✅ FIX: Use last_series_show as INDEX (not series number)
            active_series_index = selected_widget.last_series_show
            logger.info(f"Active series index: {active_series_index}")
            
            # Validate index
            total_thumbnails = len(self.patient_widget.lst_thumbnails_data)
            if active_series_index < 0 or active_series_index >= total_thumbnails:
                logger.error(f"Invalid index: {active_series_index}")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.patient_widget, "Error", f"Invalid series index: {active_series_index}")
                return
            
            # Get data directly by index
            thumbnail_data = self.patient_widget.lst_thumbnails_data[active_series_index]
            vtk_image_data = thumbnail_data.get('vtk_image_data')
            metadata = thumbnail_data.get('metadata', {})
            series_metadata = metadata.get('series', {})
            
            series_number = series_metadata.get('series_number', 'Unknown')
            logger.info(f"   ✅ Found series at index {active_series_index}, series_number={series_number}")

            if vtk_image_data is None:
                logger.warning(f"No image data available at index {active_series_index}")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self.patient_widget, "MPR Viewer", f"No image data available.")
                return

            logger.info(f"vtk_image_data found: {vtk_image_data}")
            
            # Get DICOM directory and window/level from this specific series
            dicom_directory = series_metadata.get('series_path')
            window_width = None
            window_center = None
            
            instances = metadata.get('instances', [])
            if instances and len(instances) > 0:
                first_instance = instances[0]
                if not dicom_directory:
                    first_instance_path = first_instance.get('instance_path')
                    if first_instance_path:
                        dicom_directory = os.path.dirname(first_instance_path)
                window_width = first_instance.get('window_width')
                window_center = first_instance.get('window_center')
                logger.info(f"   DICOM directory: {dicom_directory}")
                logger.info(f"   Window/Level: {window_width}/{window_center}")

            print("Calling _replace_selected_viewport_with_mpr...", file=sys.stderr, flush=True)
            self._replace_selected_viewport_with_mpr(
                selected_widget, 
                vtk_image_data, 
                dicom_directory, 
                window_width, 
                window_center
            )
            print("_replace_selected_viewport_with_mpr completed successfully", file=sys.stderr, flush=True)

        except Exception as e:
            logger.error(f"Error opening MPR viewer: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self.patient_widget, "MPR Viewer Error", f"Error opening MPR viewer:\n{str(e)}")
            import traceback
            traceback.print_exc(file=sys.stderr)
            return

        self.tool_selected = self.tool_access.MPR
        self.handle_buttons_checked()
        logger.info("MPR toggle completed successfully")
        logger.info("=" * 80)

    def _replace_selected_viewport_with_mpr_DEPRECATED(self, selected_widget, vtk_image_data, dicom_directory=None, window_width=None, window_center=None):
        """
        DEPRECATED: This method used the old MprViewer module which has been removed.
        This method is kept for reference only and will be removed in a future version.
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.warning("_replace_selected_viewport_with_mpr called but this is deprecated and does nothing.")
        return
        
        # OLD CODE COMMENTED OUT - KEPT FOR REFERENCE
        """
        Replace the selected viewport with MPR viewer
        
        Args:
            selected_widget: The VTK widget to replace with MPR viewer
            vtk_image_data: VTK image data (used as fallback if dicom_directory is None)
            dicom_directory: Path to DICOM series directory (preferred method for correct orientation)
            window_width: Window width for display
            window_center: Window center for display
        
        import logging
        import sys
        import os
        logger = logging.getLogger(__name__)
        
        print("=" * 80, file=sys.stderr, flush=True)
        print("_replace_selected_viewport_with_mpr CALLED", file=sys.stderr, flush=True)
        print(f"selected_widget: {selected_widget}", file=sys.stderr, flush=True)
        print(f"vtk_image_data: {vtk_image_data}", file=sys.stderr, flush=True)
        print(f"dicom_directory (passed): {dicom_directory}", file=sys.stderr, flush=True)
        print(f"window_width (passed): {window_width}", file=sys.stderr, flush=True)
        print(f"window_center (passed): {window_center}", file=sys.stderr, flush=True)
        
        # Get series_index from selected_widget
        series_index = selected_widget.last_series_show
        print(f"   Series index from widget: {series_index}", file=sys.stderr, flush=True)
        print(f"🎯 Final dicom_directory: {dicom_directory}", file=sys.stderr, flush=True)
        logger.info(f"   Using W/L: W={window_width}, C={window_center}")
        
        # Import and create MPR viewer
        print("Importing MprViewerWrapper...", file=sys.stderr, flush=True)
        from PacsClient.pacs.patient_tab.MprViewer.MprViewerWrapper import MprViewerWrapper
        print("MprViewerWrapper imported successfully", file=sys.stderr, flush=True)
        
        # Get parent widget and layout
        print("Getting parent widget...", file=sys.stderr, flush=True)
        parent_widget = selected_widget.parent()
        print(f"parent_widget: {parent_widget}", file=sys.stderr, flush=True)
        
        print("Getting parent layout...", file=sys.stderr, flush=True)
        parent_layout = parent_widget.layout()
        print(f"parent_layout: {parent_layout}", file=sys.stderr, flush=True)
        
        # Hide the original widget
        print("Hiding original widget...", file=sys.stderr, flush=True)
        selected_widget.setVisible(False)
        
        # Create MPR widget WITH PARENT to avoid popup window
        print("Creating MprViewerWrapper...", file=sys.stderr, flush=True)
        try:
            # Define callback to restore original viewer when MPR is closed
            def restore_original_viewer_callback():
                self._restore_selected_viewer(selected_widget)

            # Pass dicom_directory (preferred) AND vtk_image_data (fallback)
            # Also pass window/level if available and the close callback
            mpr_widget = MprViewerWrapper(
                vtk_image_data=vtk_image_data,
                dicom_directory=dicom_directory,
                parent=parent_widget,
                window_width=window_width,
                window_center=window_center,
                close_callback=restore_original_viewer_callback
            )
            print("MprViewerWrapper created successfully", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"ERROR creating MprViewerWrapper: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            raise
        
        # Add the MPR widget to the layout where the original widget was
        print("Adding MPR widget to grid at position (0, 0)...", file=sys.stderr, flush=True)
        print(f"mpr_widget parent before addWidget: {mpr_widget.parent()}", file=sys.stderr, flush=True)
        print(f"mpr_widget isVisible before addWidget: {mpr_widget.isVisible()}", file=sys.stderr, flush=True)
        
        parent_layout.addWidget(mpr_widget, 0, 0)
        print("MPR widget added to layout", file=sys.stderr, flush=True)
        
        print(f"mpr_widget parent after addWidget: {mpr_widget.parent()}", file=sys.stderr, flush=True)
        print(f"mpr_widget size: {mpr_widget.size()}", file=sys.stderr, flush=True)
        print(f"mpr_widget isVisible: {mpr_widget.isVisible()}", file=sys.stderr, flush=True)
        
        # Show and update the MPR widget
        mpr_widget.show()
        mpr_widget.update()
        parent_widget.update()
        print("MPR widget shown and updated", file=sys.stderr, flush=True)
        
        # Store reference to MPR widget for later restoration
        selected_widget._mpr_widget = mpr_widget
        selected_widget._original_visible = True
        
        logger.info(f"MPR viewer replaced viewport at grid position (0, 0)")
        print(f"MPR viewer replaced viewport at grid position (0, 0)", file=sys.stderr, flush=True)
        print("_replace_selected_viewport_with_mpr completed successfully", file=sys.stderr, flush=True)
        """

    def toggle_curved_mpr(self, selected_widget):
        """Toggle Curved MPR mode for vessel/airway visualization"""
        import logging
        from PySide6.QtWidgets import QMessageBox
        logger = logging.getLogger(__name__)

        if self.tool_selected == self.tool_access.CURVED_MPR:  # deactivate tool
            # Disable curved MPR mode in viewer
            if hasattr(selected_widget, 'image_viewer') and selected_widget.image_viewer:
                selected_widget.image_viewer.enable_curved_mpr_mode(False)
            
            self.tool_selected = None
            self.handle_buttons_checked()
            logger.info("Curved MPR mode deactivated")
            return

        try:
            # Check if widget has image data
            if not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                logger.warning("No image loaded in selected viewport")
                QMessageBox.warning(
                    self.patient_widget,
                    "No Image",
                    "Please load an image first for Curved MPR"
                )
                return

            # Show instruction message
            QMessageBox.information(
                self.patient_widget,
                "Curved MPR Mode",
                "Curved MPR mode activated!\n\n"
                "Instructions:\n"
                "1. Click points along vessel/airway/dental arch centerline\n"
                "2. Press 'G' to generate curved MPR\n"
                "3. Press 'C' to clear points\n"
                "4. Press ESC to exit mode\n\n"
                "Tip: Works for vessel straightening, airway visualization, dental panoramic view"
            )

            self.check_and_deactivate_tools()
            
            # Actually enable curved MPR mode in viewer
            selected_widget.image_viewer.enable_curved_mpr_mode(True)
            
            self.tool_selected = self.tool_access.CURVED_MPR
            self.handle_buttons_checked()

            logger.info("Curved MPR mode activated")

        except Exception as e:
            logger.error(f"Error activating Curved MPR: {e}", exc_info=True)
            QMessageBox.critical(
                self.patient_widget,
                "Error",
                f"Error activating Curved MPR:\n{str(e)}"
            )

    def _restore_original_volume(self, selected_widget):
        try:
            image_viewer = getattr(selected_widget, 'image_viewer', None)
            if image_viewer is None:
                return
            original_data = getattr(selected_widget, '_original_image_data', None)
            if original_data is None:
                return

            current_slice = getattr(selected_widget, '_original_slice', None)
            image_viewer.vtk_image_data = original_data
            image_viewer.image_reslice.SetInputData(original_data)
            image_viewer.image_reslice.Update()
            image_viewer.color_mapper.SetInputConnection(image_viewer.image_reslice.GetOutputPort())
            image_viewer.color_mapper.Update()
            image_viewer.SetInputData(image_viewer.image_reslice.GetOutput())
            image_viewer.UpdateDisplayExtent()

            if current_slice is not None:
                image_viewer.SetSlice(current_slice)

            image_viewer.update_corners_actors()
            image_viewer.GetRenderer().ResetCameraClippingRange()
            image_viewer.Render()

            selected_widget._mip_mode = None
            self.tool_selected = None
        except Exception:
            pass

        self.handle_buttons_checked()

    def toggle_segmentation(self, selected_widget):
        """Toggle Advanced Segmentation Tools panel"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Toggle the Advanced Tools Panel visibility
            if hasattr(self.patient_widget, 'advanced_tools_panel'):
                panel = self.patient_widget.advanced_tools_panel

                # Switch to the Advanced Tools tab in right panel
                if hasattr(self.patient_widget, 'right_panel'):
                    # Find index of advanced_tools_panel
                    for i in range(self.patient_widget.right_panel.count()):
                        if self.patient_widget.right_panel.widget(i) == panel:
                            self.patient_widget.right_panel.setCurrentIndex(i)
                            logger.info("Switched to Advanced Tools Panel")
                            break

                    # Activate Segmentation tab in the panel
                    if hasattr(panel, 'tab_widget'):
                        # Find the segmentation tab
                        for i in range(panel.tab_widget.count()):
                            if "Segmentation" in panel.tab_widget.tabText(i):
                                panel.tab_widget.setCurrentIndex(i)
                                logger.info("Switched to Segmentation tab")
                                break

                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self.patient_widget,
                    "Segmentation Tools",
                    "Advanced Segmentation Tools Opened!\n\n"
                    "Available tools:\n"
                    "• Lung Segmentation\n"
                    "• Airway Tree Extraction\n"
                    "• Vessel Segmentation\n"
                    "• Bone Segmentation\n\n"
                    "Find tools in the right panel."
                )
            else:
                logger.warning("Advanced Tools Panel not available")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self.patient_widget,
                    "Not Available",
                    "Advanced Segmentation Tools panel is not available.\n"
                    "Please check your installation."
                )

            self.handle_buttons_checked()

        except Exception as e:
            logger.error(f"Error opening Segmentation Tools: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                self.patient_widget,
                "Error",
                f"Error opening Segmentation Tools:\n{str(e)}"
            )

    def toggle_upload_attachments(self, selected_widget):
        study_uid = self.patient_widget.study_uid
        print('study_uid:', study_uid)

        if self.tool_selected == self.tool_access.UPLOAD:
            self.tool_selected = None

            self.handle_buttons_checked()

        else:
            attachments_uploaded = get_attachments_uploaded(study_uid)

            self.check_and_deactivate_tools()

            Thread(target=upload_attachments_for_study, args=(study_uid, attachments_uploaded)).start()
            # upload_attachments_for_study(study_uid=study_uid, attachments_uploaded=attachments_uploaded)

            self.tool_selected = self.tool_access.UPLOAD
            self.handle_buttons_checked()
            self.check_and_deactivate_tools()

            self.patient_widget.close_and_remove_patient_tab()  # close patient tab

    def _restore_selected_viewer(self, selected_widget):
        """Restore the original viewport"""
        import logging
        logger = logging.getLogger(__name__)
        
        # Find MPR widget (handle different MPR implementations)
        mpr_widget = None
        original_widget = selected_widget
        
        # Case 1: selected_widget has _mpr_widget attribute (MprViewerWrapper)
        if hasattr(selected_widget, '_mpr_widget'):
            mpr_widget = selected_widget._mpr_widget
            
        # Case 2: selected_widget has _zeta_mpr_widget attribute (StandardMPRViewer/Zeta)
        elif hasattr(selected_widget, '_zeta_mpr_widget'):
            mpr_widget = selected_widget._zeta_mpr_widget
            
        # Case 3: selected_widget itself is the MPR widget (toolbar_integration pattern)
        elif hasattr(selected_widget, '_original_widget'):
            mpr_widget = selected_widget
            original_widget = selected_widget._original_widget
        
        if mpr_widget:
            logger.info(f"Restoring viewer: MPR widget found {type(mpr_widget).__name__}")
            
            # CRITICAL: Cleanup VTK resources BEFORE deleteLater()
            try:
                if hasattr(mpr_widget, 'cleanup'):
                    logger.info("Calling mpr_widget.cleanup() before deleteLater...")
                    mpr_widget.cleanup()
                    logger.info("mpr_widget.cleanup() completed")
            except Exception as e:
                logger.error(f"Error during MPR cleanup: {e}", exc_info=True)
            
            # CRITICAL: Remove MPR from layout before deleteLater
            try:
                parent = mpr_widget.parent()
                if parent:
                    parent_layout = parent.layout()
                    if parent_layout:
                        parent_layout.removeWidget(mpr_widget)
                        logger.info("MPR widget removed from layout")
            except Exception as e:
                logger.error(f"Error removing MPR from layout: {e}", exc_info=True)
            
            # Hide and schedule deletion
            mpr_widget.hide()
            mpr_widget.setParent(None)  # Remove parent to ensure complete cleanup
            mpr_widget.deleteLater()
            
            # Clean up references
            if hasattr(original_widget, '_mpr_widget'):
                delattr(original_widget, '_mpr_widget')
            if hasattr(original_widget, '_zeta_mpr_widget'):
                delattr(original_widget, '_zeta_mpr_widget')
            if hasattr(original_widget, '_new_mpr_zeta_widget'):
                delattr(original_widget, '_new_mpr_zeta_widget')
            if hasattr(mpr_widget, '_original_widget'):
                delattr(mpr_widget, '_original_widget')

        # CRITICAL: Re-add original widget to layout
        # When MPR was added, it displaced the original widget from layout
        try:
            parent = original_widget.parent()
            if parent:
                parent_layout = parent.layout()
                if parent_layout:
                    # Remove from layout first (in case it's still there)
                    parent_layout.removeWidget(original_widget)
                    # Re-add at saved grid position if available
                    grid_position = getattr(original_widget, '_mpr_grid_position', None)
                    if grid_position:
                        row, col, row_span, col_span = grid_position
                        parent_layout.addWidget(original_widget, row, col, row_span, col_span)
                        logger.info(f"Original widget re-added to layout at ({row}, {col})")
                        try:
                            delattr(original_widget, '_mpr_grid_position')
                        except Exception:
                            pass
                    else:
                        parent_layout.addWidget(original_widget, 0, 0)
                        logger.info("Original widget re-added to layout at (0,0)")
        except Exception as e:
            logger.error(f"Error re-adding original widget to layout: {e}", exc_info=True)

        # Show original widget
        original_widget.show()
        original_widget.setVisible(True)
        original_widget.setEnabled(True)
        
        # Force update
        try:
            original_widget.update()
            if original_widget.parent():
                original_widget.parent().update()
        except:
            pass

        # Clean up other references
        if hasattr(original_widget, '_mpr_backup_widget'):
            delattr(original_widget, '_mpr_backup_widget')
        if hasattr(original_widget, '_original_visible'):
            delattr(original_widget, '_original_visible')
            
        # Reset tool state if needed
        if hasattr(self, '_new_mpr_zeta_active'):
            self._new_mpr_zeta_active = False
            
        logger.info("Original viewer restored successfully")


    def handle_buttons_checked(self):
        def _is_tool_active(tool_name: str) -> bool:
            if self.tool_selected == tool_name:
                return True
            if isinstance(self.tool_selected, str):
                parts = [part.strip() for part in self.tool_selected.split(',') if part.strip()]
                return tool_name in parts
            return False

        for tool_name, tool_btn in self.tools_button.items():
            try:
                tool_btn: QPushButton
                tool_btn.setChecked(_is_tool_active(tool_name))
            except Exception:
                pass

        try:
            if hasattr(self, '_measurement_menu_btn'):
                is_measurement_active = any(_is_tool_active(tool) for tool in self.measurement_tools)
                self._measurement_menu_btn.setChecked(is_measurement_active)
        except Exception:
            pass

        try:
            if hasattr(self, '_mpr_menu_btn'):
                is_mpr_dropdown_active = any(_is_tool_active(tool) for tool in self.mpr_dropdown_tools)
                self._mpr_menu_btn.setChecked(is_mpr_dropdown_active)
        except Exception:
            pass

        # Keep MPR button green if any MPR viewer is active
        try:
            mpr_btn = self.tools_button.get(self.tool_access.MPR)
            if mpr_btn:
                mpr_btn.setChecked(_is_tool_active(self.tool_access.MPR) or self._is_any_mpr_open())
        except Exception:
            pass

    def _is_any_mpr_open(self):
        try:
            for node in self.patient_widget.lst_nodes_viewer:
                widget = getattr(node, 'vtk_widget', None)
                if widget is None:
                    continue
                if hasattr(widget, '_zeta_mpr_widget') and widget._zeta_mpr_widget:
                    return True
                if hasattr(widget, '_new_mpr_zeta_widget') and widget._new_mpr_zeta_widget:
                    return True
            if self.is_mpr_viewer(getattr(self.patient_widget, 'selected_widget', None)):
                return True
        except Exception:
            pass
        return False

    def check_and_deactivate_tools(self):
        self._debug_target(
            f"check_and_deactivate_tools: tool_selected={self.tool_selected}, "
            f"sync_enabled={getattr(self, '_sync_point_enabled', False)}"
        )
        # Always deactivate the click-to-target interactor when switching tools.
        # When Lock Sync is active, patient_widget.toggle_sync_point(False) will
        # remove the interactor/cursor/observers but keep the sync pipeline alive.
        if getattr(self, '_sync_point_enabled', False):
            self.toggle_sync_point(False)
            # continue to handle any other active tool states

        if self.tool_selected is None:  # it's mean we haven't selected tool before
            return

        # when we switch between two tools and hasn't deactivated first tool
        elif self.tool_selected == self.tool_access.MPR:
            self.toggle_zeta_mpr()  # deactivate Zeta MPR

        elif self.tool_selected == self.tool_access.RULER:
            # self.toggle_ruler()  # deactivate ruler
            self.toggle_ruler(self.patient_widget.selected_widget)  # deactivate ruler

        elif self.tool_selected == self.tool_access.ERASER:
            # self.toggle_eraser()  # deactivate eraser
            self.toggle_eraser(self.patient_widget.selected_widget)  # deactivate eraser

        elif self.tool_selected == self.tool_access.RESET:
            self.toggle_reset_selected_widget(self.patient_widget.selected_widget)  # deactivate reset image

        elif self.tool_selected == self.tool_access.ANGLE:
            self.toggle_angle(self.patient_widget.selected_widget)  # deactivate angle

        elif self.tool_selected == self.tool_access.TWO_LINE_ANGLE:
            self.toggle_two_line_angle(self.patient_widget.selected_widget)  # deactivate two-line angle

        elif self.tool_selected == self.tool_access.ARROW:
            self.toggle_arrow(self.patient_widget.selected_widget)  # deactivate arrow

        elif self.tool_selected == self.tool_access.TEXT:
            self.toggle_text(self.patient_widget.selected_widget)  # deactivate arrow

        elif self.tool_selected == self.tool_access.ZOOM_TO_FIT:
            self.toggle_zoom_to_fit(self.patient_widget.selected_widget)  # deactivate zoom to fit

        elif self.tool_selected == self.tool_access.ZOOM:
            self.toggle_zoom(self.patient_widget.selected_widget)  # deactivate zoom

        elif self.tool_selected == self.tool_access.WINDOW_LEVEL:
            self.toggle_window_level(self.patient_widget.selected_widget)  # deactivate zoom

        elif self.tool_selected == self.tool_access.PAN:
            self.toggle_pan(self.patient_widget.selected_widget)  # deactivate zoom

        elif self.tool_selected == self.tool_access.STACKED:
            self.toggle_stacked(self.patient_widget.selected_widget)  # deactivate stacked

        elif self.tool_selected == self.tool_access.MIP:
            self.toggle_mip(self.patient_widget.selected_widget)

        elif self.tool_selected == self.tool_access.MINIP:
            self.toggle_minip(self.patient_widget.selected_widget)

        elif self.tool_selected == self.tool_access.THICK_SLAB:
            self.toggle_thick_slab(self.patient_widget.selected_widget)

        elif self.tool_selected == self.tool_access.ROTATION_LEFT:
            self.toggle_rotation_left(self.patient_widget.selected_widget)  # deactivate rotation left

        elif self.tool_selected == self.tool_access.ROTATION_RIGHT:
            self.toggle_rotation_right(self.patient_widget.selected_widget)  # deactivate rotation right

        elif self.tool_selected == self.tool_access.FLIP_HORIZONTAL:
            self.toggle_flip_horizontal(self.patient_widget.selected_widget)  # deactivate Flip Horizontal

        elif self.tool_selected == self.tool_access.FLIP_VERTICAL:
            self.toggle_flip_vertical(self.patient_widget.selected_widget)  # deactivate Flip Vertical

        elif self.tool_selected == self.tool_access.CAPTURE:
            self.toggle_capture(self.patient_widget.selected_widget)  # deactivate Flip Vertical

        elif self.tool_selected == self.tool_access.MICROPHONE:
            # (We don't add mic to check_and_deactivate_tools. because we won't turn off mic when viewer changed)
            pass

        elif self.tool_selected == self.tool_access.TARGET:
            self.toggle_sync_point(False)

        elif self.tool_selected == self.tool_access.ROI:
            self.toggle_roi(self.patient_widget.selected_widget)  # deactivate Flip Vertical

        elif self.tool_selected == self.tool_access.CURVED_MPR:
            self.toggle_curved_mpr(self.patient_widget.selected_widget)

        elif self.tool_selected == self.tool_access.CIRCLE_ROI:
            self.toggle_circle_roi(self.patient_widget.selected_widget)

        elif self.tool_selected == self.tool_access.AI_CHAT:
            self.toggle_ai_chat(self.patient_widget.selected_widget)  # deactivate AI Chat

        # # MPR should only be toggled by its own button, not by other tools
        # elif self.tool_selected == self.tool_access.MPR:
        #     self.toggle_mpr(self.patient_widget.selected_widget)  # deactivate MPR

        elif self.tool_selected == self.tool_access.UPLOAD:
            self.toggle_upload_attachments(self.patient_widget.selected_widget)

    def get_tool_activated_method(self):
        if self.tool_selected is None:  # it's mean we haven't selected tool before
            return None

        # when we switch between two tools and hasn't deactivated first tool
        elif self.tool_selected == self.tool_access.RULER:
            return self.toggle_ruler

        elif self.tool_selected == self.tool_access.ERASER:
            return self.toggle_eraser

        elif self.tool_selected == self.tool_access.RESET:
            return self.toggle_reset_selected_widget

        elif self.tool_selected == self.tool_access.ANGLE:
            return self.toggle_angle

        elif self.tool_selected == self.tool_access.ARROW:
            return self.toggle_arrow

        elif self.tool_selected == self.tool_access.TEXT:
            return self.toggle_text

        elif self.tool_selected == self.tool_access.ZOOM:
            return self.toggle_zoom

        elif self.tool_selected == self.tool_access.WINDOW_LEVEL:
            return self.toggle_window_level

        elif self.tool_selected == self.tool_access.PAN:
            return self.toggle_pan

        elif self.tool_selected == self.tool_access.STACKED:
            return self.toggle_stacked

        elif self.tool_selected == self.tool_access.ROTATION_LEFT:
            return self.toggle_rotation_left

        elif self.tool_selected == self.tool_access.ROTATION_RIGHT:
            return self.toggle_rotation_right

        elif self.tool_selected == self.tool_access.FLIP_HORIZONTAL:
            return self.toggle_flip_horizontal

        elif self.tool_selected == self.tool_access.FLIP_VERTICAL:
            return self.toggle_flip_vertical

        elif self.tool_selected == self.tool_access.CAPTURE:
            return self.toggle_capture

        elif self.tool_selected == self.tool_access.ROI:
            return self.toggle_roi

        elif self.tool_selected == self.tool_access.CIRCLE_ROI:
            return self.toggle_circle_roi

        # elif self.tool_selected == self.tool_access.AI_CHAT:
        #     return self.toggle_ai_chat

        elif self.tool_selected == self.tool_access.MPR:
            return self.toggle_mpr

    def _create_separator(self):
        """Helper method to create a thin vertical separator with spacing"""
        # Create a container with spacing
        separator_container = QWidget()
        separator_container.setFixedWidth(24)  # Total spacing: 10px + 1px + 10px = 21px
        separator_container.setStyleSheet("background: transparent;")  # Match toolbar background

        # Create thin line in the center
        separator_layout = QHBoxLayout(separator_container)
        separator_layout.setContentsMargins(11, 2, 11, 2)  # 11px margin on each side
        separator_layout.setSpacing(0)

        separator_line = QWidget()
        separator_line.setFixedWidth(1)  # Thin line
        separator_line.setStyleSheet("""
            QWidget {
                background-color: #4b5563;
                border: none;
            }
        """)

        separator_layout.addWidget(separator_line)
        return separator_container
        

        
    def add_toolbar_actions(self, toolbar: QToolBar):
        # تنظیم toolbar اصلی
        toolbar.setMovable(False)
        toolbar.setStyleSheet("""
            QToolBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
                border: none;
                padding: 0px;
                spacing: 0px;
            }
        """)
        
        # ایجاد یک ویجت اصلی که دو بخش دارد
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # بخش 1: محتوای toolbar
        content_widget = QWidget()
        content_widget.setMinimumHeight(48)
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 2, 5, 2)
        content_layout.setSpacing(4)
        
        # بخش 2: اسکرول‌بار (جداگانه)
        scrollbar_widget = QWidget()
        scrollbar_widget.setFixedHeight(16)  # ارتفاع ثابت برای اسکرول‌بار
        scrollbar_widget.setStyleSheet("background: transparent;")
        
        # ایجاد QScrollArea برای بخش محتوا
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # همیشه نمایش بده
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        # استایل بسیار ساده برای QScrollArea
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
                padding: 0px;
            }
            QScrollArea > QWidget > QWidget {
                /* داخلی‌ترین ویجت */
                padding: 0px;
            }
        """)
        
        # تنظیم scrollbar به صورت دستی (اینجا کنترل کامل داریم)
        horizontal_scrollbar = scroll_area.horizontalScrollBar()
        horizontal_scrollbar.setStyleSheet("""
            QScrollBar:horizontal {
                border: none;
                background: #1f2937;
                height: 12px;
                border-radius: 6px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #4b5563;
                min-width: 40px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #6b7280;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                width: 0px;
                height: 0px;
            }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)   

            # تنظیم content_widget به عنوان ویجت scroll_area
        scroll_area.setWidget(content_widget)
        
        # اضافه کردن scroll_area به layout اصلی
        main_layout.addWidget(scroll_area)
        
        # اضافه کردن main_widget به toolbar
        toolbar.addWidget(main_widget)     
        # ایجاد یک ویجت container برای تمام محتوای نوار ابزار
        toolbar_container = QWidget()
        toolbar_container.setStyleSheet("background: transparent;")
        toolbar_container.setMinimumHeight(48)  # ارتفاع container
        
        # ایجاد یک layout افقی برای کل نوار ابزار
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(5, 2, 5, 2)
        toolbar_layout.setSpacing(4)
        toolbar_layout.setAlignment(Qt.AlignTop)  # دکمه‌ها را در بالا قرار می‌دهد        
        # ایجاد یک ویجت container برای تمام محتوای نوار ابزار
        toolbar_container = QWidget()
        toolbar_container.setStyleSheet("background: transparent;")
        
        # ایجاد یک layout افقی برای کل نوار ابزار
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(5, 2, 5, 2)
        toolbar_layout.setSpacing(4)
        
        # ============================================================
        # LOGO SECTION
        # ============================================================
        logo_widget = QWidget()
        logo_widget.setFixedWidth(250)
        logo_widget.setFixedHeight(38)
        logo_layout = QHBoxLayout(logo_widget)
        logo_layout.setContentsMargins(8, 1, 8, 1)
        logo_layout.setSpacing(8)
        logo_layout.setAlignment(Qt.AlignCenter)

        # AI Logo
        logo_label = QLabel()
        logo_pixmap = QPixmap("PacsClient/login/images/aiLogo.png")
        if not logo_pixmap.isNull():
            logo_pixmap = logo_pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(logo_pixmap)
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)

        # AI PACS Text
        ai_text_label = QLabel("AI PACS")
        ai_text_label.setAlignment(Qt.AlignCenter)
        ai_text_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)

        # Description text
        desc_label = QLabel("Intelligent Medical Imaging")
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 9px;
                font-family: 'Roboto', sans-serif;
                font-weight: 400;
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)

        logo_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                border: 1px solid #4b5563;
                border-radius: 6px;
                margin: 1px;
            }
            QWidget:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
        """)

        logo_layout.addWidget(logo_label)
        logo_layout.addWidget(ai_text_label)
        logo_layout.addWidget(desc_label)
        toolbar_layout.addWidget(logo_widget)
        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 1: BASIC TOOLS (Reset & Layout)
        # ============================================================
        # Reset Selected button
        reset_selected_btn = create_tool_btn(self.patient_widget, 'Reset Selected', 'reset.png')
        reset_selected_btn.clicked.connect(
            lambda: self.toggle_reset_selected_widget(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(reset_selected_btn)
        self.tools_button[self.tool_access.RESET] = reset_selected_btn

        # Series layout button
        series_layout_btn = QToolButton()
        series_layout_btn.setToolTip('Series Layout')
        icon = QIcon(f"{ICON_PATH}/series-layout.png")
        series_layout_btn.setIcon(icon)
        series_layout_btn.setIconSize(QSize(20, 20))
        series_layout_btn.setPopupMode(QToolButton.InstantPopup)

        menu_matrix = QMenu(toolbar)
        matrix_selector = MatrixSelector(max_rows=3, max_cols=3, parent=menu_matrix)
        matrix_selector.set_method_change_viewers(self.patient_widget.apply_multi_viewer)

        widget_action = QWidgetAction(menu_matrix)
        widget_action.setDefaultWidget(matrix_selector)
        menu_matrix.addAction(widget_action)

        series_layout_btn.setMenu(menu_matrix)
        series_layout_btn.setStyleSheet("""
            QToolButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 4px 6px;
                margin: 1px;
                min-width: 36px;
                min-height: 36px;
                font-size: 11px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QToolButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QToolButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
        """)
        toolbar_layout.addWidget(series_layout_btn)
        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 2: MEASUREMENT TOOLS
        # ============================================================
        measurements_container = QWidget()
        measurements_layout = QHBoxLayout(measurements_container)
        measurements_layout.setContentsMargins(0, 0, 0, 0)
        measurements_layout.setSpacing(0)
        measurements_layout.setAlignment(Qt.AlignVCenter)

        measurements_menu_btn = QPushButton()
        measurements_menu_btn.setCheckable(True)
        measurements_menu_btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
        measurements_menu_btn.setIconSize(QSize(14, 14))
        measurements_menu_btn.setToolTip('View Angle/Arrow/Text/ROI')
        measurements_menu_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
                padding: 4px 2px;
                margin: 0px;
                min-width: 11px;
                min-height: 36px;
                max-width: 11px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                border-color: #10b981;
                color: #ffffff;
            }
        """)
        measurements_menu_btn.setCursor(Qt.PointingHandCursor)
        measurements_menu_btn.clicked.connect(lambda: self._show_measurements_dropdown(measurements_menu_btn))
        self._measurement_menu_btn = measurements_menu_btn

        # Ruler button
        ruler_btn = create_tool_btn(self.patient_widget, 'Ruler', 'ruler.png')
        ruler_btn.clicked.connect(lambda: self.toggle_ruler(self.patient_widget.selected_widget))
        ruler_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-left: none;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                padding: 4px 6px;
                margin: 0px;
                min-width: 36px;
                min-height: 36px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                border-color: #10b981;
                color: #ffffff;
            }
        """)

        measurements_layout.addWidget(measurements_menu_btn)
        measurements_layout.addWidget(ruler_btn)

        toolbar_layout.addWidget(measurements_container)
        self.tools_button[self.tool_access.RULER] = ruler_btn
        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 3: ANNOTATION TOOLS
        # ============================================================
        # Eraser button
        eraser_btn = create_tool_btn(self.patient_widget, 'Eraser', 'eraser.png')
        eraser_btn.clicked.connect(lambda: self.toggle_eraser(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(eraser_btn)
        self.tools_button[self.tool_access.ERASER] = eraser_btn
        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 4: VIEW MANIPULATION TOOLS
        # ============================================================
        # Zoom to fit button
        zoom_to_fit_btn = create_tool_btn(self.patient_widget, 'Zoom to Fit', 'fit.png')
        zoom_to_fit_btn.clicked.connect(lambda: self.toggle_zoom_to_fit(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(zoom_to_fit_btn)
        self.tools_button[self.tool_access.ZOOM_TO_FIT] = zoom_to_fit_btn

        # Zoom button
        zoom_btn = create_tool_btn(self.patient_widget, 'Zoom', 'zoom-in.png')
        zoom_btn.clicked.connect(lambda: self.toggle_zoom(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(zoom_btn)
        self.tools_button[self.tool_access.ZOOM] = zoom_btn

        # Window Level button
        window_level_btn = create_tool_btn(self.patient_widget, 'Window Level', 'contrast.png')
        window_level_btn.clicked.connect(lambda: self.toggle_window_level(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(window_level_btn)
        self.tools_button[self.tool_access.WINDOW_LEVEL] = window_level_btn

        # Pan button
        pan_btn = create_tool_btn(self.patient_widget, 'Pan', 'pan.png')
        pan_btn.clicked.connect(lambda: self.toggle_pan(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(pan_btn)
        self.tools_button[self.tool_access.PAN] = pan_btn

        # Stacked button
        stacked_btn = create_tool_btn(self.patient_widget, 'Stacked', 'layers.png')
        stacked_btn.clicked.connect(lambda: self.toggle_stacked(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(stacked_btn)
        self.tools_button[self.tool_access.STACKED] = stacked_btn
        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 5: IMAGE TRANSFORM TOOLS
        # ============================================================
        rotate_container = QWidget()
        rotate_layout = QHBoxLayout(rotate_container)
        rotate_layout.setContentsMargins(0, 0, 0, 0)
        rotate_layout.setSpacing(0)
        rotate_layout.setAlignment(Qt.AlignVCenter)

        rotate_menu_btn = QPushButton()
        rotate_menu_btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
        rotate_menu_btn.setIconSize(QSize(14, 14))
        rotate_menu_btn.setToolTip('Rotate / Flip')
        rotate_menu_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
                padding: 4px 2px;
                margin: 0px;
                min-width: 11px;
                min-height: 36px;
                max-width: 11px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
        """)
        rotate_menu_btn.setCursor(Qt.PointingHandCursor)
        rotate_menu_btn.clicked.connect(lambda: self._show_rotation_dropdown(rotate_menu_btn))

        rotation_right_btn = create_tool_btn(self.patient_widget, 'Rotate Right', 'rotate-cw.png')
        rotation_right_btn.clicked.connect(lambda: self.toggle_rotation_right(self.patient_widget.selected_widget))
        rotation_right_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-left: none;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                padding: 4px 6px;
                margin: 0px;
                min-width: 36px;
                min-height: 36px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                border-color: #10b981;
                color: #ffffff;
            }
        """)

        rotate_layout.addWidget(rotate_menu_btn)
        rotate_layout.addWidget(rotation_right_btn)
        toolbar_layout.addWidget(rotate_container)
        self.tools_button[self.tool_access.ROTATION_RIGHT] = rotation_right_btn

        # Sync container (hamburger dropdown + sync button)
        sync_container = QWidget()
        sync_layout = QHBoxLayout(sync_container)
        sync_layout.setContentsMargins(0, 0, 0, 0)
        sync_layout.setSpacing(0)
        sync_layout.setAlignment(Qt.AlignVCenter)

        sync_menu_btn = QPushButton()
        sync_menu_btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
        sync_menu_btn.setIconSize(QSize(14, 14))
        sync_menu_btn.setToolTip('Sync Options (Lock Sync)')
        sync_menu_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
                padding: 4px 2px;
                margin: 0px;
                min-width: 11px;
                min-height: 36px;
                max-width: 11px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
        """)
        sync_menu_btn.setCursor(Qt.PointingHandCursor)
        sync_menu_btn.clicked.connect(lambda: self._show_sync_dropdown(sync_menu_btn))
        self._sync_menu_btn = sync_menu_btn  # store for Lock Sync icon updates

        sync_btn = QPushButton(self.patient_widget)
        sync_btn.setCheckable(True)
        sync_btn.setToolTip('Sync Images')
        sync_btn.setCursor(Qt.PointingHandCursor)
        sync_btn.setIcon(qta.icon('fa5s.crosshairs', color='#e5e7eb'))
        sync_btn.setIconSize(QSize(20, 20))
        sync_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                border-left: none;
                padding: 4px 6px;
                margin: 0px;
                min-width: 36px;
                min-height: 36px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #dc2626, stop:1 #b91c1c);
                border-color: #ef4444;
                color: #ffffff;
            }
        """)
        sync_btn.clicked.connect(lambda checked=False: self.toggle_sync_point(checked))
        self.sync_point_button = sync_btn
        self.tools_button[self.tool_access.TARGET] = sync_btn

        sync_layout.addWidget(sync_menu_btn)
        sync_layout.addWidget(sync_btn)
        toolbar_layout.addWidget(sync_container)

        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 6: CAPTURE & AUDIO TOOLS
        # ============================================================
        # Capture button with menu
        capture_container = QWidget()
        capture_layout = QHBoxLayout(capture_container)
        capture_layout.setContentsMargins(0, 0, 0, 0)
        capture_layout.setSpacing(0)
        capture_layout.setAlignment(Qt.AlignVCenter)

        capture_menu_btn = QPushButton()
        capture_menu_btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
        capture_menu_btn.setIconSize(QSize(14, 14))
        capture_menu_btn.setToolTip('View Captured Images')
        capture_menu_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
                padding: 4px 2px;
                margin: 0px;
                min-width: 11px;
                min-height: 36px;
                max-width: 11px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
        """)
        capture_menu_btn.setCursor(Qt.PointingHandCursor)
        capture_menu_btn.clicked.connect(lambda: self._show_capture_dropdown(capture_menu_btn))

        capture_btn = BadgeButton(self.patient_widget)
        capture_btn.setCheckable(True)
        capture_btn.setToolTip('Capture Screenshot')
        icon = QIcon(f"{ICON_PATH}/camera.png")
        capture_btn.setIcon(icon)
        capture_btn.setIconSize(QSize(20, 20))
        capture_btn.setCursor(Qt.PointingHandCursor)
        capture_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-left: none;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                padding: 4px 6px;
                margin: 0px;
                min-width: 36px;
                min-height: 36px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                border-color: #10b981;
                color: #ffffff;
            }
        """)
        capture_btn.clicked.connect(lambda: self._show_capture_mode_dropdown(capture_btn))

        capture_layout.addWidget(capture_menu_btn)
        capture_layout.addWidget(capture_btn)
        toolbar_layout.addWidget(capture_container)
        self.tools_button[self.tool_access.CAPTURE] = capture_btn

        # update counter of capture
        self.update_capture_counter()

        # Microphone button with menu
        mic_widget = QWidget(self.patient_widget)
        mic_layout = QHBoxLayout(mic_widget)
        mic_layout.setContentsMargins(0, 0, 0, 0)
        mic_layout.setSpacing(0)
        mic_layout.setAlignment(Qt.AlignVCenter)

        mic_menu_btn = QPushButton()
        mic_menu_btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
        mic_menu_btn.setIconSize(QSize(14, 14))
        mic_menu_btn.setToolTip('View Audio Recordings')
        mic_menu_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
                padding: 4px 2px;
                margin: 0px;
                min-width: 11px;
                min-height: 36px;
                max-width: 11px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
        """)
        mic_menu_btn.setCursor(Qt.PointingHandCursor)
        mic_menu_btn.clicked.connect(lambda: self._show_audio_dropdown(mic_menu_btn))

        mic_btn = BadgeButton(self.patient_widget)
        mic_btn.setCheckable(True)
        mic_btn.setToolTip('Record Audio')
        icon = QIcon(f"{ICON_PATH}/mic.png")
        mic_btn.setIcon(icon)
        mic_btn.setIconSize(QSize(20, 20))
        mic_btn.setCursor(Qt.PointingHandCursor)
        mic_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-left: none;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                padding: 4px 6px;
                margin: 0px;
                min-width: 36px;
                min-height: 36px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #dc2626, stop:1 #b91c1c);
                border: 1px solid #ef4444;
                border-left: none;
                color: #ffffff;
            }
        """)

        mic_btn.clicked.connect(lambda: self._on_mic_clicked(mic_btn))

        mic_layout.addWidget(mic_menu_btn)
        mic_layout.addWidget(mic_btn)
        toolbar_layout.addWidget(mic_widget)

        self.tools_button[self.tool_access.MICROPHONE] = mic_btn
        self.update_audio_counter()
        toolbar_layout.addWidget(self._create_separator())

        # AI Chat button
        ai_chat_btn = create_tool_btn(self.patient_widget, 'AI Analyze', 'eagle.png', icon_size=30)
        ai_chat_btn.clicked.connect(lambda: self.toggle_ai_chat(self.patient_widget.selected_widget))
        toolbar_layout.addWidget(ai_chat_btn)
        self.tools_button[self.tool_access.AI_CHAT] = ai_chat_btn
        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 7: ADVANCED VISUALIZATION TOOLS
        # ============================================================
        # MPR button with menu
        mpr_container = QWidget()
        mpr_layout = QHBoxLayout(mpr_container)
        mpr_layout.setContentsMargins(0, 0, 0, 0)
        mpr_layout.setSpacing(0)
        mpr_layout.setAlignment(Qt.AlignVCenter)

        mpr_menu_btn = QPushButton()
        mpr_menu_btn.setCheckable(True)
        mpr_menu_btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
        mpr_menu_btn.setIconSize(QSize(14, 14))
        mpr_menu_btn.setToolTip('View MIP/MinIP/Thick Slab')
        mpr_menu_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
                padding: 4px 2px;
                margin: 0px;
                min-width: 11px;
                min-height: 36px;
                max-width: 11px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                border-color: #10b981;
                color: #ffffff;
            }
        """)
        mpr_menu_btn.setCursor(Qt.PointingHandCursor)
        mpr_menu_btn.clicked.connect(lambda: self._show_mpr_dropdown(mpr_menu_btn))
        self._mpr_menu_btn = mpr_menu_btn

        mpr_btn = create_tool_btn(self.patient_widget, 'Zeta MPR Viewer', icon_name=None, text_icon='MPR')
        mpr_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-left: none;
                border-top-left-radius: 0px;
                border-bottom-left-radius: 0px;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                padding: 4px 6px;
                margin: 0px;
                min-width: 36px;
                min-height: 36px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:checked {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                border-color: #10b981;
                color: #ffffff;
            }
        """)
        
        mpr_btn.clicked.connect(lambda: self.toggle_zeta_mpr())
        
        mpr_layout.addWidget(mpr_menu_btn)
        mpr_layout.addWidget(mpr_btn)
        toolbar_layout.addWidget(mpr_container)
        self.tools_button[self.tool_access.MPR] = mpr_btn
        toolbar_layout.addWidget(self._create_separator())

        # ============================================================
        # CATEGORY 8: UPLOAD & SYNC TOOLS
        # ============================================================
        # Upload status button with menu
        upload_container = QWidget()
        upload_layout = QHBoxLayout(upload_container)
        upload_layout.setContentsMargins(0, 0, 0, 0)
        upload_layout.setSpacing(0)
        upload_layout.setAlignment(Qt.AlignVCenter)

        upload_menu_btn = QPushButton()
        upload_menu_btn.setIcon(qta.icon('fa5s.bars', color='#9ca3af', scale_factor=0.9))
        upload_menu_btn.setIconSize(QSize(14, 14))
        upload_menu_btn.setToolTip('Select status')
        upload_menu_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-top-right-radius: 0px;
                border-bottom-right-radius: 0px;
                border-right: none;
                padding: 4px 2px;
                margin: 0px;
                min-width: 11px;
                min-height: 36px;
                max-width: 11px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
        """)
        upload_menu_btn.setCursor(Qt.PointingHandCursor)
        upload_menu_btn.clicked.connect(lambda: self._show_status_upload_dropdown(upload_menu_btn))

        upload_layout.addWidget(upload_menu_btn)
        toolbar_layout.addWidget(upload_container)

        # Sync button
        sync_btn = QPushButton(self.patient_widget)
        sync_btn.setToolTip('Sync patient data with server\n(Uploads attachments & sets status to "Awaiting Secretary Approval")')
        sync_btn.setCursor(Qt.PointingHandCursor)
        
        try:
            icon = qta.icon('fa5s.cloud-upload-alt', color='#60a5fa')
            sync_btn.setIcon(icon)
            sync_btn.setIconSize(QSize(20, 20))
        except Exception:
            sync_btn.setText("🔄")
        
        sync_btn.setStyleSheet(f"""
            QPushButton {{
                qproperty-iconSize: 20px 20px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 4px 6px;
                margin: 1px;
                min-width: 36px;
                min-height: 36px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }}
            QPushButton:disabled {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
                color: #6b7280;
                border-color: #374151;
            }}
        """)
        
        sync_btn.clicked.connect(self._start_patient_sync)
        self.sync_button = sync_btn
        toolbar_layout.addWidget(sync_btn)
        

        
        # ============================================================
        # انتهای layout - افزودن فضای خالی برای راست‌چین شدن محتوا
        # ============================================================
        toolbar_layout.addStretch(1)
        
        # تنظیم container به عنوان ویجت اصلی scroll area
        scroll_area.setWidget(toolbar_container)
        
        # افزودن scroll area به نوار ابزار
        toolbar.addWidget(scroll_area)

    def _check_status_change(self):
        """Periodic check for status changes"""
        try:
            current_widget_status = getattr(self.patient_widget, 'report_status', None)
            if current_widget_status and hasattr(self, '_last_known_status'):
                if current_widget_status != self._last_known_status:
                    self._update_report_status_display()
            self._last_known_status = current_widget_status
        except Exception:
            pass

    def _show_capture_mode_dropdown(self, button):
        """Show dropdown menu for capture options (Active vs Total layouts)"""
        from PySide6.QtWidgets import QMenu, QWidgetAction, QLabel, QHBoxLayout, QWidget
        
        try:
            menu = QMenu(self.patient_widget)
            menu.setStyleSheet("""
                QMenu {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1f2937, stop:1 #111827);
                    border: 2px solid #374151;
                    border-radius: 10px;
                    color: #f3f4f6;
                    padding: 8px;
                    min-width: 220px;
                }
                QMenu::item {
                    padding: 0px;
                    border-radius: 6px;
                    margin: 2px 0px;
                }
                QMenu::item:hover {
                    background: transparent;
                }
            """)
            
            # Header
            header = QLabel("📸 Capture Options")
            header.setStyleSheet("""
                color: #f7fafc;
                font-size: 14px;
                font-weight: 700;
                font-family: 'Roboto', sans-serif;
                padding: 6px 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3b82f6, stop:1 #2563eb);
                border-radius: 6px;
                margin-bottom: 6px;
            """)
            header_action = QWidgetAction(menu)
            header_action.setDefaultWidget(header)
            menu.addAction(header_action)
            
            # Active Layout Option
            active_widget = QWidget()
            active_layout = QHBoxLayout(active_widget)
            active_layout.setContentsMargins(8, 6, 8, 6)
            active_layout.setSpacing(8)
            
            active_icon = QLabel("📷")
            active_icon.setStyleSheet("font-size: 16px; background: transparent;")
            active_text = QLabel("Present Active Layout\n<small style='color: #9ca3af;'>Capture current viewer only</small>")
            active_text.setStyleSheet("color: #f3f4f6; font-size: 12px; background: transparent;")
            active_text.setTextFormat(Qt.RichText)
            
            active_layout.addWidget(active_icon)
            active_layout.addWidget(active_text, 1)
            active_layout.addStretch()
            
            active_widget.setStyleSheet("""
                QWidget {
                    background: transparent;
                    border-radius: 6px;
                }
                QWidget:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #374151, stop:1 #2d3748);
                }
            """)
            
            active_widget.mousePressEvent = lambda e: self._capture_active_layout()
            active_action = QWidgetAction(menu)
            active_action.setDefaultWidget(active_widget)
            menu.addAction(active_action)
            
            # Separator line
            separator = QWidget()
            separator.setFixedHeight(1)
            separator.setStyleSheet("background-color: #4b5563; margin: 4px 0px;")
            sep_action = QWidgetAction(menu)
            sep_action.setDefaultWidget(separator)
            menu.addAction(sep_action)
            
            # Total Layouts Option
            total_widget = QWidget()
            total_layout = QHBoxLayout(total_widget)
            total_layout.setContentsMargins(8, 6, 8, 6)
            total_layout.setSpacing(8)
            
            total_icon = QLabel("🎞️")
            total_icon.setStyleSheet("font-size: 16px; background: transparent;")
            total_text = QLabel("Total Layouts\n<small style='color: #9ca3af;'>Capture all viewers</small>")
            total_text.setStyleSheet("color: #f3f4f6; font-size: 12px; background: transparent;")
            total_text.setTextFormat(Qt.RichText)
            
            total_layout.addWidget(total_icon)
            total_layout.addWidget(total_text, 1)
            total_layout.addStretch()
            
            # Show count badge if available
            if hasattr(self.patient_widget, 'lst_nodes_viewer'):
                count = len(self.patient_widget.lst_nodes_viewer)
                count_label = QLabel(f"{count}")
                count_label.setStyleSheet("""
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #7c3aed, stop:1 #6d28d9);
                    color: #ffffff;
                    border-radius: 8px;
                    padding: 2px 6px;
                    font-size: 10px;
                    font-weight: bold;
                """)
                total_layout.addWidget(count_label)
            
            total_widget.setStyleSheet("""
                QWidget {
                    background: transparent;
                    border-radius: 6px;
                }
                QWidget:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #374151, stop:1 #2d3748);
                }
            """)
            
            total_widget.mousePressEvent = lambda e: self._capture_all_layouts()
            total_action = QWidgetAction(menu)
            total_action.setDefaultWidget(total_widget)
            menu.addAction(total_action)
            
            # Position and show menu
            pos = button.mapToGlobal(QPoint(0, button.height() + 2))
            menu.exec(pos)
            
        except Exception as e:
            print(f"[ERROR] Failed to show capture mode dropdown: {e}")
            import traceback
            traceback.print_exc()
            # Fallback to active layout only
            self._capture_active_layout()

    def _capture_active_layout(self):
        """Capture only the currently active layout (original behavior)"""
        selected_widget = self.patient_widget.selected_widget
        
        if selected_widget is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.patient_widget, "No Selection", "Please select a viewer first.")
            return
        
        # Deactivate any existing tool first
        self.check_and_deactivate_tools()
        
        # Set up and immediately execute capture
        self.check_and_deactivate_tools()
        selected_widget.set_new_interactorstyle(DefaultInteractionInteractorStyle)
        selected_widget.current_style.activate(self.tool_access.CAPTURE)
        
        # Update counter
        self.update_capture_counter()
        
        # Reset tool state
        self.tool_selected = None
        self.handle_buttons_checked()
        
        # Ensure cleanup
        if hasattr(selected_widget, 'restore_default_interactorstyle'):
            selected_widget.restore_default_interactorstyle()

    def _capture_all_layouts(self):
        """Capture the entire viewer grid as a single image"""
        import os
        import random
        from datetime import datetime
        from PySide6.QtWidgets import QMessageBox, QApplication
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QGuiApplication
        
        try:
            # Get study UID
            study_uid = self.patient_widget.study_uid
            if not study_uid:
                study_uid = str(random.randint(10000, 100000))
                print(f"Generated study_uid: {study_uid}")
            
            # Prepare directory
            attach_path = ATTACHMENT_PATH / study_uid
            if not attach_path.exists():
                os.makedirs(attach_path, exist_ok=True)
            
            # Change cursor to wait
            QApplication.setOverrideCursor(Qt.WaitCursor)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Generate filename
            filename = f"capture_all_layouts_{timestamp}.png"
            full_path = str(attach_path / filename)
            
            # Find the main viewer container widget
            # The patient_widget should have a viewer_container or similar
            target_widget = None
            
            # Find the widget that contains vtk_layout (the grid of viewers)
            if hasattr(self.patient_widget, 'vtk_layout') and self.patient_widget.vtk_layout:
                # Get the parent widget of vtk_layout
                target_widget = self.patient_widget.vtk_layout.parentWidget()
                if target_widget is None:
                    print("[ERROR] vtk_layout has no parent widget")
                    target_widget = self.patient_widget
            else:
                print("[WARNING] vtk_layout not found, using patient_widget")
                target_widget = self.patient_widget
            
            print(f"[CAPTURE] Capturing widget: {target_widget}")
            
            # Force update/repaint before capture
            target_widget.repaint()
            QApplication.processEvents()
            QTimer.singleShot(120, lambda: None)  # Small delay for rendering
            QApplication.processEvents()

            # Capture the entire widget as pixmap (OpenGL-safe)
            screen = None
            try:
                window_handle = target_widget.window().windowHandle()
                screen = window_handle.screen() if window_handle else None
            except Exception:
                screen = None

            if screen is None:
                screen = QGuiApplication.primaryScreen()

            pixmap = screen.grabWindow(int(target_widget.winId())) if screen else None

            # Fallback to QWidget.grab() if screen grab failed
            if pixmap is None or pixmap.isNull():
                pixmap = target_widget.grab()
            
            # Save the pixmap
            if pixmap and not pixmap.isNull() and pixmap.save(full_path, "PNG"):
                print(f"[CAPTURE] Saved: {filename}")
                success = True
            else:
                print(f"[ERROR] Failed to save: {filename}")
                success = False
            
            # Restore cursor
            QApplication.restoreOverrideCursor()
            
            # Update counter badge
            self.update_capture_counter()
            
            # Show result message
            if success:
                msg = f"✅ Captured entire layout successfully!\n\n📁 Saved to: {attach_path}"
                QMessageBox.information(
                    self.patient_widget,
                    "Layout Capture Complete",
                    msg
                )
            else:
                QMessageBox.warning(
                    self.patient_widget,
                    "Capture Failed",
                    "Failed to save the capture image."
                )
            
        except Exception as e:
            QApplication.restoreOverrideCursor()
            print(f"[ERROR] Total capture failed: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self.patient_widget,
                "Capture Error",
                f"Failed to capture layouts:\n{str(e)}"
            )
            

    def _show_status_upload_dropdown(self, button):
        """Show dropdown menu for report status selection - 6 status states"""
        try:
            from PySide6.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QWidget
            from PySide6.QtCore import Qt, QPoint
            
            # Clean up any existing dropdown with proper C++ object check
            if hasattr(self, '_status_dropdown') and self._status_dropdown:
                try:
                    self._status_dropdown.close()
                except RuntimeError:
                    # Object already deleted by Qt (WA_DeleteOnClose)
                    pass
                self._status_dropdown = None
            
            dropdown = QWidget(self.patient_widget)
            dropdown.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            dropdown.setAttribute(Qt.WA_DeleteOnClose)
            dropdown.setStyleSheet("""
                QWidget {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1f2937, stop:1 #111827);
                    border: 2px solid #4b5563;
                    border-radius: 12px;
                    padding: 8px;
                }
            """)
            
            layout = QVBoxLayout(dropdown)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(6)
            
            # Header
            header = QLabel("📊 Change Report Status")
            header.setStyleSheet("""
                QLabel {
                    color: #f7fafc;
                    font-size: 14px;
                    font-weight: 700;
                    font-family: 'Roboto', sans-serif;
                    padding: 8px 12px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #3b82f6, stop:1 #2563eb);
                    border-radius: 8px;
                    margin-bottom: 8px;
                }
            """)
            header.setAlignment(Qt.AlignCenter)
            layout.addWidget(header)
            
            # Current status display
            current_status = getattr(self.patient_widget, 'report_status', 'pending')
            from PacsClient.components.socket_report_status_service import REPORT_STATUSES
            
            current_label = QLabel(f"Current Status: {REPORT_STATUSES.get(current_status, current_status)}")
            current_label.setStyleSheet("""
                QLabel {
                    color: #94a3b8;
                    font-size: 11px;
                    font-weight: 500;
                    background: rgba(59, 130, 246, 0.1);
                    padding: 6px 10px;
                    border-radius: 6px;
                    margin-bottom: 8px;
                }
            """)
            current_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(current_label)
            
            # Separator
            line = QWidget()
            line.setFixedHeight(1)
            line.setStyleSheet("background-color: #4b5563; margin: 4px 0px;")
            layout.addWidget(line)
            
            # 6 Status buttons with icons and colors
            statuses = [
                ('pending', '⏳', '#f59e0b', 'Pending'),
                ('awaiting_physician_approval', '👨‍⚕️', '#3b82f6', 'Awaiting Physician'),
                ('awaiting_secretary_approval', '👩‍💼', '#8b5cf6', 'Awaiting Secretary'),
                ('physician_approved', '✅👨‍⚕️', '#10b981', 'Physician Approved'),
                ('secretary_approved', '✅👩‍💼', '#059669', 'Secretary Approved'),
                ('completed', '✓✓', '#06b6d4', 'Completed'),
            ]
            
            for status_key, icon, color, display_name in statuses:
                is_current = (current_status == status_key)
                
                btn_container = QWidget()
                btn_layout = QHBoxLayout(btn_container)
                btn_layout.setContentsMargins(8, 6, 8, 6)
                btn_layout.setSpacing(8)
                
                # Icon label
                icon_label = QLabel(icon)
                icon_label.setStyleSheet(f"font-size: 16px; background: transparent;")
                
                # Text
                text_label = QLabel(f"{display_name}")
                text_label.setStyleSheet(f"""
                    color: {'#fbbf24' if is_current else '#f3f4f6'};
                    font-size: 12px;
                    font-weight: {'700' if is_current else '500'};
                    background: transparent;
                """)
                
                # Status indicator
                indicator = QWidget()
                indicator.setFixedSize(8, 8)
                indicator.setStyleSheet(f"""
                    background-color: {color};
                    border-radius: 4px;
                    {'border: 2px solid white;' if is_current else ''}
                """)
                
                btn_layout.addWidget(indicator)
                btn_layout.addWidget(icon_label)
                btn_layout.addWidget(text_label, 1)
                
                if is_current:
                    check = QLabel("✓")
                    check.setStyleSheet("color: #10b981; font-weight: bold; background: transparent;")
                    btn_layout.addWidget(check)
                
                # Container styling
                base_style = f"""
                    QWidget {{
                        background: {'qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #374151, stop:1 #1f2937)' if not is_current else 'qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #059669, stop:1 #047857)'};
                        border: 1px solid {color if not is_current else '#10b981'};
                        border-radius: 8px;
                    }}
                    QWidget:hover {{
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4b5563, stop:1 #374151);
                        border-color: #60a5fa;
                    }}
                """
                btn_container.setStyleSheet(base_style)
                btn_container.setCursor(Qt.PointingHandCursor)
                
                # Click handler
                btn_container.mousePressEvent = lambda e, s=status_key: self._change_status_from_dropdown(s, dropdown)
                
                layout.addWidget(btn_container)
            
            layout.addSpacing(8)
            
            # Sync and go home button at bottom
            sync_btn = create_dropdown_tool('🔄 Sync and Return Home', 'fa5s.cloud-upload-alt', '#10b981')
            sync_btn.clicked.connect(lambda: [dropdown.close(), self._sync_and_go_home()])
            layout.addWidget(sync_btn)
            
            # Position dropdown below the button
            button_pos = button.mapToGlobal(QPoint(0, button.height()))
            dropdown.move(button_pos)
            dropdown.setFixedWidth(280)
            dropdown.raise_()
            dropdown.activateWindow()
            
            self._status_dropdown = dropdown
            dropdown.show()
            
        except Exception as e:
            print(f"[ERROR] Failed to show status dropdown: {e}")
            import traceback
            traceback.print_exc()
    
    def _change_status_from_dropdown(self, new_status: str, dropdown=None):
        """Change report status from dropdown menu"""
        try:
            current_status = getattr(self.patient_widget, 'report_status', 'pending')
            
            if new_status == current_status:
                print(f"[Toolbar] Status is already {new_status}, skipping")
                if dropdown:
                    dropdown.close()
                return
            
            print(f"[Toolbar] Changing status via dropdown: {current_status} -> {new_status}")
            
            # Call patient widget's change method
            if hasattr(self.patient_widget, '_change_report_status'):
                self.patient_widget._change_report_status(
                    study_uid=self.patient_widget.study_uid,
                    old_status=current_status,
                    new_status=new_status,
                    comment=f"Status changed via toolbar dropdown"
                )
            else:
                # Fallback: update directly
                self.patient_widget.report_status = new_status
                self._update_report_status_display()
            
            if dropdown:
                dropdown.close()
                
        except Exception as e:
            print(f"[ERROR] Failed to change status from dropdown: {e}")
            import traceback
            traceback.print_exc()
    
    def _sync_and_go_home(self):
        """Sync patient data and return to home page"""
        try:
            print("[Toolbar] Sync and go home triggered")
            
            # First sync
            self._start_patient_sync()
            
            # Then close patient tab and go home (delayed to allow sync to start)
            from PySide6.QtCore import QTimer
            
            def go_home():
                try:
                    if hasattr(self.patient_widget, 'close_and_remove_patient_tab'):
                        self.patient_widget.close_and_remove_patient_tab()
                        print("[Toolbar] Returned to home page")
                except Exception as e:
                    print(f"[Toolbar] Error closing tab: {e}")
            
            # Wait a bit for sync to initialize, then go home
            QTimer.singleShot(500, go_home)
            
        except Exception as e:
            print(f"[ERROR] Failed to sync and go home: {e}")
            import traceback
            traceback.print_exc()
    
    def _update_report_status_display(self):
        """Update the report status badge display - handles both badge types safely"""
        try:
            # Get current report status from widget
            current_status = getattr(self.patient_widget, 'report_status', 'pending')
            
            # Import status labels and colors
            from PacsClient.components.socket_report_status_service import REPORT_STATUSES, STATUS_COLORS
            
            # Get status label and color
            status_label = REPORT_STATUSES.get(current_status, current_status.title())
            status_color = STATUS_COLORS.get(current_status, '#f59e0b')
            
            # Status mapping for indicator
            status_indicator_map = {
                'pending': '⏳',
                'awaiting_physician_approval': '👨‍⚕️',
                'awaiting_secretary_approval': '👩‍💼',
                'awaiting_approval': '⏰',
                'physician_approved': '✅P',
                'secretary_approved': '✅S',
                'completed': '✓✓',
                'archived': '📦'
            }
            indicator_text = status_indicator_map.get(current_status, '?')
            
            # Update sync button badge if exists (legacy attribute name)
            if hasattr(self, 'sync_button_badge') and self.sync_button_badge:
                try:
                    self.sync_button_badge.setText(indicator_text)
                    self.sync_button_badge.setStyleSheet(f"""
                        QLabel {{
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {status_color}, stop:1 {status_color});
                            color: #ffffff;
                            border: 1px solid rgba(255, 255, 255, 0.3);
                            border-radius: 8px;
                            padding: 1px 4px;
                            font-weight: 600;
                            font-family: 'Roboto', sans-serif;
                            font-size: 8px;
                            min-width: 16px;
                            min-height: 16px;
                        }}
                    """)
                    self.sync_button_badge.show()
                except RuntimeError:
                    # Badge was deleted
                    pass
            
            # Update report_status_badge if exists (new attribute name)
            if hasattr(self, 'report_status_badge') and self.report_status_badge:
                try:
                    self.report_status_badge.setText(indicator_text)
                    self.report_status_badge.setStyleSheet(f"""
                        QLabel {{
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {status_color}, stop:1 {status_color});
                            color: #ffffff;
                            border: 1px solid rgba(255, 255, 255, 0.3);
                            border-radius: 8px;
                            padding: 1px 4px;
                            font-weight: 600;
                            font-family: 'Roboto', sans-serif;
                            font-size: 8px;
                        }}
                    """)
                    self.report_status_badge.show()
                    
                    # Update tooltip on button parent
                    if hasattr(self.report_status_badge, 'parent') and self.report_status_badge.parent():
                        self.report_status_badge.parent().setToolTip(f"Report Status: {status_label}\n(Click to change)")
                except RuntimeError:
                    # Badge was deleted
                    pass
            
            # Update tooltip on sync button if it exists
            if hasattr(self, 'sync_button') and self.sync_button:
                self.sync_button.setToolTip(f"Status: {status_label}\nClick to sync and return")
            
            print(f"[Toolbar] Status display updated: {current_status} -> {indicator_text}")
            
        except Exception as e:
            print(f"[ERROR] Failed to update report status display: {e}")
            import traceback
            traceback.print_exc()

            
    def initialize_status_sync(self):
        """Initialize status synchronization between patient widget and toolbar"""
        try:
            # Connect to patient widget status changes if possible
            if self.patient_widget:
                # Initial update
                self._update_report_status_display()
                
                # Create timer for periodic checks if not exists
                if not hasattr(self, '_status_check_timer') or self._status_check_timer is None:
                    self._status_check_timer = QTimer(self.patient_widget)
                    self._status_check_timer.setInterval(1000)  # Check every second
                    self._status_check_timer.timeout.connect(self._check_status_change)
                    self._status_check_timer.start()
                
                print("✅ [Toolbar] Status sync initialized")
        except Exception as e:
            print(f"⚠️ [Toolbar] Failed to initialize status sync: {e}")



    def _check_status_change(self):
        """Periodic check for status changes"""
        try:
            current_widget_status = getattr(self.patient_widget, 'report_status', None)
            if current_widget_status:
                if not hasattr(self, '_last_known_status'):
                    self._last_known_status = None
                if current_widget_status != self._last_known_status:
                    self._update_report_status_display()
                    self._last_known_status = current_widget_status
        except Exception:
            pass
        
    def turn_off_all_tools(self):
        self.check_and_deactivate_tools()
        self.handle_buttons_checked()
    
    def _start_patient_sync(self):
        """Start patient data synchronization with server"""
        try:
            from PySide6.QtWidgets import QProgressDialog, QMessageBox
            from PySide6.QtCore import QTimer
            from PacsClient.pacs.patient_tab.utils import get_patient_sync_service
            
            # Get study_uid from patient_widget
            study_uid = getattr(self.patient_widget, 'study_uid', None)
            if not study_uid:
                # Try to get from metadata_fixed
                metadata_fixed = getattr(self.patient_widget, 'metadata_fixed', {})
                study_uid = metadata_fixed.get('study_uid')
            
            if not study_uid:
                QMessageBox.warning(self.patient_widget, "Error", "Study UID not found.")
                return
            
            # Disable sync button during sync
            if hasattr(self, 'sync_button'):
                self.sync_button.setEnabled(False)
            
            # Create progress dialog
            progress_dialog = QProgressDialog(
                "Synchronizing patient data...",
                "Cancel",
                0, 100,
                self.patient_widget
            )
            progress_dialog.setWindowTitle("Patient Data Sync")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setMinimumDuration(0)
            progress_dialog.setValue(0)
            
            # Style progress dialog
            progress_dialog.setStyleSheet("""
                QProgressDialog {
                    background: #0b1220;
                    border: 1px solid #223046;
                    border-radius: 12px;
                    color: #e5e7eb;
                }
                QProgressDialog QLabel {
                    color: #e5e7eb;
                    font-family: 'Segoe UI', 'Roboto';
                    font-size: 14px;
                    font-weight: 600;
                    padding: 10px 14px;
                }
                QProgressBar {
                    border: 1px solid #2b3b55;
                    border-radius: 8px;
                    background: #0f172a;
                    height: 14px;
                    text-align: center;
                    color: #94a3b8;
                }
                QProgressBar::chunk {
                    border-radius: 8px;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                 stop:0 #38bdf8, stop:1 #60a5fa);
                }
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #374151, stop:1 #1f2937);
                    color: #e5e7eb;
                    border: 1px solid #4b5563;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #4b5563, stop:1 #374151);
                }
            """)
            
            # Get sync service
            sync_service = get_patient_sync_service()
            
            # Connect signals
            def on_sync_started(uid):
                if uid == study_uid:
                    progress_dialog.setLabelText("🔄 Starting synchronization...")
                    progress_dialog.setValue(5)
            
            def on_sync_progress(uid, current, total):
                if uid == study_uid:
                    if total > 0:
                        percentage = int((current / total) * 90) + 5  # 5-95% for file uploads
                        progress_dialog.setLabelText(f"📤 Uploading attachments... ({current}/{total})")
                        progress_dialog.setValue(percentage)
            
            def on_sync_completed(uid, result):
                if uid == study_uid:
                    progress_dialog.setValue(100)
                    progress_dialog.close()
                    
                    # Re-enable sync button
                    if hasattr(self, 'sync_button'):
                        self.sync_button.setEnabled(True)
                    
                    # Update patient_widget report_status to awaiting_secretary_approval
                    self.patient_widget.report_status = 'awaiting_secretary_approval'
                    
                    # Update visited status to synced (green underline)
                    try:
                        from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                        home_widget = get_home_widget()
                        if home_widget and hasattr(home_widget, 'patient_table_widget'):
                            home_widget.patient_table_widget.update_visited_status(study_uid, status='synced')
                    except Exception:
                        pass
                    
                    # Show success message
                    success_msg = f"✅ Synchronization completed!\n\n"
                    success_msg += f"📤 Uploaded: {result['attachments_uploaded']} files\n"
                    if result['attachments_failed'] > 0:
                        success_msg += f"❌ Failed: {result['attachments_failed']} files\n"
                    success_msg += f"📋 Status: Set to 'Awaiting Secretary Approval'"
                    
                    QMessageBox.information(
                        self.patient_widget,
                        "Sync Completed",
                        success_msg
                    )
            
            def on_sync_failed(uid, error_msg):
                if uid == study_uid:
                    progress_dialog.close()
                    
                    # Re-enable sync button
                    if hasattr(self, 'sync_button'):
                        self.sync_button.setEnabled(True)
                    
                    # QMessageBox.warning(
                    #     self.patient_widget,
                    #     "Sync Failed",
                    #     f"Failed to synchronize patient data:\n{error_msg}"
                    # )
            
            # Connect all signals
            sync_service.sync_started.connect(on_sync_started)
            sync_service.sync_progress.connect(on_sync_progress)
            sync_service.sync_completed.connect(on_sync_completed)
            sync_service.sync_failed.connect(on_sync_failed)
            
            # Handle cancel button
            def on_cancel():
                # Re-enable sync button
                if hasattr(self, 'sync_button'):
                    self.sync_button.setEnabled(True)
                # QMessageBox.information(
                #     self.patient_widget,
                #     "Sync Cancelled",
                #     "Synchronization was cancelled by user.\nNote: Some files may have been uploaded."
                # )
            
            progress_dialog.canceled.connect(on_cancel)
            
            # Start sync
            sync_service.sync_patient_data(study_uid, verbose=True)
            
            # Show progress dialog
            progress_dialog.show()
            
        except Exception as e:
            print(f"[ERROR] Failed to start patient sync: {e}")
            import traceback
            traceback.print_exc()
            
            # Re-enable sync button
            if hasattr(self, 'sync_button'):
                self.sync_button.setEnabled(True)
            
            from PySide6.QtWidgets import QMessageBox
            # QMessageBox.warning(
            #     self.patient_widget,
            #     "Error",
            #     f"Failed to start synchronization: {str(e)}"
            # )
    
    def _update_report_status_display(self):
        """Update the report status badge display"""
        try:
            # Get current report status from widget
            current_status = getattr(self.patient_widget, 'report_status', 'pending')
            
            # Import status labels and colors
            from PacsClient.components.socket_report_status_service import REPORT_STATUSES, STATUS_COLORS
            
            # Get status label and color
            status_label = REPORT_STATUSES.get(current_status, current_status.title())
            status_color = STATUS_COLORS.get(current_status, '#f59e0b')
            
            # Choose simple indicator based on status
            # Use single character or symbol for compact display
            status_indicator_map = {
                'pending': 'P',
                'awaiting_physician_approval': 'MD',
                'awaiting_secretary_approval': 'SC',
                'awaiting_approval': 'A',
                'physician_approved': 'MD',  # Medical Doctor approved - different from secretary
                'secretary_approved': 'SC',  # Secretary approved - different from physician
                'completed': '✓✓',
                'archived': 'A'
            }
            indicator_text = status_indicator_map.get(current_status, '?')
            
            # Update badge with colored background - with safety check
            if hasattr(self, 'report_status_badge') and self.report_status_badge:
                try:
                    self.report_status_badge.setText(indicator_text)
                    self.report_status_badge.setStyleSheet(f"""
                        QLabel {{
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {status_color}, stop:1 {status_color});
                            color: #ffffff;
                            border: 1px solid rgba(255, 255, 255, 0.3);
                            border-radius: 8px;
                            padding: 1px 4px;
                            font-weight: 600;
                            font-family: 'Roboto', sans-serif;
                            font-size: 8px;
                        }}
                    """)
                    self.report_status_badge.show()
                    
                    # Update tooltip on button
                    button = self.report_status_badge.parent()
                    if button:
                        button.setToolTip(f"Report Status: {status_label}\n(Click to change)")
                    
                    print(f"📋 [Toolbar] Updated status badge: {current_status} -> {indicator_text} ({status_label})")
                except RuntimeError:
                    # Badge was deleted
                    pass
            else:
                print(f"⚠️ [Toolbar] report_status_badge not available, skipping display update")
            
        except Exception as e:
            print(f"[ERROR] Failed to update report status display: {e}")
            import traceback
            traceback.print_exc()
