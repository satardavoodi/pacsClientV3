"""Guard tests — Nuitka builder ARM64/WoA parity (user directive 2026-07-08).

BOTH build pipelines (PyInstaller `build_release.py` AND Nuitka
`builder nuitka/build_nuitka_release.py`) must work on ARM64 + x64, and the
installer must auto-detect the machine. Both active edition pipelines now use
the canonical Inno script; ARM is deliberately x64 emulation. Native ARM is
not a claimed product of the three-edition matrix. Actual install tests need
ISCC and Windows/ARM hardware.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NUITKA_DIR = ROOT / "builder nuitka"
BUILD = NUITKA_DIR / "build_nuitka_release.py"
ISS = ROOT / "builder/installer/AIPacs_Setup.iss"
ISS_ARM64 = NUITKA_DIR / "installer" / "AIPacs_Nuitka_Setup_arm64.iss"
ISS_WOA = NUITKA_DIR / "installer" / "AIPacs_Nuitka_Setup_woa.iss"


def test_build_script_uses_shared_editions_and_x64_validation():
    src = BUILD.read_text(encoding="utf-8", errors="replace")
    assert 'validate_build_arch("x64")' in src
    assert '"--edition"' in src
    assert 'INSTALLER_SCRIPT=BUILDER_ROOT / "installer/AIPacs_Setup.iss"' in src
    assert 'INSTALLER_SCRIPT_WOA=BUILDER_ROOT / "installer/AIPacs_Setup_WoA.iss"' in src
    assert "inventory = compile_editions(" in src
    assert 'for_distribution=not getattr(ctx.args, "internal_build", False)' in src


def test_required_arm_output_is_not_best_effort():
    src = BUILD.read_text(encoding="utf-8", errors="replace")
    helper = src[src.index("def stage_10_inno_setup"): src.index("def smoke_test")]
    assert "if rc != 0:" in helper and "raise StageError" in helper
    assert "except" not in helper
    assert 'glob("*.exe")' not in helper


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
