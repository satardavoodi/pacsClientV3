# AI-PACS v3.6.4 Installer Build Readiness — 2026-08-30

## Decision

**Overall release status: BLOCKED.**

The Windows x64 workstation has the compilers, Python environment, packaging tools, native
runtimes, and disk capacity needed to produce both installer variants. Client-side EchoMind
credential hardening is now implemented under the release owner's accepted threat model. The
current repository must not produce a release artifact yet because the working tree is not
clean, the existing staged outputs are v3.6.3, the builder guard suite is red against that stale
stage, and release-source traceability requires an explicit decision.

| Pipeline | Build environment | Safe to start release build | Safe to ship |
| --- | --- | --- | --- |
| PyInstaller (Python) x64 | Ready | No | No |
| Nuitka x64 | Ready | No | No |
| Nuitka ARM64 / Windows on ARM | Not ready | No | No |

No v3.6.4 installer was created during this evaluation.

## Evaluated release state

- Current branch: `beta-version`
- Current branch commit: `a6ff2010e8c807ae781cb5bbe8f136ab7fc33295`
- v3.6.4 tag target: `7f96b392a1cda47673f71b0c4917dedbaa74b149`
- Difference from the tag target to branch HEAD: release documentation only
- `pyproject.toml`, `main.py`, package feeds, module manifests, and version-resource metadata:
  `3.6.4`
- Current local remote-tracking refs for `origin`, `p2`, and `satar`: `a6ff2010`
- Working tree: eight modified tracked generated or machine-local files and an untracked
  `generated-files/gapgpt/` tree; none were reset or included in a release build

The tag is on the release code commit and the branch contains a later documentation-only
commit. A release build must record one exact source commit. The preferred artifact source is
the immutable `v3.6.4` tag target. Before executing the build, either teach the release gate to
accept an exact verified release tag or record a deliberate, reviewed tagged-build procedure.
Do not move or force-update the published tag merely to include the later documentation commit.

## Toolchain and payload readiness

Verified on the build workstation:

- Windows 11 x64 / AMD64
- Python 3.13.5 in `.venv_build`
- PyInstaller 6.11.1
- Nuitka 4.1.3
- Nuitka-managed Zig 0.16.0
- Visual Studio 2022 Build Tools with x86/x64 C++ components
- Inno Setup 6 at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`
- PySide6 6.10.2, OpenCV 4.13.0, SimpleITK 2.5.3, VTK 9.6.1, pydicom 2.4.5
- `.venv_build` dependency consistency: `pip check` passed
- Required graphics runtime DLLs present
- Advanced MPR runtime present: 12,338 files, approximately 0.85 GB
- Free space on `E:`: approximately 94 GB
- Plugin mirrors: 456 pairs match, zero mismatches
- No active build process and no PyInstaller build lock at evaluation time

## Automated verification results

### Passed

- Focused v3.6.4 release coverage: **647 passed, 8 xfailed**
- EchoMind non-live suite after credential hardening: **2,315 passed, 12 skipped, 4 expected
  failures, 15 live tests deselected**
- EchoMind credential regression guard: **6 passed**, including authenticated decryption,
  wrong-code rejection, tamper rejection, and plaintext scanning
- Current source and installer-payload scan: **0 plaintext provider credentials and 0 plaintext
  center access codes**
- Plugin mirror verification: **458 matched, 0 mismatched**
- `git diff --check`: passed; only line-ending warnings were emitted for generated Nuitka XML
- PyInstaller pre-build checks: source freshness, plugin mirrors, codecs, and build prerequisites
  passed

### Failed or incomplete

- Builder guard suite: **7 failed, 87 passed, 5 deselected**
  - Six failures show that Nuitka ARM64 / Windows-on-ARM support is incomplete.
  - One failure is expected from the stale v3.6.3 PyInstaller stage and its config mismatch.
- PyInstaller post-stage gate: failed `stage_config_parity` for
  `config/patient_table_sort.json`.
- Repository-wide fast test proof remains unavailable because `run_test.ps1` can mask failure.
- Clinical source-build validation, clean-machine installation QA, upgrade/downgrade QA, log
  review, and rollback rehearsal have not been completed for v3.6.4.

## Existing artifacts are stale

Both current installer trees are from v3.6.3 and must not be renamed or reused:

- PyInstaller stage manifest and installer: v3.6.3, last built 2026-08-23
- Nuitka build state, stage metadata, manifest, and installer: v3.6.3, last built 2026-08-23
- Expected v3.6.4 artifact names do not exist

The cross-build coherence checker currently passes because it compares the two staged outputs
to each other. Both happen to report v3.6.3. It does not compare their version with the source
version in `pyproject.toml`, so this pass is not release proof.

## Build-process defects that must be addressed or explicitly controlled

1. The PyInstaller release gate warns about a dirty tracked worktree but does not fail, and it
   ignores untracked files. A build can therefore include unreproducible local content.
2. The PyInstaller post-stage gate does not compare the staged product version to the current
   source version.
3. Nuitka resume state has no source commit, source-tree, or version fingerprint. Plain
   `--resume` would trust the completed v3.6.3 stages under v3.6.4 source.
4. Cross-build coherence checks PyInstaller against Nuitka, but not either output against the
   source version.
5. `builder/build_release.py` obtains its build lock before parsing arguments; even a help-only
   invocation can leave a stale lock if argument handling exits early.
6. Nuitka ARM64 / Windows-on-ARM command, installer, and package-selection paths do not satisfy
   the existing parity guards.

For v3.6.4, use a clean isolated checkout at the chosen commit and treat any dirty tree as a
hard stop even before the tooling defects are repaired.

## Client credential hardening and residual risk

The current source tree and EchoMind installer payload no longer contain plaintext center access
codes or plaintext provider bearer credentials. Center access codes are represented by lookup
digests. Each code derives an independent key with scrypt and opens only its own AES-GCM
authenticated provider-credential envelope. Company Server 3 now uses the provider credential
opened by the validated EchoMind center instead of a separate embedded fallback. A regression
guard scans both tracked files and newly added runtime/mirror files.

This is deliberate client-side extraction resistance, not a hardware- or server-backed secret
boundary. A determined operator with a debugger can still recover a credential while the process
uses it, weak center codes remain susceptible to offline guessing, and previously published Git
history may retain earlier plaintext values. Dashboard quotas and center controls remain the
operational enforcement layer accepted by the release owner. Before public distribution, record
that residual-risk acceptance and review provider-key rotation/history remediation separately;
neither limitation should be misrepresented as solved by encryption at rest.

## Approved execution plan after blockers are cleared

Run these commands only from a new, clean, isolated build checkout at the approved source commit.
Do not run them in the current dirty development checkout.

### Shared preflight

```powershell
git status --porcelain=v1
git rev-parse HEAD
git rev-parse "v3.6.4^{}"
.\.venv_build\Scripts\python.exe -m pip check
.\.venv_build\Scripts\python.exe tools/dev/verify_plugin_mirrors.py
.\.venv_build\Scripts\python.exe -m pytest -p no:debugging tests/code/builder -q
```

Required results: empty Git status, the recorded source SHA, matching mirrors, dependency check
pass, and a green builder suite for the selected x64 release scope. Do not use `run_test.ps1` as
release evidence until its exit-code defect is fixed.

### PyInstaller (Python) x64 release

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv_build\Scripts\python.exe build.py --clean-build 2>&1 |
  Tee-Object -FilePath "builder\output\build_v3.6.4_clean.log"
.\.venv_build\Scripts\python.exe builder/release_gate.py --stage-check
Get-Item "builder\output\installer\ai-pacs installer v3.6.4.exe"
Get-FileHash "builder\output\installer\ai-pacs installer v3.6.4.exe" -Algorithm SHA256
```

Both pre-build and post-stage release gates must report PASS. Never use
`--skip-release-gate`, `--skip-pyinstaller`, or `AIPACS_ALLOW_STALE_MPR_PYZ` for a release.

### Nuitka x64 release

For a pristine isolated release checkout, the most defensible path is a full clean staged build:

```powershell
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --clean-all
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py"
```

If the approved process deliberately preserves validated stages 0-5, the minimum safe v3.6.4
rebuild is:

```powershell
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --clean-stage 6
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --stage 6
.\.venv_build\Scripts\python.exe "builder nuitka/build_nuitka_release.py" --from-stage 7
```

Do not use plain `--resume` for v3.6.4 because the current completed state belongs to v3.6.3.
After the build, verify that the manifest and release metadata both report 3.6.4, then hash the
fresh versioned installer. Executable launch and clinical smoke testing must follow the project's
human-controlled source-build and clean-machine QA rules.

### Cross-build acceptance

```powershell
.\.venv_build\Scripts\python.exe builder/scripts/check_build_coherence.py
```

In addition to that checker, manually assert that both staged app versions equal the source
version, `3.6.4`, until the checker is fixed. Record for each artifact: source SHA, builder,
compiler, Python version, build time, byte size, SHA-256, gate logs, install QA result, and
rollback result.

## Release acceptance checklist

The installers may be called release-ready only when all items are complete:

- [x] Current source and installer payload contain no plaintext center/provider credentials
- [x] Automated EchoMind credential regression scan is green
- [ ] Release owner records acceptance of runtime extraction and published-history risk, or rotates
  affected provider credentials before distribution
- [ ] Exact source SHA approved and clean isolated checkout proven
- [ ] Builder guard suite green for the supported architecture
- [ ] PyInstaller pre-build and post-stage gates green
- [ ] Nuitka stages rebuilt from valid v3.6.4 state, not plain resume
- [ ] Both staged versions equal source version 3.6.4
- [ ] Both installers freshly generated and SHA-256 hashes recorded
- [ ] Clean-machine installation and uninstall tests completed
- [ ] Upgrade from v3.6.3 and rollback to v3.6.3 verified
- [ ] Source-build clinical workflow and log review completed
- [ ] Installer QA checklist signed by the responsible human

## Recommended next engineering work

Before spending hours on compilation, add hard guards for clean-tree enforcement, staged-to-source
version parity, Nuitka source fingerprints, and source-aware cross-build coherence. Record the
accepted client-only credential threat model, then rerun the builder suite in a clean isolated
checkout. This makes the expensive builds deterministic and prevents another stale-but-coherent
installer from appearing valid.
