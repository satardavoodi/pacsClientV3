# Release and build documentation hub

This page is the documentation map for every Git publication, package, installer,
and release-candidate task. It is a navigation layer, not an alternate runbook.

## Mandatory route

1. Read [`../../RELEASE.md`](../../RELEASE.md) before a versioned commit, tag,
   push, or full build. It owns remote policy, commit/tag rules, verification,
   and the synchronization receipt.
2. Read [`../../BUILD.md`](../../BUILD.md) before packaging. It owns lane
   selection, the canonical coordinator, output folders, expected sizes,
   coherence checks, install QA, and recovery.
3. Read the backend reference only when diagnosing or changing that backend:
   - [PyInstaller builder index](../../builder/docs/README.md)
   - [Nuitka builder reference](../../builder%20nuitka/README_NUITKA_BUILD.md)
4. Read [release records](../releases/README.md) for the current version's scope,
   evidence, approval state, and historical releases.
5. For any build containing Advanced Viewer, use the
   [definitive custom Slicer baseline](SLICER_NATIVE_BASELINE_2026-09-23.md).
   Client and Server must use that same native runtime; ordinary builds reuse
   it without recompilation.
6. Before an Eagle Eye Server installer, read the
   [separate service packaging gate](../../builder/docs/EAGLE_EYE_SERVER_SERVICE_BUILD_PARITY.md).
   A source-service pilot does not qualify a frozen installer.

If a lower-level document conflicts with `RELEASE.md` or `BUILD.md`, stop. The
root runbooks win and the conflicting document must be corrected before work
continues.

## Which path do I use?

An unqualified request to make a build means the four-file Standard Client group:
Standard and ARM64-emulated from PyInstaller and Nuitka. An explicit Eagle Eye
Server request means the two-file Eagle Eye group, one per backend. The same two
canonical output folders serve both groups, but each uses a distinct immutable
candidate and records its `build_target`. A Server release remains blocked while
portable Breast/Bone payloads and service/clean-host qualification are unfinished;
Server local install QA is non-promotable and currently blocked until the
service dependency preflight has a separately prepared build cache.

| Need | Start here | Result |
|---|---|---|
| Test a source change | `BUILD.md` → Source validation | Tests and Developer Run evidence; no installer |
| Create a Standard Client build | `RELEASE.md`, then `BUILD.md` → Canonical role-selected command | Standard and ARM from both backends: four files in the existing folders |
| Create an Eagle Eye Server QA build | `BUILD.md` → Local role-selected install QA | Eagle Eye from both backends: two non-promotable files in the existing folders |
| Recover an interrupted role build | `BUILD.md` → Same-candidate interruption recovery | The same immutable, recorded role; completed work is retained |
| Check one installer/profile when explicitly requested | `BUILD.md` → Optional single-package diagnostic | One non-promotable backend/edition inside temporary compiler scratch space |
| Publish a release source revision | `RELEASE.md` | One verified SHA/tag on all required remotes plus a receipt |
| Verify selected candidate installers | `BUILD.md` → Acceptance | Version, hashes, contents, size, install lifecycle, and platform evidence |
| Diagnose PyInstaller internals | `builder/docs/README.md` | Backend-specific evidence only |
| Diagnose Nuitka stages | `builder nuitka/README_NUITKA_BUILD.md` | Stage/checkpoint evidence only |
| Review what shipped | `docs/releases/README.md` | Version record and release notes |

## Authority and ownership

| Topic | Authoritative file |
|---|---|
| Git destinations and branches | `tools/git/release_targets.json` |
| Commit, tag, push, and receipt workflow | `RELEASE.md` |
| Build lanes and role-selected four/two-installer contract | `BUILD.md` |
| Build coordinator implementation | `tools/build/build_local_candidate.py` |
| Custom 3D Slicer source and reusable native baseline | `docs/release-and-build/SLICER_NATIVE_BASELINE_2026-09-23.md` |
| PyInstaller implementation details | `builder/docs/README.md` |
| Nuitka implementation details | `builder nuitka/README_NUITKA_BUILD.md` |
| Current version scope and acceptance | `docs/releases/VERSION_<version>_RELEASE.md` |
| Point-in-time investigations | `docs/reports/` |

Direct backend scripts are implementation interfaces, not release entry points.
Release-capable backend execution is guarded by `build_source_manifest.json`:
an official run requires a fresh Git receipt-backed snapshot, while an internal
diagnostic run requires an explicitly prepared non-promotable snapshot.
Candidate compilation also disables automatic remote update publication; signing,
install QA, and any later distribution remain separate authorized operations.
The coordinator supplies safe defaults for version, asset cache, and short workspace;
it also rejects missing release-only Brain evidence before compiling either backend.
The coordinator exposes no supported final-output redirect; normal builds always
write to the two repository folders listed below.

## Output ownership

Final files stay in the established repository folders:

- PyInstaller: `builder/output/installer/`
- Nuitka: `builder nuitka/output/installer/`

Do not create a third output hierarchy, rename an internal artifact into a
release artifact, or distribute from `_superseded`. Expected filenames, metadata,
size bands, and validation steps are defined only in `BUILD.md`.

For a repeated same-version local install-QA repair, the coordinator preserves
the selected backend's prior exact outputs in a timestamped `_superseded`
subfolder before rebuilding. Do not do this manually and do not apply that local
QA recovery rule to receipt-backed release candidates.

## Documentation maintenance rule

When the release process changes, update this hub, `RELEASE.md`, `BUILD.md`, the
affected backend index, the current version release record, and the navigation
guard in `tests/code/builder/test_canonical_build_runbook.py` in the same change.
Historical reports should not be rewritten to look current; label their
precedence and link back here instead.
