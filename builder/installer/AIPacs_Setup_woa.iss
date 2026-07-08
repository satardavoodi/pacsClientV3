; AIPacs — Windows-on-ARM (ARM64) installer, EMULATED x64 payload.
; ARM64 emulation strategy 2026-07-07 (docs/plans/architecture/
; ARM64_WINDOWS_PLATFORM_PLAN_2026-07-07.md §4/§5 + strategy pivot):
; ship the proven x64 build to ARM64 machines KNOWINGLY — this SKU is only
; installable on ARM64 hosts (ArchitecturesAllowed=arm64), shows an
; informative (not warning) first page, titles itself " (ARM64 emulated)",
; and stamps install_package=x64_on_arm64 into installation_profile.json so
; the app applies the WoA runtime profile ([WOA-PROFILE]) and diagnostics.
;
; Thin single-source wrapper over the canonical script — the PAYLOAD is the
; SAME x64 stage the classic installer uses; only installer metadata differs.
; Compile via:  python builder/build_release.py --with-woa-installer
; (part of the normal x64 build — no ARM64 builder needed)
#define WOA_EMULATED_BUILD 1
#include "AIPacs_Setup.iss"
