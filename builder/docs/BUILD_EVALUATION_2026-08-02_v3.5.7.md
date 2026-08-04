# AI‑PACS build pipeline — evaluation + v3.5.7 release report

**Date:** 2026‑08‑02
**Source:** `beta-version` @ `37a59f4d` — *release(v3.5.7)*, working tree clean
**Builder:** Dr.Alizadeh PC · `E:\ai-pacs\ai-pacs codes\ai-pacs beta version` · `.venv_build`
· Python 3.13.5 · PyInstaller 6.11.1 · PySide6 6.10.2 · VTK 9.6.1 · cv2 4.13.0 · Inno Setup 6

---

## Part 1 — Release result (v3.5.7)

### Artifacts produced

| Artifact | Size | SHA‑256 |
|---|---|---|
| `ai-pacs installer v3.5.7.exe` (x64) | 631,032,652 B (601.8 MB) | `B3845F312132BAE45DCB5309F9D894AEA79C832CCC596688AAC03F8670588216` |
| `ai-pacs installer.exe` (same build) | 631,032,652 B | *identical to above* |
| `ai-pacs installer arm64-emulated v3.5.7.exe` (WoA SKU) | 631,032,588 B | `96C65E0F27DC6F3F4C77C10F249883540B755C624055039ABEF7882AE5D9D1E0` |
| `ai-pacs installer arm64-emulated.exe` | 631,032,588 B | *identical to above* |

Plus `SHA256.txt` / `SHA256_FA.txt`, `INSTALL_NOTES.txt` / `INSTALL_NOTES_FA.txt`, and the
incremental update bundle: **8,908 files, 7,999 new blobs / 909 reused, 536,876,571 B store**.

Location: `builder\output\installer\` · update feed: `builder\output\updates\`

**Nuitka SKU (second builder, completed the same day — see §4.3):**

| Artifact | Size | SHA‑256 |
|---|---|---|
| `ai-pacs installer v3.5.7.exe` (Nuitka) | 739,586,824 B (705.3 MB) | `7F2AD44790A09148D600C3DE11EC785D96D479D45D6249E7D558D8D781D12F01` |

Location: `builder nuitka\output\installer\` (+ `nuitka_installer_release_metadata.json`).
App exe `Engine\AIPacs.exe` (133.2 MB) carries FileVersion **3.5.7.0**.

### Gate results — all green

```
[PASS] source_freshness      HEAD=37a59f4d2e branch=beta-version
[PASS] plugin_mirrors        422 mirror pair(s) match, 0 plugin-only, 422 checked
RELEASE_GATE: PASS (pre-build)

[OK]   [MPR_GEOMETRY_GATE] frozen MPR geometry verified.
[OK]   Stamped engine/version.json (3.5.7)

[PASS] frozen_runtime_pyz    catalog ids match source (14 ids); 4/4 sentinels present
[PASS] stage_config_parity   26 config templates match sanitized expectation; no centre values
[PASS] stage_plugin_packages all 7 optional packages staged
[PASS] education_payload_set 37 education .py files mirrored 1:1
RELEASE_GATE: PASS (post-stage)

[WARN] stage_binary_architecture   1 of 831 binaries is x86: engine\speech_recognition\flac-win32.exe
```

### Independent verification (re‑run after the build, not just log‑reading)

- Post‑stage gate re‑executed standalone → **all four checks PASS, exit 0**.
- Config leak scan on the *staged* `engine/config` → **0 leaks**.
- Version resources: setup EXEs = 3.5.7, staged `AIPacs.exe` = 3.5.7,
  `engine/version.json` = `{"version": "3.5.7", "built_at_utc": "2026-08-02T17:55:55Z"}`.

### Timings (clean build, ~55 min wall clock)

PyInstaller Analysis→EXE ≈ 5.5 min · COLLECT ≈ 1.3 min · CD Lite Viewer sub‑build ≈ 1 min
(self‑test PASSED, 105.9 MB, 50.6 MB pruned) · x64 ISCC **960 s** · WoA ISCC **621 s** ·
delta publish ≈ 2 min.

---

## Part 2 — How the pipeline works

`build.py` is a 3‑line forwarder to `builder/build_release.py` (1,707 lines) — one process,
eleven sequential phases:

| # | Phase |
|---|---|
| 1 | PID‑checked build lock (stale locks auto‑reclaimed) |
| 2 | Selective clean, driven by `--clean-build` / `--skip-*` |
| 3 | **Release gate, pre‑build** — source freshness + plugin mirrors |
| 4 | `graphics_runtime/` validation (3 Mesa DLLs) *before* the long run |
| 5 | PyInstaller → `dist/AIPacs`, plus a second PyInstaller run for the CD Lite Viewer |
| 6 | Theme QSS sync, bundle graphics re‑check, **frozen‑MPR‑geometry PYZ gate** |
| 7 | Stage → `stage/core`, stamp `engine/version.json` |
| 8 | Advanced‑MPR payload validation, optional module packages, manifest |
| 9 | **Release gate, post‑stage** + PE‑machine architecture scan |
| 10 | ISCC → installer (+ optional WoA SKU), SHA256 + install notes |
| 11 | Update feed / content‑addressed delta store, optional remote publish |

`run_resumable_build.py` splits this into two checkpoints (stage 1 = everything but ISCC,
stage 2 = ISCC only).

---

## Part 3 — What is strong

**The gate system.** Every gate traces to a specific past incident and blocks a specific
class of silent regression:

- `source_freshness` — refuses a tree behind upstream or on a non‑release branch. Exists
  because a second build PC once sat on the ancient `DR.vahid` branch and froze v2.2.x code.
- `plugin_mirrors` — 422 SHA‑compared pairs. Plugin payloads *override* the frozen engine at
  runtime, so drift there ships old code invisibly.
- `MPR_GEOMETRY_GATE` — greps the **frozen PYZ bytecode** for named symbols. Checking the
  `.py` on disk proves nothing when `module_collection_mode={"modules": "pyz+py"}`.
- `frozen_runtime_pyz` — staged exe's embedded catalog ids must equal source `MODULE_CATALOG`.
- `stage_config_parity` + `education_payload_set` — the latter is a file‑*set* comparison,
  which catches a new canonical file that a payload→canonical hash walk can never see.

**Build‑time config sanitization.** The repo's `config/` holds the dev centre's real PACS IPs,
EchoMind `api_key` and Google OAuth `client_secret`, and the frozen app seeds bundled config
into every client on first run. The spec now generates a sanitized tree and **aborts the
build** if a scan still finds centre values. Build and gate share one manifest so they cannot
disagree. Verified again today: 0 leaks in the shipped tree.

**Fail‑fast ordering.** The cheap checks run before the 20‑minute PyInstaller run; the
expensive frozen‑artifact checks run before the 16‑minute ISCC compile.

---

## Part 4 — Findings

### 4.1 No code signing — the biggest gap
No `SignTool`, `SignedUninstaller` or certificate step exists anywhere in `builder/`. Every
centre installing an unsigned 630 MB executable meets a SmartScreen "unrecognized app" wall,
and there is no tamper evidence on a clinical binary. An OV/EV certificate wired into
`[Setup] SignTool=` is the single highest‑value addition to this pipeline.

### 4.2 Nuitka chain has silently lost all ARM64 / WoA support — **verified regression**
The project directive requires both builders to work on x64 *and* ARM64.

- `550d73d5` (*"…ARM64 installers"*) added `--arch`, `--with-woa-installer` to
  `builder nuitka/build_nuitka_release.py` and the full `ARM64_BUILD` / `WOA_EMULATED_BUILD` /
  `ResolvedInstallPackageKind()` / `IsArm64` block to `AIPacs_Nuitka_Setup.iss`.
- `69382766` (**release v3.5.3**) removed it: `−171 / +17` lines across exactly those two
  files. Current `HEAD` has **zero** matches for any of those symbols.
- The PyInstaller side (`builder/installer/AIPacs_Setup.iss`) is untouched and still correct.
- **The wrappers survived.** `AIPacs_Nuitka_Setup_arm64.iss` and `_woa.iss` still
  `#define ARM64_BUILD 1` and `#include "AIPacs_Nuitka_Setup.iss"` — but that file no longer
  reads the symbol. Compiling either today produces a **plain x64 installer wearing an ARM64
  name**, which is worse than a hard failure.
- The guard test `tests/code/builder/test_nuitka_arm64_parity.py` is **6 of 7 failing** and
  has been red since v3.5.3 — four releases with an ignored merge gate.

*Restoration — better than expected.* `HEAD` is **byte‑identical to `69382766`** for both
files (nothing has touched them since v3.5.3), so the reversal is clean and carries no
unrelated changes. A ready‑to‑review patch is at
`builder/docs/ARM64_RESTORE_nuitka_2026-08-02.patch` (294 lines: 4 hunks in the `.py`,
7 in the `.iss`), generated with
`git diff HEAD 550d73d5 -- "builder nuitka/build_nuitka_release.py" "builder nuitka/installer/AIPacs_Nuitka_Setup.iss"`
and **verified with `git apply --check` (exit 0)**. Apply it, then run
`pytest tests/code/builder/test_nuitka_arm64_parity.py` — it should go 7/7.

### 4.3 Nuitka needs a Developer environment — SOLVED, and the Nuitka build then COMPLETED

**Outcome — Nuitka v3.5.7 built successfully**, all stages 02→10, driver exit 0:

| | Nuitka | PyInstaller (x64) |
|---|---|---|
| `ai-pacs installer v3.5.7.exe` | **739,586,824 B (705.3 MB)** | 631,032,652 B (601.8 MB) |
| SHA‑256 | `7F2AD44790A09148D600C3DE11EC785D96D479D45D6249E7D558D8D781D12F01` | `B3845F31…70588216` |
| app exe | `Engine\AIPacs.exe` 133.2 MB, FileVersion **3.5.7.0** ✅ | `AIPacs.exe`, 3.5.7 ✅ |
| stage tree | 4.73 GB | 2.32 GB |

Stage timings (this run, stages 2–10 ≈ 100 min): st10 ISCC **1,617.9 s**. Upgrade detection
verified correct — the Nuitka `.iss` prefers `Engine\AIPacs.exe` (which carries the version
resource) and falls back to `{app}\AIPacs.exe`, so `GetVersionNumbersString` succeeds.

Two parity gaps vs the PyInstaller SKU, both minor:
- the Nuitka **setup EXE itself carries no version resource** — `AIPacs_Setup.iss:72` has
  `VersionInfoVersion={#MyAppVersion}`, the Nuitka `.iss` has no equivalent line;
- no WoA/ARM64 SKU is producible at all — see §4.2.

**Root cause of the earlier failure: run the Nuitka pipeline with `vcvarsall.bat x64`
active.** Nuitka/SCons cannot
auto‑discover the VS 2022 **BuildTools** edition on this machine (it finds Community/Pro/
Enterprise only). Proof: `python -m nuitka --msvc=latest --version` reports
`cannot locate suitable C compiler` from a plain shell, and
`Version C compiler: cl (cl None)` after `call vcvarsall.bat x64`. Stage 2 then passes.

The version‑drift theory was **wrong and is disproved**: the committed July report
(`nuitka_stage_02_qt_shell.xml`) records `nuitka_version="4.1.3"` — the same version
installed now — with `c_compiler="MSVC" the_cc_name="cl"`. `requirements-nuitka.txt` pins
`nuitka==4.1.3` (bumped from 4.0.8 on 2026‑07‑07) and the venv matches it. **The July build
worked because it ran in a Developer environment; today's plain shell fell back to zig.**

Symptoms seen before the fix — stages 0/1 pass, **stage 2 (Qt Shell) fails both ways**:

- **zig 0.16.0** (auto‑selected): compiles fine, but the produced PySide6 standalone binary
  dies at startup — `Fatal Python error: Failed to import encodings module`.
- **`--compiler msvc`**: the driver prints `[WARN] --msvc=latest selected, but vcvarsall.bat
  was not found`, then Nuitka reports `cannot locate suitable C compiler`.

The toolchain is physically present and complete: MSVC **14.44.35207** with
`cl.exe` at `…\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\`, `vcvarsall.bat`
present at `…\2022\BuildTools\VC\Auxiliary\Build\`, Windows SDK 10.0.26100.0. So the driver's
own MSVC probe is looking in the wrong place — it appears not to consider the **BuildTools**
edition, only Community/Professional/Enterprise.

**Durable fixes (not applied):** (a) teach the driver's `vcvarsall.bat` probe to look under
the `BuildTools` edition — today it emits a false‑negative WARN; (b) have the driver refuse
to silently fall back to zig for a PySide6 stage, since that fallback produces a binary that
compiles but cannot start. A hard failure there would have named this problem in seconds
instead of after two full stage runs.

### 4.4 The Nuitka installer ships 2.6 GB of build intermediates — including generated C source
Measured in the completed v3.5.7 Nuitka stage tree:
`builder nuitka/output/stage/core/Engine/generated-files/` = **2,639.8 MB across 7,547 files**

| kind | files | size |
|---|---|---|
| `.c` (Nuitka‑generated C source) | 2,698 | **1,179.6 MB** |
| `.o` (object files) | 1,375 | 1,070.1 MB |
| `.const` | 2,691 | 33.2 MB |
| `.dll` / `.exe` | 74 | 93.6 MB |

The PyInstaller stage does **not** contain this directory (verified). Two consequences:

1. **Size** — it accounts for essentially all of the Nuitka SKU's +103.5 MB over PyInstaller
   (the `.c`/`.o` files compress well, but they are still shipped), and it is why stage 10's
   ISCC pass ran 1,617.9 s.
2. **It partly defeats the point of using Nuitka.** The `.c` files are the transpiled program
   logic, complete with string constants — shipping them to customers gives away more than a
   `.pyc` would. If Nuitka was chosen for compiled‑code protection, this cancels it.

Root cause: the Nuitka stage assembly copies `generated-files/` wholesale into `Engine/`, and
`generated-files/build/lite_viewer/` holds the Lite Viewer's Nuitka `.build` directory —
Nuitka logs `Keeping build directory …` by design. Fix: exclude `generated-files/**/*.build/`
(or `generated-files/build/`) from the Nuitka stage's data copy, the same way
`spec_utils.get_privacy_exclude_patterns()` already excludes build dirs on the PyInstaller
side. **Not applied — awaiting your decision.**

### 4.5 The release artifact is written to disk four times
`installer/` keeps both `ai-pacs installer.exe` and `…v3.5.7.exe` (byte‑identical, 601.8 MB
each), and `publish_update_bundle` copies **both** again into `updates/core/` — ~2.4 GB of
duplicate bytes per release, on a drive that started this build with 23.9 GB free. Hardlinks,
or shipping only the versioned name plus a pointer, would reclaim ~1.8 GB per release.

### 4.6 Build output is block‑buffered → poor live observability
`build.py` spawns `build_release.py` without `-u`, so the orchestrator's own `print()` lines
sit in an 8 KB buffer while ISCC's subprocess output streams straight through. The log
interleaves out of order and every gate verdict appears minutes late — during this build the
gate lines did not reach the log until the process exited.
**APPLIED 2026‑08‑02:** `build.py` now forwards `-u`. Verified with `py_compile` and
`build_release.py --help`.

### 4.7 A missing ISCC was a warning, not an error
If `ISCC.exe` was absent, `compile_installer` printed `[WARN]`, returned `None`, and the
build still exited 0 while publishing an update feed whose core entry is `available: false`
— a "successful" release with no shippable artifact.
**APPLIED 2026‑08‑02:** it now raises `SystemExit` when an installer was actually requested
(`--skip-installer-compile` remains the supported way to build staging only), with
`AIPACS_ALLOW_MISSING_ISCC=1` as a deliberate escape hatch. Verified with `py_compile` and
`--help`.

### 4.8 The x64 architecture scan is warn‑only — and enabling it would fail today
`check_stage_binary_architecture` only enforces on arm64. Today's run flagged exactly one
file: `engine\speech_recognition\flac-win32.exe` (x86, out of 831 scanned). It is benign on
x64 and ARM64 (both emulate x86), but it means **turning on `AIPACS_ENFORCE_ARCH_SCAN=1`
without an allow‑list entry for that file would break the build.** Add the allow‑list, then
enforce.

### 4.9 Gate bypasses are documented but leave no trace
`--skip-release-gate`, `AIPACS_ALLOW_STALE_MPR_PYZ=1`, `AIPACS_SKIP_SOURCE_FRESHNESS=1` all
exist and the runbook says "never for a customer release" — but nothing enforces that and
nothing records their use. Stamping any bypass into `stage/manifest/` would make a bypassed
artifact impossible to mistake for a clean one months later.

### 4.10 The Advanced‑MPR payload ships CPython's test suite
Observed directly in the ISCC compression log, inside
`stage/plugin_packages/advanced_mpr/payload/python-install/`:
`Lib\test\test_setcomps.py`, `Lib\test\test_tkinter\test_messagebox.py`,
`Lib\site-packages\pydicom\data\test_files\…`, `Lib\site-packages\pip\_vendor\…`.
A vendored CPython with `Lib/test`, pip's vendored packages and pydicom's DICOM test corpus is
being compressed into every installer. Pruning it is the largest available size win.

### 4.11 `builder nuitka/output/` is tracked in git
Build state, checkpoints and Nuitka XML reports are committed. Today's Nuitka run therefore
dirtied the working tree (6 modified/deleted files) purely by running. Those files should be
gitignored — build output does not belong in the repo.

### 4.12 Minor
- `verify_frozen_mpr_geometry` is MPR‑specific; the same PYZ‑symbol technique would cover the
  other lazily‑imported subsystems hand‑pinned in the spec (the `modules.network.ino_*` set).
- The Advanced‑MPR payload check verifies file *presence*, not version — a stale Slicer
  runtime passes.
- 16 historical `build_v3.x.log` files (~2.4 MB each, none newer than v3.2.1) sit in
  `builder/output/`; log retention is inconsistent.

---

## Part 5 — Verdict

On the **correctness** axis this pipeline is better defended than most commercial Windows
build chains: it does not trust the filesystem, it inspects the frozen bytecode, and every
gate is a scar from a real incident. Nothing in its design blocked the v3.5.7 release, and the
artifact produced today is verified clean.

The weaknesses are elsewhere: **distribution trust** (no code signing), **an unnoticed ARM64
regression that four releases of a red guard test failed to surface**, **disk economy**, and
**observability**. In priority order:

1. Code signing (§4.1)
2. Restore Nuitka ARM64/WoA + get the guard test green (§4.2) — patch is ready and verified;
   and find out why a red builder test went unnoticed for four releases
3. Stop shipping Nuitka's generated `.c`/`.o` intermediates (§4.4) — 2.6 GB, and it cancels
   the code‑protection reason for using Nuitka in the first place
4. Make the Nuitka driver find the BuildTools edition, and refuse the silent zig fallback
   that produces a non‑bootable binary (§4.3)
5. Payload pruning (§4.10) and artifact de‑duplication (§4.5)

Both SKUs for v3.5.7 are built and verified. `-u` live gate visibility (§4.6) and the
non‑zero exit on a missing ISCC (§4.7) were applied during this session.
