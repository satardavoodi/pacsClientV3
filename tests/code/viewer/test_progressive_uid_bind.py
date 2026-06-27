"""Guards for multi-study progressive binding by series_uid (2026-06-17, 46970).

A secondary-study series dropped into the viewport is awaited under a DISPLAY KEY
(offset key, e.g. 1000302), but the Download Manager reports progress under the
bare resolved number (302). The viewer therefore never bound the progress to the
waiting viewport → empty viewport until a manual re-drag, and (worse) matching on
the number alone is unsafe because series numbers collide across a patient's
studies. The fix re-keys progress to the awaiting display key, matched on the
globally-unique SeriesInstanceUID, in the download→viewer bridge.

These tests pin the viewer helper that does the uid→display-key lookup, and that
the bridge is wired to use it. ``_vc_progressive`` pulls heavy Qt deps, so the
import is skip-guarded (matching the other viewer tests).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_BRIDGE = _REPO_ROOT / "PacsClient/pacs/workstation_ui/home_ui/home_download_service.py"
_SRC_BRIDGE = _BRIDGE.read_text(encoding="utf-8")


def _cls():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_progressive import _VCProgressiveMixin
    except Exception as exc:  # heavy Qt/viewer deps absent in this shard
        pytest.skip(f"_vc_progressive import unavailable: {exc}")
    return _VCProgressiveMixin


def _ctrl(server_series_info, viewports):
    cls = _cls()
    inst = object.__new__(cls)
    inst.parent_widget = SimpleNamespace(_server_series_info=server_series_info)
    inst.lst_nodes_viewer = [
        SimpleNamespace(vtk_widget=SimpleNamespace(_awaiting_series_number=a))
        for a in viewports
    ]
    return inst


# ---- viewer helper: uid -> awaiting display key -------------------------

def test_matches_awaiting_display_key_by_uid():
    # Multi-study: viewport awaits display key 1000302; progress carries the uid.
    inst = _ctrl({"1000302": {"series_uid": "UID_X", "series_number": "302"}}, ["1000302"])
    assert inst.display_key_awaiting_series_uid("UID_X") == "1000302"


def test_no_match_returns_none():
    inst = _ctrl({"1000302": {"series_uid": "UID_X"}}, ["1000302"])
    assert inst.display_key_awaiting_series_uid("UID_OTHER") is None


def test_no_viewport_awaiting_returns_none():
    inst = _ctrl({"1000302": {"series_uid": "UID_X"}}, [None])  # nothing awaiting
    assert inst.display_key_awaiting_series_uid("UID_X") is None


def test_blank_uid_returns_none():
    inst = _ctrl({"1000302": {"series_uid": "UID_X"}}, ["1000302"])
    assert inst.display_key_awaiting_series_uid("") is None
    assert inst.display_key_awaiting_series_uid(None) is None


def test_single_study_returns_its_own_key_so_bridge_no_ops():
    # Single-study: the awaiting key IS the number; helper returns "5", and the
    # bridge only re-keys when the display key differs from the resolved number,
    # so single-study behavior is unchanged.
    inst = _ctrl({"5": {"series_uid": "UID5", "series_number": "5"}}, ["5"])
    assert inst.display_key_awaiting_series_uid("UID5") == "5"


def test_accepts_series_instance_uid_field():
    inst = _ctrl({"1000302": {"series_instance_uid": "UID_X"}}, ["1000302"])
    assert inst.display_key_awaiting_series_uid("UID_X") == "1000302"


# ---- bridge wiring (UNIFIED 2026-06-27) ---------------------------------
# S3b cutover: the AIPACS_PROGRESSIVE_UID_BIND flag + its dedicated re-key branch were collapsed
# into the single `_grow_lane_display_key` resolver. The awaiting case it handled is now covered by
# the SUPERSET `display_key_for_active_series_uid` (awaiting OR progressively displaying). The
# controller method `display_key_awaiting_series_uid` is still exercised above and remains available.

def test_bridge_uses_unified_resolver_not_flag():
    # the flag's env-read + its dedicated branch are gone (the doc comment may still NAME the
    # retired flag for grep-ability); every grow-lane event goes through the ONE resolver.
    assert 'getenv("AIPACS_PROGRESSIVE_UID_BIND"' not in _SRC_BRIDGE
    assert "_grow_lane_display_key(" in _SRC_BRIDGE
    assert "display_key_for_active_series_uid" in _SRC_BRIDGE
