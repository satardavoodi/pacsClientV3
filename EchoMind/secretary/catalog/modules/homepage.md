# Module Document: Homepage / Patient List
**module_id:** `homepage`
**Document version:** 1.0
**Used in Phase 2 by the LLM brain to generate an executable JSON action plan.**

---

## 1. What this module does

The Homepage module controls the main patient-list panel of the AIPacs workstation.  
It can:
- Search for patients using zero or more filters (date range, modality, patient name, patient code).
- Return the filtered patient rows to the user.
- Switch the active source between the **local** cache and the **PACS server**.
- Refresh/re-fetch the list from the server.

---

## 2. Available actions

### 2.1 `list_patients`
Returns a filtered list of patient rows from the active or specified source.

**Entity schema:**

| entity       | type    | required | description |
|--------------|---------|----------|-------------|
| `source`     | string  | no       | `"local"` \| `"server"` \| `"active_tab"` (default). |
| `date`       | string  | no       | `"today"` \| `"yesterday"` \| `"YYYY-MM-DD"` \| `"YYYY-MM-DD..YYYY-MM-DD"` (range). |
| `modality`   | string  | no       | DICOM modality code: `"CT"` \| `"MR"` \| `"US"` \| `"DX"` \| `"CR"` \| `"XA"` … Note: "MRI" maps to `"MR"`. |
| `patient_name` | string | no     | Free-text partial match against patient name. |
| `patient_code` | string | no     | Exact or partial patient ID match. |

**Confirmation required:** `false`

**Example output JSON:**
```json
{
  "action": "list_patients",
  "entities": {
    "source": "server",
    "date": "today"
  },
  "confidence": 0.95,
  "needs_confirmation": false,
  "reason": "User asked to show today's patients from the server."
}
```

---

## 3. Persian / multilingual phrase map

| User says (Persian)                              | Maps to                    |
|--------------------------------------------------|----------------------------|
| لیست بیماران / بیماران رو نشون بده              | `list_patients`            |
| بیماران امروز                                    | `date = "today"`           |
| بیماران دیروز / دیروز                            | `date = "yesterday"`       |
| بیماران سرور / از سرور                           | `source = "server"`        |
| بیماران محلی / لوکال                             | `source = "local"`         |
| سی‌تی اسکن / CT                                 | `modality = "CT"`          |
| MRI / ام‌آر‌آی                                   | `modality = "MR"`          |

---

## 4. Execution notes

- If `source` is not specified, use `"active_tab"` to keep the current tab.
- Date ranges are inclusive on both ends.
- `needs_confirmation` must be `false` for `list_patients`.
- `confidence` should reflect how clearly the user's request maps; range 0.0–1.0.

---

## 5. Output contract (strict)

Return **only** a JSON object (no markdown fences, no prose) with exactly these top-level keys:

```
action, entities, confidence, needs_confirmation, reason
```
