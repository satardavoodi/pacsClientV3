"""Guards for the viewport download notification (2026-06-17).

While a dropped series is still downloading, the waiting spinner shows a rich,
reassuring loading state so the user sees it is working, not frozen (and does not
re-drag — the slow-link thrash trigger):

  - series identity ("MR · Series 4 · T2 FLAIR"),
  - main status ("Downloading 12 of 25 · 48%" / "Finalizing…"),
  - a progress-bar fraction,
  - a detail line ("1.2 img/s · ~8s left · 5s elapsed"),
  - an inferred connection state ("Connecting…" / "Waiting for server…" /
    "Slow connection — still trying…").

Pure UI only — no render/geometry effect. These tests pin the pure formatters, the
helper's viewport-matching behavior, and that it is wired into the progress handler
+ the spinner/overlay plumbing. The heavy Qt import is skip-guarded (matching
test_batch_growth.py / test_dragdrop_coalesce.py).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_PROG = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_progressive.py"
_SPINNER = _REPO_ROOT / "modules/viewer/widgets/loading_spinner.py"
_OVERLAY = _REPO_ROOT / "PacsClient/components/loading_overlay.py"
_SWITCH = _REPO_ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py"
_SRC_PROG = _PROG.read_text(encoding="utf-8")
_SRC_SPINNER = _SPINNER.read_text(encoding="utf-8")
_SRC_OVERLAY = _OVERLAY.read_text(encoding="utf-8")
_SRC_SWITCH = _SWITCH.read_text(encoding="utf-8")


def _mod():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as m
    except Exception as exc:  # heavy Qt/viewer deps absent in this shard
        pytest.skip(f"_vc_progressive import unavailable: {exc}")
    return m


# ---- pure status formatter (now with percent) ---------------------------

def test_status_in_flight_has_count_and_percent():
    assert _mod()._format_download_progress(12, 25) == "Downloading 12 of 25 · 48%"


def test_status_complete_is_finalizing():
    assert _mod()._format_download_progress(25, 25) == "Finalizing…"


def test_status_clamps_overshoot():
    assert _mod()._format_download_progress(26, 25) == "Finalizing…"


def test_status_unknown_total_is_plain():
    m = _mod()
    assert m._format_download_progress(5, 0) == "Downloading…"
    assert m._format_download_progress("x", "y") == "Downloading…"


def test_status_clamps_negative_downloaded():
    assert _mod()._format_download_progress(-3, 25) == "Downloading 0 of 25 · 0%"


# ---- progress fraction --------------------------------------------------

def test_fraction_basic_and_clamps():
    m = _mod()
    assert m._download_fraction(5, 20) == 0.25
    assert m._download_fraction(0, 0) is None
    assert m._download_fraction(30, 20) == 1.0
    assert m._download_fraction(-5, 20) == 0.0


# ---- rate / ETA + detail line -------------------------------------------

def test_rate_eta_smoothed_from_first_observation():
    m = _mod()
    # 0 → 10 images over 5 s = 2 img/s; 15 remaining of 25 ⇒ ETA 7.5 s.
    rate, eta = m._compute_download_rate_eta(0, 100.0, 10, 105.0, 25)
    assert abs(rate - 2.0) < 1e-6
    assert abs(eta - 7.5) < 1e-6


def test_rate_eta_none_without_progress_or_time():
    m = _mod()
    assert m._compute_download_rate_eta(10, 100.0, 10, 105.0, 25) == (None, None)  # no Δcount
    assert m._compute_download_rate_eta(0, 100.0, 10, 100.0, 25) == (None, None)   # no Δtime


def test_detail_line_omits_unknown_parts():
    m = _mod()
    assert m._format_download_detail(2.0, 7.5, 5) == "2.0 img/s · ~8s left · 5s elapsed"
    assert m._format_download_detail(None, None, 0) == ""
    assert m._format_download_detail(1.0, 0, 0) == "1.0 img/s"


def test_fmt_secs_minutes():
    m = _mod()
    assert m._fmt_secs(8) == "8s"
    assert m._fmt_secs(75) == "1m 15s"


# ---- series identity ----------------------------------------------------

def test_identity_full_and_partial():
    m = _mod()
    assert m._resolve_series_identity_text("MR", "4", "T2 FLAIR") == "MR · Series 4 · T2 FLAIR"
    assert m._resolve_series_identity_text("", "4", "") == "Series 4"
    assert m._resolve_series_identity_text("CT", "", None) == "CT"
    assert m._resolve_series_identity_text("", "", "") == ""


# ---- connection-state inference -----------------------------------------

def test_connection_state_is_neutral_and_never_claims_slow_network():
    m = _mod()
    # Fresh → no override (the normal "Downloading…" line shows instead).
    assert m._connection_state_text(1.0, has_progress=False) == ""
    # Progress arriving → never nags, even if a little stale between batches.
    assert m._connection_state_text(m._DL_STALLED_AFTER_S + 5, has_progress=True) == ""
    # A quiet, not-yet-started wait escalates only to NEUTRAL wording.
    assert m._connection_state_text(m._DL_SLOW_AFTER_S + 0.1, has_progress=False) == "Preparing images…"
    assert m._connection_state_text(m._DL_STALLED_AFTER_S + 0.1, has_progress=False) == "Still loading… (the series may be queued)"
    # Regression guard (patient 46970, fast LAN): the viewer must NEVER assert the
    # connection is slow — it cannot tell slow-link from queued/other-key download.
    for age in (1, 7, 20, 120):
        assert "slow connection" not in m._connection_state_text(age, False).lower()
        assert "slow connection" not in m._connection_state_text(age, True).lower()


# ---- helper viewport-matching behavior (now pushes set_loading_details) --

def _spinner_stub(calls):
    return SimpleNamespace(set_loading_details=lambda **kw: calls.append(kw))


def _node(spinner, awaiting=None, progressive=None):
    vw = SimpleNamespace(
        viewport_spinner=spinner,
        image_viewer=SimpleNamespace(metadata={"series": {"series_number": awaiting or progressive}}),
        _awaiting_series_number=awaiting,
        _progressive_series_number=progressive,
    )
    return SimpleNamespace(vtk_widget=vw)


def test_helper_pushes_details_to_matching_viewport_only():
    m = _mod()
    a_calls, b_calls = [], []
    inst = object.__new__(m._VCProgressiveMixin)
    inst.parent_widget = SimpleNamespace(_server_series_info={})
    inst.lst_nodes_viewer = [
        _node(_spinner_stub(a_calls), awaiting="7"),
        _node(_spinner_stub(b_calls), awaiting="3"),
    ]
    inst._update_download_spinner_text("7", 12, 25)
    assert len(a_calls) == 1 and a_calls[0]["status"] == "Downloading 12 of 25 · 48%"
    assert a_calls[0]["fraction"] == 0.48
    assert b_calls == []  # non-matching viewport untouched


def test_helper_off_when_flag_disabled(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_DOWNLOAD_PROGRESS_TEXT", False)
    calls = []
    inst = object.__new__(m._VCProgressiveMixin)
    inst.parent_widget = SimpleNamespace(_server_series_info={})
    inst.lst_nodes_viewer = [_node(_spinner_stub(calls), awaiting="7")]
    inst._update_download_spinner_text("7", 4, 20)
    assert calls == []


def test_helper_survives_viewport_without_spinner():
    m = _mod()
    inst = object.__new__(m._VCProgressiveMixin)
    inst.parent_widget = SimpleNamespace(_server_series_info={})
    inst.lst_nodes_viewer = [
        SimpleNamespace(vtk_widget=SimpleNamespace(
            _awaiting_series_number="7", _progressive_series_number=None,
            viewport_spinner=None))
    ]
    inst._update_download_spinner_text("7", 4, 20)  # must not raise


# ---- wiring (catches a refactor that drops the feature) -----------------

def test_flag_defaults_on_with_kill_switch():
    assert 'AIPACS_DOWNLOAD_PROGRESS_TEXT", "1"' in _SRC_PROG


def test_helper_called_from_progress_impl():
    assert "self._update_download_spinner_text(sn, downloaded, total)" in _SRC_PROG


def test_overlay_has_structured_updater_and_bar():
    assert "def set_loading_details(" in _SRC_OVERLAY
    assert "QProgressBar" in _SRC_OVERLAY
    assert "AiPacsLoaderIdentityMinimal" in _SRC_OVERLAY  # identity line


def test_viewport_spinner_delegates_loading_details():
    assert "def set_loading_details(" in _SRC_SPINNER


def test_connection_state_watchdog_wired():
    assert "def _dl_watchdog_tick(" in _SRC_PROG
    assert "def _begin_download_wait(" in _SRC_PROG
    # The awaiting path seeds the wait (identity + "Connecting…") + arms the watchdog.
    assert "self._begin_download_wait(vtk_widget, series_number)" in _SRC_SWITCH
