; AIPacs (Nuitka) — Windows ARM64 (native) installer variant.
; Parity with builder/installer/AIPacs_Setup_arm64.iss. Thin single-source
; wrapper: defines ARM64_BUILD and includes the canonical Nuitka script, whose
; arch-specific pieces (ArchitecturesAllowed=arm64, install_package=arm64,
; " (ARM64)" suffix) are all conditional on this symbol.
; Requires an ARM64 builder (Nuitka cannot cross-compile).
#define ARM64_BUILD 1
#include "AIPacs_Nuitka_Setup.iss"
