# Import Pipeline Review + Compressed-DICOM Support (2026-06-06)

Review of the Home-Page Import workflow with two real defects found and
fixed, plus decompress-on-import implemented and validated end-to-end.

## 1. Pipeline review (as-built map)

`Import tab → folder pick → _hp_import._import_folder_with_preview`:

| Stage | Where | Verdict |
|---|---|---|
| Folder/file selection | Import tab → `_import_folder_with_preview` (+ `auto_import_folder_from_startup` for CD media) | ✅ |
| DICOM detection | `scan_dicom_import_folder` → `_read_import_dicom_header`: Part-10 via `is_dicom`, vendor/extensionless via `force=True` retry, core-UID validation, DICOMDIR skipped | ✅ robust |
| Metadata reading | `specific_tags` header read (patient/study/series/instance + transfer syntax); per-file `is_compressed`; multi-patient-in-study and multi-study warnings | ✅ |
| Patient/study/series creation | scan groups by StudyInstanceUID/SeriesInstanceUID with fallbacks; `save_complete_study_info` registers patient→study→series in `dicom.db` | ✅ |
| Local storage | `import_scanned_dicom_studies` → `SOURCE_PATH/<study_uid>/<folder_key>/NNNNN_<sop>.dcm`, instance-ordered, duplicate/same-file skips. `folder_key` is normally `series_number`; duplicate numbers use the shared UID-aware collision key. | ✅ |
| Thumbnails | `_prepare_imported_study_for_fast_open` → `load_series_preview` + `save_image_as_png` per canonical `folder_key`, cache cleared | ✅ |
| Viewer compatibility | primary study opens with `viewer_backend_override=BACKEND_PYDICOM` (FAST pipeline decodes via pydicom `pixel_array`) | ⚠️ SUPERSEDED 2026-06-28 — see `IMPORT_OPENS_FAST_VIEWER_2026-06-28.md`. `BACKEND_PYDICOM` is `pydicom_2d` (the legacy **VTK**-rendering backend), NOT the FAST viewer (`pydicom_qt`). Since v2.3.3 that pin opened imported studies in the OLD VTK viewer while every other path used FAST. Decompress-on-import (§3) already stores plain uncompressed DICOM, so the pin gave no decode benefit; it is removed (default), kept behind `AIPACS_IMPORT_FORCE_LEGACY_VIEWER=1`. |
| Error handling | per-file copy errors collected; per-study DB failures listed; scan/import/prep wrapped with user-facing dialogs; background jobs run in a thread with a responsive progress dialog (QEventLoop, no processEvents poll) | ✅ |

## 2. Defects found → fixed

### D1 — Capability detector probed the WRONG module names (pre-existing)
`_detect_decoder_capabilities` checked `pylibjpeg_libjpeg` / `pylibjpeg_openjpeg`
/ `pylibjpeg_rle` — but those packages install modules named **`libjpeg` /
`openjpeg` / `rle`**. Result: with every codec installed, the import preview
still classified RLE/JPEG/J2K as *unsupported*. Fixed: probe both spellings
(`_module_available_any`). This is what the new validation suite tripped over.

### D2 — Frozen build shipped ZERO compressed-pixel codecs (ship-blocker class)
`AIPacs.spec` hiddenimports contained only `pydicom.pixel_data_handlers.numpy_handler`.
Installed builds therefore could not decode ANY compressed DICOM (J2K, JPEG
lossless/baseline, RLE) — imports and downloads of compressed studies showed
nothing, while the dev venv worked. Fixed in the spec:
- hiddenimports += `pylibjpeg_handler`, `pillow_handler`, `rle_handler`,
  `gdcm_handler`, `pylibjpeg(+utils)`, `libjpeg`, `openjpeg`, `rle`, `PIL`;
- `datas += copy_metadata(...)` for pylibjpeg + the three plugins — pylibjpeg
  discovers decoders via **entry-point metadata**, so without copy_metadata the
  frozen app imports the modules yet reports zero decoders.

## 3. Decompress-on-import (new, default ON)

Per the requirement: compressed sources are now **converted to Explicit VR
Little Endian while being copied into AI-PACS storage**
(`_decompress_file_to_destination` in `import_preview_dialog.py`):

- Only attempted when the syntax is classified decodable with the runtime's
  codecs; written via `.part` temp + `os.replace` (atomic — never a partial
  destination file).
- **Metadata preserved by construction**: the same dataset is re-saved; only
  PixelData encoding + TransferSyntaxUID change. Lossless families round-trip
  pixel-identically; lossy families store the reference decode.
- **Any failure → byte-identical copy of the original** plus a
  `conversion_warnings` entry — an import can never lose a file to a codec
  problem (`errors` stays for real copy failures).
- Benefit: imported studies never depend on runtime codecs again — viewer,
  thumbnails, pixel cache, and frozen builds all read plain uncompressed files;
  repeated opens skip per-frame decode cost.
- Escape hatches: `AIPACS_IMPORT_DECOMPRESS=0` (env wins) or
  `<USER_DATA_ROOT>/config/import_settings.json {"decompress_on_import": false}`.
- Result dict gains `converted_files` + `conversion_warnings`.

## 4. Library → compression mapping (current runtime)

| Transfer syntax | Decoder used | Installed |
|---|---|---|
| Uncompressed (ELE/ILE/EBE) | pydicom numpy handler | ✅ |
| JPEG Baseline/Extended (.50/.51 — lossy) | pylibjpeg-libjpeg (Pillow fallback) | ✅ |
| JPEG Lossless (.57/.70) | pylibjpeg-libjpeg | ✅ |
| JPEG 2000 (.90 lossless /.91 lossy) | pylibjpeg-openjpeg | ✅ |
| RLE Lossless (.5) | pylibjpeg-rle (pydicom RLE fallback) | ✅ |
| JPEG-LS (.80/.81) | pyjpegls or GDCM | ❌ not installed — correctly flagged *unsupported* in the preview; recommend adding `pyjpegls` to requirements if JPEG-LS sources appear |
| Video/other encapsulated | — | flagged unsupported, imported as original copy |

GDCM: not installed (not needed given pylibjpeg). SimpleITK/VTK: used for
rendering paths, not for import decode.

## 5. Validation (`tests/code/test_import_pipeline_dicom.py` — real encoded data)

| Case | Result |
|---|---|
| Standard uncompressed (CT_small) → copied byte-identical, no conversion | ✅ |
| RLE Lossless (MR_small_RLE) → converted, `pixel_array` identical, PatientID/UIDs/Rows/Cols preserved | ✅ |
| JPEG Lossless P14SV1 → converted, identical decode | ✅ |
| **JPEG 2000** (synthesized via openjpeg encode → real J2K codestream) → detected compressed, converted, **lossless pixel round-trip** | ✅ |
| Large series (40 instances) → all imported, instance-ordered names | ✅ |
| Multi-study folder → both studies detected + warning | ✅ |
| Non-image DICOM (RTPLAN, no PixelData) → detected, copied as-is | ✅ |
| Kill-switch env → original bytes stored | ✅ |
| Simulated codec failure → fallback copy + surfaced warning, zero hard errors | ✅ |
| Empty-caps classification (J2K unsupported / uncompressed fine) | ✅ |
| Source contracts (atomic publish, fail-open) | ✅ |

**11 passed, 1 skipped** (the *bundled* J2K sample isn't in this pydicom —
covered by the synthesized-J2K test instead). Mirrors 291/291 (files touched
are not plugin-mirrored).

## 6. Remaining notes

- **2026-08-30 identity follow-up:** Import previously used order-dependent
  duplicate names (`1`, `1_2`) while Download Manager/viewer used (`1`,
  `1__<uid8>`). Import and Local thumbnail/load projection now share the
  canonical `SeriesInstanceUID`-aware folder key and persisted `series_path`.
  See `IMPORT_DUPLICATE_SERIES_NUMBER_IDENTITY_2026-08-30.md`.

- JPEG-LS support: add `pyjpegls` to requirements + spec if such sources are
  expected (detector already probes for it).
- `shutil.copy2` for non-converted files is not atomic (pre-existing; an
  interrupted import could leave one partial original-copy — rerun skips
  completed files). Low risk; could adopt the `.part` pattern later.
- The D2 spec fix takes effect at the **next frozen build** — until then,
  installed apps still can't decode compressed studies (decompress-on-import
  shields newly-imported ones once a fixed build is out).
