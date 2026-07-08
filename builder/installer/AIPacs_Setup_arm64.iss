; AIPacs — Windows ARM64 (native) installer variant.
; ARM64 plan §4/§5 (docs/plans/architecture/ARM64_WINDOWS_PLATFORM_PLAN_2026-07-07.md).
;
; Thin single-source wrapper: defines ARM64_BUILD and includes the canonical
; script. Every arch-specific piece in AIPacs_Setup.iss is conditional on this
; symbol (ArchitecturesAllowed=arm64, ArchitecturesInstallIn64BitMode=arm64,
; " (ARM64)" uninstall-name suffix, and the x64-on-ARM warning is compiled out).
;
; Compile via:  python builder/build_release.py --arch arm64
; (must run on an ARM64 builder with the .venv-arm64 environment — PyInstaller
; cannot cross-build; see tools/build/setup_arm64_env.ps1)
#define ARM64_BUILD 1
#include "AIPacs_Setup.iss"
