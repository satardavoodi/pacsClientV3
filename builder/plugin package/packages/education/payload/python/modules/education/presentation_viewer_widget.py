"""Presentation viewer widget with fullscreen mode and navigation."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QStackedWidget,
    QTextBrowser, QFrame, QMessageBox, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap, QKeyEvent
from pathlib import Path

from modules.education.video_slide_widget import SimpleVideoWidget
from PacsClient.utils.theme_manager import get_theme_manager


class SlideContentWidget(QWidget):
    """Widget for displaying a single slide's content."""
    
    def __init__(self, slide_data, course_pk, parent=None):
        super().__init__(parent)
        self.slide_data = slide_data
        self.course_pk = course_pk
        self.dicom_widgets = []  # Keep references to prevent cleanup
        self.video_widgets = []
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the slide display."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(20)
        
        # Slide title
        if self.slide_data.get('slide_title'):
            title = QLabel(self.slide_data['slide_title'])
            title_font = QFont()
            title_font.setPointSize(28)
            title_font.setBold(True)
            title.setFont(title_font)
            title.setStyleSheet("color: #e2e8f0;")
            title.setAlignment(Qt.AlignCenter)
            layout.addWidget(title)
        
        # Content area (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(20)
        
        # Render each content item
        for content_item in self.slide_data.get('content', []):
            content_type = content_item['content_type']
            content_data = content_item['content_data']
            
            if content_type == 'text':
                widget = self.create_text_widget(content_data)
            elif content_type == 'image':
                widget = self.create_image_widget(content_data)
            elif content_type == 'video':
                widget = self.create_video_widget(content_data)
            elif content_type == 'dicom_study':
                widget = self.create_dicom_study_widget(content_data)
            elif content_type == 'dicom_series':
                widget = self.create_dicom_series_widget(content_data)
            else:
                widget = QLabel(f"Unknown content type: {content_type}")
                widget.setStyleSheet("color: #e53e3e;")
            
            if widget:
                content_layout.addWidget(widget)
        
        scroll.setWidget(content_widget)
        layout.addWidget(scroll, stretch=1)
    
    def create_text_widget(self, content_data):
        """Create text display widget."""
        text_browser = QTextBrowser()
        text_browser.setPlainText(content_data.get('text', ''))
        text_browser.setStyleSheet("""
            QTextBrowser {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 2px solid #4a5568;
                border-radius: 10px;
                padding: 20px;
                font-size: 14pt;
            }
        """)
        text_browser.setMinimumHeight(150)
        return text_browser
    
    def create_image_widget(self, content_data):
        """Create image display widget."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        
        image_path = content_data.get('path', '')
        
        if Path(image_path).exists():
            image_label = QLabel()
            pixmap = QPixmap(image_path)
            
            # Scale to fit while maintaining aspect ratio
            max_width = 1200
            max_height = 600
            scaled_pixmap = pixmap.scaled(max_width, max_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(image_label)
            
            # Caption
            if content_data.get('caption'):
                caption = QLabel(content_data['caption'])
                caption.setStyleSheet("color: #a0aec0; font-style: italic;")
                caption.setAlignment(Qt.AlignCenter)
                layout.addWidget(caption)
        else:
            error_label = QLabel(f"Image not found: {image_path}")
            error_label.setStyleSheet("color: #e53e3e;")
            error_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(error_label)
        
        return container
    
    def create_video_widget(self, content_data):
        """Create video player widget."""
        video_path = content_data.get('path', '')
        
        if Path(video_path).exists():
            video_widget = SimpleVideoWidget(video_path)
            video_widget.setMinimumHeight(400)
            self.video_widgets.append(video_widget)  # Keep reference
            
            # Auto-play if specified
            if content_data.get('autoplay', False):
                video_widget.play()
            
            return video_widget
        else:
            error_label = QLabel(f"Video not found: {video_path}")
            error_label.setStyleSheet("color: #e53e3e; font-size: 14pt;")
            error_label.setAlignment(Qt.AlignCenter)
            return error_label
    
    def create_dicom_study_widget(self, content_data):
        """Create DICOM study viewer widget."""
        try:
            from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget
            from PacsClient.utils import CallerTypes
            
            study_uid = content_data.get('study_uid')
            patient_id = content_data.get('patient_id')
            
            if not study_uid:
                error_label = QLabel("Invalid DICOM study data")
                error_label.setStyleSheet("color: #e53e3e;")
                return error_label
            
            # Create PatientWidget for DICOM viewing
            dicom_widget = PatientWidget(
                parent=self,
                import_folder_path=None,
                size_init_viewers=(1, 1),
                caller=CallerTypes.SERVER,
                study_uid=study_uid,
                patient_id=patient_id,
                enable_progressive_mode=False
            )
            
            dicom_widget.setMinimumHeight(500)
            self.dicom_widgets.append(dicom_widget)  # Keep reference
            
            return dicom_widget
            
        except Exception as e:
            error_label = QLabel(f"Failed to load DICOM study: {str(e)}")
            error_label.setStyleSheet("color: #e53e3e; font-size: 12pt;")
            error_label.setWordWrap(True)
            return error_label
    
    def create_dicom_series_widget(self, content_data):
        """Create DICOM series viewer widget."""
        try:
            from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget
            from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
            from PacsClient.pacs.patient_tab.utils import get_study_source_path
            from PacsClient.utils import CallerTypes
            
            study_uid = content_data.get('study_uid')
            series_number = content_data.get('series_number')
            patient_id = content_data.get('patient_id')
            
            if not study_uid or series_number is None:
                error_label = QLabel("Invalid DICOM series data")
                error_label.setStyleSheet("color: #e53e3e;")
                return error_label
            
            # Get study path
            study_path, _ = get_study_source_path(study_uid)
            
            if not study_path or not Path(study_path).exists():
                error_label = QLabel(f"Study path not found for UID: {study_uid}")
                error_label.setStyleSheet("color: #e53e3e; font-size: 12pt;")
                return error_label
            
            # Create PatientWidget
            dicom_widget = PatientWidget(
                parent=self,
                import_folder_path=str(study_path),
                size_init_viewers=(1, 1),
                caller=CallerTypes.SERVER,
                study_uid=study_uid,
                patient_id=patient_id,
                enable_progressive_mode=False
            )
            
            # Load specific series
            result = load_single_series_by_number(
                study_path=str(study_path),
                series_number=int(series_number)
            )

            if result and dicom_widget.lst_nodes_viewer:
                # Convert generator to list to safely get the first item
                result_list = list(result)
                if result_list:
                    vtk_image_data, metadata, _ = result_list[0]  # Use first item
                else:
                    # Handle case where no series data was loaded
                    print(f"⚠️ No series data found for series {series_number}")
                    return QLabel(f"No data found for series {series_number}")
                viewer = dicom_widget.lst_nodes_viewer[0]
                
                # Display the series
                viewer.switch_series(
                    vtk_image_data=vtk_image_data,
                    metadata=metadata,
                    series_index=int(series_number),
                    metadata_fixed=dicom_widget.metadata_fixed
                )
            
            dicom_widget.setMinimumHeight(500)
            self.dicom_widgets.append(dicom_widget)  # Keep reference
            
            return dicom_widget
            
        except Exception as e:
            error_label = QLabel(f"Failed to load DICOM series: {str(e)}")
            error_label.setStyleSheet("color: #e53e3e; font-size: 12pt;")
            error_label.setWordWrap(True)
            return error_label
    
    def cleanup(self):
        """Cleanup resources when switching slides."""
        # Stop videos
        for video_widget in self.video_widgets:
            try:
                video_widget.stop()
                video_widget.cleanup()
            except:
                pass
        
        # Clear DICOM widgets
        for dicom_widget in self.dicom_widgets:
            try:
                dicom_widget.deleteLater()
            except:
                pass
        
        self.video_widgets.clear()
        self.dicom_widgets.clear()


class PresentationViewerWidget(QWidget):
    """Fullscreen presentation viewer with navigation."""
    
    def __init__(self, course_data, parent=None):
        super().__init__(parent)
        self.course_data = course_data
        self.slides = course_data.get('slides', [])
        self.current_slide_index = 0
        self.slide_widgets = []
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        
        if not self.slides:
            QMessageBox.warning(self, "No Slides", "This course has no slides.")
            self.close()
            return
        
        self.setup_ui()
        self.load_all_slides()
        self.show_slide(0)
    
    def _on_theme_changed(self, theme):
        """Handle theme changes."""
        self._theme = theme or self.theme_manager.current_theme()
        self._apply_theme_styles()
        # Clean up and reload slides to reapply theme
        while self.slides_stack.count() > 0:
            widget = self.slides_stack.widget(0)
            self.slides_stack.removeWidget(widget)
            widget.deleteLater()
        self.slide_widgets = []
        self.load_all_slides()
        self.show_slide(self.current_slide_index)
    
    def setup_ui(self):
        """Setup the presentation viewer UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Main content area (stacked widget for slides)
        self.slides_stack = QStackedWidget()
        self.slides_stack.setStyleSheet("""
            QStackedWidget {
                background-color: #1a202c;
            }
        """)
        layout.addWidget(self.slides_stack, stretch=1)
        
        # Navigation controls
        controls_widget = QWidget()
        controls_widget.setFixedHeight(80)
        controls_widget.setStyleSheet("""
            QWidget {
                background-color: #2d3748;
                border-top: 2px solid #4a5568;
            }
        """)
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(20, 15, 20, 15)
        controls_layout.setSpacing(15)
        
        # Previous button
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.setFixedHeight(50)
        self.prev_btn.clicked.connect(self.previous_slide)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton:hover {
                background-color: #6b7280;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #6b7280;
            }
        """)
        controls_layout.addWidget(self.prev_btn)
        
        controls_layout.addStretch()
        
        # Slide counter
        self.slide_counter = QLabel()
        self.slide_counter.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 16pt;
                font-weight: bold;
            }
        """)
        controls_layout.addWidget(self.slide_counter)
        
        controls_layout.addStretch()
        
        # Next button
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.setFixedHeight(50)
        self.next_btn.clicked.connect(self.next_slide)
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #6b7280;
            }
        """)
        controls_layout.addWidget(self.next_btn)
        
        # Exit button
        self.exit_btn = QPushButton("Exit (Esc)")
        self.exit_btn.setFixedHeight(50)
        self.exit_btn.clicked.connect(self.close)
        self.exit_btn.setStyleSheet("""
            QPushButton {
                background-color: #e53e3e;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
                font-size: 12pt;
            }
            QPushButton:hover {
                background-color: #c53030;
            }
        """)
        controls_layout.addWidget(self.exit_btn)
        
        layout.addWidget(controls_widget)
        
        # Set focus to enable keyboard navigation
        self.setFocusPolicy(Qt.StrongFocus)
        
        self._apply_theme_styles()
    
    def _apply_theme_styles(self):
        """Apply theme-based styling to all UI elements."""
        t = self._theme
        
        # Slides stack background
        self.slides_stack.setStyleSheet(f"""
            QStackedWidget {{
                background-color: {t['panel_deep_bg']};
            }}
        """)
        
        # Controls widget
        if hasattr(self, 'controls_widget'):
            self.controls_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {t['panel_alt_bg']};
                    border-top: 2px solid {t['border']};
                }}
            """)
        
        # Navigation buttons
        nav_button_style = f"""
            QPushButton {{
                background-color: {t['border']};
                color: {t['text_secondary']};
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
            }}
            QPushButton:hover {{
                background-color: {t['accent_hover']};
                color: {t['button_text']};
            }}
        """
        
        # Next/Previous buttons
        for button in self.findChildren(QPushButton):
            if button.text() in ["Previous", "Next"]:
                if button.text() == "Next":
                    button.setStyleSheet(f"""
                        QPushButton {{
                            background-color: {t['accent']};
                            color: {t['button_text']};
                            border: none;
                            border-radius: 5px;
                            padding: 8px 15px;
                        }}
                        QPushButton:hover {{
                            background-color: {t['accent_hover']};
                        }}
                    """)
                else:
                    button.setStyleSheet(nav_button_style)
    
    def load_all_slides(self):
        """Load all slide widgets."""
        for slide in self.slides:
            slide_widget = SlideContentWidget(slide, self.course_data['course_pk'])
            self.slides_stack.addWidget(slide_widget)
            self.slide_widgets.append(slide_widget)
    
    def show_slide(self, index):
        """Display a specific slide."""
        if 0 <= index < len(self.slides):
            # Cleanup previous slide
            if 0 <= self.current_slide_index < len(self.slide_widgets):
                try:
                    self.slide_widgets[self.current_slide_index].cleanup()
                except:
                    pass
            
            self.current_slide_index = index
            self.slides_stack.setCurrentIndex(index)
            
            # Update controls
            self.slide_counter.setText(f"{index + 1} / {len(self.slides)}")
            self.prev_btn.setEnabled(index > 0)
            self.next_btn.setEnabled(index < len(self.slides) - 1)
    
    def next_slide(self):
        """Go to next slide."""
        if self.current_slide_index < len(self.slides) - 1:
            self.show_slide(self.current_slide_index + 1)
    
    def previous_slide(self):
        """Go to previous slide."""
        if self.current_slide_index > 0:
            self.show_slide(self.current_slide_index - 1)
    
    def keyPressEvent(self, event: QKeyEvent):
        """Handle keyboard navigation."""
        key = event.key()
        
        if key in (Qt.Key_Right, Qt.Key_Space, Qt.Key_PageDown):
            self.next_slide()
        elif key in (Qt.Key_Left, Qt.Key_Backspace, Qt.Key_PageUp):
            self.previous_slide()
        elif key == Qt.Key_Escape:
            self.close()
        elif key == Qt.Key_Home:
            self.show_slide(0)
        elif key == Qt.Key_End:
            self.show_slide(len(self.slides) - 1)
        else:
            super().keyPressEvent(event)
    
    def closeEvent(self, event):
        """Cleanup when closing."""
        # Cleanup all slides
        for slide_widget in self.slide_widgets:
            try:
                slide_widget.cleanup()
            except:
                pass
        
        event.accept()
