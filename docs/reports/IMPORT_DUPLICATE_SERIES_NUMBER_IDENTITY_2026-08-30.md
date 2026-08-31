# Imported Duplicate-Series-Number Identity Fix (2026-08-30)

## Status

Implemented and regression-tested in the source build. The affected source
study was also decoded headlessly through the production FAST pipeline. Live UI
validation is still required; no installed executable or release build was
launched.

## Incident shape

One imported ultrasound study contained two image series with distinct
`SeriesInstanceUID` values but the same DICOM `SeriesNumber`. One was a still
series and the other was a lossy multi-frame cine series. Both pixel payloads
decoded successfully, including the cine frames, so codec support was not the
root cause.

The Home page could show one thumbnail, but the Patient tab omitted the other
series. The defect was series identity, not cine rendering.

The first live follow-up exposed a second, related failure. The sidebar showed
three cards, but two opened as black one-slice viewports. A header and log audit
showed four DICOM groups in the imported study:

- a 25-instance still-image series;
- a two-instance lossy cine series containing 424 decodable frames;
- two metadata-only DICOM groups with no Pixel Data.

Only the first two are image-viewer series. The metadata-only objects must stay
preserved on disk, but they must not become thumbnail cards or viewer loads.

## Root cause

The Import copier grouped correctly by `SeriesInstanceUID`, but assigned
duplicate storage folders using an order-dependent convention:

```text
<study>/1/
<study>/1_2/
```

Download Manager and the viewer already shared a different deterministic
collision contract:

```text
<study>/1/
<study>/1__<uid8>/
```

Import preparation then derived both thumbnail/load requests from the raw
`SeriesNumber` and targeted `1.png` plus `<study>/1`. The first thumbnail caused
the second series to be skipped. Local SQLite projection also omitted the
persisted `series_path`, so both rows collapsed back to the same raw number.

The follow-up had two additional causes:

1. Import scan incremented `image_count` for every readable DICOM object,
   including SR and vendor metadata objects with no Pixel Data. FAST therefore
   synthesized a one-slice pipeline and repeatedly logged that no pixel element
   was present.
2. Thumbnail count persistence updated SQLite by `(study_uid, series_number)`.
   Because both real image series were numbered `1`, the cine count overwrote
   both rows. A stale Local database could consequently report the still series
   as two images even though its folder contained 25 instances.
3. The Local thumbnail card used the collision-aware storage folder (`1_2`) as
   its drag payload. Both Fast and VTK viewport drop parsers require a numeric
   display handle, so the drop was silently rejected before any decoder ran.
4. The database metadata projection omitted both `SamplesPerPixel` and
   `NumberOfFrames`. A colour `Rows x Columns x 3` still frame was therefore
   mistaken for a grayscale multi-frame array and reduced to `Columns x 3`,
   producing the reported black frames. The same omission left a two-object
   cine at two slices instead of its full 424-frame stack.

## Canonical contract

| Field | Meaning | Rule |
|---|---|---|
| `series_uid` | Clinical series identity | `SeriesInstanceUID`; authoritative and globally unique. |
| `series_number` | DICOM display/order metadata | Preserve exactly; it is not unique inside a study. |
| `folder_key` | Study-local storage/load/thumbnail key | Normally the raw number; on collision use `resolve_series_folder_key`. |
| `series_path` | Persisted local byte location | Authoritative for an already-imported/local series; its final component is the persisted `folder_key`. |
| `display_key` | Thumbnail/drag/viewer-map handle | Always a digit string. A collision loser receives a deterministic reserved-band alias; it never replaces the DICOM number or folder key. |
| Thumbnail filename | Disk cache identity | `<THUMBNAIL_PATH>/<study_uid>/<folder_key>.png`. |

The common unique-number case remains byte-identical. No DICOM tag is rewritten
to manufacture uniqueness.

## Implementation

1. `import_preview_dialog.import_scanned_dicom_studies` now computes every
   folder with the existing shared `resolve_series_folder_key` authority and
   records both `series_path_name` and `folder_key`.
2. `_prepare_imported_study_for_fast_open` loads the exact folder key and writes
   a separate PNG for each collision member.
3. `database.manager.get_study_info_with_series` now returns the already-present
   `series.series_path` column.
4. Home Local and Patient-tab Local projections derive `folder_key` from that
   persisted path through `persisted_series_folder_key`, while retaining the raw
   series number for display.
5. `allocate_series_display_keys` assigns a deterministic digit-only UI handle.
   The canonical collision member keeps the raw number; other members use an
   available `900001..999999` alias. The Patient-tab map, card widget, and drag
   payload use this handle, while `folder_key` remains the disk identity.
6. Local/Import viewer opens reconcile SQLite series before accepting a partial
   PNG cache. For an older import, a missing PNG is rebuilt from the exact
   persisted series folder on the existing worker path, then rendered and loaded
   without contacting PACS. If local decode fails, the established clickable
   placeholder remains the fail-safe.
7. Import scan now records `instance_count` separately from pixel-bearing
   `image_count`, plus `frame_count` and `has_pixel_data`. It discovers the pixel
   element while reading only the header boundary; compressed cine payloads are
   not materialized or decoded during classification.
8. Local projections inspect the persisted series directory on their existing
   worker path. Pixel-bearing folders are projected with their real local file
   count; metadata-only folders are excluded from the image viewer. Their DICOM
   files and database rows are not deleted.
9. Count persistence now targets the immutable `SeriesInstanceUID` when it is
   available. Raw `SeriesNumber` remains only a compatibility fallback, so one
   duplicate-number member cannot overwrite another.
10. `SeriesRef` now carries a separate `storage_key`. A numeric display alias
    resolves to the original DICOM number for identity/DB work and to the exact
    suffixed folder key for the legacy disk loader. This prevents the authority
    layer from reconstructing `<study>/1` when the requested cine lives in
    `<study>/1_2`.
11. Local pixel inventory records both pixel-bearing object count and total
    frame count. Completeness remains object-based, while the card can show the
    viewport frame count (424 for this cine) without making the downloader think
    422 files are missing.
12. FAST decode refreshes `SamplesPerPixel`, colour state, and photometric data
    from the decoded DICOM dataset before deciding whether an array is colour or
    multi-frame. A cached `Rows x Columns x 3/4` array also repairs incomplete
    metadata on cache hit. Until those per-file facts are authoritative,
    background prefetch stays on the in-process dataset-aware decoder rather
    than the metadata-trusting subprocess path.
13. Legacy metadata with no `NumberOfFrames` probes the first object. If it is
    multi-frame, every object in that cine is probed and expanded with its own
    frame count. Ordinary multi-file CT/MR pays one small header read, not an
    O(N) scan.
14. The instance header stub now carries `NumberOfFrames`, `SamplesPerPixel`,
    and `PlanarConfiguration` so newly rebuilt metadata does not need the legacy
    fallback.

## Compatibility and boundaries

- FAST cine expansion and colour classification changed only where metadata is
  incomplete; authoritative metadata and ordinary single-frame behavior remain
  unchanged.
- Decompress-on-import remains unchanged. Decodable lossy data may be stored as
  Explicit VR Little Endian according to the existing import policy.
- Server/download traffic remains on its existing socket/download paths.
- Local mode remains a hard offline boundary.
- Ordinary multi-study offset keys remain unchanged. A collision alias is first
  allocated below one million and then receives the existing per-study offset;
  its `SeriesRef` retains the raw number and exact storage folder independently.
- No database schema migration was required; `series_path` already existed.
- Non-pixel DICOM objects remain imported and available for future dedicated
  SR/document handling; this change only prevents the 2-D image viewer from
  claiming that they contain renderable pixels.

## Local cached-card follow-up

The first live source-build validation exposed a second identity leak before the
authoritative Local projection completed. `pipeline_manager` synchronously
rendered existing thumbnail PNGs and used each filename stem as the card and
drag handle. For a duplicate-SeriesNumber study, the canonical storage key
`1_2` therefore escaped into the display layer. Python accepts underscores in
integer strings, so the FAST drop parser silently converted `int("1_2")` to
`12` and requested a non-existent Series 12. The same early card for storage key
`1` occupied the deduplication slot before the projected 25-object entry arrived,
leaving the still-series count stale.

Local startup now uses the cached PNG inventory only to preserve pipeline
control flow; it does not render those storage stems as cards. The background
SQLite/disk projection remains the only Local authority that creates cards, so
it supplies the digit-only `display_key`, exact `folder_key`, object count, and
frame count together. The FAST custom-MIME parser also rejects any value that is
not an optional minus sign followed by decimal digits before calling `int()`.
This is a defensive boundary: storage keys can no longer be reinterpreted as
numeric display handles even if a future producer leaks one.

## Regression guards and verification

The original Import guard was first run against the old code and failed because it
observed `5_2` where the shared authority required `5__<uid8>`. The partial
Local-cache guard also failed before the Local reconciliation change.

The follow-up behavioral guard was also run before implementation and failed:
the non-pixel DICOM group had no `instance_count` distinction and was counted as
one image. After the change it remains one imported DICOM object but reports
zero displayable image instances.

The new guards were run before implementation and failed for the intended
reasons: missing numeric allocator, collapsed `(Columns, 3)` colour decode,
missing frame inventory, and a two-object cine expanding to only two slices.
They pass after the fix. The affected source data now produces 25/25 correctly
shaped still frames and expands two cine objects to 424/424 frames; first/last
cine probes decode with the expected dimensions.

Two additional behavioral guards were also demonstrated red before the cached-
card follow-up: Local startup rendered one cache stem directly, and the FAST
drop parser returned Series 12 for `1_2`. Both pass after the correction.

Covered suites:

- `tests/code/viewer/test_dicom_import_preview.py`
- `tests/code/ui_services/test_local_offline_contract.py`
- `tests/code/download_manager/test_series_number_collision.py`
- `tests/code/viewer/test_fast_multiframe.py`
- `tests/code/viewer/test_cine_playback.py`
- `tests/code/viewer/test_dicom_color_decode.py`
- `tests/code/viewer/test_series_ref_authority.py`
- `tests/code/ui_services/test_patient_study_set.py`

## Required live validation

Using the source build and a disconnected network:

1. Restart the source build, open the already-imported study from Local, and
   confirm exactly two image cards exist. Both may display the raw label
   `Series 1`; their storage keys remain distinct internally.
2. Select the still card and confirm all 25 instances load.
3. Select the cine card and confirm both multi-frame objects load and playback
   traverses the cine frames.
4. Confirm the former metadata-only Series 2/Series 4 black cards are absent.
5. Re-import the source folder; confirm both canonical PNGs are generated and
   reopening the study still shows both cards.
6. Open a normal unique-number study and a multi-study patient to confirm their
   ordering and load behavior are unchanged.

## Live validation result

On 2026-08-30, the human operator confirmed the reported workflow in the source
build now works correctly: the pre-existing still series is displayed again
with its 25-image count restored, and the duplicate-number cine series renders
its images after selection/drag. This closes the live gate for the original
Local/Fast regression and confirms that the cached-card follow-up did not trade
the working cine path for a broken still-series path.

This confirmation is intentionally limited to the reported source-build
workflow. Re-import validation, an explicitly disconnected-network repetition,
the normal unique-number/multi-study comparison, packaged-runtime validation,
and release readiness remain separate gates. Do not validate by launching a
second application instance.
