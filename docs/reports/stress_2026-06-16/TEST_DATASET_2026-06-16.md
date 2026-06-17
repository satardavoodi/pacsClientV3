# AI-PACS Stress Test Dataset (selected from live `dicom.db`, 2026-06-16)

Local DB totals: **940 patients · 1070 studies · 9080 series · 321,173 instances.**
Study modalities: MR 735, CT 135, DOC 90, DX 35, MR+DOC 22, MG 21, US 7, PX 1.

All IDs below are real `patient_id`s present locally unless marked *server-only*. Use these for both the automated and live (`LIVE_STRESS_RUNBOOK`) scenarios.

## Multi-study patients (one Patient ID, many studies)
| patient_id | name | #studies | total inst | modalities | use |
|---|---|---|---|---|---|
| **1** | GHOLAM HOSEINI^YAGHOB | **20** | 6062 | MR | Primary multi-study torture test; also exercises the report-status amplification fixed in F1 |
| 43802 | AMIRI SAMANESADAT | 4 | 1602 | MR | secondary |
| 44127 | BAHRAMIFAR ALIASGHAR | 4 | 334 | MR | secondary |
| 44345 | MOBASHERI^FATEMEH | 3 | 811 | MR | secondary |
| 40779 | AMRAEE^MOHAMAD REZA | 3 | 488 | MR | secondary |

## High-slice CT / MRI (deep stacks — scroll/decode/render)
| patient_id | modality | series | image_count | desc |
|---|---|---|---|---|
| **562346** | CT | 3 | **802** | +C (contrast) — deepest stack |
| 46492 | CT | 202 / 302 | 580 each | Tissue |
| 43977 | CT | 202 / 302 | 576 each | Tissue (also F3 disk>DB drift example) |

## Many-series / cardiac-style (many series, fewer cuts each)
| patient_id | modality | #series | inst | note |
|---|---|---|---|---|
| **40921** | MR | **135** | 4612 | Primary many-series test (fast series switching, thumbnail list, viewport replacement) |
| 43718 | MR | 79 | 1677 | secondary |
| 46370 | MR | 62 | 1910 | secondary |
| 46330 | (mixed) | 74 | 1496 | secondary |
| **46030** | — | — | — | ***server-only*** (not in local DB; nearest local IDs 46024/46040). Requested cardiac case — fetch live via server search to exercise the *open-non-downloaded-patient → download* path. |

## X-ray / DX (large single/few-image studies)
| patient_id | modality | inst | dimensions / note |
|---|---|---|---|
| **44876** | DX | 8 | **12488 × 4407 = 55 MP** (largest image in DB) |
| **42275** | DX | 10 | 10910 × 4363 = 47 MP (also most DX instances) |
| 42396 | DX | 8 | 8758 × 4361 = 38 MP |

## Mammography (MG — test separately; hanging/layout)
| patient_id | modality | series | inst |
|---|---|---|---|
| **42552** | MG | 5 | 5 |
| 44966 | MG | 5 | 5 |
| 45073 | MG | 5 | 5 |
| 45523 | MG | 5 | 5 |
| 44945 | MG | 5 | 5 |
| 46316 | MG | 5 | 5 |

## Download-manager pressure
- **Not-downloaded / server-only:** `46030` (above) and any patient whose study shows `db_ni > 0, actual = 0` (245 such studies). Open → start download → switch patient mid-download → reopen → confirm no duplicate task, correct resume.
- **Partial studies** (downloaded files < server total, e.g. `db_ni 398 / actual 396`): confirm the missing tail is fetched on reopen, not the whole study.

## Reproduction artifacts (scratch, this session)
`C:\Temp\aipacs_stress\` — `db_recon.py/json`, `log_scan.py`, `log_detail.py`, `stall_mine.py`, `consistency.py`, `run_pytest.py`, `run_tool.py` (all read-only analysis; reusable).
