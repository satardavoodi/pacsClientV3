from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QSplitter, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class CombinedTabWidget(QWidget):
    """
    A combined widget that includes both the main widget and text content as a single tab
    """
    
    def __init__(self, main_widget, title="", description="", parent=None):
        super().__init__(parent)
        self.main_widget = main_widget
        self.title = title
        self.description = description
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the combined UI with widget and text"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Main content area with splitter
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        
        # Main widget area
        main_widget_frame = QFrame()
        main_widget_frame.setObjectName("MainWidgetFrame")
        main_widget_frame.setStyleSheet("""
            QFrame#MainWidgetFrame {
                background: #1a202c;
                border: 1px solid #4a5568;
                border-radius: 8px;
            }
        """)
        
        main_widget_layout = QVBoxLayout(main_widget_frame)
        main_widget_layout.setContentsMargins(8, 8, 8, 8)
        main_widget_layout.addWidget(self.main_widget)
        
        # Text area
        text_frame = QFrame()
        text_frame.setObjectName("TextFrame")
        text_frame.setStyleSheet("""
            QFrame#TextFrame {
                background: #1a202c;
                border: 1px solid #4a5568;
                border-radius: 8px;
            }
        """)
        
        text_layout = QVBoxLayout(text_frame)
        text_layout.setContentsMargins(8, 8, 8, 8)
        
        # Text area label
        text_label = QLabel("Information & Help")
        text_label.setFont(QFont('Roboto', 14, QFont.Weight.Medium))
        text_label.setStyleSheet("color: #ffffff; margin-bottom: 8px;")
        text_layout.addWidget(text_label)
        
        # Text edit area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet("""
            QTextEdit {
                background: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 6px;
                color: #e2e8f0;
                font-family: 'Roboto', sans-serif;
                font-size: 12px;
                line-height: 1.5;
                padding: 8px;
            }
        """)
        self.text_edit.setMaximumWidth(300)
        self.text_edit.setMinimumWidth(250)
        
        # Set default text based on widget type
        self.set_default_text()
        
        text_layout.addWidget(self.text_edit)
        
        # Add widgets to splitter
        splitter.addWidget(main_widget_frame)
        splitter.addWidget(text_frame)
        
        # Set splitter proportions (main widget gets more space)
        splitter.setSizes([800, 300])
        
        layout.addWidget(splitter)
        
    def set_default_text(self):
        """Set default text based on the main widget type"""
        if "DownloadManager" in str(type(self.main_widget)):
            self.text_edit.setHtml("""
                <h3 style="color: #3b82f6; margin-bottom: 10px;">Download Manager</h3>
                <p style="margin-bottom: 8px;"><strong>Features:</strong></p>
                <ul style="margin-left: 15px; margin-bottom: 8px;">
                    <li>Manage multiple downloads simultaneously</li>
                    <li>Pause, resume, and cancel downloads</li>
                    <li>Set download priorities</li>
                    <li>Monitor download progress</li>
                    <li>View download history</li>
                </ul>
                <p style="margin-bottom: 8px;"><strong>Usage:</strong></p>
                <p style="margin-bottom: 8px;">1. Select files or studies to download</p>
                <p style="margin-bottom: 8px;">2. Choose download location</p>
                <p style="margin-bottom: 8px;">3. Set priority level</p>
                <p style="margin-bottom: 8px;">4. Monitor progress in the queue</p>
                <p style="color: #a0aec0; font-size: 11px; margin-top: 15px;">
                    <em>Tip: You can drag and drop files to reorder download priority.</em>
                </p>
            """)
        elif "AiMainWindow" in str(type(self.main_widget)):
            self.text_edit.setHtml("""
                <h3 style="color: #7c3aed; margin-bottom: 10px;">AI Analysis Tools</h3>
                <p style="margin-bottom: 8px;"><strong>Available Tools:</strong></p>
                <ul style="margin-left: 15px; margin-bottom: 8px;">
                    <li><strong>Imaging Tools:</strong> Advanced image processing and analysis</li>
                    <li><strong>Model Training:</strong> Train custom AI models</li>
                    <li><strong>AI Chat:</strong> Interactive AI assistance</li>
                    <li><strong>Segmentation:</strong> Automated image segmentation</li>
                </ul>
                <p style="margin-bottom: 8px;"><strong>Getting Started:</strong></p>
                <p style="margin-bottom: 8px;">1. Select the tool you want to use</p>
                <p style="margin-bottom: 8px;">2. Load your medical images</p>
                <p style="margin-bottom: 8px;">3. Configure analysis parameters</p>
                <p style="margin-bottom: 8px;">4. Run the analysis</p>
                <p style="color: #a0aec0; font-size: 11px; margin-top: 15px;">
                    <em>Note: Some AI features may require additional model downloads.</em>
                </p>
            """)
        else:
            self.text_edit.setHtml("""
                <h3 style="color: #ffffff; margin-bottom: 10px;">Information Panel</h3>
                <p style="margin-bottom: 8px;">This panel provides context and help information for the current tool or feature.</p>
                <p style="margin-bottom: 8px;">Use the main area to interact with the application features.</p>
                <p style="color: #a0aec0; font-size: 11px; margin-top: 15px;">
                    <em>For more help, check the documentation or contact support.</em>
                </p>
            """)
    
    def update_text(self, html_content):
        """Update the text content with custom HTML"""
        self.text_edit.setHtml(html_content)
    
    def append_text(self, text):
        """Append text to the current content"""
        current_text = self.text_edit.toPlainText()
        self.text_edit.setPlainText(current_text + "\n" + text)
