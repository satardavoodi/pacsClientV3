# Three distribution outputs and offline build assets

Current Eagle Eye requirement (2026-09-07): both Brain and Lumbar offline assets
are required. The historical lumbar-only cache described below is insufficient.
See [Brain delivery](../../docs/modules/EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md) for the
portable candidate, source override, distribution evidence and unresolved clean
Windows gate. Standard and ARM exclude the `eagle_eye` Brain payload as well as
the legacy `offline_lumbar` payload. Shared Slicer remains installed in all editions.

Prepared: 2026-08-31. Updated: 2026-09-06.

> Start at [`../../BUILD.md`](../../BUILD.md) for the canonical human/AI workflow.
> This document defines payload and asset details. The shared distribution profiles
> now apply to both PyInstaller and Nuitka; direct backend commands below are useful
> for diagnosis but are not the official combined release entry point.

## Output contract

The default build now requests all three outputs from one frozen x64 core:

| Edition | Versioned output name | Included image AI assets | Platform |
|---|---|---|---|
| Eagle Eye | `ai-pacs eagle-eye v<version>.exe` | Custom Slicer, background/runtime integration, complete offline TotalSegmentator `vertebrae_mr` CPU environment, Dataset756 weights and notices | Windows x64 |
| Standard | `ai-pacs standard v<version>.exe` | Existing core, optional modules, and standard Advanced MPR/Slicer runtime; no Eagle Eye offline lumbar environment or weights | Windows x64 |
| ARM | `ai-pacs arm64-emulated v<version>.exe` | Same Slicer-without-Eagle-Eye-model policy as Standard | Windows on ARM, x64 emulation; **not native ARM64** |

The ARM choice preserves the user's established emulation-first platform strategy
in `docs/plans/architecture/ARM64_WINDOWS_PLATFORM_PLAN_2026-07-07.md`.
It uses the existing ARM-only Inno wrapper and `x64_on_arm64` runtime profile.
Hardware graphics and emulation acceptance still require an ARM computer.
[Microsoft's emulation documentation](https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation)
explains the distinction from native ARM applications.

Eagle Eye's Advanced MPR component is mandatory for both installer types; it is
not a checkbox that silently omits the model. A missing runtime, integration module,
model manifest, environment or checkpoint fails preparation/packaging. Its named
local analysis operations are described in
[the resident runtime guide](../../docs/modules/ADVANCED_ANALYSIS_RESIDENT_RUNTIME.md).
This is the selected, implemented MR vertebral model, not every TotalSegmentator
task or every third-party Slicer extension. MedSAM Lite and additional MONAI
checkpoints have not been integrated or claimed as bundled features. The two
external Eagle Eye LLM providers still need their normal configuration/network;
local segmentation does not make those services offline.

Standard preserves the 3.6.3 capability baseline: the Advanced MPR package and
standard Slicer runtime are physically present and installed by default. Only the
Eagle Eye-specific `offline_lumbar` environment, weights, and
`AIPacsOfflineLumbar.py` module are physically absent. The package feed therefore
continues to advertise Advanced MPR as available. ARM follows the same payload
policy under x64 emulation. Eagle Eye is the only edition that adds the complete
offline lumbar environment and model.

## Size baseline and enforcement

The existing version-3.6.3 x64 installer is **628,247,370 bytes** (approximately
599 MiB); its ARM compatibility installer is **628,247,380 bytes**. Its stage
contains 813,234,047 bytes of Advanced MPR/Slicer runtime. The first 3.6.5 profile
incorrectly removed that entire package and produced a 442,928,735-byte Python
Standard installer. That reduction was missing functionality, not improved
compression. Standard and ARM now retain the Slicer runtime and exclude only the
2,266,104,815-byte uncompressed Eagle Eye offline-lumbar payload.

Standard and ARM target the current compressed size. A completed installer over
**700,000,000 bytes** fails the compact-edition size gate; it is not silently
accepted or trimmed by removing clinical functionality. Override only deliberately
with `--compact-max-mb`. Actual new installer sizes are unknown until a fresh
release build. Eagle Eye is necessarily larger; no invented compressed size is
reported. Installing Standard over an earlier Eagle Eye installation does not
erase existing models or patient data, so it is not an installed-size cleanup tool.

## Assets available locally

Cache: `generated-files/distribution-assets/` (ignored by Git).
The completed inventory contains **34,529 files, 4,329,814,502 bytes** (about
4.33 GB / 4.03 GiB), excluding diagnostic logs and the outer inventory itself.
An independent final `--check` verified every recorded length and SHA-256 hash.

| Directory/artifact | Contents |
|---|---|
| `slicer-runtime/` | 7916 files / 811,813,491 bytes; assembled custom Slicer `ae061ac`, required Qt/Python/native libraries and package resources |
| `offline_lumbar/` | 26,305 files / 2,266,104,815 bytes; validated CPU model bundle, interpreter, weights, adapter and licenses |
| `model-wheels/` | 92 exact model-environment wheels for Python 3.12 on Windows x64 |
| `build-wheels/` | 89 exact installed workstation/build-environment wheels for Python 3.13 on Windows x64 |
| `downloads/` | Original pinned Python 3.12 embedded archive and Dataset756 archive, plus Python 3.13.5 x64 installer |
| `inno-setup/` | Local copy of the installed Inno compiler/resources, excluding its uninstaller |
| `*-environment.lock` | Complete distribution metadata from each interpreter, including stdlib-shadowing package distributions |
| `*-wheels-hashed.lock` | Exact versions and SHA-256 hashes for offline dependency installation |
| `manifest.json` | Per-file path, length and SHA-256 inventory; platform, model, offline resolution status and explicit `release_approved: false` |

The Python 3.13.5 installer has a **Valid Authenticode signature from the Python
Software Foundation**. The custom Slicer cache uses a top-level runtime allowlist:
local `Kitware, Inc` settings, `_test_dicom.py`, and root probe state are excluded.
Required dependency `examples`, `testing`, and other resources are retained.
Do not use this cache as a patient workspace or add credentials to it.

Both wheel collections passed a dependency-resolution dry run using
`--no-index --require-hashes --ignore-installed`, without installing packages or
accessing an index. The first model dry run exposed `argparse==1.4.0`: it was
installed but omitted by `pip freeze`. Preparation now captures actual
distribution metadata, downloads that wheel too, and requires the complete offline
resolution check to pass. Public source-only packages were converted to wheels;
the active workstation and model environments were not upgraded.
[pip's offline collection options](https://pip.pypa.io/en/stable/cli/pip_download/)
describe using local packages with `--find-links` and `--no-index`.

These are all inputs for the supported local model/runtime and the current build
environment. They do not constitute a native ARM toolchain, Windows SDK/MSVC
offline installation kit, source checkout backup, signing certificate, or proof
of all third-party redistribution rights. The cache must be copied separately to
another build machine because it is intentionally not committed to Git.

## Commands

Verify the cache without downloading anything:

```powershell
.\.venv\Scripts\python.exe tools/build/prepare_distribution_assets.py --check
```

Prepare a **new** cache on a connected preparation machine:

```powershell
.\.venv\Scripts\python.exe tools/build/prepare_distribution_assets.py --download-wheels --root E:/BuildAssets/AI-PACS
```

An already completed cache is not overwritten by normal preparation. The explicit
`--refresh-wheels` operation verifies the old inventory first, refreshes locked
wheels from the current environments, checks offline resolution, and records a
new inventory. Preparation uses the already assembled custom Slicer and the prior
`generated-files/offline-lumbar/bundle`; it does not fetch an unrelated stock Slicer
or run its extension-install UI.

When release prerequisites are satisfied, follow the single coordinator command
in root [`../../BUILD.md`](../../BUILD.md). It creates all three editions for both
backends. For one diagnostic edition, use only the explicitly non-promotable
internal snapshot lane documented there; do not invoke `build.py` from the
developer checkout. Git publication and the required receipt are governed by
[`../../RELEASE.md`](../../RELEASE.md), with the complete route indexed at
[`../../docs/release-and-build/README.md`](../../docs/release-and-build/README.md).

Use `--asset-root E:/BuildAssets/AI-PACS` for another verified cache. Every
three-edition build now requires the verified cache because every edition contains
the standard Slicer runtime. Eagle Eye additionally consumes the offline lumbar
environment and weights. New metadata is an installer edition stamp inside the
existing installation profile; no feature-flag family, licensing bypass, or
provider secret is added.

After installing the cached Python through the normal approved bootstrap, an
isolated build environment can resolve packages completely offline:

```powershell
python -m venv .venv_build
.\.venv_build\Scripts\python.exe -m pip install --no-index --find-links generated-files/distribution-assets/build-wheels --require-hashes -r generated-files/distribution-assets/build-wheels-hashed.lock
```

Do not run that creation command over the existing development environment during
ordinary work. For a compiler-only machine, `AIPACS_ISCC_EXE` can point to the
cached `inno-setup/ISCC.exe`; an invalid explicit compiler path fails rather than
silently choosing another version. Native ARM experimentation remains the
separate legacy `--arch arm64 --edition legacy` path with its own hardware and
dependency prerequisites.

## Output and publishing behavior

Final PyInstaller outputs go directly to `builder/output/installer/`. Final
Nuitka outputs go directly to `builder nuitka/output/installer/`. Each folder
contains its own versioned Eagle Eye, Standard and ARM64-emulated EXEs plus
`distributions.json`, `INSTALL_NOTES.txt`, `INSTALL_NOTES_FA.txt`, `SHA256.txt`
and `SHA256_FA.txt`. The compatibility `_FA` filenames contain the same English
release metadata until an explicitly approved localization is supplied.

Edition views and Inno compiler output are prepared under a unique short
`<drive>:\ap-stage\r-*` directory to remain below the Windows path limit. This is
temporary compiler input, never a delivery or release-output location. Final
files are hash-verified and atomically moved into the existing backend installer
folder only after every requested edition compiles successfully.
`--skip-installer-compile` records only a temporary `status: staged` inventory,
never `compiled`. Hard links are used for immutable files where possible, with
copy fallback; profile feeds and metadata are independent files.

Every requested edition is required. A compiler failure, missing expected EXE,
oversize compact installer or incomplete Eagle Eye payload prevents a successful
inventory; the code never substitutes a stale EXE found in another directory.
Temporary stage directories may remain for diagnosis but are not a completed set.
No `output/distributions` delivery tree is created.

**The three-edition path does not publish updates or upload artifacts.** The old
single-installer feed cannot safely choose among these editions. `--edition legacy`
preserves the prior artifact names and publishing behavior for deliberate legacy
use; do not use it as an approval bypass. The resumable PyInstaller wrapper calls
`build.py`, so its stages inherit the new default; restart from stage 1 for a new
release instead of trusting an old completed resume state.

## Verification and release limits

- Focused distribution/model/ARM/packaging/resident tests: **84 passed**, direct
  pytest exit code 0.
- Actual Inno compiler syntax checks: Standard, ARM and Eagle Eye pass with
  synthetic fixture files and `/O-` (installer output disabled). Eagle Eye with a
  missing model manifest fails as required. Reproduce with
  `tools/build/verify_distribution_installer.py`.
- The Slicer installer resource guard failed before correction: the old wildcard
  excluded dependency `examples` directories required by the runtime. It now
  preserves these resources as well as the separate model environment.
- The broader neighboring suite still reports **7 known baseline failures**:
  one stale staged `patient_table_sort.json` parity check and six existing Nuitka
  ARM parity failures. The Nuitka build/script files are unchanged from HEAD.
  None was hidden by a success-only test wrapper or marked as newly passing.
- No full release build, upgrade install, disconnected customer-PC run, ARM
  hardware test, or clinical accuracy validation was performed here.

Before customer packaging/publishing, resolve the committed-credential issue in
`docs/reports/CODEX_REPOSITORY_READINESS_2026-08-27.md`, reconcile the release test
baseline, qualify the combined installer on clean machines, and review licensing
and clinical claims. Assets being locally complete is not release approval.
