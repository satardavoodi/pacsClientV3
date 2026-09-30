# Advanced Analysis lumen workspaces

Implementation receipt: 2026-09-27. Live GUI acceptance remains pending a fresh
human-launched source session and login. No release or installer build is claimed.

## Scope and architecture

Advanced Analysis exposes **Vascular Analysis** and **Virtual Bronchoscopy**.
Both launch the existing custom Slicer runtime, selecting `AIPacsVascular` or
`AIPacsBronchoscopy`. They are subfeatures of the existing `advanced_mpr` package,
not new independently installed components. The Python 3.13 workstation does not
load Slicer's Python 3.12 native geometry bindings.

Both cold startup and the resident bridge require the exact SeriesInstanceUID
for these workflows. They select only that series and obtain its study identity
from the imported DICOM database. There is no first-patient fallback for either
specialized workflow. The generic MPR route retains its existing behavior.

Each workspace owns parameter-node references to its source volume, segmentation,
endpoints, path, surface, and measurement table. Segment Editor provides manual
and semi-assisted segmentation. A selected segment and two endpoints drive VMTK
centerline extraction; a manually supplied curve is also supported. This version
does not include a dedicated automatic airway or vessel segmentation model.

The selected label is copied from potentially shared, cropped segment labelmaps
with its physical affine. Transformed source nodes are rejected until hardened.
Native surface/centerline/section computation runs in an owned subprocess, with
file staging and result reading off the GUI thread. Cancellation terminates only
that child; generation checks discard obsolete results. Windows job ownership
also closes the geometry child when its owning process exits.

Vascular controls navigate perpendicular sections and show area, equivalent
diameter, and diameter reduction relative to a user-selected reference. This is
not an automatic NASCET measurement or a clinical validation claim. Bronchoscopy
adds first-person camera navigation, playback, speed, direction, and field of
view, alongside an external overview. Slicer Save Data saves scene artifacts.

## Native engine and packaging

VMTK source: https://github.com/vmtk/vmtk at
`d8f45c1b8c276e1aaf5e19a7ae16320b5df6b03b`.
The local successful build used VS 2022 x64, Qt 5.15.2, and the matching Slicer SDK
at `C:/S/NB`: Python 3.12.10 and VTK 9.5.2. Build VMTK with these CMake settings:

```text
VMTK_USE_SUPERBUILD=OFF
USE_SYSTEM_VTK=ON
USE_SYSTEM_ITK=ON
VTK_DIR=C:/S/NB/VTK-build
ITK_DIR=C:/S/NB/ITK-build
Python3_ROOT_DIR=C:/S/NB/python-install
Python3_EXECUTABLE=C:/S/NB/python-install/bin/PythonSlicer.exe
Python3_INCLUDE_DIR=C:/S/NB/python-install/include
Python3_LIBRARY=C:/S/NB/python-install/libs/python312.lib
Qt5_DIR=C:/Qt/5.15.2/msvc2019_64/lib/cmake/Qt5
VTK_VMTK_WRAP_PYTHON=ON
VTK_VMTK_BUILD_TETGEN=OFF
VMTK_SCRIPTS_ENABLED=ON
VMTK_TEST_DATA_SOURCE=in-place
BUILD_SHARED_LIBS=ON
```

Configure a fresh build directory, build Release, and install to a dedicated
prefix. `tools/slicer/prepare_lumen_vmtk.py --source <clean-pinned-source>
--install <prefix> --output <fresh-bundle-directory>` stages only the Common and
ComputationalGeometry DLLs/bindings, license, and a hash/ABI manifest. The current
development bundle is `generated-files/lumen-vmtk/bundle` (ignored, not committed).
`tools/slicer/probe_lumen_backend.py` exercises the actual native bindings when
run through the custom Slicer launcher's `--launch` Python path, without a GUI.

Both package materialization and release staging call `stage_lumen_vmtk`.
`AIPACS_LUMEN_VMTK_BUNDLE_SOURCE` selects the immutable cache bundle for isolated
build checkouts. Fresh distribution asset preparation now includes `lumen_vmtk`;
release staging requires its inventory and hashes. Older caches are insufficient
for these features: prepare a fresh cache using the existing BUILD.md workflow
and select it via `--asset-root`. Do not mutate a completed cache. Existing donor
reuse copies other assets but snapshots the current native viewer and VMTK bundle.
No complete fresh cache or installer was built during this task.

## Verification and outstanding acceptance

- Focused geometry, payload, materialization, current-source runtime, distribution
  profile, and runtime guards: **90 passed**.
- Existing resident bridge: **17 passed**; window promotion: **3 passed**, run
  separately to avoid incompatible Qt application fixtures.
- Actual Slicer VTK 9.5.2 native subprocess probe: **passed**, 72 path points,
  length 52.794178 mm, median cylinder area 72.000794 mm2. Synthetic data only.
- Full builder/runtime attempt timed out in the existing release gate's Git
  fetch; it is not a suite pass. Existing staged-output parity is stale in
  unrelated configuration families and was not rebuilt.
- GUI acceptance is pending. Verify both buttons after a human launches
  `run_app.ps1 -TestServer` and signs in; inspect exact source identity, selected
  segment, endpoint placement, compute/cancel, reference measurements, camera
  playback, switching workspaces, and saved-scene restoration. Do not restart an
  active clinical session or automate authentication.

Primary guards: `tests/code/mpr/test_lumen_analysis.py` and
`tests/code/builder/test_lumen_vmtk_payload.py`. Numerical synthetic checks do not
establish patient-data accuracy or usability.

## Guided seed classes (2026-09-27)

Bronchoscopy prepares Airway lumen, Lung parenchyma, and Soft tissue / background
as visible classes, plus hidden optional External air. Vascular prepares Vessel
lumen and Surrounding tissue / background, plus hidden optional Other vessels
and Bone / calcification. These are workflow defaults, not a universal required
anatomical partition. Optional classes should be enabled only when relevant.
Clicking a class selects it, makes it visible and activates Paint. Placement
instructions appear beside each class. Grow from seeds is activated for manual
preview and Apply; no automatic classification or application is claimed.

Slicer uses visible segments and requires at least two seeded classes. Hide
unused classes; after erasing seeds, cancel and initialize the preview again.
Reference: https://slicer.readthedocs.io/en/5.4/user_guide/modules/segmenteditor.html
Airway/background guidance also follows Slicer maintainer advice:
https://discourse.slicer.org/t/creating-a-3d-printable-model-of-lung-airways-using-ct-data/9675

Stable segment role tags preserve renamed targets and existing paint on reopen;
legacy lumen segments are adopted only by exact name. Computation always resolves
the tagged lumen rather than the last painted background class. No seeds or
patient anatomy are inferred merely by creating these empty classes.

Updated geometry/preset tests: 14 passed. Native Slicer segmentation-class probe
and VMTK subprocess probe both passed. Live GUI selection, painting and Grow from
seeds preview/Apply remain pending the human-launched source session.

## Compact panel revision (2026-09-27)

All four numbered steps now use the same scoped collapsible-header style,
including Source image. The seed controls use one class selector and compact
Paint action; class placement details and workflow instructions remain available
in a collapsed Seed guide and item tooltips. Optional-class semantics are
unchanged. Action rows size buttons to their text instead of stretching across
the module panel. Compute route / Cancel and Restore overview / Save scene are
paired. Defined endpoint counts and computation feedback remain adjacent to the
route actions. These changes apply to both workspaces and do not change geometry.

Existing placement, geometry and bundle guards: 20 passed; Python compilation
passed. Current open Slicer is not hot-reloaded. Visual acceptance at narrow and
wide panel sizes and a fresh-source route computation remain pending. The previous
Save scene and measurements action is now labeled Save scene and opens the same
native Save Data dialog.

## Native editor and interior lighting follow-up (2026-09-27)

The owner's latest UI instruction supersedes the custom seed selector/guide
revision above: step 2 now contains the native Segment Editor, with its
segmentation and source-volume selectors hidden through supported widget APIs.
Add, Remove, Show 3D, the segment list and native effects remain available.
Preset creation and stable target-role tags are retained; only duplicate controls
and custom seed guide/paint/grow controls were removed. Source image remains step 1.

Fly-through previously inherited external-view lighting without a dedicated
interior light. A synthetic dim-scene renderer reproduced dark inner walls before
the fix (brightness guard failed, exit 1). The first-person renderer now owns a
camera headlight and enables two-sided lighting; previous lights, switches and
renderer lighting flags are restored on overview/exit/cancel/cleanup. The reviewed
surface has explicit ambient/diffuse/specular coefficients and both-face visibility.
A renderer change restores the old light scope before attaching to the new view.
Geometry and segmentation algorithms are unchanged.

Guard: `tests/code/mpr/test_lumen_placement.py::test_flythrough_lights_interior_despite_dim_external_scene_lights`.
It renders from inside a synthetic closed surface and verifies brightness and
restoration, with no patient data. It passed in the actual Slicer VTK 9.5.2 Python
runtime as well as the workstation test selection. Live appearance on the user's
case and fresh panel layout remain pending; no current scene was hot-reloaded.
The existing next-build handoff includes the new `aipacs_lumen/lighting.py` through
its complete-package requirement. No Slicer C++ rebuild is required.

## 2026-09-27 - Recurrent dark/purple bronchoscopic interior

The owner reports that the prior headlight change remains insufficient in the real
first-person view. Do not treat the earlier synthetic sphere pass as acceptance
of the clinical scene. Review found that restoreResult bypassed all material
initialization; saved routes could retain old dark/selected/scalar-colored model
properties. The native model display manager also maintains a separate backface
material with an HSV offset. The exact dominant cause in the reported live case
is not yet established.

A restored-scene callback guard failed before this correction because no ambient
material was applied. configure_lumen_display now applies an explicit warm surface
color, neutral backface HSV offset, scalar coloring off, selected state off,
opaque double-sided display, ambient 0.55 and retained diffuse/specular shading.
Both publish and restore apply it. A compact Wall brightness control (20-80%)
allows adjusting the ambient component without changing segmentation or geometry.
The camera light is attached to the renderer owning the actual active MRML camera,
not merely the first renderer in the render-window collection.

Source selection: 22 related guards passed. Native Slicer Python/VTK checked the
real MRML material setters, restored-scene callback and interior renderer test.
The source callback failure was reproduced before the change; actual user-case
brightness/depth cues and narrow-panel UI remain pending fresh-source inspection.
Brightness is a rendering property, not optical tissue color or evidence of lesion
detection. The user's scene was not hot-reloaded, altered or restarted by this task.
