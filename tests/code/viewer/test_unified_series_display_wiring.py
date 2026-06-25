"""Source-wiring guard: change_series_on_viewer's same-series path routes its
never-downgrade decision through the shared series-display authority
(PacsClient/utils/series_display_state.py) — §7 unification step
(docs/reports/SERIES_DISPLAY_PIPELINE_UNIFIED_METHOD_EVALUATION_2026-06-24.md).

The real switch needs a live viewer; this pins the wiring so a stale build or an
accidental revert is caught.
"""
import re
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _switch_src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "_vc_switch.py"
    ).read_text(encoding="utf-8")


def test_authority_is_imported():
    src = _switch_src()
    assert "from PacsClient.utils.series_display_state import" in src
    assert "decide_display_action" in src
    assert "build_series_display_state" in src
    assert "DisplayAction" in src


def test_flag_present_default_on():
    src = _switch_src()
    assert "AIPACS_UNIFIED_SERIES_DISPLAY" in src
    m = re.search(
        r'os\.getenv\(\s*"AIPACS_UNIFIED_SERIES_DISPLAY"\s*,\s*"1"\s*\)[\s\S]*?!=\s*"0"',
        src,
    )
    assert m is not None, "unified series-display gate must default ON (disable on '0')"


def test_guard_feeds_real_viewer_visible_count():
    """The decision must be fed the viewer's ACTUAL visible slice count
    (get_count_of_slices) — not the canonical-metadata count — since that is the
    quantity the legacy branching ignored."""
    src = _switch_src()
    idx = src.find("AIPACS_UNIFIED_SERIES_DISPLAY")
    assert idx != -1
    block = src[idx: idx + 1400]
    assert "get_count_of_slices()" in block
    assert "viewer_visible_count=" in block
    assert "build_series_display_state(" in block


def test_skip_downgrade_returns_without_rebuild():
    src = _switch_src()
    idx = src.find("AIPACS_UNIFIED_SERIES_DISPLAY")
    assert idx != -1
    block = src[idx: idx + 3600]
    # The only NEW behavior is honoring SKIP_DOWNGRADE by keeping the current
    # volume (return) — every other action falls through to the legacy branching.
    assert "DisplayAction.SKIP_DOWNGRADE" in block
    assert re.search(r"skip-downgrade series=", block)
    # It returns (does not fall through to a rebuild) on the downgrade verdict:
    # the skip-downgrade log line is immediately followed by a `return`.
    assert re.search(r"skip-downgrade series=[\s\S]{0,400}?\n\s+return\b", block)


def test_2a_authority_drives_grow_and_incomplete_flags():
    """Phase 2A: the authority is the single decision source — its viewer-aware
    verdict drives the legacy operation flags (series_grew / series_incomplete),
    not just the downgrade guard. This removes the dual (canonical-only vs
    viewer-aware) decision."""
    src = _switch_src()
    idx = src.find("AIPACS_UNIFIED_SERIES_DISPLAY")
    assert idx != -1
    block = src[idx: idx + 3600]
    # has_lazy_loader is fed in so GROW_IN_PLACE vs REFRESH_AND_REBUILD is accurate.
    assert "has_lazy_loader=" in block
    # The action maps onto the operation flags.
    assert re.search(r"DisplayAction\.GROW_IN_PLACE[\s\S]{0,260}?series_grew\s*=\s*True", block)
    assert re.search(r"DisplayAction\.AWAIT_DOWNLOAD[\s\S]{0,260}?series_incomplete\s*=\s*True", block)
    assert re.search(r"DisplayAction\.NOOP[\s\S]{0,300}?series_grew\s*=\s*False", block)
