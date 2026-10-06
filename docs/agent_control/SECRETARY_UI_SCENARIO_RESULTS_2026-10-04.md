# Secretary UI scenario execution report (2026-10-04)

All requests and persisted data in these experiments are synthetic. No real center setting, patient, recording, download or deletion was changed.
Company brain requests used the authenticated Eagle Eye route; model proposals were not executed in the clinical application.
Native source Test Control ping was unavailable. Offscreen form/controller tests and isolated repository execution are independent of native/clinical acceptance.

## Coverage and receipts

- 859 source-traced per-control scenario drafts, including custom wrappers. They require reviewed typed binding/native execution and are not execution passes.
- 50 authored natural requests: 35 settings operations, 6 Home searches and 9 Fast toolbar modes. Actual async settings persistence/readback, actual offscreen search form/query routing and real Fast ToolController state were checked.
- Focused code receipt: 210 tests, 0 failures/errors. The deterministic new suite has 56 guards: 50 operation cases plus inventory/privacy/unsupported-field/backend boundaries.
- Authenticated one-proposal brain receipt: {'mismatch': 2, 'pass': 48} across 50 requests. A read-before-write proposal is a prerequisite, not completed verification or cloning.
- Two additional live continuation cases feed actual isolated read results back to the authenticated brain, then execute only correctly scoped typed proposals through the same bus/service. See their separate receipt below.
- Real DICOM connectivity is not verified here: port 105 success / port 104 failure are injected synthetic echo outcomes.
- No rendered clinical annotation, actual PACS population/search result, native external Slicer UI, physical media or clinical cleanup is certified.

## Authored requests and evaluated outcomes

| Scenario | User request | Isolated execution | Active brain proposal | Native application |
| --- | --- | --- | --- | --- |
| server_echo_two_ports | Verify the configured Test Center using DICOM ports 105 and 104. Do not change its configuration. | PASS: checked state/readback | PREREQUISITE ONLY: configuration read | NOT RUN |
| server_clone | Copy Test Center as Test Center 2, preserving its socket and reception endpoints. | PASS: checked state/readback | PREREQUISITE ONLY: configuration read | NOT RUN |
| persistent_modalities | In Settings Modality Grid, remove NM and XA. Keep MR and CT available for future searches. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| reference_line_color | In Tool Settings, change the reference line color to #00FF80. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| reference_line_width | In Tool Settings, set reference line line width to 4. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ruler_color | In Tool Settings, change the ruler color to #00FF80. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ruler_width | In Tool Settings, set ruler line width to 4. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| arrow_color | In Tool Settings, change the arrow color to #00FF80. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| arrow_width | In Tool Settings, set arrow line width to 4. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| angle_color | In Tool Settings, change the angle color to #00FF80. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| angle_width | In Tool Settings, set angle line width to 4. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| polygon_color | In Tool Settings, change the polygon color to #00FF80. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| polygon_width | In Tool Settings, set polygon line width to 4. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| rectangle_color | In Tool Settings, change the rectangle color to #00FF80. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| rectangle_width | In Tool Settings, set rectangle line width to 4. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ct_min_slices | In Image Filter Settings, set CT min slices to 5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ct_enabled | In Image Filter Settings, set CT enabled to False. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ct_gaussian_smoothing_sigma | In Image Filter Settings, set CT gaussian smoothing sigma to 1.5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ct_gaussian_high_pass_sigma | In Image Filter Settings, set CT gaussian high pass sigma to 1.5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ct_laplacian_sharpening_alpha | In Image Filter Settings, set CT laplacian sharpening alpha to 0.5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| mr_min_slices | In Image Filter Settings, set MR min slices to 5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| mr_enabled | In Image Filter Settings, set MR enabled to False. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| mr_gaussian_smoothing_sigma | In Image Filter Settings, set MR gaussian smoothing sigma to 1.5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| mr_gaussian_high_pass_sigma | In Image Filter Settings, set MR gaussian high pass sigma to 1.5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| mr_laplacian_sharpening_alpha | In Image Filter Settings, set MR laplacian sharpening alpha to 0.5. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| voice_v2t | In AI Settings, select v2t as the voice transcription provider. Preserve my existing credentials. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| voice_openai | In AI Settings, select OpenAI Whisper as the voice transcription provider. Preserve my existing credentials. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| voice_auto | In AI Settings, select auto as the voice transcription provider. Preserve my existing credentials. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| proxy_direct | In AI Settings, choose direct with the configured proxy port 2082. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| proxy_socks5 | In AI Settings, choose socks5 with the configured proxy port 2082. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| read_server | Show the safe current server configuration. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| read_modality_grid | Show the safe current modality grid configuration. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| read_tools | Show the safe current tools configuration. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| read_image_filter | Show the safe current image filter configuration. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| read_ai | Show my AI settings without displaying passwords or tokens. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| patient_id | Search the server for patient ID SYN-001. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| patient_name | Search local studies for patient name Synthetic Example. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| exact_date_mr | Search only MRI studies on the server dated 2026-10-02. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| ct_date_range | Find server CT studies from 2026-10-01 through 2026-10-03. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| advanced_age_body | Search the server for knee MRI studies with patient age 12 through 18. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| advanced_multiple_ids | Search the server for MRI studies belonging to patient IDs SYN-001 and SYN-002. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_ruler | In the active Fast Viewer, activate the ruler tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_angle | In the active Fast Viewer, activate the angle tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_two_line_angle | In the active Fast Viewer, activate the two line angle tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_roi_rect | In the active Fast Viewer, activate the roi rect tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_roi_circle | In the active Fast Viewer, activate the roi circle tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_arrow | In the active Fast Viewer, activate the arrow tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_text | In the active Fast Viewer, activate the text tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_eraser | In the active Fast Viewer, activate the eraser tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |
| toolbar_select | In the active Fast Viewer, activate the select tool on viewport 0. | PASS: checked state/readback | PASS: expected action and requested fields | NOT RUN |

## Result-driven continuation

- server_echo_two_ports: pass; cycle=1; error=None; completed actions=['get_settings_snapshot', 'verify_settings_server'].
- server_clone: pass; cycle=1; error=None; completed actions=['get_settings_snapshot', 'clone_settings_server'].

## Additional workflow scenarios

| Request | Evidence | Scope |
| --- | --- | --- |
| How many loaded MRI studies dated 2026-10-04 have a voice recording, and how many are verified without one? | PASS in focused guards: `tests/code/echomind/test_patient_workflow_facts.py::test_summary_counts_unknown_separately_and_never_claims_personal_authorship` | Synthetic/offscreen; native not run |
| How do I tell whether a patient report is completed? Explain the actual status icon. | PASS in focused guards: `tests/code/echomind/test_patient_workflow_facts.py::test_guide_explains_actual_report_and_voice_indicators` | Synthetic/offscreen; native not run |
| Open the first study in my current list that is verified without a voice recording. | PASS in focused guards: `tests/code/echomind/test_patient_workflow_facts.py::test_act_opens_original_first_verified_absent_row_from_bound_receipt` | Synthetic/offscreen; native not run |
| Teach me how to open a patient study and highlight the relevant list. | PASS in focused guards: `tests/code/echomind/test_secretary_guidance.py::test_tutorial_highlight_requires_visible_target` | Synthetic/offscreen; native not run |
| Remove all local Patient Data Folder content, after showing the scope and obtaining local confirmation. | PASS in focused guards: `tests/code/echomind/test_secretary_settings_examples.py::test_patient_folder_cleanup_waits_for_local_confirmation_and_terminal_receipt` | Synthetic/offscreen; native not run |
| Start a new conversation memory, then verify message cycles count 1 through 10 and roll over without mixing prior context. | PASS in focused guards: `tests/code/echomind/test_secretary_memory_cycles.py::test_cycles_rollover_new_and_independent_numbers` | Synthetic/offscreen; native not run |

## Findings and interpretation

- Fixed inventory omission of five real Home composite search controls by explicitly recognizing LoginLineField/ComboField/DateField/NumberField and CustomCheckbox. The regression guard failed before the fix. Wrapper observation now retains outer field identity while redacting entered values.
- Source declares Gender, Study Description and Series Description fields, but the current typed advanced-search contract does not support them. Negative tests verify rejection before UI/search changes. Their source declaration does not establish that they are visible in the compact current form.
- Fast toolbar activation is verified for 9 modes through the actual ToolController. An Advanced backend without the Fast controller correctly returns NOT_IMPLEMENTED; this is a support boundary, not a successful activation.
- First brain batch used a 45-second test timeout; a slow provider call timed out and subsequent requests returned 429 Busy. Resume used the normal 90-second request timeout; queue pauses on Busy and never changes provider or releases another request lock.
- Initial ID-search probe exposed only two Home actions and the brain asked for missing selection capabilities. Repeating with the real factory contracts produced the correct ID search. A constrained test harness must not be presented as the full application contract.
- Body-part comparison follows the existing search engine case-folding: knee and KNEE match. This is not an erroneous body-part filter.
- The active server does not yet advertise UI-observation version 1. Actual redacted screen delivery requires the matching staged server update; old-server rejection remains explicit.
- The first two live continuation attempts failed with SERVER_UPSTREAM_FAILED. A subsequent same-server retry passed both cases; no provider fallback or live server mutation was used. This demonstrates transient planning unavailability, not an established upstream root cause.
- Read-result continuation is exercised by the test harness, not proof that the current native Secretary automatically feeds each receipt into the next planning cycle. That native orchestration gate remains open.

## Reproduction

`python tools/testing/build_secretary_ui_scenarios.py` regenerates drafts.
`pytest -p no:debugging tests/code/echomind/test_secretary_ui_scenarios.py -q --reruns 0` runs isolated operation scenarios.
`python tools/testing/run_secretary_ui_planning.py --resume` resumes synthetic authenticated planning only; no proposals execute in the app.
Set AIPACS_LIVE_SCENARIO_PLANNING=1 only for `test_live_secretary_ui_scenarios.py`; it uses temporary settings/database and stub echo, while the brain is real.
`python tools/testing/build_secretary_ui_scenario_report.py` regenerates this report from actual receipts.

Final receipt: 210 focused code/workflow guards passed (separate pytest process exits 0) and 2 opt-in authenticated live-brain continuation tests passed after same-server retry. Scenario coverage and syntax checks passed. Global plugin mirror verification still reports the pre-existing unrelated `modules/EchoMind/viewer_chat/ai_chat_pages.py` drift; this task did not alter that workstream. A final native ping remained unavailable; no source app was launched/restarted or signed in by automation.
