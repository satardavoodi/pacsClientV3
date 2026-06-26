"""S5b guard: cancellation-on-teardown wired into the async series apply + the close path.

Flag AIPACS_VIEWER_UNIFIED_TEARDOWN (default ON 2026-06-26 — safe-robustness activation; =0 → no
tokens → byte-identical legacy). When ON, an
in-flight async apply registers a CancellationToken on this viewer's stable handle; a tab/patient
close (cancel_inflight_loads) or a superseding load cancels it, so the queued UI-thread apply bails
BEFORE touching a possibly-deleted widget (the D1 use-after-free class).

Plan: docs/plans/architecture/VIEWER_UNIFICATION_STAGED_PLAN_2026-06-25.md (S5b).
"""
import logging
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


@pytest.fixture()
def _ctl():
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui._vc_switch import _VCSwitchMixin
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"_vc_switch import unavailable: {exc}")

    class _Ctl(_VCSwitchMixin):
        def __init__(self):
            self._viewer_request_token = {}
            self.logger = logging.getLogger("test_s5b")

    return _Ctl()


class _W:
    def __init__(self, slot):
        self.id_vtk_widget = slot


# --------------------------------------------------------------------------- #
# Functional — the cancellation helpers
# --------------------------------------------------------------------------- #

def test_flag_off_is_noop(_ctl, monkeypatch):
    monkeypatch.setenv("AIPACS_VIEWER_UNIFIED_TEARDOWN", "0")
    assert _ctl._register_load_cancellation(_W(0)) is None
    assert _ctl.cancel_inflight_loads() == 0          # no registry ever created


def test_flag_on_register_and_cancel(_ctl, monkeypatch):
    monkeypatch.setenv("AIPACS_VIEWER_UNIFIED_TEARDOWN", "1")
    tok = _ctl._register_load_cancellation(_W(0))
    assert tok is not None and not _ctl._load_cancelled(tok)
    assert _ctl.cancel_inflight_loads() == 1          # close cancels the in-flight load
    assert _ctl._load_cancelled(tok)


def test_retire_prevents_later_cancel(_ctl, monkeypatch):
    monkeypatch.setenv("AIPACS_VIEWER_UNIFIED_TEARDOWN", "1")
    tok = _ctl._register_load_cancellation(_W(0))
    _ctl._retire_load_cancellation(tok)               # apply finished cleanly
    _ctl.cancel_inflight_loads()
    assert not _ctl._load_cancelled(tok)


def test_supersede_cancels_prior_load_same_viewport(_ctl, monkeypatch):
    monkeypatch.setenv("AIPACS_VIEWER_UNIFIED_TEARDOWN", "1")
    w = _W(0)
    t1 = _ctl._register_load_cancellation(w)
    t2 = _ctl._register_load_cancellation(w)           # supersede=True → cancels the prior load
    assert _ctl._load_cancelled(t1) and not _ctl._load_cancelled(t2)


# --------------------------------------------------------------------------- #
# Source-pins — the hot-path wiring
# --------------------------------------------------------------------------- #

def test_wired_into_async_apply():
    s = (_root() / "PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py").read_text(encoding="utf-8")
    assert "AIPACS_VIEWER_UNIFIED_TEARDOWN" in s
    assert "_cancel_tok = self._register_load_cancellation(vtk_widget)" in s
    fin = s[s.index("def _finish_on_ui"):]
    assert "if self._load_cancelled(_cancel_tok):" in fin[:300]     # bails first, before the body
    assert "self._retire_load_cancellation(_cancel_tok)" in s        # retires on completion


def test_wired_into_close_path():
    life = (_root() / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_lifecycle.py"
            ).read_text(encoding="utf-8")
    assert "cancel_inflight_loads()" in life
