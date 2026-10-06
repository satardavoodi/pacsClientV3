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
| `date`       | string  | no       | `"today"` \| `"yesterday"` \| `"YYYY-MM-DD"` \| `"YYYY-MM-DD..YYYY-MM-DD"` (range). **Always resolve relative expressions to a concrete `YYYY-MM-DD` using the DATE CONTEXT in the prompt.** |
| `modality`   | string  | no       | DICOM modality code: `"CT"` \| `"MR"` \| `"US"` \| `"DX"` \| `"CR"` \| `"XA"` أ¢â‚¬آ¦ "MRI" maps to `"MR"`. |
| `patient_name` | string | no     | Free-text partial match against patient name. |
| `patient_code` | string | no     | Exact or partial patient ID match. |

**Confirmation required:** `false`

---

### 2.2 `set_source_mode`
Switch the active data-source tab (Local / Server / Import).

**Entity schema:**

| entity  | type   | required | description |
|---------|--------|----------|-------------|
| `mode`  | string | yes      | `"local"` \| `"server"` \| `"import"` |

**Confirmation required:** `false`

---

### 2.3 `import_dicom`
Open the Import tab and launch the DICOM folder-selection dialog.

**Entity schema:** *(none required)*

**Confirmation required:** `false`

---

### 2.4 `select_patient`
Select (tick the checkbox of) one or more patient rows **without opening them**.

**Entity schema:**

| entity         | type    | required | description |
|----------------|---------|----------|-------------|
| `patient_code` | string  | no       | Patient ID or partial name to match. |
| `limit`        | integer | no       | Select the top N rows in current display order. |

Provide **either** `patient_code` **or** `limit`.

**Confirmation required:** `false`

---

### 2.5 `change_font_size`
Increase or decrease the patient-list text size.

**Entity schema:**

| entity      | type   | required | description |
|-------------|--------|----------|-------------|
| `direction` | string | yes      | `"increase"` or `"decrease"` |

**Confirmation required:** `false`

---

### 2.6 `sort_patients`
Sort the patient list by a column.

**Entity schema:**

| entity   | type   | required | description |
|----------|--------|----------|-------------|
| `column` | string | yes      | `"date"` \| `"time"` \| `"images_count"` \| `"modality"` \| `"patient_name"` \| `"patient_id"` \| `"description"` \| `"age"` |
| `order`  | string | no       | `"asc"` or `"desc"` (default `"desc"`) |

**Confirmation required:** `false`

---

### 2.7 `select_and_download`
Sort the list أ¢â€ â€™ select the top N rows أ¢â€ â€™ download them (requires confirmation).

**Entity schema:**

| entity        | type    | required | description |
|---------------|---------|----------|-------------|
| `sort_column` | string  | no       | Column to sort by (default `"date"`). |
| `sort_order`  | string  | no       | `"asc"` or `"desc"` (default `"desc"`). |
| `limit`       | integer | yes      | How many patients to select and download. |

**Confirmation required:** `true`

**Example JSON (download first 10 patients by date):**
```json
{
  "action": "select_and_download",
  "entities": { "sort_column": "date", "sort_order": "desc", "limit": 10 },
  "confidence": 0.95,
  "needs_confirmation": true,
  "reason": "User asked to download the 10 most recent patients."
}
```

**Example JSON (download 10 patients with most images):**
```json
{
  "action": "select_and_download",
  "entities": { "sort_column": "images_count", "sort_order": "desc", "limit": 10 },
  "confidence": 0.95,
  "needs_confirmation": true,
  "reason": "User asked to download patients with highest image count, top 10."
}
```

---

### 2.8 `open_patient`
Open a patient study (simulate double-click أ¢â€ â€™ PatientWidget opens).

**Entity schema:**

| entity         | type   | required | description |
|----------------|--------|----------|-------------|
| `patient_code` | string | yes      | Patient ID or partial name. |

**Confirmation required:** `true`

---

### 2.9 `download_patient`
Download a single patient study.

**Entity schema:**

| entity         | type   | required | description |
|----------------|--------|----------|-------------|
| `patient_code` | string | no       | Patient ID or partial name. Uses last selected if omitted. |

**Confirmation required:** `true` أ¢â‚¬â€‌ **EXCEPTION:** if `patient_code` is a plain numeric ID resolved directly from the conversation memory list (single unambiguous match), set `needs_confirmation: false`.

---

## 3. Persian / multilingual phrase map

| User says (Persian / English)                               | Maps to                                    |
|-------------------------------------------------------------|--------------------------------------------|
| ط¸â€‍ط؛إ’ط·آ³ط·ع¾ ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ±ط·آ§ط¸â€  / ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ±ط·آ§ط¸â€  ط·آ±ط¸ث† ط¸â€ ط·آ´ط¸ث†ط¸â€  ط·آ¨ط·آ¯ط¸â€،                         | `list_patients`                            |
| ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ±ط·آ§ط¸â€  ط·آ§ط¸â€¦ط·آ±ط¸ث†ط·آ²                                               | `date = "today"`                           |
| ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ±ط·آ§ط¸â€  ط·آ¯ط؛إ’ط·آ±ط¸ث†ط·آ² / ط·آ¯ط؛إ’ط·آ±ط¸ث†ط·آ²                                       | `date = "yesterday"`                       |
| ط·آ¯ط¸ث† ط·آ±ط¸ث†ط·آ² ط¸â€ڑط·آ¨ط¸â€‍ / ط¸آ¾ط·آ±ط؛إ’ط·آ±ط¸ث†ط·آ²                                        | `date = <2 days ago ISO>`                  |
| ط·آ³ط¸â€، ط·آ±ط¸ث†ط·آ² ط¸â€ڑط·آ¨ط¸â€‍                                                  | `date = <3 days ago ISO>`                  |
| N ط·آ±ط¸ث†ط·آ² ط¸â€ڑط·آ¨ط¸â€‍ / N ط·آ±ط¸ث†ط·آ² ط¸آ¾ط؛إ’ط·آ´                                      | `date = <N days ago ISO>`                  |
| ط¸â€،ط¸ظ¾ط·ع¾ط¸â€، ط¹آ¯ط·آ°ط·آ´ط·ع¾ط¸â€، / ط·آ§ط؛إ’ط¸â€  ط¸â€،ط¸ظ¾ط·ع¾ط¸â€،                                      | `date = <week range ISO>`                  |
| ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ±ط·آ§ط¸â€  ط·آ³ط·آ±ط¸ث†ط·آ± / ط·آ§ط·آ² ط·آ³ط·آ±ط¸ث†ط·آ±                                      | `source = "server"`                        |
| ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ±ط·آ§ط¸â€  ط¸â€¦ط·آ­ط¸â€‍ط؛إ’ / ط¸â€‍ط¸ث†ط¹آ©ط·آ§ط¸â€‍                                        | `source = "local"`                         |
| ط·آ³ط؛إ’أ¢â‚¬إ’ط·ع¾ط؛إ’ ط·آ§ط·آ³ط¹آ©ط¸â€  / CT                                            | `modality = "CT"`                          |
| MRI / ط·آ§ط¸â€¦أ¢â‚¬إ’ط·آ¢ط·آ±أ¢â‚¬إ’ط·آ¢ط؛إ’ / ط·آ§ط¸â€¦ ط·آ¢ط·آ± ط·آ¢ط؛إ’                                  | `modality = "MR"`                          |
| ط·آ³ط¸ث†ط¸â€ ط¸ث†ط¹آ¯ط·آ±ط·آ§ط¸ظ¾ط؛إ’ / US / ط·آ§ط¸ث†ط¸â€‍ط·ع¾ط·آ±ط·آ§ط·آ³ط¸ث†ط¸â€ ط·آ¯                                | `modality = "US"`                          |
| ط·آ±ط·آ§ط·آ¯ط؛إ’ط¸ث†ط¹آ¯ط·آ±ط·آ§ط¸ظ¾ط؛إ’ / DX / CR / ط¹آ¯ط·آ±ط·آ§ط¸ظ¾ط؛إ’                               | `modality = "DX"`                          |
| **Source Mode**                                             |                                            |
| ط·آ¨ط·آ±ط¸ث† ط·آ³ط·آ±ط¸ث†ط·آ± / ط·آ­ط·آ§ط¸â€‍ط·ع¾ ط·آ³ط·آ±ط¸ث†ط·آ± / ط·ع¾ط·آ¨ ط·آ³ط·آ±ط¸ث†ط·آ±                             | `set_source_mode { mode: "server" }`       |
| ط·آ¨ط·آ±ط¸ث† ط¸â€‍ط¸ث†ط¹آ©ط·آ§ط¸â€‍ / ط·آ­ط·آ§ط¸â€‍ط·ع¾ ط¸â€‍ط¸ث†ط¹آ©ط·آ§ط¸â€‍ / ط·ع¾ط·آ¨ ط¸â€¦ط·آ­ط¸â€‍ط؛إ’                           | `set_source_mode { mode: "local" }`        |
| ط·آ¨ط·آ±ط¸ث† ط·آ§ط؛إ’ط¸â€¦ط¸آ¾ط¸ث†ط·آ±ط·ع¾ / ط¸ث†ط·آ§ط·آ±ط·آ¯ ط¹آ©ط·آ±ط·آ¯ط¸â€  ط¸ظ¾ط·آ§ط؛إ’ط¸â€‍ / ط·ع¾ط·آ¨ ط·آ§ط؛إ’ط¸â€¦ط¸آ¾ط¸ث†ط·آ±ط·ع¾                 | `set_source_mode { mode: "import" }`       |
| ط؛إ’ط¹آ© ط¸ظ¾ط·آ§ط؛إ’ط¸â€‍ DICOM ط¸ث†ط·آ§ط·آ±ط·آ¯ ط¹آ©ط¸â€  / ط·آ§ط؛إ’ط¸â€¦ط¸آ¾ط¸ث†ط·آ±ط·ع¾ ط·آ¯ط·آ§ط؛إ’ط¹آ©ط·آ§ط¸â€¦                    | `import_dicom`                             |
| **Search / Find / Locate Patient** (verb = locate in list, NOT open viewer) |  |
| ط·آ³ط·آ±ط·آ´ ط¹آ©ط¸â€  / ط·آ³ط·آ±ط·آ²ط·آ¯ط¸â€  ط·آ¨ط¸â€،ط·آ´ / ط·آ¬ط·آ³ط·ع¾ط·آ¬ط¸ث†ط·آ´ ط¹آ©ط¸â€  / ط¸آ¾ط؛إ’ط·آ¯ط·آ§ط·آ´ ط¹آ©ط¸â€                 | `select_patient { patient_code: "X" }`     |
| ط·آ¨ط·آ±ط·آ±ط·آ³ط؛إ’ط·آ´ ط¹آ©ط¸â€  / ط·آ¨ط·آ¨ط؛إ’ط¸â€  ط¹آ©ط·آ¬ط·آ§ط·آ³ط·ع¾ / ط·آ³ط·آ±ط¹â€ ط·آ´ ط¹آ©ط¸â€  / checkط·آ´ ط¹آ©ط¸â€               | `select_patient { patient_code: "X" }`     |
| search X / find X / locate X / look up X                   | `select_patient { patient_code: "X" }`     |
| **Select Patient**                                          |                                            |
| ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ± X ط·آ±ط¸ث† ط·آ§ط¸â€ ط·ع¾ط·آ®ط·آ§ط·آ¨ ط¹آ©ط¸â€  / select patient X                    | `select_patient { patient_code: "X" }`     |
| ط؛آ±ط؛آ° ط·ع¾ط·آ§ ط·آ§ط¸ث†ط¸â€‍ ط·آ±ط¸ث† ط·آ§ط¸â€ ط·ع¾ط·آ®ط·آ§ط·آ¨ ط¹آ©ط¸â€  / select first 10                   | `select_patient { limit: 10 }`             |
| **Open Patient** (verb = enter viewer أ¢â‚¬â€‌ ط·آ¨ط·آ§ط·آ² ط¹آ©ط¸â€  / ط·آ¨ط·آ§ط·آ²ط·آ´ ط¹آ©ط¸â€ )  |                                            |
| ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ± X ط·آ±ط¸ث† ط·آ¨ط·آ§ط·آ² ط¹آ©ط¸â€  / ط·آ¨ط·آ§ط·آ²ط·آ´ ط¹آ©ط¸â€  / open patient X               | `open_patient { patient_code: "X" }`       |
| **Font Size**                                               |                                            |
| ط¸ظ¾ط¸ث†ط¸â€ ط·ع¾ ط·آ±ط¸ث† ط·آ¨ط·آ²ط·آ±ط¹آ¯أ¢â‚¬إ’ط·ع¾ط·آ± ط¹آ©ط¸â€  / ط¸â€¦ط·ع¾ط¸â€  ط·آ±ط¸ث† ط·آ¨ط·آ²ط·آ±ط¹آ¯ط·ع¾ط·آ± / increase text        | `change_font_size { direction: "increase" }` |
| ط¸ظ¾ط¸ث†ط¸â€ ط·ع¾ ط·آ±ط¸ث† ط¹آ©ط¸ث†ط¹â€ ط؛إ’ط¹آ©أ¢â‚¬إ’ط·ع¾ط·آ± ط¹آ©ط¸â€  / ط¸â€¦ط·ع¾ط¸â€  ط·آ±ط¸ث† ط¹آ©ط¸ث†ط¹â€ ط¹آ©ط·ع¾ط·آ± / decrease text       | `change_font_size { direction: "decrease" }` |
| **Sort**                                                    |                                            |
| ط¸â€¦ط·آ±ط·ع¾ط·آ¨ ط¹آ©ط¸â€  ط·آ¨ط·آ± ط·آ§ط·آ³ط·آ§ط·آ³ ط·ع¾ط·آ§ط·آ±ط؛إ’ط·آ® / sort by date                       | `sort_patients { column: "date", order: "desc" }` |
| ط¸â€¦ط·آ±ط·ع¾ط·آ¨ ط¹آ©ط¸â€  ط·آ¨ط·آ± ط·آ§ط·آ³ط·آ§ط·آ³ ط·ع¾ط·آ¹ط·آ¯ط·آ§ط·آ¯ ط·ع¾ط·آµط¸ث†ط؛إ’ط·آ± / sort by images               | `sort_patients { column: "images_count", order: "desc" }` |
| ط¸â€¦ط·آ±ط·ع¾ط·آ¨ ط¹آ©ط¸â€  ط·آ¨ط·آ± ط·آ§ط·آ³ط·آ§ط·آ³ ط·آ§ط·آ³ط¸â€¦ ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ± / sort by name                   | `sort_patients { column: "patient_name", order: "asc" }` |
| **Select & Download**                                       |                                            |
| ط؛آ±ط؛آ° ط·ع¾ط·آ§ط؛إ’ ط·آ§ط¸ث†ط¸â€‍ ط·آ±ط¸ث† ط·آ¯ط·آ§ط¸â€ ط¸â€‍ط¸ث†ط·آ¯ ط¹آ©ط¸â€  / download first 10                | `select_and_download { sort_column:"date", sort_order:"desc", limit:10 }` |
| ط؛آ±ط؛آ° ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ± ط·آ¨ط·آ§ ط·آ¨ط؛إ’ط·آ´ط·ع¾ط·آ±ط؛إ’ط¸â€  ط·ع¾ط·آµط¸ث†ط؛إ’ط·آ± ط·آ¯ط·آ§ط¸â€ ط¸â€‍ط¸ث†ط·آ¯ / highest image count     | `select_and_download { sort_column:"images_count", sort_order:"desc", limit:10 }` |
| ط·آ§ط¸â€ ط·ع¾ط·آ®ط·آ§ط·آ¨ ط¸ث† ط·آ¯ط·آ§ط¸â€ ط¸â€‍ط¸ث†ط·آ¯ N ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ± / select and download N            | `select_and_download { limit: N }`         |

---

## 4. Execution notes

- If `source` is not specified for `list_patients`, use `"active_tab"` to keep the current tab.
- Date ranges are inclusive on both ends.
- `needs_confirmation` must be `false` for `list_patients`, `set_source_mode`, `import_dicom`, `select_patient`, `change_font_size`, `sort_patients`.
- `needs_confirmation` must be `true` for `open_patient`, `download_patient`, `select_and_download` أ¢â‚¬â€‌ **EXCEPT** when the `patient_code` is a numeric patient ID resolved unambiguously from the conversation memory list: in that case set `needs_confirmation: false` for `open_patient` and `download_patient`.
- `confidence` range: 0.0أ¢â‚¬â€œ1.0.
- `select_and_download`: always set `needs_confirmation: true` because it will queue downloads.
- `sort_patients` + immediate download should use `select_and_download` (single action), not two separate actions.
- When user says "first N patients" without specifying sort, default `sort_column` to `"date"`, `sort_order` to `"desc"`.
- When user says "most images" or "highest image count", use `sort_column: "images_count"`, `sort_order: "desc"`.

---

## 5. Output contract (strict)

Return **only** a JSON object (no markdown fences, no prose) with exactly these top-level keys:

```
action, entities, confidence, needs_confirmation, reason
```

---

## 7. VERB SEMANTICS أ¢â‚¬â€‌ CRITICAL ACTION DISAMBIGUATION

The **verb** in the user's sentence determines the action.  Context alone must
never override the verb.  The following table is authoritative:

| Verb group | Persian examples | English | أ¢â€ â€™ Action |
|---|---|---|---|
| **Search / Find / Locate** | ط·آ³ط·آ±ط·آ´ ط¹آ©ط¸â€  ط¢آ· ط·آ³ط·آ±ط·آ²ط·آ¯ط¸â€  ط¢آ· ط·آ¬ط·آ³ط·ع¾ط·آ¬ط¸ث† ط¹آ©ط¸â€  ط¢آ· ط¸آ¾ط؛إ’ط·آ¯ط·آ§ط·آ´ ط¹آ©ط¸â€  ط¢آ· ط·آ¨ط·آ¨ط؛إ’ط¸â€  ط¹آ©ط·آ¬ط·آ§ط·آ³ط·ع¾ ط¢آ· ط·آ³ط·آ±ط¹â€ ط·آ´ ط¹آ©ط¸â€  ط¢آ· ط¹â€ ط¹آ© ط¹آ©ط¸â€  | search ط¢آ· find ط¢آ· locate ط¢آ· look up ط¢آ· check | `select_patient` |
| **Open / View** | ط·آ¨ط·آ§ط·آ² ط¹آ©ط¸â€  ط¢آ· ط·آ¨ط·آ§ط·آ²ط·آ´ ط¹آ©ط¸â€  ط¢آ· ط¸â€¦ط·آ´ط·آ§ط¸â€،ط·آ¯ط¸â€، ط¹آ©ط¸â€  ط¢آ· ط·آ¨ط·آ¨ط؛إ’ط¸â€ ط¸â€¦ط·آ´ | open ط¢آ· view ط¢آ· launch ط¢آ· enter | `open_patient` |
| **Download / Fetch** | ط·آ¯ط·آ§ط¸â€ ط¸â€‍ط¸ث†ط·آ¯ط·آ´ ط¹آ©ط¸â€  ط¢آ· ط·آ¯ط·آ±ط؛إ’ط·آ§ط¸ظ¾ط·ع¾ط·آ´ ط¹آ©ط¸â€  ط¢آ· ط·آ¨ط¹آ¯ط؛إ’ط·آ±ط·آ´ | download ط¢آ· fetch ط¢آ· save | `download_patient` |
| **List / Show** | ط¸â€ ط·آ´ط¸ث†ط¸â€  ط·آ¨ط·آ¯ط¸â€، ط¢آ· ط·آ¨ط؛إ’ط·آ§ط·آ± ط¢آ· ط¸â€‍ط؛إ’ط·آ³ط·ع¾ ط¹آ©ط¸â€  (no specific patient) | list ط¢آ· show ط¢آ· display | `list_patients` |

**Rule:** When only the verb differs, GPT MUST follow the table above.  
**Example:** "ط·آ§ط¸â€¦ ط·آ¢ط·آ± ط·آ¢ط؛إ’ ط¸â€¦ط·ط›ط·آ² ط·آ³ط¸ث†ط¸â€¦ط؛إ’ط¸â€، ط¸â€¦ط؛إ’ط·آ±ط¸ظ¾ط¸â€ ط·آ¯ط·آ± ط·آ§ط·آ³ط¹آ©ط؛إ’ ط·آ±ط¸ث† ط·آ³ط·آ±ط·آ´ ط¹آ©ط¸â€ " أ¢â€ â€™ `select_patient` (search verb).
**Example:** "ط·آ§ط¸â€¦ ط·آ¢ط·آ± ط·آ¢ط؛إ’ ط¸â€¦ط·ط›ط·آ² ط·آ³ط¸ث†ط¸â€¦ط؛إ’ط¸â€، ط¸â€¦ط؛إ’ط·آ±ط¸ظ¾ط¸â€ ط·آ¯ط·آ± ط·آ§ط·آ³ط¹آ©ط؛إ’ ط·آ±ط¸ث† ط·آ¨ط·آ§ط·آ² ط¹آ©ط¸â€ " أ¢â€ â€™ `open_patient` (open verb).

If the verb is ambiguous or absent, choose the least-intrusive action:
`select_patient` > `open_patient` > `download_patient`

---

## 6. CONVERSATION MEMORY أ¢â‚¬â€‌ how to use prior-cycle patient lists

When the prompt contains a `=== CONVERSATION MEMORY ===` block, treat it as the
**authoritative intermediate state** from the current session.  Each cycle in
that block contains a structured `[Patient List]` section formatted as:

```
  N. ID:<patient_id> | Name:<patient_name> | Modality:<code> | Body:<body_part> | Date:... | Time:... | Images:...
```

### 6.1 Resolving a patient reference from memory

When the user's follow-up command references a patient by any characteristic
that can be matched against the memory list (modality, body part, name fragment,
position / index, description), you **must**:

1. Scan the `[Patient List]` rows of the **most recent cycle** whose list is
   non-empty.
2. Filter rows where the referenced characteristic matches (case-insensitive
   substring match is acceptable for body_part and patient_name; exact match
   for modality code).
3. Extract the `patient_id` value (the number after `ID:`) from the matched
   row(s).
4. Use that numeric `patient_id` as the `patient_code` entity in your plan.
5. Because the patient is already uniquely identified, set `needs_confirmation: false` (single match) so the command executes immediately without requiring a second voice confirmation.

**IMPORTANT أ¢â‚¬â€‌ what NOT to do:**
- أ¢â€Œإ’ Do NOT use the body-part name (e.g. `"BREAST"`, `"BRAIN"`) as `patient_code`.
- أ¢â€Œإ’ Do NOT use the modality code (e.g. `"MR"`, `"CT"`) as `patient_code`.
- أ¢â€Œإ’ Do NOT use descriptive words from the user request as `patient_code`.
- أ¢إ“â€¦ `patient_code` must always be a real patient identifier from the memory list.

### 6.2 Multiple matches from memory

If multiple rows match the filter:
- Set `needs_confirmation: true`.
- Place the **first** (or best) match `patient_id` in `patient_code`.
- Explain the ambiguity in the `reason` field.

### 6.3 Memory list is empty / body_part not populated

If the memory patient list is empty or the needed field (e.g. `body_part`) is
blank for all rows, produce a fresh `list_patients` action with the appropriate
filter (e.g. `modality`, `date`) to re-fetch the data, instead of guessing.

### 6.4 Continuation examples

| User follow-up (after a list of 60 MRI patients was fetched) | Correct plan |
|--------------------------------------------------------------|--------------|
| "ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ±ط؛إ’ ط¹آ©ط¸â€، ط·آ¨ط·آ±ط·آ³ط·ع¾ ط·آ§ط¸â€ ط·آ¬ط·آ§ط¸â€¦ ط·آ¯ط·آ§ط·آ¯ط¸â€، ط·آ¯ط·آ§ط¸â€ ط¸â€‍ط¸ث†ط·آ¯ط·آ´ ط¹آ©ط¸â€ " (download breast patient) | Find row with Body containing "breast" أ¢â€ â€™ use its ID as patient_code أ¢â€ â€™ `download_patient { patient_code: "<ID>", needs_confirmation: false }` |
| "ط¸â€ ط¸ظ¾ط·آ± ط¸آ¾ط¸â€ ط·آ¬ط¸â€¦ ط·آ±ط¸ث† ط·آ¯ط·آ§ط¸â€ ط¸â€‍ط¸ث†ط·آ¯ ط¹آ©ط¸â€ " (download the 5th one) | Take the 5th row from memory list أ¢â€ â€™ use its ID أ¢â€ â€™ `download_patient { patient_code: "<ID>", needs_confirmation: false }` |
| "ط·آ¨ط؛إ’ط¸â€¦ط·آ§ط·آ± ط·آ§ط·آ­ط¸â€¦ط·آ¯ط؛إ’ ط·آ±ط¸ث† ط·آ¨ط·آ§ط·آ² ط¹آ©ط¸â€ " (open patient Ahmadi) | Find row with Name containing "AHMADI" أ¢â€ â€™ use its ID أ¢â€ â€™ `open_patient { patient_code: "<ID>", needs_confirmation: false }` |
| "ط·آ§ط¸ث†ط¸â€‍ط؛إ’ط¸â€  ط·آ±ط¸ث† ط·آ§ط¸â€ ط·ع¾ط·آ®ط·آ§ط·آ¨ ط¹آ©ط¸â€ " (select the first one) | Take the 1st row ID أ¢â€ â€™ `select_patient { patient_code: "<ID>" }` |


## Shared advanced filter, exact selection and media contract (2026-10-02)

Use `advanced_search_patients` for body_part, age_min/age_max, modality (comma-separated CT/MR tokens), date_from/date_to (YYYYMMDD), patient ID/name and source local/server. This is the existing Patient-ID Advanced Search path; do not substitute an unfiltered list or use the old relative-date entity for this action. Poll `read_patients` until ready; use its `list_id` for ordinal selection. Calendar dates must be resolved from the supplied client time. Clarify calendar-month versus rolling-range ambiguity.

`select_patients` accepts exactly one of `row_indices` (one-based, with list_id), `study_uids`, or `patient_ids`. A patient ID with several visible studies is ambiguous; list and use exact study UIDs. Names alone are never authoritative identity. Selection replaces existing checkboxes and returns `selection_id`. A changed selection/source invalidates the receipt. `selection_status` verifies the receipt. Never fabricate list_id or selection_id. Negotiated sequential workflows may reference `$list_id` and `$selection_id` from real preceding read/selection results.

`download_selection` enqueues exactly the receipt's studies; queued is not downloaded. `film_selection` requests the existing Printing module with that selection; it does not claim films printed. Use separate terminal verification before following download with output operations.

`media_drives` starts a worker drive discovery; poll `media_status` using operation_id. `write_selection_media` requires explicit confirmation, selection_id, and mode `burn` or `folder`. Burn requires an explicit drive_id from discovery. Folder requires an absolute new output_folder whose parent exists. Optional disc_label, anonymize, include_report/images/attachments, original/uncompressed/lossless/jpeg2000 format, write_speed_sectors, finalize_disc and verify_after_burn are supported. Verification defaults on. include_viewer defaults on and resolves the saved local viewer setting on the worker; unavailable configured viewer fails instead of silently producing media without it. Existing center identity is loaded locally. Existing CD worker prepares DICOM content and the locally configured portable viewer. Poll `media_status` for terminal success/failure; `cancel_media` requests cancellation. All selected studies must already have local DICOM content; a missing study fails the whole output instead of silently omitting it. Never claim initiation equals successful CD write. Honor run_cd/printing installation gates.

# Prepare the Write CD configuration dialog

When the user asks to proceed to Write CD without an explicit physical-write target,
finish the requested filtering and sorting, bind the current ordered list, select
the requested rows with select_patients, then call prepare_selection_media with
selection_id: "$selection_id". This opens the existing Write to CD/DVD settings
dialog after asynchronous preflight. It does not burn a disc or download studies.
Poll media_status with operation_id: "$operation_id" to verify dialog_open.
media_drives only discovers drives and does not satisfy a request to open Write CD.
Do not omit the requested preparation step. Never substitute a physical write
without the required target and confirmation. Only advertise this action when it
is present in the negotiated runtime snapshot.

### Bound ordinal opening
The runtime open_patient action accepts either patient_id or row_index (1-based) plus list_id. For search then open first: advanced_search_patients, read_patients until ready, then open_patient with row_index: 1 and list_id: "$list_id" from that receipt. Never invent patient identifiers or reuse a stale list. Preserve confirmation policy and verify the active study identity.

## Verified patient workflow facts

read_patients rows include report_status, voice_presence (present/absent/unknown), local_artifacts, row_index and workflow_scope. Unknown or expired evidence is not absent. Voice presence combines fresh study/person-bound server audio counts and positive local cached voice evidence. Local absence alone never proves absence on the server. Author identity is unavailable unless explicitly supplied; assignment and reporting physician do not identify the voice recorder.

To open the first patient without voice, read the current list and pick the first row with voice_presence exactly absent. Preserve its original row_index and list_id for open_patient; never renumber a filtered list or use an unknown row. If no row has verified absence, explain the missing evidence rather than guessing. A truncated list only supports the returned prefix. Re-read and re-evaluate after list/source changes. A displayed row may merge studies: facts describe the primary study, not every study for that person.

get_loaded_study_summary provides date/modality workflow_groups, separate unknown counts and daily_population_complete. Loaded rows are not all daily admissions. Do not say “your recordings” without author evidence. Completed is distinct from physician_approved, secretary_approved, awaiting approval and archived. No voice does not prove no final report; voice present does not prove report completed.

get_tutorial_catalog supplies workflow_guide with verified indicator meanings. Completed report uses an emerald double-check or green reporting physician name. Physician/secretary approval uses a single check-circle. The Report tooltip identifies the actual workflow status. A red local microphone indicates local voice files; a blue server microphone indicates server audio. Neither proves personal authorship or delivery to reception. Highlight only tutorial IDs actually supplied by the client; otherwise give text guidance.

For voice-conditioned opening, include required_voice_presence: "absent" (or "present") with row_index and list_id. The client rechecks the evidence immediately before opening and rejects changed/unknown status.


## UI observation and execution boundary (2026-10-04)
- get_ui_control_catalog: entities {area,offset,limit}; area=all,home,settings,patient_viewer,advanced_viewer,advanced_analysis,eagle_eye. Source-traced field types/options plus currently registered executable_contracts. Paginate with limit <=100. Discovery is not execution support.
- inspect_ui_controls: entities {}; inspect the currently visible Qt page/modal. Returns enabled state, bounds, checked state and dropdown option indices. Text/numeric values are redacted; unknown dynamic labels are local-only. Do not infer patient identities or missing values.
- capture_ui_context: entities {}; capture redacted control pixels asynchronously. Use returned snapshot_id with ui_context_status; wait for state=ready. Screenshots exclude clinical canvas and all input values. No Windows file path is a usable server image.
- ui_context_status: entities {snapshot_id}; returns correlated PNG pixels and control metadata; rejects changed pages and captures older than 90 seconds. Re-observe after navigation.
- Select a supported typed action from executable_contracts and validate its entities/enum/range/backend. Never execute source callbacks or generic widget writes. Filled fields do not prove saved/applied state; poll asynchronous operations and read back results. Fast Viewer, Advanced Viewer and native Advanced Imaging are distinct execution domains. External native/Slicer controls are not accessible merely because their sources appear in an inventory.
