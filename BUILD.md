# AI-PACS canonical build and installer runbook

Status: authoritative for the current three-edition Windows build matrix.
Audience: human maintainers and AI agents.

Documentation map: [`docs/release-and-build/README.md`](docs/release-and-build/README.md).

This is the single entry point for creating AI-PACS installers. Backend-specific
documents explain implementation details and historical recovery, but they do not
replace this procedure. If another build document conflicts with this file, stop
and update the conflicting document before building.

Versioned Git publication is governed by `RELEASE.md`. A full release candidate
cannot start until the exact clean source commit is synchronized to every required
remote branch and its fresh receipt is available.

## 1. Supported deliverables

Eagle Eye asset update (2026-09-07): its payload now requires both Brain and
Lumbar. Brain preparation, distribution-evidence requirements and remaining clean
Windows acceptance are documented in
[Eagle Eye Brain delivery](docs/modules/EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md).
The earlier lumbar-only asset cache does not satisfy this new contract. Set
`AIPACS_EAGLE_EYE_BRAIN_SOURCE` to an approved immutable Brain payload when using
an isolated source snapshot. Do not bypass the new payload validation to build
an incomplete Eagle Eye installer. Standard and ARM exclude both Eagle Eye models.

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

## 2. One workflow, three lanes

Do not build six installers after every source edit. Select the narrowest lane
that answers the current question. An artifact may move only from a stricter lane,
never from a faster lane by renaming it.

| Lane | When to use it | Output | Release status |
|---|---|---|---|
| Source validation | Every normal code change | Tests and Developer Run evidence | No installer; never distributable |
| Internal packaging validation | Installer/profile work or focused QA | Synthetic Inno check or one isolated edition | Disposable; never promote or distribute |
| Full release candidate | Source is frozen and the owner requests a candidate | All six installers from one isolated snapshot | Eligible for install QA; not production until all release gates pass |

On the 2026-09-06 reference machine, the complete 3.6.5 matrix took about
2 hours 54 minutes. PyInstaller took about 62 minutes and Nuitka about 112 minutes.
The six Inno compression passes consumed about 96 minutes in total; Nuitka Stage 6
consumed about 49 minutes. These are measurements, not universal promises.

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
The TEST center remains disabled by default. During human-operated clean-machine
install QA, enter an authorized center code and verify the matching active center
and a synthetic model response; never include credentials in QA evidence.
Client-side encryption raises extraction effort but cannot hide an authorized
center's decrypted key from someone controlling that running workstation.

Any failed prerequisite blocks the full build. Fix the cause; do not disable the
gate. `AIPACS_SKIP_GIT_FETCH` above is scoped only to deterministic unit tests;
`build_local_candidate.py` removes inherited `AIPACS_SKIP_*` and `AIPACS_ALLOW_*`
values before invoking the real release gates.

## 4. Canonical full-matrix command

Use a new short workspace on `C:`. Never reuse a workspace name. The command
creates an isolated, sanitized, content-addressed snapshot, compiles both backends
sequentially, writes the six final files only to the established repository
installer folders, and runs cross-backend coherence. It never publishes or
launches the workstation.

```powershell
$repoRoot = (Get-Location).Path
$version = & .\.venv_build\Scripts\python.exe -c "import pathlib,tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$candidateRoot = "C:\b\aipacs-$version-$stamp"
$assetRoot = Join-Path $repoRoot "generated-files\distribution-assets"
$releaseHead = git rev-parse HEAD
$receipt = "generated-files\release-git\v$version-$($releaseHead.Substring(0, 12)).json"
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --workspace $candidateRoot `
  --version $version `
  --asset-root $assetRoot `
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
prepare an isolated snapshot and build only the required edition inside it. The
output remains inside the candidate snapshot and must never replace a canonical
six-file set.

```powershell
$repoRoot = (Get-Location).Path
$version = & .\.venv_build\Scripts\python.exe -c "import pathlib,tomllib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'])"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$candidateRoot = "C:\b\aipacs-internal-$version-$stamp"
$assetRoot = Join-Path $repoRoot "generated-files\distribution-assets"
& .\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --workspace $candidateRoot --version $version --asset-root $assetRoot `
  --internal --prepare-only
Push-Location (Join-Path $candidateRoot "source")
try {
  & (Join-Path $repoRoot ".venv_build\Scripts\python.exe") `
    builder\build_release.py --internal-build --edition standard --asset-root $assetRoot
} finally {
  Pop-Location
}
```

Replace `standard` with `eagle-eye` or `arm` only when that exact edition is the
test target. For a Nuitka-specific internal check, replace the command inside the
snapshot with:

```powershell
& (Join-Path $repoRoot ".venv_build\Scripts\python.exe") `
  "builder nuitka\build_nuitka_release.py" --internal-build --release --edition standard --asset-root $assetRoot
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

## 6. Expected sizes and content checks

Size is an anomaly signal, not proof of completeness. The 3.6.5 r15 reference is:

| Backend | Eagle Eye | Standard | ARM64 emulation |
|---|---:|---:|---:|
| Python/PyInstaller | 1,156,051,065 bytes | 634,708,026 bytes | 634,708,231 bytes |
| Nuitka | 1,117,929,527 bytes | 596,594,493 bytes | 596,594,689 bytes |

Expected review bands for the current dependency family are 1.0–1.3 GB for Eagle
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

- `docs/releases/VERSION_3.6.6_BUILD.md` — current candidate preparation and artifact evidence.
- `docs/releases/VERSION_3.6.5_BUILD.md` — previous measured artifact baseline.
- `builder/docs/DISTRIBUTION_EDITIONS_AND_OFFLINE_ASSETS.md` — edition payloads.
- `builder/docs/INSTALLER_QA_CHECKLIST.md` — clean-machine installer QA.
- `builder/docs/AI_AGENT_BUILD_RUNBOOK.md` — historical PyInstaller details.
- `builder nuitka/README_NUITKA_BUILD.md` — Nuitka diagnostics and stages.
- `docs/reports/CODEX_REPOSITORY_READINESS_2026-08-27.md` — repository blockers.
