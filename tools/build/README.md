# Build coordination tooling

Start at the [release and build documentation hub](../../docs/release-and-build/README.md),
then follow [`../../RELEASE.md`](../../RELEASE.md) and
[`../../BUILD.md`](../../BUILD.md).

`build_local_candidate.py` is the only installer coordinator. It
creates an isolated source snapshot, requires a fresh Git synchronization receipt,
runs PyInstaller and Nuitka sequentially, writes final files only to the two
established installer folders, and records cross-backend coherence evidence.

An unqualified request to "make a build" always means the official six-installer
matrix. `build_local_candidate.py --internal` is only an explicitly requested
single-package diagnostic. Its output remains in temporary compiler scratch space,
is non-promotable, and never counts as a completed build. Backend scripts remain
implementation details and reject direct release-capable execution from the
mutable developer checkout.

The official lane takes only `--git-sync-receipt <path>` in the common case. It
fails missing Eagle Eye Brain redistribution evidence before expensive compilation.
`C:\b` is only the short-path compilation workspace. Final installers are written
only to `builder/output/installer/` and `builder nuitka/output/installer/`.

Other scripts in this folder are helpers and gates used by the canonical
coordinator. Their presence does not create another supported release workflow.
