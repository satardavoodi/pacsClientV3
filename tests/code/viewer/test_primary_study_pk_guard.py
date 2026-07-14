"""Guard: a PRIMARY (plain-key) series must read DB metadata with the PRIMARY study_pk (50238).

Root cause (2026-07-14, patient 50238 — the DB-dimension twin of the 49836 tab
study_path poisoning):

`_effective_study_pk` (`_vc_load._load_single_series_on_demand`) defaults to
`parent_widget.metadata_fixed['study_pk']` — MUTABLE TAB STATE. A secondary-study
load can leave the tab carrying the SECONDARY study's pk. A later PRIMARY
(plain-key) load then asks the DB for "series N of study <SECONDARY>" and, when the
two studies share series NUMBERS, gets back the WRONG study's same-numbered series.

50238 (study 1 and study 2 BOTH have series 2/3/4):
    study 1 series 3 -> 90 images, SeriesUID …3882107555
    study 2 series 3 -> 30 images, SeriesUID …0005302607

Live log — bare key 3 fetched STUDY 2's series 3:
    [MULTI-STUDY LOAD] key=3 -> study_path=<study1>/3 (slot=0)     <- disk path CORRECT
    FAST:meta_cache key=series_15208_n30                            <- 30 images == study 2
    [IDENTITY-GATE] SKIP render: incoming series=3 uid=…0005302607
                    != intended uid=…3882107555

The identity gate correctly refused to paint the wrong study's images, so series 3
and 4 were BLANK on first open. Reopening "fixed" it only because the tab state was
rebuilt — the load was still wrong.

Fix (flag `AIPACS_PRIMARY_STUDY_PK_GUARD`, default on; `=0` = legacy inherit):
a plain (< 1_000_000) key ALWAYS belongs to the tab's PRIMARY study, so pin its
study_pk to the primary study_uid's own pk. Multi-study + plain-key only, so
single-study tabs and every secondary (offset-key) load are byte-identical.
"""

import pytest


PRIMARY_PK = 1974      # study 1
SECONDARY_PK = 1975    # study 2 (the pk that contaminated the tab state)


def _guard(env, series_key, multistudy, primary_uid, effective_pk, primary_pk=PRIMARY_PK):
    """Mirrors the STUDY-PK-GUARD decision in _load_single_series_on_demand."""
    if (env.get("AIPACS_PRIMARY_STUDY_PK_GUARD", "1") or "1").strip() == "0":
        return effective_pk                      # kill switch -> legacy
    try:
        is_plain = int(str(series_key)) < 1_000_000
    except Exception:
        is_plain = False
    if is_plain and multistudy and primary_uid and primary_pk \
            and str(primary_pk) != str(effective_pk):
        return primary_pk                        # pin to the PRIMARY study
    return effective_pk                          # fail-open / untouched


# ── the 50238 bug ──────────────────────────────────────────────────────
@pytest.mark.parametrize("key", [2, 3, 4])
def test_plain_key_pinned_to_primary_after_secondary_contaminated_tab(key):
    """bare keys 2/3/4 must read the PRIMARY study's rows, not the secondary's."""
    assert _guard({}, key, True, "STUDY1", SECONDARY_PK) == PRIMARY_PK


def test_plain_key_unchanged_when_already_primary():
    assert _guard({}, 3, True, "STUDY1", PRIMARY_PK) == PRIMARY_PK


# ── the secondary path must NOT regress (48101 fix stays intact) ───────
@pytest.mark.parametrize("key", [1000002, 1000003, 1000004])
def test_offset_key_keeps_its_own_secondary_study_pk(key):
    """A secondary (offset-key) series must still load with ITS OWN study_pk."""
    assert _guard({}, key, True, "STUDY1", SECONDARY_PK) == SECONDARY_PK


# ── byte-identical / fail-open / kill switch ──────────────────────────
def test_single_study_tab_is_byte_identical():
    assert _guard({}, 3, False, "STUDY1", SECONDARY_PK) == SECONDARY_PK


def test_unknown_primary_uid_fails_open():
    assert _guard({}, 3, True, "", SECONDARY_PK) == SECONDARY_PK


def test_unresolvable_primary_pk_fails_open():
    assert _guard({}, 3, True, "STUDY1", SECONDARY_PK, primary_pk=None) == SECONDARY_PK


def test_kill_switch_restores_legacy_inherit():
    assert _guard(
        {"AIPACS_PRIMARY_STUDY_PK_GUARD": "0"}, 3, True, "STUDY1", SECONDARY_PK
    ) == SECONDARY_PK


# ── the concrete 50238 sequence ────────────────────────────────────────
def test_50238_sequence():
    """Load study 2's series (offset keys) -> tab pk contaminated -> then bare key 3."""
    tab_pk = PRIMARY_PK
    # 1) secondary series load legitimately uses study 2's pk...
    assert _guard({}, 1000004, True, "STUDY1", SECONDARY_PK) == SECONDARY_PK
    tab_pk = SECONDARY_PK          # ...and leaves the tab carrying it (the defect)

    # 2) now a PRIMARY series: must still read study 1's rows
    assert _guard({}, 3, True, "STUDY1", tab_pk) == PRIMARY_PK
    assert _guard({}, 4, True, "STUDY1", tab_pk) == PRIMARY_PK
