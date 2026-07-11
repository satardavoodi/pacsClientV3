# Windows-on-ARM (Snapdragon X Elite) — MPR native crash + slow startup investigation

> **RESOLVED 2026-07-08 — root cause found by the shipped faulthandler, and it was NOT the
> OpenGLOn12 access-violation hypothesis.** Decisive evidence from `native_fault.log` +
> `[HW_CHECK]` on the live Snapdragon machine:
> - `[HW_CHECK] overall=ok opengl_ok=True detail=OpenGL 3.3 renderer=Gallium 0.4 on llvmpipe` —
>   the app was using the **bundled SOFTWARE renderer (Mesa llvmpipe / `opengl32sw.dll`)**, NOT
>   the hardware `D3D12 (Adreno) / 4.6` path GLview saw. The install defaulted to `cpu_safe`
>   (software OpenGL).
> - `Windows fatal exception: code 0xc000001d` (**EXCEPTION_ILLEGAL_INSTRUCTION**, not the
>   `0xc0000005` access-violation I predicted) with `Current thread … _mpr_views.py:498 in
>   _create_axial_view` = `vtk_widget.Initialize()` — the first real use of the GL context.
> - **Mechanism:** llvmpipe is an x64 binary whose LLVM JIT emits a SIMD instruction that Prism's
>   x64→ARM64 emulator cannot execute → illegal instruction → instant death, no traceback. The
>   Qt pre-flight probe PASSED (it used the same software GL and returned 3.3 without hitting that
>   specific instruction) — exactly the "probe passes while VTK crashes deeper" caveat.
> - **The safe/dangerous choice is INVERTED on Windows-on-ARM:** software rendering (the safe
>   default on a normal PC) crashes under emulation; the hardware D3D12/Adreno path works.
> **FIX SHIPPED (default-on):** on an emulated WoA host the software graphics profile now uses the
> **system/desktop hardware OpenGL** (D3D12→Adreno) instead of forcing bundled llvmpipe
> (`aipacs_runtime.build_windows_graphics_environment` WoA branch; `QT_OPENGL=desktop`,
> `VTK_USE_HARDWARE=1`, no Mesa DLLs on PATH; escape hatch `AIPACS_WOA_FORCE_SOFTWARE_GL=1`).
> Emulation detection hardened (`is_windows_on_arm_emulated`, IsWow64Process2 came back blank on
> this box → env/CPU-identifier fallback). The `[MPR-STEP]` bisector confirmed the crash window
> (last line `render_window_add_renderer end`, next native call = the crash). This does NOT rule
> out the separate OpenGLOn12 pack regression on OTHER machines — but on THIS machine the pack
> path is the WORKING one and llvmpipe was the crash. Guards: `test_woa_graphics.py` (9),
> updated `test_runtime_arch_log.py`. NEEDS live re-test on the Snapdragon box.

**Date:** 2026-07-07 · **Machine:** PC2 "baba" = ASUS Vivobook S, Snapdragon X Elite X1E78100,
Adreno X1-85 (driver 31.0.137.0), Windows 11 Home ARM64, 2880×1620@120 Hz.
**Master plan item:** OPT-21 (extends the same-day PC2 crash work).
**Status:** evidence-driven analysis + instrumentation shipped; decisive machine-side evidence
(faulting module) pending one run of `tools/diagnostics/collect_pc_crash_evidence.ps1` on PC2.

**Reframe:** the earlier "driver cannot provide OpenGL 3.2" hypothesis is WITHDRAWN. GLview on this
machine proves OpenGL 3.0–4.5 render tests pass at high FPS on
`D3D12 (Qualcomm Adreno X1-85 GPU)` / `OpenGL 4.6 Core, Mesa` — the crash is an
application-stack interaction, not missing capability or weak hardware.

---

## 1. Existing architecture (what actually runs on PC2)

Our app is **Python (CPython x64) + PySide6/Qt + VTK 9 (`vtkmodules`) + numpy, frozen with
PyInstaller 3.4.6-era build** (log provenance: `frozen=True loader=PyiFrozenImporter`,
`D:\AIPacs\engine\...pyc`) — *not* WPF/.NET (Phase templates mentioning WPF/C# map to
PySide6/QVTKRenderWindowInteractor here). There is no ARM64 build; the installed exe is x64.
On PC2 the real stack is therefore:

```
AI-PACS (x64 frozen)  →  Prism x64→ARM64 emulation (whole process: Python, Qt, VTK, numpy)
    VTK OpenGL (vtkWin32OpenGLRenderWindow / WGL)
        →  Microsoft OpenCL/OpenGL Compatibility Pack (Microsoft.D3DMappingLayers)
           = Mesa GLon12 (`OpenGLOn12.dll`, x64 variant inside the emulated process)
        →  Direct3D 12  →  Qualcomm Adreno X1-85 driver  →  GPU
```

Two architectural facts follow: (a) every instruction of the app, including VTK and the x64
`OpenGLOn12.dll`, is JIT-translated by Prism; (b) the FAST 2D viewer is deliberately VTK-free
(Qt raster, no GL), so **the first OpenGL touch of the entire process is the Standard-MPR click** —
matching "everything works until MPR".

## 2. Startup timeline (session 2026-07-07 14:47, from PC2 logs)

| t (mm:ss.ms) | Δ | Stage (log evidence) |
|---|---|---|
| 47:12.72 | 0 | first log line (`configure_diagnostic_logging`); PyInstaller unpack + Prism first-translation happen BEFORE this and are unmeasured |
| 47:12.75→13.28 | 0.5 s | probes/CPU budget; `SetPriorityClass failed (err=6)` (benign, emulation quirk) |
| 47:13.35 | — | single-instance lock |
| 47:13.71→22.82 | **9.1 s** | login/UI construction; stall traces: `app_handler.__init__` 436 ms, `main.notify` gap 2061 ms; CPU 92–99% the whole window |
| 47:22.82→25.60 | 2.8 s | socket login (server round-trip 1256 ms — network/server, not this machine) |
| 47:25.95→26.76 | — | `[STARTUP_STAGE] db_init_migrate 33.8ms · setup_ui 165ms · setupUi_pre_home 565ms` |
| 47:27.9→29.5 | 1.6 s | main window, columns, EchoMind adapters (77 actions); CPU 97–99.9% |
| 47:34.99 | — | DM warm 412 ms; 47:38.97 first patient search |
| Total | **~15 s log-visible** (+ unmeasured pre-log) | vs. seconds on x64 dev hardware |

>1 s stages: the 9.1 s UI-construction window (dominant), login network wait, `main.notify` 2.06 s
stall, session `max_gap_ms=4001`. **Signature:** CPU pinned ~100% through every construction stage
with modest I/O — the classic Prism JIT-translation tax on a fast CPU, not disk/RAM starvation.
38 main-thread stalls in 48 s during use. (Whether this 3.4.6 build predates the OPT-01/OPT-12
startup fixes of 07-04/05 should be checked; those reduce the same stages on all machines.)

## 3. MPR timeline (14:48:01.711 → death at 14:48:02.639)

| t | Step | Evidence |
|---|---|---|
| 01.711 | `toggle_zeta_mpr` enter | app.log banner |
| 01.743→02.195 | 144-file volume load (async off-thread) | `[MPR VTK LOAD] ✓ dims=(208,256,144)` — **452 ms, healthy**: decode/compute speed is fine on this machine |
| 02.409 | `canonicalize_volume` RESULT (sagittal→ZetaAnatA) | zeta_mpr_canon_probe.log |
| 02.630 | `MPRMeasurementTools` init | app.log |
| 02.635 | `Calling _setup_ui()` | viewer_diagnostics.log |
| 02.6387 | `create_view view_name=axial` | viewer_diagnostics.log |
| **02.6389** | **geometry-contract warn (`_mpr_views.py:383`) = LAST LINE in every log** | process terminates |

## 4. Exact last successful operation

`_emit_geometry_contract_missing_guard(feature="zeta_mpr_create_axial_view")` — i.e. the line
immediately before `QVTKRenderWindowInteractor(container)`. Death occurs inside the window of
`_create_axial_view` lines ~390–424: QVTK ctor → `GetRenderWindow().AddRenderer` →
`vtk_widget.Initialize()/Start()` = **first Win32 OpenGL context creation / first GL use**. No
Python traceback anywhere; deferred-3D/VRT never reached; threading is clean (everything on GUI
thread tid 13104 — Phase 6: creation, first render, and interactor init are same-thread by design
in `toggle_zeta_mpr`; the only off-thread step is the file load, which completed).

## 5. OpenGL vendor/renderer/version seen INSIDE the app

**Unknown for the crash session — the process died creating its first context, and the app had no
GL logging.** GLview's result (Microsoft / D3D12 Adreno X1-85 / 4.6 Mesa) is the *external*
answer; per this investigation the internal answer is now captured two ways (shipped today):
`[MPR-GL-CAPS]` (VTK `ReportCapabilities` after the first pane initializes — the exact Phase-3
comparison) and the Settings **Hardware Requirements Check** (Qt `QOpenGLContext` probe: vendor,
renderer, version — works even if VTK would crash later). Note the subtlety: the app is x64, so it
loads the **x64** `OpenGLOn12.dll` under emulation, whereas ARM64-native GLview loads the arm64
one — the two can behave differently; only in-app logging answers the question.

## 6. Process / native-dependency architecture

- Installed exe: x64 (built by our x64 PyInstaller pipeline) → **runs under Prism emulation** on
  the ARM64 host. All native wheels (VTK, PySide6, numpy, pydicom codecs) are x64.
- Confirmation on PC2: `collect_pc_crash_evidence.ps1` §4 reads the PE header (expected `0x8664`),
  §1 reads the host arch from the registry (expected `ARM64`).
- Shipped: `[RUNTIME_ARCH]` startup banner (`PacsClient/utils/runtime_arch_log.py`, wired in
  `main.py` after logging config; `IsWow64Process2` nativeMachine + `platform.machine()`), and a
  "Process architecture" row in the Settings hardware check (flags
  "x64 build running under Windows-on-ARM emulation (Prism)…" as a warning).

## 7. Windows crash information

Not yet captured (the log folder contained only app logs; the production build had no
faulthandler until today's OPT-21 work). Two collectors now exist:
- **On the CURRENT installed build (no redeploy):** run
  `tools/diagnostics/collect_pc_crash_evidence.ps1` on PC2 → Event Viewer `Application Error`
  records (Faulting module name + exception code), WER reports, D3DMappingLayers version, GPU
  driver, exe PE arch; `-EnableDumps` registers WER LocalDumps for a full `.dmp` on the next
  repro. **Prediction to falsify:** faulting module `OpenGLOn12.dll` (or the Qualcomm/D3D12 DLL),
  exception `0xc0000005`.
- **Next build:** faulthandler → `native_fault.log` (all-thread Python stacks at the fault) +
  `[MPR-STEP]` bisector naming the exact native call.

## 8. Root-cause candidates, ranked by evidence

**Crash (independent of startup):**
1. **Mesa GLon12 / `OpenGLOn12.dll` bug in the Microsoft compatibility pack (D3DMappingLayers) —
   STRONG external corroboration.** microsoft/OpenCLOn12#68 documents systematic
   `EXCEPTION_ACCESS_VIOLATION` in `OpenGLOn12.dll` on ARM64 (incl. **Surface Pro 11 / Snapdragon
   X Elite**, package 1.2505–1.2510; regression vs v1.2403.9.0) killing Blender/Godot/xlights at
   GL init / extension discovery / first texture ops — apps die silently right where ours does,
   while simple GL viewers pass. Blender on the same class of hardware is FIXED by downgrading the
   pack to v1.2403.9.0. Our crash sits exactly in first-context-creation/first-GL-use; VTK's
   OpenGL2 backend does aggressive extension discovery there. Same class as Godot's
   "OpenGLOn12 regression" (godotengine/godot#106853).
2. **Qualcomm Adreno X1 driver 31.0.137.0 defect** (the D3D12 half of the same path). Blender
   #142859 reports Vulkan breakage on Adreno 31.0.112.0+; the GLon12 path terminates in this
   driver. Distinguished from (1) by the faulting module name / pack downgrade test.
3. **x64-emulation interaction:** our GL path runs the *x64* `OpenGLOn12.dll` under Prism (GLview
   likely tested the arm64 one), so an emulation-specific corruption is possible — but (1)
   reproduces on ARM64-native apps, so emulation is more likely an amplifier than the cause.
4. Threading / VTK object lifetime / invalid buffer: **no supporting evidence** — single-threaded
   construction, volume built and validated (dims/spacing logged), crash before any pixel upload.
5. Weak hardware / missing OpenGL: **excluded** by GLview + the 452 ms volume load.

**Slow startup (separate causes, Phase 7):**
1. **Prism x64 JIT translation of a very large frozen app** (Python + Qt + VTK + numpy DLLs) —
   CPU pinned ~100% through construction; first launches worst until the per-module translation
   cache (XtaCache) warms; AVX-heavy numpy paths are translated expensively.
2. Known cross-machine startup stages (OPT-01/OPT-12 fixed 07-04/05) — verify this build includes
   them; on PC2 every such stage is multiplied by emulation.
3. Login server round-trip (~1.3 s) — environmental, not the machine.

## 9. Next smallest distinguishing experiments (in order)

1. **(5 min, current build, read-only)** Run `collect_pc_crash_evidence.ps1` on PC2 → the
   **Faulting module name** separates candidate 1 (OpenGLOn12.dll) from 2 (Qualcomm/D3D12 DLL)
   from "something else"; also captures the pack version + driver version + exe arch in one zip.
2. **(10 min, reversible, no app change)** If OpenGLOn12: swap the compatibility-pack version —
   try the newest Store version; if unchanged, the documented known-good
   `v1.2403.9.0` (`Get-AppxPackage Microsoft.D3DMappingLayers | Remove-AppxPackage;
   Add-AppxPackage Universal_D3DMappingLayers_1.2403.9.0_arm64.appx`) → click MPR. Fix ⇒ pack
   regression confirmed (report to Microsoft; pin version on WoA machines). No fix ⇒ driver/other.
3. **(5 min)** Update the Adreno driver (31.0.137.0 is old for X1-85) → retry MPR. Distinguishes
   candidate 2.
4. **(next build)** `[MPR-STEP]` + `[MPR-GL-CAPS]` + `native_fault.log` + `[RUNTIME_ARCH]` land —
   the step trace names the exact native call; GL-CAPS answers Phase 3 definitively.

**Deliberately NOT done (per the brief):** no GPU-disable, no software-rendering fallback, no VTK
feature removal, no quality downgrade — mitigations wait for the faulting-module evidence. If the
platform bug is confirmed and unfixable machine-side, the sanctioned mitigations to evaluate are,
in order: pack version pin on WoA installs → ship-Mesa-softpipe *option* for MPR on such machines
→ a native ARM64 build (long-term; PySide6/VTK ARM64 wheels exist).

## Shipped in this investigation (all default-on, flag-gated, 34/34 guard tests green)

| What | Where | Flag |
|---|---|---|
| `[RUNTIME_ARCH]` startup banner + emulation detection | `PacsClient/utils/runtime_arch_log.py`, `main.py` | — (single line) |
| `[MPR-STEP]` native-call bisector around the axial pane + `[MPR-GL-CAPS]` VTK GL report | `modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py` | `AIPACS_MPR_STEP_TRACE` |
| "Process architecture" row in Hardware Requirements Check | `modules/mpr/opengl_preflight.py` (`evaluate_hardware`), settings panel | — |
| PC2 evidence collector (Event Viewer/WER/pack/driver/PE arch, `-EnableDumps`) | `tools/diagnostics/collect_pc_crash_evidence.ps1` | — |
| (earlier today) OpenGL pre-flight + persisted hardware check + faulthandler | OPT-21 | `AIPACS_MPR_OPENGL_PREFLIGHT`, `AIPACS_NATIVE_FAULT_LOG` |

Note: on THIS machine the Qt pre-flight probe may PASS (context creation works — GLview proves the
stack can create contexts) while VTK still crashes deeper in GL use; the probe guards the
missing-GL class (original PC2 hypothesis), the step trace + dumps pin this new class.

## External references

- microsoft/OpenCLOn12 #68 — "OpenGLOn12.dll systematic crashes on ARM64" (Snapdragon X Elite
  repro; v1.2403.9.0 downgrade fix): https://github.com/microsoft/OpenCLOn12/issues/68
- godotengine/godot #106853 — Windows ARM64 OpenGLOn12 regression:
  https://github.com/godotengine/godot/issues/106853
- Blender #142859 — Vulkan fails on Windows ARM with Adreno 31.0.112.0+ driver:
  https://projects.blender.org/blender/blender/issues/142859
- Microsoft — How x86/x64 emulation works on Arm (translation cache):
  https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation
