# AI-PACS canonical build and installer runbook

Status: authoritative for the current three-edition Windows build matrix.
Audience: human maintainers and AI agents.

Documentation map: [`docs/release-and-build/README.md`](docs/release-and-build/README.md).

This is the single entry point for creating AI-PACS installers. Backend-specific
documents explain implementation details and historical recovery, but they do not
replace this procedure. If another build document conflicts with this file, stop
and update the conflicting document before building.

## Non-negotiable interpretation of a build request

An unqualified owner request such as "build", "make a new build", or "build the
current version" always means exactly six installers: three PyInstaller editions
and three Nuitka editions. The lane changes prerequisites and promotion status; it
never changes that matrix or its final destinations. Do not ask whether the owner
wants one backend, silently select one edition, or report an internal diagnostic
artifact as a completed build.

The only exception is an explicit request containing words such as "diagnostic",
"one backend", or a named single edition. That request may use the internal lane
and remains non-promotable. If a full build is interrupted, continue or recover
the same immutable candidate according to this runbook; do not switch to a backend
script or invent a new output route.

Final deliverables have exactly two writable destinations:

- `builder/output/installer/` for the three PyInstaller installers.
- `builder nuitka/output/installer/` for the three Nuitka installers.

The coordinator CLI intentionally has no final-output-directory override. `C:\b`,
`C:\ap-stage`, backend `dist`/`stage` trees, logs, checkpoints, and `_superseded`
are scratch or evidence only. A human or agent must not copy, rename, deliver, or
describe files from those locations as the requested build.

## Canonical six-installer command

When the owner asks to "make a build", this is the required workflow. After
`RELEASE.md` has produced a fresh synchronization receipt, create the complete
candidate with one command:

```powershell
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --git-sync-receipt <receipt-path>
```

The official lane always builds both backends and all three editions. It writes
final files only to the established backend installer folders. Missing Eagle Eye
Brain approval is checked before the snapshot, asset-cache verification, Lite
Viewer build, or application compilation begins.

The short timestamped directory under `C:\b` is compiler scratch space only. It
exists to avoid Windows path-length failures and preserve reproducible logs. It is
not a third output hierarchy, and no installer may be delivered from it. A build
request is complete only when the six versioned files and their metadata are in
`builder/output/installer/` and `builder nuitka/output/installer/`.

### Optional single-package diagnostic

Use the following only when the owner explicitly requests an internal packaging
diagnostic for one backend/edition. It does not satisfy a request to "make a
build" and it never updates the two canonical installer folders:

```powershell
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py --internal
```

The diagnostic defaults to Standard PyInstaller. `--backend nuitka` or
`--edition eagle-eye` / `--edition arm` selects another explicit diagnostic target.
Its isolated output is deliberately non-promotable.

### Local six-installer install QA

When the owner explicitly requests installable local artifacts before Git or legal
distribution approval, use the same six-output matrix in local install-QA mode:

```powershell
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --local-install-qa
```

This mode builds PyInstaller and Nuitka for Eagle Eye, Standard, and ARM64-emulated
and writes them to the same two canonical repository folders. It validates the
technical Brain payload but does not claim redistribution approval, publication,
signing, or production acceptance. Its installers are for local installation QA
only until the remaining release gates pass.

Versioned Git publication is governed by `RELEASE.md`. A full release candidate
cannot start until the exact clean source commit is synchronized to every required
remote branch and its fresh receipt is available.

## 1. Supported deliverables

Eagle Eye asset update (2026-09-14): its payload requires Brain volumetry,
Brain MS lesion analysis and Lumbar. The lesion bundle defaults to
`generated-files/eagle-eye/brain-lesions`; set `AIPACS_EAGLE_EYE_LESION_SOURCE`
for an explicit prepared source. Standard/ARM exclude the lesion model/runtime.
See [lesion payload evidence](docs/modules/EAGLE_EYE_BRAIN_MS_LESION_DESIGN.md).
Brain preparation, distribution-evidence requirements and remaining clean
Windows acceptance are documented in
[Eagle Eye Brain delivery](docs/modules/EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md).
The earlier lumbar-only asset cache does not satisfy this new contract. The
coordinator automatically uses `generated-files/eagle-eye/brain-tf212-py310` or an
explicit `--brain-source`. Do not bypass the payload validation to build an
incomplete Eagle Eye installer. Standard and ARM exclude both Eagle Eye models.

A complete release candidate contains six standalone Windows installers. Both
backends use one core build and then create three edition views.

| Backend | Edition | Required filename | Runtime policy |
|---|---|---|---|
| Python/PyInstaller | Eagle Eye | `builder/output/installer/ai-pacs eagle-eye v<version>.exe` | x64, Slicer, and offline Brain/Lumbar assets |
| Python/PyInstaller | Standard | `builder/output/installer/ai-pacs standard v<version>.exe` | x64 and Slicer; no Eagle Eye Brain/Lumbar assets |
| Python/PyInstaller | ARM64 emulation | `builder/output/installer/ai-pacs arm64-emulated v<version>.exe` | x64-on-ARM64 and Slicer; no Eagle Eye Brain/Lumbar assets |
| Nuitka | Eagle Eye | `builder nuitka/output/installer/ai-pacs eagle-eye v<version>.exe` | x64, Slicer, and offline Brain/Lumbar assets |
| Nuitka | Standard | `builder nuitka/output/installer/ai-pacs standard v<version>.exe` | x64 and Slicer; no Eagle Eye Brain/Lumbar assets |
| Nuitka | ARM64 emulation | `builder nuitka/output/installer/ai-pacs arm64-emulated v<version>.exe` | x64-on-ARM64 and Slicer; no Eagle Eye Brain/Lumbar assets |

ARM64 emulation is not a native ARM64 binary. Do not rename or describe it as
native ARM64.

Each backend installer folder must also contain its current release metadata,
`distributions.json`, `INSTALL_NOTES.txt`, `INSTALL_NOTES_FA.txt`, `SHA256.txt`,
and `SHA256_FA.txt`. A folder named `_superseded` contains historical evidence;
never distribute from it.

## 2. One fixed matrix, three validation lanes

Do not build six installers after every source edit. Select the narrowest lane
that answers the current question. An artifact may move only from a stricter lane,
never from a faster lane by renaming it.

Lane selection is not edition selection. Both the receipt-backed release lane and
the local install-QA lane always produce the same six-file matrix in the same two
repository folders. Only the explicitly requested internal diagnostic lane may
produce fewer files, and those files never enter the canonical installer folders.

| Lane | When to use it | Output | Release status |
|---|---|---|---|
| Source validation | Every normal code change | Tests and Developer Run evidence | No installer; never distributable |
| Internal packaging validation | Installer/profile work or focused QA | Synthetic Inno check or one isolated edition | Disposable; never promote or distribute |
| Full release candidate | Source is frozen and the owner requests a candidate | All six installers from one isolated snapshot | Eligible for install QA; not production until all release gates pass |

On the 2026-09-06 reference machine, the complete 3.6.5 matrix took about
2 hours 54 minutes. PyInstaller took about 62 minutes and Nuitka about 112 minutes.
The six Inno compression passes consumed about 96 minutes in total; Nuitka Stage 6
consumed about 49 minutes. These are measurements, not universal promises.

The completed 3.6.6 local install-QA run on 2026-09-10 provides a second baseline.
Exact-input PyInstaller repackaging took about 49 minutes. Nuitka took about 3 hours
15 minutes, including about 54 minutes for Stage 6 and about 63 minutes for Stage
10. The three Nuitka Inno compiles themselves consumed about 60 minutes. Recovery
overhead makes this a conservative comparison, but it confirms that native compile
and repeated standalone-installer compression remain the dominant costs.

The completed 3.6.7 local install-QA run on 2026-09-21 used the canonical recovery
route after an infrastructure interruption. PyInstaller took about 69 minutes,
Nuitka Stage 6 took about 41 minutes, and the successful resumed Stage 10 took about
62 minutes. Recovery reused the completed PyInstaller backend and valid same-snapshot
Nuitka checkpoints; it did not recompile Stage 6. Interruption overhead is excluded
from those stage measurements.

The safe immediate speed improvement is procedural: perform source validation on
every change, use a single isolated edition only when installer behavior needs
inspection, and run the complete matrix once after source freeze. Do not increase
Nuitka parallelism on this machine: serial `--jobs=1`, low-memory mode, no LTO, and
the MSVC `/Od` Stage 6 override are stability controls added after real compiler
heap failures.

## 3. Preconditions for every full candidate

### 3.1 Build-machine bootstrap

The supported host is Windows 10/11 x64 with Python 3.13.5, Inno Setup 6, MSVC,
and the repository's `.venv_build`. On a new build machine, use the existing
bootstrap once:

```powershell
.\setup_build_env.ps1
```

Do not use `-Force` during an ordinary release; it destroys and recreates the
build environment and changes the toolchain being qualified. After bootstrap,
verify PyInstaller, Nuitka, PySide6, VTK, SimpleITK, pydicom, and Inno Setup before
starting a multi-hour run. Use the immutable offline asset cache described in
`builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md` rather than downloading
dependencies during a release.

The r15 evidence occupied about 17.6 GiB in its candidate workspace and another
23.0 GiB across the two short Inno staging trees, in addition to the 4.03 GiB
asset cache and final installers. Keep at least 60 GiB free on the candidate/stage
drive before a full matrix. Failed candidate and stage trees are evidence; do not
delete them automatically or with a broad wildcard. Archive or remove only an
explicitly reviewed path after the release is superseded.

### 3.2 Candidate checks

1. Read this file, `RELEASE.md`, and the current version release note.
2. Confirm the owner has accepted the current Developer Run as the candidate input.
3. Complete the canonical Git release workflow. The worktree must be clean and
   the exact current HEAD/version must have a fresh multi-remote synchronization
   receipt under `generated-files/release-git/`. Preserve unrelated work and do
   not switch, pull, reset, or clean a dirty checkout automatically.
4. Confirm `pyproject.toml`, `main.py`, and the Information-panel version guard
   agree. The requested version must equal `pyproject.toml`.
5. Use Python 3.13.5 from `.venv_build` and run `pip check`.
6. Verify plugin mirrors. Run the sync tool only after reviewing drift and deciding
   that the source tree is authoritative.
7. Verify the immutable distribution asset cache. Never rebuild or partially
   replace the cache during a release run.
8. Run focused tests directly with pytest and check its process exit code. The
   repository readiness report says the historical wrapper can mask failures.
9. Ensure the candidate drive and `C:` have adequate space. The verified asset
   cache is about 4.33 GB, the Eagle Eye uncompressed model is about 2.27 GB, and
   each backend needs additional temporary compiler and installer space.
10. Do not start the workstation, an installer, or another full build while the
    release candidate is running.

Minimum commands from the repository root:

```powershell
git status --short
& .\.venv_build\Scripts\python.exe -m pip check
& .\.venv_build\Scripts\python.exe tools\dev\verify_plugin_mirrors.py
& .\.venv_build\Scripts\python.exe tools\build\prepare_distribution_assets.py --check
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
$env:AIPACS_SKIP_GIT_FETCH = "1" # Test isolation only; the candidate runner removes this override.
& .\.venv\Scripts\python.exe -m pytest -p no:debugging `
  tests/code/echomind/test_credential_obfuscation.py `
  tests/code/builder/test_canonical_build_runbook.py `
  tests/code/builder/test_distribution_profiles.py `
  tests/code/builder/test_release_candidate_packaging.py `
  tests/code/builder/test_codec_bundling.py `
  tests/code/builder/test_installer_legal_notices.py `
  tests/code/builder/test_windows_qt_icu_hygiene.py `
  tests/code/builder/test_nuitka_arm64_parity.py `
  tests/code/dicom_media/test_dicom_vm_normalization.py `
  tests/code/cd_burner/test_lite_viewer_autobuild.py `
  tests/code/cd_burner/test_lite_viewer_core.py `
  tests/code/test_home_info_panel.py -q
$testExit = $LASTEXITCODE
Remove-Item Env:AIPACS_SKIP_GIT_FETCH
if ($testExit -ne 0) { exit $testExit }
```

EchoMind credential protection is a required pre-build check for both backends.
The center registry and its plugin mirror must contain only authenticated encrypted
provider envelopes, never plaintext provider keys or center access codes. Keep
`credential_envelope.py` and `center_registry.py` in the EchoMind package and retain
the `cryptography` runtime dependency. Do not copy the administrator's `API.md`,
development credentials, or authenticated local settings into installer inputs.
The owner-approved TEST center is the end-user demo and is enabled by default. A
restricted deployment can remove demo access by setting
`AIPACS_ENABLE_DEMO_CENTER=0`; the legacy `AIPACS_ALLOW_TEST_CENTER` flag remains
readable for compatibility. During human-operated clean-machine install QA, enter
the authorized demo code and verify the matching active center and a synthetic
model response; never include credentials in QA evidence. Provider-side quota,
billing, monitoring, and rotation are owned by GapGPT and are intentionally outside
the desktop client's activation contract.
Client-side encryption raises extraction effort but cannot hide an authorized
center's decrypted key from someone controlling that running workstation.

Any failed prerequisite blocks the full build. Fix the cause; do not disable the
gate. `AIPACS_SKIP_GIT_FETCH` above is scoped only to deterministic unit tests;
`build_local_candidate.py` removes inherited `AIPACS_SKIP_*` and `AIPACS_ALLOW_*`
values before invoking the real release gates.

## 4. Canonical full-matrix command

The coordinator creates a new short workspace on `C:` automatically. The command
creates an isolated, sanitized, content-addressed snapshot, compiles both backends
sequentially, writes the six final files only to the established repository
installer folders, and runs cross-backend coherence. It never publishes or
launches the workstation.

```powershell
$version = & .\.venv_build\Scripts\python.exe -c "import pathlib,tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
$releaseHead = git rev-parse HEAD
$receipt = "generated-files\release-git\v$version-$($releaseHead.Substring(0, 12)).json"
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --git-sync-receipt $receipt
```

The candidate workspace is evidence. Keep its `build_status.json`, backend logs,
`coherence.log`, `source/build_source_manifest.json`, Nuitka checkpoints, and XML
report until the release is accepted or superseded.

## 5. Safe faster paths

### 5.1 Source validation: normal development path

Run the relevant direct pytest selection and use the source Developer Run. Do not
create installers merely to check a Python behavior. This is the normal path for
most commits.

### 5.2 Synthetic installer validation

When only the Inno script or edition profile is being reviewed, use the compiler-
only synthetic matrix. It verifies Standard, ARM64-emulated, Eagle Eye, and the
missing-model rejection without producing a customer installer or compiling the
application core.

```powershell
& .\.venv_build\Scripts\python.exe tools\build\verify_distribution_installer.py
```

### 5.3 One isolated edition for internal QA

If an install screen or one edition must be inspected before source freeze,
run the same coordinator in its internal lane. It prepares the snapshot and runs
only the requested backend/edition. The output remains inside the candidate
snapshot and must never replace a canonical six-file set.

```powershell
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py --internal
```

Add `--edition eagle-eye` or `--edition arm` only when that exact edition is the
test target. For a Nuitka-specific internal check, use:

```powershell
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --internal --backend nuitka
```

These single-edition outputs are diagnostic. They do not pass the six-artifact
coherence contract and cannot be promoted.

### 5.4 Exact-input PyInstaller repackaging

`tools/build/repackage_candidate.py` may reuse a prior PyInstaller core only when
its recorded core-input map and every current hash match exactly. It reruns the
pre-build, post-stage, and frozen-MPR gates. A mismatch requires a fresh compile.
The canonical coordinator exposes this as `--reuse-python-source`; it still builds
Nuitka freshly and still requires a new candidate workspace.

This path is appropriate for a packaging retry with an unchanged frozen core. It
is not appropriate after application, dependency, spec, runtime-resource, plugin,
or version changes. Never copy a prior `dist` manually.

### 5.5 Same-candidate interruption recovery

Nuitka checkpoints are useful only inside the same immutable candidate after an
infrastructure interruption. `--resume` must reject changed source, version, or
toolchain identity. Do not transplant checkpoints between candidates. A recovered
backend is not complete until all selected stages, installer metadata, hashes, and
cross-backend coherence pass and the recovery is recorded.

Resume through the same root coordinator, never by choosing a backend command:

```powershell
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --resume-workspace C:\b\<exact-candidate-directory>
```

The coordinator infers the recorded release/local-QA lane, revalidates the immutable
source and external asset locations, refuses a still-running recorded process,
skips a backend only when it completed with exit code 0 and all three of its
canonical installers still exist, and resumes Nuitka only across the release stages
`0, 6, 7, 8, 9, 10`. It then reruns cross-backend coherence. It
must never enter diagnostic stages 1-5 while recovering a full candidate. Do not
start a fresh candidate merely because the controlling terminal or agent stopped;
use this command after confirming the recorded child process is no longer active.

### 5.6 Reuse and compression decision

The build already avoids compiling the application six times. Each backend creates
one core and stages three edition views from it. The immutable Slicer, Brain,
Lumbar, Qt, codec, and other dependency inputs also come from verified local caches;
they are not downloaded again for every edition.

The remaining repetition is mostly Inno Setup compression. Because the contract is
six standalone EXE installers and the edition payloads or architecture rules differ,
Inno must currently read and compress each complete edition separately. Inno Setup
does not provide a safe incremental block cache for rebuilding one monolithic EXE.
Unchanged DLLs therefore do not, by themselves, make an old installer reusable.
A version, source, manifest, installer-script, dependency, profile, or payload change
invalidates the corresponding final artifact.

Use the following decision table instead of guessing:

| Situation | Safe action | What may be reused |
|---|---|---|
| Normal source development | Source tests and Developer Run | Existing environments and immutable asset cache; no installer |
| One installer/profile investigation | Explicit internal diagnostic lane | Verified assets and that isolated diagnostic workspace only |
| Packaging retry with byte-identical PyInstaller core inputs | `--reuse-python-source` with its fail-closed input map | Validated PyInstaller core; gates and installers run again |
| Infrastructure interruption in the current full candidate | Root coordinator `--resume-workspace` | Completed backend plus validated same-candidate Nuitka checkpoints/objects |
| New version or changed core inputs | Fresh full matrix after source freeze | Toolchain and immutable asset cache only |

Do not manually copy a DLL tree or decide reuse from modification times. Reuse is
valid only when a checked content manifest covers source, dependency lock, build
toolchain, spec/configuration, runtime resources, edition profile, and installer
script inputs.

The next safe implementation target is content-addressed Nuitka Stage 6 reuse with
fail-closed invalidation and a new coherence guard. After that, benchmark a faster
compression profile for non-promotable internal diagnostics. Bounded parallel Inno
compilation may be evaluated only on a dedicated machine with measured RAM and disk
headroom. None of these experiments changes the current release default until a
before/after six-artifact run passes every existing content, hash, version, size,
Qt/ICU, codec, DICOM Flow, and installability guard.

## 6. Expected sizes and content checks

Size is an anomaly signal, not proof of completeness. The completed 3.6.7 local
install-QA evidence is:

| Backend | Eagle Eye | Standard | ARM64 emulation |
|---|---:|---:|---:|
| Python/PyInstaller | 1,785,526,154 bytes | 635,475,974 bytes | 635,476,107 bytes |
| Nuitka | 1,749,308,055 bytes | 599,265,245 bytes | 599,265,466 bytes |

Expected review bands for the current dependency family are 1.65–1.85 GB for Eagle
Eye and 0.55–0.70 GB for Standard/ARM. Stop and investigate any result outside its
band. Do not remove Slicer, codecs, Qt, legal files, or modules to satisfy a size
target. The compact-edition hard maximum is 700,000,000 bytes; content gates remain
authoritative even when size looks normal.

For every backend verify:

- Standard and ARM contain the Advanced MPR/Slicer executable and do not contain
  `offline_lumbar` or `AIPacsOfflineLumbar.py`.
- Eagle Eye contains Slicer, the offline-lumbar manifest, model environment, and
  integration module.
- The core contains exactly one compatible QtCore runtime, no foreign app-local
  ICU DLLs, and retains WebEngine `icudtl.dat`.
- DICOM codec modules and discovery metadata are present. The Nuitka XML report
  must include pylibjpeg, OpenJPEG, RLE, JPEG-LS, and GDCM metadata.
- The cardiac Flow VM-normalization and DICOMDIR modules appear in the PyInstaller
  TOC and Nuitka report.
- The Lite Viewer frozen self-test passes.

## 7. Completion and acceptance

A build is complete only when all of the following are true:

1. `build_status.json` says `completed`.
2. Python and Nuitka have exit code 0.
3. `coherence_exit_code` is 0.
4. Both backend metadata files say `status: compiled`, `version: <version>`, and
   `published: false`.
5. All six required filenames exist, are newly produced, and have no `.partial`
   or `.tmp` sibling.
6. Independent file length and SHA-256 calculations match metadata and checksum
   files.
7. Every installer reports matching Windows FileVersion and ProductVersion.
8. Profile-content, codec, legal, Qt/ICU, Lite Viewer, version-display, and DICOM
   Flow guards pass.
9. The release document records source identity, toolchain, times, sizes, hashes,
   warnings, and remaining blockers.

Build completion is not production acceptance. Before distribution, perform clean
Windows install, upgrade, uninstall, rollback, installed clinical/viewer checks,
real Windows-on-ARM64 emulation, representative de-identified cvi42 Flow re-import,
log review, credential remediation, legal review, code signing, hash regeneration,
and explicit owner sign-off.

## 8. Never do these

- Do not use `build.py`, `build.bat`, `build_nuitka.py`, the simple Nuitka command,
  or old resumable wrappers as the official six-file release entry point.
- Do not build a final candidate directly from the dirty development checkout.
- Do not run PyInstaller and Nuitka full-core compilation concurrently on the
  current build machine.
- Do not increase Nuitka jobs, enable LTO, remove `/Od`, or enable compiler caches
  in the release default without a separate measured experiment and full guards.
- Do not reuse or rename an older installer, stage, `dist`, checkpoint, or output
  after source identity changes.
- Do not edit generated build output as source.
- Do not delete historical installers or candidate workspaces as part of a build.
- Do not exclude Slicer to make Standard or ARM smaller.
- Do not bypass source, mirror, asset, codec, frozen-runtime, version, coherence,
  privacy, legal, or size gates.
- Do not launch an installer or the frozen workstation automatically.
- Do not upload, sign, publish, or label a candidate production-ready without the
  deployment gate and owner approval.

## 9. Future speed work that requires a guarded experiment

The following may reduce time but are not approved release defaults:

1. Add content-addressed Nuitka Stage 6 reuse across isolated candidates with an
   explicit core-input manifest, toolchain identity, artifact hash, and fail-closed
   invalidation comparable to PyInstaller repackaging.
2. Add a faster Inno compression profile for disposable internal candidates only.
   Benchmark time, installed size, extraction time, and byte integrity; prevent
   that profile from being promoted as a final release.
3. Benchmark bounded parallel Inno compilation only on a dedicated machine with
   measured RAM, disk throughput, and deterministic output verification. Keep the
   current sequential default until evidence proves it safe.
4. Consider a shared payload/bootstrap architecture only as a versioned product
   decision. It changes offline installation and rollback semantics and must not be
   introduced merely to reduce build time.

Record accepted optimization work under the existing OPT-53 item in
`docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md`.

## 10. Supporting references

- `docs/releases/VERSION_3.6.7_BUILD.md` — current candidate preparation and artifact evidence.
- `docs/releases/VERSION_3.6.6_BUILD.md` — previous measured artifact baseline.
- `docs/releases/VERSION_3.6.5_BUILD.md` — earlier measured artifact baseline.
- `builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md` — edition payloads.
- `builder/docs/INSTALLER_QA_CHECKLIST.md` — clean-machine installer QA.
- `builder/docs/AI_AGENT_BUILD_RUNBOOK.md` — historical PyInstaller details.
- `builder nuitka/README_NUITKA_BUILD.md` — Nuitka diagnostics and stages.
- `docs/reports/CODEX_REPOSITORY_READINESS_2026-08-27.md` — repository blockers.
