"""S1 (read-only shadow) guard: stable ViewerHandle attached to viewer cells + a default-off
shadow that detects grid-index (A1) reuse, WITHOUT changing the live request-token behavior.

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md

- Source-pins: the live token path is unchanged (shadow call comes AFTER the token write /
  the `current` computation), shadow helpers gate on `shadow_enabled()`.
- Functional: shadow OFF → token increments + `_is_request_current` identical to legacy and NO
  handle attached (zero cost); shadow ON → reusing a grid index with a different cell identity
  logs `grid_slot_reused`.
"""
import logging
import re
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_switch.py"
    ).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Source-pins: live path unchanged, shadow is gated + read-only
# --------------------------------------------------------------------------- #

def test_live_token_write_precedes_shadow():
    src = _src()
    fn = src[src.index("def _next_request_token"): src.index("def _is_request_current")]
    i_write = fn.index("self._viewer_request_token[viewer_id] = token")
    i_shadow = fn.index("_shadow_record_token")
    i_return = fn.index("return token")
    assert i_write < i_shadow < i_return, "shadow must run AFTER the token write, before return"


def test_is_request_current_returns_live_value():
    src = _src()
    fn = src[src.index("def _is_request_current"): src.index("def _arm_spinner_timeout")]
    # current is computed from the live token dict, shadow is called, then current returned.
    assert "current = int(self._viewer_request_token.get(viewer_id, 0)) == int(expected_token)" in fn
    assert fn.index("current =") < fn.index("_shadow_check_token") < fn.rindex("return current")


def test_shadow_helpers_gate_on_flag():
    src = _src()
    # _shadow_check_token stays shadow-only; _shadow_record_token also feeds S1b so it gates on
    # (shadow_enabled() OR the stable-identity flag) — both still no-op when neither is on.
    chk = src[src.index("def _shadow_check_token"):]
    chk = chk[: chk.index("\n    def ", 1)]
    assert "if not shadow_enabled()" in chk
    rec = src[src.index("def _shadow_record_token"):]
    rec = rec[: rec.index("\n    def ", 1)]
    assert "shadow_enabled()" in rec and "AIPACS_VIEWER_STABLE_IDENTITY" in rec
    assert "if not (shadow_enabled() or _stable)" in rec


# --------------------------------------------------------------------------- #
# Functional
# --------------------------------------------------------------------------- #

@pytest.fixture()
def _ctl():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_switch import _VCSwitchMixin
    except Exception as exc:  # pragma: no cover - import env guard
        pytest.skip(f"_vc_switch import unavailable: {exc}")

    class _Ctl(_VCSwitchMixin):
        def __init__(self):
            self._viewer_request_token = {}
            self.logger = logging.getLogger("test_vc_identity")

    return _Ctl()


class _W:
    def __init__(self, slot):
        self.id_vtk_widget = slot


def test_handle_is_stable_and_slot_is_diagnostic(_ctl):
    w = _W(0)
    h1 = _ctl._viewer_handle_for(w)
    h2 = _ctl._viewer_handle_for(w)
    assert h1 == h2 and h1.uuid == h2.uuid          # stable across calls
    w.id_vtk_widget = 3                              # cell moved to another slot
    h3 = _ctl._viewer_handle_for(w)
    assert h3 == h1 and h3.slot_hint == 3           # same identity, refreshed slot


def test_shadow_off_is_byte_identical_and_zero_cost(_ctl, monkeypatch):
    from PacsClient.utils import series_state_store
    monkeypatch.setattr(series_state_store, "_VIEWER_SPINE_SHADOW", False)
    w = _W(0)
    assert _ctl._next_request_token(w) == 1
    assert _ctl._next_request_token(w) == 2
    assert _ctl._is_request_current(w, 2) is True
    assert _ctl._is_request_current(w, 1) is False
    # shadow off → no handle attached, no shadow store created (zero cost)
    assert not hasattr(w, "_viewer_handle")
    assert getattr(_ctl, "_viewer_token_handle", None) is None


def test_shadow_on_detects_grid_slot_reuse(_ctl, monkeypatch, caplog):
    from PacsClient.utils import series_state_store
    monkeypatch.setattr(series_state_store, "_VIEWER_SPINE_SHADOW", True)
    caplog.set_level(logging.INFO, logger="test_vc_identity")

    cell_a = _W(0)                     # patient A's viewer at grid slot 0
    _ctl._next_request_token(cell_a)
    cell_b = _W(0)                     # patient B's NEW viewer reusing grid slot 0
    _ctl._next_request_token(cell_b)

    assert any("grid_slot_reused" in r.message or "grid_slot_reused" in r.getMessage()
               for r in caplog.records), "reusing a grid slot with a new cell identity must log"
    # the live token dict still works the legacy way (keyed by grid index)
    assert _ctl._viewer_request_token[0] == 2
    # and the shadow store now tracks cell_b's handle for slot 0
    assert _ctl._viewer_token_handle[0] == cell_b._viewer_handle.uuid
