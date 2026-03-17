# Module Document: Download Manager
**module_id:** `download`
**Document version:** 1.0
**Sent in Phase 2 when the LLM needs to queue or manage a study download.**

---

## 1. What This Module Does

The Download Manager module uses the Zeta download engine to:

* Queue study downloads from the PACS server
* Monitor, pause, resume, and cancel downloads
* Report download progress and storage usage

Queuing a download is a **side-effect** action and always requires confirmation.

---

## 2. Available Actions

### `download_patient`

Resolves a patient and queues all of their studies for download.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `patient_code` | string | conditional | Required unless `use_context_patient=true` |
| `use_context_patient` | boolean | no | `true` → download the currently selected patient |
| `source` | string | no | `"server"` (downloads are always from server) |
| `resolved_patient` | dict | no | Pre-resolved patient row (internal) |

**side_effects:** `true`
**needs_confirmation:** `true` — ALWAYS

### `check_download_status` *(read-only, no confirmation)*

Returns summary of current download queue.

| Entity | Type | Notes |
|---|---|---|
| *(none required)* | — | Returns queue snapshot |

**needs_confirmation:** `false`

---

## 3. Output Contract

```json
{
  "action": "download_patient",
  "entities": {
    "patient_code": "P-10042",
    "source": "server"
  },
  "confidence": 0.9,
  "needs_confirmation": true,
  "reason": "User asked to download patient P-10042 from server"
}
```

* `needs_confirmation` must be `true` for `download_patient`
* Raw JSON only

---

## 4. Example Interactions

**Input:** `"دانلود بیمار فعلی"`
```json
{"action":"download_patient","entities":{"use_context_patient":true,"source":"server"},"confidence":0.9,"needs_confirmation":true,"reason":"User asked to download the current patient"}
```

**Input:** `"download patient P-999"`
```json
{"action":"download_patient","entities":{"patient_code":"P-999","source":"server"},"confidence":0.95,"needs_confirmation":true,"reason":"User specified explicit patient code for download"}
```
