# Build coordination tooling

Start at the [release and build documentation hub](../../docs/release-and-build/README.md),
then follow [`../../RELEASE.md`](../../RELEASE.md) and
[`../../BUILD.md`](../../BUILD.md).

`build_local_candidate.py` is the only installer coordinator. It
creates an isolated source snapshot, requires a fresh Git synchronization receipt,
runs PyInstaller and Nuitka sequentially, writes final files only to the two
established installer folders, and records cross-backend coherence evidence.

`build_local_candidate.py --internal` is the one-command Developer Run packaging
path. It defaults to one Standard PyInstaller output, automatically selects the
current version, asset cache, and a new short workspace, and marks the result
non-promotable. `--backend nuitka` and `--edition ...` select a focused alternative.
Backend scripts remain implementation details and reject direct release-capable
execution from the mutable developer checkout.

The official lane takes only `--git-sync-receipt <path>` in the common case. It
fails missing Eagle Eye Brain redistribution evidence before expensive compilation.

Other scripts in this folder are helpers and gates used by the canonical
coordinator. Their presence does not create another supported release workflow.
