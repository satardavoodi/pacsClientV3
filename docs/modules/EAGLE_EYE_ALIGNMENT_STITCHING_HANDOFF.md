# Stitching to Eagle Eye Alignment handoff review

Reviewed 2026-09-17. Source audit and a synthetic export/load probe only.
No runtime changes, patient data, clinical validation or live GUI acceptance.

## Current path and confirmed incompatibility

- Patient entry: `_pw_advanced.py::_launch_stitching_async` supplies the available
  series to `StitchingWidget.launch_with_series`; no explicit immutable study
  ownership contract is passed into a completed result.
- `StitchWorker.run` resamples and blends a chain into a float32 `sitk.Image`.
  `_on_worker_completed` retains it as `_stitched_sitk`. The completed signal
  carries the image, not source SOP identities, transforms or calibration evidence.
- Full computation and Quick Preview are separate. Preview caps the longest side,
  skips the residual pause gate and never replaces `_stitched_sitk`.
- `_export_as_dicom` writes Secondary Capture, Modality OT, new Study/Series/SOP
  UIDs, MONOCHROME2 uint16, and row/column spacing swapped correctly from SITK.
  It does not propagate patient/examination attributes or SourceImageSequence.
  Its image orientation is hard-coded, not established patient geometry.
- Alignment `service.load_image` requires the selected Study UID, optional Series
  UID, DX/CR, monochrome single-frame pixels, complete instance identity and an
  80-million-pixel size bound. `study_images` also discovers only DX/CR.
- `eagle_eye_workspace.open_alignment` creates a study-owned widget and scans the
  existing inventory. There is no public stitched-artifact import route.

Synthetic probe: a 20 x 20 float32 ramp with SITK spacing (0.2, 0.3) exported as
OT with DICOM spacing (0.3, 0.2), no patient ID and no source references. Loading
under the original synthetic study was rejected for study mismatch; loading
under the exported study was rejected for modality. Pydicom also warned that
the declared explicit VR differed from the detected implicit encoding. This
warning needs exporter-owner verification; it was not silently repaired here.

## Proposed user workflow

Select exact source radiographs -> place stitching landmarks -> Compute Stitching
-> review full result/seams -> **Analyze in ELA Alignment** -> review upright AP,
coverage and laterality -> suggest alignment points -> manual correction -> PDF.

The new button must refer to a completed full-result revision, not Quick Preview.
Changing inputs, pair landmarks, transform options or restarting computation
invalidates eligibility until a new full result completes. The current completed
image can remain visible as a previous result, but must not masquerade as current.
Closing Stitching after successful transfer must not invalidate Alignment's copy.

## Immutable artifact contract

Use an owner-approved, identity-keyed derived-artifact path through the existing
shared trunk. Do not pass the mutable SITK object, VTK viewer, interactor or
Stitching widget into Alignment. Do not create another catalog/coordinator.

The Stitching owner publishes a private, atomic result bundle in a background job:

- A derived monochrome DICOM, with the verified original Study UID and patient
  context; new Series/SOP UIDs identify the derived image. Preserve correct SC/OT
  semantics rather than relabeling it DX merely to bypass the current loader.
  Validate all selected sources against the intended examination before blending.
- A versioned manifest: artifact ID/revision, pixel/file hashes, ordered exact
  source Study/Series/SOP/frame identities, source calibration evidence, output
  shape, spacing/aspect, origin/direction in their declared coordinate system,
  transform types/parameters/composition, residuals and any operator override,
  blend version, full-versus-preview state and review status.
- Preserve original source lineage across intermediate virtual stitches. A local
  generated Series UID cannot replace the identities of the constituent images.
- Do not invent patient 3D orientation from the 2D stitching canvas. Distinguish
  canvas coordinates from verified DICOM patient orientation and calibration.

Alignment receives only a descriptor through a public adapter, validates identity,
hash, revision, source type and bounds off the GUI thread, then creates its own
pixel array. Add a narrowly scoped derived-Stitching loader; retain generic OT
rejection for ordinary input. The primary-series selector must show the derived
series explicitly and must not accidentally rescan/select an original fragment.
Reuse current AI, editable landmarks, measurements, reference context and PDF
generation after import. Preserve the manifest as report provenance. An existing
edited Alignment session must not be overwritten silently.

Local analysis does not itself require PACS publication. Catalog registration or
thumbnail presentation is a separate Unify-owned integration, if needed.

## Geometry is an acceptance condition

The UI defaults to Similarity; the worker API defaults to Affine. Rigid preserves
local lengths and angles, similarity adds scale, and affine permits anisotropic
scale/shear. Different segment transforms can affect whole-limb geometry even if
each local match looks good. A low landmark residual is not proof of measurement
accuracy. Record transforms and validate their clinical applicability rather than
automatically treating a blended image as calibrated.

PixelSpacing on the exported canvas is not evidence of patient-plane calibration.
Keep absolute lengths uncalibrated unless source/transform calibration is verified.
The existing percentage LLD cancels only a common scale; independent segment
scales, differential magnification, stitching distortion and positioning remain.
Use an explicit uncertainty/review state for affected metrics. The simple first
measurement workflow should prefer rigid registration with verified acquisition
geometry; scaled/affine outputs require additional validation before quantitative
acceptance. A global ruler alone cannot repair arbitrary local deformation.

## Additional owner findings

Stitching currently keys loaded/virtual images by displayed series number and the
loader selects a series from a directory, with middle-slice fallback. These are
not sufficient exact SOP/frame selection for this handoff. Also, loading and DICOM
export are invoked synchronously from widget slots; keep future adapter I/O off
the GUI thread. Old result invalidation on selection/landmark/transform changes
needs coverage before enabling the new button. These are findings, not fixes.

Owner routing follows the boundary agreement section 0.2:
[VTK/Stitching owner](../reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md)
owns decode, geometry, export and native lifecycle;
[Unify owner](../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md)
owns shared identity/artifact registration and invalidation contracts.
The ELA owner implements its public artifact adapter and report provenance after
the producer contract is agreed. No other owner's code or mirrors changed here.

## Required acceptance for implementation

Synthetic three-part radiograph with known geometry and expected recovered angles,
lengths and percentage; anisotropic spacing and calibration cases; similarity and
affine distortion cases; exact source identity and mismatched-study rejection;
duplicate series-number inputs; multi-stage lineage; full/preview and stale-result
rejection; cancellation/close without cross-domain interference; export VR validity;
artifact hash integrity and PDF provenance. Then a fresh-source real mouse workflow
from Stitching through manual point correction and PDF, with clinician comparison
to independent landmarks. Software guards and a clinically validated stitch are
separate acceptance results.
