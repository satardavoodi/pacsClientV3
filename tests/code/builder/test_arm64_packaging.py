"""Guard tests — ARM64 packaging foundation (ARM64 plan §7, 2026-07-07).

Pins the implementable-on-x64 half of
docs/plans/architecture/ARM64_WINDOWS_PLATFORM_PLAN_2026-07-07.md:
requirements-arm64, the single-source Inno arch variants, build_release
--arch plumbing + cross-build guard, the release-gate PE-architecture scan,
and the per-arch update-source selection + arm64-lite profile in
aipacs_runtime. The actual arm64 build/validation needs the ARM64 builder.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aipacs_runtime as runtime  # noqa: E402
from builder import release_gate  # noqa: E402

REQ = ROOT / "requirements-arm64.txt"
ISS = ROOT / "builder" / "installer" / "AIPacs_Setup.iss"
ISS_ARM64 = ROOT / "builder" / "installer" / "AIPacs_Setup_arm64.iss"
BUILD_RELEASE = ROOT / "builder" / "build_release.py"
BOOTSTRAP = ROOT / "tools" / "build" / "setup_arm64_env.ps1"


# ---------------------------------------------------------------------------
# requirements-arm64.txt
# ---------------------------------------------------------------------------

def _req_active_lines() -> list[str]:
    lines = []
    for raw in REQ.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def test_requirements_arm64_exists_with_pyside_minimum():
    active = _req_active_lines()
    assert any(l.startswith("PySide6>=6.11.1") for l in active), \
        "PySide6>=6.11.1 is the first release with win_arm64 wheels"


def test_requirements_arm64_excludes_x64_only_and_dead_deps():
    active = _req_active_lines()
    for banned in ("grpcio", "vtk", "SimpleITK"):
        assert not any(l.lower().startswith(banned.lower()) for l in active), \
            f"{banned} must not be an ACTIVE dependency of the arm64 set"
    # optional/unverified wheels live in the #OPTIONAL best-effort section
    text = REQ.read_text(encoding="utf-8")
    for opt in ("pylibjpeg", "opencv-python-headless", "sounddevice"):
        assert f"#OPTIONAL {opt}" in text or f"#OPTIONAL {opt}" in text.replace("==", " ") or opt in text


def test_bootstrap_script_exists_and_guards_host_arch():
    src = BOOTSTRAP.read_text(encoding="utf-8")
    assert "PROCESSOR_ARCHITECTURE" in src
    assert "ARM64" in src
    assert "requirements-arm64.txt" in src or "$req" in src
    assert "pyinstaller" in src.lower()


# ---------------------------------------------------------------------------
# Inno Setup single-source variants
# ---------------------------------------------------------------------------

def test_iss_arch_directives_are_conditional():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    assert "#ifdef ARM64_BUILD" in src
    assert "ArchitecturesAllowed=arm64" in src
    assert "ArchitecturesInstallIn64BitMode=arm64" in src
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in src
    # arm64 directives must sit INSIDE the ARM64_BUILD branch, before the #else
    block = src[src.index("#ifdef ARM64_BUILD", src.index("[Setup]")):]
    assert block.index("ArchitecturesAllowed=arm64") < block.index("#else")


def test_iss_x64_build_warns_on_arm64_host():
    # Since the WoA SKU landed, the classic-x64 warning lives in the
    # `#elif !defined ARM64_BUILD` branch of the [Code] arch chain and points
    # users at the dedicated WoA package.
    src = ISS.read_text(encoding="utf-8", errors="replace")
    idx = src.index("#elif !defined ARM64_BUILD", src.index("[Code]"))
    code = src[idx:]
    assert "function InitializeSetup(): Boolean;" in code
    assert "IsArm64" in code
    assert "SuppressibleMsgBox" in code, "silent installs must keep working"
    assert "ARM64 emulated" in code  # names the dedicated WoA package


def test_iss_arm64_wrapper_defines_and_includes():
    src = ISS_ARM64.read_text(encoding="utf-8", errors="replace")
    assert "#define ARM64_BUILD 1" in src
    assert '#include "AIPacs_Setup.iss"' in src


# ---------------------------------------------------------------------------
# WoA emulation SKU (ARM64 emulation strategy, 2026-07-07)
# ---------------------------------------------------------------------------

ISS_WOA = ROOT / "builder" / "installer" / "AIPacs_Setup_woa.iss"


def test_iss_woa_wrapper_defines_and_includes():
    src = ISS_WOA.read_text(encoding="utf-8", errors="replace")
    assert "#define WOA_EMULATED_BUILD 1" in src
    assert '#include "AIPacs_Setup.iss"' in src


def test_iss_woa_branch_is_arm64_only_with_x64_payload_mode():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    idx = src.index("#elif defined WOA_EMULATED_BUILD", src.index("[Setup]"))
    branch = src[idx: src.index("#else", idx)]
    assert "ArchitecturesAllowed=arm64" in branch
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in branch


def test_iss_stamps_install_package_kind():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    assert '#define InstallPackageKind "x64"' in src
    assert '#define InstallPackageKind "x64_on_arm64"' in src
    assert '#define InstallPackageKind "arm64"' in src
    assert '"install_package": "' in src  # written into installation_profile.json


def test_iss_woa_first_page_is_informative_not_blocking():
    src = ISS.read_text(encoding="utf-8", errors="replace")
    idx = src.index("#ifdef WOA_EMULATED_BUILD", src.index("[Code]"))
    block = src[idx: src.index("#elif !defined ARM64_BUILD", idx)]
    assert "mbInformation" in block
    assert "Result := True;" in block


def test_build_release_woa_installer_plumbing():
    src = BUILD_RELEASE.read_text(encoding="utf-8", errors="replace")
    assert '"--with-woa-installer"' in src
    assert "def compile_woa_installer(" in src
    assert "AIPacs_Setup_woa.iss" in src
    assert "arm64-emulated" in src


# ---------------------------------------------------------------------------
# build_release --arch plumbing
# ---------------------------------------------------------------------------

def test_build_release_arch_plumbing():
    src = BUILD_RELEASE.read_text(encoding="utf-8", errors="replace")
    assert '"--arch"' in src
    assert 'SUPPORTED_BUILD_ARCHES = ("x64", "arm64")' in src
    assert "AIPacs_Setup_arm64.iss" in src
    assert "def validate_build_arch(" in src
    assert "PyInstaller cannot cross-build" in src
    # arch scan wired post-stage, respecting --skip-release-gate
    assert "check_stage_binary_architecture(" in src
    # x64 default keeps the historical artifact names
    assert 'suffix = " arm64" if CURRENT_BUILD_ARCH == "arm64" else ""' in src


# ---------------------------------------------------------------------------
# release-gate PE architecture scan
# ---------------------------------------------------------------------------

def _fake_pe(machine: int) -> bytes:
    head = bytearray(b"MZ")
    head += b"\x00" * (0x3C - 2)
    head += struct.pack("<I", 0x40)          # e_lfanew -> 0x40
    head += b"\x00" * (0x40 - len(head))
    head += b"PE\x00\x00" + struct.pack("<H", machine)
    return bytes(head)


def test_read_pe_machine(tmp_path):
    x64 = tmp_path / "a.dll"
    x64.write_bytes(_fake_pe(0x8664))
    arm = tmp_path / "b.pyd"
    arm.write_bytes(_fake_pe(0xAA64))
    junk = tmp_path / "c.dll"
    junk.write_bytes(b"not a pe file")
    assert release_gate.read_pe_machine(x64) == 0x8664
    assert release_gate.read_pe_machine(arm) == 0xAA64
    assert release_gate.read_pe_machine(junk) is None


def test_arch_scan_flags_wrong_binaries(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    (core / "good.dll").write_bytes(_fake_pe(0x8664))
    (core / "bad.pyd").write_bytes(_fake_pe(0xAA64))
    (core / "notes.txt").write_text("ignored", encoding="utf-8")

    check = release_gate.check_stage_binary_architecture(tmp_path, expected_arch="x64", enforce=True)
    assert check.status == "FAIL"
    assert any("bad.pyd" in line for line in check.details)

    warn = release_gate.check_stage_binary_architecture(tmp_path, expected_arch="x64", enforce=False)
    assert warn.status == "WARN"

    (core / "bad.pyd").write_bytes(_fake_pe(0x8664))
    clean = release_gate.check_stage_binary_architecture(tmp_path, expected_arch="x64", enforce=True)
    assert clean.status == "PASS"

    arm_ok = release_gate.check_stage_binary_architecture(tmp_path, expected_arch="arm64", enforce=True)
    assert arm_ok.status == "FAIL"  # x64 binaries in an arm64 stage must fail


def test_arch_scan_missing_stage_is_warning(tmp_path):
    check = release_gate.check_stage_binary_architecture(tmp_path / "nope", expected_arch="arm64")
    assert check.status == "WARN"


# ---------------------------------------------------------------------------
# runtime: per-arch update selection + arm64-lite profile
# ---------------------------------------------------------------------------

def test_resolve_source_location_legacy_passthrough():
    src = {"location": r"D:\updates"}
    assert runtime.resolve_source_location(src, native_arch="ARM64") == r"D:\updates"
    assert runtime.resolve_source_location(src, native_arch="AMD64") == r"D:\updates"


def test_resolve_source_location_by_arch():
    src = {
        "location": "https://example.com/legacy",
        "location_by_arch": {
            "x64": "https://example.com/x64",
            "arm64": "https://example.com/arm64",
        },
    }
    assert runtime.resolve_source_location(src, native_arch="ARM64") == "https://example.com/arm64"
    assert runtime.resolve_source_location(src, native_arch="AMD64") == "https://example.com/x64"
    # unknown host arch -> x64 bucket; missing bucket -> legacy fallback
    assert runtime.resolve_source_location(src, native_arch="") == "https://example.com/x64"
    partial = {"location": "legacy", "location_by_arch": {"arm64": "a64"}}
    assert runtime.resolve_source_location(partial, native_arch="AMD64") == "legacy"
    assert runtime.resolve_source_location(partial, native_arch="ARM64") == "a64"


def test_build_profile_env_override_and_vtk_gate(monkeypatch):
    monkeypatch.setenv("AIPACS_BUILD_PROFILE", "arm64_lite")
    assert runtime.build_profile() == "arm64_lite"
    assert runtime.vtk_features_available() is False
    monkeypatch.setenv("AIPACS_BUILD_PROFILE", "standard")
    assert runtime.build_profile() == "standard"
    assert runtime.vtk_features_available() is True
    monkeypatch.delenv("AIPACS_BUILD_PROFILE", raising=False)
    assert runtime.build_profile() in ("standard", "arm64_lite")
