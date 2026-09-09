# Build coordination tooling

Start at the [release and build documentation hub](../../docs/release-and-build/README.md),
then follow [`../../RELEASE.md`](../../RELEASE.md) and
[`../../BUILD.md`](../../BUILD.md).

`build_local_candidate.py` is the only full release-candidate coordinator. It
creates an isolated source snapshot, requires a fresh Git synchronization receipt,
runs PyInstaller and Nuitka sequentially, writes final files only to the two
established installer folders, and records cross-backend coherence evidence.

The `--internal --prepare-only` mode creates a disposable, non-promotable
snapshot for focused packaging diagnostics. Backend scripts require
`--internal-build` when used in that snapshot. They intentionally reject direct
release-capable execution from the mutable developer checkout.

Other scripts in this folder are helpers and gates used by the canonical
coordinator. Their presence does not create another supported release workflow.
