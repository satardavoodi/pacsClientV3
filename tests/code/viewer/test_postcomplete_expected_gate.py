"""Guard: the post-download "already fully visible" skip is gated on the
AUTHORITATIVE expected series count, not a transient/cached on-disk count
(2026-06-24, left-viewport partial-stack freeze — patient 47804 series 6, Razi).

Root cause: after a series finishes downloading, ``load_series_on_demand``
decided whether to skip a redundant reload by calling
``_viewer_has_series_fully_visible(series, _count_series_files_on_disk(series))``.
``_count_series_files_on_disk`` has a 1 s TTL cache and counts only finished
``.dcm`` files, so a probe that ran moments earlier (the same-series "retry
incomplete" check) or a concurrent re-download mid ``.part``-write left a
STALE-LOW value cached (observed: 3 cached while 24 were on disk).  Passing that
low number in as the completeness TARGET made a viewer showing a partial stack
(8 of 24) look "fully visible" (8 >= 3) and SKIP the grow-to-full reload, so the
left viewport stayed frozen on a partial series.

Fix: bust the disk-count cache at the completion boundary (the download just
finished, so disk truly holds every file) AND gate the skip on
``max(disk, _resolve_series_expected_count(series))`` so the skip fires only when
the viewer genuinely shows every expected slice.  Default ON; kill switch
``AIPACS_POSTCOMPLETE_EXPECTED_GATE=0`` restores the legacy raw-disk gate.

Source-pin (the real reload needs a live viewer + worker thread to exercise).
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
        / "_vc_load.py"
    ).read_text(encoding="utf-8")


def test_flag_present_default_on():
    src = _src()
    assert "AIPACS_POSTCOMPLETE_EXPECTED_GATE" in src
    # Default ON: env default literal is "1" and the gate disables only on "0".
    m = re.search(
        r'os\.getenv\(\s*"AIPACS_POSTCOMPLETE_EXPECTED_GATE"\s*,\s*"1"\s*\)[\s\S]*?!=\s*"0"',
        src,
    )
    assert m is not None, "post-complete expected gate must default ON (disable on '0')"


def test_busts_disk_count_cache_at_completion_boundary():
    src = _src()
    idx = src.find("AIPACS_POSTCOMPLETE_EXPECTED_GATE")
    assert idx != -1
    block = src[idx: idx + 1400]
    # The completion boundary must invalidate the stale disk-count cache so the
    # downstream completeness probes read the TRUE current file count.
    assert "_invalidate_disk_count_cache(series_number_str)" in block


def test_gate_uses_authoritative_expected_not_raw_disk():
    src = _src()
    idx = src.find("AIPACS_POSTCOMPLETE_EXPECTED_GATE")
    assert idx != -1
    block = src[idx: idx + 1400]
    # Expected target is resolved (server series-info / metadata), not the raw count.
    assert "_resolve_series_expected_count(series_number_str)" in block
    # The gate target is max(disk, resolved-expected) — never the raw disk alone.
    assert re.search(r"_gate_expected\s*=\s*max\(\s*_completed_disk_count\s*,\s*_resolved_expected\s*\)", block)
    # And that target (not the raw disk count) is what the skip is gated on.
    assert re.search(
        r"_viewer_has_series_fully_visible\(\s*series_number_str\s*,\s*_gate_expected\s*,",
        block,
    )


def test_legacy_gate_preserved_as_kill_switch():
    """When the flag is OFF the gate target collapses to the raw disk count
    (legacy behavior) — i.e. _gate_expected is seeded from _completed_disk_count
    before the flag-gated max() runs."""
    src = _src()
    idx = src.find("AIPACS_POSTCOMPLETE_EXPECTED_GATE")
    assert idx != -1
    block = src[idx: idx + 1400]
    assert "_gate_expected = _completed_disk_count" in block
