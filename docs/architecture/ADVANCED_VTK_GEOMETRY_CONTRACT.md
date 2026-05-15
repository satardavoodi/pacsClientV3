# Advanced VTK Geometry Contract

## Goal

Advanced VTK now has a single ordering and geometry authority for slice display and per-slice metadata:

`raw DICOM files -> minimal header read -> SeriesGeometryIndex -> SimpleITK file order + metadata['instances'] + sync/reference mapping`

The contract is built around DICOM LPS coordinates:

- `+X = Left`
- `+Y = Posterior`
- `+Z = Superior`
- `row_cosines = IOP[0:3]`
- `col_cosines = IOP[3:6]`
- `slice_normal = cross(row_cosines, col_cosines)`
- `slice_pos = dot(IPP, slice_normal)`

## Authority

The sole Advanced ordering authority is `SeriesGeometryIndex` in [PacsClient/pacs/patient_tab/utils/advanced_geometry_contract.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/PacsClient/pacs/patient_tab/utils/advanced_geometry_contract.py).

It is a frozen dataclass that stores:

- `series_uid`
- `study_uid`
- `modality`
- `body_part`
- `laterality`
- `patient_position`
- `plane`
- `row_cosines`
- `col_cosines`
- `slice_normal`
- `sorted_instances_geometry_order`
- `display_instances_order`
- `dicom_files_for_itk`
- `sop_uid_by_display_index`
- `ipp_by_display_index`
- `iop_by_display_index`
- `display_order_hash`
- `geometry_order_hash`
- `first_display_label`
- `last_display_label`
- `display_convention`
- explicit display/geometry index maps

## Pipeline

### Builder

`build_series_geometry_index()` reads actual DICOM files, validates a single `SeriesInstanceUID`, computes geometry from IOP/IPP, sorts by `dot(IPP, normal)`, applies an explicit display convention, and freezes the result.

### Display convention

The builder applies one explicit Advanced display convention:

- `AXIAL` body imaging: `Superior -> Inferior`
- `AXIAL` joint/extremity with detectable superior-axis semantics: `Proximal -> Distal`
- `SAGITTAL`: `Right -> Left`
- `CORONAL`: `Anterior -> Posterior`
- `OBLIQUE`: preserve geometry order and log classification

### Runtime consumption

Advanced load now uses the geometry index for all of these:

- `SimpleITK` file order via `geometry_index.dicom_files_for_itk`
- `metadata['instances']` via `geometry_index.display_instances_order`
- display index to SOP/IPP/IOP mapping
- reopen/cache consistency via serialized geometry-index cache

## Files Changed

- [PacsClient/pacs/patient_tab/utils/advanced_geometry_contract.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/PacsClient/pacs/patient_tab/utils/advanced_geometry_contract.py)
- [PacsClient/pacs/patient_tab/utils/image_io.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/PacsClient/pacs/patient_tab/utils/image_io.py)
- [PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_sync.py)
- [PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py)
- [PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py)
- [tests/viewer/test_canonical_series_sort.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/tests/viewer/test_canonical_series_sort.py)

## Old Ordering Paths Removed From Advanced

These are no longer part of the Advanced load authority:

- `canonical_sort_instances()` in the Advanced filesystem load branch
- `canonical_sort_instances()` in the Advanced DB/reopen load branch
- `apply_advanced_display_convention()` in the Advanced filesystem load branch
- `apply_advanced_display_convention()` in the Advanced DB/reopen load branch
- post-backfill Advanced re-sort in the DB path
- post-load `_normalize_metadata_instances()` on geometry-index-backed metadata

These functions remain for legacy or FAST-only behavior:

- `canonical_sort_instances()`
- `apply_advanced_display_convention()`
- `reference_line.rl_sort_instances_by_ipp()`

## Old Ordering Paths Guarded

These paths now refuse to mutate geometry-index-backed Advanced metadata:

- `_PWSyncMixin._ensure_instances_sorted_for_geometry()`
- `_VCCacheMixin._refresh_stored_metadata_instances()`
- `_VCCacheMixin._sync_viewer_metadata_instances()`
- `ViewerController._load_single_series_on_demand()` empty-instance repair
- metadata cache normalization in `_get_cached_metadata()`

If any code mutates finalized Advanced metadata order, `assert_advanced_order_contract()` logs and raises:

- `[ADVANCED_ORDER_CONTRACT_ERROR]`

## Diagnostics

Each Advanced geometry build emits one structured line:

- `[ADVANCED_SERIES_GEOMETRY_INDEX]`

It includes:

- patient code
- study UID
- series UID
- series number
- instance count
- plane
- modality
- body part
- laterality
- patient position
- row cosines
- col cosines
- slice normal
- geometry hash
- display hash
- display convention
- first/last display SOP
- first/last display IPP
- first/last display labels
- source
- cache hit flag

It also emits warnings for mixed-plane or mixed-orientation series:

- `[ADVANCED_SERIES_GEOMETRY_WARNING]`

## Validation

Validated with:

- [tests/viewer/test_canonical_series_sort.py](e:/ai-pacs/ai-pacs%20codes/ai-pacs%20beta%20version/tests/viewer/test_canonical_series_sort.py)

Focused results:

- filesystem and DB input order produce identical geometry/display hashes
- reopen reproduces identical display hash
- axial abdomen starts `Superior`
- axial knee starts `Proximal`
- sagittal starts `Right`
- SimpleITK order equals display order
- `metadata['instances']` equals display order
- mixed `SeriesInstanceUID` raises
- mixed plane/orientation logs warning
- finalized Advanced metadata mutation raises contract error

## Runtime Examples

A real-patient runtime capture was not run in this implementation pass, so no new production patient log excerpt is included here.

Expected runtime line shape:

```text
[ADVANCED_SERIES_GEOMETRY_INDEX] patient_code=... study_uid=... series_uid=... series_number=... n_instances=... plane=AXIAL modality=CT body_part=ABDOMEN laterality= patient_position=HFS row_cosines=(...) col_cosines=(...) slice_normal=(...) geometry_order_hash=... display_order_hash=... display_convention=AXIAL_SUPERIOR_TO_INFERIOR first_display_sop_uid=... last_display_sop_uid=... first_display_ipp=(...) last_display_ipp=(...) first_display_label=Superior last_display_label=Inferior source=db cache_hit=True
```

## Remaining Work

The load authority is now unified. The remaining follow-up is operational validation on real patients for:

- axial abdomen
- axial joint
- sagittal knee
- coronal series

That runtime validation should confirm the emitted geometry-index logs and any downstream MPR/reference-line assumptions still tied to legacy metadata access.