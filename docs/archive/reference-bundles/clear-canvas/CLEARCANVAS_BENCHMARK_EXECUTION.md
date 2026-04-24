# ClearCanvas Benchmark Execution

**Date:** 2026-04-15  
**Scope:** Practical side-by-side benchmark execution design for AI-PACS FAST and ClearCanvas  
**ClearCanvas checkout inspected:** `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master`

---

## 1. ClearCanvas Build And Launch Status

### Current status

**ClearCanvas cannot currently be built on this machine as-is.**

### Verified blockers

1. **Missing .NET Framework 4.0 targeting pack**
   - Verified by build probe:
   - `dotnet msbuild C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master\Desktop\Executable\ClearCanvas.Desktop.Executable.csproj /t:Build /p:Configuration=Release`
   - Error:
     - `MSB3644: The reference assemblies for .NETFramework,Version=v4.0 were not found.`

2. **Missing `ReferencedAssemblies` checkout**
   - ClearCanvas `README.md` requires a sibling `ReferencedAssemblies` repository.
   - This checkout currently does **not** contain:
     - `C:\AI-Pacs codes\ClearCanvas-master\ClearCanvas-master\ReferencedAssemblies`
     - `C:\AI-Pacs codes\ClearCanvas-master\ReferencedAssemblies`

3. **Legacy Visual Studio/MSBuild toolchain expectations**
   - Solution file is Visual Studio 2013.
   - The post-build flow expects old MSBuild/SDK tooling such as:
     - `corflags`
     - `editbin`
     - `VS100COMNTOOLS`
   - Some parts of the tree also reference native/interop dependencies and legacy libraries from `ReferencedAssemblies`.

### What was identified as the minimal viewer launch target

- **Primary solution to build:** `ImageViewer/ImageViewer.sln`
- **Minimal executable project:** `Desktop/Executable/ClearCanvas.Desktop.Executable.csproj`
- **Main executable after build:** `ClearCanvas.Desktop.Executable.exe`
- **Default launch root:** `ClearCanvas.Desktop.Application`

### Why `ImageViewer.sln` is the realistic target

Building only the executable project is not enough for a useful benchmark run, because the viewer needs the image viewer plugins and distribution files copied by the post-build packaging flow.

### Smallest realistic path to viewer launch

1. Install Visual Studio Build Tools or Visual Studio with legacy .NET Framework support.
2. Install the **.NET Framework 4.0 Developer Pack / Targeting Pack**.
3. Obtain the required **`ReferencedAssemblies`** repository and place it where ClearCanvas expects it.
4. Build `ImageViewer/ImageViewer.sln`.
5. Launch the generated `ClearCanvas.Desktop.Executable.exe`.
6. Open a local DICOM study or directory in the running UI.

---

## 2. Chosen Execution Path

Because ClearCanvas is not currently runnable in this environment, the benchmark workflow is designed in two layers:

### Layer 1: Directly comparable benchmark

- same fully local DICOM dataset
- AI-PACS measured through headless run and/or UI process monitor
- ClearCanvas measured through process monitor plus manual operator actions

### Layer 2: AI-PACS-only overlap diagnostics

- active download plus live viewing
- AI-PACS log parsing
- internal FAST KPIs

### Optional approximate ClearCanvas stress analogue

If desired, ClearCanvas can also be run under **background staged file-copy pressure**. This is **not equivalent** to AI-PACS progressive live growth, but it is useful as a low-confidence external stress analogue.

---

## 3. Benchmark Dataset Assumptions

### Mode 1: Local identical dataset

This is the primary fair comparison mode.

- one stable local DICOM folder
- same study/series for both apps
- no mutation during the direct comparison run

### Mode 2: AI-PACS progressive/live case

This is **AI-PACS-only** unless future ClearCanvas verification proves otherwise.

- AI-PACS opens a series while data is still downloading or growing
- ClearCanvas has no verified equivalent live-progressive viewer path in this environment

### Optional Mode 3: ClearCanvas background copy pressure

- ClearCanvas opens the same fully local series
- a separate staged copy of DICOM data runs in parallel
- this adds external IO/CPU pressure only
- this does **not** emulate viewer-side progressive growth

---

## 4. Benchmark Phases

| Phase | Meaning |
|---|---|
| `A` | Initial open |
| `B` | Early interaction on partially available or freshly opened data |
| `C` | Active scrolling |
| `D` | Mixed-load overlap |
| `E` | After completion / settled state |

---

## 5. Step Mapping Between AI-PACS And ClearCanvas

The step model is stored in:

- `tests/performance/clearcanvas_aipacs_benchmark_model.json`

### Core direct-comparison steps

| Step ID | Phase | AI-PACS action | ClearCanvas action | Confidence |
|---|---|---|---|---|
| `S1` | `A` | Launch AI-PACS FAST and prepare local open | Launch ClearCanvas and prepare local open | High |
| `S2` | `A` | Open same local study/series | Open same local study/series | High |
| `S3` | `B` | Confirm first usable image and first scrollable frame | Same | High |
| `S4` | `C` | Scroll 10 slices slowly | Scroll 10 slices slowly | High |
| `S5` | `C` | Fast burst through dense series section | Closest equivalent fast burst | Medium |
| `S6` | `C` | Direction reversal stress | Direction reversal stress | High |
| `S7` | `E` | Stop and let viewer settle | Stop and let viewer settle | High |
| `S8` | `E` | Reopen same series | Reopen same series | High |

### AI-PACS-only overlap steps

| Step ID | Phase | AI-PACS action | ClearCanvas equivalent | Confidence |
|---|---|---|---|---|
| `S9` | `D` | Start download and open while incomplete | None verified | Low |
| `S10` | `D` | Scroll during active download/progressive growth | None verified | Low |
| `S11` | `D` | Reverse direction during overlap | None verified | Low |
| `S12` | `E` | Observe completion, cache warm, settle | None verified | Low |

### Optional approximate ClearCanvas stress-only steps

| Step ID | Phase | AI-PACS equivalent | ClearCanvas action | Confidence |
|---|---|---|---|---|
| `S13` | `D` | None direct | Launch under background staged copy pressure | Low |
| `S14` | `D` | None direct | Scroll while background copy is active | Low |
| `S15` | `E` | None direct | Stop and wait for copy/UI settle | Low |

---

## 6. KPI Capture Rules

### Directly comparable KPIs

| KPI | AI-PACS capture | ClearCanvas capture | Comparability |
|---|---|---|---|
| `first_image_visible_ms` | headless run or manual/UI timing | manual/UI timing | Direct |
| `set_slice_present_p95_ms` | headless run or manual step timing | manual step timing | Approximate-direct |
| `cpu_p95_pct` | process monitor | process monitor | Direct |
| `rss_peak_mb` | process monitor | process monitor | Direct |
| `thread_count_p95` | process monitor | process monitor | Direct |
| `read_mb_delta` | process monitor | process monitor | Direct |
| `write_mb_delta` | process monitor | process monitor | Direct |
| `longest_ui_gap_ms` | headless/runtime instrumentation | not currently instrumented | AI-PACS-strong, ClearCanvas weak |

### AI-PACS-only internal diagnostics

| KPI | Capture method |
|---|---|
| `terminal_completion_duplicate_count` | `parse-aipacs-log` |
| `cache_warm_duplicate_count` | `parse-aipacs-log` |
| `stale_task_ratio` | headless FAST metrics |
| `cache_hit_ratio_pct` | headless FAST metrics |
| `decode_p95_ms` | headless FAST metrics |
| `frame_render_p95_ms` | headless FAST metrics |

### Two-level result model

#### Level 1: shared external metrics

- time to first visible image
- step timing
- CPU
- RSS
- threads
- disk IO

#### Level 2: AI-PACS internal diagnostics

- decode
- cache behavior
- duplicate lifecycle activity
- UI gap instrumentation

This split is intentional and honest. ClearCanvas currently does not emit the same internal diagnostics in this workflow.

---

## 7. What Is Automated And What Is Manual

### Automated now

- AI-PACS headless benchmark run
- external process monitoring for either app
- AI-PACS log parsing
- execution-pack generation
- comparison markdown generation from JSON payloads

### Manual now

- building ClearCanvas
- launching a working ClearCanvas viewer build
- opening the local dataset in ClearCanvas
- performing ClearCanvas scroll actions
- recording manual step timings/observations where no automation exists

### Approximate/manual only

- any ClearCanvas stress run meant to mimic AI-PACS live progressive overlap

---

## 8. Benchmark Workflow Files

- `tools/performance/clearcanvas_aipacs_kpi_harness.py`
- `tests/performance/clearcanvas_aipacs_scenarios.json`
- `tests/performance/clearcanvas_aipacs_benchmark_model.json`
- `tests/performance/test_clearcanvas_aipacs_kpi_harness.py`
- `tools/performance/run_clearcanvas_manual_benchmark.ps1`

The PowerShell wrapper:

1. generates an execution pack
2. launches ClearCanvas
3. runs process monitoring for the selected scenario
4. leaves a manual CSV for operator timings and notes

### What each file is for

| File | Purpose |
|---|---|
| `tools/performance/clearcanvas_aipacs_kpi_harness.py` | main CLI for AI-PACS headless runs, external-process monitoring, execution-pack generation, log parsing, manual-result normalization, and comparison |
| `tests/performance/clearcanvas_aipacs_scenarios.json` | scenario durations, KPI targets, and benchmark step envelopes |
| `tests/performance/clearcanvas_aipacs_benchmark_model.json` | benchmark phase and step correspondence between AI-PACS and ClearCanvas |
| `tools/performance/run_clearcanvas_manual_benchmark.ps1` | helper to launch ClearCanvas, generate the execution pack, and collect process metrics |
| `tests/performance/test_clearcanvas_aipacs_kpi_harness.py` | regression tests for the benchmark harness and file contract |

### Fast file map for AI agents

If another agent needs to continue this work, the minimum useful read set is:

1. `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`
2. `tests/performance/clearcanvas_aipacs_scenarios.json`
3. `tests/performance/clearcanvas_aipacs_benchmark_model.json`
4. `tools/performance/clearcanvas_aipacs_kpi_harness.py`

### Standard result folder contract

Use one output folder per benchmark run, for example:

- `generated-files/benchmarks/run_001/`

Expected files inside a common local-comparison run:

| File | Produced by | Meaning |
|---|---|---|
| `instructions.md` | `emit-execution-pack` | operator-facing step list |
| `manual_step_results.csv` | `emit-execution-pack`, then filled by operator | manual timings and notes |
| `result_manifest.json` | `emit-execution-pack` | run manifest and expected outputs |
| `aipacs_common.json` | `run-aipacs-headless` | AI-PACS common local KPI JSON |
| `clearcanvas_process_metrics.json` | `monitor-process` or PowerShell wrapper | raw ClearCanvas process metrics |
| `clearcanvas_common.json` | `summarize-manual-results` | normalized ClearCanvas KPI JSON |
| `comparison.md` | `compare` | side-by-side KPI comparison |
| `aipacs_overlap.json` | `run-aipacs-headless` | AI-PACS overlap-only headless metrics |
| `aipacs_overlap_log.json` | `parse-aipacs-log` | AI-PACS overlap-only runtime diagnostics |

### How to extract ClearCanvas KPIs from the test files

This is the intended flow once ClearCanvas is buildable.

1. Generate the execution pack.
2. Run ClearCanvas with process monitoring.
3. Fill `manual_step_results.csv` for the ClearCanvas rows.
4. Normalize the manual CSV plus process JSON into one KPI JSON.

The normalization command is:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py summarize-manual-results `
  --manual-csv generated-files\benchmarks\run_001\manual_step_results.csv `
  --process-json generated-files\benchmarks\run_001\clearcanvas_process_metrics.json `
  --app clearcanvas `
  --viewer-label ClearCanvas `
  --output generated-files\benchmarks\run_001\clearcanvas_common.json
```

This command extracts:

- `first_image_visible_ms` from manual step `S2` or `S13`
- `set_slice_present_p95_ms` from manual scroll steps `S4`, `S5`, `S6`, and optional `S14`
- `cpu_p95_pct`, `rss_peak_mb`, `thread_count_p95`, `read_mb_delta`, `write_mb_delta` from the ClearCanvas process JSON

### Important honesty rule for ClearCanvas KPI extraction

- Process KPIs are automated.
- Step timings are currently manual.
- ClearCanvas internal decode/cache lifecycle KPIs are **not** currently available in this workflow.
- Therefore `clearcanvas_common.json` is a normalized external-metrics payload, not an internal instrumentation dump.

---

## 9. Step-By-Step Execution Procedure

### A. Prepare prerequisites

1. Make ClearCanvas buildable:
   - install .NET Framework 4.0 targeting pack
   - obtain `ReferencedAssemblies`
   - build `ImageViewer/ImageViewer.sln`
2. Prepare one stable local DICOM dataset for both apps.
3. Choose an output folder for benchmark artifacts.

### B. Prepare the execution pack

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py emit-execution-pack `
  --scenario common_local_viewing `
  --viewer both `
  --dataset C:\path\to\dicom-series `
  --output-dir generated-files\benchmarks\run_001
```

This creates:

- `instructions.md`
- `manual_step_results.csv`
- `result_manifest.json`

### C. Run AI-PACS common local benchmark

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py run-aipacs-headless `
  --dataset C:\path\to\dicom-series `
  --scenario common_local_viewing `
  --output generated-files\benchmarks\run_001\aipacs_common.json
```

### D. Run ClearCanvas common local benchmark

After ClearCanvas is buildable, either:

#### Option 1: use the wrapper

```powershell
tools\performance\run_clearcanvas_manual_benchmark.ps1 `
  -ExecutablePath C:\path\to\ClearCanvas.Desktop.Executable.exe `
  -Scenario common_local_viewing `
  -OutputDir generated-files\benchmarks\run_001
```

#### Option 2: manual launch + direct monitor

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py monitor-process `
  --scenario common_local_viewing `
  --process-name ClearCanvas.Desktop.Executable `
  --label ClearCanvas `
  --output generated-files\benchmarks\run_001\clearcanvas_process_metrics.json
```

While that runs, follow `instructions.md` and fill `manual_step_results.csv`.

Then normalize the result:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py summarize-manual-results `
  --manual-csv generated-files\benchmarks\run_001\manual_step_results.csv `
  --process-json generated-files\benchmarks\run_001\clearcanvas_process_metrics.json `
  --app clearcanvas `
  --viewer-label ClearCanvas `
  --output generated-files\benchmarks\run_001\clearcanvas_common.json
```

### E. Run AI-PACS overlap diagnostics

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py run-aipacs-headless `
  --dataset C:\path\to\dicom-series `
  --scenario aipacs_live_download_overlap `
  --output generated-files\benchmarks\run_001\aipacs_overlap.json
```

If a real runtime log is available:

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py parse-aipacs-log `
  --log C:\path\to\aipacs.log `
  --output generated-files\benchmarks\run_001\aipacs_overlap_log.json
```

### F. Generate comparison markdown

```powershell
.venv\Scripts\python.exe tools\performance\clearcanvas_aipacs_kpi_harness.py compare `
  --left generated-files\benchmarks\run_001\aipacs_common.json `
  --right generated-files\benchmarks\run_001\clearcanvas_common.json `
  --output generated-files\benchmarks\run_001\comparison.md
```

---

## 10. Result Table Structure

### Step-level table

| Step ID | Scenario | AI-PACS time | ClearCanvas time | AI-PACS CPU | ClearCanvas CPU | Notes | Fairness |
|---|---|---:|---:|---:|---:|---|---|

### KPI summary table

| KPI | AI-PACS | ClearCanvas | Gap | Interpretation |
|---|---:|---:|---:|---|

### Internal AI-PACS diagnostics table

| KPI | AI-PACS value | Interpretation |
|---|---:|---|

### How these tables should be populated

- Step-level table:
  - use `manual_step_results.csv`
  - use `instructions.md` and benchmark model step IDs
- KPI summary table:
  - use `aipacs_common.json`
  - use `clearcanvas_common.json`
  - use `comparison.md` for the first generated interpretation
- Internal AI-PACS diagnostics table:
  - use `aipacs_overlap.json`
  - use `aipacs_overlap_log.json`

---

## 11. Exact Next Run Procedure

The next concrete step is:

1. Make ClearCanvas buildable by installing the missing .NET Framework 4.0 targeting pack and obtaining `ReferencedAssemblies`.
2. Build `ImageViewer/ImageViewer.sln`.
3. Generate an execution pack for `common_local_viewing`.
4. Run AI-PACS local benchmark.
5. Run ClearCanvas local benchmark with process monitor and manual operator steps.
6. Generate the first common comparison markdown.
7. Run AI-PACS overlap benchmark and treat it as AI-PACS-only or low-confidence approximate when compared against any ClearCanvas stress analogue.
