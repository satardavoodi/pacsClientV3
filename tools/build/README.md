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

The matrix is fixed for both receipt-backed release candidates and
`--local-install-qa`: PyInstaller Eagle Eye/Standard/ARM64-emulated plus Nuitka
Eagle Eye/Standard/ARM64-emulated. The coordinator has no final-output-directory
override. A successful process outside the two canonical installer folders is
diagnostic evidence, not delivery.

For speed, do not run the six-file matrix during ordinary source iteration. Use
source tests/Developer Run, the explicit one-package internal diagnostic when
necessary, exact-input PyInstaller repackaging, or same-candidate Nuitka resume.
The final matrix runs once after source freeze. See `BUILD.md` section 5.6 for the
reuse/invalidation contract and measured bottlenecks.

If a full candidate is interrupted, resume it only through this coordinator:
`build_local_candidate.py --resume-workspace C:\b\<exact-candidate-directory>`.
It retains a completed backend, uses only release stages when resuming Nuitka, and
reruns coherence. Do not replace this with a direct backend recovery command.

The official lane takes only `--git-sync-receipt <path>` in the common case. It
fails missing Eagle Eye Brain redistribution evidence before expensive compilation.
`C:\b` is only the short-path compilation workspace. Final installers are written
only to `builder/output/installer/` and `builder nuitka/output/installer/`.
For an explicitly requested local six-installer package before publication or
redistribution approval, use `--local-install-qa`; it writes all six installable
artifacts to those same canonical folders while marking the run non-promotable.

Other scripts in this folder are helpers and gates used by the canonical
coordinator. Their presence does not create another supported release workflow.
