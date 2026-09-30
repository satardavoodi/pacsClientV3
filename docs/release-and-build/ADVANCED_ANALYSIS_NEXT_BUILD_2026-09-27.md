# Advanced Analysis: mandatory next-build handoff

Owner request: 2026-09-27. Status: **pending inclusion and artifact acceptance**.
This is an inclusion checklist under BUILD.md, not a new build or release route.
The completed September 26 installers do not contain this later work. Do not
mark this handoff complete based on source tests or mirror verification alone.

## Required scope

- Two Advanced Analysis entry points: Vascular Analysis and Virtual Bronchoscopy.
- Shared custom Slicer runtime with separate Python workspace modules.
- Prepared seed classes, stable lumen identity, and preserved segmentation.
- Correct owned-line endpoint placement (not generic fiducials), defined-point
  counter, and computation feedback beside the button.
- Compact panels: four matching step headers, seed selector/Paint, collapsed
  guide, and compact Compute/Cancel and overview/save action rows.
- Isolated VMTK geometry worker with cancellation, sections, and camera navigation.

Implementation and limitations:
[lumen workspaces](../modules/ADVANCED_ANALYSIS_LUMEN_WORKSPACES.md).
Failure evidence and outstanding live gate:
[VTK owner record](../reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md).

## Native build decision

**Do not rebuild the custom Slicer C++ core for these Python/UI changes.** Reuse
the verified native baseline and its provenance. VMTK is a separate compiled
dependency, already built locally against Slicer Python 3.12 / VTK 9.5.2 x64.
Its DLLs, Python bindings and license must accompany the new Python modules.
Changing the native Slicer source or Python/VTK ABI requires a fresh compatibility
assessment; existing VMTK binaries must not be carried across an incompatible ABI.

## Before capturing the next immutable candidate

- [ ] Preserve unrelated work and complete the authorized source/release gates.
  Include these new files in the candidate; untracked developer files are not
  evidence that a published source snapshot contains them.
- [ ] Include `PacsClient/.../patient_widget_core/_pw_advanced.py`, the updated
  `modules/mpr/advanced_3d_slicer` launcher/startup/presentation/background runtime,
  `workflows.py`, `slicer_modules/AIPacsVascular.py`,
  `slicer_modules/AIPacsBronchoscopy.py`, and all `slicer_modules/aipacs_lumen/*.py`.
- [ ] Include `builder/lumen_vmtk_payload.py`, both staging integrations, the
  advanced_mpr package definition, updated distribution asset preparation,
  `tools/slicer/prepare_lumen_vmtk.py`, the native probe, and lumen guards.
- [ ] Synchronize the advanced_mpr Python mirrors with the supported sync tool;
  verify all relevant payload/source pairs without overwriting other workstreams.
- [ ] Verify the local VMTK bundle at `generated-files/lumen-vmtk/bundle`.
  This ignored binary directory is **not supplied by a Git checkout**. On another
  builder, securely provision the verified bundle or reproduce the pinned build
  documented in the implementation receipt. Preserve its hash manifest and license.
- [ ] Prepare a **fresh immutable distribution asset cache** using the existing
  BUILD.md preparation workflow. It must contain `lumen_vmtk/manifest.json` and
  every DLL/PYD/license listed there, as well as the current Slicer baseline.
  Do not modify a completed cache. The historical default
  `distribution-assets-native-3.6.7-vc143-20260923` lacks this new dependency;
  explicitly supply the newly prepared cache with `--asset-root`.
- [ ] Confirm staging takes VMTK from that cache through
  `AIPACS_LUMEN_VMTK_BUNDLE_SOURCE`. Canonical release staging uses
  `verify(..., require_lumen=True)` and must fail if the bundle is missing,
  damaged, incompletely inventoried, or incompatible. Never bypass this gate.
- [ ] Run the placement, geometry and bundle guards and native Slicer Python
  probe. Record exact commands, exit codes and candidate source/asset receipts.

## Required output checks

The scope applies wherever advanced_mpr is included: Standard Client,
ARM64-emulated Client, and Eagle Eye Server desktop, for both PyInstaller and
Nuitka. Build only the role group authorized under BUILD.md; this checklist does
not authorize an extra role or a build now. Existing Server qualification gates
remain in force. Shared source tests do not count as six installer acceptance runs.

- [ ] Inspect each applicable staged/installed advanced_mpr payload for both
  workspace modules, the complete lumen package, matching launcher companions,
  and the verified `lumen_vmtk` bundle. Match their hashes to candidate inputs.
- [ ] In the authorized acceptance workflow, verify both entry buttons and
  exact-series loading; compact headers and controls at narrow/wide panel sizes;
  seed selection and preservation; two placed route points counted as 2/2;
  Compute/cancel and readable failures; vascular section navigation;
  bronchoscopy Position/Play/overview; scene save/reload and close/reopen.
- [ ] Record acceptance separately for each produced artifact with path/hash,
  edition/backend, date and result. Keep any unbuilt or untested cell pending.
- [ ] Link the completed candidate/artifact receipt here and in its release
  record before marking this handoff complete.

Current evidence: 20 related source tests passed; native synthetic VMTK and seed
class probes passed; 484 mirror pairs matched after the compact UI change.
The previous endpoint failure was observed in the running source GUI. Corrected
endpoint placement, compact UI live acceptance and new installers are **pending**.

## Latest UI/lighting scope amendment

The later owner revision removes the custom seed selector/Paint/guide controls and the native segmentation/source selectors from step 2. Include the native Add/Remove/Show 3D editor layout with preset segments preserved. Also include `aipacs_lumen/lighting.py` and its workspace integration: scoped headlight, two-sided interior lighting, surface material, and restoration of previous light state. This supersedes the seed-selector/guide wording above. Add interior-wall visibility and overview-light restoration to next-artifact acceptance. Source and native synthetic checks do not close the live gate.

## Current title and activation amendment

Include `window_activation.py`, `resident_service.py`, launcher and startup/presentation changes that derive the title from current_app_version and grant foreground access to the requested viewer PID. Acceptance must cover a single current-version title and foreground visibility after cold/warm Virtual Bronchoscopy loading, including modal handling; no C++ baseline rebuild is required. See the VTK owner record for source evidence; native OS focus acceptance remains pending.

## Recurrent interior-darkness amendment

Include the latest lighting.py/workspace.py material initialization on both publish and scene restore, neutral backface color, scalar-color disabling, camera-owned renderer selection and Wall brightness control. Prior headlight-only acceptance is insufficient: next-artifact QA must inspect actual inside-wall visibility/depth cues at several route positions, also after saving/reopening the scene. Live case acceptance is pending.

## Exit-notification amendment

Include the updated slicer_launcher.py: remove the speculative Viewer Closed modal on nonzero process exit, retaining actual exit codes and warning logs. Launch errors remain actionable dialogs. Add ordinary viewer-close/no-modal behavior to next-artifact acceptance; no C++ rebuild is required.

## Close/reopen amendment

Include the launcher's bounded pending-reopen handling and the background runtime's
PHI-free failure-stage diagnostics. Guard: tests/code/mpr/test_slicer_reopen.py.
25 reopen/exit/resident tests pass, including 20 synthetic runtime sessions.
Actual repeated close/reopen and correct next-series identity remain acceptance
requirements in every applicable profile/backend. The user's subsequent generic
RuntimeError has not yet been causally resolved; capture the new operation stage
in a fresh-source session before closing this release gate. No C++ rebuild needed.

### Native close-during-load follow-up

The latest failure-stage evidence identified the native shutdown/import lifetime
boundary. Include ViewerCloseGuard, reply-aware deferred close, shutdown poll
suppression and typed viewer_closing handling in AIPacsBackgroundRuntime.py,
resident_service.py and slicer_launcher.py. The new close-during-load guard and
related selection pass 41 tests; an offscreen native probe passes both workspace
activations with deferred close. Accept actual close during loading, immediate
reopen on another exact series, and Cancel Exit on fresh source and every produced
artifact. Earlier host-grace-only evidence does not close this gate. Python-only
payload update; retain the existing native Slicer build.

Final close-lifecycle selection: 42 passed. Include the late-show no-restart guard
and reply-time close-intent refresh; 486 mirrored pairs verified. GUI/artifact
acceptance remains pending.

## Required implicit-quit correction (latest diagnosis)

Include AIPacsBackgroundRuntime's early setQuitOnLastWindowClosed(False) and
explicit app.exit(0) after accepted native close. The actual resident socket/DICOM
launch failed even without Close input; script-based native probes had masked
startup timing. Run tools/slicer/probe_resident_lumen.py with the source .venv and
PYTHONPATH=. as the opt-in synthetic native gate, then validate real close/reopen
and Cancel Exit on each artifact. This is a Python payload correction, not a new
native C++ build. See the corrected diagnosis in the VTK owner report.

Latest receipt: 43 focused tests and six actual native resident socket/DICOM
loads pass (three per workspace), both commands exit 0. Preserve the opt-in native
probe in release verification; widget-only tests do not cover this startup bug.
