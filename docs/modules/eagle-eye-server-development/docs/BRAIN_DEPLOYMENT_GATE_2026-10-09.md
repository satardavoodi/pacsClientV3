# Deployment Safety Record - Eagle AI Brain - 2026-10-09

Change: shared private Brain authority and transport usage gate.
Gate result: BLOCKED for the shared active clinical service.

- CONFIRMED: scoped source change inventory and synthetic tests exist.
- CONFIRMED: immutable Razi candidates preserve the running service and private data.
- CONFIRMED: no new credentials or clinical content are in changed fixtures/docs.
- N/A: no viewer/rendering/DICOM implementation is changed by this slice.
- BLOCKED: complete local/Razi Developer and required payload parity receipt.
- BLOCKED: affected native GUI acceptance; existing control ping found no listener.
- BLOCKED: real-provider and authenticated client acceptance of the new service.
- BLOCKED: exact final transition/rollback command and locked admission drain have
  not been qualified against the current active service/reconciled revision.

User authorized updating Razi for testing. That is recorded authorization, not
proof that the missing engineering gates passed. Only source preparation and
review are allowed at this checkpoint; no clinical service switch or release.

Policy: C:/Users/Dr.Alizadeh/.codex/skills/deploy-safety-check/SKILL.md:
"Any single BLOCKED item blocks the whole deploy."

## Launcher mismatch correction - 2026-10-10

The desktop link selected brain-profiles-r2 while SCM selected education-presenter.
The launcher only started the GUI; it never activated the backend. Comparing
candidate and active service showed 18 candidate-only Python modules and 21
changed hosted Python files, including user admission. Private candidate config
enables user_access whereas active config does not. Blind activation is not safe.

The external Developer launcher now checks exact service entry source and private
config before GUI launch. Mismatch shows a visible English warning, even though
PowerShell is hidden. It does not restart any service or automate login.
Helper: tools/eagle_eye/developer_service_target.ps1. Four focused guards pass;
remote PowerShell parse and actual mismatch rejection pass. No source GUI launched.
Backup and host receipt: Razi staging/launcher-target-20261010. Restore
launcher-before.ps1 to the original launcher path to undo the external edit.
Local helper/tests are mirrored in that staging directory; immutable r2 is unchanged.
Full Developer parity, new authenticated service admission, GUI acceptance and
safe controlled service transition remain pending. This fixes misleading launch
behavior, not the backend version mismatch. No build/release handoff is permitted.

## Developer review launcher correction - 2026-10-10

The strict external launcher blocked the operator from reviewing settings while
service activation was pending. Developer review now displays a visible mismatch
notice and continues to the source GUI. Other launch failures remain fatal. It
does not restart services, change launch test flags or weaken installed-package
identity checks. PowerShell parsing passed on Razi; actual GUI launch/login was
not automated or verified. Backup and receipt remain in launcher-target-20261010.
This is review access only; active backend parity remains unresolved.
