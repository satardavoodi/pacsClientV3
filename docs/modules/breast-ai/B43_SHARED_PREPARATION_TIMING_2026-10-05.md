# B43: Measured shared-preparation efficiency

Date: 2026-10-05. Decision: retain shared image preparation as an efficiency
prototype; accuracy benefit and production deployment remain unqualified.

## Controlled comparison

Eight existing calcium-review images, identical 18 ROI requests and normalization.
Separate route: one source SHA check, one DICOM decode for calcium preparation,
one additional decode for all soft-tissue crops. Shared route: same single source
SHA check, one decode shared by calcium preparation and all crops. Both keep
arrays alive through the timed work and produce identical inputs and crops.
Checks occur outside timing. This compares research adapters, not two complete
production worker implementations or the ITK-versus-pydicom engine difference.

Warm up both routes, then run five rounds, alternating route order each round.
Collect garbage before timing each route/image. CPU/Linux, warm filesystem cache;
no OS cache flush, no GPU, no model inference. Both routes include source hashing.

| Round | Separate preparation, eight images (s) | Shared preparation (s) |
|---|---:|---:|
| 1 | 2.1141 | 1.8963 |
| 2 | 2.1156 | 1.8957 |
| 3 | 2.1282 | 1.8852 |
| 4 | 2.1158 | 1.9013 |
| 5 | 2.0944 | 1.9015 |
| Median | 2.1156 | 1.8963 |

Median preparation reduction: 0.21935 seconds per eight images, or 10.368% of
this measured stage. DICOM decode calls drop from 16 to 8 per round. There is no
claim of 10.4% full-study acceleration. Overall improvement depends on the fraction
spent in preparation; native calcium neural inference may dominate. Peak RAM,
cold-cache behavior, concurrency and Razi complete-study latency remain unmeasured.
The design avoids duplicate decode but does not halve all computation or memory.

## Accuracy status and decision

Exact input and crop equality supports unchanged inputs to the frozen branches.
B42 also verified previously saved calcium outputs; no new network execution here.
Neither result is improved sensitivity, improved specificity or new clinical
qualification. B41's removal of weak proxies is a separate exploratory finding
and must not be credited to sharing or the real calcium branch.

The typed B38/B41 cohort still needs actual source-bound calcium predictions with
upstream training-exposure control. The eight reviewed calcium cases alone cannot
estimate Mass/FA/Asymmetry improvement. Next compare the same typed classifier
with/without these features, maintaining group splits and explicit availability.
Do not manufacture an accuracy result by reusing calcium boxes as mass labels.

Accept the shared-preparation principle for continued engineering. Defer combined
classifier adoption until paired typing performance improves without unacceptable
Mass or calcium losses. No inference service, model, skin filter or UI changed.

Evidence: P/benchmark_shared_breast_20261005.py and
P/shared-breast-audit-20261005/timing.json, mirrored under R.
Script SHA-256: f683218b5ebe83d9c9c7990fc5d44a34f8902489989b014af259cac1b9ec890f.
Input geometry/identity references inherit B42. No private identifiers in this report.
