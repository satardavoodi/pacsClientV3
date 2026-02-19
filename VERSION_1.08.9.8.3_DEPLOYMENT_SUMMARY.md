# AIPacs Deployment Summary — v1.08.9.8.3

**Release Date:** 2026-02-09  
**Tag:** v1.08.9.8.3  
**Commit:** v1.08.9.8.3 (tagged release commit)

## Scope
- Stable version consolidation for v1.08.9.8.3.
- Documentation cleanup and alignment with current stable references.

## Deployment Checklist
- [ ] Confirm repository clean (except intended changes).
- [ ] Run any ad-hoc tests if needed (no automated suite).
- [ ] Build executable via `build.bat` if a build artifact is required.
- [ ] Create local backup: `backups/v1.08.9.8.3_2026-02-09/` **excluding** `.dcm` files.
- [ ] Commit and tag release `v1.08.9.8.3`.
- [ ] Push tag and branch to:
  - `origin` → branch `DR.vahid` (satardavoodi/PacsClientV2)
  - `vahid` → branch `main` (Vahid-INO/ai-pacs)

## Notes
- Backup must exclude all `.dcm` files.
- If any image pipeline or MPR internals change in the future, update the related reference docs.

---

Keep **Commit** pointing to the tagged release commit.
