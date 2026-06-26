"""S1b guard: _is_request_current also requires the cell's stable ViewerHandle to match the
handle that issued the token, closing the A1 grid-index collision. Flag
AIPACS_VIEWER_STABLE_IDENTITY (default off → byte-identical token-only check).

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md (S1b).
"""
import logging
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def _ctl():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_switch import _VCSwitchMixin
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"_vc_switch import unavailable: {exc}")

    class _Ctl(_VCSwitchMixin):
        def __init__(self):
            self._viewer_request_token = {}
            self.logger = logging.getLogger("test_stable_identity")

    return _Ctl()


class _W:
    def __init__(self, slot):
        self.id_vtk_widget = slot


def test_same_widget_passes(_ctl, monkeypatch):
    monkeypatch.setenv("AIPACS_VIEWER_STABLE_IDENTITY", "1")
    w = _W(0)
    tok = _ctl._next_request_token(w)
    assert _ctl._is_request_current(w, tok) is True   # same cell/handle → current


def test_rebound_slot_rejected_even_if_token_matches(_ctl, monkeypatch):
    """A1: a different cell rebound to the SAME grid slot must NOT pass a stale token, even
    though the numeric token still matches the slot's counter."""
    monkeypatch.setenv("AIPACS_VIEWER_STABLE_IDENTITY", "1")
    w_a = _W(0)
    tok = _ctl._next_request_token(w_a)          # records w_a's handle for slot 0
    w_b = _W(0)                                   # NEW cell rebound to slot 0 (new handle)
    # token dict still says slot 0 == tok, so the legacy token-only check would pass...
    assert int(_ctl._viewer_request_token[0]) == tok
    # ...but the stable-identity handle check rejects the foreign cell.
    assert _ctl._is_request_current(w_b, tok) is False


def test_flag_off_is_token_only(_ctl, monkeypatch):
    monkeypatch.setenv("AIPACS_VIEWER_STABLE_IDENTITY", "0")
    w_a = _W(0)
    tok = _ctl._next_request_token(w_a)
    w_b = _W(0)
    # legacy behavior: token-only, handle ignored → the rebound slot still "passes"
    assert _ctl._is_request_current(w_b, tok) is True


def test_no_recorded_handle_falls_back_to_token(_ctl, monkeypatch):
    """If no handle was recorded for the slot (e.g. token issued before identity was on),
    the check falls back to token-only — never a false rejection."""
    monkeypatch.setenv("AIPACS_VIEWER_STABLE_IDENTITY", "1")
    w = _W(2)
    _ctl._viewer_request_token[2] = 5            # token present, but no handle recorded
    assert _ctl._is_request_current(w, 5) is True
