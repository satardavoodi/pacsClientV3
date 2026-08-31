# AI-PACS DICOM Compatibility Repository Map

Read this before tracing a study. It is a routing map, not proof that every listed path supports every IOD.

## Verified local runtime baseline

- Python: repository `.venv`, supported version 3.13.5.
- pydicom: 2.4.5, using the legacy `pixel_data_handlers` API.
- SimpleITK: 2.5.3.
- VTK: 9.6.1.
- NumPy: 2.4.4.
- Available pydicom handlers in the inspected development environment: NumPy, Pillow, pylibjpeg and native RLE.
- GDCM and JPEG-LS handlers were not available through pydicom in that environment.
- Declared codec dependencies include `pylibjpeg`, `pylibjpeg-libjpeg`, `pylibjpeg-openjpeg`, and `pylibjpeg-rle`.

Re-measure these values in the environment under test. Do not assume the development environment and packaged application are equivalent.

## End-to-end flow

```text
PACS socket download or local import
        |
        v
local DICOM storage + SQLite identity
        |
        +--> thumbnail/displayability classification
        |
        +--> Fast Viewer: pydicom/NumPy/Qt
        |
        +--> Advanced Viewer: SimpleITK/GDCM -> ITK -> NumPy -> VTK
        |
        +--> dedicated modality/VTK modules where explicitly routed
```

Transport compression is not necessarily DICOM transfer-syntax compression. The socket download path can use gzip for transport while the DICOM payload keeps its own transfer syntax.

## Import, identity and storage

- `PacsClient/importer/import_preview_dialog.py`: scans and groups local imports by Study Instance UID and Series Instance UID; current work also identifies pixel-bearing instances, Number of Frames and collision-aware storage keys.
- `PacsClient/utils/dicom_displayability.py`: current uncommitted work classifies Pixel Data, Float Pixel Data and Double Float Pixel Data without turning metadata-only objects into image cards.
- Local import currently defaults to decompressing supported compressed instances and writing Explicit VR Little Endian. Failed decompression preserves the original instance.
- Codec capability checks in the import UI are currently based partly on module imports. That is not sufficient evidence that the active pydicom version and handler can decode a particular transfer syntax.
- The current import warning text can imply originals are always imported unchanged even while decompression-on-import is enabled. Treat UI wording and actual storage behavior as separate evidence.
- Compare original and stored instances before investigating a renderer. Confirm SOP identity, transfer syntax, payload kind, frame count, file length/hash and decode outcome locally.

## Fast Viewer

Primary paths:

- `modules/viewer/fast/lightweight_2d_pipeline.py`: pydicom-to-NumPy image pipeline, caches and frame selection.
- `modules/viewer/fast/dicom_header_scan.py`: header-only inventory.
- `modules/viewer/fast/decode_service.py`: background/process decode support.
- `modules/viewer/fast/dicom_color.py`: YBR normalization and color conversion.
- `modules/viewer/fast/multiframe_geometry.py`: shared/per-frame functional groups and frame geometry.
- `modules/viewer/fast/cine_metadata.py` and `cine_player.py`: cine timing and playback.
- `modules/viewer/fast/qt_fast_container.py`: Qt host and mode integration.

Current behaviors and review points:

- A multiframe instance is expanded into frame-level slice metadata and keyed by file plus frame index.
- Dataset caching avoids repeatedly reading the whole file for every frame.
- The subprocess decoder is not frame-index aware, so the main pipeline disables that path for multiframe instances.
- Functional-group parsing handles shared/per-frame plane position, orientation, pixel measures and frame content, then classifies spatial, temporal, multi-stack and multi-dimensional layouts.
- YBR subsampling normalization occurs before `pixel_array`, followed by YBR-to-RGB conversion.
- The multiframe metadata probe is optimized around a one-file series; explicitly test series containing multiple multiframe instances or concatenations.
- `_DERIVE_STACK_GEOMETRY` has a comment/default mismatch in current code. Treat it as a baseline risk and do not change it without a reproducer and regression guard.

Fast Viewer must not instantiate or import VTK runtime objects.

## Advanced Viewer

Primary paths:

- `PacsClient/pacs/patient_tab/utils/image_io.py`
- `PacsClient/pacs/patient_tab/utils.py`
- advanced-viewer geometry and series-loading helpers referenced by `docs/INDEX_BY_SUBSYSTEM.md`.

The main volume path uses SimpleITK/GDCM, then converts ITK data to NumPy and VTK under repository-specific canonical ordering and geometry contracts. SimpleITK requires a correctly acquisition-direction-sorted file list; do not assume natural filename order is sufficient. Test both the repository's canonical sort and any backend-specific series discovery.

## Objects that need explicit routing

No general product renderer was found in the inspected paths for:

- DICOM Waveform Sequence objects such as ECG and hemodynamic waveforms;
- encapsulated documents and encapsulated video;
- non-raster ophthalmic measurements or maps that require specialized coordinates/calibration;
- arbitrary non-pixel composite IODs.

Preservation, classification, decoding and rendering are separate capabilities. Never claim rendering support solely because `dcmread()` succeeds.

## High-value regression guards

- Import/identity: `tests/code/test_dicom_import_preview.py`, `test_local_offline_contract.py`, `test_series_number_collision.py`, `test_flat_folder_import.py`.
- Codecs/build: `tests/code/test_codec_bundling.py`, `test_import_header_only_reads.py`, `test_import_pipeline_dicom.py`.
- Multiframe/cine: `tests/code/test_fast_multiframe.py`, `test_multiframe_geometry.py`, `test_multiframe_derived_stack_geometry.py`, `test_multiframe_ds_cache.py`, `test_cine_playback.py`.
- Color/window: `tests/code/test_dicom_color_decode.py`, `test_ybr_color_decode.py`, `test_mg_window_placeholder.py`, `tests/code/fast/test_per_instance_window.py`.
- Geometry/boundaries: `tests/code/test_canonical_series_sort.py`, `test_pydicom_backend_geometry.py`, `test_series_geometry_index.py`, `tests/code/architecture/test_backend_geometry_boundary_guards.py`.

Locate exact current paths with `rg --files tests | rg '<name>'` before invoking pytest.

## Package mirrors

Fast Viewer files have mirrors under:

`builder/plugin package/packages/viewer/payload/python/modules/viewer/fast/`

When a mirrored source changes, use `tools/dev/sync_plugin_mirrors.py`, verify with `tools/dev/verify_plugin_mirrors.py`, and run the builder/runtime parity guards required by `CLAUDE.md`.
