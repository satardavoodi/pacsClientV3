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
finished, so disk truly holds every file) AND gate the skip on the completeness
TARGET (``max(disk, _resolve_series_expected_count(series))``) so the skip fires
only when the viewer genuinely shows every expected slice.

UNIFIED (S3b cutover, 2026-06-27): the ``AIPACS_POSTCOMPLETE_EXPECTED_GATE`` flag +
its legacy raw-disk ``=0`` branch (the buggy 47804 path) were removed, and the
target now comes from the SHARED series-display authority
(``build_series_display_state(...).target`` == ``max(disk, expected)``) — the same
truth every other entry point uses, routed through the one authority instead of a
local ``max()``. The fix is preserved structurally (proven equivalent below).

Source-pin + a functional equivalence proof (the real reload needs a live viewer).
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


def test_gate_is_unconditional_no_flag():
    src = _src()
    # S3b cutover 2026-06-27: the flag's env-read + its legacy raw-disk `=0` branch were removed
    # (the comment may still NAME the retired flag for history). The gate is unconditional.
    assert 'getenv("AIPACS_POSTCOMPLETE_EXPECTED_GATE"' not in src


def test_busts_disk_count_cache_at_completion_boundary():
    src = _src()
    anchor = src.find("UNCONDITIONAL since the S3b cutover")
    assert anchor != -1
    block = src[anchor: anchor + 1500]
    # The completion boundary must STILL invalidate the stale disk-count cache so the
    # downstream completeness probes read the TRUE current file count (the 47804 fix).
    assert "_invalidate_disk_count_cache(series_number_str)" in block


def test_gate_target_via_shared_authority():
    src = _src()
    anchor = src.find("UNCONDITIONAL since the S3b cutover")
    assert anchor != -1
    block = src[anchor: anchor + 1500]
    # Expected is resolved (server series-info / metadata), and the TARGET comes from the ONE
    # series-display authority (build_series_display_state(...).target == max(disk, expected)) —
    # not a local max() re-derived per site.
    assert "_resolve_series_expected_count(series_number_str)" in block
    assert "build_series_display_state(" in block and ".target" in block
    # And that authoritative target (not the raw disk count) is what the skip is gated on.
    assert re.search(
        r"_viewer_has_series_fully_visible\(\s*series_number_str\s*,\s*_gate_expected\s*,",
        src,
    )


def test_authority_target_equals_max_disk_expected():
    """Behaviour-equivalence proof: routing through the authority yields the SAME target the old
    inline `max(disk, expected)` did — so the 47804 fix is preserved, structurally. The 8/24 and
    3/24 cases are the exact stale-low-disk scenarios that froze the left viewport."""
    from PacsClient.utils.series_display_state import build_series_display_state
    for disk, exp in [(24, 0), (8, 24), (3, 24), (0, 0), (10, 10), (126, 1)]:
        t = build_series_display_state("6", disk_count=disk, expected_count=exp).target
        assert t == max(disk, exp), (disk, exp, t)
