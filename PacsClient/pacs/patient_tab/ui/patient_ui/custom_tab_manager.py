from PySide6.QtWidgets import QTabWidget, QTabBar, QWidget, QHBoxLayout, QVBoxLayout, QSizePolicy, QPushButton, QLabel
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QIcon, QImage, QPainter, QColor, QPixmap
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
    
    def __init__(self, tab_widget: QTabWidget, title_bar_tab_area=None, right_tab_area=None):
        self.tab_widget = tab_widget
        self.title_bar_tab_area = title_bar_tab_area
        self.right_tab_area = right_tab_area
        self.right_tab_layout = None
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
        
        # Create logo button
        self.logo_button = QPushButton()
        self.logo_button.setObjectName("LogoButton")
        # Text-only logo button (requested: no picture)
        self.logo_button.setFixedHeight(70)
        self.logo_button.setFixedWidth(165)
        self.logo_button.setCursor(Qt.PointingHandCursor)

        # Build a UI-consistent text-only logotype inside the button using labels.
        # This avoids the “one weird font” look and matches the app’s Roboto-based UI.
        self.logo_button.setToolTip("AI-Pacs\nClick to show patient list")
        self._build_logo_logotype_contents()
        
        # Connect click event to show patient list
        self.logo_button.clicked.connect(self.show_patient_list)
        
        # Set initial state (inactive)
        self.logo_button.setProperty("active", False)
        
        # Force size policy to prevent layout from changing the size
        self.logo_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        # Apply styling for the logo button
        self._apply_logo_logotype_style()
        
        self.logo_button.setStyle(self.logo_button.style())
        
        self.title_bar_layout.addWidget(self.logo_button)
        
        # Force immediate layout update
        self.logo_button.updateGeometry()
        self.logo_button.update()
        
        # Add some spacing after the logo
        self.title_bar_layout.addSpacing(10)

        # Dedicated container for tab buttons so the logo stays fixed on the left.
        self.title_bar_tabs_container = QWidget(self.title_bar_tab_area)
        self.title_bar_tabs_container.setObjectName("TitleBarTabsContainer")
        self.title_bar_tabs_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.title_bar_tabs_layout = QHBoxLayout(self.title_bar_tabs_container)
        self.title_bar_tabs_layout.setContentsMargins(0, 0, 0, 0)
        self.title_bar_tabs_layout.setSpacing(4)
        self.title_bar_tabs_layout.addStretch(1)

        self.title_bar_layout.addWidget(self.title_bar_tabs_container, 1)
        self.title_bar_layout.addStretch(1)
        
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

        # Optional: setup a right-side tab strip near the user/admin area.
        if self.right_tab_area:
            self.right_tab_layout = QHBoxLayout(self.right_tab_area)
            self.right_tab_layout.setContentsMargins(0, 5, 0, 5)
            self.right_tab_layout.setSpacing(4)

    def _add_title_bar_tab_widget(self, widget: QWidget, insert_at_start: bool = False) -> None:
        """Insert a custom tab widget either at the start (right after logo) or before the stretch spacer.
        
        Args:
            widget: The tab widget to add
            insert_at_start: If True, insert at position 0 (right after logo). If False, insert before stretch.
        """
        if not hasattr(self, "title_bar_tabs_layout") or self.title_bar_tabs_layout is None:
            self.title_bar_layout.addWidget(widget)
            return

        if insert_at_start:
            # Insert at the beginning (right after logo, at the right side)
            insert_index = 0
        else:
            # Insert before the stretch spacer (default behavior)
            insert_index = max(0, self.title_bar_tabs_layout.count() - 1)
        
        self.title_bar_tabs_layout.insertWidget(insert_index, widget)

    def _add_title_bar_right_tab_widget(self, widget: QWidget) -> None:
        """Insert a custom tab widget into the right-side tab area (near admin/user info)."""
        if self.right_tab_layout is not None:
            self.right_tab_layout.addWidget(widget)
            return
        # Fallback to the main title bar tabs area.
        self._add_title_bar_tab_widget(widget)

    def _build_logo_logotype_contents(self):
        """Create the text-only "AI-Pacs" mark using child labels.

        QPushButton text rendering is limited (single color/weight). Using QLabel children lets us
        build a more brand-like logotype while staying consistent with the UI fonts.
        """
        if not hasattr(self, 'logo_button'):
            return

        # Ensure no icon and no default text.
        self.logo_button.setIcon(QIcon())
        self.logo_button.setText("")

        # Avoid rebuilding if already present.
        if getattr(self, '_logo_mark_built', False):
            return

        # Container that holds the word-mark.
        container = QWidget(self.logo_button)
        container.setObjectName("AIPacsBrandContainer")
        container.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        ai = QLabel("AI", container)
        ai.setObjectName("AIPacsBrandAI")
        ai.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        ai.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        f_ai = QFont("Roboto")
        f_ai.setPixelSize(26)
        f_ai.setWeight(QFont.Black)
        ai.setFont(f_ai)

        dash = QLabel("-", container)
        dash.setObjectName("AIPacsBrandDash")
        dash.setAlignment(Qt.AlignVCenter | Qt.AlignHCenter)
        dash.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        f_dash = QFont("Roboto")
        f_dash.setPixelSize(20)
        f_dash.setWeight(QFont.Medium)
        dash.setFont(f_dash)

        pacs = QLabel("Pacs", container)
        pacs.setObjectName("AIPacsBrandPacs")
        pacs.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        pacs.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        f_pacs = QFont("Roboto")
        f_pacs.setPixelSize(26)
        f_pacs.setWeight(QFont.DemiBold)
        pacs.setFont(f_pacs)

        row.addWidget(ai)
        row.addWidget(dash)
        row.addWidget(pacs)

        # Mount into the button.
        btn_layout = self.logo_button.layout()
        if btn_layout is None:
            btn_layout = QHBoxLayout(self.logo_button)
            btn_layout.setContentsMargins(14, 0, 14, 0)
            btn_layout.setSpacing(0)
            btn_layout.setAlignment(Qt.AlignCenter)

        btn_layout.addWidget(container)
        self._logo_mark_built = True

    def _render_svg_icon(self, svg_path, size: QSize, tint: QColor | None = None) -> QIcon | None:
        """Render an SVG file into a QIcon at the requested size.

        If `tint` is provided, the rendered icon is recolored via SourceIn composition.
        """
        try:
            from PySide6.QtSvg import QSvgRenderer
        except Exception:
            return None

        try:
            renderer = QSvgRenderer(str(svg_path))
            if not renderer.isValid():
                return None

            image = QImage(size, QImage.Format_ARGB32_Premultiplied)
            image.fill(Qt.transparent)

            painter = QPainter(image)
            renderer.render(painter)
            painter.end()

            if tint is not None and isinstance(tint, QColor) and tint.isValid():
                tinted = QImage(size, QImage.Format_ARGB32_Premultiplied)
                tinted.fill(Qt.transparent)
                p = QPainter(tinted)
                p.drawImage(0, 0, image)
                p.setCompositionMode(QPainter.CompositionMode_SourceIn)
                p.fillRect(tinted.rect(), tint)
                p.end()
                image = tinted

            pixmap = QPixmap.fromImage(image)
            return QIcon(pixmap)
        except Exception:
            return None

    def _try_apply_logo_icon(self):
        """Try to add an icon to the top-left AI Pacs logotype button.

        Uses `Qss/images/ai_pacs_logo.svg` (imported from user's SVG), with a tinted accent.
        Falls back to `Qss/images/aiLogo.png` if SVG rendering is unavailable.
        """
        if not hasattr(self, 'logo_button'):
            return

        try:
            from PacsClient.utils.config import IMAGES_LOGIN_PATH
        except Exception:
            IMAGES_LOGIN_PATH = None

        # Bigger icon since the button is icon-only.
        target_size = QSize(54, 54)

        svg_icon = None
        png_icon = None

        try:
            if IMAGES_LOGIN_PATH is not None:
                svg_path = IMAGES_LOGIN_PATH / "ai_pacs_logo.svg"
                if svg_path.exists():
                    # Keep original SVG colors (logo-only request).
                    svg_icon = self._render_svg_icon(svg_path, target_size, tint=None)

                png_path = IMAGES_LOGIN_PATH / "aiLogo.png"
                if png_path.exists():
                    pix = QPixmap(str(png_path)).scaled(
                        target_size,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                    png_icon = QIcon(pix)
        except Exception:
            svg_icon = None
            png_icon = None

        icon = svg_icon or png_icon
        if icon is None:
            return

        try:
            self.logo_button.setIcon(icon)
            self.logo_button.setIconSize(target_size)
            self._apply_logo_logotype_style()
        except Exception:
            return

    def _logo_logotype_stylesheet(self) -> str:
        """Single source of truth for the AI-Pacs text logotype button styling.

        Keep this stable and avoid swapping style blocks on tab changes,
        because that previously caused the button to revert when opening system tabs.
        """
        return """
            QPushButton#LogoButton {
                /* Softer, UI-consistent look: low-contrast gradient + muted border */
                /* Lighter indigo-tinted container gradient (box only; letters are separate) */
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1b2340, stop:1 #111a2e);
                border: 1px solid rgba(99, 102, 241, 0.18);
                border-radius: 12px;
                color: #f8fafc;
                padding: 0px;
                margin: 0px;
                text-align: center;
            }

            QPushButton#LogoButton QLabel#AIPacsBrandAI {
                /* Muted accent (less eye-catching) */
                color: rgba(165, 180, 252, 0.92);
            }

            QPushButton#LogoButton QLabel#AIPacsBrandDash {
                color: rgba(148, 163, 184, 0.88);
            }

            QPushButton#LogoButton QLabel#AIPacsBrandPacs {
                /* Slightly softened white for lower contrast */
                color: rgba(226, 232, 240, 0.96);
            }

            QPushButton#LogoButton[active="true"] {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a2240, stop:1 #0f172a);
                border: 1px solid rgba(99, 102, 241, 0.32);
                color: #ffffff;
            }

            QPushButton#LogoButton[active="true"] QLabel#AIPacsBrandAI {
                color: rgba(196, 181, 253, 0.96);
            }

            QPushButton#LogoButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #222b4d, stop:1 #141e36);
                border: 1px solid rgba(99, 102, 241, 0.26);
            }

            QPushButton#LogoButton[active="true"]:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #232c52, stop:1 #111a2e);
                border: 1px solid rgba(99, 102, 241, 0.34);
            }

            QPushButton#LogoButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #101a33, stop:1 #0b1220);
                border: 1px solid rgba(96, 165, 250, 0.32);
            }
        """

    def _apply_logo_logotype_style(self):
        """Apply the logotype stylesheet once (and safely re-apply if needed)."""
        if not hasattr(self, 'logo_button'):
            return
        try:
            self.logo_button.setStyleSheet(self._logo_logotype_stylesheet())
        except Exception as e:
            print(f"[CustomTabManager] Failed to apply logo logotype stylesheet: {e}")
    
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
        self._add_title_bar_tab_widget(custom_tab)
        
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
        for tab_idx, tab_data in self.patient_tabs.items():
            if hasattr(tab_data['custom_tab'], 'set_active'):
                tab_data['custom_tab'].set_active(False)
            try:
                widget = tab_data.get('widget')
                if widget is not None and hasattr(widget, 'on_tab_deactivated'):
                    widget.on_tab_deactivated()
            except Exception:
                pass
        
        # Set current tab as active
        if index in self.patient_tabs:
            tab_data = self.patient_tabs[index]
            if hasattr(tab_data['custom_tab'], 'set_active'):
                tab_data['custom_tab'].set_active(True)
                # Set logo button as inactive when patient tab is selected
                self.set_logo_active(False)

            try:
                widget = tab_data.get('widget')
                if widget is not None and hasattr(widget, 'on_tab_activated'):
                    widget.on_tab_activated()
            except Exception:
                pass
            
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

            # Do NOT reassign older styles here.
            # Only polish/unpolish so the [active="true"] selector updates.
            try:
                self._apply_logo_logotype_style()
            except Exception:
                pass

            self.logo_button.style().unpolish(self.logo_button)
            self.logo_button.style().polish(self.logo_button)
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
            self.patient_tabs.pop(tab_index)

            # Remove from title bar if using title bar tabs
            if self.title_bar_tab_area and tab_index in self.title_bar_tabs:
                title_bar_tab = self.title_bar_tabs.pop(tab_index)
                title_bar_tab.setParent(None)
                title_bar_tab.deleteLater()

            # Remove from tab widget
            self.tab_widget.removeTab(tab_index)

            # Update remaining tab indices and study_uid mappings
            self.update_tab_indices()

            # Switch to another available tab if exists, otherwise go to home
            self._switch_to_remaining_tab_after_close(tab_index)

    def _switch_to_remaining_tab_after_close(self, closed_index):
        """
        After closing a tab, switch to another available tab.
        
        Args:
            closed_index: The index of the tab that was closed
        """
        # Check if there are any patient/service tabs remaining (excluding home tab at index 0)
        if self.patient_tabs:
            # Find a suitable tab to switch to
            # Prefer tabs with lower index than the closed one, or the next available tab
            target_index = None
            
            # First, try to find a tab at a lower index than the closed one
            for idx in sorted(self.patient_tabs.keys()):
                if idx < closed_index:
                    target_index = idx
                    break
            
            # If no lower index found, use the first available tab (could be higher index)
            if target_index is None:
                target_index = min(self.patient_tabs.keys())
            
            # Activate the target tab
            if target_index is not None:
                self.set_tab_active(target_index)
                return
        
        # No tabs available, go to home
        self.set_logo_active(True)
        if self.tab_widget.count() > 0:
            self.tab_widget.setCurrentIndex(0)

    def update_tab_indices(self):
        """Update tab indices after closing a tab"""
        # Rebuild patient_tabs dictionary with correct indices
        # This is necessary because after removing a tab, all higher indices shift down
        new_patient_tabs = {}
        new_study_uid_to_tab = {}
        
        # Get all items sorted by old index
        sorted_tabs = sorted(self.patient_tabs.items(), key=lambda x: x[0])
        
        for old_index, tab_data in sorted_tabs:
            # New index is one less than old index if old index > closed tab index
            # But since we already removed the tab and called removeTab,
            # we need to recalculate based on position in the sorted list
            # Actually, we need to iterate through the actual tab_widget to get correct indices
            pass
        
        # Better approach: iterate through actual tab widget and rebuild mappings
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            # Find matching tab_data from old patient_tabs
            for old_index, tab_data in sorted_tabs:
                if tab_data.get('widget') == widget:
                    new_patient_tabs[i] = tab_data
                    study_uid = tab_data.get('study_uid')
                    if study_uid:
                        new_study_uid_to_tab[study_uid] = i
                    break
        
        self.patient_tabs = new_patient_tabs
        self.study_uid_to_tab = new_study_uid_to_tab

        if self.title_bar_tab_area:
            new_title_bar_tabs = {}
            for idx, tab_data in self.patient_tabs.items():
                custom_tab = tab_data.get('custom_tab')
                if custom_tab is None:
                    continue
                new_title_bar_tabs[idx] = custom_tab

                if isinstance(custom_tab, QPushButton):
                    try:
                        custom_tab.clicked.disconnect()
                    except Exception:
                        pass
                    custom_tab.clicked.connect(lambda checked=False, i=idx: self.set_tab_active_simple(i))
                else:
                    custom_tab.mousePressEvent = lambda event, i=idx: self.on_title_bar_tab_clicked(i)

                if hasattr(custom_tab, 'close_requested'):
                    try:
                        custom_tab.close_requested.disconnect()
                    except Exception:
                        pass
                    custom_tab.close_requested.connect(lambda i=idx: self.close_patient_tab(i))

            self.title_bar_tabs = new_title_bar_tabs
    
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
            self._add_title_bar_tab_widget(tab_button)
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
            # Add to right-side area (near admin/user info)
            custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
            self._add_title_bar_right_tab_widget(custom_tab)
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
            self._add_title_bar_tab_widget(custom_tab)
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
            # Add to right-side area (near admin/user info)
            custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
            self._add_title_bar_right_tab_widget(custom_tab)
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

    def add_printing_tab(self, widget=None):
        """
        Add Printing tab with custom tab UI (like patient tabs)

        Args:
            widget: The PrintingWidget to display

        Returns:
            int: The index of the added tab
        """
        print("[CustomTabManager] add_printing_tab called")

        # Check if printing tab already exists
        for idx, tab_data in self.patient_tabs.items():
            if tab_data.get('is_printing_tab', False):
                print("[CustomTabManager] Printing tab already exists, switching to it")
                self.set_tab_active_simple(idx)
                return idx

        # Create custom tab widget with icon
        custom_tab = ServiceTabWidget(
            service_name="Printing",
            icon_name="fa5s.print",
            icon_color="white"
        )

        # Add tab to tab widget
        tab_index = self.tab_widget.addTab(widget, "")
        print(f"[CustomTabManager] Printing tab added at index: {tab_index}")

        # Connect close button signal
        custom_tab.close_requested.connect(lambda: self.close_patient_tab(tab_index))

        if self.title_bar_tab_area:
            # Add to title bar
            custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
            self._add_title_bar_tab_widget(custom_tab)
            self.title_bar_tabs[tab_index] = custom_tab
        else:
            # Set custom tab widget as tab button
            self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.LeftSide, custom_tab)

        # Store reference
        self.patient_tabs[tab_index] = {
            'custom_tab': custom_tab,
            'widget': widget,
            'is_printing_tab': True
        }

        # Set as current tab
        self.tab_widget.setCurrentIndex(tab_index)
        self.set_tab_active(tab_index)
        print("[CustomTabManager] Printing tab added successfully")

        return tab_index

    def add_educational_course_tab(self, course_name="", course_pk=None, widget=None, activate=True):
        """
        Add Educational Course tab with custom tab UI.

        Args:
            course_name: Name of the selected course (shown as subtitle)
            course_pk: Optional course primary key for duplicate prevention
            widget: The educational viewer widget
            activate: Whether to switch to the tab after creation

        Returns:
            int: The index of the added/existing tab
        """
        print("[CustomTabManager] add_educational_course_tab called")

        # Prevent duplicate course tabs when course_pk is available
        for idx, tab_data in self.patient_tabs.items():
            if not tab_data.get('is_educational_course_tab', False):
                continue
            if course_pk is not None and tab_data.get('course_pk') == course_pk:
                print(f"[CustomTabManager] Educational Course tab already exists for course_pk={course_pk}")
                if activate:
                    self.set_tab_active_simple(idx)
                return idx

        custom_tab = ServiceTabWidget(
            service_name="Educational Course",
            icon_name="fa5s.book-reader",
            icon_color="white"
        )
        if course_name:
            custom_tab.set_description(str(course_name))

        tab_index = self.tab_widget.addTab(widget, "")
        print(f"[CustomTabManager] Educational Course tab added at index: {tab_index}")

        custom_tab.close_requested.connect(lambda: self.close_patient_tab(tab_index))

        if self.title_bar_tab_area:
            custom_tab.mousePressEvent = lambda event: self.on_title_bar_tab_clicked(tab_index)
            self._add_title_bar_tab_widget(custom_tab)
            self.title_bar_tabs[tab_index] = custom_tab
        else:
            self.tab_widget.tabBar().setTabButton(tab_index, QTabBar.ButtonPosition.LeftSide, custom_tab)

        self.patient_tabs[tab_index] = {
            'custom_tab': custom_tab,
            'widget': widget,
            'is_educational_course_tab': True,
            'course_pk': course_pk,
            'course_name': course_name,
        }

        if activate:
            self.tab_widget.setCurrentIndex(tab_index)
            self.set_tab_active(tab_index)
            print("[CustomTabManager] Educational Course tab added and activated successfully")
        else:
            print("[CustomTabManager] Educational Course tab added without activation")

        return tab_index





