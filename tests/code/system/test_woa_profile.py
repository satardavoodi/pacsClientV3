"""Guard tests — Windows-on-ARM emulation runtime profile (strategy 2026-07-07).

Decision: ARM64 machines run the x64 build under emulation for now. The WoA
profile must (a) be a complete NO-OP on native machines, (b) apply emulation
defaults ONLY for env vars the user has not set, (c) never raise, (d) be
disabled by AIPACS_WOA_PROFILE=0, and (e) be wired into main.py BEFORE app
construction so env defaults take effect.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PacsClient.utils import woa_profile as wp  # noqa: E402


def test_decide_noop_when_native_or_unknown():
    assert wp.decide_woa_tuning(emulated=False, environ={}) == []
    assert wp.decide_woa_tuning(emulated=None, environ={}) == []


def test_decide_applies_defaults_under_emulation():
    decisions = wp.decide_woa_tuning(emulated=True, environ={})
    names = [name for (name, _v, _w) in decisions]
    assert "AIPACS_BROWSER_PREWARM" in names
    values = {name: value for (name, value, _w) in decisions}
    assert values["AIPACS_BROWSER_PREWARM"] == "0"


def test_decide_never_overrides_user_env():
    environ = {"AIPACS_BROWSER_PREWARM": "1"}  # user explicitly wants prewarm
    decisions = wp.decide_woa_tuning(emulated=True, environ=environ)
    assert all(name != "AIPACS_BROWSER_PREWARM" for (name, _v, _w) in decisions)


def test_decide_disabled_by_kill_switch():
    assert wp.decide_woa_tuning(emulated=True, environ={}, enabled=False) == []


def test_apply_never_raises_and_reports(monkeypatch):
    # Force the "native" path deterministically: patched arch reader.
    monkeypatch.setattr(
        "PacsClient.utils.runtime_arch_log.get_runtime_architecture",
        lambda: {"emulated": False, "process_arch": "AMD64", "native_arch": "AMD64"},
    )
    result = wp.apply_woa_runtime_profile()
    assert result["emulated"] is False
    assert result["applied"] == []


def test_apply_under_emulation_sets_env(monkeypatch):
    monkeypatch.setattr(
        "PacsClient.utils.runtime_arch_log.get_runtime_architecture",
        lambda: {"emulated": True, "process_arch": "AMD64", "native_arch": "ARM64"},
    )
    monkeypatch.setattr(wp, "installed_package_kind", lambda: "x64_on_arm64")
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM", raising=False)
    monkeypatch.delenv("AIPACS_WOA_PROFILE", raising=False)
    result = wp.apply_woa_runtime_profile()
    assert result["emulated"] is True
    assert result["package"] == "x64_on_arm64"
    assert "AIPACS_BROWSER_PREWARM" in result["applied"]
    import os
    assert os.environ.get("AIPACS_BROWSER_PREWARM") == "0"
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM", raising=False)


def test_mainpy_wired_before_app_construction():
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    assert "apply_woa_runtime_profile" in src
    # runs in the bootstrap flow: logging configured -> arch banner -> WoA
    # profile (env defaults must land before app/module construction).
    assert src.index("configure_diagnostic_logging(process_role=") \
        < src.index("log_runtime_architecture") \
        < src.index("apply_woa_runtime_profile")


def test_mpr_diagnostics_include_emulation_and_kpi():
    views = (ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_views.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "get_runtime_architecture" in views  # [MPR-GL-CAPS] emulated= field
    toolbar = (
        ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_toolbar" / "toolbar_manager.py"
    ).read_text(encoding="utf-8", errors="replace")
    assert "[MPR-OPEN-KPI]" in toolbar
    assert "standard_mpr_construct_ms" in toolbar
