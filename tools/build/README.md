# Build coordination tooling

Start at the [release and build documentation hub](../../docs/release-and-build/README.md),
then follow [`../../RELEASE.md`](../../RELEASE.md) and
[`../../BUILD.md`](../../BUILD.md).
The [definitive custom Slicer baseline](../../docs/release-and-build/SLICER_NATIVE_BASELINE_2026-09-23.md)
is shared by Client and Server. Ordinary builds reuse its verified asset cache;
they do not compile Slicer again.

`build_local_candidate.py` is the only installer coordinator. It
creates an isolated source snapshot, requires a fresh Git synchronization receipt,
runs PyInstaller and Nuitka sequentially, writes final files only to the two
established installer folders, and records cross-backend coherence evidence.

An unqualified request to "make a build" means four Standard Client installers:
Standard and ARM64-emulated from both backends. `--target server` selects two
Eagle Eye installers, one from each backend. `build_local_candidate.py --internal`
is only an explicitly requested
single-package diagnostic. Its output remains in temporary compiler scratch space,
is non-promotable, and never counts as a completed build. Backend scripts remain
implementation details and reject direct release-capable execution from the
mutable developer checkout.

The selected role is fixed inside its snapshot and resume state. Client release
and local-QA runs select Standard/ARM; Server local-QA runs select Eagle Eye.
Server release is blocked pending portable Breast/Bone and service qualification.
The coordinator has no final-output-directory
override. A successful process outside the two canonical installer folders is
diagnostic evidence, not delivery.

For speed, do not run either full role build during ordinary source iteration. Use
source tests/Developer Run, the explicit one-package internal diagnostic when
necessary, exact-input PyInstaller repackaging, or same-candidate Nuitka resume.
The selected role runs once after source freeze. See `BUILD.md` section 5.6 for the
reuse/invalidation contract and measured bottlenecks.

If a full candidate is interrupted, resume it only through this coordinator:
`build_local_candidate.py --resume-workspace C:\b\<exact-candidate-directory>`.
It retains a completed backend, uses only release stages when resuming Nuitka, and
reruns coherence. Do not replace this with a direct backend recovery command.

The Client official lane takes only `--git-sync-receipt <path>` in the common case.
Server local-QA uses `--local-install-qa --target server` and validates its available
model inputs before expensive compilation.
`C:\b` is only the short-path compilation workspace. Final installers are written
only to `builder/output/installer/` and `builder nuitka/output/installer/`.
For an explicitly requested local Client package before publication or
redistribution approval, use `--local-install-qa`; it writes four installable
artifacts to those same canonical folders while marking the run non-promotable.

Other scripts in this folder are helpers and gates used by the canonical
coordinator. Their presence does not create another supported release workflow.
