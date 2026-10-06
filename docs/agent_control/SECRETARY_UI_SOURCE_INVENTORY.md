# Secretary UI source inventory

Generated from static Qt declarations. Source references and callbacks are documentation, never executable commands.
Dynamic factories, computed options and absent labels require live inspection. Discovered controls are not automatically MCP actions.
Sensitive controls remain local-only. Actual execution is defined by registered typed CommandBus capabilities.

| Source / line | Field or action | Widget | Label / purpose | Static dropdown options | Constraints | Callback |
| --- | --- | --- | --- | --- | --- | --- |
| PacsClient/pacs/patient_tab/ui/patient_ui/_vc_warmup.py:882 | slider | QSlider | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py:63 | self.logo_button | QPushButton | AI-Pacs Click to show patient list |  | {} | self.show_patient_list |
| PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py:1075 | tab_button | QPushButton | Reception Data |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py:381 | view_btn | QPushButton | View Image |  | {} | self._open_file |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py:404 | del_btn | QPushButton | Delete |  | {} | self._delete |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py:684 | self._slider | QSlider | Live inspection required |  | {"minimum": 0, "maximum": 1000} | self._on_press, self._on_release |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py:702 | self._play_btn | QPushButton | Play Audio |  | {} | self._toggle |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py:729 | stop_btn | QPushButton | Stop Audio |  | {} | self._stop |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py:758 | report_btn | QPushButton | ECHO MIND - Report |  | {} | self._open_report |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown.py:785 | del_btn | QPushButton | Delete File |  | {} | self._delete |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown_new.py:155 | self.play_btn | QPushButton | Play Audio |  | {} | self._toggle_play |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown_new.py:176 | stop_btn | QPushButton | Stop Audio |  | {} | self._stop_audio |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown_new.py:198 | view_btn | QPushButton | View Image |  | {} | self._view_image |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown_new.py:219 | delete_btn | QPushButton | Delete File |  | {} | self._delete_file |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/attachments_dropdown_new.py:276 | self.seek_slider | QSlider | Live inspection required |  | {"minimum": 0, "maximum": 1000} | self._on_slider_pressed, self._on_slider_released |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/internal_assign_ui.py:66 | self.manage_btn | QPushButton | Live inspection required |  | {} | self._open_shared_component |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:542 | btn | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:588 | btn | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:954 | self._add_points_btn | QPushButton | Start Adding Points |  | {} | self._toggle_point_adding |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:976 | undo_btn | QPushButton | Undo Last |  | {} | self._undo_last_curved_mpr_point |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:981 | clear_btn | QPushButton | Clear |  | {} | self._clear_curved_mpr_points |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:1002 | self._crown_arch_btn | QPushButton | Crown (occlusal) |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:1003 | self._apical_arch_btn | QPushButton | Apical (root) |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:1035 | self._thickness_slider | QSlider | Live inspection required |  | {"minimum": 2, "maximum": 30} | _on_thickness_changed |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:1052 | generate_btn | QPushButton | Generate Curved MPR |  | {} | self._generate_curved_mpr |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:1071 | close_btn | QPushButton | Close |  | {} | self._close_curved_mpr_panel |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:2019 | slider | QSlider | Live inspection required |  | {"minimum": 0} | on_slider_change |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:2035 | prev_btn | QPushButton | < Prev |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:2036 | next_btn | QPushButton | Next > |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:2037 | close_btn | QPushButton | Close |  | {} | dialog.close |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:3114 | lock_sync_btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4090 | _thick_slider | QSlider | Live inspection required |  | {"minimum": 1, "maximum": 50} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4105 | _rb_std | QRadioButton | Standard |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4106 | _rb_avg | QRadioButton | Thick Slab |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4106 | _rb_minip | QRadioButton | MinIP |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4106 | _rb_mip | QRadioButton | MIP |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4120 | _cb_ax | QCheckBox | Axial |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4120 | _cb_cor | QCheckBox | Coronal |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4120 | _cb_sag | QCheckBox | Sagittal |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:4134 | _open_btn | QPushButton | Open projection |  | {} | _on_open_projection |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8079 | series_layout_btn | QToolButton | Series Layout |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8134 | measurements_menu_btn | QPushButton | View Angle/Arrow/Text/ROI |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8254 | wl_menu_btn | QPushButton | CT Window Presets |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8292 | rotate_menu_btn | QPushButton | Rotate / Flip |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8383 | sync_menu_btn | QPushButton | Sync Options (Lock Sync) |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8486 | capture_menu_btn | QPushButton | View Captured Images |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8587 | mic_menu_btn | QPushButton | View Audio Recordings |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8703 | mic_cancel_btn | QPushButton | Cancel Recording |  | {} | self._on_mic_cancel |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8711 | mic_send_btn | QPushButton | Send and Finish |  | {} | self._on_mic_send |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8719 | mic_pause_btn | QPushButton | Pause Recording |  | {} | self._on_mic_pause_toggle |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8801 | mpr_menu_btn | QPushButton | View MIP/MinIP/Thick Slab |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8905 | upload_menu_btn | QPushButton | Select status |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:8948 | sync_btn | QPushButton | Sync patient data with server, close patient, and return to Home |  | {} | self.toggle_sync_point, self._on_patient_sync_clicked |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:9883 | b | QToolButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py:287 | self.btn_play | QPushButton | Play |  | {} | self._on_play_clicked |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py:293 | self.btn_record_pause | QPushButton | Pause |  | {} | self._on_record_pause_clicked |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py:299 | self.btn_save | QPushButton | Save |  | {} | self._on_save_clicked |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py:305 | self.btn_delete | QPushButton | Delete |  | {} | self._on_delete_clicked |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py:311 | self.btn_report | QPushButton | Report |  | {} | self._on_report_clicked |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py:318 | self.btn_sync | QPushButton | Sync |  | {} | self._on_sync_clicked |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_advanced.py:295 | b | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py:372 | self.series_thumb_btn | QPushButton | Series Thumbnails |  | {} | self._show_series_thumbnails_view |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py:412 | self.prev_exam_btn | QPushButton | Previous Exam |  | {} | self._toggle_previous_exams_view |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py:728 | self.btn_open_folder_attachments | QPushButton | Open Attachments |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_previous_exams.py:323 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_viewers.py:655 | slider | QSlider | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_panel_widget.py:202 | self.btn_open_folder_attachments | QPushButton | Open Attachments |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_panel_widget.py:211 | self.btn_view_reports | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py:222 | self.status_filter | QComboBox | Live inspection required | All, Pending, Read, Archived | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py:229 | self.btn_refresh | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py:281 | self.btn_mark_read | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py:286 | self.btn_archive | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py:291 | self.btn_copy | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/reception_reports_viewer.py:298 | self.btn_delete | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/patient_tab/ui/patient_ui/structured_report_view.py:55 | self.selector | QComboBox | Live inspection required |  | {} | self._select |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:114 | self.date_preset | QComboBox | Live inspection required |  | {} | self._on_date_preset_changed |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:120 | self.date_from | QDateEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:121 | self.date_to | QDateEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:142 | self.import_preset | QComboBox | Live inspection required |  | {} | self._on_import_preset_changed |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:148 | self.import_from | QDateEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:149 | self.import_to | QDateEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:174 | check | QCheckBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:182 | self.body_part_edit | QLineEdit | Body part (e.g. CHEST, KNEE) |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:187 | self.age_min | QSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 150} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:190 | self.age_max | QSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 150} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:198 | self.physician_edit | QLineEdit | Reporting doctor / radiologist (e.g. Alizadeh) |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:215 | self.cancel_btn | QPushButton | Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/home_ui/advanced_search_dialog.py:217 | self.search_btn | QPushButton | Search |  | {} | self.accept |
| PacsClient/pacs/workstation_ui/home_ui/data_access_panel.py:203 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/data_access_panel.py:298 | refresh_button | QPushButton | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/data_access_panel.py:355 | self.server_combo | QComboBox | Select the PACS or offline server for patient search |  | {} | self.on_server_changed |
| PacsClient/pacs/workstation_ui/home_ui/data_access_panel.py:522 | self.select_folder_btn | QPushButton | Live inspection required |  | {} | self.method_select_folder |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1077 | self.output_dir_input | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1080 | browse_btn | QPushButton | Browse |  | {} | self.browse_output_directory |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1088 | self.batch_size_input | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 100} |  |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1098 | self.compression_combo | QComboBox | Live inspection required | gzip, none | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1105 | self.resume_checkbox | QCheckBox | Resume from previous download |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1112 | start_btn | QPushButton | Start Download |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1117 | resume_btn | QPushButton | Resume Only |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_download.py:1121 | cancel_btn | QPushButton | Cancel |  | {} | dialog.reject |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py:202 | self.adaptive_layout_btn | QPushButton | Auto-fit table columns and keep controls visible on any screen size |  | {} | self.apply_adaptive_layout |
| PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py:432 | self.socket_test_btn | QPushButton | Live inspection required |  | {} | self.check_socket_connection_status |
| PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py:1125 | self.select_all_series_button | QPushButton | Select All |  | {} | self._on_select_all_series_clicked |
| PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py:1130 | self.clear_series_button | QPushButton | Clear |  | {} | self._on_clear_series_clicked |
| PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py:1171 | self.summary_toggle_button | QToolButton | Live inspection required |  | {} | self._set_summary_expanded |
| PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py:1213 | cancel_btn | QPushButton | Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py:1218 | self.import_button | QPushButton | Import Selected Into AI-PACS |  | {} | self._accept_if_selection_valid |
| PacsClient/pacs/workstation_ui/home_ui/internal_assignment_panel.py:158 | b | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/internal_assignment_panel.py:180 | self._search | QLineEdit | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/internal_assignment_panel.py:211 | self._send | QPushButton | Assign to selected (0) |  | {} | self._on_assign_clicked |
| PacsClient/pacs/workstation_ui/home_ui/internal_assignment_panel.py:309 | cb | QCheckBox | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/internal_assignment_panel.py:563 | close | QPushButton | Close |  | {} | self.accept |
| PacsClient/pacs/workstation_ui/home_ui/offline_cloud_export_dialog.py:336 | self.server_combo | QComboBox | Live inspection required |  | {} | self._update_server_details |
| PacsClient/pacs/workstation_ui/home_ui/offline_cloud_export_dialog.py:425 | cancel_btn | QPushButton | Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/home_ui/offline_cloud_export_dialog.py:430 | export_btn | QPushButton | Start Export |  | {} | self._accept_export |
| PacsClient/pacs/workstation_ui/home_ui/offline_cloud_manager_dialog.py:86 | self._server_combo | QComboBox | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/offline_cloud_manager_dialog.py:91 | self._refresh_btn | QPushButton | Refresh |  | {} | self._reload |
| PacsClient/pacs/workstation_ui/home_ui/offline_cloud_manager_dialog.py:111 | self._delete_btn | QPushButton | Delete Selected Patient(s) |  | {} | self._on_delete |
| PacsClient/pacs/workstation_ui/home_ui/offline_cloud_manager_dialog.py:118 | close_btn | QPushButton | Close |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/home_ui/patient_edit_dialog.py:189 | self._revert_btn | QPushButton | Reset fields |  | {} | self._reset_fields |
| PacsClient/pacs/workstation_ui/home_ui/patient_edit_dialog.py:204 | editor | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:168 | check | QCheckBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:224 | self.search_btn | QPushButton | Live inspection required |  | {} | self._on_search_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:262 | self.cancel_search_btn | QPushButton | Live inspection required |  | {} | self._on_cancel_search_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:304 | self.patient_id_edit | QLineEdit | Patient ID (e.g., 12345) |  | {"maxLength": 50} | self._on_search_clicked, self._open_advanced_search_dialog |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:318 | self.patient_name_edit | QLineEdit | Patient Name (e.g., John Doe) |  | {"maxLength": 100} | self._on_search_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:330 | self.patient_sex | QLineEdit | Gender (M/F/O) |  | {"maxLength": 1} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:336 | self.study_id | QLineEdit | Study ID (e.g., S001) |  | {"maxLength": 50} | self._on_search_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:343 | self.date_selector | QComboBox | Live inspection required | Custom Date, All Dates, Today, Yesterday, Two days ago, Last Week, Last Month, Last Year | {} | self._on_date_selector_changed, self._on_date_selector_activated |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:363 | self.date_from_edit | QDateEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:369 | self.date_to_edit | QDateEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:374 | self.study_description | QLineEdit | Study Description (e.g., Chest CT) |  | {"maxLength": 200} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:380 | self.series_description | QLineEdit | Series Description (e.g., Axial) |  | {"maxLength": 200} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:386 | self.modality | QComboBox | Live inspection required | All Modalities, CT, MR, US, CR, DX, MG, NM, PT, RF, SC, XA | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py:402 | self.request_type | QComboBox | Live inspection required | All Types, Study Query, Patient Query, Series Query | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:638 | reset_btn | QPushButton | Reset to Default |  | {} | self.reset_to_default |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:776 | checkbox | QCheckBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:841 | checkbox | QCheckBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1571 | self.download_btn | QPushButton | Download selected studies with Zeta Download Manager |  | {} | self._on_zeta_download_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1608 | self.delete_btn | QPushButton | Delete selected downloaded studies |  | {} | self._on_delete_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1650 | self.cd_burn_btn | QPushButton | Write selected downloaded studies to CD/DVD with DICOMDIR |  | {} | self._on_cd_burn_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1688 | self.print_btn | QPushButton | Print selected studies |  | {} | self._on_print_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1724 | self.offline_export_btn | QPushButton | Manual hub sync with an Offline Cloud Server folder (for USB / Dropbox / Google Drive style exchange) |  | {} | self._on_offline_cloud_sync_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1776 | self.settings_btn | QPushButton | Column Settings (Order and Visibility) |  | {} | self._open_column_settings |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1784 | self.refresh_btn | QPushButton | Live inspection required |  | {} | self.refresh_download_statuses |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1796 | self.font_increase_btn | QPushButton | A+ |  | {} | self._on_font_increase_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:1803 | self.font_decrease_btn | QPushButton | A- |  | {} | self._on_font_decrease_clicked |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:2448 | add_btn | QPushButton | Add Selected Patient to Offline Service |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:2456 | manage_btn | QPushButton | Edit or Delete Existing Offline Patients |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:2462 | cancel_btn | QPushButton | Cancel |  | {} | dlg.reject |
| PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py:4362 | checkbox_widget | QCheckBox | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/report_status_dialog.py:83 | self.status_combo | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/report_status_dialog.py:170 | cancel_btn | QPushButton | Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/home_ui/report_status_dialog.py:189 | apply_btn | QPushButton | Apply Change |  | {} | self.apply_change |
| PacsClient/pacs/workstation_ui/home_ui/report_status_dialog.py:241 | btn | QToolButton | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:710 | self.close_btn | QToolButton | Close popup |  | {} | self.close |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:918 | self._no_btn | QPushButton | No, Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:937 | self._yes_btn | QPushButton | Yes, Proceed |  | {} | self.accept |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:1150 | self.report_issue_button | QToolButton | Review and send an AI-PACS support issue |  | {} | self._open_support_issue |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:1178 | self.command_input | QLineEdit | LOCAL ONLY |  | {"maxLength": 20000} | self._send_typed_command |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:1184 | self.command_send | QPushButton | LOCAL ONLY |  | {} | self._send_typed_command |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:1209 | self.memory_new_btn | QToolButton | Start a new conversation memory file |  | {} | self._on_new_memory |
| PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py:1235 | self.log_expand_icon | QToolButton | Details |  | {} | self._toggle_log_popup |
| PacsClient/pacs/workstation_ui/home_ui/secretary_clarification_dialog.py:58 | button | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/secretary_clarification_dialog.py:61 | self.custom | QLineEdit | Or explain what you mean... |  | {"maxLength": 2000} | Dynamic callback, Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/secretary_clarification_dialog.py:63 | submit | QPushButton | Send answer |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/secretary_clarification_dialog.py:68 | cancel | QPushButton | Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/home_ui/secretary_compact_ui.py:52 | open_button | QPushButton | Conversation |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/secretary_compact_ui.py:56 | mute | QPushButton | Sound on |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/secretary_compact_ui.py:66 | widget.mode_selector | QComboBox | LOCAL ONLY |  | {} | mode_changed |
| PacsClient/pacs/workstation_ui/home_ui/secretary_header_shortcut.py:11 | button | QToolButton | LOCAL ONLY |  | {} | toggle |
| PacsClient/pacs/workstation_ui/home_ui/secretary_popup.py:69 | self.close_btn | QToolButton | Close (cancels listening if active) |  | {} | self.request_close |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:52 | self.expand_button | QPushButton | Open |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:55 | close_button | QPushButton | Close |  | {} | self.close |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:91 | self.play | QPushButton | Read aloud |  | {} | self.speak |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:92 | self.stop_button | QPushButton | Stop |  | {} | self.stop |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:93 | self.auto_voice | QCheckBox | Speak new replies |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:94 | self.include_screen | QCheckBox | Include screen context |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:96 | details | QPushButton | Details |  | {} | self.detailsRequested.emit |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:102 | self.command_input | QLineEdit | LOCAL ONLY |  | {"maxLength": 20000} | self._submit_command |
| PacsClient/pacs/workstation_ui/home_ui/secretary_response_panel.py:106 | send | QPushButton | Send |  | {} | self._submit_command |
| PacsClient/pacs/workstation_ui/home_ui/series_selection_widget.py:101 | self.select_all_cb | QCheckBox | Select all series |  | {} | self._on_select_all_clicked |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:57 | self.category | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:70 | self.voice | QPushButton | Speak issue |  | {} | self._voice_clicked |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:80 | self.windows | QCheckBox | Include Windows crash / hang fields (last 24 hours) |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:82 | self.log_archive | QCheckBox | Attach raw log ZIP from the last 24 hours (may include sensitive information) |  | {} |  |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:87 | self.consent | QCheckBox | I reviewed this report and agree to send it. |  | {} | self._buttons |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:95 | self.send | QPushButton | Send issue |  | {} | self._submit |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:97 | self.retry | QPushButton | Retry pending issue |  | {} | self._retry |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:99 | self.discard | QPushButton | Discard pending issue |  | {} | self._discard |
| PacsClient/pacs/workstation_ui/home_ui/support_issue_dialog.py:101 | self.close_button | QPushButton | Close |  | {} | self.close |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:148 | self._chk_enabled | QCheckBox | Enable Agent Gateway |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:153 | self._cmb_transport | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:164 | self._cmb_advertise | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:177 | self._spn_port | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:181 | self._chk_tls | QCheckBox | TLS (self-signed, cert-pinned via QR) |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:193 | self._btn_apply | QPushButton | Save & Apply |  | {} | self._on_apply |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:196 | self._btn_refresh | QPushButton | Refresh status |  | {} | self._refresh_status |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:236 | self._btn_pair | QPushButton | Generate Pairing QR |  | {} | self._on_generate_pairing |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:259 | self._ed_mcp_path | QLineEdit | /mcp |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:263 | self._cmb_mode | QComboBox | Live inspection required |  | {} | self._update_mode_warning |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:297 | self._ed_relay_url | QLineEdit | https://relay.example.com |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:301 | self._ed_relay_ws | QLineEdit | e.g. clinic-room-3 |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:305 | self._ed_relay_token | QLineEdit | LOCAL ONLY |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:327 | btn | QPushButton | Refresh devices |  | {} | self._refresh_devices |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:480 | cmb | QComboBox | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py:491 | btn | QPushButton | Revoke |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:318 | self.btn_export_education | QPushButton | Export Education... |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:319 | self.btn_import_education | QPushButton | Import Education... |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:368 | self.btn_signin_google | QPushButton | Sign in with Google |  | {} | self._sign_in_aipacs_web |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:371 | self.btn_signin_account | QPushButton | Sign in with AI-PACS account |  | {} | self._sign_in_with_account |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:387 | self.btn_signout | QPushButton | Sign out of AI-PACS |  | {} | self._disconnect_aipacs |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:458 | self.btn_check_access | QPushButton | Check access |  | {} | self._check_access |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:492 | self.edit_base_url | QLineEdit | Server address: |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:494 | self.chk_web_enabled | QCheckBox | Enable the AI-PACS website connection |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:501 | self.btn_save_web | QPushButton | Save server settings |  | {} | self._save_web_config |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:510 | self.btn_open_portal | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:512 | self.btn_open_library | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:514 | self.btn_open_profile | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:516 | self.btn_open_website | QPushButton | Live inspection required |  | {} | self._open_website |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:530 | self.edit_consult_addr | QLineEdit | Consultation address: |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:533 | self.edit_center_id | QLineEdit | Center ID: |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:536 | self.chk_hub_mode | QCheckBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:548 | self.btn_save_center | QPushButton | Save workstation settings |  | {} | self._save_center_identity |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:559 | self.chk_identity_enabled | QCheckBox | Identity (external accounts and sign-in) |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:561 | self.chk_cloud_enabled | QCheckBox | Cloud consultation |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:562 | self.chk_chat_enabled | QCheckBox | AiPacs Chat console |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:576 | self.btn_save_gates | QPushButton | Save module settings |  | {} | self._save_gate_flags |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:578 | self.btn_chat_test | QPushButton | Test chat connection |  | {} | self._test_chat_connection |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:596 | self.btn_open_web_console | QPushButton | Live inspection required |  | {} | self._open_web_chat_console |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:598 | self.btn_open_visitors | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:601 | self.btn_open_drive_panel | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:604 | self.btn_open_greetings | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:621 | self.btn_drive_connect | QPushButton | Live inspection required |  | {} | self._connect_drive |
| PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py:623 | self.btn_drive_disconnect | QPushButton | Disconnect Drive |  | {} | self._disconnect_drive |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:37 | self.url | QLineEdit | https://eagle-eye.example:8042 |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:39 | self.token_file | QLineEdit | LOCAL ONLY |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:41 | self.ca_file | QLineEdit | Optional trusted CA file |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:43 | self.client_certificate | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:44 | self.client_private_key | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:55 | self.save_button | QPushButton | Save connection |  | {} | self._save |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:56 | self.test_button | QPushButton | Test connection |  | {} | self._test |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:57 | self.reload_button | QPushButton | Reload |  | {} | self._load |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:58 | self.jobs_button | QPushButton | Refresh my jobs |  | {} | self._jobs |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:70 | self.listen_host | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:71 | self.listen_port | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:73 | self.listen_certificate | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:74 | self.listen_private_key | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:85 | self.listener_button | QPushButton | Save listener settings for next start |  | {} | self._save_listener |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:92 | self.source_mode | QComboBox | Live inspection required | Existing workstation cache, PACS metadata and mapped storage | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:95 | self.pacs_url | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:96 | self.dicom_port | QSpinBox | DICOM port |  | {"minimum": 1, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:97 | self.socket_port | QSpinBox | Patient/download socket port |  | {"minimum": 1, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:98 | self.local_pacs_button | QPushButton | Use PACS on this computer |  | {} | self._local_pacs |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:103 | self.database | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:104 | self.job_root | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:116 | self.source_button | QPushButton | Save source settings for next start |  | {} | self._save_source |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:119 | self.pacs_username | QLineEdit | PACS service username |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:120 | self.pacs_password | QLineEdit | LOCAL ONLY |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:124 | self.account_button | QPushButton | Save encrypted PACS account |  | {} | self._save_account |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:127 | self.pacs_test_button | QPushButton | Test saved PACS connection |  | {} | self._test_pacs |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:142 | self.service_refresh_button | QPushButton | Refresh service status |  | {} | self._service_status |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:145 | self.service_install_button | QPushButton | Install automatic service (administrator) |  | {} | self._install_service |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:158 | self.parallel | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 8} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:159 | self.cpu | QSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 512} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:160 | self.ram | QSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 4194304} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:163 | self.quota | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 16} |  |
| PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py:176 | self.resources_button | QPushButton | Save resource policy for next start |  | {} | self._save_resources |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:330 | button | QPushButton | Live inspection required |  | {} | self._open_reception_templates |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:333 | review | QPushButton | Live inspection required |  | {} | self._open_organized_templates |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:354 | self.backend_combo | QComboBox | Live inspection required | AI PACS Ecomind Backend, OpenAI Direct Backend | {} | self._on_backend_changed |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:369 | self.backend_save_btn | QPushButton | Save Backend Selection |  | {} | self._on_save_backend_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:411 | self.proxy_type_combo | QComboBox | Live inspection required | Direct (No Proxy) | {} | self._on_proxy_type_changed |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:418 | self.proxy_port_combo | QComboBox | Live inspection required | 2080, 2081, 2082 | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:429 | self.proxy_save_btn | QPushButton | Save Proxy Settings |  | {} | self._on_save_proxy_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:462 | self.key_input | QLineEdit | LOCAL ONLY |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:467 | self.auth_btn | QPushButton | Authenticate |  | {} | self._on_authenticate_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:489 | combo | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:524 | self.openai_api_key_input | QLineEdit | LOCAL ONLY |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:530 | self.openai_base_url_input | QLineEdit | Enter your provider's API base URL |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:535 | self.openai_org_input | QLineEdit | Optional organization header |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:538 | self.openai_project_input | QLineEdit | Optional project header |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:563 | self.openai_reasoning_combo | QComboBox | Live inspection required | Default, None, Minimal, Low, Medium, High, XHigh | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:575 | self.openai_temperature_spin | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.0, "maximum": 2.0, "decimals": 2} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:581 | self.openai_max_tokens_spin | QSpinBox | LOCAL ONLY |  | {"minimum": 1, "maximum": 32000} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:585 | self.openai_timeout_spin | QSpinBox | Live inspection required |  | {"minimum": 5, "maximum": 600} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:596 | self.openai_eagle_screening_input | QLineEdit | Model ID from your provider |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:598 | self.openai_eagle_diagnosis_input | QLineEdit | Model ID from your provider |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:619 | self.openai_save_btn | QPushButton | Save OpenAI Settings |  | {} | self._on_save_openai_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:624 | self.openai_test_btn | QPushButton | Test OpenAI Connection |  | {} | self._on_test_openai_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:673 | self.prompt_save_btn | QPushButton | Save Prompt Settings |  | {} | self._on_save_prompts_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:693 | self.refresh_usage_btn | QPushButton | Refresh Usage |  | {} | self._on_refresh_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:803 | self.provider_combo | QComboBox | Live inspection required |  | {} | self._on_provider_changed |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:809 | self.stt_url_input | QLineEdit | http://192.168.1.50 |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:812 | self.stt_port_input | QSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:817 | self.stt_path_input | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:820 | self.stt_timeout_input | QSpinBox | Live inspection required |  | {"minimum": 5, "maximum": 3600} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:825 | self.stt_token_input | QLineEdit | LOCAL ONLY |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:829 | self.stt_save_btn | QPushButton | Save Voice to Text |  | {} | self._on_save_stt_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py:832 | self.stt_test_btn | QPushButton | Test Connection |  | {} | self._on_test_stt_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:89 | self._service_combo | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:95 | self._ae_title_edit | QLineEdit | Remote AE Title (max 16 chars) |  | {"maxLength": 16} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:106 | self._dimse_radio | QRadioButton | DIMSE |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:107 | self._dicomweb_radio | QRadioButton | DICOMWeb |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:118 | self._desc_edit | QLineEdit | Optional description |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:135 | self._ip_edit | QLineEdit | e.g. 192.168.1.100 |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:140 | self._port_spin | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:156 | self._qido_edit | QLineEdit | https://pacs.example.com/dicom-web/studies |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:161 | self._wado_edit | QLineEdit | https://pacs.example.com/dicom-web/studies |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:166 | self._stow_edit | QLineEdit | https://pacs.example.com/dicom-web/studies |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:182 | self._auth_check | QCheckBox | Enable authentication |  | {} | self._on_auth_toggled |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:186 | self._user_edit | QLineEdit | Username |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:192 | self._pass_edit | QLineEdit | LOCAL ONLY |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:203 | self._tls_check | QCheckBox | Use TLS / SSL encryption |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:212 | ok_btn | QPushButton | OK |  | {} | self._on_ok |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_server_dialog.py:218 | cancel_btn | QPushButton | Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:141 | self._new_btn | QPushButton | Live inspection required |  | {} | self._on_new |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:147 | self._delete_btn | QPushButton | Delete |  | {} | self._on_delete |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:154 | self._edit_btn | QPushButton | Live inspection required |  | {} | self._on_edit |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:160 | self._refresh_btn | QPushButton | Refresh |  | {} | self._load_and_display |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:165 | self._echo_btn | QPushButton | Echo |  | {} | self._on_echo_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:184 | self._local_ae_edit | QLineEdit | AIPACS_SCU |  | {"maxLength": 16} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:190 | self._local_port_spin | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/external_pacs_settings.py:195 | save_scp_btn | QPushButton | Save SCP Settings |  | {} | self._save_scp_settings |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:201 | self._header_btn | QToolButton | Live inspection required |  | {} | self._on_toggled |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:765 | self.preset_combo | QComboBox | Live inspection required |  | {} | self._on_preset_selected |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:776 | save_as | QPushButton | Live inspection required |  | {} | self.save_preset_as |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:794 | save | QPushButton | Live inspection required |  | {} | self.save_config |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:799 | reload_btn | QPushButton | Live inspection required |  | {} | self.load_config |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:804 | reset | QPushButton | Live inspection required |  | {} | self.reset_to_default |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:850 | enabled_cb | QCheckBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:922 | enabled | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:975 | enabled | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1023 | enabled | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1037 | sigmas_edit | QLineEdit | Smaller values target fine detail; larger values target broader edges. |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1051 | amounts_edit | QLineEdit | Higher amounts sharpen more but can create halos. |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1066 | mild_sigmas_edit | QLineEdit | Use larger values to avoid ringing on thick slices. |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1080 | mild_amounts_edit | QLineEdit | Lower values help prevent over-sharpening in mild mode. |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1093 | enabled | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1141 | en | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1262 | enabled | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1310 | enabled | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/filter_config.py:1358 | enabled | QCheckBox | Enabled |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/hardware_check_panel.py:79 | self.run_button | QPushButton | Runs the full hardware check now and saves the result. Use this after updating the graphics (GPU) driver. |  | {} | self._on_run_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:228 | self.refresh_btn | QPushButton | Refresh |  | {} | self.refresh_modules |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:232 | self.install_file_btn | QPushButton | Install Package... |  | {} | self.install_from_file |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:236 | self.install_folder_btn | QPushButton | Install From Folder... |  | {} | self.install_from_folder |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:240 | self.install_url_btn | QPushButton | Install From URL... |  | {} | self.install_from_url |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:244 | self.toggle_btn | QPushButton | Enable |  | {} | self.toggle_selected_module |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:248 | self.test_btn | QPushButton | Test Module |  | {} | self.test_selected_module |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:252 | self.open_runtime_btn | QPushButton | Open Runtime Folder |  | {} | self.open_runtime_folder |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:312 | self.auto_check_checkbox | QCheckBox | Check for updates at startup |  | {} | self._on_auto_check_toggled |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:331 | self.check_updates_btn | QPushButton | Check Updates |  | {} | self.refresh_updates |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:335 | self.set_update_folder_btn | QPushButton | Set Update Folder... |  | {} | self.set_update_folder |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:339 | self.set_update_url_btn | QPushButton | Set Update URL... |  | {} | self.set_update_url |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:343 | self.apply_update_btn | QPushButton | Apply Selected Update |  | {} | self.apply_selected_update |
| PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py:347 | self.open_update_source_btn | QPushButton | Open Update Source |  | {} | self.open_update_source |
| PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py:175 | self.default_viewer_rb | QRadioButton | Use the default AI-PACS portable viewer (recommended) |  | {} | self._on_mode_changed |
| PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py:176 | self.custom_viewer_rb | QRadioButton | Use a custom portable viewer executable |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py:197 | self.path_edit | QLineEdit | Select the Light Viewer executable (.exe) |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py:229 | self.browse_btn | QPushButton | Browse... |  | {} | self.browse_for_viewer |
| PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py:275 | self.clear_btn | QPushButton | Clear Path |  | {} | self.clear_viewer_path |
| PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py:307 | self.disc_label_edit | QLineEdit | Default Disc Label: |  | {"maxLength": 32} |  |
| PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py:341 | save_btn | QPushButton | Save Settings |  | {} | self.save_settings |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_package_dialog.py:160 | reload_btn | QPushButton | Reload |  | {} | self.refresh_view |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_package_dialog.py:162 | validate_btn | QPushButton | Validate |  | {} | self._validate_only |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_package_dialog.py:164 | rebuild_btn | QPushButton | Rebuild JSON |  | {} | self._rebuild_json |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_package_dialog.py:167 | save_btn | QPushButton | Save JSON |  | {} | self._save_json |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_package_dialog.py:170 | open_btn | QPushButton | Open Folder |  | {} | self._open_folder |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_package_dialog.py:172 | close_btn | QPushButton | Close |  | {} | self.accept |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_server_dialog.py:92 | self.name_edit | QLineEdit | Offline Cloud Server Name |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_server_dialog.py:97 | self.folder_edit | QLineEdit | C:\Shared\AIPacsOfflineCloud |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_server_dialog.py:101 | browse_btn | QPushButton | Live inspection required |  | {} | self._browse_folder |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_server_dialog.py:106 | self.description_edit | QLineEdit | Optional note shown in Settings |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_server_dialog.py:115 | ok_btn | QPushButton | Save |  | {} | self._on_accept |
| PacsClient/pacs/workstation_ui/settings_ui/offline_cloud_server_dialog.py:118 | cancel_btn | QPushButton | Cancel |  | {} | self.reject |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:222 | eagle_eye | QPushButton | Live inspection required |  | {} | self.eagleEyeSettingsRequested.emit |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:325 | self.name_edit | QLineEdit | Server Name |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:330 | self.host_edit | QLineEdit | 192.168.1.100 |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:340 | self.port_edit | QLineEdit | 104 |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:345 | self.ae_title_edit | QLineEdit | AE_TITLE |  | {"maxLength": 16} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:358 | self.poor_conn_check | QCheckBox | Poor connectivity / unstable internet (download one image at a time) |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:382 | self._socket_port_edit | QLineEdit | 50052 |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:409 | _e | QLineEdit | host:port (optional) |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:423 | self._svc_fill_btn | QPushButton | Fill service URLs from host (default ports) |  | {} | self._fill_service_defaults_from_host |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:428 | local_profile | QPushButton | Use local PACS and Reception (keep ports) |  | {} | self._local_server_profile |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:443 | self.save_btn | QPushButton | Save |  | {} | self.save_server |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:448 | self.verify_btn | QPushButton | Verify |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:463 | self.delete_btn | QPushButton | Delete |  | {} | self.delete_server |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:469 | self.clear_btn | QPushButton | Clear |  | {} | self.clear_form |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:521 | edit | QLineEdit | http://host:port |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:530 | approve_btn | QPushButton | Approve |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:550 | self._ai_service_save_btn | QPushButton | Save URLs |  | {} | self._save_ai_service_urls |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:555 | self._ai_service_load_btn | QPushButton | Load |  | {} | self._load_ai_service_urls |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:623 | self._local_ae_edit | QLineEdit | AIPACS_SCU |  | {"maxLength": 16} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:629 | self._local_port_spin | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 65535} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:639 | save_scp | QPushButton | Save SCP |  | {} | self._ext_save_scp_settings |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:653 | self._ext_new_btn | QPushButton | Live inspection required |  | {} | self._ext_on_new |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:658 | self._ext_echo_btn | QPushButton | Echo |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:666 | self._ext_verify_all_btn | QPushButton | Verify All |  | {} | self._ext_verify_all |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:680 | self._ext_delete_btn | QPushButton | Delete |  | {} | self._ext_on_delete |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:686 | self._ext_edit_btn | QPushButton | Live inspection required |  | {} | self._ext_on_edit |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:691 | self._ext_refresh_btn | QPushButton | Refresh |  | {} | self._ext_load_and_display |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:766 | self._cloud_new_btn | QPushButton | Live inspection required |  | {} | self._cloud_on_new |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:770 | self._cloud_edit_btn | QPushButton | Live inspection required |  | {} | self._cloud_on_edit |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:774 | self._cloud_delete_btn | QPushButton | Delete |  | {} | self._cloud_on_delete |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:779 | self._cloud_open_btn | QPushButton | Open Folder |  | {} | self._cloud_open_folder |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:783 | self._cloud_manifest_btn | QPushButton | Package JSON... |  | {} | self._cloud_open_manifest |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:787 | self._cloud_refresh_btn | QPushButton | Refresh |  | {} | self._cloud_load_and_display |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:979 | verify_btn | QPushButton | Verify |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1633 | self._reception_api_edit | QLineEdit | http://host:port |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1640 | test_btn | QPushButton | Test |  | {} | self._on_reception_api_test |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1654 | save_btn | QPushButton | Save Endpoint |  | {} | self._save_reception_api_settings |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1658 | load_btn | QPushButton | Load |  | {} | self._load_reception_api_settings |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1665 | local_reception | QPushButton | Use Reception on this computer (keep port) |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1704 | self._ino_assign_enable | QCheckBox | Enable internal assignment |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1710 | self._ino_assign_base_edit | QLineEdit | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1725 | self._ino_assign_transport | QComboBox | Live inspection required | REST (PACS HTTP :8000) | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1735 | save | QPushButton | Save Assignment Settings |  | {} | self._save_ino_assign_settings |
| PacsClient/pacs/workstation_ui/settings_ui/server_settings.py:1739 | load | QPushButton | Load |  | {} | self._load_ino_assign_settings |
| PacsClient/pacs/workstation_ui/settings_ui/servers_config.py:131 | le | QLineEdit | http://host:port |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/servers_config.py:139 | btn | QPushButton | Approve |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/servers_config.py:160 | self.save_urls_btn | QPushButton | Save URLs |  | {} | self.on_save |
| PacsClient/pacs/workstation_ui/settings_ui/servers_config.py:165 | self.load_urls_btn | QPushButton | Load |  | {} | self.load_from_file |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:252 | refresh_btn | QPushButton | Live inspection required |  | {} | self._on_refresh_storage_info_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:262 | consistency_btn | QPushButton | Find DB/file mismatches (studies still marked downloaded but whose files are gone, dangling thumbnails) and optionally repair them so the green/downloaded status matches the actual local files. |  | {} | self._on_check_consistency_clicked |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:372 | clear_btn | QPushButton | Live inspection required |  | {} | self._on_clear_patients_clicked, Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:745 | all_radio | QRadioButton | Clear ALL patient data (folders + database) |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:753 | recent_radio | QRadioButton | Delete locally stored patients older than |  | {} | recent_spin.setEnabled |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:756 | recent_spin | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 365} |  |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:772 | count_radio | QRadioButton | Delete oldest |  | {} | count_spin.setEnabled |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:775 | count_spin | QSpinBox | Live inspection required |  | {"minimum": 1, "maximum": 10000} |  |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:796 | preview_btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:811 | execute_btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py:826 | cancel_btn | QPushButton | Cancel |  | {} | dialog.reject |
| PacsClient/pacs/workstation_ui/settings_ui/tools_settings_ui.py:89 | self.line_width_spin | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.5, "maximum": 20.0} |  |
| PacsClient/pacs/workstation_ui/settings_ui/tools_settings_ui.py:108 | self.opacity_slider | QSlider | Live inspection required |  | {"minimum": 0, "maximum": 100} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/tools_settings_ui.py:124 | self.font_size_spin | QDoubleSpinBox | Live inspection required |  | {"minimum": 8, "maximum": 72} |  |
| PacsClient/pacs/workstation_ui/settings_ui/tools_settings_ui.py:316 | reset_btn | QPushButton | Reset to Defaults |  | {} | self.reset_to_defaults |
| PacsClient/pacs/workstation_ui/settings_ui/tools_settings_ui.py:322 | save_btn | QPushButton | Save Settings |  | {} | self.save_settings |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:74 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:347 | self.new_name | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:364 | self.preset_combo | QComboBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:372 | add_btn | QPushButton | Add |  | {} | self.add_modality |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:402 | self.viewer_mode_combo | QComboBox | Live inspection required |  | {} | self._refresh_gpu_status |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:439 | self.gpu_boost_toggle | QCheckBox | Use GPU when available |  | {} | self._refresh_gpu_status |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:473 | self.boostviewer_toggle | QCheckBox | Live inspection required |  | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:475 | self.viewer_backend_combo | QComboBox | Live inspection required | VTK / SimpleITK (Current), PyDK (PyDicom 2D Lazy Load) | {} |  |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:484 | save | QPushButton | Live inspection required |  | {} | self.save_config |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:494 | reload_btn | QPushButton | Live inspection required |  | {} | self.load_config |
| PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py:689 | rm | QToolButton | Live inspection required |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/ai_mainwindow.py:102 | self.function_button | QPushButton | Choose Function |  | {} | self.workspace_controller.choose_function |
| modules/ai_imaging/ai_module_ui/cursor_3d/dual_view_widget.py:258 | close_btn | QPushButton | Live inspection required |  | {} | self._on_close |
| modules/ai_imaging/ai_module_ui/cursor_3d/dual_view_widget.py:290 | self._btn_interior | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/cursor_3d/dual_view_widget.py:296 | self._btn_middle | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/cursor_3d/dual_view_widget.py:302 | self._btn_posterior | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/cursor_3d/dual_view_widget.py:313 | self._btn_clear | QPushButton | Clear |  | {} | self._on_clear |
| modules/ai_imaging/ai_module_ui/cursor_3d/guided_picker.py:104 | self._back_btn | QPushButton | Live inspection required |  | {} | self.back_requested.emit |
| modules/ai_imaging/ai_module_ui/cursor_3d/guided_picker.py:106 | cancel_btn | QPushButton | Cancel |  | {} | self.cancel_requested.emit |
| modules/ai_imaging/ai_module_ui/cursor_3d/nipple_picker.py:172 | cancel_btn | QPushButton | Cancel |  | {} | self._cancel |
| modules/ai_imaging/ai_module_ui/cursor_3d/pectoral_picker.py:186 | cancel_btn | QPushButton | Cancel |  | {} | self._cancel |
| modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py:1693 | btn | QPushButton | Hide Boxes |  | {} | self._toggle_ai_boxes |
| modules/ai_imaging/ai_module_ui/service_tab/abstract_tab.py:67 | button | QPushButton | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/dataset_tab.py:614 | self.refresh_btn | QPushButton | Live inspection required |  | {} | self._refresh_results |
| modules/ai_imaging/ai_module_ui/service_tab/dataset_tab.py:636 | self.columns_btn | QPushButton | Columns |  | {} | self._show_columns_menu |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:271 | self.corrected_years_edit | QLineEdit | e.g. 13.5 |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:275 | self.corrected_months_edit | QLineEdit | e.g. 162 |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:279 | self.corrected_sex_combo | QComboBox | Live inspection required | male, female | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:283 | self.validation_combo | QComboBox | Live inspection required | pending_review, confirmed, corrected, excluded | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:287 | self.reviewer_edit | QLineEdit | Reviewer ID |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:296 | self.save_review_btn | QPushButton | Save Review |  | {} | self._save_review |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:538 | widget | QLineEdit | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:561 | self.action_combo | QComboBox | Live inspection required | confirmed, rejected, corrected, new_human_finding | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:564 | self.validation_combo | QComboBox | Live inspection required | pending, confirmed, rejected, corrected, new_human_finding, excluded | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:567 | self.reviewer_edit | QLineEdit | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:726 | self.eagle_eye_result_btn | QPushButton | View Eagle Eye Result |  | {} | self._eagle_eye_workflow.open_result |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:834 | self.lst_boxes_combo | QComboBox | Live inspection required |  | {} | Dynamic callback, Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:847 | self.rb_normal | QRadioButton | Normal |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:848 | self.rb_abnormal | QRadioButton | Abnormal |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:885 | self.validation_combo | QComboBox | Live inspection required | pending_review, confirmed, corrected, excluded | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:889 | self.reviewer_edit | QLineEdit | Reviewer ID |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:898 | self.laterality_combo | QComboBox | Live inspection required | Left, Right, Bilateral, Unknown | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:902 | self.view_combo | QComboBox | Live inspection required | CC, MLO, ML, LM, XCCL, XCCM, Other | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:906 | self.lesion_type_combo | QComboBox | Live inspection required | No Finding, Mass, Suspicious Calcification, Focal Asymmetry, Architectural Distortion, Other | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:918 | self.location_edit | QLineEdit | Free-text location |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:922 | self.quadrant_combo | QComboBox | Live inspection required | UOQ, UIQ, LOQ, LIQ, Central, Retroareolar, Axillary Tail | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:926 | self.clock_edit | QLineEdit | e.g. 2 o'clock |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:930 | self.depth_combo | QComboBox | Live inspection required | Anterior, Middle, Posterior | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:934 | self.birads_combo | QComboBox | Live inspection required | 0, 1, 2, 3, 4A, 4B, 4C, 5, 6 | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:938 | self.confidence_edit | QLineEdit | 0.00 - 1.00 |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:942 | self.human_action_combo | QComboBox | Live inspection required | update, confirm, correct, remove, new_finding | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:946 | self.mg_runs_combo | QComboBox | Live inspection required |  | {} | self._on_mg_run_changed |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:950 | self.apply_btn | QPushButton | Apply |  | {} | self._on_apply_clicked |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:951 | self.new_finding_btn | QPushButton | New Finding |  | {} | self._on_new_mg_finding_clicked |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:952 | self.save_finding_btn | QPushButton | Save Finding |  | {} | self._on_save_mg_finding_clicked |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:953 | self.confirm_finding_btn | QPushButton | Confirm |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:954 | self.reject_finding_btn | QPushButton | Reject |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:955 | self.edit_finding_btn | QPushButton | Correct / Edit |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:1521 | btn | QPushButton | Live inspection required |  | {} | slot |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:1583 | self.cursor3d_findings_combo | QComboBox | Select which corresponding lesion to review |  | {} | self._on_cursor3d_finding_combo |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:2657 | import_btn | QPushButton | Import Folder |  | {} | self.toggle_import_folder |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:2661 | export_file_btn | QPushButton | Export File |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:2664 | save_workstation_btn | QPushButton | Save Workstation |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py:2677 | polygon_btn | QPushButton | Polygon |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:659 | view_btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:705 | new_btn | QPushButton | Write New Report |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:948 | zoom_in_btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:966 | zoom_out_btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:984 | reset_btn | QPushButton | Live inspection required |  | {} | image_view.reset_zoom |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:1005 | close_btn | QPushButton | Close |  | {} | viewer.close |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:1112 | browser_btn | QPushButton | Open in Browser |  | {} | Dynamic callback |
| modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py:1133 | close_btn | QPushButton | Close |  | {} | viewer.close |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:461 | self.cmb_backbone | QComboBox | Backbone: | eva02_base_patch14_448.mim_in22k_ft_in22k_in1k, eva02_large_patch14_448.mim_in22k_ft_in22k_in1k, eva02_small_patch14_336.mim_in22k_ft_in22k_in1k, vit_base_patch16_384, vit_large_patch16_384 | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:471 | self.spn_img_size | QSpinBox | Image Size: |  | {"minimum": 224, "maximum": 768} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:477 | self.chk_use_gender | QCheckBox | Gender: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:481 | self.spn_dropout | QDoubleSpinBox | Dropout Rate: |  | {"minimum": 0.0, "maximum": 0.8} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:487 | self.spn_drop_path | QDoubleSpinBox | Drop Path Rate: |  | {"minimum": 0.0, "maximum": 0.5} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:500 | self.spn_epochs | QSpinBox | Epochs: |  | {"minimum": 1, "maximum": 1000} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:505 | self.spn_batch | QSpinBox | Batch Size: |  | {"minimum": 1, "maximum": 256} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:510 | self.spn_lr | QDoubleSpinBox | Learning Rate: |  | {"minimum": 1e-06, "maximum": 1.0, "decimals": 6} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:517 | self.spn_weight_decay | QDoubleSpinBox | Weight Decay: |  | {"minimum": 0.0, "maximum": 1.0, "decimals": 5} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:524 | self.cmb_scheduler | QComboBox | LR Scheduler: | CosineAnnealing, StepLR, OneCycleLR, ReduceOnPlateau | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:528 | self.spn_warmup | QSpinBox | Warmup Epochs: |  | {"minimum": 0, "maximum": 50} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:540 | self.chk_clahe | QCheckBox | CLAHE: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:544 | self.chk_strong_clahe | QCheckBox | Strong CLAHE (higher clip limit) |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:548 | self.spn_crop_min | QDoubleSpinBox | Crop Area Min Ratio: |  | {"minimum": 0.1, "maximum": 1.0} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:554 | self.spn_crop_pad | QDoubleSpinBox | Crop Pad Fraction: |  | {"minimum": 0.0, "maximum": 0.5} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:560 | self.spn_tta | QSpinBox | TTA Steps: |  | {"minimum": 1, "maximum": 20} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:565 | self.chk_flip_tta | QCheckBox | TTA Augment: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:569 | self.spn_target_max | QDoubleSpinBox | Max Age (months): |  | {"minimum": 100.0, "maximum": 300.0} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:581 | self.txt_data_path | QLineEdit | Select training data folder... |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:586 | btn_browse | QPushButton | Browse |  | {} | self._on_browse |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:603 | self.cmb_model_source | QComboBox | Training Init: | AI Pacs Model, Scratch | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:608 | self.txt_pretrained_model_url | QLineEdit | Backbone URL: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:619 | self.txt_model_output_dir | QLineEdit | Select folder for saving trained model... |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:623 | self.btn_browse_output_dir | QPushButton | Browse |  | {} | self._on_browse_output_dir |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:780 | self.cmb_det_backbone | QComboBox | Backbone: | ResNet50-FPN, ResNet101-FPN, ResNeXt101-FPN, EfficientNet-B4-BiFPN | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:789 | self.spn_det_threshold | QDoubleSpinBox | Detection Threshold: |  | {"minimum": 0.1, "maximum": 0.99} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:795 | self.spn_det_img_size | QSpinBox | Image Size: |  | {"minimum": 512, "maximum": 2048} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:801 | self.spn_det_epochs | QSpinBox | Epochs: |  | {"minimum": 1, "maximum": 500} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:806 | self.spn_det_batch | QSpinBox | Batch Size: |  | {"minimum": 1, "maximum": 64} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:811 | self.spn_det_lr | QDoubleSpinBox | Learning Rate: |  | {"minimum": 1e-06, "maximum": 1.0, "decimals": 6} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:818 | self.spn_det_wd | QDoubleSpinBox | Weight Decay: |  | {"minimum": 0.0, "maximum": 1.0, "decimals": 5} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:825 | self.spn_det_momentum | QDoubleSpinBox | Momentum: |  | {"minimum": 0.0, "maximum": 0.99} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:838 | self.cmb_cls_model | QComboBox | Classifier: | XGBoost-Stacked, XGBoost-Single, LightGBM, RandomForest | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:847 | self.spn_n_estimators | QSpinBox | N Estimators: |  | {"minimum": 10, "maximum": 2000} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:853 | self.spn_max_depth | QSpinBox | Max Depth: |  | {"minimum": 2, "maximum": 20} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:858 | self.spn_xgb_lr | QDoubleSpinBox | Learning Rate: |  | {"minimum": 0.001, "maximum": 1.0, "decimals": 4} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:865 | self.spn_subsample | QDoubleSpinBox | Subsample: |  | {"minimum": 0.3, "maximum": 1.0} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:871 | self.spn_colsample | QDoubleSpinBox | Col Sample: |  | {"minimum": 0.3, "maximum": 1.0} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:884 | self.chk_run_detection | QCheckBox | Detection: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:888 | self.chk_run_classification | QCheckBox | Classification: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:892 | self.chk_dual_view | QCheckBox | Dual-View: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:896 | self.cmb_views | QComboBox | Views: | CC + MLO (Both), CC Only, MLO Only | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:907 | self.cmb_model_source | QComboBox | Training Init: | AI Pacs Model, Scratch | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:912 | self.txt_detector_pretrained_url | QLineEdit | Detector URL: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:916 | self.txt_classifier_pretrained_url | QLineEdit | Classifier URL: |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:927 | self.txt_model_output_dir | QLineEdit | Select folder for saving trained model... |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:931 | self.btn_browse_output_dir | QPushButton | Browse |  | {} | self._on_browse_output_dir |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:944 | self.txt_data_path | QLineEdit | Select mammography training data folder... |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:949 | btn_browse | QPushButton | Browse |  | {} | self._on_browse |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:1168 | self.btn_save | QPushButton | Live inspection required |  | {} | self._on_save |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:1184 | self.btn_reset | QPushButton | Live inspection required |  | {} | self._on_reset |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:1244 | self.btn_collect | QPushButton | Scan all confirmed/rejected labels from the Imaging Tools tab and show how many training samples are available. |  | {} | self._on_collect_labels |
| modules/ai_imaging/ai_module_ui/service_tab/training_data_settings_tab.py:1266 | self.btn_train | QPushButton | Live inspection required |  | {} | self._on_train |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:488 | self.btn_previous_exams | QToolButton | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:517 | self.btn_minimize | QToolButton | Minimize |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:523 | self.btn_maximize | QToolButton | Maximize |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:636 | self.font_size_spin | QSpinBox | Live inspection required |  | {"minimum": 8, "maximum": 72} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:747 | self.direction_combo | QComboBox | Live inspection required | LTR, RTL | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:760 | self.heading_combo | QComboBox | Live inspection required | Normal, Heading 1, Heading 2, Heading 3, Heading 4 | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:770 | btn | QPushButton | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:777 | btn | QToolButton | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:800 | btn | QToolButton | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:1008 | self.status_combo | QComboBox | Live inspection required |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:1029 | self.btn_reset | QPushButton | Reset |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:1035 | self.btn_save | QPushButton | Save Changes |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py:1059 | self.btn_close | QPushButton | Close |  | {} |  |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_image_picker_dialog.py:122 | self._btn_refresh | QPushButton | Refresh |  | {} | self._reload |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_image_picker_dialog.py:132 | self._btn_insert | QPushButton | Insert |  | {} | self._accept_selection |
| modules/ai_imaging/ai_module_ui/service_tab/widgets/report_image_picker_dialog.py:138 | self._btn_cancel | QPushButton | Cancel |  | {} | self.reject |
| modules/ai_imaging/background_analysis.py:30 | button | QPushButton | Hide window / return to PACS |  | {} | self.close |
| modules/ai_imaging/background_analysis.py:84 | button | QPushButton | Hide progress / return to PACS |  | {} | dialog.hide |
| modules/ai_imaging/dx_wrist_ai_analyze/controller.py:164 | cancel | QPushButton | Cancel |  | {} | dialog.reject |
| modules/ai_imaging/dx_wrist_ai_analyze/controller.py:165 | confirm | QPushButton | Confirm and Open EchoMind Report |  | {} | dialog.accept |
| modules/ai_imaging/dx_wrist_ai_analyze/controller.py:203 | close | QPushButton | Close |  | {} | dialog.accept |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:50 | self.bases | QComboBox | Live inspection required | Lumbar spine template, Blank template | {} | self._base_changed |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:64 | self.name | QLineEdit | Dataset name |  | {} |  |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:65 | self.modality | QComboBox | Modality |  | {} | self.changed |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:69 | self.anatomy | QLineEdit | Anatomical area |  | {} |  |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:70 | self.regions | QLineEdit | Regions / levels |  | {} |  |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:89 | self.add_button | QPushButton | Add Field |  | {} | self.add_field |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:137 | kind | QComboBox | Live inspection required |  | {} | self.changed |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:140 | scope | QComboBox | Live inspection required | Once per case, Each region | {} | self.changed |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:144 | required | QComboBox | Live inspection required | Optional, Required | {} | self.changed |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:153 | remove | QPushButton | Remove |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:209 | self.author | QLineEdit | Form author |  | {} | self.changed |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:237 | widget | QLineEdit | Number; leave empty if unknown | Not entered | {} | self.changed, self.changed, self.changed |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:260 | self.draft_button | QPushButton | Save Draft |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:261 | self.complete_button | QPushButton | Save Completed Form |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye/datasets/dialogs.py:262 | close | QPushButton | Close |  | {} | self.reject |
| modules/ai_imaging/eagle_eye/datasets/workspace.py:72 | self.new_button | QPushButton | New Dataset |  | {} | self.new_dataset |
| modules/ai_imaging/eagle_eye/datasets/workspace.py:73 | self.edit_button | QPushButton | Edit Template |  | {} | self.edit_template |
| modules/ai_imaging/eagle_eye/datasets/workspace.py:74 | self.add_button | QPushButton | Add Current Study |  | {} | self.add_current_study |
| modules/ai_imaging/eagle_eye/datasets/workspace.py:75 | self.refresh_button | QPushButton | Refresh Lists |  | {} | self.refresh |
| modules/ai_imaging/eagle_eye/datasets/workspace.py:96 | self.search | QLineEdit | Find a case by patient code, name or study date |  | {} | self.filter_cases |
| modules/ai_imaging/eagle_eye/datasets/workspace.py:109 | self.open_button | QPushButton | Open Selected Case |  | {} | self.open_case |
| modules/ai_imaging/eagle_eye_alignment/widget.py:135 | self.series | QComboBox | Live inspection required |  | {} | self._series_changed |
| modules/ai_imaging/eagle_eye_alignment/widget.py:138 | self.files | QComboBox | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_alignment/widget.py:138 | self.scan | QPushButton | Find study images |  | {} | self.scan_study |
| modules/ai_imaging/eagle_eye_alignment/widget.py:139 | self.browse | QPushButton | Open DICOM |  | {} | self.browse_image |
| modules/ai_imaging/eagle_eye_alignment/widget.py:139 | self.load | QPushButton | Load selected image |  | {} | self.load_selected |
| modules/ai_imaging/eagle_eye_alignment/widget.py:146 | self.confirm | QCheckBox | Standing AP, complete hips-to-ankles; patient right is on image left. |  | {} | self._invalidate_review |
| modules/ai_imaging/eagle_eye_alignment/widget.py:149 | fit | QPushButton | Fit image |  | {} | self.canvas.fit |
| modules/ai_imaging/eagle_eye_alignment/widget.py:149 | self.flip | QPushButton | Flip horizontally |  | {} | self.flip_image |
| modules/ai_imaging/eagle_eye_alignment/widget.py:153 | self.cancel | QPushButton | Cancel |  | {} | self._cancel.set |
| modules/ai_imaging/eagle_eye_alignment/widget.py:153 | self.run | QPushButton | Suggest landmarks with AI |  | {} | self.start_ai |
| modules/ai_imaging/eagle_eye_alignment/widget.py:156 | self.manual | QComboBox | Live inspection required | Pan / drag existing points | {} | self._manual_changed |
| modules/ai_imaging/eagle_eye_alignment/widget.py:165 | self.col_spacing | QDoubleSpinBox | Live inspection required |  | {} | self._calibration_changed |
| modules/ai_imaging/eagle_eye_alignment/widget.py:165 | self.row_spacing | QDoubleSpinBox | Live inspection required |  | {} | self._calibration_changed |
| modules/ai_imaging/eagle_eye_alignment/widget.py:169 | self.calibrated | QCheckBox | Verified patient-plane scale (DICOM or known-length marker). |  | {} | self._calibration_changed |
| modules/ai_imaging/eagle_eye_alignment/widget.py:178 | self.review | QCheckBox | I reviewed all landmarks, orientation and calibration. |  | {} | self._refresh_controls |
| modules/ai_imaging/eagle_eye_alignment/widget.py:179 | self.comparison | QLineEdit | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_alignment/widget.py:179 | self.impression | QLineEdit | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_alignment/widget.py:179 | self.indication | QLineEdit | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_alignment/widget.py:183 | self.export | QPushButton | Generate reviewed PDF report |  | {} | self.save_report |
| modules/ai_imaging/eagle_eye_alignment/widget.py:185 | self.open_pdf | QPushButton | Open PDF |  | {} | self._open_pdf |
| modules/ai_imaging/eagle_eye_alignment/widget.py:185 | self.save_pdf | QPushButton | Save PDF copy |  | {} | self._save_pdf |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:33 | self.primary_disease | QComboBox | Live inspection required | Select clinical context | {} | self._context_changed |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:40 | self.clinical_note | QLineEdit | Clinical details (optional; supplied by the clinician) |  | {"maxLength": 500} |  |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:44 | self.ms_comparison | QCheckBox | Compare previous and current MS examinations |  | {} | self._comparison_changed |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:50 | self.fazekas | QComboBox | Live inspection required | Fazekas (clinician): not provided | {} |  |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:59 | self.acquisition_mode | QComboBox | Live inspection required | 3D MRI / T1 + FLAIR, 2D MRI / FLAIR slice analysis (research) | {} | self._acquisition_changed |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:171 | verified | QCheckBox | I verified the same patient, full-brain T1 and FLAIR, and previous/current examinations. |  | {} | update |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:213 | picker_mode | QComboBox | Live inspection required | 3D FLAIR / single volume, 2D FLAIR / axial and optional second plane | {} | change_picker_mode |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:236 | combo | QComboBox | Live inspection required | Select a series | {} | update |
| modules/ai_imaging/eagle_eye_brain/lesion_widget.py:274 | verified | QCheckBox | I verified brain coverage, FLAIR roles and, if supplied, the T1 before/after contrast order. |  | {} | update |
| modules/ai_imaging/eagle_eye_brain/manual_slicer.py:49 | effect_button | QPushButton | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_brain/manual_slicer.py:53 | open_editor | QPushButton | Open Segment Editor |  | {} |  |
| modules/ai_imaging/eagle_eye_brain/manual_slicer.py:56 | button | QPushButton | Save correction for AI-PACS |  | {} |  |
| modules/ai_imaging/eagle_eye_brain/widget.py:41 | self.study_button | QPushButton | Select MRI series |  | {} | self.start_study_segmentation |
| modules/ai_imaging/eagle_eye_brain/widget.py:54 | self.age | QDoubleSpinBox | Live inspection required |  | {"decimals": 2} | self._update_reference |
| modules/ai_imaging/eagle_eye_brain/widget.py:59 | self.sex | QComboBox | Live inspection required |  | {} | self._update_reference |
| modules/ai_imaging/eagle_eye_brain/widget.py:70 | advanced_toggle | QCheckBox | Advanced options and reference details |  | {} | self.advanced.setVisible |
| modules/ai_imaging/eagle_eye_brain/widget.py:77 | self.reference | QComboBox | Live inspection required |  | {} | self._update_reference |
| modules/ai_imaging/eagle_eye_brain/widget.py:89 | self.profile | QComboBox | Live inspection required | Standard, Robust (for difficult contrast; review required) | {} |  |
| modules/ai_imaging/eagle_eye_brain/widget.py:95 | self.confirm | QCheckBox | I verified the selected images and examination. |  | {} |  |
| modules/ai_imaging/eagle_eye_brain/widget.py:102 | self.run | QPushButton | Run brain volumetry |  | {} | self._start |
| modules/ai_imaging/eagle_eye_brain/widget.py:107 | self.regenerate | QPushButton | Report from completed analysis |  | {} | self._regenerate |
| modules/ai_imaging/eagle_eye_brain/widget.py:110 | self.cancel | QPushButton | Cancel |  | {} | self._cancel.set |
| modules/ai_imaging/eagle_eye_brain/widget.py:114 | self.output | QPushButton | Open result folder |  | {} | self._open_output |
| modules/ai_imaging/eagle_eye_brain/widget.py:117 | self.pdf | QPushButton | Open PDF report |  | {} | self._open_pdf |
| modules/ai_imaging/eagle_eye_brain/widget.py:120 | self.save_pdf | QPushButton | Save PDF report... |  | {} | self._save_pdf |
| modules/ai_imaging/eagle_eye_brain/widget.py:145 | self.comparison_button | QPushButton | Open T1 comparison PDF |  | {} | self._open_comparison |
| modules/ai_imaging/eagle_eye_brain/widget.py:167 | self.manual_edit | QPushButton | Manual correction in 3D Slicer |  | {} | self._manual_open |
| modules/ai_imaging/eagle_eye_brain/widget.py:171 | self.manual_recalculate | QPushButton | Recalculate corrected report |  | {} | self._manual_recalculate |
| modules/ai_imaging/eagle_eye_brain/widget.py:186 | field | QLineEdit | Choose from this examination |  | {} |  |
| modules/ai_imaging/eagle_eye_brain/widget.py:197 | button | QPushButton | Live inspection required |  | {} | self.start_study_segmentation, Dynamic callback |
| modules/ai_imaging/eagle_eye_brain/widget.py:463 | segmentation | QPushButton | Whole Brain Segmentation / T1 MPRAGE |  | {} | dialog.accept |
| modules/ai_imaging/eagle_eye_brain/widget.py:466 | lesions | QPushButton | White-matter Lesions / T1 + 3D FLAIR |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_brain/widget.py:562 | flair_choices | QComboBox | Live inspection required | No FLAIR selected | {} | update |
| modules/ai_imaging/eagle_eye_brain/widget.py:570 | verified | QCheckBox | I confirm all selected T1 series are full-brain 3D T1-weighted images, not T1 maps or FLAIR. |  | {} | update |
| modules/ai_imaging/eagle_eye_brain/widget.py:571 | flair_verified | QCheckBox | I confirm the optional series is full-brain 3D FLAIR. |  | {} | update |
| modules/ai_imaging/eagle_eye_lumbar/result_panel.py:100 | self.btn_copy | QPushButton | Copy |  | {} | self._copy_to_clipboard |
| modules/ai_imaging/eagle_eye_lumbar/result_panel.py:105 | self.btn_folder | QPushButton | Open session folder |  | {} | self._open_folder |
| modules/ai_imaging/eagle_eye_lumbar/result_panel.py:110 | self.btn_stage_images | QPushButton | View stage images |  | {} | self._open_stage_images |
| modules/ai_imaging/eagle_eye_lumbar/result_panel.py:121 | self.btn_reanalyze | QPushButton | Re-analyze |  | {} | self.reanalyzeRequested.emit |
| modules/ai_imaging/eagle_eye_lumbar/result_panel.py:129 | self.btn_close | QPushButton | Close |  | {} | self.hide |
| modules/ai_imaging/eagle_eye_lumbar/stage_audit_panel.py:158 | close_button | QPushButton | Close |  | {} | self.hide |
| modules/ai_imaging/eagle_eye_total_spine/guided_review.py:109 | self.edit | QPushButton | Complete / edit required data |  | {} | self.edit_required |
| modules/ai_imaging/eagle_eye_total_spine/guided_review.py:110 | self.confirm | QPushButton | Confirm this result |  | {} | self.confirm_result |
| modules/ai_imaging/eagle_eye_total_spine/guided_review.py:111 | next_button | QPushButton | Next item to review |  | {} | self.next_item |
| modules/ai_imaging/eagle_eye_total_spine/sam_ui.py:24 | self.choose | QPushButton | Select body box for SAM |  | {} | self.select_box |
| modules/ai_imaging/eagle_eye_total_spine/sam_ui.py:25 | self.run | QPushButton | Segment selected body |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/sam_ui.py:26 | self.apply | QPushButton | Use proposed endplates for selected level |  | {} | self.accept_endplates |
| modules/ai_imaging/eagle_eye_total_spine/sam_ui.py:27 | self.clear | QPushButton | Clear SAM preview |  | {} | self.reset |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:101 | widget | QComboBox | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:122 | self.files | QComboBox | Live inspection required |  | {} | self.clear_image |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:122 | self.series | QComboBox | Live inspection required |  | {} | self._series_changed |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:123 | self.load | QPushButton | Load selected image |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:124 | clear | QPushButton | Clear projection |  | {} | self.clear_image |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:145 | toggle | QToolButton | Live inspection required |  | {} | change |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:156 | self.confirm | QCheckBox | Standing acquisition verified |  | {} | self.invalidate |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:162 | fit | QPushButton | Fit image |  | {} | self.canvas.fit |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:168 | self.ai | QPushButton | Suggest vertebrae inside selected region |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:177 | region_button | QPushButton | Select spine region (two opposite corners) |  | {} | self._select_region |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:187 | self.candidate | QComboBox | Live inspection required |  | {} | self._show_candidate |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:189 | assign | QPushButton | Assign to selected level |  | {} | self._assign_candidate |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:191 | anchor | QPushButton | Number from this level |  | {} | self._candidate_numbering |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:194 | discard | QPushButton | Discard selected candidate |  | {} | self._discard_candidate |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:214 | undo | QPushButton | Undo last correction / measurement |  | {} | self._undo_edit |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:220 | button | QPushButton | Live inspection required |  | {} | Dynamic callback, Dynamic callback, Dynamic callback, Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:224 | remove_pedicles | QPushButton | Clear pedicles / grade |  | {} | self._clear_pedicles |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:231 | remove | QPushButton | Remove selected level |  | {} | self._remove_level |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:232 | remove_marker | QPushButton | Remove selected balance marker |  | {} | self._remove_marker |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:237 | self.col_spacing | QDoubleSpinBox | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:237 | self.row_spacing | QDoubleSpinBox | Live inspection required |  | {} |  |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:242 | self.calibrated | QCheckBox | Verified patient-plane mm/pixel |  | {} | self._scale_changed |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:272 | suggest | QPushButton | Suggest maximum-angle pair from assigned levels |  | {} | self._suggest_pair |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:274 | add | QPushButton | Add curve from selected endplates |  | {} | self._add_curve |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:281 | confirm_curve | QPushButton | Confirm selected curve endplates and numbering |  | {} | self._confirm_curve |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:283 | update_curve | QPushButton | Update selected curve with chosen levels |  | {} | self._update_curve |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:285 | remove_curve | QPushButton | Remove selected curve |  | {} | self._remove_curve |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:293 | rotation | QPushButton | Save grade |  | {} | self._rotation |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:298 | self.review | QCheckBox | Measurements reviewed |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:322 | rename | QPushButton | Correct assigned numbering |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:325 | fit_quick | QPushButton | Fit image |  | {} | self.canvas.fit |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:726 | sequence | QCheckBox | Shift all assigned levels from this anchor (preserve known gaps) |  | {} | update |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:764 | checked | QCheckBox | I reviewed the body order, excluded duplicate detections, and corrected missing levels or anatomical exceptions. |  | {} | validate |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:916 | self.scan | QPushButton | Find study images |  | {} | self.scan_study |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:918 | self.cancel | QPushButton | Cancel task |  | {} | self._cancel.set |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:920 | self.region_button | QPushButton | Select spine region |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:921 | self.analyze_button | QPushButton | Detect vertebrae (AI) |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:922 | self.measure_button | QPushButton | Measure angles |  | {} | self.show_measurements |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:938 | self.notes | QLineEdit | Clinician impression (optional) |  | {"maxLength": 2000} | self.invalidate_report |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:941 | self.draft | QPushButton | Generate draft PDF |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:941 | self.reviewed | QPushButton | Generate reviewed PDF |  | {} | Dynamic callback |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:949 | self.open | QPushButton | Open PDF |  | {} | self.open_pdf |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:949 | self.save | QPushButton | Save PDF copy |  | {} | self.save_pdf |
| modules/ai_imaging/eagle_eye_total_spine/widget.py:953 | self.open_images | QPushButton | Open annotated images |  | {} | self.open_annotated_images |
| modules/ai_imaging/legion_consult/dialogs.py:91 | self.t1_combo | QComboBox | Required T1: |  | {} | self._refresh |
| modules/ai_imaging/legion_consult/dialogs.py:92 | self.t2_combo | QComboBox | Required T2: |  | {} | self._refresh |
| modules/ai_imaging/legion_consult/dialogs.py:110 | self.select_all | QCheckBox | Include all eligible diagnostic series |  | {} | self._refresh |
| modules/ai_imaging/legion_consult/result_panel.py:86 | self.btn_copy | QPushButton | Copy current tab |  | {} | self._copy_current |
| modules/ai_imaging/legion_consult/result_panel.py:87 | self.btn_folder | QPushButton | Open session folder |  | {} | self._open_folder |
| modules/ai_imaging/legion_consult/result_panel.py:88 | self.btn_reanalyze | QPushButton | Re-analyze |  | {} | self.reanalyzeRequested.emit |
| modules/ai_imaging/legion_consult/result_panel.py:89 | self.btn_close | QPushButton | Close |  | {} | self.hide |
| modules/ai_imaging/mammography_ai_analyze/controller.py:148 | cancel | QPushButton | Cancel |  | {} | dialog.reject |
| modules/ai_imaging/mammography_ai_analyze/controller.py:149 | confirm | QPushButton | Confirm and Open EchoMind Report |  | {} | dialog.accept |
| modules/ai_imaging/mammography_ai_analyze/controller.py:187 | close | QPushButton | Close |  | {} | dialog.accept |
| modules/data_analysis/admission_reports.py:96 | self.range_combo | QComboBox | Live inspection required |  | {} | Dynamic callback |
| modules/data_analysis/admission_reports.py:104 | self.refresh_btn | QPushButton | Live inspection required |  | {} | self.refresh |
| modules/data_analysis/admission_reports.py:137 | self.retry_btn | QPushButton | Live inspection required |  | {} | self.refresh |
| modules/data_analysis/widget.py:616 | self.refresh_btn | QPushButton | Refresh |  | {} | Dynamic callback |
| modules/data_analysis/widget.py:618 | self.auto_refresh_checkbox | QCheckBox | Auto refresh |  | {} | self._toggle_auto_refresh |
| modules/data_analysis/widget.py:628 | self.date_filter | QComboBox | Live inspection required |  | {} | self._on_data_filter_changed |
| modules/data_analysis/widget.py:630 | self.server_filter | QComboBox | Live inspection required |  | {} | self._on_data_filter_changed |
| modules/data_analysis/widget.py:632 | self.user_filter | QComboBox | Live inspection required |  | {} | self._on_data_filter_changed |
| modules/data_analysis/widget.py:634 | self.modality_filter | QComboBox | Live inspection required |  | {} | self._apply_filters |
| modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsOfflineLumbar.py:236 | self.confirm | QCheckBox | I confirm this is an MR volume; output is anatomy assistance, not diagnosis |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsOfflineLumbar.py:238 | self.apply | QPushButton | Segment vertebrae offline (CPU) |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsOfflineLumbar.py:239 | self.cancelButton | QPushButton | Cancel analysis |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:86 | self.place | QPushButton | Place start and destination |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:102 | self.compute | QPushButton | Compute route |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:107 | self.cancelButton | QPushButton | Cancel |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:115 | self.position | QSlider | Position |  | {"minimum": 0, "maximum": 0} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:123 | self.reference | QPushButton | Set reference |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:131 | self.playButton | QPushButton | Play / Pause |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:134 | self.speed | QDoubleSpinBox | Speed |  | {"minimum": 0.5, "maximum": 50} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:139 | self.reverse | QCheckBox | Reverse travel |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:141 | self.angle | QDoubleSpinBox | Field of view (degrees) |  | {"minimum": 30, "maximum": 120} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:146 | self.wallBrightness | QSpinBox | Wall brightness |  | {"minimum": 20, "maximum": 80} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:153 | self.overview | QPushButton | Restore overview |  | {} |  |
| modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py:155 | save | QPushButton | Save scene |  | {} |  |
| modules/mpr/curved_mpr/curved_mpr_panoramic_view.py:747 | self._xsection_slider | QSlider | Live inspection required |  | {"minimum": 0, "maximum": 0} | self._on_xsection_slider_changed |
| modules/mpr/curved_mpr/curved_mpr_view.py:153 | self.window_slider | QSlider | Live inspection required |  | {"minimum": 1, "maximum": 4000} | self._on_window_changed |
| modules/mpr/curved_mpr/curved_mpr_view.py:165 | self.level_slider | QSlider | Live inspection required |  | {"maximum": 3000} | self._on_level_changed |
| modules/mpr/curved_mpr/curved_mpr_view.py:180 | reset_btn | QPushButton | Reset View |  | {} | self._reset_view |
| modules/mpr/curved_mpr/curved_mpr_view.py:185 | save_btn | QPushButton | Save Image |  | {} | self._save_image |
| modules/mpr/curved_mpr/curved_mpr_view.py:190 | close_btn | QPushButton | Close |  | {} | self.close |
| modules/mpr/orthogonal/example_usage.py:128 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/mpr/orthogonal/example_usage.py:133 | crosshair_btn | QPushButton | Toggle Crosshairs |  | {} | toggle_crosshairs |
| modules/mpr/orthogonal/example_usage.py:142 | slab_btn | QPushButton | Enable MIP Slab (10mm) |  | {} | toggle_slab |
| modules/mpr/orthogonal/widgets/slice_slider.py:85 | self._slider | QSlider | Live inspection required |  | {"minimum": 0, "maximum": 100} | self._on_slider_changed |
| modules/mpr/orthogonal/widgets/slice_slider.py:229 | self._prev_btn | QPushButton | Live inspection required |  | {} | self.decrement |
| modules/mpr/orthogonal/widgets/slice_slider.py:246 | self._play_btn | QPushButton | Live inspection required |  | {} | self._toggle_play |
| modules/mpr/orthogonal/widgets/slice_slider.py:263 | self._next_btn | QPushButton | Live inspection required |  | {} | self.increment |
| modules/mpr/orthogonal/widgets/toolbar.py:110 | self._preset_combo | QComboBox | Live inspection required |  | {} | self._on_preset_changed |
| modules/mpr/orthogonal/widgets/toolbar.py:143 | self._crosshair_btn | QToolButton | Live inspection required |  | {} | self._on_crosshair_toggled |
| modules/mpr/orthogonal/widgets/toolbar.py:161 | self._slab_btn | QToolButton | Live inspection required |  | {} | self._on_slab_toggled |
| modules/mpr/orthogonal/widgets/toolbar.py:169 | self._slab_mode_combo | QComboBox | Live inspection required | MIP, MinIP, Mean | {} | self._on_slab_mode_changed |
| modules/mpr/orthogonal/widgets/toolbar.py:188 | self._slab_thickness | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.5, "maximum": 50.0} | self._on_slab_thickness_changed |
| modules/mpr/orthogonal/widgets/toolbar.py:222 | self._pointer_btn | QToolButton | Pointer |  | {} |  |
| modules/mpr/orthogonal/widgets/toolbar.py:232 | self._distance_btn | QToolButton | Measure Distance |  | {} |  |
| modules/mpr/orthogonal/widgets/toolbar.py:241 | self._angle_btn | QToolButton | Measure Angle |  | {} |  |
| modules/mpr/orthogonal/widgets/toolbar.py:257 | self._reset_btn | QToolButton | Live inspection required |  | {} | self._on_reset_clicked |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_ui.py:153 | self.btn_clear | QPushButton | Clear Points |  | {} | self.clear_points |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_ui.py:170 | self.source_plane | QComboBox | Changing the drawing plane clears the current path. | Axial, Sagittal, Coronal | {} |  |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_ui.py:175 | self.volume_mode | QComboBox | Live inspection required | Path VRT, Straightened VRT, Curved MIP | {} |  |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_ui.py:178 | self.volume_preset | QComboBox | Rendering appearance; does not segment or isolate vessels. |  | {} |  |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_ui.py:189 | self.volume_width | QDoubleSpinBox | Live inspection required |  | {"minimum": 5, "maximum": 100} |  |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_ui.py:197 | self.orbit_angle | QDoubleSpinBox | Scroll either CPR image to rotate both sampling planes around the path. |  | {"minimum": 0, "maximum": 359.9} |  |
| modules/mpr/zeta_mpr/CurveMPR/curve_mpr_ui.py:239 | spin | QDoubleSpinBox | Live inspection required |  | {} | Dynamic callback |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_layout.py:144 | btn | QPushButton | Hide crosshair in this viewport |  | {} | Dynamic callback |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_series.py:119 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:440 | self.wl_combo | QComboBox | Live inspection required |  | {} | self._on_wl_changed |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:470 | self.vol_combo | QComboBox | Live inspection required |  | {} | self._on_volume_preset_changed |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:483 | self.crosshair_btn | QPushButton | Crosshairs |  | {} | self._toggle_crosshairs, self._show_crosshair_settings_menu |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:503 | self.reset_btn | QPushButton | Reset |  | {} | self._reset_rendering |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py:516 | self.close_btn | QPushButton | Close |  | {} | self._close_mpr |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_vrt.py:188 | quality | QComboBox | Detailed adds local shadows at rest. Large volumes retain balanced lighting. | Detailed, Balanced | {} | self._set_vrt_quality |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_vrt.py:195 | threshold | QSpinBox | Shift tissue visibility relative to the selected preset. No tissue segmentation. |  | {} | self._set_vrt_threshold |
| modules/mpr/zeta_mpr/mpr_viewer/_mpr_vrt.py:287 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/mpr/zeta_mpr/standard_mpr_viewer_original.py:1387 | self.wl_combo | QComboBox | Live inspection required |  | {} | self._on_wl_changed |
| modules/mpr/zeta_mpr/standard_mpr_viewer_original.py:1426 | self.vol_combo | QComboBox | Live inspection required |  | {} | self._on_volume_preset_changed |
| modules/mpr/zeta_mpr/standard_mpr_viewer_original.py:1440 | self.crosshair_btn | QPushButton | Crosshairs |  | {} | self._toggle_crosshairs, self._show_crosshair_settings_menu |
| modules/mpr/zeta_mpr/standard_mpr_viewer_original.py:1464 | self.reset_btn | QPushButton | Reset |  | {} | self._reset_rendering |
| modules/mpr/zeta_mpr/standard_mpr_viewer_original.py:1481 | self.close_btn | QPushButton | Close |  | {} | self._close_mpr |
| modules/mpr/zeta_mpr/standard_mpr_viewer_original.py:1608 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/mpr/zeta_mpr/standard_mpr_viewer_original.py:4786 | btn | QPushButton | Live inspection required |  | {} | Dynamic callback |
| modules/viewer/advanced/filter_config_widget.py:145 | self.slider | QSlider | Live inspection required |  | {} | self._on_slider_changed |
| modules/viewer/advanced/filter_config_widget.py:416 | save | QPushButton | Live inspection required |  | {} | self.save_config |
| modules/viewer/advanced/filter_config_widget.py:420 | reload_btn | QPushButton | Live inspection required |  | {} | self.load_config |
| modules/viewer/advanced/filter_config_widget.py:424 | reset | QPushButton | Live inspection required |  | {} | self.reset_to_default |
| modules/viewer/advanced/filter_config_widget.py:438 | enabled_cb | QCheckBox | Live inspection required |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:485 | enabled | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:508 | enabled | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:531 | enabled | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:536 | sigmas_edit | QLineEdit | 0.5,1.0,2.0 |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:542 | amounts_edit | QLineEdit | 0.25,0.12,0.06 |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:548 | mild_sigmas_edit | QLineEdit | 0.5,1.0,2.0,4.0 |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:554 | mild_amounts_edit | QLineEdit | 0.20,0.10,0.05,0.025 |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:566 | enabled | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:589 | en | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:630 | enabled | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:653 | enabled | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/filter_config_widget.py:676 | enabled | QCheckBox | Enabled |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:178 | self.modality_combo | QComboBox | Live inspection required | CT, MR, PET, US, X-Ray, Other | {} | self.on_modality_changed |
| modules/viewer/advanced/image_filter_sidebar.py:225 | apply_btn | QPushButton | Live inspection required |  | {} | self.apply_filters |
| modules/viewer/advanced/image_filter_sidebar.py:249 | reset_btn | QPushButton | Live inspection required |  | {} | self.reset_to_defaults |
| modules/viewer/advanced/image_filter_sidebar.py:277 | self.enable_all_cb | QCheckBox | Enable All Filters |  | {} | self.toggle_all_filters |
| modules/viewer/advanced/image_filter_sidebar.py:321 | self.noise_enable | QCheckBox | Enable |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:326 | self.noise_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.05, "maximum": 3.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:332 | self.noise_mild_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.05, "maximum": 3.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:356 | self.gaussian_smooth_enable | QCheckBox | Gaussian Smoothing |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:360 | self.gaussian_smooth_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:366 | self.gaussian_smooth_mild_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:378 | self.high_pass_enable | QCheckBox | High Pass Filter |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:382 | self.high_pass_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:388 | self.high_pass_mild_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:400 | self.low_pass_enable | QCheckBox | Low Pass Filter |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:404 | self.low_pass_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:410 | self.low_pass_mild_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:433 | self.multiscale_enable | QCheckBox | Multiscale Sharpening |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:438 | self.multiscale_sigmas | QLineEdit | 0.5,1.0,2.0 |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:444 | self.multiscale_amounts | QLineEdit | 0.25,0.12,0.06 |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:450 | self.multiscale_mild_sigmas | QLineEdit | 0.5,1.0,2.0,4.0 |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:456 | self.multiscale_mild_amounts | QLineEdit | 0.20,0.10,0.05,0.025 |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:462 | self.laplacian_enable | QCheckBox | Laplacian Sharpening |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:466 | self.laplacian_alpha | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 1} |  |
| modules/viewer/advanced/image_filter_sidebar.py:472 | self.laplacian_mild_alpha | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 1} |  |
| modules/viewer/advanced/image_filter_sidebar.py:484 | self.adaptive_enable | QCheckBox | Adaptive Sharpening |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:488 | self.adaptive_base | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 2} |  |
| modules/viewer/advanced/image_filter_sidebar.py:494 | self.adaptive_boost | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 2} |  |
| modules/viewer/advanced/image_filter_sidebar.py:500 | self.adaptive_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 2} |  |
| modules/viewer/advanced/image_filter_sidebar.py:506 | self.adaptive_mild_base | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 2} |  |
| modules/viewer/advanced/image_filter_sidebar.py:512 | self.adaptive_mild_boost | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 2} |  |
| modules/viewer/advanced/image_filter_sidebar.py:518 | self.adaptive_mild_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0, "maximum": 2} |  |
| modules/viewer/advanced/image_filter_sidebar.py:551 | self.band_pass_enable | QCheckBox | Band Pass Filter |  | {} |  |
| modules/viewer/advanced/image_filter_sidebar.py:555 | self.band_pass_low_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:561 | self.band_pass_high_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:567 | self.band_pass_mild_low_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/image_filter_sidebar.py:573 | self.band_pass_mild_high_sigma | QDoubleSpinBox | Live inspection required |  | {"minimum": 0.1, "maximum": 5.0} |  |
| modules/viewer/advanced/viewer_3d.py:75 | self.reset_btn | QPushButton | Reset View |  | {} | self.reset_view |
| modules/viewer/advanced/viewer_3d.py:171 | self.x_rotation_slider | QSlider | Live inspection required |  | {} | self.on_x_rotation_changed |
| modules/viewer/advanced/viewer_3d.py:213 | self.y_rotation_slider | QSlider | Live inspection required |  | {} | self.on_y_rotation_changed |
| modules/viewer/advanced/viewer_3d.py:259 | self.zoom_slider | QSlider | Live inspection required |  | {"minimum": 10, "maximum": 200} | self.on_zoom_changed |
| modules/viewer/advanced/viewer_3d.py:351 | self.category_combo | QComboBox | Live inspection required | All, CT Bone, CT Soft Tissue, CT Lung, CT Vessel, CT Cardiac, CT Contrast, MRI Brain, MRI Angiography, Technique | {} | self._on_category_changed |
| modules/viewer/advanced/viewer_3d.py:419 | self.preset_combo | QComboBox | Live inspection required |  | {} | self._on_preset_changed |

Parse gaps: []
