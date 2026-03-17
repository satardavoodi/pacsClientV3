# Module Document: EchoMind AI Assistant
**module_id:** `echomind`
**Document version:** 1.0
**Sent in Phase 2 when the LLM needs to handle AI chat, voice, or report generation.**

---

## 1. What This Module Does

EchoMind is the conversational AI layer of the AIPacs workstation.
It provides:

* **Voice-to-text (STT):** Convert spoken commands to text via native STT or the V2T engine.
* **AI Chat:** Free-form clinical conversation with GPT-4.1-mini about the active study.
* **Findings Summary:** Auto-generate a structured radiology findings paragraph.
* **Report Generation:** Produce a full structured radiology report from the findings.

EchoMind is the module where the *Secretary orchestrator itself* lives.
When the user's intent is AI conversation or report authoring (not PACS navigation),
this is the appropriate module.

---

## 2. Available Actions

### `ai_chat`

Sends a free-form message to the AI chat companion for the active study.

| Entity | Type | Notes |
|---|---|---|
| `message` | string | The user's question or instruction |
| `context` | string | `"active_study"` (default) \| `"findings"` |

**needs_confirmation:** `false`

### `generate_summary`

Asks EchoMind to auto-summarise the current study's key findings.

| Entity | Type | Notes |
|---|---|---|
| `style` | string | `"brief"` (default) \| `"detailed"` \| `"structured"` |

**needs_confirmation:** `false`

### `generate_report`

Generates a full structured radiology report.

| Entity | Type | Notes |
|---|---|---|
| `template` | string | `"default"` \| `"chest_ct"` \| `"mri_brain"` etc. |
| `include_measurements` | boolean | Include caliper measurements in the report |

**needs_confirmation:** `false`

---

## 3. Output Contract

```json
{
  "action": "generate_summary",
  "entities": {
    "style": "structured"
  },
  "confidence": 0.9,
  "needs_confirmation": false,
  "reason": "User asked EchoMind to summarise the study findings"
}
```

---

## 4. Example Interactions

**Input:** `"summarize this study"`
```json
{"action":"generate_summary","entities":{"style":"brief"},"confidence":0.9,"needs_confirmation":false,"reason":"User asked for brief findings summary"}
```

**Input:** `"generate a chest CT report"`
```json
{"action":"generate_report","entities":{"template":"chest_ct"},"confidence":0.92,"needs_confirmation":false,"reason":"User asked for a chest CT structured report"}
```

**Input:** `"what does this scan show?"`
```json
{"action":"ai_chat","entities":{"message":"what does this scan show?","context":"active_study"},"confidence":0.88,"needs_confirmation":false,"reason":"User asked a general question about the active study"}
```
