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

If a lower-level document conflicts with `RELEASE.md` or `BUILD.md`, stop. The
root runbooks win and the conflicting document must be corrected before work
continues.

## Which path do I use?

An unqualified request to make a build always means the complete six-installer
matrix. Release versus local install-QA changes evidence and promotion status, not
the number of installers or their destination folders. Fewer than six files are
permitted only for an explicitly requested non-promotable diagnostic.

| Need | Start here | Result |
|---|---|---|
| Test a source change | `BUILD.md` → Source validation | Tests and Developer Run evidence; no installer |
| Create a requested build | `RELEASE.md`, then `BUILD.md` → Canonical six-installer command | Three PyInstaller and three Nuitka installers in the two existing repository output folders |
| Recover an interrupted full build | `BUILD.md` → Same-candidate interruption recovery | The same immutable six-installer candidate; completed work is retained |
| Check one installer/profile when explicitly requested | `BUILD.md` → Optional single-package diagnostic | One non-promotable backend/edition inside temporary compiler scratch space |
| Publish a release source revision | `RELEASE.md` | One verified SHA/tag on all required remotes plus a receipt |
| Verify all six candidate installers | `BUILD.md` → Acceptance | Version, hashes, contents, size, install lifecycle, and platform evidence |
| Diagnose PyInstaller internals | `builder/docs/README.md` | Backend-specific evidence only |
| Diagnose Nuitka stages | `builder nuitka/README_NUITKA_BUILD.md` | Stage/checkpoint evidence only |
| Review what shipped | `docs/releases/README.md` | Version record and release notes |

## Authority and ownership

| Topic | Authoritative file |
|---|---|
| Git destinations and branches | `tools/git/release_targets.json` |
| Commit, tag, push, and receipt workflow | `RELEASE.md` |
| Build lanes and six-installer contract | `BUILD.md` |
| Build coordinator implementation | `tools/build/build_local_candidate.py` |
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

## Documentation maintenance rule

When the release process changes, update this hub, `RELEASE.md`, `BUILD.md`, the
affected backend index, the current version release record, and the navigation
guard in `tests/code/builder/test_canonical_build_runbook.py` in the same change.
Historical reports should not be rewritten to look current; label their
precedence and link back here instead.
