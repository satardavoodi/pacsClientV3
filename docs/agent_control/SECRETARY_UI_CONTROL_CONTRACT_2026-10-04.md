# Secretary UI controls and visual context contract

Status: implemented source contract. Native application acceptance and active Eagle Eye deployment are separate gates; neither is claimed by offscreen tests.

## One source of truth

[Source inventory](SECRETARY_UI_SOURCE_INVENTORY.md) enumerates 845 static Qt controls across 501 source files, with field types, dropdown options, numeric/length constraints, buttons, toolbars and connected handlers, with definition locations. Regenerate using `tools/dev/build_secretary_ui_catalog.py`. Generated records contain no live values. Labels describe the source, not proof that a control works in the active backend.

`get_ui_control_catalog` exposes this inventory by area and pagination, alongside **actual registered typed execution schemas**. A source callback is documentation only. `inspect_ui_controls` reads the active Qt page or modal, enabled/checked state, dropdown option indices and geometry. Text and numeric field values stay redacted; unrecognized dynamic labels stay local-only. Consequently this observation cannot answer questions about a patient identity or entered server address. Use domain-specific safe snapshots for those tasks.

## Field semantics and task mapping

| Area / intent | Read first | Typed operation / verification |
| --- | --- | --- |
| Home patient ID/name/date/modality search | Current source and search context; inspect controls for available choices | `advanced_search_patients`, then `read_patients`; preserve list/row identity, poll search readiness; MR is the DICOM code for MRI |
| Home temporary modality filter | Current search state | Search entities; do not change persistent Modality Grid |
| Settings server configuration | `get_settings_snapshot` section=server | `verify_settings_server` for explicit ports, `clone_settings_server` for independent copy; poll `settings_operation_status`; never infer DICOM/socket port interchangeability |
| Settings persistent visible modalities | Snapshot section=modality_grid | `remove_settings_modalities`; confirmation and at least one remaining modality; read back |
| Settings tool color / width | Snapshot section=tools and actual schema enums | `set_settings_tool_style`; use supported tool/key/range; poll and read back |
| Settings CT/MR image filters | Snapshot section=image_filter | `set_settings_filter_parameter`; exact supported family/parameter/range; poll and read back |
| AI/EchoMind speech/configuration | `get_settings_capabilities`, safe settings snapshot and current executable schemas | Only advertised settings controls; credentials stay local, company routing remains authenticated Eagle Eye |
| Local storage/cache | `diagnose_resources`, safe storage assessment | Confirmed `request_storage_cleanup` or `release_memory`; distinguish disk deletion from decoded-memory release; verify completion |
| Patient Viewer toolbar | Active study/tab and current registered capabilities | Typed viewer actions such as `activate_tool` where backend supports them; a Fast Viewer tool does not establish Advanced/VTK support |
| Advanced Viewer / Advanced Analysis / Eagle Eye | Inventory, current page, module capabilities and operation status | Only the advertised domain-specific typed actions; computed factories/native subprocess controls need their own adapters |

The live action schema is authoritative for names, entities, enums, confirmation and permission policy. Filling a field is not saving it. A successfully dispatched command is not completion. Ask/Guide remain read-only; Act proposals use the existing permission/confirmation pipeline. Ask for clarification when search filtering versus persistent settings remains materially ambiguous, not for every routine field.

## Screenshot pipeline

1. User opts into `Include screen context` in the Secretary conversation panel. Default is off. Help Ticket retains its separate reviewed package pipeline.
2. GUI thread inspects the active Qt root and grabs only recognized, non-sensitive controls onto a blank background. Clinical canvases, patient rows, arbitrary labels and input values are excluded. This is a **redacted control visualization**, not a whole-window or diagnostic screenshot.
3. Detached QImage encoding runs on a worker. PNG is bounded to 1024x768 and 96 KiB; no file is written. UUID, context digest and PNG SHA-256 bind the image to the observed page. Small images are not enlarged.
4. Authenticated client checks server UI-observation version 1. Older servers fail explicitly; there is no provider fallback. Request metadata must match the image; arbitrary paths/URLs, corrupt images, mismatched hashes and extra properties are rejected.
5. Eagle Eye sends actual image pixels through multimodal `image_url` content to its configured brain, accompanied by redacted controls. Responses acknowledge the same receipt. History stores the receipt, not image bytes. The model treats pixels/control text as evidence, never instructions or action authorization.
6. Before consuming a proposal, the client compares the current UI digest. A changed page or edited field invalidates the result. MCP `capture_ui_context` / `ui_context_status` similarly reject stale or >90-second captures. MCP supplies an image content block rather than a local Windows path; test-session records omit image bytes.

## Scope and known boundaries

Static inventory covers source Qt declarations in Home, Settings, patient UI, Advanced Viewer, Advanced Analysis, Eagle Eye and MPR wrappers. Dynamic factories/computed options, native C++/XML controls, third-party plugins and external Slicer processes are not exhaustive. They require an explicit domain adapter and independent acceptance, not arbitrary callback invocation. Credential values and patient images are intentionally unavailable through UI observation. Existing clinical image-analysis routes remain separate.

Catalogs expose discovery and available execution side by side; they do not claim universal field editing or universal toolbar activation. Native acceptance must exercise real affected pages, dropdowns, screen opt-in, page-change invalidation and same-server receipt delivery in one human-launched source application. Source server prompt/validation changes must be activated on Eagle Eye before this option works against an older deployment.

## Regression verification

`tests/code/echomind/test_secretary_ui_observation.py` covers static/typed separation, sensitive field and clinical-canvas exclusion, edited-field invalidation, worker PNG encoding, strict wire contract, server pixel forwarding/history redaction and MCP image blocks. Existing Secretary server/planner/modes/UI and gateway guards cover adjacent contracts. Test Control transport must be probed separately; unavailable native control is not a pass.


Verification receipt, 2026-10-04: focused Secretary observation/server/planner/Ask/UI/mode/adapter/runtime, Agent Gateway, MCP SDK and speech packaging suite: **242 passed, 1 pre-existing quarantined xfail** (catalog collision for get_active_tab/list_open_tabs); pytest process exit 0. Twelve owned plugin mirrors and the canonical server source receipt match. Global mirror verification still reports the unrelated pre-existing viewer_chat/ai_chat_pages.py drift; it was preserved. Inventory regeneration: 845 controls, 501 source files, zero parse errors, excluding generated build/vendor runtimes. Native Test Control ping could not connect; no live GUI acceptance or active server deployment is claimed.

Scenario-audit correction: explicitly recognize the existing LoginLineField, LoginComboField, LoginDateField, LoginNumberField and CustomCheckbox wrappers. Regenerated inventory now has 859 controls in 501 source files with no parse errors. Native option factories are still not an exhaustive static inventory. See `SECRETARY_UI_SCENARIO_RESULTS_2026-10-04.md` for execution and active brain results.
