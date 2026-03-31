# Installer QA Checklist (PC A / PC B)

Use this checklist for every Windows installer release to validate functionality and avoid regressions.

## Scope

- Installer artifact: `builder/output/installer/ai-pacs installer.exe`
- Versioned artifact: `builder/output/installer/ai-pacs installer v<version>.exe`
- Release metadata: `builder/output/installer/INSTALL_NOTES.txt`, `builder/output/installer/SHA256.txt`
- Installation modes: **Core** and **Custom**
- Graphics path: **GPU-preferred** and **CPU-safe/software OpenGL fallback**

## 0) Pre-check (PC A)

1. Confirm build completed without errors.
2. Confirm both installer files exist and are non-zero size.
3. Confirm `INSTALL_NOTES.txt` and `SHA256.txt` were regenerated for the same version.
4. Record:
   - app version
   - commit hash
   - installer file sizes
   - build date/time

## 1) Install flow validation (PC A)

Run installer and verify each wizard stage:

1. Welcome / license page opens correctly.
2. Setup type page allows:
   - Core
   - Custom
3. Custom mode shows optional modules:
   - Advanced MPR
   - Printing
   - Run CD
   - Web Browser
   - EchoMind
4. Graphics page behavior:
   - Auto-detection hint appears
   - Manual checkbox override works
5. Ready page summary includes:
   - install path
   - selected modules
   - graphics preference
6. Install completes and launch option works.

## 2) Post-install functional checks (PC A)

After first launch:

1. Core app launches without startup error.
2. `installation_profile.json` is written in:
   - `{app}\_internal\config\installation_profile.json` (preferred)
   - or `{app}\config\installation_profile.json` (fallback)
3. Selected optional modules are available in UI.
4. Non-selected optional modules are not active by default.
5. Graphics behavior:
   - if GPU-capable: app can run in GPU-preferred mode
   - if not GPU-capable: app falls back to software OpenGL mode safely
6. Basic smoke flow works:
   - open a patient/study
   - load images
   - close app cleanly

## 3) Uninstall checks (PC A)

1. Uninstaller runs successfully.
2. App binaries are removed from install directory.
3. User data/config behavior matches product expectations (kept or removed as designed).

## 4) Cross-PC validation (PC B)

Follow `docs/performance/CROSS_PC_IMPROVEMENT_WORKFLOW.md`:

1. Pull exact same commit used on PC A.
2. Verify same installer artifact/version.
3. Repeat sections **1**, **2**, **3** on PC B.
4. Compare results and document any deltas.

## 5) Release evidence (required)

Store a short report with:

- commit hash
- installer names + sizes
- pass/fail per section
- screenshots for:
  - setup type page
  - module selection page
  - graphics page
  - completion page
- first-launch runtime outcome (GPU vs software fallback)
- known issues (if any)

## Quick pass criteria

Release is **ready** only if:

- Installer files are generated with expected names.
- Core install and launch pass on PC A and PC B.
- Custom optional module selection behaves correctly.
- Graphics fallback is safe on non-GPU or unsupported setups.
- Uninstall completes without fatal errors.
