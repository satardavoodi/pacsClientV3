"""
Right Panel Widget for displaying series information and thumbnails
"""

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QRect
from PySide6.QtGui import QPixmap, QPainter, QPen
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QGridLayout
try:
    import qtawesome as qta
    QTAWESOME_AVAILABLE = True
except ImportError:
    QTAWESOME_AVAILABLE = False


class LoadingSpinner(QWidget):
    """Modern loading spinner widget"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(60, 60)
        self.angle = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.rotate)
        
        # Style with semi-transparent background
        self.setStyleSheet("""
            QWidget {
                background: rgba(15, 20, 25, 180);
                border-radius: 30px;
            }
        """)
    
    def start(self):
        """Start the spinner animation"""
        self.timer.start(50)  # 50ms = smooth rotation
        self.show()
    
    def stop(self):
        """Stop the spinner animation"""
        self.timer.stop()
        self.hide()
    
    def rotate(self):
        """Rotate the spinner"""
        self.angle = (self.angle + 10) % 360
        self.update()
    
    def paintEvent(self, event):
        """Custom paint event for the spinner"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Set up the pen
        pen = QPen()
        pen.setWidth(4)
        pen.setCapStyle(Qt.RoundCap)
        
        # Draw the spinner
        rect = QRect(10, 10, 40, 40)
        
        # Background circle (light)
        pen.setColor(Qt.darkGray)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        
        # Active arc (colored) - use purple theme color
        from PySide6.QtGui import QColor
        pen.setColor(QColor(124, 58, 237))  # #7c3aed - purple theme color
        painter.setPen(pen)
        painter.drawArc(rect, self.angle * 16, 90 * 16)  # 90 degree arc


class RightPanelWidget(QWidget):
    """Right panel widget for displaying series information and thumbnails"""
    
    # Signals
    thumbnailClicked = Signal(str)  # series_number
    seriesInfoRequested = Signal(str)  # series_uid
    
    def __init__(self, parent=None):
        super(RightPanelWidget, self).__init__(parent)
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the UI components"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)
        
        # Enhanced header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_widget.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border-radius: 8px;
            }
        """)
        
        # Title
        self.title_label = QLabel("Study Information")
        self.title_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 0px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                border: 1px solid #7c3aed;
                border-radius: 8px;
                margin: 4px 0px;
            }
        """)
        
        # Count indicator
        self.count_label = QLabel("0 series")
        self.count_label.setStyleSheet("""
            QLabel {
                font-size: 9px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 4px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
                margin: 4px 0px;
            }
        """)
        
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.count_label)
        main_layout.addWidget(header_widget)
        
        # Scroll area for content
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                border: 1px solid #4b5563;
                background: #1f2937;
                width: 12px;
                margin: 12px 0px 12px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 40px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 12px;
                width: 12px;
                background: transparent;
                border: none;
                subcontrol-origin: margin;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
            }
        """)
        
        # Content container
        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)
        
        self.content_grid = QGridLayout(self.content_widget)
        # Move thumbnail to the left side with minimal margins
        # Small left margin, larger right margin to push thumbnail left
        self.content_grid.setContentsMargins(8, 6, 14, 6)  # Left-aligned with proper spacing
        self.content_grid.setHorizontalSpacing(6)  # Reduced spacing for better fit
        self.content_grid.setVerticalSpacing(6)   # Reduced spacing for better fit
        self.content_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # Align thumbnails to the left
        
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)
        
        # Loading spinner as overlay (initially hidden)
        self.loading_spinner = LoadingSpinner(self)
        self.loading_spinner.hide()
        
        # Set fixed width - calculated for 180px thumbnails + margins + scrollbar
        # Calculation: 180px (thumbnail) + 10px (left margin) + 10px (right margin) + 16px (scrollbar) = 216px
        self.setFixedWidth(216)
        
    def clear_content(self):
        """Clear all content from the panel"""
        for i in reversed(range(self.content_grid.count())):
            widget = self.content_grid.itemAt(i).widget()
            if widget:
                widget.setParent(None)
    
    def display_series_info(self, study_info):
        """Display series information in the panel - prepare for progressive thumbnail display"""
        try:

            self.clear_content()
            self.count_label.setText(f"Loading {len(study_info['series'])} series...")
            self.show_loading()
        except Exception as e:
            print(f"Error in display_series_info: {str(e)}")
    
    def display_thumbnails(self, thumbnails, progressive: bool = True):
        """Display thumbnail images with series info in single boxes."""
        try:
            self.count_label.setText(f"Loading {len(thumbnails)} series...")
            if progressive:
                QTimer.singleShot(50, lambda: self.display_thumbnails_progressively(thumbnails))
            else:
                QTimer.singleShot(0, lambda: self.display_thumbnails_immediately(thumbnails))
        except Exception as e:
            print(f"Error in display_thumbnails: {str(e)}")
    
    def show_loading(self):
        """Show loading spinner as overlay"""
        # Position spinner in center of the widget
        self.position_spinner()
        self.loading_spinner.start()
    
    def hide_loading(self):
        """Hide loading spinner"""
        self.loading_spinner.stop()
    
    def position_spinner(self):
        """Position the spinner in the center of the widget"""
        if self.loading_spinner:
            # Calculate center position
            widget_rect = self.rect()
            spinner_size = self.loading_spinner.size()
            
            x = (widget_rect.width() - spinner_size.width()) // 2
            y = (widget_rect.height() - spinner_size.height()) // 2 + 40  # Offset for header
            
            self.loading_spinner.move(x, y)
    
    def resizeEvent(self, event):
        """Handle resize events to reposition spinner"""
        super().resizeEvent(event)
        if hasattr(self, 'loading_spinner') and self.loading_spinner.isVisible():
            self.position_spinner()
    
    def display_thumbnails_progressively(self, thumbnails):
        """Display thumbnails one by one with a small delay for better UX"""
        try:

            self.hide_loading()
            
            self.current_thumbnail_index = 0
            self.thumbnails_to_display = thumbnails

            self.count_label.setText(f"0/{len(thumbnails)} series")

            self.thumbnail_timer = QTimer()
            self.thumbnail_timer.timeout.connect(self.display_next_thumbnail)
            self.thumbnail_timer.start(120)  # 120ms delay between each thumbnail to prevent overlapping
            
        except Exception as e:
            print(f"Error in display_thumbnails_progressively: {str(e)}")
            self.hide_loading()  # Make sure to hide loading on error

    def display_thumbnails_immediately(self, thumbnails):
        """Display thumbnails immediately (no progressive delay)."""
        try:
            self.hide_loading()
            self.clear_content()
            total = len(thumbnails)
            self.count_label.setText(f"0/{total} series")

            from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
            temp_manager = ThumbnailManager(lambda x: None)

            for idx, thumb in enumerate(thumbnails):
                thumb_path = thumb.get('file_path')
                if not thumb_path:
                    continue

                try:
                    pixmap = QPixmap(thumb_path)
                    if pixmap.isNull():
                        continue

                    series_info = self.extract_series_info_from_thumbnail(thumb)
                    combined_widget = temp_manager.create_thumbnail_widget(
                        pixmap=pixmap,
                        label_text=str(series_info.get('series_number', idx + 1)),
                        thumbnail_index=idx,
                        series_info=series_info,
                        show_progress=False
                    )
                    self.content_grid.addWidget(combined_widget, idx, 0, 1, 1)
                except Exception as e:
                    print(f"Error displaying thumbnail {idx}: {str(e)}")

                self.count_label.setText(f"{idx + 1}/{total} series")

            self.count_label.setText(f"{total} series")
        except Exception as e:
            print(f"Error in display_thumbnails_immediately: {str(e)}")
            self.hide_loading()
    
    def display_next_thumbnail(self):
        """Display the next thumbnail in the queue"""
        try:
            if self.current_thumbnail_index >= len(self.thumbnails_to_display):
                # All thumbnails displayed, stop the timer
                self.thumbnail_timer.stop()
                # Update final count
                self.count_label.setText(f"{len(self.thumbnails_to_display)} series")
                return
            
            thumb = self.thumbnails_to_display[self.current_thumbnail_index]
            thumb_path = thumb.get('file_path')

            # print('thumb_path:', thumb_path)

            if thumb_path:
                try:
                    pixmap = QPixmap(thumb_path)
                    if not pixmap.isNull():
                        # Use unified thumbnail widget creation
                        series_info = self.extract_series_info_from_thumbnail(thumb)

                        # print('series_info:', series_info)
                        # Import ThumbnailManager for consistent widget creation
                        from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
                        temp_manager = ThumbnailManager(lambda x: None)  # Dummy callback

                        # print('FIND FIND')
                        combined_widget = temp_manager.create_thumbnail_widget(
                            pixmap=pixmap,
                            label_text=str(series_info.get('series_number', self.current_thumbnail_index + 1)),
                            thumbnail_index=self.current_thumbnail_index,
                            series_info=series_info,
                            show_progress=False  # Right panel doesn't show progress
                        )
                        
                        # Place widgets in a single column with proper positioning
                        self.content_grid.addWidget(combined_widget, self.current_thumbnail_index, 0, 1, 1)
                        
                        # Force layout update to prevent overlapping
                        combined_widget.show()
                        combined_widget.updateGeometry()
                        self.content_grid.update()

                except Exception as e:
                    print(f"Error displaying thumbnail {self.current_thumbnail_index}: {str(e)}")
            
            self.current_thumbnail_index += 1
            
            # Update progress count
            self.count_label.setText(f"{self.current_thumbnail_index}/{len(self.thumbnails_to_display)} series")
            
        except Exception as e:
            # Stop timer on error
            if hasattr(self, 'thumbnail_timer'):
                self.thumbnail_timer.stop()
            self.hide_loading()  # Make sure to hide loading on error
    
    def extract_series_info_from_thumbnail(self, thumb):
        """Extract series information from thumbnail data"""
        try:
            # Get series number
            series_number = thumb.get('series_number', 0)
            
            # Try to get modality from different possible fields
            modality = thumb.get('modality', '')
            if not modality:
                modality = thumb.get('Modality', '')
            if not modality:
                modality = thumb.get('modality_type', '')
            
            # Try to get series description from different possible fields
            series_description = thumb.get('series_description', '')
            if not series_description:
                series_description = thumb.get('SeriesDescription', '')
            if not series_description:
                series_description = thumb.get('description', '')
            
            # Try to get image count from different possible fields
            image_count = thumb.get('image_count', 0)
            if not image_count:
                image_count = thumb.get('ImageCount', 0)
            if not image_count:
                image_count = thumb.get('number_of_images', 0)
            
            # Try to get protocol name
            protocol_name = thumb.get('protocol_name', '')
            if not protocol_name:
                protocol_name = thumb.get('ProtocolName', '')
            if not protocol_name:
                protocol_name = thumb.get('protocol', '')
            
            # Try to get body part examined
            body_part = thumb.get('body_part_examined', '')
            if not body_part:
                body_part = thumb.get('BodyPartExamined', '')
            if not body_part:
                body_part = thumb.get('body_part', '')
            
            extracted_info = {
                'series_number': series_number,
                'modality': modality if modality else 'Unknown',
                'series_description': series_description if series_description else f'Series {series_number}',
                'image_count': image_count if image_count else 0,
                'protocol_name': protocol_name,
                'body_part_examined': body_part
            }
            

            
            return extracted_info
            
        except Exception as e:
            print(f"Error extracting series info: {str(e)}")
            return {
                'series_number': thumb.get('series_number', 0),
                'modality': 'Unknown',
                'series_description': f'Series {thumb.get("series_number", 0)}',
                'image_count': 0,
                'protocol_name': '',
                'body_part_examined': ''
            }
    
    def create_combined_thumbnail_info_widget(self, pixmap, series):
        """DEPRECATED: Use ThumbnailManager.create_thumbnail_widget() for consistency"""
        try:
            widget = QWidget()
            widget.setFixedSize(180, 220)  # Match unified size
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(6, 6, 6, 6)
            layout.setSpacing(3)
            
            # Series header with number
            header_label = QLabel(f"Series {series['series_number']}")
            header_label.setFixedHeight(20)  # Reduced height
            header_label.setAlignment(Qt.AlignCenter)
            header_label.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    font-weight: bold;
                    color: #ffffff;
                    background: transparent;
                    border: none;
                    padding: 2px;
                }
            """)
            layout.addWidget(header_label)
            
             # Thumbnail without internal borders
            image_label = QLabel()
            image_label.setFixedHeight(85)  # Reduced height
            scaled_pixmap = pixmap.scaled(120, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # Reduced image size
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setStyleSheet("""
                 QLabel {
                     background: transparent;
                     border: none;
                     padding: 1px;
                     border-radius: 6px;
                 }
             """)
            layout.addWidget(image_label)
            
            # Info section without internal borders
            info_parts = []
            
            # Modality
            if series.get('modality') and series['modality'] != 'Unknown':
                info_parts.append(f"📊 {series['modality']}")
            
            # Description (shortened)
            if series.get('series_description') and series['series_description'] not in ['No description', '']:
                desc = series['series_description']
                if len(desc) > 15:
                    desc = desc[:12] + "..."
                info_parts.append(f"📝 {desc}")
            
            # Image count
            if series.get('image_count', 0) > 0:
                info_parts.append(f"🖼️ {series['image_count']} images")
            
            # Create info text
            info_text = " • ".join(info_parts) if info_parts else "Series Info"
            
            info_label = QLabel(info_text)
            info_label.setFixedHeight(25)  # Reduced height
            info_label.setAlignment(Qt.AlignCenter)
            info_label.setStyleSheet("""
                QLabel {
                    font-size: 8px;
                    color: #cbd5e0;
                    background: transparent;
                    border: none;
                    padding: 2px;
                }
            """)
            info_label.setWordWrap(True)
            layout.addWidget(info_label)
            
            # Main widget styling - single clean box
            widget.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: 1px solid #4a5568;
                    border-radius: 8px;
                    margin: 2px;
                }
                QWidget:hover {
                    border: 2px solid #667eea;
                    background: #374151;
                }
            """)
            
            # Add click functionality
            widget.mousePressEvent = lambda event: self._on_series_clicked(series['series_number'])
            widget.setCursor(Qt.PointingHandCursor)
            
            return widget
            
        except Exception as e:
            print(f"Error creating combined thumbnail info widget: {str(e)}")
            return self.create_error_widget(f"Error: {str(e)}")
    
    def create_info_row(self, label_text, value_text, icon_name=None):
        """Create a clean info row with optional icon"""
        row_widget = QWidget()
        row_widget.setFixedHeight(20)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.setSpacing(6)
        
        # Icon (if QtAwesome is available and icon_name is provided)
        if QTAWESOME_AVAILABLE and icon_name:
            try:
                icon = qta.icon(icon_name, color='#a0aec0')
                icon_label = QLabel()
                icon_label.setPixmap(icon.pixmap(12, 12))
                icon_label.setFixedSize(12, 12)
                row_layout.addWidget(icon_label)
            except:
                # If icon fails, add empty space
                spacer = QLabel()
                spacer.setFixedSize(12, 12)
                row_layout.addWidget(spacer)
        
        # Label
        label = QLabel(f"{label_text}:")
        label.setStyleSheet("""
            QLabel {
                font-size: 9px;
                color: #a0aec0;
                font-weight: bold;
                min-width: 35px;
            }
        """)
        row_layout.addWidget(label)
        
        # Value
        value = QLabel(value_text)
        value.setStyleSheet("""
            QLabel {
                font-size: 9px;
                color: #e2e8f0;
                font-weight: normal;
            }
        """)
        value.setWordWrap(True)
        row_layout.addWidget(value)
        row_layout.addStretch()
        
        row_widget.setStyleSheet("""
            QWidget {
                background: transparent;
                border: none;
            }
        """)
        
        return row_widget
    
    def create_error_widget(self, error_text):
        """Create a simple error widget"""
        error_widget = QWidget()
        error_widget.setFixedSize(140, 100)
        error_layout = QVBoxLayout(error_widget)
        error_label = QLabel(error_text)
        error_label.setStyleSheet("color: red; font-size: 8px;")
        error_layout.addWidget(error_label)
        return error_widget
    
    def create_series_info_widget(self, series):
        """Create a widget to display series information in a single clean box"""
        try:
            widget = QWidget()
            widget.setFixedSize(140, 90)  # Reduced height
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(6, 6, 6, 6)  # Reduced margins
            layout.setSpacing(2)  # Reduced spacing
            
            # Series header with number
            header_text = f"Series {series['series_number']}"
            header_label = QLabel(header_text)
            header_label.setAlignment(Qt.AlignCenter)
            header_label.setStyleSheet("""
                QLabel {
                    font-size: 9px;
                    font-weight: bold;
                    color: #f7fafc;
                    background: transparent;
                    border: none;
                    padding: 2px 4px;
                }
            """)
            layout.addWidget(header_label)
            
            # All series details in one clean box with emoji icons
            details_parts = []
            
            # Modality
            if series['modality'] and series['modality'] != 'Unknown':
                details_parts.append(f"📊 {series['modality']}")
            
            # Description (shortened)
            if series['series_description'] and series['series_description'] != 'No description':
                desc = series['series_description'][:20]
                if len(series['series_description']) > 20:
                    desc += "..."
                details_parts.append(f"📝 {desc}")
            
            # Image count
            if series['image_count'] > 0:
                details_parts.append(f"🖼️ {series['image_count']} images")
            
            # Protocol name (if available)
            if series.get('protocol_name') and series['protocol_name'].strip():
                protocol = series['protocol_name'][:15]
                if len(series['protocol_name']) > 15:
                    protocol += "..."
                details_parts.append(f"📋 {protocol}")
            
            # Body part (if available)
            if series.get('body_part_examined') and series['body_part_examined'].strip():
                details_parts.append(f"🏥 {series['body_part_examined']}")
            
            # If no details found, show basic info
            if not details_parts:
                details_parts = [
                    f"📊 {series['modality']}",
                    f"📝 Series {series['series_number']}",
                    f"🖼️ {series['image_count']} images"
                ]
            
            # Create details text
            details_text = '\n'.join(details_parts)
            
            details_label = QLabel(details_text)
            details_label.setAlignment(Qt.AlignLeft)
            details_label.setWordWrap(True)
            details_label.setStyleSheet("""
                QLabel {
                    font-size: 7px;
                    color: #e2e8f0;
                    background: transparent;
                    border: none;
                    padding: 2px;
                }
            """)
            layout.addWidget(details_label)
            
            # Main widget styling - single clean box design
            widget.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: 1px solid #4a5568;
                    border-radius: 8px;
                    margin: 2px;
                }
                QWidget:hover {
                    border: 2px solid #3182ce;
                    background: #374151;
                }
            """)
            
            # Add click functionality
            widget.mousePressEvent = lambda event: self._on_series_clicked(series['series_number'])
            widget.setCursor(Qt.PointingHandCursor)
            
            return widget
            
        except Exception as e:
            print(f"Error creating series info widget: {str(e)}")
            # Return a simple error widget
            error_widget = QWidget()
            error_widget.setFixedSize(140, 60)
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Error: {str(e)}")
            error_label.setStyleSheet("color: red; font-size: 8px;")
            error_layout.addWidget(error_label)
            return error_widget
    
    def create_detailed_series_info_widget(self, series):
        """Create a detailed widget to display full series information in one clean box"""
        try:
            widget = QWidget()
            widget.setFixedSize(140, 180)  # Reduced height
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(6, 6, 6, 6)  # Reduced margins
            layout.setSpacing(2)  # Reduced spacing
            
            # Series header
            header_label = QLabel(f"Series {series['series_number']}")
            header_label.setAlignment(Qt.AlignCenter)
            header_label.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    font-weight: bold;
                    color: #f7fafc;
                    background: transparent;
                    border: none;
                    padding: 2px 4px;
                }
            """)
            layout.addWidget(header_label)
            
            # Series details (detailed version) with emoji icons
            details_text = f"""
📊 {series['modality']}
📝 {series['series_description']}
🖼️ {series['image_count']} images
            """.strip()
            
            details_label = QLabel(details_text)
            details_label.setAlignment(Qt.AlignLeft)
            details_label.setWordWrap(True)
            details_label.setStyleSheet("""
                QLabel {
                    font-size: 9px;
                    color: #e2e8f0;
                    background: transparent;
                    border: none;
                    padding: 4px;
                }
            """)
            layout.addWidget(details_label)
            
            # Additional info if available (detailed) with emoji icons
            if series.get('protocol_name') or series.get('body_part_examined'):
                extra_info = []
                if series.get('protocol_name'):
                    extra_info.append(f"📋 {series['protocol_name']}")
                if series.get('body_part_examined'):
                    extra_info.append(f"🏥 {series['body_part_examined']}")
                
                if extra_info:
                    extra_label = QLabel('\n'.join(extra_info))
                    extra_label.setAlignment(Qt.AlignLeft)
                    extra_label.setWordWrap(True)
                    extra_label.setStyleSheet("""
                        QLabel {
                            font-size: 8px;
                            color: #cbd5e1;
                            background: transparent;
                            border: none;
                            padding: 3px;
                        }
                    """)
                    layout.addWidget(extra_label)
            
            # Main widget styling - single clean box
            widget.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: 1px solid #4a5568;
                    border-radius: 8px;
                    margin: 2px;
                }
                QWidget:hover {
                    border: 2px solid #3182ce;
                    background: #374151;
                }
            """)
            
            # Add click functionality
            widget.mousePressEvent = lambda event: self._on_series_clicked(series['series_number'])
            widget.setCursor(Qt.PointingHandCursor)
            
            return widget
            
        except Exception as e:
            print(f"Error creating detailed series info widget: {str(e)}")
            # Return a simple error widget
            error_widget = QWidget()
            error_widget.setFixedSize(140, 100)
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Error: {str(e)}")
            error_label.setStyleSheet("color: red; font-size: 10px;")
            error_layout.addWidget(error_label)
            return error_widget
    
    def create_thumbnail_widget(self, pixmap, label_text):
        """Create thumbnail widget with image"""
        try:
            widget = QWidget()
            widget.setFixedSize(140, 140)  # Reduced height
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(3, 3, 3, 3)  # Reduced margins
            layout.setSpacing(2)  # Reduced spacing
            
            # Image container
            image_container = QWidget()
            image_container.setFixedSize(132, 100)  # Reduced height
            image_container.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: 1px solid #4a5568;
                    border-radius: 8px;
                }
            """)
            
            image_layout = QVBoxLayout(image_container)
            image_layout.setContentsMargins(2, 2, 2, 2)  # Reduced margins
            
            image_label = QLabel()
            scaled_pixmap = pixmap.scaled(126, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)  # Reduced image size
            image_label.setPixmap(scaled_pixmap)
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setStyleSheet("border: none; border-radius: 6px;")
            image_layout.addWidget(image_label)
            
            layout.addWidget(image_container)
            
            # Series label
            text_label = QLabel(f"Series {label_text}")
            text_label.setAlignment(Qt.AlignCenter)
            text_label.setWordWrap(True)
            text_label.setStyleSheet("""
                QLabel {
                    font-size: 10px;
                    color: #f7fafc;
                    background: #4a5568;
                    border-radius: 8px;
                    padding: 2px 4px;
                }
            """)
            layout.addWidget(text_label)
            
            # Main widget styling
            widget.setStyleSheet("""
                QWidget {
                    background: #1a202c;
                    border: 1px solid #4a5568;
                    border-radius: 8px;
                    margin: 2px;
                }
                QWidget:hover {
                    border: 1px solid #3182ce;
                    background: #2d3748;
                }
            """)
            
            # Add click functionality
            widget.mousePressEvent = lambda event: self._on_thumbnail_clicked(label_text)
            widget.setCursor(Qt.PointingHandCursor)
            
            return widget
            
        except Exception as e:
            print(f"Error creating thumbnail widget: {str(e)}")
            # Return a simple error widget
            error_widget = QWidget()
            error_widget.setFixedSize(140, 100)
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Thumbnail Error: {str(e)}")
            error_label.setStyleSheet("color: red; font-size: 10px;")
            error_layout.addWidget(error_label)
            return error_widget
    
    def create_study_stats_widget(self, stats, study_info):
        """Create a widget to display study statistics in one clean box"""
        try:
            widget = QWidget()
            widget.setFixedSize(140, 120)
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(4)
            
            # Study header with emoji icon
            study_header = QLabel("📈 Study Stats")
            study_header.setAlignment(Qt.AlignCenter)
            study_header.setStyleSheet("""
                QLabel {
                    font-size: 11px;
                    font-weight: bold;
                    color: #f7fafc;
                    background: transparent;
                    border: none;
                    padding: 4px 6px;
                }
            """)
            layout.addWidget(study_header)
            
            # Statistics with emoji icons
            stats_text = f"""
📊 {stats['total_series']} series
🖼️ {stats['total_images']} images
📈 Avg: {stats['average_images_per_series']}
            """.strip()
            
            stats_label = QLabel(stats_text)
            stats_label.setAlignment(Qt.AlignLeft)
            stats_label.setStyleSheet("""
                QLabel {
                    font-size: 10px;
                    color: #e2e8f0;
                    background: transparent;
                    border: none;
                    padding: 8px;
                }
            """)
            layout.addWidget(stats_label)
            
            # Modalities with emoji icon
            modalities_text = "🔬 " + ", ".join([f"{mod}: {count}" for mod, count in stats['modalities'].items()])
            modalities_label = QLabel(modalities_text)
            modalities_label.setAlignment(Qt.AlignLeft)
            modalities_label.setWordWrap(True)
            modalities_label.setStyleSheet("""
                QLabel {
                    font-size: 9px;
                    color: #cbd5e1;
                    background: transparent;
                    border: none;
                    padding: 6px;
                }
            """)
            layout.addWidget(modalities_label)
            
            # Main widget styling - single clean box
            widget.setStyleSheet("""
                QWidget {
                    background: #2d3748;
                    border: 1px solid #4a5568;
                    border-radius: 8px;
                    margin: 2px;
                }
            """)
            
            return widget
            
        except Exception as e:
            print(f"Error creating stats widget: {str(e)}")
            # Return a simple error widget
            error_widget = QWidget()
            error_widget.setFixedSize(140, 80)
            error_layout = QVBoxLayout(error_widget)
            error_label = QLabel(f"Stats Error: {str(e)}")
            error_label.setStyleSheet("color: red; font-size: 10px;")
            error_layout.addWidget(error_label)
            return error_widget
    
    def get_series_statistics(self, series_list):
        """Get statistics from series list"""
        try:
            if not series_list:
                return None
            
            total_series = len(series_list)
            total_images = sum(s.get('image_count', 0) for s in series_list)
            
            # Count modalities
            modalities = {}
            for series in series_list:
                modality = series.get('modality', 'Unknown')
                modalities[modality] = modalities.get(modality, 0) + 1
            
            # Calculate average
            average_images = total_images / total_series if total_series > 0 else 0
            
            return {
                'total_series': total_series,
                'total_images': total_images,
                'modalities': modalities,
                'average_images_per_series': round(average_images, 2)
            }
            
        except Exception as e:
            print(f"Error in get_series_statistics: {str(e)}")
            return None
    
    def _on_series_clicked(self, series_number):
        """Handle series click event"""
        self.seriesInfoRequested.emit(str(series_number))
    
    def _on_thumbnail_clicked(self, series_number):
        """Handle thumbnail click event"""
        self.thumbnailClicked.emit(str(series_number))
