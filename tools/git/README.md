# Git release tooling

The only versioned multi-remote publication procedure is
[`../../RELEASE.md`](../../RELEASE.md). The overall documentation route is
[`../../docs/release-and-build/README.md`](../../docs/release-and-build/README.md).

- `release_targets.json` is the reviewed machine-readable remote/branch policy.
- `release_manager.py audit` performs the fail-closed pre-publication audit.
- `release_manager.py publish` requires the exact full SHA and literal
  `--execute`, publishes explicit refs, reads them back, and writes a short-lived
  ignored synchronization receipt.
- `Push-GitHub.ps1` is only a connectivity/non-release feature-branch helper. It
  refuses live release-branch pushes and is not an alternative release path.

Never force-push shared release branches, manually move a published version tag,
or treat an offline audit as proof of remote synchronization.
