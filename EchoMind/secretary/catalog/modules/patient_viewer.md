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

## 2. Available Action

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
