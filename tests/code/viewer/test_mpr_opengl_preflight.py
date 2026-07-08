"""Guard tests — OPT-21 OpenGL pre-flight + persisted hardware check (2026-07-07).

Protects the fix for the PC2 end-user crash: a machine whose display driver
cannot provide OpenGL 3.2 dies with a NATIVE access violation inside the first
QVTKRenderWindowInteractor (``_mpr_views._create_axial_view``).

Semantics pinned here (user directive 2026-07-07 — "not every time"):
- The check runs ONCE PER INSTALL: a persisted PASS in hardware_check.json is
  trusted with ZERO probing on MPR open.
- A persisted FAIL (or no file) probes now + persists — self-heals after a
  driver update.
- The full check is exposed in Settings → Viewer Configuration →
  "Hardware Requirements Check" (``hardware_check_panel.py``).
- Flag ``AIPACS_MPR_OPENGL_PREFLIGHT=0`` = legacy no-probe, no-block.

Headless: pure decisions, flag/caching/persistence logic and source pins only
(no Qt context is created here).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.mpr import opengl_preflight as ogp  # noqa: E402

TOOLBAR = (
    ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)
SETTINGS_PAGE = (
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "settings_ui" / "viewerconfigsetting.py"
)
PANEL = (
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "settings_ui" / "hardware_check_panel.py"
)


def _isolate(tmp_path, monkeypatch):
    """Point persistence at a tmp file + clear caches; returns the json path."""
    monkeypatch.delenv("AIPACS_MPR_OPENGL_PREFLIGHT", raising=False)
    path = tmp_path / "hardware_check.json"
    ogp.set_persist_path_for_tests(str(path))
    ogp.reset_cache_for_tests()
    return path


def teardown_function(_fn):
    ogp.set_persist_path_for_tests(None)
    ogp.reset_cache_for_tests()


# ---------------------------------------------------------------------------
# Pure decisions
# ---------------------------------------------------------------------------

def test_evaluate_rejects_failed_context_creation():
    ok, reason = ogp.evaluate_opengl_support(created=False, major=4, minor=6)
    assert ok is False
    assert "creation failed" in reason


def test_evaluate_rejects_old_opengl():
    ok, reason = ogp.evaluate_opengl_support(created=True, major=2, minor=1)
    assert ok is False
    assert "below the required" in reason
    assert ogp.evaluate_opengl_support(True, 3, 1)[0] is False


def test_evaluate_accepts_minimum_and_newer():
    assert ogp.evaluate_opengl_support(True, 3, 2)[0] is True
    assert ogp.evaluate_opengl_support(True, 4, 6)[0] is True


def test_evaluate_handles_garbage_version():
    ok, _ = ogp.evaluate_opengl_support(created=True, major=None, minor="x")  # type: ignore[arg-type]
    assert ok is False


def test_min_version_is_vtk9_requirement():
    assert ogp.MIN_GL_VERSION == (3, 2)


def test_evaluate_hardware_statuses():
    result = ogp.evaluate_hardware({
        "opengl": {"ok": True, "detail": "OpenGL 4.6", "renderer": "FakeGPU"},
        "cpu_cores": 8,
        "ram_bytes": 16 * 1024 ** 3,
        "disk_free_bytes": 200 * 1024 ** 3,
    })
    assert result["overall"] == "ok"
    assert {i["key"] for i in result["items"]} == {"opengl", "cpu", "ram", "disk"}
    assert all(i["status"] == "ok" for i in result["items"])
    # renderer folded into the OpenGL detail line
    gl_item = next(i for i in result["items"] if i["key"] == "opengl")
    assert "FakeGPU" in gl_item["detail"]


def test_evaluate_hardware_fail_and_warning():
    result = ogp.evaluate_hardware({
        "opengl": {"ok": False, "detail": "OpenGL 1.1 is below the required 3.2"},
        "cpu_cores": 2,
        "ram_bytes": 4 * 1024 ** 3,
        "disk_free_bytes": 20 * 1024 ** 3,
    })
    assert result["overall"] == "fail"  # opengl fail dominates
    by_key = {i["key"]: i["status"] for i in result["items"]}
    assert by_key["opengl"] == "fail"
    assert by_key["cpu"] == "warning"
    assert by_key["ram"] == "warning"
    assert by_key["disk"] == "warning"
    # unknown facts degrade to warning, never crash
    unk = ogp.evaluate_hardware({"opengl": {"ok": True, "detail": "OpenGL 3.2"}})
    assert unk["overall"] == "warning"


def test_evaluate_hardware_platform_emulation_item():
    base = {
        "opengl": {"ok": True, "detail": "OpenGL 4.6"},
        "cpu_cores": 8,
        "ram_bytes": 16 * 1024 ** 3,
        "disk_free_bytes": 200 * 1024 ** 3,
    }
    # Windows-on-ARM: x64 build under Prism -> warning + explanation
    emu = ogp.evaluate_hardware({**base, "arch": {
        "process_arch": "AMD64", "native_arch": "ARM64", "emulated": True,
    }})
    plat = next(i for i in emu["items"] if i["key"] == "platform")
    assert plat["status"] == "warning"
    assert "emulation" in plat["detail"].lower()
    assert "D3D12" in plat["detail"]
    assert emu["overall"] == "warning"
    # Native build -> ok
    nat = ogp.evaluate_hardware({**base, "arch": {
        "process_arch": "AMD64", "native_arch": "AMD64", "emulated": False,
    }})
    plat = next(i for i in nat["items"] if i["key"] == "platform")
    assert plat["status"] == "ok"
    # No arch facts -> no platform item (back-compat)
    none = ogp.evaluate_hardware(base)
    assert all(i["key"] != "platform" for i in none["items"])


def test_mpr_step_trace_wired():
    """OPT-21 Phase-3/4: the axial-pane native-boundary step trace must exist."""
    src = (
        ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_views.py"
    ).read_text(encoding="utf-8", errors="replace")
    assert 'os.getenv("AIPACS_MPR_STEP_TRACE", "1")' in src.replace("_os", "os")
    # steps bracket the crash window: qvtk ctor -> Initialize -> Start
    for step in (
        "'qvtk_interactor_ctor', 'begin'",
        "'qvtk_interactor_ctor', 'end'",
        "'interactor_initialize', 'begin'",
        "'interactor_initialize', 'end'",
        "'interactor_start', 'end'",
    ):
        assert f"_mpr_step('axial', {step})" in src, f"missing axial step {step}"
    # Phase-3: VTK-side GL capabilities logged once after the first window is live
    assert "_log_vtk_gl_capabilities(vtk_widget)" in src
    assert "[MPR-GL-CAPS]" in src
    # order: ctor trace before Initialize trace
    assert src.index("'qvtk_interactor_ctor', 'begin'") < src.index("'interactor_initialize', 'begin'")


# ---------------------------------------------------------------------------
# Flag + once-per-install persistence semantics
# ---------------------------------------------------------------------------

def test_flag_off_skips_probe_and_allows(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("AIPACS_MPR_OPENGL_PREFLIGHT", "0")

    def _boom():  # pragma: no cover - must not be called
        raise AssertionError("probe must not run when the flag is off")

    monkeypatch.setattr(ogp, "_probe_qt_opengl", _boom)
    ok, reason = ogp.opengl_preflight()
    assert ok is True
    assert reason == "preflight disabled"


def test_persisted_pass_is_trusted_with_zero_probing(tmp_path, monkeypatch):
    path = _isolate(tmp_path, monkeypatch)
    path.write_text(json.dumps({
        "schema": 1,
        "opengl": {"ok": True, "detail": "OpenGL 4.6"},
        "overall": "ok",
    }), encoding="utf-8")

    def _boom():  # pragma: no cover - must not be called
        raise AssertionError("persisted PASS must skip the probe entirely")

    monkeypatch.setattr(ogp, "_probe_qt_opengl", _boom)
    ok, reason = ogp.opengl_preflight()
    assert ok is True
    assert "OpenGL 4.6" in reason


def test_no_persisted_result_probes_once_and_persists(tmp_path, monkeypatch):
    path = _isolate(tmp_path, monkeypatch)
    calls = {"n": 0}

    def _fake_probe():
        calls["n"] += 1
        return {"ok": True, "detail": "OpenGL 4.1", "major": 4, "minor": 1,
                "renderer": "FakeGPU", "vendor": "Fake"}

    monkeypatch.setattr(ogp, "_probe_qt_opengl", _fake_probe)
    assert ogp.opengl_preflight() == (True, "OpenGL 4.1")
    assert ogp.opengl_preflight() == (True, "OpenGL 4.1")  # in-memory cache
    assert calls["n"] == 1
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["opengl"]["ok"] is True
    assert saved["schema"] == ogp.PERSIST_SCHEMA
    assert saved["overall"] in ("ok", "warning")

    # A NEW SESSION (in-memory cache cleared) trusts the persisted PASS: no probe.
    ogp.reset_cache_for_tests()

    def _boom():  # pragma: no cover
        raise AssertionError("second session must trust the persisted PASS")

    monkeypatch.setattr(ogp, "_probe_qt_opengl", _boom)
    assert ogp.opengl_preflight()[0] is True


def test_persisted_fail_reprobes_and_self_heals(tmp_path, monkeypatch):
    path = _isolate(tmp_path, monkeypatch)
    path.write_text(json.dumps({
        "schema": 1,
        "opengl": {"ok": False, "detail": "OpenGL 1.1 is below the required 3.2"},
        "overall": "fail",
    }), encoding="utf-8")

    # Driver was upgraded since the FAIL was recorded -> probe now succeeds.
    monkeypatch.setattr(ogp, "_probe_qt_opengl", lambda: {
        "ok": True, "detail": "OpenGL 4.6", "major": 4, "minor": 6,
        "renderer": "UpgradedGPU", "vendor": "Fake",
    })
    ok, reason = ogp.opengl_preflight()
    assert ok is True and "OpenGL 4.6" in reason
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["opengl"]["ok"] is True  # self-healed persisted state


def test_run_hardware_check_persists_and_refreshes_gate(tmp_path, monkeypatch):
    path = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(ogp, "_probe_qt_opengl", lambda: {
        "ok": False, "detail": "OpenGL context creation failed (no usable GPU driver)",
        "major": 0, "minor": 0, "renderer": None, "vendor": None,
    })
    result = ogp.run_hardware_check(persist=True)
    assert result["overall"] == "fail"
    assert path.is_file()
    # the MPR gate reflects the fresh check without another probe
    monkeypatch.setattr(ogp, "_probe_qt_opengl", lambda: (_ for _ in ()).throw(AssertionError))
    assert ogp.opengl_preflight()[0] is False


def test_persistence_helpers_never_raise(tmp_path):
    ogp.set_persist_path_for_tests(str(tmp_path / "no_dir" / "hw.json"))
    assert ogp.load_persisted_check() is None
    assert ogp.save_persisted_check({"schema": 1}) is True  # creates the dir
    ogp.set_persist_path_for_tests(None)


# ---------------------------------------------------------------------------
# Source pins — wiring into toggle_zeta_mpr and the Settings page
# ---------------------------------------------------------------------------

def _toggle_body() -> str:
    text = TOOLBAR.read_text(encoding="utf-8", errors="replace")
    start = text.index("def toggle_zeta_mpr")
    return text[start:]


def test_toggle_zeta_mpr_calls_preflight_before_volume_load():
    body = _toggle_body()
    idx_preflight = body.index("opengl_preflight()")
    idx_load = body.index("_load_full_vtk_for_mpr")
    idx_viewer = body.index("StandardMPRViewer(")
    assert idx_preflight < idx_load, "preflight must run before the MPR volume load"
    assert idx_preflight < idx_viewer, "preflight must run before StandardMPRViewer construction"


def test_toggle_zeta_mpr_blocked_path_resets_tool_state():
    body = _toggle_body()
    idx_preflight = body.index("opengl_preflight()")
    blocked = body[idx_preflight: idx_preflight + 1800]
    assert "QMessageBox.warning" in blocked
    assert "self.tool_selected = None" in blocked
    assert "handle_buttons_checked()" in blocked
    assert "return" in blocked
    assert "Hardware Requirements" in blocked  # dialog points at the Settings check


def test_toggle_zeta_mpr_imports_probe_module():
    assert "from modules.mpr.opengl_preflight import opengl_preflight" in _toggle_body()


def test_settings_page_hosts_hardware_check_panel():
    src = SETTINGS_PAGE.read_text(encoding="utf-8", errors="replace")
    assert "from .hardware_check_panel import HardwareCheckPanelWidget" in src
    assert "self.hardware_check_panel = HardwareCheckPanelWidget()" in src
    assert "addWidget(self.hardware_check_panel)" in src


def test_hardware_check_panel_runs_and_loads_persisted():
    src = PANEL.read_text(encoding="utf-8", errors="replace")
    assert "run_hardware_check" in src
    assert "load_persisted_check" in src
    assert "Run Hardware Check" in src
    assert "Hardware Requirements Check" in src
