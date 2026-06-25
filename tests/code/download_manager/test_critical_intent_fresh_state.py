"""Guard: request_critical_series reads `current_series_number` FRESH (post-update),
not from the entry snapshot, so the batch-yield / interrupt targets the series the
running worker is ACTUALLY on (2026-06-25, architecture-review F1 race).

Root cause: `state` is captured at method entry; the running download subprocess
(sharing the state store) can advance `current_series_number` before the
yield/interrupt decision. Reasoning from the stale snapshot wrote the
.critical_intent.json for the wrong series under rapid cross-patient/series drops
("nothing finishes"). Fix: re-read state after `state_store.update`. Default on;
`AIPACS_CRITICAL_INTENT_FRESH_STATE=0` restores the legacy stale read. The
VALIDATING fallback intentionally still reads the entry snapshot's
viewed_series_number.

Source-pin (the race needs a live worker subprocess + state store to exercise).
"""
import re
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _src() -> str:
    return (
        _repo_root() / "modules" / "download_manager" / "coordinator"
        / "series_intent_coordinator.py"
    ).read_text(encoding="utf-8")


def test_flag_present_default_on():
    src = _src()
    assert "AIPACS_CRITICAL_INTENT_FRESH_STATE" in src
    m = re.search(
        r'os\.getenv\(\s*"AIPACS_CRITICAL_INTENT_FRESH_STATE"\s*,\s*"1"\s*\)[\s\S]*?!=\s*"0"',
        src,
    )
    assert m is not None, "critical-intent fresh-state must default ON (disable on '0')"


def test_current_series_reread_after_update():
    src = _src()
    upd = src.find("self.state_store.update(study_uid, **updates)")
    flag = src.find("AIPACS_CRITICAL_INTENT_FRESH_STATE")
    assert upd != -1 and flag != -1
    # The fresh read happens AFTER the state_store.update call.
    assert flag > upd
    block = src[flag: flag + 500]
    # current_series is taken from a freshly re-fetched state (fall back to entry snapshot).
    assert "_fresh_state = self.state_store.get(study_uid)" in block
    assert re.search(r"current_series\s*=\s*getattr\(\s*_fresh_state\s*or\s*state", block)


def test_validating_fallback_keeps_entry_snapshot():
    """The VALIDATING fallback must still read the ENTRY snapshot's
    viewed_series_number (pre-update, the previously-viewed series) — not the fresh
    state (which would equal the just-requested series)."""
    src = _src()
    assert re.search(
        r"effective_current\s*=\s*current_series\s*or\s*\(\s*getattr\(\s*state,\s*'viewed_series_number'",
        src,
    )
