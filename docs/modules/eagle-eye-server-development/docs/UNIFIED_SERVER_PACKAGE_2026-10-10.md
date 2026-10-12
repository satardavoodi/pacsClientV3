# Unified Eagle Eye Server package lifecycle

Owner requirement: the desktop UI, SCM service, headless children, Brain gateway,
CRM/Secretary core and approved plugin/model payloads form one qualified release.
Updating a desktop link alone is not an update of the Server product.

## Implemented source boundary

Canonical stage_edition now stamps the Server core with eagle-eye-release.json;
compile_editions supplies the actual build version on both backend paths. Standard
and ARM stages are unchanged. Every core file has a SHA-256 identity; private host
configuration is outside this inventory. A completed stamp cannot be overwritten.

Frozen service startup validates its installed executable and captures the package
identity once. Authenticated capabilities returns that captured identity. It does
not reread a later manifest and pretend an old process became a new release.
Frozen Server desktop preflight requires a running exact-owned SCM command and a
matching qualified service identity before writing its desktop-client config.
This bounds the in-place upgrade hazard of an old process and new files at one path.
The executable-only startup check is not full native/plugin/model validation.

release_package.transition defines the ordering contract against an explicit host
adapter: hold admission closed, verify retained old and staged new core, drain
model/text/CRM work, persist prepared journal, stop the owned service, select and
start candidate, validate authenticated application health, then publish the common
GUI/service selection. Failure restores old service and pointer. Failed recovery
remains recovery_required. No adapter is inferred from SCM RUNNING alone.

## Required installer work - NOT IMPLEMENTED OR QUALIFIED

Server PrepareToInstall now refuses existing targets before any previous
uninstaller can run, and Server setup disables automatic application closing.
Client and Server use separate AppIds and state/package roots. The transition
contract is still not wired to a qualified Windows host adapter. This protective
fence is not an atomic Server updater. See SERVER_HARDENING_2026-10-10.md.

1. Implement the Windows setup host adapter with protected durable journal,
   admission drain ownership, exact LocalService command/account checks, retained
   previous core and complete payload manifests, crash recovery and rollback.
2. Route Server PrepareToInstall through that adapter before deleting any old core;
   preserve Standard/ARM behavior. Publish shortcuts only after verified commit.
3. Bind fresh Server enrollment to one absolute host-private config and license;
   installer shortcuts and postinstall launch must pass the Server role/config.
   Current icons have no role/config arguments. Do not invent center credentials,
   copy test identity, or ship Razi settings. Keep private settings across upgrades.
4. Extend release identity coverage to plugin/model/native payload revisions and
   verify their full manifests before activation; core identity alone is insufficient.
5. Qualify fresh install, upgrade, rollback, reboot and Session 0 on a clean Windows
   test host independently for PyInstaller and Nuitka. No developer Python required.
6. Reconcile all local/Razi source and required assets, activate the same reviewed
   revision and run the three-platform synthetic acceptance package.

## Evidence and limits

71 focused local tests passed, including immutable/corrupt core verification,
installed GUI identity gate for both freeze detectors, lifecycle ordering/rollback,
and adjacent builder/service guards. No installed binary, installer or release was
built. No active Razi service, credentials or admission policy was changed.
The source helpers are a foundation for a unified package; installation lifecycle
and full Developer parity remain blockers. Full product readiness is not claimed.
