# Installer QA Checklist (PC A / PC B)

> **Current precedence (2026-09-06):** select and create candidates through
> [`../../BUILD.md`](../../BUILD.md). Apply this QA checklist to every backend and
> edition intended for distribution. Legacy single-installer filenames below are
> historical examples, not the current six-file output contract.

Release target for this publication: `v2.3.7` (`2026-04-22`)

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
4. Confirm the release bundle included the software-render fallback runtime (`opengl32sw.dll`, `osmesa.dll`, `pipe_swrast.dll`) so CPU-safe installs work on non-GPU systems.
5. Record:
   - app version
   - commit hash
   - installer file sizes
   - build date/time

## 1) Install flow validation (PC A)

Run installer and verify each wizard stage:

1. Welcome / license page opens correctly.
   - Verify the page shows proprietary AI-Pacs/AIPAX EULA text (not MIT/open-source text).
   - Verify installation requires explicit user acceptance before continuing.
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
   - installed version in selected folder
   - current installer version
   - planned install action
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
   - runtime profile captures the final graphics probe outcome on first launch
6. Basic smoke flow works:
   - open a patient/study
   - load images
   - close app cleanly

### Role-specific Settings visibility (PyInstaller and Nuitka)

In a fresh installed launch, open Settings and record the visible controls for
each role without saving credentials or starting a service merely for this QA.

For both roles, the top level must show `Server Settings`, `Viewer Configuration`,
`AI`, `Installation & Updates`, and `Consultation & Education`. The nested
`Viewer Configuration` group contains `Viewer Configuration`, `Tools Settings`,
`Image Filter`, and `Light Viewer` only when that module is installed. The
nested `AI` group contains `EchoMind` only when installed, plus `Eagle Eye` and
`Agent`. Open each leaf in a fresh frozen process to catch missing imports or
blank lazy pages. Confirm that selecting the viewer configuration still wires
its change notification, and that the Server Settings link opens `AI > Eagle
Eye` directly without constructing the EchoMind page. Do not confuse these
navigation checks with approval of any configured connection or clinical AI.

- Standard/ARM Client: Eagle Eye client connection URL/credential and paired
  client certificate/private-key file controls are visible as the single AI
  connection. Legacy Breast, Bone Age,
  Segmentation and Mammography connection editors are hidden in both global
  and server-profile UI; their previously saved values are preserved, not
  deleted. PACS/Reception connections remain available. Server-local PACS
  source, resource and SCM management are hidden.
- Eagle Eye Server: Eagle Eye client connection form and outbound legacy AI
  service editors are hidden. Local PACS source, resource reservations and
  independent service management labels/panels are visible. The listener panel
  exposes IPv4 bind address, request/result port, TLS certificate and private
  key paths, clearly marked as applying after a controlled service restart.
  The installed edition, not a test-only environment flag, must select the
  Server role. Existing saved hidden endpoints and PACS/Reception settings
  remain intact.
- Repeat for both frozen backends. Missing Settings modules, the wrong role,
  duplicate listener startup or a modal import failure is a failed installed
  GUI gate. Source tests and the Razi source copy do not replace
  this fresh-launch frozen check.

On an authorized isolated Server QA host, check that invalid bind IP/port,
network bind without TLS, missing or mismatched cert/key files, and a stale
settings revision are rejected without changing the running listener. With a
valid certificate whose SANs cover the client-facing address and loopback,
verify a service-managed HTTPS desktop connects to the independent SCM service
without hosting a second listener. An authenticated synthetic request and
result retrieval must use the same configured port; the Standard client must
reach that HTTPS address with its paired client certificate/key and owner token,
verifying the Server CA and address SAN. The Server must require trusted client
certificates and an exact certificate SHA-256 pin for each token owner. Test a
successful synthetic request/result plus rejection of a missing client
certificate, a trusted certificate with another owner's pin, an incorrect
token, an untrusted Server, and a wrong-host Server certificate. Check missing
or malformed paired key-file input and document cert renewal/revocation without
recording secrets. This installation pairing is not commercial-license
attestation. The successful source cutover and source tests are not frozen
acceptance. Use an isolated QA host; do not disturb the live Razi 8002 service.

Check the local PACS and Reception presets separately: they retain a user-entered
port; an empty local Reception port resolves to the product default 8080.
Reception HTTP, DICOM, patient/download socket and Eagle Eye request/result
ports remain distinct. The Razi full-source SCM and paired Standard Client now
use TLS port 8002, while Reception remains on local 8080. The control PC's
public-address check originated from that same PC, not an independent outside
network. Frozen Server/Client installers, fresh GUI/PACS account acceptance,
and full clinical inference remain pending.

### Frozen native-graphics child route (both backends and roles)

The QA operator, not the build automation, runs the installed windowed
`AIPacs.exe` once with `--aipacs-native-graphics-probe` and a fresh private
`AIPACS_GRAPHICS_PROBE_RECEIPT` JSON path outside patient storage. It must
exit promptly, create a small `{"supported": true}` or
`{"supported": false}` receipt, and never
open the normal workstation UI. Do not rely on stdout from a windowed build.
The probe uses synthetic pixels; do not copy clinical images into this test.

- On a known supported graphics host, record `supported: true`, then verify
  normal viewer launch and affected-series GUI input/output.
- On a host where native Win32 VTK admission fails, record `supported: false`
  (or the isolated child fault) and verify the parent remains usable in
  VTK-free Fast mode; stale MPR preflight PASS must not re-enable native VTK.
- Repeat for PyInstaller and Nuitka, for Standard/ARM and any Server candidate
  actually built. A missing child module, timeout, crash in the parent, absent
  receipt, or fallback to VTK despite failed admission is a failed QA gate.
- Successful child admission is not a substitute for live patient-list,
  drag/drop, rendered-image, and Server model acceptance. On 2026-09-23 Razi,
  an initial source GUI attempt failed; a later normal-source patient-open and
  actual-image-display workflow passed. That scoped pass does not qualify the
  frozen installers, Advanced/MPR, AI, or the outstanding UI stall and
  download-progress warnings.

Also verify inside `installation_profile.json`:

- `app_version` matches the installer version
- `installer.current_version` matches the installer version
- `installer.detected_existing_version` matches what setup found in the target folder
- `installer.install_action` is correct for fresh install, update, reinstall, or downgrade
- `installer.should_update` is `true` only when an older installed version was detected
- selected optional modules are marked `selected_for_install`
- non-selected optional modules are marked `not_installed`
- `graphics.user_declared_gpu` matches the setup checkbox choice

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
