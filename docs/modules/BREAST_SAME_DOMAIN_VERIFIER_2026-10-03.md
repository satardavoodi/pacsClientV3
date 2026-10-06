# Breast calcification same-domain verifier pilot

Research-only experiment completed on 2026-10-03. No production inference or deployed weights changed.

## Supervision and training

The physician's direct attestation establishes positive green rectangles and calcification-free reviewed crops. Labels apply only to reviewed crops, not entire source images. Non-mammography cases 026 and 027 were excluded. One negative crop intersecting a broad positive rectangle was held aside pending adjudication.

The frozen person-group split contains 37 training crops (20 positive, 17 negative) and eight development-validation crops (five positive, three negative) from four held-out source images/person groups. Training contains 53 positive region bags and 70 negative candidate bags. Validation contains six positive reference regions. Overlapping crops and findings are not fully deduplicated.

A compact three-convolution verifier receives native detail, wider context, and local contrast. Positive rectangles provide multiple-instance bags of teacher candidates; they do not label every enclosed pixel or patch positive. The verifier was initialized from the earlier KIOS patch experiment and fine-tuned with AdamW for 100 epochs/1,400 updates. DeepMiCa candidate extraction stays fixed at teacher threshold 0.5 and native 65-pixel grouping. Training loss fell from 1.7801 to 0.0527. Total experiment time was 67.67 seconds and peak allocated VRAM was 2.196 GiB. Checkpoint reload/output equality passed.

## Matched development comparison

All rows use the same eight development crops and six reference regions. Verifier thresholds are separate from the teacher threshold and are not calibrated probabilities.

| Route | Proposals | Regions containing proposal center | Regions retaining at least three predicted pixels | Centers outside all reference rectangles | Regions with IoU >= 0.25 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Teacher 0.5, no verifier | 20 | 5/6 | 6/6 | 14 | 4/6 |
| Teacher 0.5, verifier 0.001 | 15 | 6/6 | 6/6 | 8 | 4/6 |
| Teacher 0.5, verifier 0.01 | 14 | 6/6 | 6/6 | 7 | 3/6 |
| Teacher 0.5, verifier 0.1 | 14 | 5/6 | 5/6 | 8 | 2/6 |
| Teacher 0.5, verifier 0.5 | 8 | 3/6 | 3/6 | 4 | 1/6 |

Verifier 0.01 halves outside-reference centers while preserving these six regions by center and pixel-occupancy proxies. Box overlap worsens: this is not a uniform localization improvement. Verifier 0.001 is also worth retaining because overlap coverage is preserved. Verifier 0.5 is rejected for this screening-oriented pilot because it loses half the reference regions. Grouping can move box centers, so center counts need not change monotonically.

## Limits and next gate

This is a small, previously reviewed development cohort. Region coverage is not punctum sensitivity, clinical sensitivity, negative predictive value, or FROC. Outside-reference centers are candidates for adjudication, not confirmed false positives. Broad rectangles and repeated crops limit localization interpretation. Thresholds were swept on development data; no independent qualification has passed.

The next experiment should expand person-disjoint same-domain supervision, audit the complete KIOS archive and its annotation semantics, and evaluate a frozen candidate/threshold on a genuinely untouched test cohort. Compare both 0.001 and 0.01 operating points, measure missed reference regions and independently adjudicated false positives per image, and preserve a separate final test. New physician review should target new ambiguous/error candidates rather than repeat completed quality review. The existing model remains in production until that gate passes.

The complete KIOS v3 archive download is verified: 3,036,405,780 bytes; MD5 `6169bd77ac56da37c67407f9acbfe7da`; SHA256 `949ae8d4cac394de1b4b255210c3ad05fd767417be0edb47bca7fcae36348e76`. Full extraction, annotation audit and training on the full archive remain pending.

## Aggregate evidence and lineage

- `generated-files/eagle-eye/calcification-candidate-20261001/same-domain-verifier-20261003.json`
- `generated-files/eagle-eye/calcification-candidate-20261001/same-domain-validation-baseline-20261003.json`
- Supervision manifest SHA256: `548b028da77c068de1d811354d58ce34cd0433510e6f87f0b7d022a96122cf05`.
- Verifier checkpoint SHA256: `47313259e933d1f0f7760267d1faa19070fa0ea16e075af82c161bfbc5f934de`.
- Teacher checkpoint SHA256: `df50a71d269596dc88ebc09b3b063338c13b61749ab433d1a543eb8280d55fef`.

Private manifests, images, annotations, scripts and weights remain in protected dataset/research storage. The baseline receipt's inherited statement that quality ratings are missing refers to its original audit template; the physician attestation resolves assessability for these reviewed crops.
