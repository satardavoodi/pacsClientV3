# Storm Knob Sweep

- Dataset: `c:/AI-Pacs codes/aipacs-pydicom2d/user_data/patients/dicom/1.2.840.1.99.1.47.1.1772527236103.85188/202`
- AI-PACS overlap scenario: `aipacs_live_download_overlap`
- AI-PACS common scenario: `common_local_viewing`
- ClearCanvas source root: `c:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`
- ClearCanvas desktop solution: `c:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master\Desktop\Desktop.sln`
- ClearCanvas image viewer solution: `c:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master\ImageViewer\ImageViewer.sln`

## Ranked profiles

| Profile | Storm Index | Balance Index | Overlap P95 ms | Overlap CPU P95 % | Common First Image ms | Common P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| `admit_batch_small` | 0.6761 | 0.7451 | 11.21 | 172.00 | 856.64 | 5.35 |
| `decode_service_off` | 1.0041 | 0.8464 | 11.52 | 176.86 | 682.32 | 4.12 |
| `baseline` | 1.0 | 1.0 | 12.82 | 167.65 | 1009.83 | 6.76 |
| `lazy_workers_2` | 1.2581 | 1.1523 | 13.08 | 183.90 | 1147.09 | 5.39 |
| `lazy_workers_1` | 1.303 | 1.2042 | 13.72 | 184.73 | 1148.86 | 6.59 |
| `prefetch_conservative` | 1.5665 | 1.3663 | 14.14 | 185.09 | 1161.89 | 7.19 |

## Notes

- Best current balance: `admit_batch_small` with balance index 0.7451 and storm index 0.6761.
- Lower Storm Index is better; it focuses on overlap interaction and CPU behavior versus AI-PACS baseline.
- Lower Balance Index is better; it rewards storm reduction while penalizing common-path and first-image regressions.
- ClearCanvas tolerance, when available, is checked with a 10% upper bound for lower-is-better metrics.

### Admission batch 5

- Smaller non-terminal progressive admission to spread burst shock over more ticks.
- Overlap vs baseline ratios: p95=0.8744, max=0.804, cpu=1.0259, slow16=0.0
- Common vs baseline ratios: first-image=0.8483, p95=0.7914

### Decode service off

- Disable subprocess decode service to measure whether IPC/process overhead helps or hurts this storm class.
- Overlap vs baseline ratios: p95=0.8986, max=1.0628, cpu=1.0549, slow16=1.0
- Common vs baseline ratios: first-image=0.6757, p95=0.6095

### Baseline

- Current defaults with no extra environment overrides.
- Overlap vs baseline ratios: p95=1.0, max=1.0, cpu=1.0, slow16=1.0
- Common vs baseline ratios: first-image=1.0, p95=1.0

### Lazy workers 2

- Cap lazy decode workers to 2 to reduce concurrency without full serialization.
- Overlap vs baseline ratios: p95=1.0203, max=0.9153, cpu=1.0969, slow16=2.0
- Common vs baseline ratios: first-image=1.1359, p95=0.7973

### Lazy workers 1

- Force a single lazy decode worker to reduce overlap concurrency and CPU spikes.
- Overlap vs baseline ratios: p95=1.0702, max=1.0399, cpu=1.1019, slow16=2.0
- Common vs baseline ratios: first-image=1.1377, p95=0.9749

### Conservative prefetch

- Shrink prefetch radii to reduce background decode pressure during overlap.
- Overlap vs baseline ratios: p95=1.103, max=1.0591, cpu=1.104, slow16=3.0
- Common vs baseline ratios: first-image=1.1506, p95=1.0636
