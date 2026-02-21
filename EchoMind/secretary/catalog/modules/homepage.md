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
| `modality`   | string  | no       | DICOM modality code: `"CT"` \| `"MR"` \| `"US"` \| `"DX"` \| `"CR"` \| `"XA"` … "MRI" maps to `"MR"`. |
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
Sort the list → select the top N rows → download them (requires confirmation).

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
Open a patient study (simulate double-click → PatientWidget opens).

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

**Confirmation required:** `true`

---

## 3. Persian / multilingual phrase map

| User says (Persian / English)                               | Maps to                                    |
|-------------------------------------------------------------|--------------------------------------------|
| لیست بیماران / بیماران رو نشون بده                         | `list_patients`                            |
| بیماران امروز                                               | `date = "today"`                           |
| بیماران دیروز / دیروز                                       | `date = "yesterday"`                       |
| دو روز قبل / پریروز                                        | `date = <2 days ago ISO>`                  |
| سه روز قبل                                                  | `date = <3 days ago ISO>`                  |
| N روز قبل / N روز پیش                                      | `date = <N days ago ISO>`                  |
| هفته گذشته / این هفته                                      | `date = <week range ISO>`                  |
| بیماران سرور / از سرور                                      | `source = "server"`                        |
| بیماران محلی / لوکال                                        | `source = "local"`                         |
| سی‌تی اسکن / CT                                            | `modality = "CT"`                          |
| MRI / ام‌آر‌آی / ام آر آی                                  | `modality = "MR"`                          |
| سونوگرافی / US / اولتراسوند                                | `modality = "US"`                          |
| رادیوگرافی / DX / CR / گرافی                               | `modality = "DX"`                          |
| **Source Mode**                                             |                                            |
| برو سرور / حالت سرور / تب سرور                             | `set_source_mode { mode: "server" }`       |
| برو لوکال / حالت لوکال / تب محلی                           | `set_source_mode { mode: "local" }`        |
| برو ایمپورت / وارد کردن فایل / تب ایمپورت                 | `set_source_mode { mode: "import" }`       |
| یک فایل DICOM وارد کن / ایمپورت دایکام                    | `import_dicom`                             |
| **Select Patient**                                          |                                            |
| بیمار X رو انتخاب کن / select patient X                    | `select_patient { patient_code: "X" }`     |
| ۱۰ تا اول رو انتخاب کن / select first 10                   | `select_patient { limit: 10 }`             |
| **Open Patient**                                            |                                            |
| بیمار X رو باز کن / open patient X                         | `open_patient { patient_code: "X" }`       |
| **Font Size**                                               |                                            |
| فونت رو بزرگ‌تر کن / متن رو بزرگتر / increase text        | `change_font_size { direction: "increase" }` |
| فونت رو کوچیک‌تر کن / متن رو کوچکتر / decrease text       | `change_font_size { direction: "decrease" }` |
| **Sort**                                                    |                                            |
| مرتب کن بر اساس تاریخ / sort by date                       | `sort_patients { column: "date", order: "desc" }` |
| مرتب کن بر اساس تعداد تصویر / sort by images               | `sort_patients { column: "images_count", order: "desc" }` |
| مرتب کن بر اساس اسم بیمار / sort by name                   | `sort_patients { column: "patient_name", order: "asc" }` |
| **Select & Download**                                       |                                            |
| ۱۰ تای اول رو دانلود کن / download first 10                | `select_and_download { sort_column:"date", sort_order:"desc", limit:10 }` |
| ۱۰ بیمار با بیشترین تصویر دانلود / highest image count     | `select_and_download { sort_column:"images_count", sort_order:"desc", limit:10 }` |
| انتخاب و دانلود N بیمار / select and download N            | `select_and_download { limit: N }`         |

---

## 4. Execution notes

- If `source` is not specified for `list_patients`, use `"active_tab"` to keep the current tab.
- Date ranges are inclusive on both ends.
- `needs_confirmation` must be `false` for `list_patients`, `set_source_mode`, `import_dicom`, `select_patient`, `change_font_size`, `sort_patients`.
- `needs_confirmation` must be `true` for `open_patient`, `download_patient`, `select_and_download`.
- `confidence` range: 0.0–1.0.
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
