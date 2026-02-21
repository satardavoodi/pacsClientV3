# Module Document: Eagle AI
**module_id:** `eagle_ai`
**Document version:** 1.0
**Sent in Phase 2 when the LLM needs to control the proactive AI analysis overlay.**

---

## 1. What This Module Does

Eagle AI is a real-time radiological AI assistant that monitors the active
DICOM viewer and proactively highlights findings without waiting for a user
command.  Key features:

* Automatic detection overlays on the active series
* Severity-ranked finding list (critical → low)
* Hover-over explanations for highlighted regions
* Toggle visibility on/off without deactivating the engine
* Configuration of sensitivity/specificity trade-off

---

## 2. Available Actions

### `toggle_eagle`

Activates or deactivates the Eagle AI engine on the current viewer.

| Entity | Type | Notes |
|---|---|---|
| `state` | string | `"on"` \| `"off"` \| `"toggle"` (default) |

**needs_confirmation:** `false`

### `show_findings`

Brings the Eagle AI findings panel to the foreground.

| Entity | Type | Notes |
|---|---|---|
| *(none)* | — | No parameters needed |

**needs_confirmation:** `false`

### `explain_finding`

Asks Eagle AI to explain the currently highlighted finding.

| Entity | Type | Notes |
|---|---|---|
| `finding_index` | int | 0-based index from the findings list |

**needs_confirmation:** `false`

---

## 3. Output Contract

```json
{
  "action": "toggle_eagle",
  "entities": {
    "state": "on"
  },
  "confidence": 0.9,
  "needs_confirmation": false,
  "reason": "User asked to activate Eagle AI"
}
```

---

## 4. Example Interactions

**Input:** `"activate eagle ai"`
```json
{"action":"toggle_eagle","entities":{"state":"on"},"confidence":0.95,"needs_confirmation":false,"reason":"User explicitly asked to activate Eagle AI"}
```

**Input:** `"what has eagle detected?"`
```json
{"action":"show_findings","entities":{},"confidence":0.9,"needs_confirmation":false,"reason":"User asked to see Eagle AI findings"}
```

**Input:** `"explain the second finding"`
```json
{"action":"explain_finding","entities":{"finding_index":1},"confidence":0.85,"needs_confirmation":false,"reason":"User asked for explanation of the second AI finding"}
```
