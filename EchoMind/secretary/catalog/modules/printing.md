# Module Document: Print / Export
**module_id:** `printing`
**Document version:** 1.0
**Sent in Phase 2 when the LLM needs to print or export DICOM images.**

---

## 1. What This Module Does

The Printing module generates print layouts from the active viewer content
and can send output to:

* A local system printer (direct print)
* A DICOM print server (DICOM Greyscale Print)
* A PDF file on disk

Print operations are side-effect actions and always require confirmation.

---

## 2. Available Actions

### `print_series`

Prints the current series or selected images.

| Entity | Type | Required | Notes |
|---|---|---|---|
| `target` | string | no | `"current_series"` (default) \| `"selected_images"` \| `"all_series"` |
| `destination` | string | no | `"local_printer"` (default) \| `"dicom_printer"` \| `"pdf"` |
| `layout` | string | no | `"1x1"` \| `"2x2"` \| `"1x2"` \| `"4x4"` |
| `copies` | int | no | Number of copies (default 1) |

**side_effects:** `true`
**needs_confirmation:** `true`

### `export_pdf`

Saves the current view layout as a PDF file.

| Entity | Type | Notes |
|---|---|---|
| `filename` | string | Optional output filename (system default if omitted) |
| `include_annotations` | boolean | Whether to burn-in measurement annotations |

**side_effects:** `true`
**needs_confirmation:** `true`

---

## 3. Output Contract

```json
{
  "action": "print_series",
  "entities": {
    "target": "current_series",
    "destination": "local_printer",
    "layout": "2x2"
  },
  "confidence": 0.9,
  "needs_confirmation": true,
  "reason": "User asked to print the current series on local printer"
}
```

* `needs_confirmation` is **always** `true` for printing actions
* Raw JSON only

---

## 4. Example Interactions

**Input:** `"print the current series"`
```json
{"action":"print_series","entities":{"target":"current_series","destination":"local_printer"},"confidence":0.9,"needs_confirmation":true,"reason":"User asked to print the current series"}
```

**Input:** `"export to PDF with annotations"`
```json
{"action":"export_pdf","entities":{"include_annotations":true},"confidence":0.9,"needs_confirmation":true,"reason":"User requested PDF export with burn-in annotations"}
```
