# Native overlapping-tile experiment

Executed 2026-10-02 on the Linux A100. Research only; no optimizer updates or production weight changes.

## Protocol

Compared the previously executed DeepMiCa native 256-pixel non-overlap baseline against 256-pixel tiles with stride 128, including the final image edge. Overlapping sigmoid probabilities were blended with a separable Hann weight floored to 0.05 per axis. Source images, checkpoint, preprocessing and 65-pixel cluster grouping were unchanged. All image-derived breast foreground was scanned; physician rectangles did not guide inference. Original images were hash checked. Both aggregate receipts bind the same feedback and checkpoint hashes.

Evaluation used 46 reviewed crops from 23 source images and 59 physician region rectangles, excluding two non-mammographic crops. The baseline receipt is `generated-files/eagle-eye/calcification-candidate-20261001/physician-full-output-comparison-20261002.json`; the overlap receipt is `generated-files/eagle-eye/calcification-candidate-20261001/physician-overlap-output-comparison-20261002.json`. Scripts and sensitive annotation inputs are retained in protected research storage, outside the repository.

## Results

| Threshold | Baseline center-covered regions | Overlap center-covered regions | Baseline outside-region proposal centers | Overlap outside-region proposal centers |
|---|---:|---:|---:|---:|
| 0.1 | 36 | 36 | 419 | 406 |
| 0.3 | 46 | 45 | 288 | 283 |
| 0.5 | 51 | 50 | 201 | 198 |
| 0.7 | 53 | 53 | 126 | 121 |
| 0.9 | 41 | 42 | 38 | 38 |

At threshold 0.5, outside-region positive pixels fell from 22,661 to 8,772 (61.3%), while inside-region positive pixels were 24,331 versus 24,549. IoU >=0.25 region coverage was 20 versus 22. Both branches had at least three predicted pixels in all 59 reference regions. At threshold 0.7, that lenient pixel-occupancy coverage fell from 56 to 54 despite unchanged center coverage. This demonstrates why pixel-map improvements cannot alone establish improved finding detection.

Baseline runtime was 56.00 seconds; overlap runtime was 62.86 seconds (12.3% longer in these separate runs). Both peak allocated VRAM measurements were 2.196 GiB. Timing is descriptive, not a repeated randomized latency benchmark. Six synthetic constant-predictor checks passed, covering sub-tile, non-divisible and exact tile image sizes and both lateral orientations; restored geometry and blended constant outputs were correct. Both private experiment scripts passed Python compilation.

## Decision and limits

Retain overlap as a candidate ablation, not a selected clinical improvement. The modest proposal-count change does not solve excessive output burden; center coverage is mixed. Reduced outside-region pixel area may reflect suppressed tile-edge activations, but that mechanism has not been confirmed by a spatial edge analysis. No best architecture or threshold is established.

Counts are exploratory region proxies. Reviewed crops can overlap and repeat findings; source-coordinate deduplication remains pending. Broad region boxes do not delineate true puncta. Outside-region outputs are not all confirmed false positives, quality ratings are missing, and the cohort is selected development material. Threshold-specific comparisons do not substitute for calibrated, matched verified FP/image FROC.

The next discriminating step is label-ready native-detail/context verification: audit dense-mask data and confirmed artifact/background labels, group patients before patch extraction, and compare segmentation alone versus a trained compact two-scale verifier while counting true findings lost at the rejection stage. Full foreground inference must remain independent of physician boxes. Region labels may support weak supervision; they must not become fabricated all-positive pixel masks. No pretrained malignancy classifier should be presented as a calcification-versus-normal verifier.
