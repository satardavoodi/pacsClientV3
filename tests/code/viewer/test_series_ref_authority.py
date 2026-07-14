"""OPT-35 — SeriesRef: the ONE series-identity authority.

Pins the pure authority (`PacsClient/utils/series_ref.py`) against:

  * the three live bugs it exists to make STRUCTURALLY IMPOSSIBLE —
      48912/29694  a PRIMARY series loading a PREVIOUS exam's folder,
      49836        a secondary load repointing the TAB path, so a primary series
                   with a COLLIDING number resolved to the wrong study's folder,
      50238        a primary series reading the SECONDARY study's DB rows;
  * every PRIOR CORRECTION a fresh identity layer could silently undo (C1-C11 of
    docs/plans/architecture/SERIES_IDENTITY_PIPELINE_UNIFICATION_2026-07-14.md);
  * single-study byte-identity (the ref must NEVER redirect a single-study tab).

Pure: stdlib only, no Qt/VTK/pydicom/DB — runs offscreen.
"""

import ast
import os
from pathlib import PurePath

import pytest


def _same_path(a, b) -> bool:
    """Separator-agnostic path compare (PurePath treats '/' and '\\' alike on Windows)."""
    return PurePath(str(a)) == PurePath(str(b))

from PacsClient.utils.series_ref import (
    MULTISTUDY_OFFSET,
    SeriesRef,
    build_series_ref_table,
    is_offset_key,
    parse_series_number,
    resolve_series_ref,
    shadow_compare,
)

SRC = "/src"          # stand-in for SOURCE_PATH
PRIMARY = "STUDY1"    # the tab's primary study
SECOND = "STUDY2"     # a sibling / previous exam
THIRD = "STUDY3"

PRIMARY_PK = 1974
SECOND_PK = 1975


def _entry(study_uid, orig, slot, series_uid=None, **extra):
    """A `_server_series_info` entry exactly as _rebuild_multistudy_series_index stamps it."""
    key = str(int(orig) + (0 if slot == 0 else slot * MULTISTUDY_OFFSET))
    e = {
        "series_number": key,
        "_orig_series_number": str(orig),
        "_study_slot": slot,
        "study_uid": study_uid,
        "series_path": f"{SRC}/{study_uid}/{orig}",
    }
    if series_uid:
        e["series_uid"] = series_uid
    e.update(extra)
    return key, e


def _50238_info():
    """Patient 50238: study 1 AND study 2 both have series 2/3/4 (colliding numbers)."""
    info = {}
    for n in (2, 3, 4):
        k, e = _entry(PRIMARY, n, 0, series_uid=f"1.2.{n}.PRIMARY")
        info[k] = e
    for n in (2, 3, 4):
        k, e = _entry(SECOND, n, 1, series_uid=f"1.2.{n}.SECOND")
        info[k] = e
    return info


def _table(info=None, primary=PRIMARY):
    return build_series_ref_table(info if info is not None else _50238_info(), primary, SRC)


def _resolve(key, info=None, primary=PRIMARY, studies=None, slot_order=None, table=None):
    info = _50238_info() if info is None else info
    return resolve_series_ref(
        key,
        _table(info, primary) if table is None else table,
        server_series_info=info,
        primary_study_uid=primary,
        source_root=SRC,
        studies_index=studies,
        slot_order=slot_order,
    )


# ══════════════════════════════════════════════════════════════════════════
# The three live bugs — now impossible by construction
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("n", [2, 3, 4])
def test_50238_plain_key_resolves_to_the_PRIMARY_study(n):
    """A PLAIN key belongs to the PRIMARY study — its pk and folder are study 1's.

    This is the whole 50238 fix: `study_pk = pk_of(ref.study_uid)` and a plain key's
    entry carries study_uid == primary, so it can never inherit the sibling's pk.
    """
    ref = _resolve(n)
    assert ref.study_uid == PRIMARY
    assert ref.is_primary and ref.study_slot == 0
    assert ref.series_number == str(n)
    assert _same_path(ref.study_path, f"{SRC}/{PRIMARY}")
    assert ref.series_uid == f"1.2.{n}.PRIMARY"


@pytest.mark.parametrize("n", [2, 3, 4])
def test_50238_offset_key_resolves_to_ITS_OWN_secondary_study(n):
    """C8 (the OTHER polarity): a SECONDARY series must keep its OWN study — 48101."""
    ref = _resolve(MULTISTUDY_OFFSET + n)
    assert ref.study_uid == SECOND
    assert not ref.is_primary and ref.study_slot == 1
    assert ref.series_number == str(n)          # its OWN (original) number, not the key
    assert _same_path(ref.study_path, f"{SRC}/{SECOND}")
    assert ref.series_uid == f"1.2.{n}.SECOND"


def test_the_one_pk_rule_serves_BOTH_polarities():
    """`study_pk = pk_of(ref.study_uid)` replaces the two OPPOSING legacy guards."""
    pk_of = {PRIMARY: PRIMARY_PK, SECOND: SECOND_PK}.get
    assert pk_of(_resolve(3).study_uid) == PRIMARY_PK                     # 50238
    assert pk_of(_resolve(MULTISTUDY_OFFSET + 3).study_uid) == SECOND_PK  # 48101


def test_50238_sequence_no_tab_state_can_poison_the_next_load():
    """Load study 2's series, THEN study 1's: the ref is unchanged — it reads no tab state."""
    before = _resolve(3)
    _ = _resolve(MULTISTUDY_OFFSET + 3)   # the secondary load that used to poison the tab
    after = _resolve(3)
    assert after == before                # frozen + derived from the entry, not the tab
    assert after.study_uid == PRIMARY


def test_49836_primary_and_secondary_same_number_never_share_a_folder():
    """The 49836 defect: study B's folder being handed to study A's series 3."""
    a, b = _resolve(3), _resolve(MULTISTUDY_OFFSET + 3)
    assert not _same_path(a.series_path, b.series_path)
    assert _same_path(a.series_path, f"{SRC}/{PRIMARY}/3")
    assert _same_path(b.series_path, f"{SRC}/{SECOND}/3")
    assert a.series_uid != b.series_uid    # the identity the render gate keys on


def test_48912_plain_key_never_resolves_into_a_previous_exam():
    info = _50238_info()
    for n in (1, 2):                       # a third study (previous exam) joins
        k, e = _entry(THIRD, n, 2, series_uid=f"1.2.{n}.THIRD")
        info[k] = e
    for n in (2, 3, 4):
        assert _resolve(n, info).study_uid == PRIMARY


# ══════════════════════════════════════════════════════════════════════════
# C1 — NEVER int() a server field  (OPT-25 / Roshana: int("None") killed a study)
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad", ["None", "null", "", "  ", None, "abc", float("nan")])
def test_C1_parse_series_number_never_raises_on_junk(bad):
    assert parse_series_number(bad) is None      # returns None; does NOT raise


def test_C1_resolver_survives_a_literal_None_series_number():
    """The exact Roshana payload shape must not raise out of the identity layer."""
    assert _resolve("None") is None              # unusable key -> None, no exception
    assert is_offset_key("None") is False


def test_C1_no_bare_int_cast_on_a_series_field_in_the_module():
    """Source pin: the authority must not reintroduce a bare int() on a series value."""
    import PacsClient.utils.series_ref as m
    src = open(m.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "int" and node.args):
            arg = node.args[0]
            # int(text) inside parse_series_number's try/except is the ONE sanctioned cast;
            # every other int() must be on a slot/int-typed value, never a raw series field.
            src_seg = ast.get_source_segment(src, arg) or ""
            assert "series" not in src_seg.lower() or "text" in src_seg, (
                f"bare int() on a series field: int({src_seg})"
            )


# ══════════════════════════════════════════════════════════════════════════
# C2 — the synthetic reserved band stays a PLAIN key
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("n", [900001, 950000, 999999])
def test_C2_synthetic_band_is_below_the_offset_threshold_and_stays_primary(n):
    assert n < MULTISTUDY_OFFSET
    assert is_offset_key(n) is False
    info = dict(_50238_info())
    k, e = _entry(PRIMARY, n, 0, series_uid="1.2.SYNTH")
    info[k] = e
    ref = _resolve(n, info)
    assert ref.study_uid == PRIMARY and ref.is_primary
    assert ref.series_number == str(n)


def test_C2_offset_threshold_boundary():
    assert is_offset_key(999_999) is False
    assert is_offset_key(1_000_000) is True


# ══════════════════════════════════════════════════════════════════════════
# C3 — healthy data byte-identical, INCLUDING type ("02" stays "02")
# ══════════════════════════════════════════════════════════════════════════
def test_C3_zero_padded_series_number_text_is_preserved():
    info = {}
    k, e = _entry(PRIMARY, "02", 0)
    e["_orig_series_number"] = "02"          # as stamped, not normalised
    e["series_path"] = f"{SRC}/{PRIMARY}/02"
    info["2"] = e
    ref = resolve_series_ref(
        "2", None, server_series_info=info, primary_study_uid=PRIMARY, source_root=SRC,
    )
    assert ref.series_number == "02"         # NOT 2 — folder/thumbnail naming depends on it
    assert PurePath(ref.series_path).name == "02"


# ══════════════════════════════════════════════════════════════════════════
# C10/C11 — the display key stays a DIGIT string (ZetaBoost warmup hard-requires it)
# ══════════════════════════════════════════════════════════════════════════
def test_C10_display_key_is_always_a_digit_string():
    for ref in _table().values():
        assert ref.display_key.isdigit(), f"non-digit display key {ref.display_key!r}"
        assert int(ref.display_key) >= 0


def test_C11_offset_key_scheme_is_unchanged():
    ref = _resolve(MULTISTUDY_OFFSET + 4)
    assert int(ref.display_key) == ref.study_slot * MULTISTUDY_OFFSET + int(ref.series_number)


# ══════════════════════════════════════════════════════════════════════════
# Single-study byte-identity + the imported-study hazard
# ══════════════════════════════════════════════════════════════════════════
def test_single_study_entries_produce_a_NON_authoritative_ref():
    """A single-study tab's entries carry no _orig_series_number -> 'derived' -> never acted on.

    Its path is INFERRED as SOURCE_PATH/<primary>/<key>, which is WRONG for an externally
    IMPORTED study living outside SOURCE_PATH. Acting on it would break import; the caller
    is required to check `is_authoritative`.
    """
    info = {"1": {"series_number": "1"}, "2": {"series_number": "2"}}
    assert build_series_ref_table(info, PRIMARY, SRC) == {}      # nothing authoritative
    ref = _resolve(1, info)
    assert ref is not None
    assert ref.source == "derived"
    assert ref.is_authoritative is False                          # MUST NOT redirect the path
    assert ref.study_uid == PRIMARY                               # identity still usable


def test_multistudy_entries_ARE_authoritative():
    for ref in _table().values():
        assert ref.source == "entry"
        assert ref.is_authoritative is True


# ══════════════════════════════════════════════════════════════════════════
# The offset-key slot fallback (entry dropped by a later rebuild)
# ══════════════════════════════════════════════════════════════════════════
def test_slot_fallback_resolves_an_offset_key_whose_entry_was_dropped():
    studies = {PRIMARY: [], SECOND: [], THIRD: []}
    order = [PRIMARY, SECOND, THIRD]
    ref = resolve_series_ref(
        2 * MULTISTUDY_OFFSET + 7, {},                # empty table AND no entry
        server_series_info={},
        primary_study_uid=PRIMARY, source_root=SRC,
        studies_index=studies, slot_order=order,
    )
    assert ref.source == "slot_fallback"
    assert ref.is_authoritative is True
    assert ref.study_uid == THIRD                      # slot 2
    assert ref.series_number == "7"
    assert _same_path(ref.series_path, f"{SRC}/{THIRD}/7")


def test_slot_out_of_range_refuses_to_guess_and_NEVER_falls_back_to_primary():
    """Falling back to the primary study here is exactly how a wrong study got loaded."""
    ref = resolve_series_ref(
        9 * MULTISTUDY_OFFSET + 1, {},
        server_series_info={},
        primary_study_uid=PRIMARY, source_root=SRC,
        studies_index={PRIMARY: [], SECOND: []}, slot_order=[PRIMARY, SECOND],
    )
    assert ref is None                                 # refuse, do not guess


def test_stable_slot_order_is_honoured_so_a_key_cannot_change_study():
    """A merged previous exam must not shift an existing study's slot (and its keys)."""
    studies = {PRIMARY: [], "AAA_EARLIER": [], SECOND: []}
    order = [PRIMARY, SECOND, "AAA_EARLIER"]           # SECOND keeps slot 1 despite sorting late
    ref = resolve_series_ref(
        MULTISTUDY_OFFSET + 3, {}, server_series_info={},
        primary_study_uid=PRIMARY, source_root=SRC,
        studies_index=studies, slot_order=order,
    )
    assert ref.study_uid == SECOND


# ══════════════════════════════════════════════════════════════════════════
# Immutability + the shadow oracle
# ══════════════════════════════════════════════════════════════════════════
def test_ref_is_frozen_and_with_study_pk_returns_a_copy():
    ref = _resolve(3)
    with pytest.raises(Exception):
        ref.study_uid = "HACKED"                       # frozen: identity cannot drift
    withpk = ref.with_study_pk(PRIMARY_PK)
    assert withpk.study_pk == PRIMARY_PK
    assert ref.study_pk is None                        # original untouched
    assert withpk.study_uid == ref.study_uid


def test_shadow_detects_the_50238_pk_poisoning():
    ref = _resolve(3).with_study_pk(PRIMARY_PK)
    out = shadow_compare(ref, legacy_study_pk=SECOND_PK)   # tab state carried the sibling's pk
    assert out["mismatch"] and "study_pk" in out["fields"]


def test_shadow_detects_the_49836_path_poisoning():
    ref = _resolve(3)
    out = shadow_compare(ref, legacy_study_path=f"{SRC}/{SECOND}")  # tab repointed to study B
    assert out["mismatch"] and "study_path" in out["fields"]


def test_shadow_is_silent_when_legacy_and_authority_agree():
    ref = _resolve(3).with_study_pk(PRIMARY_PK)
    out = shadow_compare(
        ref, legacy_study_path=f"{SRC}/{PRIMARY}",
        legacy_series_number="3", legacy_study_pk=PRIMARY_PK,
    )
    assert out["mismatch"] is False and out["fields"] == []


def test_shadow_never_raises_and_a_missing_ref_is_not_a_mismatch():
    assert shadow_compare(None, legacy_study_path="/x")["mismatch"] is False
    assert shadow_compare(_resolve(3), legacy_study_path=None)["mismatch"] is False


# ══════════════════════════════════════════════════════════════════════════
# Wiring pins — the authority must actually be consumed in the load path
# ══════════════════════════════════════════════════════════════════════════
def _vc_load_src():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    path = os.path.join(
        root, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "_vc_load.py"
    )
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_wiring_flags_default_on_with_kill_switches():
    src = _vc_load_src()
    for flag in ("AIPACS_SERIESREF_SHADOW", "AIPACS_SERIESREF_DISK", "AIPACS_SERIESREF_DB"):
        assert flag in src, f"{flag} missing"
        # default-ON: the user evaluates on the routine build, so a dark flag is useless
        assert f'os.getenv("{flag}", "1")' in src, f"{flag} must default to ON"


def test_wiring_load_path_resolves_and_consumes_the_ref():
    src = _vc_load_src()
    assert "_series_ref = self._resolve_series_ref(series_key)" in src
    assert "_log_seriesref_shadow" in src
    assert "_SERIESREF_DISK and _series_ref is not None and _series_ref.is_authoritative" in src
    assert "_SERIESREF_DB" in src


def test_wiring_pk_comes_from_the_refs_own_study_uid_not_tab_state():
    """THE rule. If this pin fails, the 50238/48101 collapse has been undone."""
    src = _vc_load_src()
    assert "self._study_pk_for_uid(_series_ref.study_uid)" in src


def test_wiring_legacy_guards_stay_on_as_detectors():
    """The guards are the production regression detector — they must NOT be deleted yet."""
    src = _vc_load_src()
    assert "[STUDY-PK-GUARD]" in src
    assert "AIPACS_MULTISTUDY_PER_SERIES_STUDY_PK" in src
    assert "resolve_entry_study_location" in src
