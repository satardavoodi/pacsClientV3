from PySide6.QtWidgets import QTabWidget, QTabBar, QWidget, QHBoxLayout, QSizePolicy, QPushButton, QLabel
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from .patient_tab_widget import PatientTabWidget
from .service_tab_widget import ServiceTabWidget
import os
import logging

# Priority management is now handled by Zeta Download Manager
# Legacy priority manager has been removed
PRIORITY_MANAGER_AVAILABLE = False

logger = logging.getLogger(__name__)


class CustomTabManager:
    """
    Manages custom patient tabs with beautiful UI integrated into title bar
    Prevents duplicate tabs for the same patient using study_uid
    """
    
    def __init__(self, tab_widget: QTabWidget, title_bar_tab_area=None):
        self.tab_widget = tab_widget
        self.title_bar_tab_area = title_bar_tab_area
        self.patient_tabs = {}  # Store patient tab widgets
        self.title_bar_tabs = {}  # Store title bar tab widgets
        self.study_uid_to_tab = {}  # Map study_uid to tab_index to prevent duplicates

        if title_bar_tab_area:
            self.setup_title_bar_tabs()
        else:
            self.setup_custom_tab_bar()
        
        # Connect tab change signal
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        

    
    def setup_title_bar_tabs(self):
        """Setup tabs in the title bar area"""
        if not self.title_bar_tab_area:
            return
            
        # Create layout for title bar tabs
        self.title_bar_layout = QHBoxLayout(self.title_bar_tab_area)
        self.title_bar_layout.setContentsMargins(10, 5, 5, 5)
        self.title_bar_layout.setSpacing(4)
        
        # Add AIPacs logo button at the beginning
        from PySide6.QtWidgets import QPushButton, QLabel
        from PySide6.QtGui import QPixmap, QIcon
        from PySide6.QtCore import QSize
        
        # Create logo button
        self.logo_button = QPushButton()
        self.logo_button.setObjectName("LogoButton")
        self.logo_button.setFixedSize(70, 70)  # Reduced by 30% from 100x100
        self.logo_button.setCursor(Qt.PointingHandCursor)
        
        # Set logo icon (you can replace this with your actual logo path)
        # For now, we'll create a simple text-based logo
        self.logo_button.setText("AI PACS")
        self.logo_button.setToolTip("Click to show patient list")
        
        # Connect click event to show patient list
        self.logo_button.clicked.connect(self.show_patient_list)
        
        # Set initial state (inactive)
        self.logo_button.setProperty("active", False)
        
        # Force size policy to prevent layout from changing the size
        self.logo_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        # Apply custom CSS to ensure proper sizing
        self.logo_button.setStyleSheet("""
            QPushButton#LogoButton {
                background: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 8px;
                color: #ffffff;
                font-size: 12px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial, sans-serif;
                padding: 0px;
                margin: 0px;
                text-align: center;
                width: 70px !important;
                min-width: 70px !important;
                max-width: 70px !important;
            }
            
            QPushButton#LogoButton[active="true"] {
                background: #4a5568;
                border: 2px solid #63b3ed;
                color: #ffffff;
                font-weight: bold;
            }
            
            QPushButton#LogoButton:hover {
                background: #4a5568;
                border: 1px solid #63b3ed;
            }
            
            QPushButton#LogoButton[active="true"]:hover {
                background: #5a6a7a;
                border: 2px solid #7bb3ed;
            }
            
            QPushButton#LogoButton:pressed {
                background: #2d3748;
                border: 2px solid #3182ce;
            }
            
            QPushButton#LogoButton[active="true"]:pressed {
                background: #3a4a5a;
                border: 2px solid #3182ce;
            }
        """)
        
        self.logo_button.setStyle(self.logo_button.style())
        
        self.title_bar_layout.addWidget(self.logo_button)
        
        # Force immediate layout update
        self.logo_button.updateGeometry()
        self.logo_button.update()
        
        # Add some spacing after the logo
        self.title_bar_layout.addSpacing(10)
        
        # Hide the original tab bar
        self.tab_widget.tabBar().setVisible(False)
        
        # Style the title bar tab area
        self.title_bar_tab_area.setStyleSheet("""
            QFrame {
                background: transparent;
                border: none;
            }
        """)
        
        # Force layout update after everything is set up
        self.title_bar_layout.update()
        if hasattr(self, 'logo_button'):
            self.logo_button.updateGeometry()
            self.logo_button.update()
    
    def setup_custom_tab_bar(self):
        """Setup custom tab bar styling"""
        self.tab_widget.setTabBarAutoHide(False)
        self.tab_widget.setElideMode(Qt.ElideRight)
        
        # Apply custom styling to tab widget - allow custom tab widgets to show their styling
        self.tab_widget.setStyleSheet("""
                   QTabWidget::pane {
                       border: 4px solid #4A5568;
                       border-radius: 12px;
                       background: #1a202c;
                       margin: 4px;
                   }
                   
                   QTabBar::tab {
                       background: transparent;
                       border: none;
                       padding: 0px;
                       margin: 0px;
                       min-width: 180px;
                       height: 50px;
                   }
                   
                   QTabBar::tab:selected {
                       background: transparent;
                       border: none;
                   }
                   
                   QTabBar::tab:hover:!selected {
                       background: transparent;
                       border: none;
                   }
                   
                   QTabBar::close-button {
                       background: rgba(239, 68, 68, 0.7);
                       border-radius: 8px;
                       width: 16px;
                       height: 16px;
                       margin: 2px;
                       subcontrol-position: top right;
                       subcontrol-origin: margin;
                   }
                   
                   QTabBar::close-button:hover {
                       background: rgba(239, 68, 68, 1.0);
                   }
                   
                   QTabBar::close-button {
                       color: white;
                       font-size: 12px;
                       font-weight: bold;
                   }
                   QPushButton#LogoButton {
                       background: #2d3748;
                       border: 1px solid #4a5568;
                       border-radius: 8px;
                       color: #ffffff;
                       font-size: 14px;
                       font-weight: bold;
                       font-family: 'Segoe UI', Arial, sans-serif;
                       padding: 0px;
                       margin: 0px;
                       text-align: center;
                       width: 100px !important;
                       min-width: 100px !important;
                       max-width: 100px !important;
                       height: 40px !important;
                       min-height: 40px !important;
                       max-height: 40px !important;
                   }
                   
                   QPushButton#LogoButton[active="true"] {
                       background: #4a5568;
                       border: 2px solid #63b3ed;
                       color: #ffffff;
                       font-weight: bold;
                   }
                   
                   QPushButton#LogoButton:hover {
                       background: #4a5568;
                       border: 1px solid #63b3ed;
                   }
                   
                   QPushButton#LogoButton[active="true"]:hover {
                       background: #5a6a7a;
                       border: 2px solid #7bb3ed;
                   }
                   
                   QPushButton#LogoButton:pressed {
                       background: #2d3748;
                       border: 2px solid #3182ce;
                   }
                   
                   QPushButton#LogoButton[active="true"]:pressed {
                       background: #3a4a5a;
                       border: 2px solid #3182ce;
                   }
                   
                
               """)
    
    def add_patient_tab(self, patient_name, patient_id, thumbnail_path=None, widget=None, study_uid=None, activate=True):
        """
        Add a new patient tab with custom UI
        Prevents duplicate tabs for the same patient using study_uid
        
        Args:
            patient_name: Name of the patient
            patient_id: Patient ID
            thumbnail_path: Path to first thumbnail image
            widget: The widget to display in the tab
            study_uid: Study Instance UID to prevent duplicates
            activate: Whether to activate (switch to) the tab immediately
        """
        # Check if a tab already exists for this study_uid
        if study_uid and study_uid in self.study_uid_to_tab:
            existing_tab_index = self.study_uid_to_tab[study_uid]
            
            # Switch to existing tab only if activate is True
            if activate:
                self.tab_widget.setCurrentIndex(existing_tab_index)
                self.set_tab_active(existing_tab_index)
            
            # Update the existing tab with new information if provided
            if patient_name or patient_id or thumbnail_path:
                self.update_patient_tab(existing_tab_index, patient_name, patient_id, thumbnail_path)
            
            return existing_tab_index
        
        # Create custom tab widget
        custom_tab = PatientTabWidget(
            patient_name=patient_name,
            patient_id=patient_id,
            thumbnail_path=thumbnail_path,
            study_uid=study_uid
        )
        
        # Add tab to tab widget
        tab_index = self.tab_widget.addTab(widget, "")
        
        # Connect close button signal after tab_index is available
        custom_tab.close_requested.connect(lambda: self.close_patient_tab(tab_index))

        if self.title_bar_tab_area:
            # Add to title bar
            self.add_tab_to_title_bar(custom_tab, tab_index)
        else:
            # Set custom tab widget as tab button
            self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.LeftSide, custom_tab)
        
        # Store reference
        self.patient_tabs[tab_index] = {
            'custom_tab': custom_tab,
            'patient_name': patient_name,
            'patient_id': patient_id,
            'study_uid': study_uid,
            'widget': widget
        }
        
        # Store study_uid to tab mapping for duplicate prevention
        if study_uid:
            self.study_uid_to_tab[study_uid] = tab_index
        
        # Set as current tab ONLY if activate is True
        if activate:
            self.tab_widget.setCurrentIndex(tab_index)
            # Set this tab as active
            self.set_tab_active(tab_index)
        
        return tab_index
    
    def add_tab_to_title_bar(self, custom_tab, tab_index):
        """Add a tab to the title bar area"""
        if not self.title_bar_tab_area:
            return
            
        # Make tab clickable
        custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
        
        # Add to title bar layout
        self.title_bar_layout.addWidget(custom_tab)
        
        # Store reference
        self.title_bar_tabs[tab_index] = custom_tab
    
    def on_title_bar_tab_clicked(self, tab_index):
        """Handle title bar tab click"""
        if 0 <= tab_index < self.tab_widget.count():
            self.tab_widget.setCurrentIndex(tab_index)
            self.set_tab_active(tab_index)
    
    def update_patient_tab(self, tab_index, patient_name=None, patient_id=None, thumbnail_path=None):
        """
        Update patient information in existing tab
        
        Args:
            tab_index: Index of the tab to update
            patient_name: New patient name
            patient_id: New patient ID
            thumbnail_path: New thumbnail path
        """
        
        if tab_index in self.patient_tabs:
            custom_tab = self.patient_tabs[tab_index]['custom_tab']
            
            # Check if this is a PatientTabWidget (has update_patient_info method)
            # ServiceTabWidget and other service tabs don't have this method
            if hasattr(custom_tab, 'update_patient_info') and callable(getattr(custom_tab, 'update_patient_info')):
                try:
                    custom_tab.update_patient_info(patient_name, patient_id, thumbnail_path)
                    
                    # Update stored information
                    if patient_name and patient_name != 'N/A':
                        self.patient_tabs[tab_index]['patient_name'] = patient_name
                    if patient_id and patient_id != 'N/A':
                        self.patient_tabs[tab_index]['patient_id'] = patient_id
                except Exception as e:
                    print(f"[CustomTabManager] Error updating patient tab {tab_index}: {e}")
            else:
                # ✅ FIX: This is a service tab (Download Manager, Education, etc.) - silently ignore
                # Service tabs don't need patient info updates
                pass
        else:
            # ✅ FIX: Silently ignore - tab may be a system tab (Download Manager, Education, etc.)
            pass  # This is normal for system tabs
    
    def remove_patient_tab(self, tab_index):
        """
        Remove a patient tab
        
        Args:
            tab_index: Index of the tab to remove
        """
        if tab_index in self.patient_tabs:
            # Remove study_uid mapping
            tab_data = self.patient_tabs[tab_index]
            study_uid = tab_data.get('study_uid')
            
            # Legacy priority manager removed - Zeta handles priority internally
            # if study_uid and PRIORITY_MANAGER_AVAILABLE:
            #     priority_manager = get_download_priority_manager()
            #     priority_manager.on_patient_tab_closed(study_uid)
            if study_uid:
                logger.debug(f"Tab closed for study {study_uid[:20]}...")
            
            if study_uid and study_uid in self.study_uid_to_tab:
                del self.study_uid_to_tab[study_uid]
            
            # Remove from tab widget
            self.tab_widget.removeTab(tab_index)
            
            # Remove from stored tabs
            del self.patient_tabs[tab_index]
            
            # Update indices for remaining tabs
            new_patient_tabs = {}
            new_study_uid_to_tab = {}
            
            for old_index, tab_data in self.patient_tabs.items():
                if old_index > tab_index:
                    new_index = old_index - 1
                    new_patient_tabs[new_index] = tab_data
                    # Update study_uid mapping
                    study_uid = tab_data.get('study_uid')
                    if study_uid:
                        new_study_uid_to_tab[study_uid] = new_index
                else:
                    new_patient_tabs[old_index] = tab_data
                    # Keep study_uid mapping
                    study_uid = tab_data.get('study_uid')
                    if study_uid:
                        new_study_uid_to_tab[study_uid] = old_index
            
            self.patient_tabs = new_patient_tabs
            self.study_uid_to_tab = new_study_uid_to_tab
    
    def get_patient_tab_info(self, tab_index):
        """
        Get patient information for a specific tab
        
        Args:
            tab_index: Index of the tab
            
        Returns:
            dict: Patient information or None if not found
        """
        return self.patient_tabs.get(tab_index)
    
    def find_tab_by_study_uid(self, study_uid):
        """
        Find tab index by study UID
        
        Args:
            study_uid: Study Instance UID to search for
            
        Returns:
            int: Tab index or -1 if not found
        """
        return self.study_uid_to_tab.get(study_uid, -1)
    
    def find_tab_by_patient_id(self, patient_id):
        """
        Find tab index by patient ID
        
        Args:
            patient_id: Patient ID to search for
            
        Returns:
            int: Tab index or -1 if not found
        """
        for tab_index, tab_data in self.patient_tabs.items():
            if tab_data['patient_id'] == patient_id:
                return tab_index
        return -1

    def get_all_patient_tabs(self):
        """
        Get all patient tab information

        Returns:
            dict: All patient tabs with their information
        """
        return self.patient_tabs.copy()


    def get_current_patient_info(self):
        """
        Get information of currently active patient tab

        Returns:
            dict: Current patient information or None
        """
        current_index = self.tab_widget.currentIndex()
        return self.get_patient_tab_info(current_index)
    
    def on_tab_changed(self, index):
        """Handle tab change events"""
        
        # Set all tabs as inactive first
        for tab_data in self.patient_tabs.values():
            if hasattr(tab_data['custom_tab'], 'set_active'):
                tab_data['custom_tab'].set_active(False)
        
        # Set current tab as active
        if index in self.patient_tabs:
            tab_data = self.patient_tabs[index]
            if hasattr(tab_data['custom_tab'], 'set_active'):
                tab_data['custom_tab'].set_active(True)
                # Set logo button as inactive when patient tab is selected
                self.set_logo_active(False)
            
            # Legacy priority manager removed - Zeta handles priority internally
            # if study_uid and PRIORITY_MANAGER_AVAILABLE:
            #     priority_manager = get_download_priority_manager()
            #     priority_manager.on_patient_tab_activated(study_uid)
            study_uid = tab_data.get('study_uid')
            if study_uid:
                logger.debug(f"Tab activated for study {study_uid[:20]}...")
        else:
            # If switching to patient list tab (index 0), set logo as active
            if index == 0:
                self.set_logo_active(True)
            else:
                self.set_logo_active(False)
    
    def show_patient_list(self):
        """Show patient list when logo is clicked"""
        
        # Switch to the main tab (index 0) which contains the patient list
        if self.tab_widget.count() > 0:
            self.tab_widget.setCurrentIndex(0)
            # Set logo button as active
            self.set_logo_active(True)
    
    def set_logo_active(self, active=True):
        """Set the logo button as active or inactive"""
        if hasattr(self, 'logo_button'):
            self.logo_button.setProperty("active", active)
            
            # Apply complete CSS with all states
            self.logo_button.setStyleSheet("""
                QPushButton#LogoButton {
                    background: #2d3748;
                    border: 1px solid #4a5568;
                    border-radius: 8px;
                    color: #ffffff;
                    font-size: 12px;
                    font-weight: bold;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    padding: 0px;
                    margin: 0px;
                    text-align: center;
                    width: 70px !important;
                    min-width: 70px !important;
                    max-width: 70px !important;
                }
                
                QPushButton#LogoButton[active="true"] {
                    background: #4a5568;
                    border: 2px solid #63b3ed;
                    color: #ffffff;
                    font-weight: bold;
                }
                
                QPushButton#LogoButton:hover {
                    background: #4a5568;
                    border: 1px solid #63b3ed;
                }
                
                QPushButton#LogoButton[active="true"]:hover {
                    background: #5a6a7a;
                    border: 2px solid #7bb3ed;
                }
                
                QPushButton#LogoButton:pressed {
                    background: #2d3748;
                    border: 2px solid #3182ce;
                }
                
                QPushButton#LogoButton[active="true"]:pressed {
                    background: #3a4a5a;
                    border: 2px solid #3182ce;
                }
            """)
            
            # Force style update to apply active state
            self.logo_button.setStyle(self.logo_button.style())
            self.logo_button.update()
            self.logo_button.repaint()
    
    def close_patient_tab(self, tab_index):
        """Close a specific patient tab"""
        if tab_index in self.patient_tabs:
            # Remove study_uid mapping
            tab_data = self.patient_tabs[tab_index]
            study_uid = tab_data.get('study_uid')
            if study_uid and study_uid in self.study_uid_to_tab:
                del self.study_uid_to_tab[study_uid]

            # Remove from our tracking
            tab_data = self.patient_tabs.pop(tab_index)

            # Remove from title bar if using title bar tabs
            if self.title_bar_tab_area and tab_index in self.title_bar_tabs:
                title_bar_tab = self.title_bar_tabs.pop(tab_index)
                title_bar_tab.setParent(None)
                title_bar_tab.deleteLater()

            # # Remove from tab widget
            # self.tab_widget.removeTab(tab_index)
            self.tab_widget.tabCloseRequested.emit(tab_index)

            # Update remaining tab indices and study_uid mappings
            self.update_tab_indices()
            
            # After closing, activate logo button (Home tab)
            self.set_logo_active(True)

    def update_tab_indices(self):
        """Update tab indices after closing a tab"""
        # Rebuild study_uid to tab mapping with correct indices
        new_study_uid_to_tab = {}
        for tab_index, tab_data in self.patient_tabs.items():
            study_uid = tab_data.get('study_uid')
            if study_uid:
                new_study_uid_to_tab[study_uid] = tab_index
        
        self.study_uid_to_tab = new_study_uid_to_tab
    
    def set_tab_active(self, tab_index):
        """
        Set a specific tab as active and update visual state
        
        Args:
            tab_index: Index of the tab to activate
        """
        
        if 0 <= tab_index < self.tab_widget.count():
            # Set all tabs as inactive first
            for idx, tab_data in self.patient_tabs.items():
                if hasattr(tab_data['custom_tab'], 'set_active'):
                    tab_data['custom_tab'].set_active(False)
            
            # Set the specified tab as active
            if tab_index in self.patient_tabs:
                tab_data = self.patient_tabs[tab_index]
                if hasattr(tab_data['custom_tab'], 'set_active'):
                    tab_data['custom_tab'].set_active(True)
            
            # Set as current tab
            self.tab_widget.setCurrentIndex(tab_index)
    
    def add_reception_data_tab(self, widget=None):
        """
        Add Reception Data tab with simple tab UI
        
        Args:
            widget: The ReceptionDataTab widget to display
        
        Returns:
            int: The index of the added tab
        """
        print("[CustomTabManager] add_reception_data_tab called")
        
        # Create simple tab button
        tab_button = QPushButton("Reception Data")
        tab_button.setObjectName("ReceptionDataTabButton")
        tab_button.setFixedSize(105, 28)  # Reduced by 30% from 150x40
        tab_button.setStyleSheet("""
            QPushButton#ReceptionDataTabButton {
                background: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 6px;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                font-family: 'Segoe UI', Arial, sans-serif;
                padding: 3px;
                text-align: center;
            }
            
            QPushButton#ReceptionDataTabButton[active="true"] {
                background: #4a5568;
                border: 2px solid #63b3ed;
                color: #ffffff;
            }
            
            QPushButton#ReceptionDataTabButton:hover {
                background: #4a5568;
                border: 1px solid #63b3ed;
            }
            
            QPushButton#ReceptionDataTabButton[active="true"]:hover {
                background: #5a6a7a;
                border: 2px solid #7bb3ed;
            }
        """)
        
        # Add tab to tab widget
        tab_index = self.tab_widget.addTab(widget, "")
        print(f"[CustomTabManager] Tab added at index: {tab_index}")
        
        if self.title_bar_tab_area:
            # Add to title bar
            self.title_bar_layout.addWidget(tab_button)
            tab_button.clicked.connect(lambda: self.set_tab_active_simple(tab_index))
            self.title_bar_tabs[tab_index] = tab_button
        else:
            # Set custom tab widget as tab button
            self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.LeftSide, tab_button)
        
        # Store reference (without study_uid)
        self.patient_tabs[tab_index] = {
            'custom_tab': tab_button,
            'widget': widget,
            'is_reception_tab': True
        }
        
        # Set as current tab
        self.tab_widget.setCurrentIndex(tab_index)
        print(f"[CustomTabManager] Reception Data tab added successfully")
        
        return tab_index
    
    def set_tab_active_simple(self, tab_index):
        """Set a simple tab (like Reception Data) as active"""
        print(f"[CustomTabManager] set_tab_active_simple called for index: {tab_index}")
        if 0 <= tab_index < self.tab_widget.count():
            # Set all tabs as inactive first
            for idx, tab_data in self.patient_tabs.items():
                if 'custom_tab' in tab_data:
                    tab_data['custom_tab'].setProperty("active", "false")
                    tab_data['custom_tab'].style().unpolish(tab_data['custom_tab'])
                    tab_data['custom_tab'].style().polish(tab_data['custom_tab'])
            
            # Set the specified tab as active
            if tab_index in self.patient_tabs:
                tab_data = self.patient_tabs[tab_index]
                if 'custom_tab' in tab_data:
                    tab_data['custom_tab'].setProperty("active", "true")
                    tab_data['custom_tab'].style().unpolish(tab_data['custom_tab'])
                    tab_data['custom_tab'].style().polish(tab_data['custom_tab'])
            
            # Set as current tab
            self.tab_widget.setCurrentIndex(tab_index)
    
    def add_download_manager_tab(self, widget=None, activate=True):
        """
        Add Download Manager tab with custom tab UI (like patient tabs)
        
        Args:
            widget: The DownloadManagerWidget to display
            activate: Whether to activate/switch to the tab after creation
        
        Returns:
            int: The index of the added tab
        """
        print("[CustomTabManager] add_download_manager_tab called")
        
        # Check if download manager tab already exists
        for idx, tab_data in self.patient_tabs.items():
            if tab_data.get('is_download_manager_tab', False):
                print("[CustomTabManager] Download Manager tab already exists, switching to it")
                if activate:
                    self.set_tab_active_simple(idx)
                return idx
        
        # Create custom tab widget with icon
        custom_tab = ServiceTabWidget(
            service_name="Download Manager",
            icon_name="fa5s.download",
            icon_color="white"
        )
        
        # Add tab to tab widget
        tab_index = self.tab_widget.addTab(widget, "")
        print(f"[CustomTabManager] Download Manager tab added at index: {tab_index}")
        
        # Connect close button signal
        custom_tab.close_requested.connect(lambda: self.close_patient_tab(tab_index))
        
        if self.title_bar_tab_area:
            # Add to title bar
            custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
            self.title_bar_layout.addWidget(custom_tab)
            self.title_bar_tabs[tab_index] = custom_tab
        else:
            # Set custom tab widget as tab button
            self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.LeftSide, custom_tab)
        
        # Store reference
        self.patient_tabs[tab_index] = {
            'custom_tab': custom_tab,
            'widget': widget,
            'is_download_manager_tab': True
        }
        
        # Set as current tab if requested
        if activate:
            self.tab_widget.setCurrentIndex(tab_index)
            self.set_tab_active(tab_index)
            print(f"[CustomTabManager] Download Manager tab added and activated successfully")
        else:
            print(f"[CustomTabManager] Download Manager tab added without activation")
        
        return tab_index
    
    def add_web_browser_tab(self, widget=None):
        """
        Add Web Browser tab with custom tab UI (like patient tabs)
        
        Args:
            widget: The WebBrowserWidget to display
        
        Returns:
            int: The index of the added tab
        """
        print("[CustomTabManager] add_web_browser_tab called")
        
        # Check if web browser tab already exists
        for idx, tab_data in self.patient_tabs.items():
            if tab_data.get('is_web_browser_tab', False):
                print("[CustomTabManager] Web Browser tab already exists, switching to it")
                self.set_tab_active_simple(idx)
                return idx
        
        # Create custom tab widget with icon
        custom_tab = ServiceTabWidget(
            service_name="Web Browser",
            icon_name="fa5s.globe",
            icon_color="white"
        )
        
        # Add tab to tab widget
        tab_index = self.tab_widget.addTab(widget, "")
        print(f"[CustomTabManager] Web Browser tab added at index: {tab_index}")
        
        # Connect close button signal
        custom_tab.close_requested.connect(lambda: self.close_patient_tab(tab_index))
        
        if self.title_bar_tab_area:
            # Add to title bar
            custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
            self.title_bar_layout.addWidget(custom_tab)
            self.title_bar_tabs[tab_index] = custom_tab
        else:
            # Set custom tab widget as tab button
            self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.LeftSide, custom_tab)
        
        # Store reference
        self.patient_tabs[tab_index] = {
            'custom_tab': custom_tab,
            'widget': widget,
            'is_web_browser_tab': True
        }
        
        # Set as current tab
        self.tab_widget.setCurrentIndex(tab_index)
        self.set_tab_active(tab_index)
        print(f"[CustomTabManager] Web Browser tab added successfully")
        
        return tab_index
    
    def add_education_module_tab(self, widget=None):
        """
        Add Education Module tab with custom tab UI (like patient tabs)
        
        Args:
            widget: The EducationMainWidget to display
        
        Returns:
            int: The index of the added tab
        """
        print("[CustomTabManager] add_education_module_tab called")
        
        # Check if education module tab already exists
        for idx, tab_data in self.patient_tabs.items():
            if tab_data.get('is_education_tab', False):
                print("[CustomTabManager] Education Module tab already exists, switching to it")
                self.set_tab_active_simple(idx)
                return idx
        
        # Create custom tab widget with icon
        custom_tab = ServiceTabWidget(
            service_name="Educational Module",
            icon_name="fa5s.graduation-cap",
            icon_color="white"
        )
        
        # Add tab to tab widget
        tab_index = self.tab_widget.addTab(widget, "")
        print(f"[CustomTabManager] Education Module tab added at index: {tab_index}")
        
        # Connect close button signal
        custom_tab.close_requested.connect(lambda: self.close_patient_tab(tab_index))
        
        if self.title_bar_tab_area:
            # Add to title bar
            custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
            self.title_bar_layout.addWidget(custom_tab)
            self.title_bar_tabs[tab_index] = custom_tab
        else:
            # Set custom tab widget as tab button
            self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.LeftSide, custom_tab)
        
        # Store reference
        self.patient_tabs[tab_index] = {
            'custom_tab': custom_tab,
            'widget': widget,
            'is_education_tab': True
        }
        
        # Set as current tab
        self.tab_widget.setCurrentIndex(tab_index)
        self.set_tab_active(tab_index)
        print(f"[CustomTabManager] Education Module tab added successfully")
        
        return tab_index





