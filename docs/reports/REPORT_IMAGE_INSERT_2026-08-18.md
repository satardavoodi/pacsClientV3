# Captured images in the Medical Report Editor

**Date:** 2026-08-18
**Requested by:** owner, from the floor —
> "when we use Capture Screenshot and save an image, sometimes the physician
> wants to use that captured image as a key point and include it below the
> final report. Currently, in the Medical Report Editor … there is no option to
> insert those captured screenshots."

**Status:** Implemented. 47 guards in
`tests/code/reporting/test_report_image_insert.py`; 9 verified to FAIL on the
pre-fix codebase.

---

## 1. What was missing

The Patient tab's Capture tool already wrote key images to the study's
attachment folder, and the viewer toolbar's **View Captured Images** dropdown
already listed them. The Medical Report Editor (`ReportEditorDialog`, opened
from the Reception Data tab) could insert a **link, a table and a horizontal
line** — and nothing else. Verified against HEAD:

```
_insert_bullet_list, _insert_horizontal_line, _insert_link,
_insert_number_list, _insert_table
```

There was no path from a capture to the report.

## 2. What was built

### 2.1 Toolbar — four new buttons

Added to the format toolbar's **Insert** group, next to Link / Table /
Horizontal Line:

| Button | Action |
|---|---|
| **Insert Captured Image** | opens the gallery for this study |
| **Smaller** | scales the image at the cursor down 10% |
| **Larger** | scales it up 10% |
| **Fit to page width** | scales it to the full usable text width |

The three resize buttons are **disabled unless the cursor is on an image**,
driven by `cursorPositionChanged` / `selectionChanged`. They read as image
tools rather than dead controls.

### 2.2 The gallery — `CapturedImagePickerDialog`

Modal thumbnail grid, **scoped to the studies this report covers**. Captures
are stored per StudyInstanceUID (`ATTACHMENT_PATH/<study_uid>/`).

The first cut asked the report for `studyUID` / `study_uid` and stopped there.
That was wrong in practice — see §3.2 — so the scope is now resolved by
`resolve_study_uids()`: an explicit study UID when the caller has one,
otherwise a lookup from the patient identifiers against the local DICOM DB.
That can legitimately return more than one study, so the picker takes a list
and labels each thumbnail with its study when there is more than one.

* **Double-click inserts** (as requested); select + **Insert** also works.
* Newest capture first, labelled with capture time — a uuid filename tells the
  physician nothing.
* **Refresh** re-scans, so a capture taken without closing the editor appears.
* Empty state explains where captures come from.
* Thumbnails decode **4 per event-loop tick** via `QImageReader.setScaledSize`,
  not all at once. A study can hold 30+ full-resolution PNGs; decoding them in
  the constructor would block the GUI thread for seconds on this machine.

Listing deliberately mirrors `ImageAttachmentsPanel._iter_files` byte for byte —
same extension tuple, same mtime-descending order, same local/server duplicate
collapsing. A guard AST-reads `IMAGE_EXTS` out of `attachments_dropdown.py` and
fails if the two ever diverge.

### 2.3 Embedding — downscaled JPEG data URI

The chosen file is loaded, capped at **1000 px wide**, re-encoded as **JPEG
q88**, and embedded as a `data:` URI.

**Why embedded rather than a path.** The report is uploaded to INO as a single
JSON field (`POST /api/pacs/update-report`, `content`). A `file:///` src keeps
the HTML small but the image exists only on the machine that wrote it — the
referring doctor opens the report and sees a broken image, while the author's
copy looks perfect. The bytes have to travel with the report.

**Why downscaled.** Measured on a real 1920×1080 capture:

```
source PNG        224.8 KB
encoded JPEG       78.9 KB   (1000x563)
data URI in HTML  105.2 KB
```

A raw full-resolution PNG capture is typically 2–6 MB; base64 adds ~33 %. Three
of those would be a ~25 MB JSON POST. At ~105 KB per image the payload stays
sane. Diagnostic reading still happens in the viewer on the original DICOM —
this is a report illustration.

`AIPACS_REPORT_IMAGE_MAX_BYTES` (default 1.5 MB) is a hard ceiling on top. On
overshoot the encoder steps quality and then width down a fallback ladder, and
if it still cannot fit it **refuses and says so**. A visible "could not insert"
beats a report that will not save.

### 2.4 Rendering — and an honest finding

An embedded image has to survive four stages, each of which can silently eat
it: `toHtml()` (save) → `prepare_report_html_for_server()` (upload) →
`setHtml()` (reopen) → `QTextDocument.resource()` (render and print).

The design assumption was that Qt's `QTextDocument.loadResource()` cannot
decode `data:` URIs, so `install_data_uri_image_support` swaps in a subclass
that can. **Measured, that assumption is wrong on the shipped Qt:**

```
5. STOCK DOCUMENT
   stock document -> resolved 1000x563. This Qt build handles data URIs
   natively; the subclass is belt-and-braces, not the mechanism.
   Qt runtime: 6.10.2
```

Rather than delete the fallback or leave a document swap running for no
benefit, the install is now **self-limiting**: it probes once per process
(`stock_qt_resolves_data_uris()`, one throwaway document) and **does nothing**
when Qt already handles data URIs. On an older or regressed Qt the subclass
still saves the feature. So the common path carries none of the risk of
swapping a live document, and the guard test pins **behaviour** ("an embedded
image resolves to real pixels") rather than mechanism.

## 3.2 Second bug — reported from the floor after the first cut

The button opened and said **"This report is not linked to a study, so there
are no captured images to list"** for reception 54800 — a patient with a CT
study open in the viewer behind the dialog and a capture already on disk.

Root cause: a report opened from the Reception Data tab is handed
`reception_data_tab.current_data`, which is a **reception record**, not a
study. Verified shape:

```python
{"_id": "...", "receptionId": "54800", "nationalCode": "0046922229",
 "patient": {"Name": "porya mazaheri", "NationalID": "0046922229"}, ...}
```

No `studyUID`, no `study_uid` — and captures on disk are keyed by study UID.
So the check could only ever fail for a reception-opened report. It passed
review because the first implementation reused the *same* key precedence as
`_start_previous_exams_lookup`, and a guard pinned the two together — the two
agreed, and were both empty.

**The fix, and the trap in it.** Resolution now falls back to the local DICOM
DB. The join is the part worth remembering:

```sql
SELECT s.study_uid FROM studies s
JOIN patients p ON p.patient_pk = s.patient_fk
WHERE CAST(p.patient_id AS TEXT) = ?
```

`studies.patient_fk` is a **foreign key to `patients.patient_pk`**, not the
DICOM PatientID. A direct `studies.patient_fk = '54800'` returns zero rows
silently — measured, it does — which is exactly how this would come back.
`test_the_join_goes_through_the_patients_table` pins it.

Identifiers are tried **in order and the first match wins**
(`receptionId` → `ReceptionID` → `patient.PatientID` → … → `nationalCode`).
Unioning every match was rejected deliberately: a national code that happens
to collide with another patient's `patient_id` would mix a *different
patient's* key images into this report. That is a clinical error, not a
cosmetic one.

Verified against the live database
(`tools/analysis/oneoff/verify_report_study_resolution_2026_08_18.py`):

```
reception 54800 -> studyUID '' (the bug)
candidates      -> ['54800', '0046922229']
resolved        -> ['1.2.840.1.99.1.47.1.1787052434018.87326']
picker shows    -> capture_all_layouts_20260818_171507.png (305 KB)
explicit UID still short-circuits the DB   PASS
unknown patient -> []  (no cross-patient leak)   PASS
AIPACS_REPORT_IMAGE_DB_LOOKUP=0 restores old behaviour   PASS
```

Kill switch: `AIPACS_REPORT_IMAGE_DB_LOOKUP=0`.

## 3. A bug caught during development — worth recording

The first resize implementation probed for the image with a **reversed**
`QTextCursor` selection. `charFormat()` returns the format of the character
immediately *before* `position()`, so a reversed selection reads the character
on the far side of the range:

```
probe from just-after position:
  forward  isImage=False sel=[8,9]
  backward isImage=False sel=[7,8]     <- the image IS at [7,8]
```

Every resize button was wired, every handler ran, and the width never changed —
and **every structural/AST guard still passed.** A source-shape assertion
cannot see "the width never changed".

That is why the resize guards in this suite are behavioural, on real Qt
objects: `test_making_an_image_smaller_actually_changes_its_width`,
`test_repeated_shrinking_keeps_shrinking`,
`test_an_image_is_found_when_the_cursor_sits_just_after_it`. The fix probes
both candidate positions with a **forward** selection.

## 4. Deliberately NOT changed

* **No new dependency.** `QImage` (not `QPixmap`) does the scaling and JPEG
  encoding — already present, and it needs no QApplication, which keeps the
  helper headlessly testable.
* **The upload normaliser is untouched.** It already passes `<img>` through;
  the guard just pins that it keeps doing so.
* **No PDF export was added.** There is none for reports today
  (`modules/printing/` is DICOM film printing). Printing goes through
  `QTextEdit.print_`, which renders the same document, so an embedded image
  prints as shown.
* **No drag-resize handles.** `QTextEdit` has no native support; an overlay
  widget tracking the image rect is a much larger surface. The owner chose
  +/- buttons.
* **Scope is this study.** A patient-wide gallery would need a
  patient→studies lookup that does not exist in the capture store.

## 5. Risk

Moderate and contained to the report editor.

* Four new toolbar buttons and one new import in `_create_editor_area`; the
  rest is two new modules that nothing else imports.
* The data-URI document swap is a **no-op on the shipped Qt** (§2.4), so the
  live path is unchanged there.
* Every entry point is exception-proof: a failed picker, a failed encode and a
  failed install all leave the editor exactly as it was.
* **Payload growth is the real operational risk.** ~105 KB per image is fine;
  a physician inserting ten images makes a ~1 MB report. Bounded by the
  per-image ceiling but not by a per-report one — see §7.

## 6. Verification

```
tests/code/reporting/test_report_image_insert.py               68 passed
tests/code/reporting + ai_imaging + database                  340 passed, 8 xfailed
tests/code/reporting + ai_imaging + echomind                 2620 passed, 12 xfailed
```

All xfails are pre-existing quarantined entries.

**Round-trip, on a real capture** —
`tools/analysis/oneoff/report_image_roundtrip_2026_08_18.py`:

```
1. ENCODE            downscale 1920->1000, 224.8 KB PNG -> 78.9 KB JPEG (2.9x)
2. INSERT + toHtml   <img> emitted, data URI present, width=600 preserved
3. NORMALISER        img / data URI / width all survive the upload transform
4. REOPEN            setHtml round-trips; loadResource decodes to 1000x563
```

**End-to-end on the real dialog** —
`tools/analysis/oneoff/report_image_editor_smoke_2026_08_18.py`:

Run with the REAL reception shape (no study UID), not a synthetic dict:

```
btn_image exists=True enabled=True
btn_img_smaller/larger/fit exist, disabled with no image
explicit study uid : ''   (the floor bug)
resolved studies   : ['1.2.840.1.99.1.47.1.1787052434018.87326']
captures the picker would show: 1
   capture_all_layouts_20260818_171507.png
after insert -> smaller enabled: True
detected 400.0 -> smaller 364.0 -> larger 400.0 -> fit 566.0
aspect kept 0.749 (source 0.75)
toHtml keeps the image: True
```

**Pre-fix proof** —
`tools/analysis/oneoff/verify_report_image_guard_fails_prefix.py` reconstructs
HEAD with `git show` (the working tree is never touched — it carries unrelated
in-flight EchoMind work) and confirms **9 guards fail pre-fix**: both helper
modules absent, no `btn_image`, no resize buttons, no connections, no
`_insert_captured_image`, no `_report_study_uid`, no data-URI install.

## 7. Open / worth knowing

* **No per-report payload cap.** Each image is bounded (~105 KB typical,
  1.5 MB hard); a report with many images is not. If reports start failing to
  upload, a total-size check at save time is the fix.
* **Whether INO's viewer renders a base64 `<img>` is a server-side question**
  this codebase cannot settle. The bytes are transmitted intact and Qt renders
  them; the INO editor is TipTap-based and its handling of data URIs should be
  confirmed with one real upload before the feature is announced to physicians.
* **The EchoMind "send to reception" path** (`ai_chat_pages._send_to_reception`)
  uses the same endpoint and *replaces* report content. An image-bearing report
  can be clobbered by it — pre-existing behaviour, but it now has more to lose.
* **Single-study scope** by design (§4). Comparison images from priors need the
  patient→studies lookup first.
* **qtawesome cannot resolve the Windows fonts directory** under pytest here
  (`TypeError: expected str … not NoneType`, `WINDIR` unset), which is why the
  behavioural resize guards bind the dialog's methods to a stand-in instead of
  constructing the dialog. Pre-existing — the same gap quarantines
  `test_field_icon_chip`. Setting `WINDIR=C:\Windows` works around it.
