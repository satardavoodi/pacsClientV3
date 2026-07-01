"""Guard: Stage A1 — grow a DISPLAYED viewport to its full on-disk count (48273 Series 602).

A secondary (previous-exam) study's download progress/completion is never bridged to the
viewer, so a secondary series dragged mid-download builds a PARTIAL stack (e.g. 40/380), the
load "succeeds", its awaiting flag clears, and nothing grows it. This rule makes the watchdog
rebuild a DISPLAYED viewport whose shown slices < its OWN canonical on-disk .dcm count, once
the folder has SETTLED. Matched on canonical (study_uid, orig_series), capped, settled-only.
DEFAULT-OFF (AIPACS_GROW_DISPLAYED_TO_DISK=1 to enable) until live-verified on 48273.

Source-pins + a behavioral test of the settle predicate it reuses.
"""
import types
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_progressive.py"
    ).read_text(encoding="utf-8")


def test_flag_default_on_and_method_present():
    src = _src()
    # DEFAULT-ON (flipped 2026-06-30 after 48567): env default "1", kill switch "=0".
    assert 'os.getenv("AIPACS_GROW_DISPLAYED_TO_DISK", "1") or "1"' in src
    assert "_GROW_DISPLAYED_TO_DISK = (" in src
    assert "def _maybe_grow_displayed_to_disk(self, vtk_w) -> bool:" in src
    # gated on the flag at the top of the method (no behavior unless enabled)
    fn = src.find("def _maybe_grow_displayed_to_disk")
    head = src[fn:fn + 2000]
    assert "if not _GROW_DISPLAYED_TO_DISK:" in head and "return False" in head


def test_grow_uses_canonical_identity_and_settle_and_cap():
    src = _src()
    fn = src.find("def _maybe_grow_displayed_to_disk")
    body = src[fn:fn + 7000]
    # canonical identity, not the bare series number
    assert "self._resolve_canonical_series_identity(display_key)" in body
    assert "_viewport_displayed_series_number(vtk_w)" in body
    # counts the series' OWN folder + .part, settled-only rebuild
    assert 'nm.endswith(".part")' in body
    assert "_disk_series_settled(disk, prev, has_part)" in body
    # only rebuild when behind, via the proven change_series path
    assert "if disk <= displayed:" in body
    assert "self.change_series_on_viewer(" in body
    # force_reload=True is required so the same-series skip doesn't swallow the rebuild
    # (safe: only runs on a settled/complete folder → no re-download).
    assert "force_reload=True," in body
    # capped per (series, disk-count) to prevent churn
    assert "_GROW_DISPLAYED_MAX_ATTEMPTS" in body


def test_watchdog_wires_grow_and_keeps_alive_while_behind():
    src = _src()
    fn = src.find("def _dl_watchdog_tick")
    body = src[fn:fn + 2200]
    assert "any_behind = False" in body
    assert "if self._maybe_grow_displayed_to_disk(vtk_w):" in body
    assert "any_behind = True" in body
    # the watchdog now self-stops only when NOTHING is awaiting AND nothing is behind
    assert "if not any_awaiting and not any_behind:" in src


def test_settle_predicate_behavioral():
    # the settle predicate the grow reuses (already used by the resume) — behind+settled.
    pytest.importorskip("vtk")
    try:
        from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_progressive as MX
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"import unavailable: {exc}")
    s = MX._disk_series_settled
    # 380 stable on disk, no .part -> settled -> a 40-slice viewport is behind+settled -> grow
    assert s(380, 380, False) is True
    # still downloading (a .part present) -> not settled -> keep watching, don't rebuild
    assert s(380, 380, True) is False
    # disk still growing -> not settled
    assert s(380, 300, False) is False
