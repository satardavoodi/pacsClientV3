# AI-PACS 3.6.8 Client build record

Date: 2026-09-26
Status: PREPARING; no 3.6.8 installer completion claimed
Role: Client only
Lane: receipt-backed canonical release candidate

## Requested output contract

- builder/output/installer/ai-pacs standard v3.6.8.exe
- builder/output/installer/ai-pacs arm64-emulated v3.6.8.exe
- builder nuitka/output/installer/ai-pacs standard v3.6.8.exe
- builder nuitka/output/installer/ai-pacs arm64-emulated v3.6.8.exe

Use RELEASE.md followed by BUILD.md and
tools/build/build_local_candidate.py --target client --git-sync-receipt.
No alternate build/output route and no Eagle Eye Server installer are authorized.
Reuse generated-files/distribution-assets-native-3.6.7-vc143-20260923 without
recompiling the verified native Slicer baseline. Stage current Python/UI overlays
from the immutable 3.6.8 snapshot; never substitute historical 3.6.7 installers.

## Evidence to record before completion

Exact source SHA/tag/receipt; isolated candidate path; direct tests and mirror
parity; asset manifest/native parity; toolchain; backend times and exit codes;
coherence; four independently checked lengths/hashes; Windows version resources;
Qt/ICU, codec, Flow, legal, Lite Viewer and profile gates; warnings and remaining
clean-install, ARM64, clinical, signing and distribution approval gates.

Compilation completion is not production acceptance. Current progress and
exclusions are in VERSION_3.6.8_RELEASE.md.
