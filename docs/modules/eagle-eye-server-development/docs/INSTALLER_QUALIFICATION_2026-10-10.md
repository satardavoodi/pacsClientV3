# Server installer qualification and host adapter prerequisites

Owner backlog: OPT-51 / OPT-55 / OPT-56. This is an implementation handoff and
evidence boundary, not installer qualification or permission to restart a host.

## Corrected inspection boundary

`service_admin.inspect_service()` previously accepted a matching SCM command as
owned even when its service account was LocalSystem or another user. Frozen
desktop package preflight consumes this result. The existing mutation primitives
already required both the exact command and NT AUTHORITY\LocalService. Inspection
now applies that same case-insensitive account check. It performs no SCM mutation.

`test_service_inspection_ownership.py` reproduced two false ownership admissions
before the fix (2 failed, 2 passed; process exit 1). After the fix, the new four
cases plus service administration, release-package and installer-isolation guards
passed: 22 tests, direct pytest exit 0. No real SCM service was accessed by these
synthetic tests. The earlier package/isolation baseline independently passed 15.
Live GUI and installed backend acceptance remain pending. This change has not
been activated on Razi, and local/Razi parity for this new delta is pending.

## Adapter still missing

`release_package.transition()` is an ordering protocol exercised against fake
hosts. It is not a Windows host adapter. The existing-target Inno fence must stay
closed until an adapter meets all of these boundaries:

| Boundary | Required behavior and evidence |
|---|---|
| Protected transaction state | Administrator/System-owned journal directory, restrictive verified DACL, exclusive transaction ownership, bounded schema, atomic durable phase replacement, crash injection after each phase. A writable JSON journal alone is insufficient. |
| Retained releases | Separate immutable old/new roots; full verified core, native, plugin and approved model manifests; no in-place replacement of executing source/binaries; preserve old payload until rollback retention policy permits removal. |
| Host identity | Official Server-role enrollment and one absolute private configuration; preserve owning-host credentials, grants and license; never copy a Client identity or Razi settings into an installer. |
| Admission | Private correlated admission closure with fresh zero-inflight, completion-certain proof across model, text, CRM, Secretary and other accepted work; uncertain completion blocks transition. |
| SCM ownership | Exact service name, quoted absolute command, LocalService account, expected installation root and release; refuse adoption of foreign or differently configured services. Scope stop/start to the owned service/tree. |
| Candidate health | Authenticated application identity plus required functional readiness; SCM RUNNING, open port or public capability response alone cannot commit. |
| Shared selection | Publish common desktop/service selection only after verified health; desktop shortcut supplies Server role and exact private configuration. Current icons lack these arguments. |
| Failure/reboot | Durable recovery from every prepared, service-selected and publish phase; validate retained old release before rollback; failed rollback remains recovery_required and admission stays closed until explicit recovery. |
| Setup integration | Connect the qualified adapter before replacing any old target; preserve Client/ARM setup behavior. Fresh installation needs its own absent-previous-release path; the current transition protocol assumes a previous selection. |

Do not substitute the Developer snapshot activation scripts for this installed
product lifecycle. Their host-specific private observer inputs and source Python
environment do not qualify frozen portability or fresh Server provisioning.

## Windows A100 qualification matrix

Read-only inventory identifies Windows Server 2019 without a GPU, active demo
PACS/MongoDB and occupied ports 104, 8000, 8005 and 8085. No sampled 8002 listener
was observed. This is a shared demo host, not a clean Windows 10/11 baseline.
No installer, firewall change, reboot or service mutation has been performed.

| Scenario | PyInstaller | Nuitka | Prerequisite / acceptance |
|---|---|---|---|
| Clean Windows 10/11 fresh install | Pending | Pending | Separate disposable VM or restorable clean host; no Developer Python dependency. |
| A100 isolated side-by-side install | Pending | Pending | Isolated core/state/ports; preserve demo PACS and MongoDB; snapshot/restore plan verified before execution. |
| Session 0 boot and licensed Server admission | Pending | Pending | LocalService ACL/native dependency tests and official test Server provisioning. |
| GUI/service/child release identity | Pending | Pending | Exact shared revision; full core/plugin/native/model payload verification. |
| Busy, uncertain and idle upgrade | Pending | Pending | Busy/unknown refuses; idle qualifies; no accepted work cancelled. |
| Corrupt candidate and failed health rollback | Pending | Pending | Retained previous release recovers with original host-private configuration. |
| Crash/reboot at every journal phase | Pending | Pending | Protected durable journal recovery; no pointer/service split. |
| Client coexistence and uninstall isolation | Pending | Pending | Client settings/license/data and unrelated PACS services remain intact. |
| GUI, model, Brain and mobile acceptance | Pending | Pending | Same candidate synthetic functional tests; independent Android and iOS results. |

The canonical coordinator still blocks promotable Server releases. Its
`--local-install-qa --target server` exception creates a non-promotable candidate
only after required input gates; it does not waive these qualification checks.
Historical credential remediation, clean exact-commit synchronization receipts,
complete Developer parity and required user acceptance remain release gates.

## Implemented adapter foundation, follow-up

`tools/eagle_eye/installed_release_host.py` now implements the installed host
protocol against explicit Windows primitives. It has no import-time execution,
CLI activation command, automatic reboot recovery hook or setup integration.
This advances the missing adapter implementation; it does not qualify an updater.

Implemented boundaries:

- Separate retained release roots, full immutable core verification, exact full
  payload inventories and rejection of extra files, missing files and reparse paths.
- Administrator/System-owned protected transaction directory, LocalService read
  access only, exact DACL/owner/protection readback and exclusive file ownership.
- Bounded atomic journal and active-selection replacement with file flush and
  Windows write-through rename; failed replacement leaves the previous receipt.
- Exact journaled SCM command and LocalService ownership before service operations,
  bounded cooperative stop/start, command-only selection and untouched account,
  dependencies and password. No foreign service adoption or process kill exists.
- Authenticated health requires qualified core identity plus the expected aggregate
  payload identity; a core-only capability response is deliberately insufficient.
- Server shortcut supplies role and absolute host-private config, and publication
  failure rolls service/shortcut/pointer back. Shared publication is a recoverable
  transaction, not an OS-level atomic update across SCM, shortcut and filesystem.
- Explicit conservative crash recovery restores a fully verified retained old
  release even if candidate bytes became corrupt. Unknown drain, malformed receipts
  and failed rollback require retained closed admission rather than silent resumption.

The existing `release_package.transition()` can use this host only when its caller
provides the actual private admission controller and authenticated readiness probe.
The controller context returns an object with `drain()` and `retain_closed()`:
the first must return a fresh correlated closed/zero/completion-certain receipt,
and the second must prevent reopening admission on context exit. The probe accepts
`(release_id, payload_id)` and must verify the live process and its selected payloads,
returning `{ready, qualified, release_id, payload_id}`. Echoing arguments is not a
qualified probe. Existing capability output does not yet attest this payload ID.
No fake controller or synthetic readiness callback may be used on A100 or Razi.

Baseline selection enrollment accepts only an already healthy exact-owned install.
Fresh absent-service provisioning, Server-role enrollment, startup admission fencing,
private drain transport, live payload attestation, automatic crash/reboot entry point,
canonical freeze inclusion and Inno wiring remain required integration work. The
protective existing-target fence and canonical Server release block remain intact.

Initial five behavioral guards failed before the new module existed. Current
synthetic qualification covers commit, rollback, uncertain drain, foreign SCM,
unlisted/corrupt payloads, corrupt old release, crash phases, failed journal writes,
SCM field isolation and ACL readback. Actual Windows operations are replaced in
these tests; no clinical service, host ACL or desktop shortcut was mutated.

## Fresh setup and runtime barrier implementation

The next source slice implements `tools/eagle_eye/fresh_server_install.py` and
`modules/ai_imaging/eagle_eye_remote/startup_barrier.py`. Fresh setup refuses an
existing Eagle Eye SCM entry or installation transaction. It requires official
host-bound Server provisioning before registration. It changes only the absent
`AIPacsEagleEye` service, never PACS/MongoDB, firewall rules or occupied ports.

The protected startup manifest binds a canonical transaction UUID, qualified core
release ID, full payload identity and exact host-private configuration SHA-256.
Runtime admission starts quiesced before new HTTP/native work. It publishes a
separate LocalService-writable readiness file with actual SCM/child PIDs, runtime
UUID and the zero/certain admission snapshot. Readiness validates the exact live
SCM command/account, bounded parent chain and process creation ordering.

Only a matching Administrator/System-writable marker and committed journal can
release admission. There is no public release endpoint or timeout-to-open path.
Normal reboot before commit stays closed. After live release acknowledgment,
fresh setup records final `committed` and removes only its internal barrier config
selector, preserving every host setting. A crash before selector removal still
uses the matching committed journal. Ordinary later settings edits are therefore
not permanently blocked by the installation-time configuration digest.

Fresh rollback requires a new certain closed proof before stopping/removing the
exact-owned service or shortcut. Unknown completion retains the service and a
recovery-required journal. Explicit recovery is implemented, but an automatic
boot recovery caller and real private drain transport still need qualification.

The runtime `installer_entry` dispatcher distinguishes package staging from service
activation. Stage-only can write `package_staged_service_not_activated`; missing
official signed Server entitlement writes `awaiting_official_server_provisioning`.
Provisioning uses the existing `renewal.server_manager(config).status()` with exact
`eagle-eye-server`, valid and nonlegacy checks. No Client key, copied Razi identity,
synthetic license or dummy activation callback is accepted. The default dispatcher
does not activate without a reviewed host driver. This limitation is intentional.

Both backend specifications explicitly include the dispatcher, runtime barrier and
two tools adapter modules. Source dispatch/packaging tests are not frozen import
proof. The guarded owner slice currently passes 48 tests (host adapter, barrier,
fresh setup and dispatcher), direct exit 0; adjacent ownership/package tests are
recorded separately. No actual installed operation has been exercised yet.

## Concrete Inno integration prerequisites

Current Server Inno layout puts stamped core at `{app}` beside setup, Legal,
uninstaller files and mutable User Data, while plugins/models live in mutable
ProgramData module roots. This does not satisfy the new exact immutable core plus
payload inventory boundary. Do not waive extra-file checks to hide this mismatch.

Before enabling activated install QA, select a Server-only retained layout such as
`{app}/releases/<release_id>/core`, keep setup/uninstaller/runtime state outside it,
and select the same immutable payload revision in the runtime package resolver.
Client/ARM layout remains unchanged. Generate the protected installer request from
the exact staged release manifest and host-selected private configuration, then
route the postinstall dispatcher through that request. Publish the ordinary Server
shortcut only after qualified readiness; a stage-only receipt must remain visibly
distinct from a running licensed Server. Existing-target upgrades remain fenced.

The smallest authorized build lane after input and source/function acceptance is:

```powershell
.\.venv_build\Scripts\python.exe tools\build\build_local_candidate.py `
  --local-install-qa --target server `
  --asset-root generated-files/distribution-assets-native-vc143-vmtk-service-20260928
```

Omitting `--backend` selects both Server backends. This is non-promotable install QA,
not a full release or distribution approval. Build environment `pip check` and the
actual September 28 service-dependency preflight passed. Canonical source version
observed during preparation is 3.7.2; preserve concurrent version-owner changes.
New current-version portable inputs must be regenerated through the documented
preparation tool with actual verified development models and complete Python bases;
never rename an old seal or supply synthetic test assets to a real build.

## Concrete fresh-install layout and driver follow-up

The frozen Server now selects a core-sealed sibling `plugin_packages` tree exclusively. The canonical edition stage records its complete payload inventory before stamping the core. Client and Developer lookup remain unchanged. Both compiler backends explicitly include the installer dispatcher, immutable layout, startup barrier and OS adapters.

Inno receives the exact core release ID from the canonical compiler and copies `core` and `plugin_packages` under `releases/<release_id>`. It invokes the frozen setup dispatcher synchronously. That dispatcher constructs and protects the private setup request before reading it back through ACL verification. With no supplied host-private config or valid officially provisioned Server license, the receipt remains staged and no service is registered. The generic Client shortcut and automatic GUI launch do not run for Server; activation publishes the owned Server shortcut.

The concrete fresh driver certifies removal only for the same live SCM-owned child with matching protected readiness, quiesced zero-work admission, and an absent protected release marker. Its proof retains `state=quiesced` and explicitly certifies `never_released=true`. After marker publication, rollback refuses to infer drain safety and preserves the recovery journal/service. Upgrade and post-release recovery still require a real private drain transport; SCM stop is not a substitute. Readiness attestation is not authenticated HTTP/provider acceptance.

Read-only A100 inventory through the pinned central SSH configuration on 2026-10-10 returned WIN-I5E5QM7V2R2, no AIPacsEagleEye service, and no standard Server ProgramData/install roots. No Server license was found in those absent standard roots. Provisioning elsewhere is not inferred. No service, PACS, MongoDB, occupied port, or host identity was changed.

The current-version input audit passed service dependencies, native runtime parity, Brain, lesions, alignment and total-spine. Official Breast preparation copied the actual verified dependencies, source and weights into a new 3.7.2 output, then failed the bounded 120-second isolated import probe. That incomplete output has no certified manifest and cannot be used as a build input. Bone Age official preparation and bounded Breast sub-import diagnostics continue separately. No old seal or redistribution approval was relabeled.

Source verification: 47 focused installer/layout/distribution checks passed before the final Inno guards. This is not a frozen build, installer compile, installed GUI pass, A100 install, upgrade or clinical qualification. Inno compilation and actual host lifecycle acceptance remain required.

Final source guard receipt: `generated-files/eagle-eye/installer-foundation-20261010/final-local-tests.xml` reports 90 passed, exit 0. This includes the real barrier readiness shape, release-ack write retry, durable pre-config intent on injected write interruption, core-sealed frozen activation, stopped/absent-service process-absence prerequisite, and unsafe post-marker rollback refusal. The source contract is ready for parity staging; frozen Inno compilation and A100 lifecycle acceptance remain unperformed.

The independent Breast import diagnostic succeeded with measured imports: torch 6.452 s, torchvision 5.751 s, pydicom 0.548 s, numpy 0.000 s, pandas 1.348 s, itk 0.557 s, GDCM construction 8.699 s; total 23.356 s. Cold I/O pressure is a plausible explanation of the first timeout, not proof. A canonical fresh retry will preserve the unsealed failed output and retain the official 120-second probe budget after the concurrent Bone Age preparation finishes.

Inno post-install activation failure is non-aborting: it displays an explicit recovery message and retains candidate binaries, private receipts and any owned service. It never raises a post-install exception that could trigger file rollback. Installer completion does not certify activation. The focused compiler/layout/entry follow-up reports 32 passed, exit 0.

Durable intent now precedes both manifest and config publication. The protected journal retains manifest metadata without duplicating its payload inventory; explicit recovery reconstructs an absent manifest from that metadata and the journaled candidate. An injected crash before manifest creation is recoverable without starting a service. Focused follow-up: 27 passed, exit 0.

## Cooperative post-release installer control integration

The concrete fresh adapter now constructs the reviewed frozen identity from its exact sealed core, release manifest file, config, executable and current SCM PID/creation identity. It requests `service_control.stop_when_idle` through the protected correlated custom SCM control path with one bounded deadline. It accepts only the exact committed `CERTIFIED_IDLE_EXIT` receipt with matching identity, closed admission, integer zero in-flight work and no completion uncertainty. It then observes the same owned service STOPPED with PID zero before allowing removal. Rollback skips `SERVICE_CONTROL_STOP` after this certified cooperative proof. Unknown completion, identity drift and deadline expiry have no forced or SCM-stop fallback.

Fresh setup explicitly provisions the protected control directories before registering SCM. Both frozen packaging manifests explicitly include the service-control module. The conservative process-absence check remains an additional gate; any inaccessible or unknown process observation refuses cleanup. Actual SCM and installed-host qualification remain pending: source tests do not prove the Windows control has executed successfully on A100.

Adapter source receipt: 95 passed, exit 0, `generated-files/eagle-eye/installer-foundation-20261010/cooperative-adapter-tests.xml`. It includes successful committed receipt, unknown completion, mismatched identity and proof that certified rollback does not issue SCM stop.

Both fresh 3.7.2 portable engine preparations subsequently completed through the official tools, including unchanged isolated probe budgets and complete bundle validation. The final canonical current-version portable-engine preflight passed. Exact provenance and probe receipts are recorded in `generated-files/eagle-eye/installer-foundation-20261010/prepared-model-inputs.json`. These are local non-promotable QA inputs; no clinical or redistribution approval is inferred.

Final cooperative adapter matrix: 98 passed, exit 0. Process absence verification excludes only reserved Windows idle/kernel PIDs 0 and 4; inaccessible nonkernel processes still refuse cleanup. A read-only local audit confirmed the reserved kernel process caused the otherwise unconditional AccessDenied refusal. No process was stopped by that audit.
