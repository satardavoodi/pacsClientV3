"""
Shortcut Manager for AIPacs Application
Manages keyboard shortcuts for quick navigation and actions
"""

from PySide6.QtCore import Qt, QObject
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QWidget


class ShortcutManager(QObject):
    """
    Manages application-wide keyboard shortcuts
    
    Shortcuts:
    - F5: Go to home/patient list
    - F6: Open AI chatbot
    - F7: Start/stop recording audio (auto-opens chatbot if needed)
    - F8: Send text for report generation
    """
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.control_panel = None
        self.home_widget = None
        self.chatbot_widget = None
        
        self._setup_shortcuts()
    
    def _setup_shortcuts(self):
        """Setup all keyboard shortcuts"""
        # F5: Go to home/patient list
        self.f5_shortcut = QShortcut(QKeySequence(Qt.Key_F5), self.main_window)
        self.f5_shortcut.setContext(Qt.ApplicationShortcut)  # Work everywhere
        self.f5_shortcut.activated.connect(self._on_f5_pressed)
        
        # F6: Open chatbot
        self.f6_shortcut = QShortcut(QKeySequence(Qt.Key_F6), self.main_window)
        self.f6_shortcut.setContext(Qt.ApplicationShortcut)  # Work everywhere
        self.f6_shortcut.activated.connect(self._on_f6_pressed)
        
        # F7: Start/stop recording
        self.f7_shortcut = QShortcut(QKeySequence(Qt.Key_F7), self.main_window)
        self.f7_shortcut.setContext(Qt.ApplicationShortcut)  # Work everywhere
        self.f7_shortcut.activated.connect(self._on_f7_pressed)
        
        # F8: Send text for report
        self.f8_shortcut = QShortcut(QKeySequence(Qt.Key_F8), self.main_window)
        self.f8_shortcut.setContext(Qt.ApplicationShortcut)  # Work everywhere
        self.f8_shortcut.activated.connect(self._on_f8_pressed)
        
        # Arrow Up: Previous slice in active viewport
        self.arrow_up_shortcut = QShortcut(QKeySequence(Qt.Key_Up), self.main_window)
        self.arrow_up_shortcut.setContext(Qt.ApplicationShortcut)
        self.arrow_up_shortcut.activated.connect(self._on_arrow_up_pressed)
        
        # Arrow Down: Next slice in active viewport
        self.arrow_down_shortcut = QShortcut(QKeySequence(Qt.Key_Down), self.main_window)
        self.arrow_down_shortcut.setContext(Qt.ApplicationShortcut)
        self.arrow_down_shortcut.activated.connect(self._on_arrow_down_pressed)
        
        # Arrow Left: Previous series
        self.arrow_left_shortcut = QShortcut(QKeySequence(Qt.Key_Left), self.main_window)
        self.arrow_left_shortcut.setContext(Qt.ApplicationShortcut)
        self.arrow_left_shortcut.activated.connect(self._on_arrow_left_pressed)
        
        # Arrow Right: Next series
        self.arrow_right_shortcut = QShortcut(QKeySequence(Qt.Key_Right), self.main_window)
        self.arrow_right_shortcut.setContext(Qt.ApplicationShortcut)
        self.arrow_right_shortcut.activated.connect(self._on_arrow_right_pressed)
        
        print("✓ Shortcuts initialized: F5 (Home), F6 (Chatbot), F7 (Recording), F8 (Report)")
        print("✓ Arrow shortcuts: Up/Down (Slice), Left/Right (Series)")
        print("✓ All shortcuts set to ApplicationShortcut (work everywhere)")
    
    def set_control_panel(self, control_panel):
        """Set the control panel reference for navigation"""
        print(f"[DEBUG] set_control_panel called with: {control_panel}")
        print(f"[DEBUG] Has 'ui' attr: {hasattr(control_panel, 'ui')}")
        
        self.control_panel = control_panel
        if hasattr(control_panel, 'ui'):
            ui = control_panel.ui
            print(f"[DEBUG] ui = {ui}")
            print(f"[DEBUG] Has 'home_widget' attr: {hasattr(ui, 'home_widget')}")
            print(f"[DEBUG] Has 'mainPages' attr: {hasattr(ui, 'mainPages')}")
            
            if hasattr(ui, 'home_widget'):
                self.home_widget = ui.home_widget
                print(f"✓ Home widget connected to shortcut manager: {self.home_widget}")
            else:
                print("✗ home_widget NOT found in ui")
        else:
            print("✗ control_panel does NOT have 'ui' attribute")
    
    def _get_chatbot_widget(self):
        """Get or find the chatbot widget"""
        # Try to find chatbot in current patient tab
        try:
            if self.home_widget and hasattr(self.home_widget, 'tab_widget'):
                current_widget = self.home_widget.tab_widget.currentWidget()
                print(f"[DEBUG _get_chatbot] current_widget: {type(current_widget).__name__}")
                
                # Check if current widget is a PatientWidget
                # First try: ai_chat_window (separate window)
                if hasattr(current_widget, 'ai_chat_window') and current_widget.ai_chat_window:
                    ai_chat_window = current_widget.ai_chat_window
                    print(f"[DEBUG _get_chatbot] Found ai_chat_window: {ai_chat_window}")
                    if hasattr(ai_chat_window, 'page'):
                        print(f"[DEBUG _get_chatbot] ✓ Found via ai_chat_window.page")
                        return ai_chat_window.page, current_widget
                    return ai_chat_window, current_widget
                
                # Second try: ai_chat_widget (embedded widget)
                if hasattr(current_widget, 'ai_chat_widget') and current_widget.ai_chat_widget:
                    ai_chat_viewer = current_widget.ai_chat_widget
                    if hasattr(ai_chat_viewer, 'page'):
                        print(f"[DEBUG _get_chatbot] ✓ Found via ai_chat_widget.page")
                        return ai_chat_viewer.page, current_widget
                    print(f"[DEBUG _get_chatbot] ✓ Found via ai_chat_widget")
                    return ai_chat_viewer, current_widget
                    
                # Try looking in right_panel (might be embedded)
                if hasattr(current_widget, 'right_panel'):
                    right_panel = current_widget.right_panel
                    print(f"[DEBUG _get_chatbot] right_panel count: {right_panel.count()}")
                    # Check all widgets in the stacked widget
                    for i in range(right_panel.count()):
                        widget = right_panel.widget(i)
                        print(f"[DEBUG _get_chatbot] Widget {i}: {type(widget).__name__}")
                        if type(widget).__name__ == 'AIChatViewer':
                            if hasattr(widget, 'page'):
                                print(f"[DEBUG _get_chatbot] ✓ Found AIChatViewer at index {i}")
                                return widget.page, current_widget
                            return widget, current_widget
        except Exception as e:
            print(f"Error finding chatbot in patient tab: {e}")
            import traceback
            traceback.print_exc()
        
        return None, None
    
    def _on_f5_pressed(self):
        """F5: Navigate to home/patient list"""
        print("F5 pressed - Navigating to home/patient list")
        print(f"[DEBUG] control_panel: {self.control_panel}")
        print(f"[DEBUG] home_widget: {self.home_widget}")
        
        try:
            # Navigate to main pages home widget
            if self.control_panel and hasattr(self.control_panel, 'ui'):
                ui = self.control_panel.ui
                print(f"[DEBUG] ui found: {ui}")
                if hasattr(ui, 'mainPages'):
                    print(f"[DEBUG] mainPages found, setting to index 0")
                    ui.mainPages.setCurrentIndex(0)
                    print("✓ Navigated to home page")
                else:
                    print("[DEBUG] ✗ mainPages NOT found")
            else:
                print("[DEBUG] ✗ control_panel or ui NOT found")
            
            # Also switch to patient list tab (index 0)
            if self.home_widget and hasattr(self.home_widget, 'tab_widget'):
                print(f"[DEBUG] tab_widget found, count: {self.home_widget.tab_widget.count()}")
                self.home_widget.tab_widget.setCurrentIndex(0)
                print("✓ Switched to patient list tab")
            else:
                print("[DEBUG] ✗ home_widget or tab_widget NOT found")
                
        except Exception as e:
            print(f"✗ Error navigating to home: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_f6_pressed(self):
        """F6: Open chatbot"""
        print("F6 pressed - Opening chatbot")
        
        try:
            # Get current patient widget
            if self.home_widget and hasattr(self.home_widget, 'tab_widget'):
                current_widget = self.home_widget.tab_widget.currentWidget()
                
                # Check if it's a PatientWidget
                if hasattr(current_widget, 'btn_ai_chat'):
                    # Click the AI chat button
                    current_widget.btn_ai_chat.click()
                    print("✓ Chatbot opened in current patient tab")
                    return
                
                # Try switching to first patient tab if we're on home page
                if self.home_widget.tab_widget.count() > 1:
                    self.home_widget.tab_widget.setCurrentIndex(1)
                    print("Switched to patient tab...")
                    
                    # Try again
                    current_widget = self.home_widget.tab_widget.currentWidget()
                    if hasattr(current_widget, 'btn_ai_chat'):
                        current_widget.btn_ai_chat.click()
                        print("✓ Chatbot opened after switching to patient tab")
                        return
                
            print("✗ No patient tab open - chatbot requires an active patient context")
            
        except Exception as e:
            print(f"✗ Error opening chatbot: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_f7_pressed(self):
        """F7: Start/stop recording audio (auto-opens chatbot if needed)"""
        print("F7 pressed - Recording control")
        
        try:
            # First, ensure chatbot is open
            chatbot, patient_widget = self._get_chatbot_widget()
            
            if not chatbot:
                print("Chatbot not found, opening it first...")
                self._on_f6_pressed()
                
                # Wait a moment for UI to update, then get chatbot again
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._do_recording_action)
                return
            
            self._do_recording_action()
                
        except Exception as e:
            print(f"✗ Error controlling recording: {e}")
            import traceback
            traceback.print_exc()
    
    def _do_recording_action(self):
        """Perform the actual recording action"""
        try:
            chatbot, patient_widget = self._get_chatbot_widget()
            
            if not chatbot:
                print("✗ Could not access chatbot for recording")
                print("[DEBUG] Trying alternative method - checking if AI Chat is currently visible...")
                
                # Alternative: check if current widget in right_panel is AIChatViewer
                if self.home_widget and hasattr(self.home_widget, 'tab_widget'):
                    current_widget = self.home_widget.tab_widget.currentWidget()
                    print(f"[DEBUG Alternative] current_widget type: {type(current_widget).__name__}")
                    
                    # Try thumbnails_panel first (old name), then right_panel
                    panel = None
                    if hasattr(current_widget, 'thumbnails_panel'):
                        panel = current_widget.thumbnails_panel
                        print(f"[DEBUG Alternative] Using thumbnails_panel")
                    elif hasattr(current_widget, 'right_panel'):
                        panel = current_widget.right_panel
                        print(f"[DEBUG Alternative] Using right_panel")
                    
                    if panel:
                        current_widget_in_panel = panel.currentWidget()
                        print(f"[DEBUG Alternative] panel.count(): {panel.count()}")
                        print(f"[DEBUG Alternative] Current widget: {type(current_widget_in_panel).__name__}")
                        
                        # List all widgets
                        for i in range(panel.count()):
                            w = panel.widget(i)
                            print(f"[DEBUG Alternative] Widget {i}: {type(w).__name__}")
                        
                        if type(current_widget_in_panel).__name__ == 'AIChatViewer':
                            if hasattr(current_widget_in_panel, 'page'):
                                chatbot = current_widget_in_panel.page
                                print("[DEBUG Alternative] ✓ Found chatbot via panel.currentWidget()")
                    else:
                        print("[DEBUG Alternative] No panel found")
                
                if not chatbot:
                    print("[DEBUG Alternative] Still no chatbot found, giving up")
                    return
            
            print(f"[DEBUG] chatbot found: {chatbot}")
            
            # Find the composer (recording control)
            if hasattr(chatbot, 'composer'):
                composer = chatbot.composer
                print(f"[DEBUG] composer found: {composer}")
                
                # Check if already recording
                if hasattr(composer, '_rec_running') and composer._rec_running:
                    # Stop and send recording
                    print("Stopping recording and sending to server...")
                    if hasattr(composer, '_finish_record_and_transcribe'):
                        composer._finish_record_and_transcribe()
                        print("✓ Recording stopped and sent")
                else:
                    # Start recording
                    print("Starting recording...")
                    if hasattr(composer, '_start_record'):
                        composer._start_record()
                        print("✓ Recording started")
            else:
                print("✗ Composer not found in chatbot")
                
        except Exception as e:
            print(f"✗ Error in recording action: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_f8_pressed(self):
        """F8: Send text for report generation"""
        print("F8 pressed - Sending text for report")
        
        try:
            # First, ensure chatbot is open
            chatbot, patient_widget = self._get_chatbot_widget()
            
            if not chatbot:
                print("Chatbot not found, opening it first...")
                self._on_f6_pressed()
                
                # Wait a moment for UI to update, then send report
                from PySide6.QtCore import QTimer
                QTimer.singleShot(100, self._do_send_report)
                return
            
            self._do_send_report()
                
        except Exception as e:
            print(f"✗ Error sending text for report: {e}")
            import traceback
            traceback.print_exc()
    
    def _do_send_report(self):
        """Perform the actual send report action"""
        try:
            chatbot, patient_widget = self._get_chatbot_widget()
            
            if not chatbot:
                print("✗ Could not access chatbot for sending report")
                print("[DEBUG] Trying alternative method - checking if AI Chat is currently visible...")
                
                # Alternative: check if current widget in thumbnails_panel is AIChatViewer
                if self.home_widget and hasattr(self.home_widget, 'tab_widget'):
                    current_widget = self.home_widget.tab_widget.currentWidget()
                    if hasattr(current_widget, 'thumbnails_panel'):
                        thumbnails_panel = current_widget.thumbnails_panel
                        current_thumb_widget = thumbnails_panel.currentWidget()
                        print(f"[DEBUG] Current thumbnails_panel widget: {type(current_thumb_widget).__name__}")
                        
                        if type(current_thumb_widget).__name__ == 'AIChatViewer':
                            if hasattr(current_thumb_widget, 'page'):
                                chatbot = current_thumb_widget.page
                                print("[DEBUG] Found chatbot via thumbnails_panel.currentWidget()")
                
                if not chatbot:
                    return
            
            # Get text from composer
            if hasattr(chatbot, 'composer'):
                composer = chatbot.composer
                
                if hasattr(composer, 'box'):
                    text = composer.box.toPlainText().strip()
                    
                    if text:
                        print(f"Sending text for report: {text[:50]}...")
                        
                        # Send with Report mode
                        if hasattr(chatbot, '_send_with_mode'):
                            chatbot._send_with_mode(text, "Report")
                            print("✓ Text sent for report generation")
                        else:
                            print("✗ _send_with_mode method not found")
                    else:
                        print("✗ No text to send (text box is empty)")
            else:
                print("✗ Composer not found in chatbot")
                
        except Exception as e:
            print(f"✗ Error in send report action: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_arrow_up_pressed(self):
        """Arrow Up: Previous slice in active viewport"""
        try:
            if not self.home_widget or not hasattr(self.home_widget, 'tab_widget'):
                return
            
            # Get current patient widget
            current_widget = self.home_widget.tab_widget.currentWidget()
            
            # Check if it's a PatientWidget with selected_widget
            if hasattr(current_widget, 'selected_widget') and current_widget.selected_widget:
                vtk_widget = current_widget.selected_widget
                
                # Get slider and move to previous slice
                if hasattr(vtk_widget, 'slider') and vtk_widget.slider:
                    current_value = vtk_widget.slider.value()
                    if current_value > 0:
                        vtk_widget.slider.setValue(current_value - 1)
                        print(f"↑ Previous slice: {current_value - 1}")
                        
        except Exception as e:
            print(f"✗ Error navigating to previous slice: {e}")
    
    def _on_arrow_down_pressed(self):
        """Arrow Down: Next slice in active viewport"""
        try:
            if not self.home_widget or not hasattr(self.home_widget, 'tab_widget'):
                return
            
            # Get current patient widget
            current_widget = self.home_widget.tab_widget.currentWidget()
            
            # Check if it's a PatientWidget with selected_widget
            if hasattr(current_widget, 'selected_widget') and current_widget.selected_widget:
                vtk_widget = current_widget.selected_widget
                
                # Get slider and move to next slice
                if hasattr(vtk_widget, 'slider') and vtk_widget.slider:
                    current_value = vtk_widget.slider.value()
                    max_value = vtk_widget.slider.maximum()
                    if current_value < max_value:
                        vtk_widget.slider.setValue(current_value + 1)
                        print(f"↓ Next slice: {current_value + 1}")
                        
        except Exception as e:
            print(f"✗ Error navigating to next slice: {e}")
    
    def _get_available_series_list(self, current_widget):
        """
        Get list of available series numbers in order
        این لیست شامل series_number های موجود است، نه index های آرایه
        """
        series_list = []
        
        # Try to get from thumbnail_manager.series_widgets (keys are series numbers)
        if hasattr(current_widget, 'thumbnail_manager') and current_widget.thumbnail_manager:
            if hasattr(current_widget.thumbnail_manager, 'series_widgets'):
                series_widgets = current_widget.thumbnail_manager.series_widgets
                # Keys are series numbers as strings
                series_list = sorted([int(k) for k in series_widgets.keys()])
                print(f"Available series from series_widgets: {series_list}")
                return series_list
        
        # Fallback: try lst_thumbnails_data
        if hasattr(current_widget, 'lst_thumbnails_data') and current_widget.lst_thumbnails_data:
            for i, thumb_data in enumerate(current_widget.lst_thumbnails_data):
                if isinstance(thumb_data, dict) and 'series_number' in thumb_data:
                    series_list.append(int(thumb_data['series_number']))
                else:
                    series_list.append(i)  # Use index as fallback
            print(f"Available series from lst_thumbnails_data: {series_list}")
            return series_list
        
        return series_list
    
    def _on_arrow_left_pressed(self):
        """Arrow Left: Previous series"""
        try:
            if not self.home_widget or not hasattr(self.home_widget, 'tab_widget'):
                return
            
            # Get current patient widget
            current_widget = self.home_widget.tab_widget.currentWidget()
            
            # Get current series number (not array index!)
            current_series_number = None
            
            # Method 1: Try thumbnail_manager.selected_series
            if hasattr(current_widget, 'thumbnail_manager') and current_widget.thumbnail_manager:
                thumbnail_mgr = current_widget.thumbnail_manager
                if hasattr(thumbnail_mgr, 'selected_series') and thumbnail_mgr.selected_series:
                    try:
                        current_series_number = int(thumbnail_mgr.selected_series)
                        print(f"Found current series from thumbnail_manager: {current_series_number}")
                    except:
                        pass
            
            # Method 2: Try selected_widget's last_series_show
            if current_series_number is None and hasattr(current_widget, 'selected_widget') and current_widget.selected_widget:
                vtk_widget = current_widget.selected_widget
                if hasattr(vtk_widget, 'last_series_show') and vtk_widget.last_series_show is not None:
                    current_series_number = vtk_widget.last_series_show
                    print(f"Found current series from vtk_widget: {current_series_number}")
            
            # If we still don't have a series number, we can't navigate
            if current_series_number is None:
                print("⚠️ No series currently selected")
                return
            
            # Get list of available series
            available_series = self._get_available_series_list(current_widget)
            
            if len(available_series) <= 1:
                print(f"⚠️ Not enough series to navigate (total: {len(available_series)})")
                return
            
            # Find current position in the list
            try:
                current_position = available_series.index(current_series_number)
                print(f"Current position in series list: {current_position} (series {current_series_number})")
            except ValueError:
                print(f"⚠️ Current series {current_series_number} not found in available series {available_series}")
                return
            
            # Move to previous series
            if current_position > 0:
                new_position = current_position - 1
                new_series_number = available_series[new_position]
                
                # Trigger series change with the new series number
                if hasattr(current_widget, 'change_series_on_viewer'):
                    current_widget.change_series_on_viewer(
                        series_index=new_series_number,
                        flag_change_selected_widget=False,
                        vtk_widget=current_widget.selected_widget if hasattr(current_widget, 'selected_widget') else None,
                        slider=current_widget.selected_widget.slider if hasattr(current_widget, 'selected_widget') and hasattr(current_widget.selected_widget, 'slider') else None
                    )
                    print(f"← Previous series: {new_series_number} (position {new_position})")
            else:
                print(f"Already at first series (series {current_series_number})")
                                
        except Exception as e:
            print(f"✗ Error navigating to previous series: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_arrow_right_pressed(self):
        """Arrow Right: Next series"""
        try:
            if not self.home_widget or not hasattr(self.home_widget, 'tab_widget'):
                return
            
            # Get current patient widget
            current_widget = self.home_widget.tab_widget.currentWidget()
            
            # Get current series number (not array index!)
            current_series_number = None
            
            # Method 1: Try thumbnail_manager.selected_series
            if hasattr(current_widget, 'thumbnail_manager') and current_widget.thumbnail_manager:
                thumbnail_mgr = current_widget.thumbnail_manager
                if hasattr(thumbnail_mgr, 'selected_series') and thumbnail_mgr.selected_series:
                    try:
                        current_series_number = int(thumbnail_mgr.selected_series)
                        print(f"Found current series from thumbnail_manager: {current_series_number}")
                    except:
                        pass
            
            # Method 2: Try selected_widget's last_series_show
            if current_series_number is None and hasattr(current_widget, 'selected_widget') and current_widget.selected_widget:
                vtk_widget = current_widget.selected_widget
                if hasattr(vtk_widget, 'last_series_show') and vtk_widget.last_series_show is not None:
                    current_series_number = vtk_widget.last_series_show
                    print(f"Found current series from vtk_widget: {current_series_number}")
            
            # If we still don't have a series number, we can't navigate
            if current_series_number is None:
                print("⚠️ No series currently selected")
                return
            
            # Get list of available series
            available_series = self._get_available_series_list(current_widget)
            
            if len(available_series) <= 1:
                print(f"⚠️ Not enough series to navigate (total: {len(available_series)})")
                return
            
            # Find current position in the list
            try:
                current_position = available_series.index(current_series_number)
                print(f"Current position in series list: {current_position} (series {current_series_number})")
            except ValueError:
                print(f"⚠️ Current series {current_series_number} not found in available series {available_series}")
                return
            
            # Move to next series
            if current_position < len(available_series) - 1:
                new_position = current_position + 1
                new_series_number = available_series[new_position]
                
                # Trigger series change with the new series number
                if hasattr(current_widget, 'change_series_on_viewer'):
                    current_widget.change_series_on_viewer(
                        series_index=new_series_number,
                        flag_change_selected_widget=False,
                        vtk_widget=current_widget.selected_widget if hasattr(current_widget, 'selected_widget') else None,
                        slider=current_widget.selected_widget.slider if hasattr(current_widget, 'selected_widget') and hasattr(current_widget.selected_widget, 'slider') else None
                    )
                    print(f"→ Next series: {new_series_number} (position {new_position})")
            else:
                print(f"Already at last series (series {current_series_number})")
                                
        except Exception as e:
            print(f"✗ Error navigating to next series: {e}")
            import traceback
            traceback.print_exc()

