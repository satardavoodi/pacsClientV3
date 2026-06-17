"""Guards for the viewport download-progress notification (2026-06-17).

While a dropped series is still downloading, the waiting spinner shows a live
"Downloading N of M images…" line so the user sees motion instead of a bare
spinner (and does not assume it is stuck and re-drag — the slow-link thrash
trigger). Pure UI status text — no render/geometry effect.

Pins the pure formatter, the helper's viewport-matching behavior, and that it is
wired into the progress handler + the spinner/overlay plumbing. The heavy Qt import
is skip-guarded (matching test_batch_growth.py / test_dragdrop_coalesce.py).
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


# ---- pure formatter -----------------------------------------------------

def test_format_in_flight():
    assert _mod()._format_download_progress(3, 25) == "Downloading 3 of 25 images…"


def test_format_complete_is_finalizing():
    assert _mod()._format_download_progress(25, 25) == "Finalizing…"


def test_format_clamps_overshoot_to_finalizing():
    # A transient count > total must never print "26 of 25".
    assert _mod()._format_download_progress(26, 25) == "Finalizing…"


def test_format_unknown_total_is_plain():
    m = _mod()
    assert m._format_download_progress(5, 0) == "Downloading…"
    assert m._format_download_progress("x", "y") == "Downloading…"


def test_format_clamps_negative_downloaded():
    assert _mod()._format_download_progress(-3, 25) == "Downloading 0 of 25 images…"


# ---- helper viewport-matching behavior ----------------------------------

def _spinner_stub(calls):
    return SimpleNamespace(set_status=lambda t: calls.append(t))


def _node(spinner, awaiting=None, progressive=None):
    vw = SimpleNamespace(
        viewport_spinner=spinner,
        _awaiting_series_number=awaiting,
        _progressive_series_number=progressive,
    )
    return SimpleNamespace(vtk_widget=vw)


def test_helper_updates_only_the_matching_viewport():
    m = _mod()
    a_calls, b_calls = [], []
    inst = object.__new__(m._VCProgressiveMixin)
    inst.lst_nodes_viewer = [
        _node(_spinner_stub(a_calls), awaiting="7"),   # awaiting series 7
        _node(_spinner_stub(b_calls), awaiting="3"),   # awaiting a DIFFERENT series
    ]
    inst._update_download_spinner_text("7", 4, 20)
    assert a_calls == ["Downloading 4 of 20 images…"]
    assert b_calls == []  # non-matching viewport untouched


def test_helper_matches_progressive_series_too():
    m = _mod()
    calls = []
    inst = object.__new__(m._VCProgressiveMixin)
    inst.lst_nodes_viewer = [_node(_spinner_stub(calls), progressive="9")]
    inst._update_download_spinner_text("9", 10, 10)
    assert calls == ["Finalizing…"]


def test_helper_off_when_flag_disabled(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_DOWNLOAD_PROGRESS_TEXT", False)
    calls = []
    inst = object.__new__(m._VCProgressiveMixin)
    inst.lst_nodes_viewer = [_node(_spinner_stub(calls), awaiting="7")]
    inst._update_download_spinner_text("7", 4, 20)
    assert calls == []  # kill switch → no status updates


def test_helper_survives_viewport_without_spinner():
    m = _mod()
    inst = object.__new__(m._VCProgressiveMixin)
    inst.lst_nodes_viewer = [
        SimpleNamespace(vtk_widget=SimpleNamespace(
            _awaiting_series_number="7", _progressive_series_number=None))
    ]
    inst._update_download_spinner_text("7", 4, 20)  # must not raise


# ---- wiring (catches a refactor that drops the feature) -----------------

def test_flag_defaults_on_with_kill_switch():
    assert 'AIPACS_DOWNLOAD_PROGRESS_TEXT", "1"' in _SRC_PROG


def test_helper_called_from_progress_impl():
    assert "self._update_download_spinner_text(sn, downloaded, total)" in _SRC_PROG


def test_viewport_spinner_exposes_set_status():
    assert "def set_status(self, text):" in _SRC_SPINNER


def test_minimal_overlay_has_status_label():
    # The minimal branded overlay (used by ViewportSpinner) grew an optional
    # status line for this feature; it used to return early with no label.
    assert "AiPacsLoaderStatusMinimal" in _SRC_OVERLAY


def test_initial_downloading_status_set_on_await():
    # The awaiting-download path seeds an immediate status so the spinner is
    # never a blank "is it stuck?" wait before the first progress signal.
    assert 'set_status("Downloading' in _SRC_SWITCH
