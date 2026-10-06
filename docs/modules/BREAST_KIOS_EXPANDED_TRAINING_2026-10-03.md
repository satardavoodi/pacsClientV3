# Breast calcification expanded training and transfer audit

Research experiments on the Linux A100; production inference and weights remain unchanged. Private images, manifests, derived patches and checkpoints remain outside the repository.

## Full dataset preparation

KIOS v3 [publisher record](https://zenodo.org/records/14859694) and its README define red annotations as benign microcalcifications and blue circles as suspicious regions. Circles are not dense pixel masks. The complete verified archive was safely extracted and audited: 100 publisher person folders, 400 DICOM/annotation pairs, zero geometry mismatches and zero exact file-hash duplicates. Near duplicates and cross-category person linkage are not fully proven.

All views and prior/recent exams stay together. Previously inspected seven pilot groups were forced into training. The frozen split is 74 training, 13 calibration and 13 test groups. Patch counts are 3,435/413/591 respectively. The color audit found 18 completely unmarked Normal_cases groups, compared with 22 no-calcification participants in the publisher description. Only the conservative 18 were eligible as negatives; this discrepancy remains unresolved. Red components are provisional point-center supervision; blue regions were excluded from point-supervised pretraining. Thirty-two images had no eligible point supervision.

## Expanded point-supervised model

The native detail/context/local-contrast compact CNN used AdamW, balanced training updates, and calibration AUROC for early checkpoint selection. It completed 41 epochs/4,223 updates, selecting epoch 31. Loss fell from 0.5593 to 0.0629. The selected checkpoint was reloaded and verified for identical outputs. The calibration positive second-percentile threshold was 0.2530106. The fixed patch test was accessed only after selection.

| Partition | Positive patches | Negative patches | Patch AUROC | Positive sensitivity | Negative activation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Calibration | 157 | 256 | 0.9981 | 97.45% | 1.95% |
| Test | 335 | 256 | 0.9771 | 95.82% | 7.81% |

These correlated patch metrics do not establish full-image screening sensitivity, PPV/NPV or FROC. Calibration served both epoch and threshold selection, making its metrics optimistic. Pretraining took 30.50 seconds, peak allocated VRAM 0.153 GiB. SHA256: `7ea1117f1fd599ad58ec6612997dc026042c7fab4b5b5d4adec6f48eb81479f7`.

## Local region adaptation and failure on broader calibration images

The pretrained checkpoint was adapted using the existing physician-supervised training bags, without validation-group training. On eight physician development crops/six regions, threshold 0.3 preserved all six regions by center/pixel proxies and reduced outside-reference centers from 14 to three. Box IoU coverage remained only three of six. This reused development result is not independent qualification.

The stronger check used all 52 full mammograms of the 13 KIOS calibration groups. Test groups were not used for this end-to-end check. Teacher threshold remained 0.5. DICOM-to-uint8 conversion used label-blind per-image percentiles 1/99.5; this preprocessing itself remains unqualified for fine-detail preservation.

| Route | Red centers with prediction within eight native pixels | Blue regions retaining >=3 pixels | Proposals on eight known-negative images |
| --- | ---: | ---: | ---: |
| Teacher only | 151/157 | 13/13 | 129 |
| Expanded point verifier, threshold 0.2530 | 118/157 | 13/13 | 124 |
| Physician-adapted verifier, threshold 0.3 | 64/157 | 11/13 | 157 |

Both verifier routes fail the preservation gate on these broader images despite promising patch/local metrics. Neither is promoted. Connected-component pruning can fragment regions and increase grouped box counts: total proposals increased from 721 to 1,310 with the point verifier even as predicted pixels were removed. Blue-circle bounding rectangles and red-color center matching are annotation proxies, not adjudicated punctum localization. An occupied blue region does not prove all calcifications were detected.

## Corrective hard-negative intervention

Mine candidates from training groups only, keeping calibration and test images excluded. Fourteen conservatively negative training groups provide 28 recent CC/MLO images. The teacher generated 40,236 connected components; 1,792 negative patches were sampled, capped at 64 per image with high-confidence and random remaining candidates. These match the candidate-centered runtime feature extraction rather than relying only on generic random tissue negatives.

The joint experiment combines 53 physician positive region bags, 1,643 KIOS positive point patches and these detector-generated negatives, with balanced local/external positives per epoch. It completed 100 epochs/2,700 updates in 73.71 seconds, peak VRAM 2.196 GiB; checkpoint reload/output equality passed. SHA256: `92eeffab3e37982b5d25916e3eca277462556d39dfafb526870cbcaadbadfd83`.

| Joint verifier threshold | Red centers retained within eight pixels | Blue regions retaining >=3 pixels | Proposals on eight known-negative images |
| --- | ---: | ---: | ---: |
| 0.001 | 131/157 | 13/13 | 128 |
| 0.01 | 127/157 | 13/13 | 202 |
| 0.1 | 118/157 | 13/13 | 160 |
| 0.3 | 106/157 | 13/13 | 104 |
| 0.5 | 104/157 | 13/13 | 66 |

The joint route also fails the no-extra-miss preservation gate relative to the teacher's 151/157. At threshold 0.5, known-negative proposals halve but 47 teacher-covered reference points are lost. Occupancy of all 13 blue rectangles hides this punctum-level loss. This is a research rejection, not qualification.

## Pixel output-head alternative

To avoid assigning one score to a connected component and deleting all its pixels together, a subsequent experiment adapts DeepMiCa's 65-parameter 1x1 pixel output head. The encoder, decoder and batch-normalization statistics remain frozen. Exact teacher foreground/flip/crop/CLAHE preprocessing and original 256-pixel tile boundaries are used for feature extraction. Only training groups enter feature extraction.

The bounded recent-view intervention processed 146 images and 483 tiles, yielding 678 positive point features and 7,165 negative pixel features. Training points select one teacher-supported pixel within four pixels of a provisional red center; other pixels in positive images remain unknown. Negative pixels come only from conservatively empty training groups. Balanced sampled updates use positive loss weight eight to prioritize retention. After 100 epochs/1,100 updates, loss fell from 2.6309 to 1.3084. Total time was 78.05 seconds, peak allocated VRAM 0.384 GiB; full checkpoint reload/output equality passed. SHA256: `e35331bfe62576c55baf5ce99f4236b895be3b6036554db92317b5df1165841b`.

End-to-end calibration and negative-footprint audits rejected this route too. Counting a very large box or broadly positive image as successful point coverage is prohibited: negative predicted-pixel area and box-area fractions must accompany coverage and proposal counts.

| Pixel-head threshold | Red centers covered within eight pixels | Blue regions occupied | Proposals on eight negative images | Fraction of negative-image pixels predicted positive |
| --- | ---: | ---: | ---: | ---: |
| Original teacher 0.5 | 151/157 | 13/13 | 129 | 10.56% |
| Adapted head 0.1 | 157/157 | 13/13 | 8 | 30.10% |
| Adapted head 0.3 | 157/157 | 13/13 | 8 | 26.85% |
| Adapted head 0.5 | 157/157 | 13/13 | 16 | 23.83% |
| Adapted head 0.7 | 153/157 | 13/13 | 49 | 19.09% |
| Adapted head 0.9 | 89/157 | 13/13 | 260 | 10.40% |

The apparent 100% point coverage at low thresholds is broad positive activation, not accurate punctum detection. At threshold 0.5 the largest negative-image box covered 61.61% of its full image. All eight negative images had a box exceeding 5% image area, including with the original teacher. This guard prevents accepting one giant box as high screening sensitivity or improved precision. No final end-to-end test or clinical promotion followed.

## DICOM rendering control

All 400 source images have WindowCenter/WindowWidth and rescale fields, are MONOCHROME2/FOR PRESENTATION, and store 12-bit pixels; none has a VOI LUT sequence. Pixel spacing exists in 396 and imager spacing in 400. A separate label-blind control applies modality rescale before DICOM windowing, theoretical output-range scaling, presentation polarity and pixel-padding handling. The operation order follows [pydicom windowing documentation](https://pydicom.github.io/pydicom/stable/reference/generated/pydicom.pixels.apply_windowing.html). Existing physician display settings and source pixels were not changed.

On the same 52 calibration images, original teacher threshold 0.5 with standard windowing covered 149/157 red centers and 13/13 blue regions, compared with 151/157 and 13/13 under percentile rendering. Known-negative boxes increased from 129 to 176 even though predicted-negative-image pixels fell from 11,519,082 to 8,272,743 (28.18% reduction). This also fails the preservation/box gate. It supports auditing rendering and grouping together, not claiming windowing alone fixes the detector. The inherited percentile-rendering limitation in this comparison receipt describes its baseline branch; the second branch explicitly uses DICOM windowing.

## Required supervision and concrete physician handoff

No tested route qualifies as a reliable screening improvement. Strong patch discrimination, broad region occupancy, fewer boxes and lower loss each hid failures in at least one controlled check. The local 14-to-three outside-box result remains a reused-development observation, not a broadly validated improvement. The next supervised detector/refinement experiment needs actual suspicious punctum localization, since publisher blue circles and the existing broad green regions cannot supply dense or individual-point truth.

Eight NEW suspicious crops from eight training groups were prepared at native 1024-pixel resolution. Calibration/test groups and old physician corrections remain untouched. Protected browser review: `http://127.0.0.1:18915/point-review.html`. The physician can click true calcification centers or draw tight individual/tiny-group rectangles, zoom to 300%, and mark unclear cases as uncertain. Finishing an empty crop explicitly means no visible calcifications only in that crop. No repeat quality rating or blanket re-review of previous negative cases is requested. Display brightness/contrast changes do not alter annotation coordinates or stored source pixels.

Loopback-only backend validates native bounds, exposes no private source/person fields in browser state, and atomically persists new feedback. All eight images served successfully; out-of-range annotation payload was rejected with state unchanged; JavaScript syntax and live browser DOM/error-console checks passed. No fabricated physician positives were created. This is a research annotation UI check, not clinical AI-PACS GUI acceptance. Training with these new physician labels remains pending their completion. Preserve a separate untouched external/temporal cohort for final qualification.

## Aggregate receipts

All receipts are in `generated-files/eagle-eye/calcification-candidate-20261001/`:

- `KIOS-full-preparation-20261003.json`
- `KIOS-full-patch-training-20261003.json`
- `KIOS-full-direct-cascade-20261003.json`
- `KIOS-expanded-same-domain-20261003.json`
- `full-image-calibration-audit.json`
- `adapted-full-image-calibration-audit.json`
- `KIOS-hard-negative-preparation-20261003.json`
- `KIOS-hard-negative-joint-training-20261003.json`
- `hard-negative-full-image-calibration-audit.json`
- `KIOS-pixel-head-training-20261003.json`
- `pixel-head-full-image-calibration-audit.json`
- `pixel-head-negative-footprint-audit.json`
- `dicom-rendering-metadata-audit.json`
- `dicom-voi-calibration-audit.json`
- `new-physician-point-review-preparation-20261003.json`
- `new-physician-point-review-ui-verification-20261003.json`
- `execution-lineage.json`

Execution environment: Python 3.10.12, Torch 2.11.0+cu130, CUDA 13.0, A100-SXM4-40GB. GPU stages ran sequentially with memory caps; no other services were stopped. No application runtime change, release, deployment or GUI acceptance was performed.
