"""Guard tests — OPT-21 Phase-2 runtime architecture / WoA emulation banner.

PC2 is a Snapdragon X Elite (Windows 11 ARM64) running our x64 frozen build
under Prism emulation — previously invisible in logs. main.py must log one
[RUNTIME_ARCH] line right after logging is configured.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PacsClient.utils import runtime_arch_log as ral  # noqa: E402


def test_get_runtime_architecture_shape_and_consistency():
    info = ral.get_runtime_architecture()
    for key in ("python", "frozen", "executable", "process_arch", "native_arch", "emulated"):
        assert key in info
    assert isinstance(info["process_arch"], str) and info["process_arch"]
    assert info["emulated"] in (True, False, None)
    # Consistency rule: same native/process arch can never be flagged emulated.
    if info["native_arch"] and info["native_arch"] == info["process_arch"]:
        assert info["emulated"] is False


def test_emulation_rule_arm64_host_x64_process(monkeypatch):
    monkeypatch.setattr(ral, "_native_machine_via_iswow64process2", lambda: "ARM64")
    monkeypatch.setattr(ral.platform, "machine", lambda: "AMD64")
    info = ral.get_runtime_architecture()
    assert info["native_arch"] == "ARM64"
    assert info["emulated"] is True


def test_log_runtime_architecture_never_raises():
    info = ral.log_runtime_architecture()
    assert isinstance(info, dict)


def test_mainpy_logs_arch_after_logging_configured():
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    assert "log_runtime_architecture" in src
    assert src.index("configure_diagnostic_logging(process_role=") < src.index("log_runtime_architecture")
