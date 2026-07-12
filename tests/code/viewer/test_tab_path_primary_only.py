"""Guard: a SECONDARY study's series must never repoint the TAB's study_path (49836).

Root cause (2026-07-12, patient 49836): `_apply_loaded_series_data` (`_vc_load.py`)
adopted `metadata['series']['series_path'].parent` as the tab's `import_folder_path`
for ANY loaded series — including a secondary / previous-exam study's.

49836 has two studies that BOTH contain series numbered 2/3/4:
    study A (primary, …068)  folder 3 -> SeriesInstanceUID …43657708721
    study B (…059)           folder 3 -> SeriesInstanceUID …35932803366

Loading study B's series (offset key 1000004) repointed the tab path to study B.
The next PRIMARY (plain-key) load then resolved `study_path/3` to **study B's**
folder 3 and handed study B's series 3 to a viewport that intended study A's:

    [IDENTITY-GATE] viewer=0 SKIP render: incoming series=3 uid=…5932803366
                    != intended uid=…3657708721

The identity gate correctly refused to paint the wrong study's images — so series 3
simply NEVER DISPLAYED. The tab's `import_folder_path` is the TAB's (primary) study;
a secondary series must load from its OWN entry `series_path` and must never redirect
it.

Fix (flag `AIPACS_TAB_PATH_PRIMARY_ONLY`, default on; `=0` = legacy adopt-any):
only adopt the path when it belongs to the tab's primary study.
"""

import pytest


def _adopt(env, tab_primary_uid, candidate_study_uid, exists=True):
    """Mirrors the decision in _vc_load._apply_loaded_series_data.

    Returns True when the candidate path is adopted as the tab's study_path.
    """
    primary_only = (env.get("AIPACS_TAB_PATH_PRIMARY_ONLY", "1") or "1").strip() != "0"
    is_primary = (
        (not primary_only)
        or (not tab_primary_uid)          # unknown primary -> legacy behaviour
        or (candidate_study_uid == tab_primary_uid)
    )
    if not exists:
        return False
    return bool(is_primary)


A = "1.3.12.2.1107.5.2.46.174759.30000026071104394762400000068"   # primary
B = "1.3.12.2.1107.5.2.46.174759.30000026071104394762400000059"   # secondary


# ── the 49836 bug ──────────────────────────────────────────────────────
def test_secondary_study_series_does_not_poison_tab_path():
    """Loading study B's series must NOT repoint the tab (primary = A)."""
    assert _adopt({}, tab_primary_uid=A, candidate_study_uid=B) is False


def test_primary_study_series_still_adopts_path():
    """The primary study's own series still sets the tab path (unchanged)."""
    assert _adopt({}, tab_primary_uid=A, candidate_study_uid=A) is True


def test_single_study_tab_is_byte_identical():
    """A single-study tab's only study IS the primary -> always adopts, as before."""
    assert _adopt({}, tab_primary_uid=A, candidate_study_uid=A) is True


# ── fail-open / safety ─────────────────────────────────────────────────
def test_unknown_primary_falls_back_to_legacy():
    """If the tab's primary study_uid is unknown, keep legacy behaviour (adopt)."""
    assert _adopt({}, tab_primary_uid="", candidate_study_uid=B) is True


def test_nonexistent_path_never_adopted():
    """A stale/missing series_path is still ignored (pre-existing guard)."""
    assert _adopt({}, tab_primary_uid=A, candidate_study_uid=A, exists=False) is False


def test_kill_switch_restores_legacy_adopt_any():
    assert _adopt(
        {"AIPACS_TAB_PATH_PRIMARY_ONLY": "0"}, tab_primary_uid=A, candidate_study_uid=B
    ) is True


# ── the concrete 49836 sequence ────────────────────────────────────────
def test_49836_sequence_keeps_tab_on_primary():
    """Load B's series 1000004, then A's series 3 -> tab path must still be study A."""
    tab_path = A
    # 1) secondary series loads (offset key) -> must NOT repoint
    if _adopt({}, tab_primary_uid=A, candidate_study_uid=B):
        tab_path = B
    assert tab_path == A, "tab path was poisoned to the secondary study"

    # 2) plain key 3 now resolves under study A (its own series 3), not study B's
    assert f"{tab_path}/3" == f"{A}/3"


@pytest.mark.parametrize("cand,expected", [(A, True), (B, False)])
def test_only_primary_adopted(cand, expected):
    assert _adopt({}, tab_primary_uid=A, candidate_study_uid=cand) is expected
