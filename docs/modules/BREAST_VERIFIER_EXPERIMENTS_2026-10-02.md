# Sequential calcification verifier experiments

Executed 2026-10-02. All candidates are research-only. Production weights and services were unchanged.

## Acquisition and supervision

The original KIOS discovery referred to version 1. The latest publisher record is [version 3](https://zenodo.org/records/14859694), whose update aligns reference JPEG dimensions with DICOM inputs. The archive directory contains 400 DICOMs, 400 JPEG references and 103 directories; uncompressed size is about 10.86 GB. The publisher checksum for the 3,036,405,780-byte ZIP is MD5 `6169bd77ac56da37c67407f9acbfe7da`. Full archive acquisition/checksum verification remains pending in this snapshot. Bounded samples were extracted through CRC-checked ZIP reads with path traversal protection.

Eight initial image/reference pairs were geometrically aligned and 12-bit MONOCHROME2. Reference files contain red calcification markings and, for suspicious cases, blue circles. Color-derived centers are provisional localization supervision, not validated dense masks. Original DICOM pixels, not colored JPEGs, are used as model inputs.

An initial seven-patient acquisition subset supplied a native-detail/context patch pilot. Four views/timepoints of each patient stay together. Positives were sampled at bounded red connected-component centers; negative patches only from Normal_cases patient groups whose four reference images contained neither red nor blue markings. Background in positive images was never labeled normal. This remains a restricted publisher-annotation assumption needing full metadata/semantic audit. Physician unmarked crops were not imported as negatives because quality fields remain unknown; owner clarification is pending.

## Actual optimizer experiments

| Candidate | Training groups / held-out groups | Updates | Held-out patch AUROC | Patch sensitivity at train-positive quantile threshold | Negative patch activation |
|---|---|---:|---:|---:|---:|
| Detail/context CNN, average pooling, 20 epochs | 4 / 2 | 180 | 0.4966 | 0.9091 | 0.7969 |
| Detail/context CNN, average pooling, 100 epochs | 5 / 2 | 900 | 0.7023 | 0.9870 | 0.8281 |
| Detail/context/local-contrast CNN, max pooling, 100 epochs | 5 / 2 | 900 | 0.9735 | 0.8961 | 0.0078 |

The first experiment had 279 training patches. The second and third had the same 281 training and 205 held-out patches (77 positive, 128 negative). The initial dataset changed as the bounded subset finished acquisition, so the 20-versus-100 comparison is not a pure epoch ablation. Equal-budget 100-epoch comparison shows average pooling alone remains unsuitable for rejection. Max pooling and a contrast channel changed together; attribution to either requires separate ablation.

The held-out cohort has only two patients. Thresholds used a fifth-percentile positive training score, not independent calibration. Patch AUROC does not establish autonomous localization, NPV, screening utility or full-image FROC. Both 100-epoch candidates passed saved state-dictionary reload/output equality checks. Peak allocated VRAM was about 0.129 GiB. Training timing excludes data preparation and is not end-to-end serving cost.

## Transfer test of the promising patch candidate

The max/contrast candidate was tested as an image-only cascade on the existing 23 source images and 46 physician-reviewed crops. DeepMiCa generated connected components at probability 0.5. For each component of at least two pixels, the most confident native pixel selected a 128-pixel detail crop and a 256-pixel context crop; a local Gaussian-residual channel was added. The verifier score was attached to the original component pixels before unchanged 65-pixel cluster grouping. Physician rectangles never guided candidate generation or patch sampling at inference.

| Verifier threshold | Regions containing proposal centers / 59 | Regions with at least three retained pixels / 59 | Outside-reference proposal centers |
|---|---:|---:|---:|
| No verifier; DeepMiCa 0.5 | 51 | 59 | 201 |
| 0.1 | 26 | 28 | 37 |
| 0.3 | 23 | 23 | 32 |
| 0.5 | 23 | 23 | 29 |
| 0.7 | 21 | 21 | 28 |
| 0.9 | 20 | 20 | 28 |

Runtime was 59.23 seconds and peak allocated VRAM 2.205 GiB. This candidate is rejected for current transfer use: output burden falls substantially, but region coverage collapses even at the lowest tested verifier threshold. Local patch scores did not transfer to the existing research-image pipeline. Domain/preprocessing shift, missing positive morphologies, negative-sampling mismatch and color-center supervision are competing explanations; this test does not isolate their causes.

All counts remain development proxies, not true-punctum sensitivity or confirmed false positives. Repeated crop overlap is not deduplicated. Aggregate receipts are under `generated-files/eagle-eye/calcification-candidate-20261001/`: `patch-verifier-avg20-20261002.json`, `patch-verifier-avg100-20261002.json`, `patch-verifier-maxcontrast100-20261002.json`, and `physician-cascade-output-comparison-20261002.json`. Scripts, datasets, individual records and weights remain in protected research storage outside the repository.

## Next discriminating work

Complete archive checksum, native DICOM/annotation semantics and person-grouped metadata audit. Preserve the current development cohort as consumed research material. Establish complete same-domain negative truth before hard-negative training. The owner has been asked only to resolve image assessability for the already declared normal crops, not to repeat annotation.

Then train or adapt using same-domain confirmed artifact/background patches and native-detail positives, with region weak supervision where dense masks are absent, and replay of external data. Compare recall losses at every rejection stage. Do not promote the patch classifier merely because its small-source AUROC is high. A larger GPU is not justified by the measured memory footprint.
