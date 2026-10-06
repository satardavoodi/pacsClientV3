"""Source-grounded page explanations; discovery never grants execution or visibility."""
from copy import deepcopy

PAGE_DEFINITIONS = {'server': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/server_settings.py',
            'purpose': 'Configure PACS server connections and verify DICOM connectivity. DICOM and '
                       'socket transport ports have different purposes.'},
 'viewer': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py',
            'purpose': 'Configure modality layouts and viewer preferences. Modality Grid controls '
                       'offered modalities; Home checkboxes filter the current search.'},
 'tools': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/tools_settings_ui.py',
           'purpose': 'Configure annotation appearance, including tool colors and line widths; '
                      'this does not draw an annotation.'},
 'image_filter': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/filter_config.py',
                  'purpose': 'Configure CT and MR filter parameters. Explain scalar ranges from '
                             'source constraints; do not recommend diagnostic image alterations.'},
 'storage': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py',
             'purpose': 'Review app-owned patient and printing cache cleanup scope. Cleanup '
                        'requires local confirmation; it is not deletion of remote PACS studies.'},
 'echomind': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py',
              'purpose': 'Configure speech, Secretary and personal AI preferences. Company '
                         'inference is owned by authenticated Eagle Eye Server; personal '
                         'credentials and prompts stay local.'},
 'eagle_eye': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/eagle_eye_settings.py',
               'purpose': 'Configure and verify authenticated Eagle Eye connectivity; connection '
                          'setup does not imply a completed analysis.'},
 'agent': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/agent_settings.py',
           'purpose': 'Configure Agent Gateway access and pairing policy. The production gateway '
                      'is separate from local Test Control.'},
 'installation': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/installation_module_settings.py',
                  'purpose': 'Review installed module availability and updates. A catalog entry '
                             'does not establish that its module is installed or licensed.'},
 'education': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/consultation_education_settings.py',
               'purpose': 'Review consultation and education feature availability; unavailable '
                          'sections must be described honestly.'},
 'light_viewer': {'source': 'PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py',
                  'purpose': 'Configure the portable Light Viewer supplied with media workflows; '
                             'this page depends on the Run CD module.'},
 'home': {'source': 'PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py',
          'purpose': 'Search loaded/server/local patient studies with modality and date filters. '
                     'Explain fields without changing the current query.'}}

CONTROL_MEANINGS = {'server': {'self.name_edit': 'Display name used to identify the configured PACS server.',
            'self.host_edit': 'PACS server network address.',
            'self.port_edit': 'DICOM association port; do not substitute the patient/download '
                              'socket port.',
            'self.ae_title_edit': 'DICOM called AE title; source limits entry to 16 characters.',
            'self._socket_port_edit': 'Patient and download socket transport port, separate from '
                                      'DICOM verification.',
            'self.verify_btn': 'Start configured server connectivity verification; a click alone '
                               'is not a successful receipt.',
            'self.save_btn': 'Save the configured server entry; filling fields alone does not save '
                             'it.'},
 'tools': {'self.line_width_spin': 'Annotation line width in pixels; source range is 0.5 through '
                                   '20.',
           'self.opacity_slider': 'Annotation opacity expressed on a 0 through 100 slider.',
           'self.font_size_spin': 'Text size for the selected annotation style.'},
 'viewer': {'self.new_name': 'Choose the modality to add to the configured Modality Grid.',
            'self.viewer_backend_combo': 'Select the configured viewer backend; Fast and Advanced '
                                         'execution remain separate.',
            'self.gpu_boost_toggle': 'Prefer GPU support when available; this is not proof that '
                                     'GPU execution is active.'},
 'echomind': {'self.proxy_type_combo': 'Select the AI connection proxy type.',
              'self.proxy_port_combo': 'Choose the local proxy port.',
              'self.backend_combo': 'Select the configured AI backend; company inference remains '
                                    'Eagle Eye Server owned.'},
 'eagle_eye': {'self.url': 'Authenticated Eagle Eye Server base address.',
               'self.save_button': 'Save the client connection configuration.',
               'self.test_button': 'Test the existing authenticated connection; report the actual '
                                   'test result.',
               'self.socket_port': 'Patient/download socket port, separate from the DICOM port.',
               'self.dicom_port': 'DICOM association port.'},
 'agent': {'self._chk_enabled': 'Enable the production Agent Gateway; this does not enable local '
                                'Test Control.',
           'self._btn_pair': 'Generate the local device pairing QR workflow.',
           'self._chk_tls': 'Use certificate-pinned TLS for paired device access.'}}

def page_guides():
    from PacsClient.utils.secretary_ui_source_catalog import SOURCE_CATALOG
    result = deepcopy(PAGE_DEFINITIONS)
    for key, page in result.items():
        page['visibility'] = 'source_reference_not_live_visibility'
        page['controls'] = [{field: row[field] for field in
            ('name', 'kind', 'label', 'options', 'constraints', 'sensitive', 'line')}
            for row in SOURCE_CATALOG['controls'] if row['source'] == page['source']]
        for control in page['controls']:
            control['meaning'] = CONTROL_MEANINGS.get(key, {}).get(control['name'], '')
            control['meaning_status'] = 'reviewed_source_meaning' if control['meaning'] else 'source_metadata_only_semantic_review_required'
            if control['sensitive']:
                control.update(label='Local-only credential control', options=[])
        if key in ('echomind', 'eagle_eye'):
            page['company_route'] = 'authenticated_eagle_eye_server'
    return result
