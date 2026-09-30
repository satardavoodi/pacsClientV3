# Eagle Eye Server service packaging parity

Status: build-input assessment and fail-closed guard, 2026-09-23. No Server
installer was created by this assessment. Follow the canonical [`BUILD.md`](../../BUILD.md)
for any future build; this is not another output route.

## What the source pilot proved, and what it did not

The isolated source service on the Razi host uses Python 3.13.3 plus real
`pywin32 311` and has passed an empty-queue SCM stop/start and listener failure
recovery. See the [source-service record](../../docs/modules/eagle-eye-server-development/docs/SERVICE_AUTH.md).
That is not proof of PyInstaller or Nuitka service packaging. The canonical
build environment `.venv_build` currently has **no** `pywin32`; its immutable
`distribution-assets-native-3.6.7-vc143-20260923` cache inventories only
`pywin32-ctypes==0.2.3`, not a `pywin32` wheel. The development `.venv` does
have pywin32 311, which explains why a Developer Run can succeed while a frozen
Server service would not. `pywin32-ctypes` does not provide `servicemanager`,
`win32service`, `win32serviceutil`, `win32crypt`, `win32security`, or `pywintypes`.

The source snapshot includes `eagle_eye_remote/service_host.py`,
`service_admin.py`, `pacs_credentials.py`, `process_owner.py`, and the
`tools/eagle_eye/windows_service.py` entry point. PyInstaller's core spec
collects the `modules` tree; Nuitka's full-core lane includes
`modules.ai_imaging`. Those source paths alone are insufficient: neither
backend can freeze native extensions absent from its build interpreter.

`build_local_candidate.py` now checks **Server only** for real pywin32 311 in
the build interpreter, an inventoried x64 wheel, both exact-version and
hashed-wheel locks, and the six directly needed service/DPAPI imports. The
current cache fails this check before source snapshot or compilation. Client
preparation remains independent. This is a necessary input guard, not a claim
that a future frozen service has passed installed acceptance.

The later [paired-source cutover](../../docs/modules/eagle-eye-server-development/docs/SERVICE_AUTH.md)
placed the actual Razi SCM service on TLS port 8002 with required client
certificates and exact SHA-256 pins bound to token owners. The paired Standard
Client passed a source-only request/result path; missing client certificates,
incorrect tokens, missing Server trust, and a trusted certificate with the
wrong owner's pin were rejected. The public-address check originated from the
same control PC, not an independent outside network. The legacy Mammography
listener is stopped and port 8043 is closed. This source evidence does not
resolve the pywin32 frozen-input gap or qualify either installer backend.

## Required next dependency/cache change

### Fresh-cache dependency refresh (2026-09-28)

The canonical asset preparation tool now permits `--reuse-non-slicer-assets`
with `--download-wheels` into a new empty root. It preserves hash-verified donor
model inputs, snapshots current Slicer/VMTK, and refreshes only the current build
interpreter's lock and hashed wheels, with offline dependency graph validation.
Completed donor caches are never modified by this route. See root `BUILD.md` for
the command; this is input preparation, not a new installer entry point.

The missing-dependency diagnosis was confirmed locally. Genuine
`pywin32-311-cp313-cp313-win_amd64.whl` (SHA-256
`718a38f7e5b058e76aee1c56ddd06908116d35147e133427e59a3983f703a20d`)
was installed only in `.venv_build`; `pip check` and the six required native
imports passed. This supersedes the earlier environment observation above, not
the frozen/SCM acceptance gates. The selected old cache remains insufficient.
The new cache also must record actual decoder environment drift rather than
copying the old build lock as though it still described this interpreter.

The separately named September 28 cache
`generated-files/distribution-assets-native-vc143-vmtk-service-20260928/`
now passes independent full SHA-256 verification of 34,469 inventoried files,
the VMTK bundle check, the real pywin32 service-dependency preflight, and
byte-for-byte parity with the Developer Run native Slicer runtime. The verifier
and build-environment `pip check` exited 0. Select this cache explicitly; the
older default cache remains insufficient. This closes only the input/cache gap,
not frozen service installation, model portability, clean-host qualification,
or distribution approval.

`test_reused_asset_dependency_refresh.py` failed before the CLI correction.
It now covers donor immutability, current build pins, preserved model locks,
failed wheel validation without a completed manifest, and completed-root
overwrite refusal. The focused asset/lumen/service-preflight selection passed
16 tests, exit 0. No frozen service acceptance is asserted by these tests.

### Installed listener boundary (2026-09-28)

The code owner corrected installed desktop admission: a frozen Server desktop
requires the Eagle Eye installation profile and literal `service_managed: true`
before it can write its desktop-client configuration. It attaches to the owned
service instead of constructing another desktop listener. Bootstrap, service
administration and child dispatch now use the shared `is_frozen()` detector,
covering Nuitka as well as PyInstaller. Standard Client rejects SCM dispatch.
Fifteen behavioral cases failed before the corrections; the owner's 17-case guard
and adjacent selection passed 40 tests. The build workstream independently
reran these with cache/lumen/navigation guards: 60 passed, exit 0, three existing
SWIG deprecation warnings. This is source-test evidence, not frozen Session 0 QA.

The actual upgrade boundary is `PrepareToInstall`, which runs the previous
uninstaller before new files/profile are installed. Adding only a postinstall
SCM call would destroy the prior executable before rollback is possible. No such
shortcut was added. Retained-core upgrade/config enrollment and clean-host
acceptance remain incomplete. Operator credentials, TLS and token ownership must
not be guessed or generated as placeholders to bypass this contract.

The owner also added bounded exact-command/LocalService-owned SCM stop, start and
remove primitives. Removal waits for STOPPED, never kills unrelated processes,
and preserves configuration; SCM RUNNING is not application readiness. Fourteen
missing-API guards failed before, and 18 synthetic lifecycle cases pass after.
These primitives are not yet wired into an installer upgrade transaction. No
production SCM operation was executed.

1. Keep the existing VC143 native Slicer runtime and completed cache immutable.
   Prepare a **separately named**, complete dependency cache for the Server
   lane with the genuine `pywin32==311` Windows x64 CPython 3.13 wheel and
   exact hash in its build-environment and wheel locks. Do not overwrite the
   current all-role cache or substitute `pywin32-ctypes`.
2. Install the pinned dependency in the isolated build interpreter, not a
   global Python or clinical server runtime. Make the cache preparation path
   able to reuse hash-verified existing native Slicer/model inputs while
   collecting the new wheel and writing a fresh per-file SHA-256 manifest.
   Verify the complete cache independently before selecting it as a Server
   asset root. Client may continue to use the current shared native cache.
3. Trace the frozen PyInstaller and Nuitka Server cores independently. Verify
   `servicemanager` and every required `win32*`/`pywintypes` extension and
   supporting native DLL are actually present and importable on a clean host.
   If shared-core compilation forces server extensions into a Client binary,
   inspect size and isolation; a separate Server service entry may be needed.
4. Define an explicit Server installer/profile transaction for the absolute
   installed configuration, protected credential file, job/log storage,
   app-local Slicer executable, and LocalService ACLs. `service_config` rejects
   relative paths, but the current installer does not provision these paths or
   register the SCM service. The existing explicit Settings/service-admin path
   is source-pilot administration, not an installer lifecycle contract.
5. Make `service_managed` consistent between the installed service and desktop
   settings so desktop startup never binds a second listener. Preserve the
   edition guard: Standard/ARM must not install, start, or accept the Server
   service command.

## Promotion acceptance (both backends, Server role)

- Install on a clean Windows host, without relying on a developer Python or
  prior global pywin32 installation. Exercise the frozen Server service in
  Session 0, delayed automatic start, controlled restart, and recovery.
- Verify bounded shutdown cleans only its owned listener and descendants,
  including a loaded-work test. Preserve PACS and unrelated clinical services.
- Save a PACS account through the authorized UI; verify machine-bound protected
  credentials, LocalService ACLs, restart/401 renewal, and redacted logs.
- In fresh frozen Server Settings, verify the listener IPv4/port/certificate/key
  controls, stale-write rejection, and invalid TLS input rejection. On an
  isolated host, a service-managed HTTPS desktop must attach to the existing
  SCM listener without binding a second one; an authenticated synthetic
  request and result must use the same port. Test SAN coverage for both the
  client-facing address and loopback. The Standard Client must present its own
  paired certificate/key and token, verify the Server CA/address SAN, and be
  accepted only when the Server matches its trusted certificate's exact
  SHA-256 fingerprint to that token owner. Reject missing certificates,
  wrong-owner pins even for trusted certificates, incorrect tokens, and
  untrusted or wrong-host Servers. Test certificate renewal/revocation without
  disclosing keys or tokens. This pairing does not attest a commercial license.
  Use an isolated QA host and do not alter the live Razi 8002 listener.
- Verify the Server-local Reception/PACS presets retain entered ports and the
  blank Reception default is 8080. Keep HTTP metadata, DICOM, download socket
  and Eagle Eye listener port identities separate.
- Resolve the installed Slicer path from the actual Server payload and repeat
  no-main-window analysis startup there. The current VC143 Slicer baseline is
  shared; this test does not require recompiling Slicer.
- Verify Standard/ARM Client install and launch never provisions the service,
  cannot dispatch `--eagle-eye-windows-service`, and remain free of Server
  model payloads. Repeat for PyInstaller and Nuitka.

The source pilot's success, the input preflight, and a compiled executable are
three different gates. None alone authorizes a Server release.

## Full-workstation GUI gate: scoped source retest passed

The later Razi [full-workstation source deployment](../../docs/modules/eagle-eye-server-development/docs/FULL_WORKSTATION.md)
transferred a manifest-verified 5,525-file snapshot and installed a private
Python environment with pywin32 311. Its first signed-in session failed
patient-list acceptance: one native access violation at
`modules/viewer/advanced/viewer_2d.py:342` during `SetInputData` and a separate
sampled 6,050.9-ms Home reception-breaker gap were recorded. See the
[VTK-domain finding](../../docs/reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md)
and [UI-stall finding](../../docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md).
These observations did not establish one cause.

After the source native-graphics admission correction, the owner confirmed a
patient opened and an actual series appeared in the viewport in a fresh normal
source session. The first-image marker and responsive process corroborate this
**scoped patient-open/display PASS**; no native fatal or application error was
recorded for that session. The download log's 12 series / 111 files matched its
own authoritative total, but that is not a new on-disk or SOP audit.

Remaining findings are a 1,251.1-ms first Fast-import UI stall and Download
Manager convergence/missing-row warnings. Razi Advanced/MPR, concurrent AI,
model inference, Standard-client round trips, and frozen PyInstaller/Nuitka
installers remain unqualified. The build workstream does not modify the viewer
or shared reception pipeline. Model transfer is not inference qualification;
the scoped source PASS does not authorize a new build or release.
