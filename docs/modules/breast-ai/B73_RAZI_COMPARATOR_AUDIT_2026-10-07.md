# B73: Razi comparator provenance audit

## Objective and evidence identity

Read-only audit on 2026-10-07 to determine whether B72 establishes improvement over
deployed Razi lesion typing. It does not. No training, deployment, clinical inference,
or new accuracy evaluation was performed in B73.

Protected evidence: `C:/AI-PACS-Datasets/breast-review/point-review-20261003/b73-razi-audit-20261007/`.
This contains `razi_XGBOOST_INFERENCE.py` and `asset-hash-comparison.json`.

Razi process inspection identified the service script under
`D:/Eagle Eye Server/revisions/20261004-secretary-help-ticket/source`.
The top-level deployment receipt still names the September 23 revision and is stale
relative to those process paths. A base Python executable from another revision is
not evidence of that revision's application source. In-memory module identity and
an actual request trace remain unverified.

## Verified implementation and asset findings

- All 14 stacked-classifier asset files in that revision match the local research
  copy under `generated-files/eagle-eye/breast/weights/models_stacked` by SHA256.
- The source-mode bundle resolver prioritizes that revision's generated breast
  directory; its manifest exists. The worker passes its `weights/models_stacked`
  directory to the classifier.
- Razi classifier source SHA256:
  `083597f341dfd97ab2bbbc3d5e1d85034dafde1b1c03020b71fe2e18505c387f0`.
  Local corrected classifier source SHA256:
  `9e44c691c58ba960dbebf61214e19c08102c8896f37b446b0cdbaea1543736f9`.
- Saved/output labels are No Finding, Mass, Suspicious Calcification and Focal
  Asymmetry. There is no independent architectural-distortion or Asymmetry head.
- The inspected remote implementation stacks the base probabilities directly,
  lacks the local engineered-feature/stack-input reconstruction, and its calibrator
  does not handle the saved `logistic_model` state as the local correction does.
- The worker can preserve detection while marking classification `unavailable`
  after an exception. Therefore seeing detection boxes does not establish that
  the second-stage classifier completed. This is a code-path finding, not a claim
  that any particular clinical request failed.

## Cohort and metric contract

No new cohort or fitted model in this audit. B72 used 272 reference regions from
138 publisher-TEST studies (199 Mass, 18 distortion, 55 asymmetry family).
Its B64 research reference accuracy was 67.28%; B50 transfer 70.83%; weighted B50
69.49%. These are research results, not measurements of deployed Razi.

B50 target-only versus auxiliary transfer on that same test changed accuracy from
70.71% to 70.83% (+0.12 percentage points), and macro-F1 from 43.19% to 45.49%
(+2.30 points). This does not show a large overall gain and does not compare Razi.
It is a mean over fixed seeds, not 816 independent lesions or an ensemble result.

The older corrected legacy classifier evaluation on 4,095 precomputed feature rows
is also not a deployed-Razi evaluation. Its different unit, endpoints, multiview
feature provenance and unknown historical exposure prevent direct subtraction
from B72. Do not call Mass sensitivity overall typing accuracy.

## Decision, limitations and next action

Research superiority over Razi remains **unmeasured**, not zero and not established.
No promotion. No source, weights, services or thresholds changed on Razi.

First reproduce the inspected deployed classifier off the clinical host, including
its actual failure/fallback behavior and environment. Bind a completed request to
the live module/root before calling the reproduction deployed parity. Evaluate on
the same protected reference boxes, separately reporting the supported Mass/explicit
Focal Asymmetry endpoints, multilabel conflicts and unavailable classifications.
Do not force unsupported distortion into a supposedly comparable three-class score.
For three-class research typing retain B72, with explicit coverage differences.
Historical training exposure and patient independence remain unknown for Razi.

Training telemetry, optimizer, learning curves and runtime GUI acceptance are not
applicable to this read-only audit. Clinical acceptability and independent diagnostic
qualification were not assessed. Document checks and asset-hash equality support
provenance only, not clinical performance.
