# Calcification failure diagnosis

Status: research failure analysis; no qualified detector or production weight change.

## Fixed-network grouping experiment

Full-source DICOM inference was repeated on the eight physician-reviewed training groups with 16 region rectangles. Network, rendering, probabilities and threshold were held fixed while grouping kernels varied. Predictions intersecting the review crop were reconstructed into crop-local boxes. This differs from the earlier full-box-center inclusion audit and is not a directly interchangeable metric.

| Threshold | Grouping kernel in native pixels | Crop-intersecting proposals | Reference regions containing a proposal center | Proposals with center outside all reference regions | Boxes exceeding one quarter of crop |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0.5 | 1 (no additional dilation) | 3,140 | 16/16 | 2,921 | 6 |
| 0.5 | 9 | 718 | 12/16 | 663 | 7 |
| 0.5 | 25 | 149 | 10/16 | 132 | 7 |
| 0.5 | 65 | 24 | 6/16 | 18 | 8 |
| 0.9 | 1 | 3,763 | 15/16 | 3,380 | 1 |
| 0.9 | 65 | 42 | 8/16 | 34 | 7 |

At threshold 0.5, 2,243,847 positive pixels were outside physician rectangles out of 8,388,608 total crop pixels (26.75%). This numerator is unchanged by grouping. At 0.9 it remains 1,015,587 (12.11%). Outside-reference outputs are not independently adjudicated false positives. Center coverage among thousands of candidates does not establish true lesion sensitivity. Region rectangles are not individual-punctum masks, so individual boxes need not meet region IoU.

Execution: 29.76 seconds, 2.196 GiB peak allocated GPU memory. Aggregate receipt: `generated-files/eagle-eye/calcification-candidate-20261001/region-grouping-diagnostic-20261003.json`.

## Evidence-weighted causes

1. **Confirmed grouping contribution.** A 65-pixel dilation joins dispersed predictions through connected chains. Removing grouping restores reference-center coverage but exposes thousands of candidates. Grouping is one cause of poor box geometry, not the complete cause.
2. **Confirmed excessive raw activation.** Broad positive regions and giant components exist even without additional grouping. Cosmetic box shrinking cannot resolve network discrimination.
3. **Observed patch-to-full-image gap.** The compact point classifier reached 95.82% positive patch sensitivity on its frozen patch test, but its full-image cascade retained only 118/157 provisional reference points on calibration images, compared with the original teacher's 151/157. Candidate selection, feature distribution and full-image negatives require joint validation. Patch sensitivity is not screening sensitivity.
4. **Observed refinement tradeoff.** Joint verifier threshold 0.5 reduced known-negative proposals from 129 to 66 but retained only 104/157 reference points. Output-head adaptation increased apparent coverage by activating broad areas. Both were rejected.
5. **Limited adaptation, not demonstrated full retraining.** Prior interventions trained compact verifiers or only the 65-parameter output head of a frozen U-Net. They do not establish that a task-matched, fully adapted encoder/decoder has failed, or that additional epochs alone will solve the problem. Real optimizer updates and reload checks passed; absent training is not supported as an explanation for those experiments.
6. **Supervision and domain limitations.** Physician cluster rectangles cannot label each enclosed pixel positive. Publisher red points and blue circles have different semantics; presumed normal groups have a count discrepancy. Upstream DeepMiCa used INbreast/CBIS-DDSM; transfer to KIOS and local data is not assured. Domain shift is plausible, not isolated causally yet.
7. **Preprocessing partly checked.** Input division by 255 matches inspected upstream code. Gamma functions were not invoked in inspected source. Standard DICOM windowing reduced negative activation but did not qualify the detector. Exact upstream image-only preprocessing parity remains incomplete; ground-truth-dependent cleanup must not enter inference.

No evidence currently establishes classic overfitting as the sole cause, a universal architecture failure, or a clinically measured 30% screening sensitivity. More independent cases improve estimates and coverage, but eight new cases cannot establish deployment performance.

## Diagnostic sequence before another large training run

1. Freeze native geometry, pixel spacing, rendering and label semantics. Audit label-blind upstream preprocessing parity and tile reconstruction on synthetic and training examples.
2. Run a tiny training-subset fit with valid point/region objectives, verifying gradients in intended encoder/decoder layers. Failure to fit directs attention to geometry, labels, losses and updates; success proves pipeline capacity only.
3. Compare staged decoder/encoder adaptation with the compact native-detail classifier using the same grouped development split. Sample confirmed negatives and detector-generated hard negatives from training only. Keep unknown pixels masked and use region-level objectives for physician rectangles.
4. Separate native tiny-candidate detection, false-positive scoring and cluster grouping. Test physical-scale grouping and boundary integrity without silently discarding large true clusters or unqualified filtering.
5. Select on end-to-end lesion/cluster FROC at declared false-positive budgets, negative-image activation/box-area guards and miss review. Do not optimize on repeatedly accessed patch-test results. Freeze configuration before a new independent full-image test.

## External context

The official [DeepMiCa project](https://github.com/ales-git/DeepMiCa) separates preprocessing, patch segmentation and lesion classification; its malignancy classification result is not an autonomous calcification-detection rate. Its [paper](https://doi.org/10.1016/j.cmpb.2023.107483) describes the same three stages.

A retrospective study of a commercial CAD system reported detection of 71/74 malignant and 101/122 benign calcification cases among 196 selected BI-RADS 4/5 biopsy cases without mass/distortion: [Scaranelo et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20137883/). This demonstrates feasibility in that cohort, not present-day universal market accuracy, individual-punctum recall or specificity in a screening population. Compare like-for-like tasks, cohorts and false-positive budgets.
