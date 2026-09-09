# AI-PACS deployment safety record — v3.6.6 candidate

**Date:** 2026-09-09
**Change:** Build the synchronized 3.6.6 PyInstaller and Nuitka candidate matrix.
**Target:** Local isolated candidate only; no installation or production promotion.
**Gate result:** CANDIDATE BUILD AUTHORIZED; PRODUCTION DEPLOYMENT BLOCKED.

## Safety checklist

- [x] Scope is limited to the reviewed source release and six local installers.
- [x] Canonical release and build runbooks are the operating authority.
- [x] Printing focused tests and plugin mirror parity pass before version freeze.
- [ ] Exact release commit is published to all configured remote branches and tagged.
- [ ] Fresh synchronization receipt exists for the exact clean commit.
- [x] Build environment, assets, toolchain, disk space, and mandatory guards pass.
- [ ] Six installers pass size, hash, content, version, and coherence checks.
- [ ] Clean install, upgrade, uninstall, and rollback are verified.
- [ ] Physical printing, installed clinical workflows, and de-identified cardiac Flow
      re-import are verified by a qualified operator.
- [ ] Real Windows-on-ARM64 emulation is verified.
- [ ] Historical credential incident, legal review, and code signing are closed.
- [ ] Repository owner explicitly approves distribution.

## Monitoring and rollback

Build logs, `build_status.json`, backend metadata, hashes, and coherence evidence
must stay with the isolated candidate. A failed candidate is not promoted or
silently repaired from older artifacts. Rollback is to retain the prior accepted
release and discard only the explicitly named 3.6.6 candidate after review.

No installer is launched, uploaded, signed, or described as production-ready by
this operation.
