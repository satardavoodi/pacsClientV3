# B87: Fixed-prediction score-band analysis

Executed2026-10-07 on B81 saved predictions; no fitting, new inference, production
threshold change or independent test. Owner requested distinguishing0.40,0.45,0.50
candidates. Same selected128-image TRAIN CC cohort, area filter0.002 and maximum
cardinality IoU0.3 matching as B86. Unknown13 images are excluded from normal counts.

| Threshold | Reference matches /34 | Marks on83 publisher-normal images | Normal images marked /83 |
|---|---:|---:|---:|
| >=0.50 | 12 | 11 | 10 |
| >=0.45 | 16 | 46 | 36 |
| >=0.40 | 20 | 127 | 65 |

Lowering0.50 to0.45 adds4 net reference matches and35 normal marks; lowering0.45
to0.40 adds4 net matches and81 normal marks. Raising0.40 to0.45 reduces normal marks
by63.78%, with4 fewer matched references. Raising0.45 to0.50 reduces normal marks
by76.09%, also with4 fewer matches. These are development tradeoffs, not improvement
at fixed sensitivity. Neither threshold is selected for deployment here.

| Disjoint band | Marks on annotated-positive images | Marks overlapping any reference | Marks on publisher-normal images | Marks on unknown images |
|---|---:|---:|---:|---:|
| >=0.50 | 16 | 12 | 11 | 2 |
| [0.45,0.50) | 20 | 8 | 35 | 9 |
| [0.40,0.45) | 54 | 19 | 81 | 19 |

Overlapping-mark counts are not unique lesions or clinical PPV: multiple marks may
hit the same reference, unmatched positive-image marks are unadjudicated, and unknown
images have incomplete truth. Do not divide incremental matches by normal marks and
call it PPV. The high band still marks10 publisher-normal images, so score alone
does not establish pathology. No malignancy probability or histologic endpoint.

## Decision

Owner confirmed the interpretation and requested continuity with the existing
program. Operational use is review stratification, difficult-negative selection
within TRAIN and threshold-only controls for B84 E1. Preserve the0.45 comparator
motivated by routine experience, without claiming that experience or this selected
cohort qualifies a deployment threshold. Do not pivot into repeated threshold
searches or treat a lower mark count with lost lesions as a fixed-sensitivity gain.
The main current-state document now contains the consolidated continuation route.

Use bands for review stratification and a later controlled verifier evaluation.
The low band offers poor marginal yield here but contains real reference support;
neither discard it automatically nor send every low-score mark to the final viewer.
Include high-score normal mistakes in training/review too. Compare any staged
verifier against BOTH threshold-only0.45 and0.50 controls, preserving matched recall
and lost-lesion accounting. In a future run select thresholds on calibration data,
not by optimizing this repeatedly inspected cohort. Tissue and calcium remain
separate; this analysis does not evaluate the retained native-calcium branch.

## Reproducibility and limits

Protected root `C:/AI-PACS-Datasets/breast-review/point-review-20261003`:
script `b87_score_bands.py`; `b87-score-bands-20261007/report.json` binds source hashes;
`bands-private.json` preserves region/score/group lineage for review. Matching
functions are extracted without executing the B86 script body. Four synthetic
matching guards and score-boundary guard pass; monotonic counts and the B86 baseline
are asserted. Source predictions and annotations remain unchanged. Person-level
independence, adjudicated regional negatives and CPU parity remain unverified.
No confidence interval or clinical generalization claim from this small selected
cohort. This is an executed score analysis, not completion of E1 training readiness.
