"""Guard: the FAST container's same-series no-op must REBUILD when the displayed
volume is behind the incoming metadata's instance list, instead of skipping
(2026-06-25, patient 47855 series 203 = "1 image" while disk/metadata = 126).

Root cause: `QtFastContainer.switch_series` skipped a rebuild whenever the series
number + path matched, never checking whether the displayed VOLUME was complete.
For secondary-study series the viewport held a 1-slice preview while disk/metadata
held the full set, so every resume hit the skip and the volume never grew. Fix:
do not skip when `get_count_of_slices()` < the incoming metadata instance count —
rebuild the full volume. Default on; `AIPACS_SWITCH_REBUILD_WHEN_BEHIND=0` = legacy.

Source-pin (the real switch needs a live Qt bridge + volume).
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
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "vtk_widget" / "qt_fast_container.py"
    ).read_text(encoding="utf-8")


def test_flag_present_default_on():
    src = _src()
    assert "AIPACS_SWITCH_REBUILD_WHEN_BEHIND" in src
    m = re.search(
        r'os\.getenv\(\s*"AIPACS_SWITCH_REBUILD_WHEN_BEHIND"\s*,\s*"1"\s*\)[\s\S]*?!=\s*"0"',
        src,
    )
    assert m is not None, "rebuild-when-behind must default ON (disable on '0')"


def test_guard_compares_volume_to_incoming_instances():
    src = _src()
    idx = src.find("AIPACS_SWITCH_REBUILD_WHEN_BEHIND")
    assert idx != -1
    block = src[max(0, idx - 600): idx + 400]
    # The current VOLUME slice count vs the incoming metadata instance count.
    assert "get_count_of_slices()" in block
    assert "instances" in block
    assert re.search(r"_cur_vis\s*<\s*_inc_inst", block)


def test_volume_behind_blocks_the_skip():
    """`_volume_behind` is ANDed into the no-op condition so a partial volume
    forces a rebuild instead of the same-series skip."""
    src = _src()
    # The no-op condition must include `not _volume_behind`.
    assert re.search(r"not force_reload\s*\n\s*and not _volume_behind", src)
