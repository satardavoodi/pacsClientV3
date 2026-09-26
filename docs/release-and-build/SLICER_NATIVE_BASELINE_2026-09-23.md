# Definitive custom 3D Slicer build baseline (2026-09-23)

This is the native Advanced Viewer baseline for **both** AI-PACS Client
(Standard and x64-on-ARM64 emulation) and Eagle Eye Server, with either
PyInstaller or Nuitka. The product version is 3.6.7. A role selection changes
the model payload, not the Slicer executable. Do not use the older January
runtime, stock 3D Slicer, or a historical `slicer_runtime_v0.1.0.zip` for any
new build. Older Server installers were **not** rebuilt by the 2026-09-23
Client-only build and are not evidence of this baseline.

The portable VC143 correction made later on 2026-09-23 is part of this same
native baseline, not a new Slicer compilation. Future Client and Server builds
must use the VC143-containing runtime/cache below. The pre-VC143 3.6.7 cache
and existing installers are historical and must not be selected as a fallback.

## Authoritative locations on the preparation machine

| Purpose | Path |
|---|---|
| Native custom-app source (tracked) | `modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/` |
| Python startup and presentation source (tracked) | `modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py`, `presentation.py`, `unified_logging.py`, and `Qss/` |
| Space-free compiler source copy | `C:\S\app` |
| Pinned Slicer Git source, commit `ae061acd0f40570dcc1332920a2f6e370f1bd69d` | `C:\S\src` |
| CMake SuperBuild and dependency outputs | `C:\S\NB` |
| New inner native executable | `C:\S\NB\Slicer-build\bin\Release\AIPacsAdvancedViewer.exe` |
| Qt 5.15.2 MSVC SDK | `C:\Qt\5.15.2\msvc2019_64` |
| Canonical assembled Developer Run runtime | `modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build/` |
| Default immutable build-input cache, both roles | `generated-files/distribution-assets-native-3.6.7-vc143-20260923/` |
| Historical pre-VC143 build-input cache; do not use for new builds | `generated-files/distribution-assets-native-3.6.7-20260923/` |
| Existing Client-only cache used for the four 2026-09-23 installers | `generated-files/distribution-assets-client-v3.6.7-20260923-0015/` |
| Recoverable pre-VC143 Developer Run runtime | `generated-files/slicer-runtime-pre-vc143-20260923/` |

The compiled inner executable SHA-256 is
`275b7fc209de41a1610ff0105762f2090b428621640fd43f406fc16ecf62874e`.
The tracked native source digest recorded in `build/aipacs-native-build.json`
is `566a0816b49a97294d70ade41cbe42bb54668adeb3afa3aec94cda4fd707ab32`.
The SuperBuild additionally used pinned VTK
`e21c90bd874fb15f1dc34986c238462b8aab4af8`, ITK
`ac65b49c34fcfa3c3422a66026c7fe2bbaa88902`, and CTK
`3811bcaf0d84e9b43777e6422b2330b84baf2e0b`. Compiler paths are
machine-local and not Git artifacts; preserve a verified backup if migrating
the build machine.

### Portable compiler runtime correction

The custom Slicer binary was compiled with Visual Studio 2022 BuildTools
VC143 14.44. Its original portable assembly omitted compiler-matched CRT DLLs.
On the Windows Server 2022 pilot host, the unchanged binary therefore failed
native DLL initialization (`0xC0000142` / Win32 1114) against the older host
MSVC runtime. This was a runtime packaging defect, not evidence that a stock or
earlier Slicer should be restored. The source is the locally installed, official
BuildTools x64 app-local redistribution directory:

`C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Redist\MSVC\14.44.35112\x64\Microsoft.VC143.CRT`

`tools/slicer/assemble_slicer_runtime.py` now verifies those inputs before
touching an existing runtime, copies all ten into `bin/Release` beside the
native executable, and checks their SHA-256 values. The ten pinned names and
hashes are in `builder/slicer_runtime_payload.py::APP_LOCAL_VC_RUNTIME_HASHES`.
The essential `msvcp140.dll` SHA-256 is
`0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9`;
the native executable remains
`275b7fc209de41a1610ff0105762f2090b428621640fd43f406fc16ecf62874e`.
The same CRT hash check now gates both the Developer Run runtime and cached
build input. No System32 or global Visual C++ installation was changed.

The isolated server validation candidate is
`D:\Eagle Eye Server\slicer\20260923-vc143-candidate`. Its receipt at
`D:\Eagle Eye Server\logs\slicer-vc143-candidate-receipt.json` proves that all
7,836 original files match the preserved `20260923` baseline and exactly ten
app-local CRT DLLs were added. The ordinary launcher returned version
`3.6.7-` with exit code 0, and the existing no-main-window `slicer_probe.py`
returned `slicer_started=true`, VTK major 9, exit code 0. This validates native
startup on that host, not installed UI, models, clinical workflows, service
qualification, redistribution approval, or the current Client installers.

## Ordinary future AI-PACS build: no Slicer compilation

Read `RELEASE.md` and `BUILD.md` first. Their Git and role-selected candidate
routes remain authoritative. The coordinator defaults to the immutable cache
above and checks that its full Slicer runtime is byte-identical to the
Developer Run runtime and that both carry matching native-source provenance.
It also stages the current tracked startup script and presentation companions
into each package. A normal AI-PACS source change does **not** rerun CMake,
reassemble Slicer, or recreate this cache. Client and Server both use the same
native baseline by default; Client excludes Eagle Eye model assets from its
installer even though the shared build-input cache stores those assets.

For a read-only check before a future build:

```powershell
.\.venv\Scripts\python.exe tools\build\prepare_distribution_assets.py --check --profile all
.\.venv\Scripts\python.exe -c "from pathlib import Path; from builder.slicer_runtime_payload import verify_cache_matches_developer_runtime; p=Path.cwd(); verify_cache_matches_developer_runtime(p, p/'generated-files/distribution-assets-native-3.6.7-vc143-20260923')"
```

If only the AI-PACS-side Python startup/presentation source changes, the package
overlay and mirror guards must be rerun; the native binary does not need to be
recompiled. If **any file inside the assembled runtime** changes, create a fresh
immutable asset cache and verify parity before packaging; do not modify a
completed cache in place. If C++/CMake/Qt-resource/native input changes, or
native provenance no longer matches, follow the source-build guide below and
compile Slicer again. Do not bypass a parity failure by pointing the coordinator
at an old cache or by copying an older executable into `build/`.

## How this baseline was made; only repeat for a native change

The exact prerequisites, pinned source, CMake configuration, embedded Python
packages, assembly command, and verification procedure are in
[`../../modules/mpr/advanced_3d_slicer/slicer_custom_app/docs/BUILD_FROM_SOURCE.md`](../../modules/mpr/advanced_3d_slicer/slicer_custom_app/docs/BUILD_FROM_SOURCE.md).
In brief: the current tracked custom-app source was copied to `C:\S\app`;
`C:\S\NB` was configured against pinned `C:\S\src` and Qt 5.15.2; the Release
SuperBuild produced the inner executable; and
`tools/slicer/assemble_slicer_runtime.py` assembled the portable Developer Run
runtime after the Viewer processes were closed. The assembly wrote the native
source/executable provenance. A fresh Client cache and four Client installers
were then built. After the pilot-host CRT failure, a separate VC143 candidate
passed its receipt and startup tests. The corrected local runtime was assembled
again from the same compiler tree, verified, and promoted into Developer Run;
the prior runtime was retained at the rollback path above. A new shared all-role
cache reuses only hash-verified non-Slicer inputs from the pre-VC143 complete
cache and snapshots the corrected runtime. Its manifest and parity gate must
pass before either role is newly packaged.

The cache and compiled runtime are ignored by Git. A Git push alone does not
transport those large binaries to another builder; copy the verified immutable
cache and Developer Run runtime separately, then rerun the hashes and parity
checks. The cache is build input, not an installer or a production approval.

## Verification recorded on 2026-09-23

- The historical pre-VC143 complete shared cache passed independent per-file
  SHA-256 verification: 34,449 files / 4,307,604,656 bytes. It retains the
  offline model and both pinned wheel collections but is **not** a valid new
  packaging input after the portable-CRT finding. The corrected cache inventories
  34,459 files / 4,309,450,168 bytes: exactly the ten CRT files and 1,845,512
  bytes more. Its manifest retains the complete model and both wheel
  collections; `release_approved` remains `false`.
- Manifest-to-manifest comparison found all 34,449 historical files unchanged
  by path, length, and SHA-256; exactly ten `slicer-runtime/bin/Release/*.dll`
  files were added, with no removed or otherwise changed files. The earlier
  complete cache is retained as a non-Slicer donor/rollback reference, not a
  valid installer input.
- Independent `prepare_distribution_assets.py --check --profile all` verified
  all 34,459 recorded lengths and SHA-256 values. Full
  `verify_cache_matches_developer_runtime` passed for the corrected default
  cache and canonical Developer Run runtime. The pre-VC143 cache failed that
  same parity gate because its app-local CRT is absent.
- Its selected Slicer files matched the assembled Developer Run runtime
  byte-for-byte, including the native provenance record.
- Focused builder/source/runbook tests: 61 passed. The broader builder suite:
  218 passed; one pre-existing checkout-local stage configuration test failed
  because that diagnostic stage predates the current templates. This is not
  evidence that a Server installer has been rebuilt or accepted.
- Installed Client and Server GUI acceptance remains separate. No production
  deployment, Git publication, or fresh Server installer is claimed here.
