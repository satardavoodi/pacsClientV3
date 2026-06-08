"""Guard: search re-entrancy generation token (crash fix 2026-06-08).

Root cause of the native access violation in
``patient_table_widget.add_patient_data`` during search: ``_cancelled`` reads the
shared ``home._cancel_search_requested``, which every ``search_server`` resets to
``False`` at entry. So when a 2nd search started while the 1st was still
populating the table (the loops yield via ``await asyncio.sleep(0)``), the 1st
search stopped seeing cancellation and kept calling ``add_patient_data`` on a
table the 2nd had already ``clear_table()``'d → freed Qt cell-widget → AV.

Fix: a monotonic ``home._search_generation`` token, bumped at each search entry
and checked in every table-population loop so a superseded population stops
before touching the (re)cleared table. These source guards prevent regression.
"""
from pathlib import Path

SRC = (
    Path(__file__).resolve().parents[3]
    / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_search_service.py"
)


def _src() -> str:
    return SRC.read_text(encoding="utf-8")


def test_generation_token_bumped_at_each_search_entry():
    s = _src()
    # search_server AND search_server_advanced both bump + capture the token.
    assert s.count("home._search_generation = int(getattr(home, '_search_generation', 0)) + 1") >= 2
    assert s.count("_my_search_gen = home._search_generation") >= 2


def test_every_population_loop_checks_generation():
    s = _src()
    # socket loop + offline-cloud loop + advanced loop = 3 population loops must
    # bail when a newer search supersedes them.
    assert s.count("home._search_generation != _my_search_gen") >= 3


def test_guard_is_first_statement_of_each_population_loop():
    """Each `for i, ... in enumerate(...)` population loop must open with the
    cancellation+generation guard before any table mutation."""
    import re
    s = _src()
    pat = re.compile(
        r"for i, \w+ in enumerate\([^\n]*\):\s*\n\s*"
        r"if self\._cancelled or home\._search_generation != _my_search_gen:"
    )
    # socket loop + offline-cloud loop + advanced loop
    assert len(pat.findall(s)) >= 3
