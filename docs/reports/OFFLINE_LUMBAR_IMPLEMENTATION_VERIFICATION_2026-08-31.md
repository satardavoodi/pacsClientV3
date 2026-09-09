# Offline lumbar implementation verification

Date: 2026-08-31. Initial verification scope: development checkout, isolated custom
Slicer runtime, synthetic images only. That initial audit used no patient data,
workstation login, production deployment, installed workstation executable, or
external LLM request. The separately identified local MR follow-up below records
operational evidence only; no patient images or identifiers are included here.

Companion: [implementation and operating guide](../modules/ADVANCED_ANALYSIS_OFFLINE_LUMBAR.md).

## Verified outcomes

| Check | Observed outcome |
|---|---|
| Portable environment preparation | Completed: Python 3.12.10 AMD64, CPU Torch 2.6.0+cpu, TotalSegmentator 2.14.0, nnunetv2 2.6.2, NumPy 2.2.6; 91 resolved packages |
| Model archive | Dataset756, 230,791,939 bytes; SHA-256 matches `tools/slicer/offline_lumbar_sources.json` |
| Initial payload inventory | 26,304 hashed files, 2,260,714,423 bytes before subsequent adapter-only updates; about 2.26 GB excluding Slicer/cache/temp space |
| Package compatibility | Portable-environment `pip check` passed; constraint-based pip dry run passed against the prepared environment |
| Full payload verification | Passed after refreshing canonical adapter sources; measured 15.56 s in the workstation Python process on this machine |
| Worker preflight | Exit 0; real engine imports ready; CPU; one denied Python network operation recorded |
| Synthetic Slicer UI | Source selector, run/cancel controls and status widget initialized |
| Geometry | Cropped nonzero image extents and rotated/nonzero-origin affine survived binary-labelmap roundtrip exactly |
| Changed source | Modified source image rejected; no result segmentation was attached |
| Real model inference | `vertebrae_mr` executed on a 32 x 48 x 48 synthetic Gaussian MR array, returned same-grid labels/NIfTI and a MRML segmentation; process exit 0 |
| Network behavior | No missing-weight download required; Python audit guard active, one blocked network attempt, no approved external image transfer |
| Input cleanup | Final successful service run removed its `input.npy` |
| Focused test command | 43 passed, 5 deselected, process exit 0 |
| Plugin mirror check | 459 pairs match, 0 plugin-only files |
| Syntax / changed-file whitespace | Python compilation and scoped `git diff --check` passed; this is not a Ruff claim |

After the final adapter refresh, the same 26,304-file manifest totals
2,260,715,214 bytes. The final synthetic probe completed in approximately 56.16 s
including startup, verification and inference on this machine; this is not a
clinical-volume benchmark.

Fresh and reused release payload paths are exercised with temporary runtime/model
fixtures and the unrelated Lite Viewer build disabled inside those isolated tests.

The synthetic Gaussian contains no real anatomy and produced an **all-background
labelmap (zero anatomical segments)**. That is a valid plumbing result, not
evidence of vertebra recognition. Nonempty segmentation construction and geometry
were tested separately with a known synthetic mask. No Dice, lesion sensitivity,
numbering accuracy, or clinical inference-time claim follows from these runs.

## Evidence locations

All local evidence listed here contains synthetic inputs only. Do not reuse these
verbose diagnostic probes with patient data.

- Portable import preflight: `generated-files/offline-lumbar/preflight-1/result.json`.
- First geometry/UI qualification: `generated-files/offline-lumbar/probes/0b82699ac43b4665a46fa75e3a7fea8b/result.json`.
- First completed full inference after bootstrap separation: `generated-files/offline-lumbar/probes/85d999a12c29446fa80566a06440ebff/result.json`.
- Final full inference with the GIL-yield timer: `generated-files/offline-lumbar/probes/b5c119e26992415993b35567f623ce6a/result.json`.
- Prepared model bundle and full SHA-256 manifest: `generated-files/offline-lumbar/bundle/`.

Two earlier owned synthetic runs were stopped while the parent performed full
payload hashing with poor PythonQt background-thread progress:
`4c1aef1c103741c794fc5a1ee6adb994` and
`777fbe0bae144a489edaf00db0976710`. They are not passing runs. Thread traces
localized the delay to bundle filesystem validation. The correction moved full
verification to the standalone process and added periodic bounded GIL yielding.
Only the verified, probe-owned process trees were terminated. A later cleanup
attempt found its probe had already exited successfully; the identity check
prevented killing any other process.

The final run's `threads.log` may contain a `Timeout (0:00:45)` header from
`faulthandler.dump_traceback_later`. That is a diagnostic sampling interval, not
the probe deadline or a failing result; `result.json` and process exit establish
completion. The actual probe deadline is 900 seconds with an outer owned-process
deadline of 940 seconds.

## Automated guard command and exclusions

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest -p no:debugging tests/code/ai_imaging/test_offline_lumbar.py tests/code/builder/test_offline_lumbar_payload.py tests/code/builder/test_plugin_package_registry.py tests/code/builder/test_release_parity_guards.py tests/code/builder/test_materialize_plugin_packages.py tests/code/builder/test_plugin_package_builder.py -q -k "not stage_config_parity_against_current_stage"
```

The five deselections comprise four tests excluded by the repository's default
marker policy and the explicit current-stage config comparison exclusion. The
earlier broader run reported an existing mismatch between current
`config/patient_table_sort.json` and the old release stage. The user's configuration
was preserved. No repository-wide green status or release gate pass is claimed.

The new process-start failure guard was run before its cleanup correction and
failed because raw input remained; it passes afterward. Additional guards cover
corruption, path traversal, task/device substitution, missing weights, denied DNS,
normal cancellation, bootstrap/full-validation separation, dependency resource
retention, and combined runtime/model materialization using temporary fixtures.
The latter does not constitute a compiled-installer acceptance test.

## Local MR operator follow-up

The user subsequently confirmed that Advanced Analysis opens and responds after
the launch-button and hidden-modal repairs. A fresh rerun of the combined
launch/resident/lifecycle/builder suite passed **70 tests, 3 existing warnings,
exit 0**, and all **462 Python mirror pairs** matched. These checks do not score
model accuracy.

For the requested real-input demonstration, the assistant invoked the canonical
offline `run_snapshot` service on the exact MR series handed to Advanced Analysis.
Desktop automation opened the viewer, but could not reliably operate its module
finder; no successful Slicer-widget inference dispatch is claimed. The operator
trial does not implement the proposed Eagle Eye MCP integration and sends no
image to an external LLM endpoint.

Input reconstruction was restricted to the selected series and checked for MR
modality, single-frame slices, consistent orientation/spacing/dimensions and
uniform through-plane positions. The reader's LPS affine was explicitly converted
to RAS for the existing KJI snapshot contract. Outputs and per-case provenance
remain under ignored `user_data/analysis_trials/<opaque-id>/`; they remain
sensitive and must not be committed or treated as anonymized data.

Preparation was materially slower than the synthetic run. The interval from the
job request file to creation of the worker's engine-state configuration was
approximately **462.034 s**. This file-timestamp estimate includes worker startup
and full bundle verification, not neural-network inference. Before the marker
appeared, process I/O counters continued advancing. The cause of the difference
has not been isolated; disk/cache/antivirus effects must not be asserted from this
observation alone. Track follow-up measurements under OPT-56 and retain the full
integrity checks.

| Follow-up check | Observed outcome |
|---|---|
| Model service | Completed in 566.803 s including preparation, process startup, imports, model execution and service validation; operator process exit 0 |
| Model output | Nonempty anatomical labelmap; not an accuracy or numbering assessment |
| Source ownership | Exact handed-off series reconstructed; source file sizes and modification times unchanged after inference |
| Export verification | Saved `.seg.nrrd` reloaded with identical label voxels and matching origin, spacing and direction |
| Review artifacts | Source NIfTI, segmentation NRRD, fixed central-slice comparison PNG and private JSON provenance retained locally |
| Preview delivery | Local file-panel open requested; app returned queued. No screenshot or patient pixels sent to an external analysis tool |
| Cleanup / network guard | Temporary `input.npy` removed; no model download required; one Python network attempt blocked |
| Live Slicer result | Not imported or visually checked in the user's MRML scene; backend/export evidence only |
| Clinical validation | No expert review, reference masks, Dice, numbering accuracy or lesion-detection evidence |

The preview uses preselected central slices with source and overlay side by side;
it was not selected by model success. The approximately 104.8 s outside the
preparation estimate must not be reported as isolated inference time: imports,
weight loading and output validation are included. Neither the source viewer's
warm opening time nor the earlier synthetic run is a reliable substitute for
this observed total. The trial does not change Eagle Eye's diagnostic pipeline.

## L5-S1 disc operator experiment

The requested follow-up uses the preceding trial's source NIfTI and vertebral
labelmap, with matching geometry and unchanged SHA-256 digests. It does not infer
that a newly selected live scene still contains the same study.

The shipped `vertebrae_mr` checkpoint has no disc class. The separate experiment
uses TotalSegmentator 2.14.0's `total_mr` **Dataset850 organs part**, whose class 20
is `intervertebral_discs`. The installed engine's `nnUNet_predict_image` API is
called with model part `[850]`, its official trainer/fold, 1.5-mm resampling and
the disc class subset. This avoids downloading/running the unrelated muscle part
and does not modify or bypass the production adapter's fixed `vertebrae_mr`
contract. It is a trusted local operator experiment, not a new exposed command.
The official [task and class catalog](https://github.com/wasserth/TotalSegmentator)
describes generic MR discs; it does not give individual disc-level identities.

The official public checkpoint is prepared under ignored
`generated-files/offline-lumbar/disc-models/`, separate from the immutable existing
bundle. Archive byte counts, HTTP byte ranges, ZIP members/CRC and an extracted
file hash inventory are checked. SHA-256 values are locally observed provenance;
the upstream release API supplied no independent asset digest. No model download
process opens patient files. Inference uses the existing portable environment,
full original bundle verification, separate model verification, local owned job,
deadline and Python network-denial guard. This is not an OS-network-sandbox test.

A provisional level selector examines whole connected components of the predicted
disc mask against the previous model-proposed L5 and sacrum masks. It requires one
eligible component, adjacency to both landmarks, a center between their centers,
and no close competing vertebral label. Its explicit experiment-only constants
are 26-connectivity, at least 100 mm3, at most 6 mm nearest distance to each target
landmark, more than 6 mm from other vertebral labels, and at most 5% overlap with
the separate vertebral model. These are conservative engineering heuristics, not
validated anatomical criteria or confidence scores. The selected component is
not reshaped, filled in, or relabeled as a confirmed L5-S1 disc. Ambiguous/absent
selection requires human localization rather than an invented mask.

Five synthetic checks cover target-versus-neighbor selection, empty predictions,
two eligible components, a missing landmark and substantial bone-mask overlap.
A rotated-grid synthetic NRRD export/reload check also passes. These checks verify
operator-script behavior only. Source/mask/preview files and component measurements
remain private. Preview crops, when produced, are explicitly mask-guided display
crops; they are not used as an unbiased accuracy evaluation.

**Observed result, 2026-08-31:** the public archive download completed
(231,681,650 bytes; six extracted model files inventoried). The local worker then
completed in **182.016 s, exit 0**, with a nonempty disc prediction. This excludes
the initial model download and subsequent preview generation. Original bundle
plus added checkpoint verification finished at approximately 18.547 s, and the
model-call phase began at 25.375 s. These are operator-trial timings, not a hardware
benchmark or a measured latency improvement over the earlier different task.

Exactly one connected component passed the predeclared provisional selection
rules. Both the full disc mask and the candidate were exported as `.seg.nrrd`;
saved labels and physical geometry passed roundtrip checks. The candidate is an
unmodified subset of the model prediction and appears in the fixed central-slice
previews. PNG integrity checks passed, and the temporary model input was removed.
The app queued opening the local detail preview. No live MRML import, expert
boundary check, or confirmed L5-S1 numbering is claimed. Patient-derived artifacts
and numeric component-selection records remain in the private trial directory.

The archive, weights and preparation records are retained for future development.
They have **not** been added to the production model manifest, installer staging,
Slicer module controls or the Eagle Eye LLM/MCP interface.

**Subsequent user review: target coverage rejected.** The user reported missing
target tissue in the candidate. The earlier successful worker/export checks must
not be interpreted as complete anatomical segmentation. A local audit confirmed
that the saved candidate equals its entire predicted connected component; no
additional predicted disc component was present within the inspected 20-mm
neighborhood. This argues against the component-extraction step removing nearby
predicted tissue, but does not localize the missing target or prove why the engine
missed it. Do not report this trial as clinically accepted or expand the mask by
geometric dilation to manufacture coverage. Preserve the original prediction,
record the rejected coverage locally, and obtain a clinician-defined target region
before testing a prompted refinement or a different pathology-qualified model.
An unmasked local source contact sheet was prepared for target localization.

## Remaining acceptance work

1. Build/sign the final installer after the existing repository release/security
   gates are resolved. None was compiled or distributed here.
2. Install/uninstall/upgrade on a clean Windows x64 machine with no Python/CUDA
   setup, deny outbound traffic at OS level, and prove first-run behavior using
   only installed payloads. The Python audit hook is not a native-code sandbox.
3. Qualify minimum hardware, runtime/memory, large-volume UI responsiveness,
   crash cleanup and sensitive-artifact retention. Normal cancellation is guarded;
   abrupt parent/OS death still lacks a Windows Job Object cleanup guarantee.
4. Validate actual MR segmentation and vertebral numbering with expert reference
   data, including partial coverage, abnormal segmentation/numbering, transitional
   anatomy and postoperative cases. Measure lesion diagnosis separately.
5. Add a bounded MCP/function adapter and evaluate fixed model-derived evidence
   with Eagle Eye before promoting adaptive LLM control. Existing LLM behavior,
   network requirements and diagnoses remain unchanged.
