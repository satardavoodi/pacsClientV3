"""
Priority Dialog - Priority change confirmation

Dialog for changing download priority.
"""

import logging
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox
from PySide6.QtCore import Qt

from ...core.enums import DownloadPriority

logger = logging.getLogger(__name__)


class PriorityDialog(QDialog):
    """
    Priority change dialog
    
    Allows user to change download priority with explanation of effects.
    """
    
    def __init__(
        self,
        current_priority: DownloadPriority,
        patient_name: str,
        parent=None
    ):
        """
        Initialize priority dialog
        
        Args:
            current_priority: Current priority
            patient_name: Patient name
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.current_priority = current_priority
        self.patient_name = patient_name
        self.selected_priority = current_priority
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup dialog UI"""
        self.setWindowTitle("Change Priority")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Title
        title = QLabel(f"Change download priority for:\n{self.patient_name}")
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(title)
        
        # Priority combo
        self.priority_combo = QComboBox()
        for priority in DownloadPriority:
            self.priority_combo.addItem(priority.display_name, priority)
        
        # Set current priority
        for i in range(self.priority_combo.count()):
            if self.priority_combo.itemData(i) == self.current_priority:
                self.priority_combo.setCurrentIndex(i)
                break
        
        self.priority_combo.currentIndexChanged.connect(self._on_priority_changed)
        layout.addWidget(self.priority_combo)
        
        # Description label
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: #64748b; font-size: 12px;")
        layout.addWidget(self.description_label)
        
        self._update_description()
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
    
    def _on_priority_changed(self, index: int) -> None:
        """Handle priority change"""
        self.selected_priority = self.priority_combo.itemData(index)
        self._update_description()
    
    def _update_description(self) -> None:
        """Update description based on selected priority"""
        descriptions = {
            DownloadPriority.CRITICAL: "⚠️ CRITICAL: Pauses ALL other downloads. Only ONE critical download at a time.",
            DownloadPriority.HIGH: "⬆️ HIGH: Will preempt NORMAL and LOW priority downloads.",
            DownloadPriority.NORMAL: "➡️ NORMAL: Standard priority. FIFO queue processing.",
            DownloadPriority.LOW: "⬇️ LOW: Background download. Only runs when no higher priorities pending.",
        }
        
        self.description_label.setText(descriptions.get(self.selected_priority, ""))
    
    def get_selected_priority(self) -> DownloadPriority:
        """Get selected priority"""
        return self.selected_priority
