# B90: One Breast request with retained FCOS and frozen calcium

Date: 2026-10-08. Stage: executable research integration candidate; not activated.
Owner requests one analysis with the incumbent parenchymal pipeline and the accepted
calcium localizer. No new training, threshold search or tissue model replacement.

## Implementation and boundaries

`tools/eagle_eye/breast_dual_candidate.py` validates the sealed incumbent bundle and
the input study, then starts two isolated CPU subprocesses under one request. It
supports serial and parallel scheduling. The incumbent FCOS/stacked-classifier
runner, weights, preprocessing and tissue threshold (default 0.45) are unchanged.
`tools/eagle_eye/calcium_candidate.py` loads the frozen Inception-v4 FPN plus adapted
decoder/head, uses native 512 tiles/256 stride/128 internal trim, physical peaks and
the B33 air-context AND 1 mm silhouette filter. The calcium cutoff remains
0.000316227766; it is not the tissue threshold or a malignancy probability.

Outputs remain separate: parenchymal boxes/classification tables and native-image
calcium support points. Each calcium image carries source hash, SOP/series identity,
shape and physical spacing. A point need not represent one individual calcification;
several points may cover its neighborhood. Morphology and BI-RADS are unavailable.
Legacy classifier calcium labels remain in the raw incumbent audit tables; these
must not silently become a second competing calcium display or replace the new
branch. No combined clinical display has been implemented yet.

The candidate rejects unsupported calcium inputs rather than treating them as normal:
currently unsigned 16-bit, MONOCHROME2, single-frame, identity rescale, nonconstant
native image at least 512 in both axes, with positive PixelSpacing. Source identity
is checked before/after inference. Failure of either subprocess makes the combined
request incomplete and that branch unavailable. No automatic normal fallback.
This CLI is a developer test harness, not a client-side clinical inference route.
The final client must submit one authenticated server request and consume both
outputs; cancellation, resource scheduling and publication must use existing server
ownership before activation.

## Artifacts and environment

Protected root: `C:/AI-PACS-Datasets/breast-review/point-review-20261003/b90-dual-branch-20261008`.
Frozen weight/helper hashes are embedded in the adapter and match the B89 manifest.
The existing local Breast CPU Python 3.10.20 runtime is reused without modification.
Additional packages are isolated in the protected B90 `deps` directory:
segmentation-models-pytorch 0.2.0, timm 0.4.12, pretrainedmodels 0.7.4,
efficientnet-pytorch 0.7.1, munch 4.0.0, OpenCV-headless 4.10.0.84, tqdm 4.67.1.
Existing torch 2.5.1, torchvision 0.20.1, NumPy 2.0.2 and SciPy 1.15.3 are retained.
No global packages, source DICOM pixels or active service configuration changed.

## Verification and interpretation

- Eleven synthetic contract tests pass: complete tile coverage including irregular
  edges; rejection of undersized inputs/unsupported polarity; unchanged frozen
  normalization; no success from missing/failed branches; per-image/study identity
  and changed-source rejection.
- Actual frozen calcium weights loaded and inferred on CPU for a synthetic 512x512
  DICOM: 2.766 seconds including model load, excluding Python/dependency startup.
- One actual parallel request completed both branches, including the existing
  stacked classifier: 36.024 seconds subprocess wall time on the local computer.
  Calcium internal time in that run was 2.375 seconds. Full bundle validation,
  interpreter startup before timing and other concurrent system work are not an
  end-to-end clinical benchmark. The sealed bundle has 24,446 entries; its separate
  integrity scan incurred substantial filesystem latency.
- One native 4096x3328 exposed development image completed calcium inference in
  205.781 seconds (model load 0.515 seconds; Python/import startup excluded), using
  two torch threads. It retained 1,010 support points across the full image and
  removed three with the frozen edge filter. Full-image unreviewed points are not
  automatically true positives. Peak RAM was not instrumented.
- In the previously reviewed crop, 621 of 622 frozen post-filter output points
  were reproduced, with no extra point in that crop. This is output agreement,
  not sensitivity. The one absent point was a present physical candidate, not an
  edge-filter deletion: its old score 0.000318032864 became 0.000314449950, crossing
  the unchanged 0.000316227766 cutoff. It was not paired to an original physician
  dot, but that does not establish a false positive. Numerical/runtime portability
  is unresolved; the threshold was not tuned to force reproduction.

Protected aggregate receipts: `native-reproduction-receipt.json` and
`native-discrepancy-receipt.json`. A native whole-study dual run, serial-versus-parallel
benchmark and target-Razi native-image inference are still unmeasured. The observed native time
does not meet the previously discussed approximately one-minute budget.

The selected non-running Razi Developer candidate completed an actual-model
synthetic parallel request: both branches succeeded in 35.747 seconds subprocess
wall time. The eleven contract tests also passed on Razi (1.13 seconds); local
tests passed in 0.65 seconds. The source delta has seven files, no packaged runtime
mirror changes (developer tools/tests/documents only). The declared source inventory
of 8,170 files matched by SHA256 with no missing/differing files; the local follow-up
stability check found no changes. The additive dependency archive also matched.
Receipts are under the local protected root and
`D:/Eagle Eye Server/staging/breast-b90-20261008`; source target is
`D:/Eagle Eye Server/revisions/20261008-reconciled-developer/source`.
These scoped payload and declared-inventory checks do not constitute a new build
qualification. AIPacsEagleEye remained on r4; no restart, private-image transfer to
Razi, installed-client change or live GUI acceptance occurred.

Synthetic execution is not sensitivity/specificity evidence. The real image is
already exposed development data, not an independent test. No optimizer, new fit,
cohort rebalancing or new clinical accuracy estimate applies to B90. No conclusion
that parallel scheduling is faster than serial has been established.

## Remaining gates and next action

Resolve the observed numerical threshold drift and native CPU cost, then integrate the retained
candidate with the server job owner, sealed dependency/weight manifest, portable
artifact allowlist and client source-coordinate overlay. Verify both outputs in a
fresh authenticated source GUI session. Audit unsupported scanner inputs, independent
positives/normals, full-study CPU budget and distribution rights before clinical
activation. Preserve the current FCOS and do not retrain calcium incidentally.

Deploy-safety-check remains BLOCKED: "Any single BLOCKED item blocks the whole
deploy." Owner authorization is present; full-study target-host/client acceptance is
missing. This report is not a request to repeat permission and not a release receipt.
Developer source synchronization and full inventory audit are recorded separately;
research staging must not be described as active-service parity.
