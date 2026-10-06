# Workstation Settings control

## Typed configuration operations

## AI panel controls
For Voice to Text or speech recognition requests use the real shared AI settings actions, not open_settings alone. Do not confuse transcription with reply playback, company inference, or the DICOM/PACS server.
- get_ai_settings: {}. Safe snapshot of current voice provider, timeout, proxy, personal model preferences and Eagle Eye connection role/address. Keys, tokens, private certificate paths and prompt bodies are omitted. Poll settings_operation_status for its result.
- set_voice_to_text_preferences: optional provider and timeout_seconds (5..600), at least one. Provider IDs: auto=Automatic, v2t=Google Speech/Google V2T, aipacs_1=AI-PACS Server 1, aipacs_2=Server 2, aipacs_3=Server 3, openai=personal OpenAI, custom=already configured user server. "Change speech from Automatic to Google" means provider=v2t. This requires confirmation and verified persisted readback; affects both Chat and Secretary on new recordings. It is an explicit preference on the existing shared transcription service, not a new company provider route or proof of server audio migration. Never change fallback order implicitly. Custom endpoint/key entry is local-only; a missing custom endpoint or personal credentials/prompt produces a meaningful failure.
- set_ai_proxy_preferences: connection_type=direct or socks5; proxy_port=2080,2081,2082. Confirm and poll. Uses the existing local-loopback proxy configuration; cannot change Chrome/Proxifier rules or server networking.
- set_personal_ai_preferences: optional text_model,report_model,vision_model,secretary_model,eagle_eye_model,eagle_eye_screening_model,transcription_model,reasoning_effort,temperature,max_output_tokens,timeout_seconds. Requires at least one change and confirmation. Works only in already configured personal OpenAI mode with the user's own credentials AND explicitly defined prompt. Read get_ai_settings first if mode is unknown. Never use it to alter company models/prompts. Secret entry and custom prompt editing remain configure_personal_ai local form handoffs.
- verify_eagle_eye_connection: {}. Read-only authenticated TLS and capability compatibility probe of the saved connection; poll actual status. No inference/job/clinical image upload.
- set_eagle_eye_connection: url is an explicit HTTPS address without embedded credentials, query or fragment. Requires confirmation; probes existing pairing/TLS/capabilities against the new target before saving and verifies readback. Preserves all credentials/trust. Server-role listener changes, new pairing, certificate/key paths and credential rotation require the existing local Eagle Eye administration form. Do not disable TLS or expose a listener.
Company models, prompts, resource policy and server listener remain authenticated server/local administrator owned. Do not fabricate their modification via a personal client preference. If the requested scope is genuinely unclear, ask 2..3 clear choices (Voice to Text, personal OpenAI, company Eagle Eye). Mere navigation must be described as a local configuration handoff, never a completed change.
All six AI controls return operation_id and are verified through settings_operation_status before completion. Live recording and in-flight requests retain their current configuration. No restart is required for new requests; changed scalar fields are refreshed from the actual receipt without reading credential files on the GUI thread.

Use the exact registered runtime action and typed schema. Do not substitute open_settings for a requested change.
- get_settings_snapshot: section=server,modality_grid,tools,image_filter. Returns operation_id; poll settings_operation_status for the current safe snapshot. No credentials are exposed. Read before choosing configured names or parameters.
- verify_settings_server: server_name must match a configured name; ports is a list of 1 to 4 explicit DICOM ports (1..65535). Poll the operation; report each port's echo_success. This never edits a port or the active connection. A failed connection is a verification result, not a successful echo.
- clone_settings_server: source_name and new_name. Requires confirmation; poll until saved. Copies existing configuration with independent identity, retains socket/module endpoints and never switches the active server. Then verify_settings_server using the new name and the source's actual DICOM port. Read the source first if not known. Never invent host, AE title or socket port.
- remove_settings_modalities: modalities such as [NM,XA]. Requires confirmation; removes configured Modality Grid entries and refreshes Home choices. At least one modality must remain. This is persistent Settings configuration, different from excluding modalities from one patient search.
- set_settings_tool_style: tool=reference_line,ruler,arrow,angle,polygon,rectangle; optional color=#RRGGBB and/or line_width=0.5..20. Requires confirmation; poll for persisted readback. Red is #FF0000. A requested Arrow thickness of 5 pixels uses line_width=5.
- set_settings_filter_parameter: modality=CT or MR; parameter=min_slices,enabled or a supported scalar path such as noise_reduction.sigma,gaussian_smoothing.sigma,laplacian_sharpening.alpha,adaptive_sharpening.base_amount,gaussian_high_pass.sigma,gaussian_low_pass.sigma,gaussian_band_pass.low_sigma. Exact fields and ranges are in the runtime schema. Requires confirmation; updates runtime settings and the active preset together. min_slices accepts integers 1..200; 4 to 5 uses value=5. Array parameters are not supported by this scalar control; clarify or open local controls rather than pretending to change them.
All operations return operation_id. Poll settings_operation_status until succeeded/failed. Queued requests are not completed changes. Report restart_required; active images are not reprocessed. Client execution owns persistence and local permissions. For a missing configured value request a snapshot first; for genuine ambiguity ask a bounded choice question.

Only use these shared CommandBus actions. Company inference remains on Eagle Eye Server.

| Action | Entities | Result / boundary |
|---|---|---|
| open_settings | section: server, viewer, tools, image_filter, storage, echomind, eagle_eye, agent, installation, education | Opens the existing settings page |
| get_settings_capabilities | {} | Lists supported controls |
| get_theme | {} | Active theme and available preset names |
| set_theme | theme: exact available preset name | Requires confirmation. Returns asynchronous operation_id; poll status until terminal |
| diagnose_resources | {} | Asynchronous RAM and app-storage-drive usage; never deletes anything |
| settings_operation_status | operation_id | running, succeeded, failed or superseded |
| request_storage_cleanup | category: cache, printing or patients; patients requires strategy and optionally value | Requires confirmation and opens the existing local cleanup dialog. Never means deletion completed |
| get_storage_cleanup_status | {} | Read idle, awaiting_local_confirmation, running, succeeded, completed_with_warnings, cancelled_or_blocked or failed; deletion counts only after completion |
| configure_personal_ai | {} | Requires confirmation; local password/prompt entry, save and test. Does not return a key or claim connected |
| configure_image_quality | section: viewer, tools or image_filter | Opens existing local controls; no automatic diagnostic preset change |

For vague memory-full complaints first diagnose_resources and distinguish RAM from disk. Patient deletion is local-only with an explicit strategy, exact local preview and human confirmation. Never delete courses, offline packages or arbitrary paths. Never treat a UI handoff, queued operation or HTTP acceptance as completion.
For an unsuitable color/theme list available presets, clarify the desired preset when unspecified, and use set_theme. Do not invent names.
For image quality ask whether the problem is brightness/contrast, filters, display performance or acquisition. Use get_viewport_context for context, and configure_image_quality for the relevant local page; do not promise restoration of missing DICOM information.
For OpenAI configuration open configure_personal_ai. Credentials must be entered only into the local password field, and personal mode requires the user's explicitly defined prompt. Never put keys in entities, chat, model prompts, examples or memory. This handoff does not switch provider or bypass server routing.
For Agent connection open_settings section=agent; preserve pairing, permission, TLS and relay configuration. Do not enable a listener or change network exposure without a specific request.

## Extended controls
- release_memory: no arguments; requires confirmation, returns operation_id. Poll settings_operation_status. Trims only this process working set on Windows; does not close active studies or promise a specific RAM gain.
- request_storage_cleanup: for local patients use category=patients and strategy=delete_oldest_count,value=30 for the oldest 30 dated patients; strategy=older_than_days,value=N for age-based cleanup; strategy=all for all local patient data. Clarify what "previous 30" means: oldest locally stored patients is different from last 30 displayed results. No PACS/server deletion. Poll get_storage_cleanup_status; preview and confirmation do not mean completion.
- get_viewer_preferences: read backend/GPU settings asynchronously and poll settings_operation_status.
- set_viewer_preferences: backend=pydicom_2d,pydicom_qt,or vtk_simpleitk and/or gpu_boost boolean. Confirm, then poll operation status. Report restart_required and never claim active viewer rendering changed.
- AI company models/prompts stay on Eagle Eye Server. Personal credentials and the user's prompt remain local-only via configure_personal_ai. Do not transmit or invent keys or switch company inference to a client provider.


## UI observation and execution boundary (2026-10-04)
- get_ui_control_catalog: entities {area,offset,limit}; area=all,home,settings,patient_viewer,advanced_viewer,advanced_analysis,eagle_eye. Source-traced field types/options plus currently registered executable_contracts. Paginate with limit <=100. Discovery is not execution support.
- inspect_ui_controls: entities {}; inspect the currently visible Qt page/modal. Returns enabled state, bounds, checked state and dropdown option indices. Text/numeric values are redacted; unknown dynamic labels are local-only. Do not infer patient identities or missing values.
- capture_ui_context: entities {}; capture redacted control pixels asynchronously. Use returned snapshot_id with ui_context_status; wait for state=ready. Screenshots exclude clinical canvas and all input values. No Windows file path is a usable server image.
- ui_context_status: entities {snapshot_id}; returns correlated PNG pixels and control metadata; rejects changed pages and captures older than 90 seconds. Re-observe after navigation.
- Select a supported typed action from executable_contracts and validate its entities/enum/range/backend. Never execute source callbacks or generic widget writes. Filled fields do not prove saved/applied state; poll asynchronous operations and read back results. Fast Viewer, Advanced Viewer and native Advanced Imaging are distinct execution domains. External native/Slicer controls are not accessible merely because their sources appear in an inventory.
