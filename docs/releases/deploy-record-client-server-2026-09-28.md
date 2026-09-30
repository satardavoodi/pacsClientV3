# Deployment Safety Record - AI-PACS Client and Server - 2026-09-28

**Change:** latest-source Standard Client and Eagle Eye Server local install-QA packaging.
**Gate result:** BLOCKED for publication. Six local install-QA installers completed; no production deployment or official Server release is authorized.

## 2026-09-29 superseding local install-QA build

**Gate remains BLOCKED for production publication and clinical deployment.**
The latest `fix 1` thumbnail-card change and Slicer import repair were frozen
into new Client and Server local install-QA candidates under version 3.6.9.
All four Client and both Eagle Eye Server installers now exist in the canonical
backend installer folders. Both role coordinators, all four backend builds,
and the two staged-coherence checks exited 0. Independent installer SHA-256,
size, role-specific inventory, and Windows FileVersion checks passed for all
six files. The authoritative current paths and hashes are in the
"2026-09-29 local install-QA rebuild" section of
`docs/releases/VERSION_3.6.9_RELEASE.md`. The older artifact table below is
historical evidence for superseded same-version QA binaries and must not be
used to select or verify today's files.

The updated `fix 1` source files match in the two frozen snapshots and the
thumbnail module appears in both PyInstaller PYZ tables and Nuitka compile
reports. The checked Slicer resident and lumen files match their source in
all four backend stages. Both Server stages have standalone Breast and Bone
Age runtimes and manifests. Client PyInstaller role-specific metadata was
regenerated from its own completed compiler stage after cross-role cleanup;
the Client installer hashes were verified during that recovery. These checks
prove packaged content, not successful 3D Slicer activation on another PC.

The Client and Server snapshots are not the same source identity: a later Home
search change is present only in Server, and still-later Education work is in
neither. No Git commit, tag, push, new target-host installation, or clinical
validation was performed for this rebuild. The earlier Razi installation
record below refers to its explicitly recorded older checksum and does not
mean these replacement files were installed there. Fresh source GUI and
installed clean-host workflows, ARM emulation, Server service transaction,
model redistribution/clinical acceptance, signing, and the release Git receipt
remain open gates.

## Authorization and scope

The user explicitly requested completion of official Server packaging, then both
role groups: four Client and two Server installers. This does not authorize
production SCM changes, clinical deployment, guessed model features, fabricated
credentials, or skipping acceptance. The previous attachment-only preparation
clone is not latest source. No new commit, tag or push has been made; local
install-QA compilation completed, not publication.
On September 28 the user stated that Developer Run had been tested and asked to
finish the official installers. This confirms their build intent and source-level
confidence; it does not verify a frozen installer, Session 0 service, clean-host
model loading, or production clinical behavior.

## Workstation and service

- [x] CONFIRMED - Genuine pywin32 311 installed only in `.venv_build`; pip check and six required native imports passed.
- [x] CONFIRMED - Fresh-cache build-wheel refresh guard failed before; 16 focused asset/lumen/dependency checks pass afterward, exit 0. Donor/model immutability and failed-resolution non-completion are guarded.
- [x] CONFIRMED - Installed listener admission and backend-aware frozen detection: 40 owner checks and 60 combined independent checks passed, exit 0. No SCM operations performed.
- [x] CONFIRMED - Exact-command/LocalService-owned bounded stop/start/removal primitives: 18 synthetic lifecycle checks; final independent combined selection 78 passed, exit 0, three existing SWIG warnings. No installer wiring or live SCM acceptance inferred.
- [x] CONFIRMED - New native/VMTK/service cache at `generated-files/distribution-assets-native-vc143-vmtk-service-20260928` passed a complete SHA-256 inventory check for 34,469 files (4,356,143,152 inventoried bytes), VMTK bundle verification, real pywin32 wheel/lock/import preflight, and byte-for-byte Developer Run Slicer parity; verifier process exited 0. Build-environment `pip check` also exited 0.
- [x] CONFIRMED - Packaged plugin mirror verification matched 486 pairs, exit 0. The documented direct pre-build selection first exposed two stale legal-notice version lines (148 passed, 2 failed); after metadata-only correction, all 150 passed, exit 0. The compile-only Inno matrix passed Standard, ARM-emulated, and Eagle Eye synthetic editions and rejected three independently missing Server prerequisites. No customer installer was produced by that probe.
- [x] CONFIRMED - Five affected MPR test files initially passed only in separate processes (4 + 8 + 4 + 14 + 9 = 39 tests). Their combined process reproduced a test-only `QCoreApplication` to `QApplication` ordering abort (Windows 0xC0000409). The MPR owner corrected two test fixtures without changing runtime code; an independent combined rerun now passes 39 tests, exit 0, with six SWIG warnings. This does not replace fresh source GUI or installer acceptance.
- [ ] BLOCKED - Server installer configuration enrollment, LocalService ACLs, retained-core upgrade/rollback and uninstall transaction are not complete. Current prior-uninstaller ordering cannot safely be patched only after installation.
- [x] CONFIRMED INPUT ONLY - New sealed standalone Breast (Python 3.10.20, 18,796 manifested files) and Bone Age (Python 3.12.13, 12,667 files) inputs passed full hash and isolated-import probes. Sealed runtimes from a separate working directory completed real-model synthetic jobs; Breast explicitly returned unavailable classification. Both backend materializers, Server profile and Inno stage now require them. This does not prove installed portability or clinical qualification.
- [ ] BLOCKED - Neither engine has installed/frozen clean-host acceptance or a real manifest-bound redistribution approval. The old development venv bundles must never substitute for these standalone inputs.
- [ ] BLOCKED - At the default local roots, Brain `distribution-approval.json` and Lesion/Alignment/Total Spine `acceptance.json` are absent. File presence was checked, not full payload validation or a current rights/inference acceptance pass. Do not fabricate these receipts from source-test success.
- [ ] BLOCKED - Both frozen backends require isolated clean-host Session 0, TLS/client-owner isolation, owned loaded-work shutdown/recovery and Slicer no-window acceptance. Win A100 was reached read-only, but is a semi-production DICOM/service host without a GPU; it is not a clean-host or GPU-model acceptance substitute. No installer or service was installed there.
- [ ] BLOCKED - Latest source owner acceptance, affected GUI workflows, exact immutable reviewed commit and fresh multi-remote sync receipt remain pending.
- [x] CONFIRMED BUILD ONLY - The full six-artifact matrix is in the canonical backend installer folders. Both Server backends and both Client backends exited 0; the Client and Server staged-coherence checks passed. All six files have v3.6.9 Windows FileVersion/ProductVersion, and independent SHA-256 and byte-size checks match their role-specific `distributions-client.json` or `distributions-server.json` inventories. These remain local install-QA artifacts, not published or accepted releases.
- [ ] BLOCKED - ARM64-host installation and runtime acceptance remain pending. The ARM outputs are x64-on-ARM64 emulation installers, not native ARM64 binaries.
- [x] CONFIRMED - Both Client Nuitka local-QA installers completed with v3.6.9 Windows version resources and hashes matching `distributions-client.json`; cross-backend staged coherence passed. The staged Slicer executable matches the verified native asset cache, and sampled custom UI/resident files match the immutable Client source. This is package-content evidence, not installed GUI acceptance.
- [x] CONFIRMED - Starting Server PyInstaller clean-build removed the shared canonical Python installer folder, including completed Client outputs. The original completed Inno compiler files remained intact. A fail-before/passing cleanup regression now protects the other role, and bounded same-candidate local-QA recovery restored both Client files after Server Python completed. No application recompilation was needed; the recovered Client hashes and 3.6.9 Windows versions match their role inventory, and staged cross-backend coherence passed again.

## Completed local install-QA artifacts

These are byte-level build receipts, not installed-host or publication receipts.
All paths below are relative to the repository root. The Client and Server
candidate snapshots have different source fingerprints because the Server-only
standalone engine packaging was added after the Client snapshot; publication
requires a newly reviewed exact source commit and release synchronization.

| Backend | Role | Installer path | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| PyInstaller | Client Standard | `builder/output/installer/ai-pacs standard v3.6.9.exe` | 628,941,676 | `32f04360b72cf92c65b9e8f5b2ba7019a0815fa6a89838d5468f0d274a15b4af` |
| PyInstaller | Client ARM64-emulated | `builder/output/installer/ai-pacs arm64-emulated v3.6.9.exe` | 628,941,846 | `d701b4399bcac70ab2b2118c351d260b90f536c8baa9cd38c3ba216732feb111` |
| Nuitka | Client Standard | `builder nuitka/output/installer/ai-pacs standard v3.6.9.exe` | 612,059,500 | `ba78b97604cd3ed16552d1e953e9940a0deb221573ae7e48afd4bb911f57792e` |
| Nuitka | Client ARM64-emulated | `builder nuitka/output/installer/ai-pacs arm64-emulated v3.6.9.exe` | 612,059,689 | `09447d6f02a6deb5e5f9cf80634919ddff1d0402819640428e62f5b796a3cda4` |
| PyInstaller | Server Eagle Eye | `builder/output/installer/ai-pacs eagle-eye v3.6.9.exe` | 2,789,279,701 | `9a9ea026189ecbb21e24cac798536f6edf8c29f832b514e9a0d8318efb846a23` |
| Nuitka | Server Eagle Eye | `builder nuitka/output/installer/ai-pacs eagle-eye v3.6.9.exe` | 2,772,313,621 | `9ac950b08d6227d57d5f8d1a73d750ee7df9ff190f3e197bcff18726b3adf07e` |

The Server Inno logs show both Breast and Bone Age runtimes and weights being
compressed. Both backend candidate stages independently contain each engine's
`runtime/python.exe` and `manifest.json`, with no `runtime/pyvenv.cfg`. The
Nuitka Server staged Slicer executable has the same SHA-256 as the verified
native distribution asset (`e28c88dbda85fb919eac3b668e28f4f2f83c841c338338d700ba41c4cca814a0`). The
standalone source bundles passed full manifest and synthetic
inference checks, but no installed clean-host inference or Session 0 service
test has been performed. The local development PC has an NVIDIA GeForce GT 730
with 4,096 MiB reported by NVIDIA-SMI (driver 456.71, CUDA 11.1 maximum) and
Intel UHD Graphics 630. It is not a clean GPU QA host, and model compatibility
with the GT 730 has not been established. Win A100 is a semi-production DICOM
node without a GPU and was not used for installer testing.

## Cross-project and clinical boundaries

- [x] CONFIRMED - Client/Server ownership and reference-only job contracts remain in the existing server/client plan. Client must not acquire Server weights or provision SCM.
- [x] CONFIRMED - No patient data, credentials, production service state or clinical outputs were changed by prerequisite work. Synthetic guard fixtures contain no clinical inputs.
- [ ] BLOCKED - Latest imaging changes require attributable workflow acceptance; old source or artifact receipts are not transferable to this candidate.
- [x] CONFIRMED - The current tracked worktree has zero high-confidence findings from the repository release secret scanner; the scan returned exit 0 and did not display secret values.
- [ ] BLOCKED - Historical credential revocation/rotation and published-history remediation are separate unresolved gates; a clean current-tree scan does not prove them complete.
- [ ] BLOCKED - Signing, redistribution evidence, legal review and explicit production approval remain pending.
- [x] CONFIRMED - Windows Authenticode reports `NotSigned` for all six local install-QA installers. They must not be represented as signed release artifacts.

## Known model limitation

The owner previously deferred Breast's incompatible nine-feature classifier
contract. Detection may return explicit `classification_status=unavailable`;
successful detection/transport is not full classification qualification. Do not
pad or guess inputs or label missing probabilities as negative findings.

## Blocking items

1. Freeze and accept the latest GUI/source state, resolve the dirty worktree,
   review the exact versioned commit, and obtain the fresh three-remote Git receipt.
2. Qualify the prepared standalone Breast/Bone payloads in both installed
   backends and obtain actual model distribution/acceptance evidence without
   inventing approvals.
3. Complete transactional Server service installation, configuration enrollment,
   ACL/rollback behavior, and both-backend isolated clean-Windows acceptance.
4. Confirm historical credential revocation/history remediation, clinical and
   privacy sign-off, and explicit manual approval before production deployment.

## Rollback and sign-off

Keep completed caches and previous artifacts immutable. The new cache is a
separate input root, not another installer output folder. Ordinary builds reuse
the qualified native Slicer baseline. Preserve original dirty source/settings;
never force shared branches or move published tags.

Manual production approval: NOT YET GIVEN.
Next required operator input: identify an isolated clean Windows QA host.

## Verified input preparation

The cache preparation command completed before the independent September 28
verification. It ran separately from installer compilation:

```powershell
.\.venv_build\Scripts\python.exe tools/build/prepare_distribution_assets.py --profile all --root generated-files/distribution-assets-native-vc143-vmtk-service-20260928 --reuse-non-slicer-assets generated-files/distribution-assets-native-3.6.7-vc143-20260923 --download-wheels
```

The new root is an immutable build input; do not prepare into it again or edit
its completed donor. An independent `.venv_build` process ran
`verify(..., profile='all', require_lumen=True)`,
`preflight_server_service_dependencies(...)`, and
`verify_cache_matches_developer_runtime(...)` in sequence, exiting 0 after all
three checks. This is asset and dependency evidence, not installer, clinical,
distribution, or production acceptance.

## Razi clinical-server installation request (2026-09-28)

**Target:** `pacs` / `WIN-CTBQPS2GSM3`, the live Razi clinical PACS VM.
**Requested action:** transfer and install the newly compiled Eagle Eye Server
EXE, then test all functions on that host.
**Gate result:** BLOCKED. No installer was transferred or executed on Razi.

- [x] CONFIRMED - Read-only SSH `hostname` returned the expected target identity.
- [x] CONFIRMED - The two Eagle Eye v3.6.9 EXEs are local install-QA outputs with matching build inventories, not release-synchronized or signed production artifacts.
- [ ] BLOCKED - Frozen PyInstaller and Nuitka Server installations have not passed an isolated clean-Windows acceptance run. Source Developer Run and synthetic model jobs do not establish installed Session 0, TLS, Slicer, or clinical workflow behavior.
- [ ] BLOCKED - The installer still lacks transactional Server service enrollment, LocalService ACL/configuration provisioning, and safe upgrade/rollback. Its prior-uninstaller ordering risks removing a working installation before the new one is accepted.
- [ ] BLOCKED - The live Razi PACS holds patient data and an active source-service pilot. No target-specific maintenance window, restorable application rollback, and post-install clinical verification have been confirmed for replacing its runtime.
- [ ] BLOCKED - Model redistribution/acceptance evidence, historical credential remediation, signing, exact reviewed source commit, and the three-remote Git receipt are not complete.
- [ ] BLOCKED - The target is not a clean GPU acceptance host; no qualified GPU/model performance receipt exists for all requested functions there.

The owner requested installation, but that request does not convert the above
unverified gates into confirmations. First qualify both frozen backends on an
isolated Windows QA host with a suitable GPU, complete the installer transaction
and rollback, and review model/security/release evidence. Only then plan a
separate Razi maintenance-window deployment with explicit informed sign-off.

Manual clinical deployment approval after blocker review: NOT YET GIVEN.

## Razi workstream read-only assessment and isolated QA route (2026-09-28)

**Gate remains BLOCKED for Razi transfer/installation.** No installer was copied
or executed remotely, no service/listener/configuration was changed, and no
patient inventory, image, credential value or clinical database was accessed.
The following is a current observation and a qualification plan, not acceptance.

### Independently verified evidence

- Razi identity: WIN-CTBQPS2GSM3, Windows Server 2022 Standard, 32 GiB RAM,
  48 logical processors. Only Microsoft Basic Display Adapter was enumerated;
  no Windows NVIDIA/CUDA capability is established.
- AIPacsEagleEye is Running, automatic startup, NT AUTHORITY/LocalService.
  The service Python -> workstation-venv Python -> listener Python ancestry
  confirms that the existing source pilot owns 0.0.0.0:8002. Different parent
  and listener PIDs do not indicate a second independent service.
- The known full-workstation source entry and Eagle Eye backups directory exist.
  Free space sampled approximately C:171.1 GiB and D:3494.5 GiB. Neither folder
  presence nor free capacity establishes a complete, restorable rollback.
- wina100 is WIN-I5E5QM7V2R2, Windows Server 2019 Standard, with active
  AIPacsCoreService and InoCrmDashboard and only Basic Display Adapter reported.
  It is not a clean QA machine. No 8002 listener was observed there; a free port
  does not authorize installation or establish workload isolation.
- Both local artifacts were independently hashed and inspected without execution:

| Backend | Bytes | SHA-256 | Authenticode |
|---|---:|---|---|
| PyInstaller | 2789279701 | 9a9ea026189ecbb21e24cac798536f6edf8c29f832b514e9a0d8318efb846a23 | NotSigned |
| Nuitka | 2772313621 | 9ac950b08d6227d57d5f8d1a73d750ee7df9ff190f3e197bcff18726b3adf07e | NotSigned |

These match the build handoff. Hash equality proves artifact identity only.
It does not close signing, exact-source publication, model rights, clean-host
portability, clinical behavior or the installer transaction defect.

### Route that can qualify the installer without risking Razi

1. The operator designates a disposable, newly installed Windows QA VM. Prefer
   the target OS baseline (Server 2022). Confirm host capacity before allocating
   it; no vCenter changes or VM provisioning were performed by this assessment.
   Do not clone clinical disks. Keep its virtual network isolated from clinical
   PACS/CRM and public forwarding, with a second isolated test Client where needed.
   Use the existing product port 8002 inside that isolated network.
2. Take a verified clean VM checkpoint with no developer Python, old AI-PACS,
   global pywin32, production certificates/tokens, or patient data. Install one
   backend, collect evidence, revert to the clean checkpoint and test the other.
   This requires explicit QA-host/installation authorization; none is inferred
   from SSH access to the existing servers. Windows Sandbox alone cannot certify
   the persistent SCM/reboot/upgrade lifecycle.
3. Test clean install and a separately seeded old-version upgrade. The current
   installers may be exercised destructively only in this disposable environment.
   Their observed failures must drive installer fixes and new candidate builds;
   running an unsafe installer on QA does not make that binary production-safe.
4. Use a synthetic PACS fixture and QA-only TLS/token identities. Check Session 0,
   LocalService read/write ACLs, delayed automatic startup/reboot, bounded owned
   shutdown/recovery, and desktop attachment to the single SCM-owned listener.
   Exercise unauthenticated/wrong-owner/wrong-CA/SAN failures and correct pairing.
   Keep the configured DICOM, socket, HTTP metadata and Reception ports distinct.
5. Independently test CPU support for each packaged engine. GPU qualification
   requires an isolated Windows host with a supported NVIDIA device and the
   measured driver/runtime/model combination. Neither observed Windows server
   provides that evidence; the Linux A100 cannot qualify frozen Windows DLLs,
   Windows service execution or Windows Slicer. Do not move its GPU or disturb
   its workloads as part of this review.

### Evidence needed to close each outstanding boundary

| Boundary / owner | Required concrete receipt |
|---|---|
| Installer lifecycle / build-service owner | Stage the new core before disturbing the working version; validated absolute config and protected credentials; LocalService ACLs; preserve existing model/job/result/config roots. Inject failure before and after SCM registration/start/readiness. Prove the previous core/config/service is restored and healthy, or preserved untouched. A postinstall SCM call after the old uninstaller is insufficient. Repeat both backends and uninstall without deleting clinical inputs/results or unrelated services. |
| Service and transport / Eagle Eye owner | Clean-host import evidence, Session 0 Slicer invocation from installed paths, startup/reboot/recovery, authenticated health and real queued job (SCM RUNNING alone is insufficient); PACS credential renewal and independent-client queue/cancel/reconnect tests, without credential logging. |
| Each model / module owner | Manifest/hash-bound installed load and deterministic synthetic/reference case for Breast, Bone Age, Brain volumetry, brain-lesions, lumbar, lower-limb Alignment and Total Spine. Record expected outputs and limitations, memory/time/device evidence and the exact backend. Breast classification remains unavailable until the known feature/weight mismatch is resolved; an absent classification must never become a negative clinical finding. |
| Interactive results / UI owners | Standard Client receives the matching study/series result. Exercise native landmark/endplate drag and server revision; Slicer mask edit/save/upload and changed volume, retained original, wrong geometry/owner/stale-parent rejection and reconnect. Test SAM body-box proposals on their supported projections. This is separate from HTTP acceptance and offscreen Qt tests. |
| Full workstation / viewer owners | Fresh frozen GUI: human login, study list/open, actual series drag/drop and rendering, annotations, measurements, thumbnails, Fast/Advanced/MPR domain separation, and session log review. Current source-pilot display evidence does not qualify these installers. |
| Release/model/security owners | Reviewed exact versioned source and three-remote receipt, model redistribution evidence, historical credential remediation and final artifact signing/identity. Do not represent source tests or unsigned local QA builds as promotion evidence. |
| Razi operator | Only after the preceding gates: maintenance window and informed target approval; snapshot/backup of exact service command/account/recovery policy, binaries, configuration/credential protection and ACLs; tested restoration; defined pre/post PACS/CRM and Eagle Eye health checks; one selected backend and a controlled cutover plan for existing 8002. No blanket reconfiguration of other listeners. |

No clean isolated Windows QA host has been assigned or verified yet. The immediate
operator input is that host and its permitted test scope. Installer transactional
work and release/model/security evidence can progress independently in their
owning workstreams. The present assessment does not authorize a source-pilot
update as a workaround around the blocked installer gate.

Manual Razi deployment approval after these gates: NOT GIVEN. No production
acceptance, full-model inference pass, restore-tested backup or clinical sign-off
is claimed. Policy basis: deploy-safety-check, "Any single BLOCKED item blocks
the whole deploy", together with the explicit no-transfer/no-service-change
restriction in the build handoff.

## Explicit owner override and Razi installation trial

The owner explicitly instructed installation and execution on Razi Reception after the preceding blocked assessment. This authorizes this target deployment; it does not turn unverified clinical or official release gates into passes. Selected artifact: PyInstaller Eagle Eye 3.6.9, SHA256 `9a9ea026189ecbb21e24cac798536f6edf8c29f832b514e9a0d8318efb846a23`. Remote transferred file hash matches. Previous registered 3.6.3 installation and source-service configuration were backed up under `D:\Eagle Eye Server\backups\installed-3.6.9-20260928` with restricted ACLs; source checkout remains intact. A service rollback script captures the original SCM command. Installer launched through one SYSTEM scheduled task into `D:\Eagle Eye Server\installed\3.6.9`; outcome pending verification. No unrelated PACS/CRM services are part of this cutover.

### Owner-authorized Razi trial: installed and running

- Inno completed successfully with exit 0. Installed profile: version 3.6.9, distribution `eagle-eye`; application root `D:\Eagle Eye Server\installed\3.6.9`.
- Found a real unattended installer defect: unconditional postinstall Advanced MPR `MsgBox` ignored silent suppression. After confirming the exact message and installer PID, acknowledged its existing OK button in Session 0; installer exited normally. Build owner notified for the source fix and regression guard. Temporary installation tasks removed afterward.
- Preserved the existing LocalService SCM entry, automatic start and restart recovery delays 15/60/120 seconds. Changed only its executable/configuration to the installed AIPacs.exe `--eagle-eye-windows-service` and `config\server-installed-3.6.9.json`. Prior source checkout/configuration retained.
- No active/queued analysis jobs at cutover. Existing 8002 TLS pairing and token files preserved. New installed service process owns its installed Aipacs.exe listener child on 0.0.0.0:8002. A bounded service restart succeeded; authenticated capability retrieval succeeded again afterward.
- Client-side HTTPS capability retrieval passed for seven analysis modules; correction modules now include alignment, total-spine, brain and brain-lesions, plus spine-box segmentation and multisequence lesion review. This validates service connectivity/capability delivery, not model inference or correction-result acceptance.
- PACS local HTTP health returned 200. Configuration retains 127.0.0.1:8000, DICOM 105 and socket 50052. ReceptionCrmServer remained Running. No unrelated services were reconfigured.
- Service Slicer path now uses installed ProgramData package. Its executable SHA256 `e28c88dbda85fb919eac3b668e28f4f2f83c841c338338d700ba41c4cca814a0` matches the verified native distribution asset cited above.
- Administrator desktop `DICOM Workstation - Eagle Eye Server.lnk` and Public desktop `AIPacs.lnk` target installed 3.6.9 with explicit server mode and its service-managed config. Existing source GUI processes were not forcibly terminated or duplicated. Installed GUI/login and patient inference remain separate, unperformed acceptance checks.
- Rollback: elevated PowerShell `-File "D:\Eagle Eye Server\backups\installed-3.6.9-20260928\rollback-service.ps1"` restores the original source SCM command. Existing config and previous registered 3.6.3 binaries were backed up there. Rollback was prepared but not exercised; no restore-tested claim.
- This installation/runtime smoke test is complete under the explicit owner override. The earlier clinical acceptance, signing and official-release qualifications remain unverified and are not silently marked passed.
