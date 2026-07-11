; AIPacs (Nuitka) — Windows-on-ARM (ARM64) installer, EMULATED x64 payload.
; Parity with builder/installer/AIPacs_Setup_woa.iss (ARM64 emulation strategy
; 2026-07-08): ships the SAME x64 Nuitka build to ARM64 machines knowingly —
; ARM64-hosts-only, informative first page, stamps install_package=x64_on_arm64
; so the app applies the Windows-on-ARM runtime profile + hardware-GL fix.
; Built from the normal x64 Nuitka pipeline (no ARM64 builder needed).
#define WOA_EMULATED_BUILD 1
#include "AIPacs_Nuitka_Setup.iss"
