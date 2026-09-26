# Development workflow

The canonical workstation repository is on the control computer:
E:/ai-pacs/ai-pacs codes/ai-pacs beta version. This remote revision is an exported
source subset, not a full Git clone; tests, dependencies and modules may be absent.
Preserve remote changes and deliberately merge them back to the canonical repository.
Never assume a Git push includes ignored Slicer binaries or model assets.

## Code map relative to the active source root

| Component | Source |
|---|---|
| Source listener entry | tools/eagle_eye/serve.py |
| API and current jobs | modules/ai_imaging/eagle_eye_remote/server.py |
| Request validation | eagle_eye_remote/contracts.py under modules/ai_imaging |
| PACS source selection | eagle_eye_remote/source.py |
| Scheduling and directory ownership | eagle_eye_remote/scheduling.py, ownership.py |
| Isolated analysis adapters | eagle_eye_remote/adapters.py |
| Artifact allowlist and checksums | eagle_eye_remote/artifacts.py |
| Client and resume handles | eagle_eye_remote/client.py |
| SCM supervision foundation | eagle_eye_remote/service_host.py, bootstrap.py |
| Breast/Bone adapters | modules/ai_imaging/eagle_eye_engines/ |
| Brain and lesion workflows | modules/ai_imaging/eagle_eye_brain/ |
| Spine modules | modules/ai_imaging/eagle_eye_alignment/, eagle_eye_total_spine/, offline_lumbar/ |
| Slicer resolver | modules/mpr/advanced_3d_slicer/slicer_custom_app/launch_slicer.py |

Some vendor/model helpers were deliberately not exported. Inspect import closure
before qualifying a model; a directory's presence is not a complete implementation.

## Change cycle

1. Read status/backlog and current runner; choose one bounded change and acceptance.
2. Snapshot file hashes and preserve prior source. Prepare a NEW revision directory
   for edits; do not modify files being used by active workers.
3. Use the dedicated interpreter in VS Code. For changed dependencies build a new
   environment from reviewed pinned wheels/locks. Do not use pip upgrade globally.
4. Add a meaningful fail-before regression guard in the canonical repository and
   run the affected direct pytest selection. Never touch live dicom.db in tests.
5. Transfer only the reviewed change and its complete runtime closure; verify hashes
   on target. Keep secrets, patient files and private job logs outside the snapshot.
6. Finish the shutdown prerequisite in BACKLOG before admitting model jobs. At empty
   pilot stage, explicitly verify queue and owned listener identity before stopping.
7. Activate the candidate by updating Run-EagleEye.ps1, preserve the old runner,
   start once, verify API and selected analysis, and record receipts. Roll back the
   changed revision on failure; do not reinstall unrelated applications.
8. Update CURRENT_STATE, BACKLOG and HISTORY, then reconcile source into the canonical
   repository with a reviewed commit when the Git/release workflow permits it.

## Native Slicer and builds

Use the complete corrected runtime, not only its EXE. App-local VC143 DLLs are
required on Razi. Source changes to Python do not normally require native rebuild;
native C++/CMake/resources do. Build owner maintains assembly, provenance and cache.
Current canonical all-role input cache on the control computer is
generated-files/distribution-assets-native-3.6.7-vc143-20260923. It includes the same
native binary plus ten pinned CRT files. Existing installers are historical unless
freshly built/verified against this baseline. Follow canonical BUILD.md and RELEASE.md;
this local guide is not an alternate release or installer command route.
