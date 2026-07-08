# Windows ARM64 (win-arm64) compatibility & packaging plan — AI-PACS

> **STRATEGY PIVOT (user decision, 2026-07-07): EMULATION FIRST.** ARM64
> machines ship the proven **x64 build under Prism emulation** via a dedicated
> **WoA SKU** — native ARM64 (lite build, VTK/SimpleITK source wheels) becomes
> the LATER phase. Implemented same-day:
> `builder/installer/AIPacs_Setup_woa.iss` ("AIPacs (ARM64 emulated)":
> ArchitecturesAllowed=arm64 so it can't land on plain x64 PCs, x64 payload,
> informative first page, stamps `install_package=x64_on_arm64` into
> `installation_profile.json`; same AppId ⇒ cleanly upgrades a previous plain
> x64 install, zero impact on x64 machines) · `build_release.py
> --with-woa-installer` (compiles the WoA variant from the SAME x64 stage —
> no ARM64 builder needed; best-effort, never sinks the primary artifact) ·
> the classic x64 installer's ARM64 warning now points at the WoA package ·
> **WoA runtime profile** `PacsClient/utils/woa_profile.py` (called from
> main.py after the `[RUNTIME_ARCH]` banner): on an emulated host logs
> `[WOA-PROFILE]` (arch, installed package kind, VTK/MPR = emulated-x64 via
> OpenGLOn12, tuned vars) and applies user-overridable defaults (currently
> `AIPACS_BROWSER_PREWARM=0` — Chromium prewarm is a large JIT cost under
> emulation); kill switch `AIPACS_WOA_PROFILE=0`; native machines = no-op ·
> **diagnostics**: `[MPR-OPEN-KPI] standard_mpr_construct_ms` (toolbar) and
> `[MPR-GL-CAPS] … emulated= host=` complete the requested logging set
> (arch ✅ package ✅ native/emulated ✅ GL init ✅ GPU/renderer ✅ MPR startup
> time ✅ crash points = step trace + faulthandler ✅ slow ops = stall probe ✅).
> Guard tests: `test_arm64_packaging.py` (19) + `test_woa_profile.py` (8) —
> all green; parity suite green after mirror re-sync (which also caught that
> the OPT-22/23 files ARE plugin-mirrored — notes corrected).
> The native-ARM64 sections below (§3 VTK wheel, arm64-lite Phase 1) remain
> valid as the FUTURE phase, evaluated after the emulation path is stable.
> Validation on PC2 = plan §6 checklist run against the WoA SKU + pack/driver
> fix from the crash investigation.

**Date:** 2026-07-07 · **Trigger:** PC2 = Snapdragon X Elite running our x64 build under Prism
emulation (see `docs/reports/WOA_ARM64_MPR_CRASH_INVESTIGATION_2026-07-07.md`).
**Stack note:** AI-PACS is **Python/PySide6/VTK frozen with PyInstaller + Inno Setup** — the
".NET RID" concept from the request maps here to the **wheel platform tag `win_arm64`**, the
**CPython ARM64 runtime**, and **per-architecture PyInstaller outputs**. Same idea, different
mechanism.

---

## 1. ARM64 compatibility report (current state)

- The shipped installer is x64-only and installs on ARM64 machines via
  `ArchitecturesInstallIn64BitMode=x64compatible` (`builder/installer/AIPacs_Setup.iss:30`) —
  this is exactly how PC2 received an x64 build that runs under Prism emulation.
- Consequences measured on PC2: startup ~15 s log-visible with CPU pinned ~100% through UI
  construction (Prism JIT), 38 main-thread stalls/48 s; FAST 2D usable; MPR dies in the
  OpenGL-on-D3D12 layer (top candidate = the known `OpenGLOn12.dll` ARM64 regression,
  microsoft/OpenCLOn12#68 — note that bug hits **ARM64-native apps too** (Blender/Godot), so a
  native build does NOT automatically dodge it; pack pin / driver update still applies).
- Already shipped (OPT-21): `[RUNTIME_ARCH]` banner + emulation detection, Settings → Hardware
  Requirements Check (shows "Process architecture … under Windows-on-ARM emulation" warning),
  MPR OpenGL pre-flight, `[MPR-STEP]` bisector, faulthandler, PC2 evidence collector.
- **Nothing in our own Python code is architecture-specific** (no inline x64 assembly, no
  hand-written ctypes to x64-only DLLs found; ctypes uses kernel32 only). The porting work is
  entirely in DEPENDENCIES + BUILD/INSTALLER.

## 2. Dependency audit — x64-only vs ARM64-ready (July 2026)

**Ready (official `win_arm64` wheels / pure Python):**

| Dependency | Status |
|---|---|
| CPython | ARM64 official since 3.11 (python.org arm64 installer) |
| PySide6 | `win_arm64` wheels since **6.11.1** (2026-05) — we pin **6.10.2 → upgrade required** |
| PyInstaller | `win_arm64` supported since 5.7 (build must RUN on ARM64 Python) |
| pydicom, pynetdicom, qasync, natsort, QtAwesome, requests, python-dotenv, google-api-* / google-auth*, keyring, pypdf, python-pptx, pytesseract (binding), SpeechRecognition, comtypes, openai | pure Python — no change |
| numpy, pandas, cryptography, psutil | recent releases publish `win_arm64` wheels — **verify exact minimum versions on PyPI in Phase 1** (fallback: cgohlke/win_arm64-wheels) |

**x64-only today (the actual porting surface):**

| Dependency | Used by | ARM64 path |
|---|---|---|
| **vtk** (9.x) | MPR, Advanced viewer, 3D, dental/curved MPR | **No `win_arm64` wheel on PyPI** → source build (feasible, §3) |
| **SimpleITK 2.5.x** | Advanced viewer backend (`vtk_simpleitk`) | No `win_arm64` wheel → source build (heavy) or keep Advanced x64-only initially |
| opencv-python-headless | case-media video encode, pooyan filter | no official win_arm64; community wheel or make optional |
| pylibjpeg / -libjpeg / -openjpeg / -rle | compressed DICOM decode (FAST) | verify wheels; else source build — **required for the lite build** if servers send compressed |
| sounddevice / soundfile / pyaudio / webrtcvad | voice recording / EchoMind voice | verify (sounddevice bundles PortAudio); else make voice optional on ARM64 |
| grpcio | **retired transport (dead code per CLAUDE.md)** | **drop from ARM64 requirements entirely** |
| Tesseract engine (vendored x64 exe) | OCR hook | separate process → may stay x64-under-emulation, or vendor an ARM64 tesseract |

**x64-only DLLs currently bundled (Q6): all of them** — the entire frozen tree is x64 by
construction; nothing needs "removal", the ARM64 package is a separate build from ARM64 wheels.

## 3. VTK ARM64 feasibility (Q3/Q4)

- Must be **built from source**: CMake + MSVC "C++ ARM64 build tools" toolchain (VS 2022 supports
  native and cross arm64), Kitware's `VTKPythonPackage`/`vtk-sdk` recipe produces the wheel.
  Build ON (or cross-compile FOR) win-arm64; native build on an ARM64 dev box or GitHub
  `windows-11-arm` runners is the low-friction route.
- Trim to the module groups we import (`vtkmodules.all` today — Phase 2 should narrow imports):
  required verified modules = `RenderingOpenGL2`, `RenderingVolumeOpenGL2` (VRT),
  `ImagingCore/ImagingReslice` (vtkImageResliceMapper path), `InteractionStyle/Widgets`
  (distance/angle/caption widgets), `IOImage`, GUISupportQt (QVTKRenderWindowInteractor is
  Python-side, needs `RenderingUI`).
- **GL reality check:** on Adreno, ARM64-native VTK still renders through OpenGLOn12/Mesa-GLon12
  (there is no vendor desktop-GL ICD) — so Phase 2 validation MUST include the compatibility-pack
  version matrix, and an optional software-GL (Mesa llvmpipe `opengl32.dll` built for arm64,
  app-local) is the safety net for machines with a broken pack/driver.
- Effort estimate: days (toolchain + first wheel) + a regression pass with our geometry guard
  tests; the risk is not compilability (VTK supports ARM64 Windows) but validation breadth.

## 4. Installer architecture detection (Q7)

Inno Setup 6 supports it natively. Plan (snippets ready to apply in the builder repo pass):

- **arm64 installer:** `ArchitecturesAllowed=arm64` + `ArchitecturesInstallIn64BitMode=arm64`.
- **x64 installer:** keep `x64compatible` (so x64-on-ARM stays possible as fallback) **plus** an
  `[Code] InitializeSetup` check: `if IsArm64 then` show "An ARM64-native build is available —
  strongly recommended; continue with the emulated x64 build?" (Yes/No). No silent wrong-arch
  installs either direction.
- Detection beyond CPU: the installed app already probes GPU/OpenGL + arch at first run
  (Hardware Requirements Check persists `hardware_check.json`); the installer stays thin.
- The in-app **updater / download system (Q8)**: `update_sources.json` gains per-arch package
  URLs (`{"x64": …, "arm64": …}`); the updater selects by `[RUNTIME_ARCH]`'s native machine — an
  emulated x64 install on an ARM64 host may OFFER the arm64 package (migration path) but must
  never auto-cross-grade. Website download page: user-agent hint + explicit two buttons.

## 5. Packaging strategy (Q8) — separate outputs

```
release/
  AIPacs_Setup_<ver>_x64.exe     (today's pipeline, unchanged)
  AIPacs_Setup_<ver>_arm64.exe   (new)
```

- `build_release.py --arch {x64,arm64}`: selects the Python env (x64 venv vs ARM64 venv on the
  ARM64 builder), `requirements-arm64.txt`, PyInstaller run, and the Inno variant; release-gate
  parity checks run per-arch (frozen-PYZ probe, module catalog, installer components).
- **Phase 1 SKU = "ARM64 lite" (recommended first ship):** native ARM64 build with the FAST
  domain only — our three-domain separation makes this uniquely cheap: the FAST viewer is
  **VTK-free by architecture**, so a lite build needs only PySide6 6.11.1 + numpy + pydicom(+
  codecs). VTK-dependent modules (MPR, Advanced, dental/curved MPR, 3D) are disabled via the
  existing `MODULE_CATALOG` gating with a clear "available in the x64 build / coming to ARM64"
  message. This kills the emulation tax for the 90% workflow (open/scroll/WL/thumbnails) now.
- **Phase 2:** + VTK arm64 wheel → MPR/3D native. **Phase 3:** + SimpleITK → Advanced parity
  (until then Advanced stays hidden on ARM64 or the user keeps the x64-emulated SKU).

## 6. Performance review & validation checklist (Q5/Q9/Q10)

**Emulation verdict (Q9):** acceptable as an *interim* for 2D reading (PC2 evidence: usable but
~15 s startup, stall-prone); **not acceptable long-term** for a clinical workstation and adds a
whole extra failure layer (Prism + x64 GLon12). Native lite build is the fix, not tuning.

**ARM64-specific optimizations (Q10):** ship native (removes JIT tax — biggest single win);
verify numpy uses NEON kernels (official wheels do); re-benchmark decode (pylibjpeg arm64) and
consider libjpeg-turbo NEON; keep FAST render clock/caches unchanged (they're arch-neutral);
re-tune `_BATCH_BYTES_SOFT_CAP`/decode worker count only if benchmarks say so.

**Validation on a real ARM64 machine (PC2 is the reference box):**

1. Install (arch detection correct; no x64 DLL in the arm64 tree — release gate greps PE machine of every bundled DLL/PYD)
2. Startup < x64-native ballpark; `[RUNTIME_ARCH] emulated=False`
3. Login/patient list/patient open (multi-study + previous exams)
4. Thumbnails (sidebar + right panel), 5. drag-drop + progressive grow
6. **MPR**: `[MPR-STEP]` full ladder + `[MPR-GL-CAPS]` shows the D3D12/Adreno renderer; crosshairs/annotations/W-L
7. 3D VRT (deferred build), 8. W/L presets, 9. stack scroll ui_lag p95
10. GL init on both compatibility-pack versions (newest + v1.2403.9.0)
11. `native_fault.log` + Event Viewer clean across the session
12. KPI compare vs x64 on the same machine (startup, TTFI, decode p50, drag p95, stalls/min)

## 7. Required code / build-system changes (Q1 answer: yes, buildable — with these)

> **STATUS 2026-07-07 — foundation IMPLEMENTED on the x64 side** (guard tests
> `tests/code/builder/test_arm64_packaging.py`, 13 green; full builder/runtime/module_system
> parity suites 76 green after a pre-existing mirror-drift sync):
> ①`requirements-arm64.txt` (core verified set + `#OPTIONAL` best-effort section) ✅ ·
> ②import-hardening audit = Phase-1 task on the ARM64 machine ⏳ ·
> ③`build_release.py --arch {x64,arm64}` (cross-build guard, arch-suffixed artifacts,
> `AIPacs_Setup_arm64.iss` selection, post-stage **PE-machine scan** via
> `release_gate.check_stage_binary_architecture` — enforced for arm64, warn-only x64 until
> baseline, `AIPACS_ENFORCE_ARCH_SCAN=1` to enforce) ✅ ·
> ④arm64-lite profile foundation: `aipacs_runtime.build_profile()` /
> `vtk_features_available()` (env `AIPACS_BUILD_PROFILE` / installation-profile key;
> UI gating of VTK modules = Phase 1) ✅ ·
> ⑤per-arch updates: `resolve_source_location()` + `location_by_arch={"x64":…,"arm64":…}`
> overlay in `active_update_source()` (host-arch keyed via IsWow64Process2; legacy entries
> byte-identical) ✅ ·
> ⑥builder bootstrap `tools/build/setup_arm64_env.ps1` ✅ ·
> Inno single-source variants: conditional arch directives + " (ARM64)" suffix +
> x64-on-ARM `InitializeSetup` warning (`SuppressibleMsgBox`, silent-install safe) +
> `AIPacs_Setup_arm64.iss` wrapper ✅ — **needs one ISCC compile check of BOTH variants
> next release build**. ⑦CI on ARM64 env ⏳ (needs the builder machine).

1. `requirements-arm64.txt`: PySide6>=6.11.1, drop grpcio, pin verified arm64 versions; optional
   extras (`opencv`, voice stack) behind extras/markers.
2. Import-hardening: `opencv`, `sounddevice/soundfile/pyaudio/webrtcvad` behind existing optional
   patterns (most are already lazy — audit pass; features degrade gracefully when absent).
3. Builder: `--arch` in `build_release.py`; ARM64 Python env bootstrap script; Inno arm64 .iss
   variant + IsArm64 warning in the x64 .iss; release-gate per-arch PE-machine scan.
4. MODULE_CATALOG: mark VTK-dependent modules unavailable in the arm64-lite profile (reuses the
   purchasable-module gating — no new mechanism).
5. Updater: per-arch URLs in `update_sources.json` + native-arch selection via `runtime_arch_log`.
6. Build machine: one Windows ARM64 builder (Snapdragon dev kit / ARM64 VM / GitHub
   `windows-11-arm` runner). PyInstaller cannot cross-build — this is mandatory.
7. CI: run `tests/code` on the ARM64 env (expect green — pure Python + Qt offscreen).

## 8. Fallback strategy if ARM64-native VTK is not ready (Q8 deliverable)

Layered, in order: **(a)** ship arm64-lite (FAST-only, native) + keep the x64 SKU installable on
ARM64 for users who need MPR (emulated, with the pack/driver fix from the OPT-21 report);
**(b)** per-machine mitigation for the GLon12 crash independent of architecture: compatibility
pack version pin (v1.2403.9.0 known-good) + Adreno driver update, enforced/checked by the
Hardware Requirements Check; **(c)** optional software-GL (Mesa llvmpipe) app-local
`opengl32.dll` for MPR on machines where the GL stack stays broken — correct images, slower
render, clearly labeled; **(d)** only if all else fails: keep MPR hidden on ARM64 (module
catalog) with the "use an x64 workstation for MPR" message. No silent quality downgrades.

## Sequencing summary

| Phase | Ship | Preconditions |
|---|---|---|
| 0 (now) | x64-on-ARM supported-with-warning; PC2 pack/driver fix; installer IsArm64 warning | none (OPT-21 shipped; .iss edit next build) |
| 1 | **arm64-lite installer** (FAST native) | ARM64 builder machine; PySide6 6.11.1 bump; codec wheels verified |
| 2 | + MPR/3D (VTK arm64 source wheel) | VTK build + §6 validation incl. pack matrix |
| 3 | + Advanced viewer (SimpleITK arm64) | ITK/SimpleITK build; or explicitly keep x64-only |

## References

- PySide6 win_arm64 wheels: https://pypi.org/project/PySide6/ (6.11.1)
- VTK wheels (no win_arm64): https://pypi.org/project/vtk/ · build recipe:
  https://github.com/KitwareMedical/VTKPythonPackage · https://docs.vtk.org/en/latest/advanced/available_python_wheels.html
- SimpleITK (no win_arm64): https://pypi.org/project/SimpleITK/ · https://github.com/SimpleITK/SimpleITKPythonPackage
- PyInstaller ARM64: https://github.com/pyinstaller/pyinstaller/issues/7257 (shipped 5.7+)
- Community win_arm64 wheels: https://github.com/cgohlke/win_arm64-wheels/releases
- x86/x64 emulation on Arm (translation cache): https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation
- OpenGLOn12 ARM64 regression (affects native too): https://github.com/microsoft/OpenCLOn12/issues/68
