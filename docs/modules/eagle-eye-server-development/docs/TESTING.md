# Verification and acceptance

Use synthetic inputs for plumbing tests. For real studies use the owner's authorized
selection and authoritative identity binding; keep identifiers and outputs out of
docs, Git and external services. Prior workstation model results are not Razi results.

## Evidence recorded

| Check | Result and scope |
|---|---|
| Transfer |8,096 original source/runtime/wheel files verified on target by SHA256|
| Main environment |Offline installation and pip check passed; not model qualification|
| API |Authenticated protocol1 and input_mode=pacs_references passed|
| Authentication |Unauthenticated capabilities returned401|
| Remote client |Actual Client through temporary SSH tunnel passed; own queue empty|
| Slicer correction |All7,836 baseline runtime files unchanged; ten CRT DLLs added|
| Native startup |Ordinary --version and synthetic no-main-window script exited0|
| After activation |API and remote Client passed again; clinical listeners unchanged|
| Fresh doc preflight |Task running and127.0.0.1:8042 observed on2026-09-23|

Canonical regression files (not assumed present in the remote export):
tests/code/ai_imaging/test_eagle_eye_service_host.py, test_eagle_eye_remote.py,
test_eagle_eye_roles.py, test_eagle_eye_scheduling.py, test_eagle_eye_settings.py;
tests/code/builder/test_slicer_runtime_current_source.py and related CRT guards.
Run direct pytest with QT_QPA_PLATFORM=offscreen, PYTHONPATH=., retries disabled and
inspect the exit code. The historical run_test.ps1 wrapper is not proof of success.

## Required next acceptance

1. Shutdown/restart: empty and active synthetic jobs; no orphan workers or duplicate listener.
2. Exact model/runtime manifests and actual imports in each isolated environment.
3. Read-only PACS source mapping: complete selected series, correct patient/study/
   series/SOP binding, missing/duplicate/mixed identity rejection, source unchanged.
4. Actual authorized Bone Age and Breast detection outputs under measured resource
   budgets. Breast classifier remains explicitly deferred/unqualified.
5. Every other advertised model on supported resources, comparing geometry, masks,
   measurements and reports. Do not run Brain under insufficient free memory.
6. New Standard client UI submission/result review, disconnect/reconnect, explicit
   cancel, owner isolation and checksum verification. API tests do not pass GUI gates.
7. Concurrent clients, queue limits, low disk, worker failure, process restart and
   recovery; never inject failures into clinical PACS.
8. True SCM/service account/reboot, frozen installers on clean hosts, backup restore
   and proposed24/72-hour soak only after preceding gates pass.

Receipt for each test: timestamp, source/model/Slicer hashes, interpreter, account/
session, synthetic or authorized scope, command, exit code, result, limits, reviewer
and rollback. Store private artifacts locally and publish only redacted summaries.
