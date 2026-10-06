# Eagle Eye control

module_id: eagle_ai

EGLI and spoken Eagle Eye variants mean this module. Use only these existing
shared bus actions, not legacy show_findings/explain_finding placeholders.

| Action | Required entities | Result |
|---|---|---|
| eagle_eye_open | study_uid | Opens/reuses the exact study workspace |
| eagle_eye_series | study_uid | Available series inventory |
| eagle_eye_select_series | study_uid, series_uid | Selects one unique matching series |
| eagle_eye_functions | study_uid | Functions available for the current ready series/modality |
| eagle_eye_run | study_uid, series_uid, function; optional inputs | Starts the existing controlled workflow; poll status |
| eagle_eye_status | study_uid | Actual controlled job status, including failure |
| eagle_eye_inputs | study_uid, series_uid, inputs | Supplies verified inputs for the matching controlled series |

Opening, selecting and running require confirmation. Obtain authoritative current
study/series identity with viewer read actions; never invent UIDs or choose a
patient by name alone. If the request lacks identity, obtain current context or
clarify before planning the write. Use only functions advertised by
eagle_eye_functions. Do not invent tasks,
models, worker code, paths or provider URLs. A running job is not completed
analysis; never report findings without actual returned results. Respect device
permissions and user-defined ROI/input validation. Company inference uses the
authenticated Eagle Eye Server; no direct provider fallback.

toggle_eagle is only a legacy workspace-opening alias, not proof of turning
inference or overlays off/on.


## UI observation and execution boundary (2026-10-04)
- get_ui_control_catalog: entities {area,offset,limit}; area=all,home,settings,patient_viewer,advanced_viewer,advanced_analysis,eagle_eye. Source-traced field types/options plus currently registered executable_contracts. Paginate with limit <=100. Discovery is not execution support.
- inspect_ui_controls: entities {}; inspect the currently visible Qt page/modal. Returns enabled state, bounds, checked state and dropdown option indices. Text/numeric values are redacted; unknown dynamic labels are local-only. Do not infer patient identities or missing values.
- capture_ui_context: entities {}; capture redacted control pixels asynchronously. Use returned snapshot_id with ui_context_status; wait for state=ready. Screenshots exclude clinical canvas and all input values. No Windows file path is a usable server image.
- ui_context_status: entities {snapshot_id}; returns correlated PNG pixels and control metadata; rejects changed pages and captures older than 90 seconds. Re-observe after navigation.
- Select a supported typed action from executable_contracts and validate its entities/enum/range/backend. Never execute source callbacks or generic widget writes. Filled fields do not prove saved/applied state; poll asynchronous operations and read back results. Fast Viewer, Advanced Viewer and native Advanced Imaging are distinct execution domains. External native/Slicer controls are not accessible merely because their sources appear in an inventory.
