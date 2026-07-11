"""Guard tests — Nuitka builder ARM64/WoA parity (user directive 2026-07-08).

BOTH build pipelines (PyInstaller `build_release.py` AND Nuitka
`builder nuitka/build_nuitka_release.py`) must work on ARM64 + x64, and the
installer must auto-detect the machine. This pins the Nuitka side matches the
PyInstaller side: `--arch` + cross-build guard + `--with-woa-installer`, and
the Nuitka .iss arch conditionals + runtime install_package auto-detect + WoA
variant. Source-pin only (the actual build needs ISCC / an ARM64 box).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NUITKA_DIR = ROOT / "builder nuitka"
BUILD = NUITKA_DIR / "build_nuitka_release.py"
ISS = NUITKA_DIR / "installer" / "AIPacs_Nuitka_Setup.iss"
ISS_ARM64 = NUITKA_DIR / "installer" / "AIPacs_Nuitka_Setup_arm64.iss"
ISS_WOA = NUITKA_DIR / "installer" / "AIPacs_Nuitka_Setup_woa.iss"


def test_build_script_has_arch_and_woa_flags():
    src = BUILD.read_text(encoding="utf-8", errors="replace")
    assert '"--arch"' in src
    assert '"--with-woa-installer"' in src
    assert "def validate_nuitka_build_arch(" in src
    assert "cannot cross-build" in src
    assert "validate_nuitka_build_arch(getattr(args" in src
    # stage 10 wires arch + WoA
    assert "AIPacs_Nuitka_Setup_arm64.iss" in src
    assert "_compile_nuitka_woa_installer(" in src
    assert "ai-pacs-nuitka-installer arm64" in src


def test_woa_helper_is_best_effort():
    src = BUILD.read_text(encoding="utf-8", errors="replace")
    helper = src[src.index("def _compile_nuitka_woa_installer"): src.index("def stage_10_inno_setup")]
    assert "AIPacs_Nuitka_Setup_woa.iss" in helper
    assert "arm64-emulated" in helper
    assert "primary x64 artifact unaffected" in helper  # never sink the main build


def test_nuitka_iss_arch_conditionals():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    assert "#ifdef ARM64_BUILD" in src
    assert "ArchitecturesAllowed=arm64" in src
    assert "ArchitecturesInstallIn64BitMode=arm64" in src
    assert "#elif defined WOA_EMULATED_BUILD" in src
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in src


def test_nuitka_iss_runtime_install_package_auto_detect():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    assert "function ResolvedInstallPackageKind(): String;" in src
    assert '"install_package": "' in src
    assert "ResolvedInstallPackageKind()" in src[src.index("WriteInstallationProfile"):]
    resolver = src[src.index("function ResolvedInstallPackageKind"): src.index("function OptionalModuleStatusValue")]
    assert "IsArm64" in resolver
    assert "'x64_on_arm64'" in resolver


def test_nuitka_iss_install_package_defines():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    assert '#define InstallPackageKind "x64"' in src
    assert '#define InstallPackageKind "x64_on_arm64"' in src
    assert '#define InstallPackageKind "arm64"' in src


def test_nuitka_iss_woa_and_x64_warnings():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    assert "#ifdef WOA_EMULATED_BUILD" in src
    assert "#elif !defined ARM64_BUILD" in src
    assert "IsArm64" in src
    assert "SuppressibleMsgBox" in src  # silent installs keep working


def test_nuitka_wrappers_define_and_include():
    arm = ISS_ARM64.read_text(encoding="utf-8", errors="replace")
    assert "#define ARM64_BUILD 1" in arm
    assert '#include "AIPacs_Nuitka_Setup.iss"' in arm
    woa = ISS_WOA.read_text(encoding="utf-8", errors="replace")
    assert "#define WOA_EMULATED_BUILD 1" in woa
    assert '#include "AIPacs_Nuitka_Setup.iss"' in woa
