# Module Document: Patient Viewer / Study Tab
**module_id:** `patient_viewer`
**Document version:** 1.0
**Sent in Phase 2 when the LLM needs to open or navigate a patient study.**

---

## 1. What This Module Does

The Patient Viewer module opens a DICOM study inside a dedicated viewer tab.
Each opened study gets its own tab with:

* Multi-series layout (1×1, 1×2, 2×2, custom)
* Window/Level presets (soft tissue, bone, lung, brain, …)
* Pan, zoom, scroll, and annotate tools
* Series navigation within the study

Opening a study is a **side-effect action** — it triggers the double-click handler
that loads DICOM files and renders the VTK pipeline. This always requires
explicit user confirmation before execution.

---

## 2. Available Actions

### `open_patient`

Resolves a patient identifier and opens their study in a new viewer tab.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `patient_code` | string | conditional | Required unless `use_context_patient=true` |
| `use_context_patient` | boolean | no | `true` → open the currently selected/last-listed patient |
| `source` | string | no | `"server"` \| `"local"` \| `"active_tab"` |
| `resolved_patient` | dict | no | Pre-resolved patient row (internal use) |

**side_effects:** `true`
**needs_confirmation:** `true` — ALWAYS, no exceptions

---

### `get_active_tab`

Read the active patient viewer tab. Use this to answer "which patient/study is open?"
or to verify that a patient is open before viewer actions.

No entities.

**side_effects:** `false`
**needs_confirmation:** `false`

---

### `list_open_tabs`

Read the workstation tab strip: Home, Download Manager, patient tabs, and the current
active tab index.

No entities.

**side_effects:** `false`
**needs_confirmation:** `false`

---

### `get_series_info`

Return drop-valid series rows for the active patient tab. Use this before loading a
series when the user refers by ordinal ("third series") or when you need the real
display key. `series_number` is the opaque sidebar/drop key and is valid even in
multi-study tabs.

No entities.

**side_effects:** `false`
**needs_confirmation:** `false`

---

### `query_viewport_state`

Read each viewport's loaded/awaiting/progressive series state, slice count, and spinner
state. Use it to verify `change_series` or `scroll_slices`.

No entities.

**side_effects:** `false`
**needs_confirmation:** `false`

---

### `get_viewport_context`

Read the active viewport's structured state for external GPT/GapGPT reasoning:
study UID, viewport index, current slice, slice count, image size, widget size,
view transform, viewer metadata, current DICOM slice metadata, patient-space
corner geometry when available, and capability flags.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `viewport` | integer | no | 0-based viewport index. Default `0`. |
| `include_slice_meta` | boolean | no | Default `true`. |
| `include_local_paths` | boolean | no | Default `false`; keep false for LLM context unless local debugging. |

**side_effects:** `false`
**needs_confirmation:** `false`

---

### `capture_viewport`

Save a PNG capture of the active viewport or full patient tab under
`user_data/echomind/agent_artifacts`. Use this before asking the external GPT
brain to interpret visible anatomy or overlay text.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `viewport` | integer | no | 0-based viewport index. Default `0`. |
| `scope` | string | no | `"viewport"` or `"tab"`. Default `"viewport"`. |
| `filename_prefix` | string | no | Short audit-friendly prefix. |

**side_effects:** `true` (local artifact write)
**needs_confirmation:** `false`

---

### `activate_tool`

Activate a FAST viewer tool. Prefer direct measurement actions such as
`measure_distance` for automated workflows; use this when the user explicitly
asks to select a tool.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `tool` | string | yes | `distance`, `ruler`, `angle`, `two_line_angle`, `roi_rect`, `roi_circle`, `arrow`, `text`, `eraser`, or `select`. |
| `viewport` | integer | no | 0-based viewport index. Default `0`. |

**side_effects:** `true` (local viewer state only)
**needs_confirmation:** `false`

---

### `measure_distance`

Place a distance ruler on the current displayed slice using image-pixel
coordinates. This avoids unstable screen-coordinate dragging and validates the
slice and image bounds before creating the measurement.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `viewport` | integer | no | 0-based viewport index. Default `0`. |
| `slice_index` | integer | recommended | Must match the current displayed slice when supplied. |
| `points_image` | array | yes | Exactly two `[x, y]` image-pixel points. |
| `label` | string | no | Optional label stored on the measurement model. |

**side_effects:** `true` (local viewer annotation only)
**needs_confirmation:** `false` unless anatomy/target points are ambiguous

---

### `get_measurements`

Read measurement/annotation models from the active viewport tool store.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `viewport` | integer | no | 0-based viewport index. Default `0`. |
| `slice_index` | integer | no | Defaults to current displayed slice. |
| `all_slices` | boolean | no | Default `false`. |

**side_effects:** `false`
**needs_confirmation:** `false`

---

### `change_series`

Load a series into a viewport through the same production function that real drag/drop
uses. This is the structured equivalent of dragging a series thumbnail into a viewport.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `series_number` | integer | conditional | Preferred when known. This is the active tab's opaque sidebar/drop key. |
| `series_index` | integer | conditional | 0-based ordinal from `get_series_info` rows: first=0, third=2. |
| `series_uid` | string | conditional | Series UID, resolved against active tab metadata. |
| `viewport` | integer | no | 0-based viewport index. Default `0`. |

Provide exactly one of `series_number`, `series_index`, or `series_uid`.

**side_effects:** `true` (local viewer state only)
**needs_confirmation:** `false`

---

### `scroll_slices`

Move through the active viewport's slice stack using the same `set_slice` path used by
the wheel/slider.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `viewport` | integer | no | 0-based viewport index. Default `0`. |
| `direction` | string | no | `"next"`, `"previous"`, `"first"`, `"last"`. Default `"next"`. |
| `delta` | integer | no | Signed relative step. |
| `index` | integer | no | Absolute 0-based slice index. |

**side_effects:** `true` (local viewer state only)
**needs_confirmation:** `false`

---

### `switch_tab`

Switch the main workstation tab by 0-based index. Use `list_open_tabs` first when the
target index is not known.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `index` | integer | yes | 0-based main tab index. |

**side_effects:** `true` (UI navigation)
**needs_confirmation:** `false`

---

### `change_layout`

Currently registered but not implemented. It returns a typed `NOT_IMPLEMENTED` result.
Do not choose this action for layout changes yet.

---

## 3. Output Contract

```json
{
  "action": "open_patient",
  "entities": {
    "patient_code": "P-10042",
    "source": "active_tab"
  },
  "confidence": 0.92,
  "needs_confirmation": true,
  "reason": "User asked to open patient P-10042"
}
```

Rules:
* `needs_confirmation` **must always be** `true` for `open_patient`
* If the user said "open the current patient" or similar with no explicit code,
  set `use_context_patient: true` and omit `patient_code`
* For "load/drop/import the third series into viewport 1", use `change_series`
  with `series_index: 2` and `viewport: 0` unless a real `series_number` is known.
* For "next image/slice" or "scroll stack", use `scroll_slices`.
* For measurement requests, first use `get_viewport_context` and `capture_viewport`
  so the external GPT/GapGPT brain can choose image-space points. Only call
  `measure_distance` when the points, current slice, and target anatomy are clear.
  If ambiguous, set lower confidence and let the orchestrator ask the user.
* Raw JSON only, no prose

---

## 4. Clarification Policy

If the user's request is ambiguous about **which** patient to open
(e.g. "open patient" with no ID and no context list), set `confidence < 0.5`
and include `reason: "patient not specified"`. The orchestrator will ask the user.

---

## 5. Example Interactions

**Input:** `"باز کردن بیمار P-10042"`
```json
{"action":"open_patient","entities":{"patient_code":"P-10042"},"confidence":0.95,"needs_confirmation":true,"reason":"User asked to open patient P-10042"}
```

**Input:** `"open the last patient in the list"`
```json
{"action":"open_patient","entities":{"use_context_patient":true},"confidence":0.88,"needs_confirmation":true,"reason":"User asked to open the last listed patient"}
```

**Input:** `"load the third series into the first viewport"`
```json
{"action":"change_series","entities":{"series_index":2,"viewport":0},"confidence":0.88,"needs_confirmation":false,"reason":"User asked to load the third visible series into viewport 0"}
```

**Input:** `"next slice"`
```json
{"action":"scroll_slices","entities":{"direction":"next","viewport":0},"confidence":0.86,"needs_confirmation":false,"reason":"User asked to move one slice forward in the active viewport"}
```

**Input:** `"measure this distance on the current slice"` with confirmed image points from external GPT
```json
{"action":"measure_distance","entities":{"viewport":0,"slice_index":55,"points_image":[[120.0,210.0],[220.0,211.5]],"label":"requested distance"},"confidence":0.82,"needs_confirmation":false,"reason":"Target points were supplied by the external vision decision for the current slice"}
```
