# Module Document: Advanced Image Analysis
**module_id:** `advanced_analysis`
**Document version:** 1.0
**Sent in Phase 2 when the LLM needs to trigger AI analysis or measurement workflows.**

---

## 1. What This Module Does

The Advanced Analysis module provides AI-assisted and algorithmic analysis tools
applied to the currently active DICOM series inside the viewer.  It covers:

* AI lesion / nodule detection
* Organ segmentation (lung, liver, kidney, bone, …)
* Quantitative measurements (volume, density, HU histogram)
* Series comparison (side-by-side, difference map)
* Export of structured analysis report (PDF or DICOM SR)

Analysis results are rendered as overlays on the viewer and optionally listed
in a results panel.

---

## 2. Available Actions

### `run_analysis`

Runs a named AI or algorithmic analysis task on the active series.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `task` | string | yes | See task list below |
| `target_region` | string | no | Anatomical region hint, e.g. `"lung"`, `"liver"` |
| `series_index` | int | no | Which series (0-based); default = active series |

**needs_confirmation:** `false`

#### Supported tasks

| task value | description |
|---|---|
| `lesion_detection` | AI detection of suspicious lesions |
| `lung_segmentation` | Segment lung lobes and airways |
| `liver_segmentation` | Segment liver parenchyma |
| `bone_density` | Compute HU-based bone density |
| `nodule_detection` | Pulmonary nodule screening |
| `comparison` | Side-by-side comparison of two series |

### `export_report`

Exports the current analysis results as a structured report.

| Entity | Type | Notes |
|---|---|---|
| `format` | string | `"pdf"` \| `"dicom_sr"` \| `"json"` |

**needs_confirmation:** `false`

---

## 3. Output Contract

```json
{
  "action": "run_analysis",
  "entities": {
    "task": "lung_segmentation",
    "target_region": "lung"
  },
  "confidence": 0.9,
  "needs_confirmation": false,
  "reason": "User asked to segment the lung in the active series"
}
```

---

## 4. Example Interactions

**Input:** `"run lung segmentation"`
```json
{"action":"run_analysis","entities":{"task":"lung_segmentation","target_region":"lung"},"confidence":0.93,"needs_confirmation":false,"reason":"Explicit lung segmentation request"}
```

**Input:** `"detect lesions"`
```json
{"action":"run_analysis","entities":{"task":"lesion_detection"},"confidence":0.9,"needs_confirmation":false,"reason":"User asked for lesion detection"}
```

**Input:** `"export the analysis report as PDF"`
```json
{"action":"export_report","entities":{"format":"pdf"},"confidence":0.9,"needs_confirmation":false,"reason":"User requested PDF export of analysis results"}
```


## UI observation and execution boundary (2026-10-04)
- get_ui_control_catalog: entities {area,offset,limit}; area=all,home,settings,patient_viewer,advanced_viewer,advanced_analysis,eagle_eye. Source-traced field types/options plus currently registered executable_contracts. Paginate with limit <=100. Discovery is not execution support.
- inspect_ui_controls: entities {}; inspect the currently visible Qt page/modal. Returns enabled state, bounds, checked state and dropdown option indices. Text/numeric values are redacted; unknown dynamic labels are local-only. Do not infer patient identities or missing values.
- capture_ui_context: entities {}; capture redacted control pixels asynchronously. Use returned snapshot_id with ui_context_status; wait for state=ready. Screenshots exclude clinical canvas and all input values. No Windows file path is a usable server image.
- ui_context_status: entities {snapshot_id}; returns correlated PNG pixels and control metadata; rejects changed pages and captures older than 90 seconds. Re-observe after navigation.
- Select a supported typed action from executable_contracts and validate its entities/enum/range/backend. Never execute source callbacks or generic widget writes. Filled fields do not prove saved/applied state; poll asynchronous operations and read back results. Fast Viewer, Advanced Viewer and native Advanced Imaging are distinct execution domains. External native/Slicer controls are not accessible merely because their sources appear in an inventory.
