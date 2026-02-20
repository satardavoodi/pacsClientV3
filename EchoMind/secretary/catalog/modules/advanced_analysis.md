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
