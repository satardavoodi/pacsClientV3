"""Q3 — PROPERTY-BASED fuzz of the series-number ingestion boundary (hypothesis).

`modules/network/series_identity.py` is the ONE choke point where every server-provided series
number is normalized (OPT-25, Roshana). The outage it fixed was a single malformed value —
the literal string ``"None"`` — reaching ``int(...)`` and aborting a whole study's metadata fetch.
Example tests pin the specific values we already know about; this fuzzes the boundary with
*arbitrary* inputs so the NEXT malformed value a PACS device invents cannot slip through.

The roadmap (§3-L3) named this exact test: "generate arbitrary server payloads ... assert
`parse_series_number` never raises, `normalize_series_entries` never collides, synthetic numbers
stay in-band. This finds OPT-25 in seconds."

Invariants proven over generated inputs:
  P1  parse_series_number NEVER raises, and returns None or an int (never a str/float/bool).
  P2  normalize_series_entries NEVER raises (a normalizer must never break a fetch that would
      otherwise succeed) and returns a non-negative repaired-count.
  P3  after normalization EVERY series carries a USABLE number (parse_series_number != None) —
      i.e. no downstream consumer can ever see a non-numeric series number (the OPT-25 guarantee).
  P4  synthetic numbers are in the reserved band [900001, 999999] and STRICTLY BELOW the
      1_000_000 multi-study offset-key threshold (C2 — a synthetic can never look like an offset key).
  P5  no collisions — a synthetic number never equals another series' number (real or synthetic)
      in the same list.
  P6  BYTE-IDENTICAL for healthy data (C3) — a series whose number already parses is not touched
      at all (same value, same type; no synthetic keys added).
  P7  DETERMINISTIC — the same payload normalizes to the same result every time (so the UI process
      and the download subprocess agree on disk/thumbnail/DB naming).

Pure: stdlib + hypothesis. Marked `property` (own lane).
"""

import copy

import pytest

pytest.importorskip("hypothesis")

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from modules.network import series_identity as si

OFFSET_THRESHOLD = 1_000_000


# ── strategies: every shape a PACS server might put in `series_number` ──────
# Deliberately includes the OPT-25 killer ("None"), the usual "absent" spellings, zero-padded
# numbers, floats-as-text, bytes, booleans, huge/negative ints, NaN/inf, and unicode junk.
series_number_values = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10 ** 9), max_value=10 ** 9),
    st.floats(allow_nan=True, allow_infinity=True, width=32),
    st.sampled_from(["None", "null", "nil", "NaN", "N/A", "", "  ", "-", "unknown", "undefined"]),
    st.sampled_from(["0", "1", "3", "03", "007", "3.0", "12", "999", "900001", "1000001"]),
    st.text(max_size=8),
    st.binary(max_size=6),
)


@st.composite
def series_entry(draw):
    entry = {"series_number": draw(series_number_values)}
    if draw(st.booleans()):
        entry["series_uid"] = draw(st.text(min_size=0, max_size=10))
    if draw(st.booleans()):
        entry["modality"] = draw(st.sampled_from(["DX", "CR", "CT", "MR", "US", "OT"]))
    return entry


series_list = st.lists(series_entry(), max_size=25)

# The payload wrapper: bare list, or a dict under either recognised key, or noise.
payloads = st.one_of(
    series_list,
    series_list.map(lambda lst: {"series_thumbnails": lst}),
    series_list.map(lambda lst: {"series": lst}),
    series_list.map(lambda lst: {"patient_id": "P", "series": lst, "unrelated": 1}),
)


# ── P1: the tolerant parser never raises ───────────────────────────────────
@settings(max_examples=400)
@given(value=series_number_values)
def test_P1_parse_never_raises_and_returns_int_or_none(value):
    result = si.parse_series_number(value)
    assert result is None or (isinstance(result, int) and not isinstance(result, bool))


def test_P1_the_exact_OPT25_value():
    # The literal string that took down a whole study. Must be None, never a raise.
    assert si.parse_series_number("None") is None
    assert si.parse_series_number("none") is None


# ── P2-P7: the in-place normalizer ─────────────────────────────────────────
def _entries(payload):
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]
    out = []
    for key in ("series_thumbnails", "series"):
        v = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(v, list):
            out += [e for e in v if isinstance(e, dict)]
    return out


@settings(max_examples=300, deadline=None)
@given(payload=payloads)
def test_normalize_boundary_invariants(payload):
    original = copy.deepcopy(payload)
    before = _entries(original)
    # remember which entries were ALREADY usable, and their exact value+type (for P6).
    already_ok = []
    for i, e in enumerate(before):
        p = si.parse_series_number(e.get("series_number"))
        if p is not None:
            already_ok.append((i, e.get("series_number"), type(e.get("series_number"))))

    # P2: never raises; returns a non-negative int.
    repaired = si.normalize_series_entries(payload)
    assert isinstance(repaired, int) and repaired >= 0

    after = _entries(payload)

    for i, e in enumerate(after):
        num = e.get("series_number")
        # P3: every series now carries a USABLE number (unless the reserved band was exhausted,
        # which needs >99_999 unnumbered series — impossible for these list sizes).
        assert si.parse_series_number(num) is not None, f"entry {i} still unusable: {num!r}"

        if e.get("series_number_synthetic"):
            # P4: synthetic numbers are in-band and below the offset threshold.
            assert isinstance(num, int)
            assert si.SYNTHETIC_SERIES_NUMBER_BASE < num <= si.SYNTHETIC_SERIES_NUMBER_MAX
            assert num < OFFSET_THRESHOLD
            # the raw value the server sent is preserved for diagnostics.
            assert "series_number_raw" in e

    # P5: normalize must not INTRODUCE a collision. It deliberately leaves valid numbers untouched
    # (P6/C3), so if the SERVER sent two series with the same real number that duplicate survives —
    # that is a server data-quality issue, out of scope for the missing-number normalizer (see the
    # dedicated test below). What the normalizer guarantees: every SYNTHETIC number is unique and
    # avoids every other number, so the set of duplicated numbers after == the set that was already
    # duplicated among the parseable INPUT (normalize adds none).
    def _dupes(values):
        vals = [v for v in values if v is not None]
        return {v for v in vals if vals.count(v) > 1}

    input_real = [si.parse_series_number(e.get("series_number")) for e in before]
    after_nums = [si.parse_series_number(e.get("series_number")) for e in after]
    assert _dupes(after_nums) <= _dupes(input_real), (
        f"normalize INTRODUCED a collision: after={_dupes(after_nums)} input={_dupes(input_real)}"
    )
    # And no SYNTHETIC number is ever part of a collision.
    synth_nums = [e.get("series_number") for e in after if e.get("series_number_synthetic")]
    non_synth = [si.parse_series_number(e.get("series_number")) for e in after
                 if not e.get("series_number_synthetic")]
    for s in synth_nums:
        assert after_nums.count(s) == 1, f"synthetic {s} collided"
        assert s not in non_synth, f"synthetic {s} collided with a real number"

    # P6: byte-identical for already-healthy entries — untouched value, type, and no synthetic keys.
    for i, orig_val, orig_type in already_ok:
        e = after[i]
        assert e.get("series_number") == orig_val and type(e.get("series_number")) is orig_type
        assert "series_number_synthetic" not in e
        assert "series_number_raw" not in e

    # P7: deterministic — a second, independent normalize of the ORIGINAL yields the same result.
    payload2 = copy.deepcopy(original)
    si.normalize_series_entries(payload2)
    assert _entries(payload2) == after


@settings(max_examples=100, deadline=None)
@given(n_missing=st.integers(min_value=1, max_value=15),
       real=st.lists(st.integers(min_value=1, max_value=50), max_size=8, unique=True))
def test_synthetic_numbers_never_collide_with_present_real_numbers(n_missing, real):
    # A study with some real-numbered series and some missing ones: the synthetic numbers must
    # avoid the real ones (even if a real one happened to be in the 9xxxxx band).
    lst = [{"series_number": r, "series_uid": f"real-{r}"} for r in real]
    lst += [{"series_number": "None", "series_uid": f"missing-{i}"} for i in range(n_missing)]
    si.normalize_series_entries(lst)
    nums = sorted(si.parse_series_number(e["series_number"]) for e in lst)
    assert len(nums) == len(set(nums)), "synthetic collided with a real number"
    synth = [e["series_number"] for e in lst if e.get("series_number_synthetic")]
    assert all(n not in set(real) for n in synth)


def test_duplicate_REAL_numbers_from_server_are_preserved_not_deduped():
    """DOCUMENTED behaviour + a flagged limitation (found by the property fuzz, 2026-07-14).

    The normalizer fixes MISSING numbers; it deliberately does NOT touch valid ones (byte-identity,
    C3). So if a server sends two series with the SAME real SeriesNumber within one study, both are
    kept — the normalizer does not deduplicate them. This is a distinct concern from OPT-25 (a
    server data-quality issue), and it could feed the same folder/offset-key collision class as the
    multi-study bugs (`SOURCE_PATH/<study>/<number>/`). Captured here so the behaviour is explicit;
    fixing it (if servers ever emit duplicate real numbers) is a separate follow-up, NOT a silent
    regression of this test.
    """
    lst = [{"series_number": 3, "series_uid": "a"}, {"series_number": 3, "series_uid": "b"}]
    assert si.normalize_series_entries(lst) == 0        # nothing missing -> nothing repaired
    assert [e["series_number"] for e in lst] == [3, 3]  # duplicate preserved, not deduped


def test_kill_switch_restores_passthrough(monkeypatch):
    monkeypatch.setenv("AIPACS_SERIES_NUMBER_NORMALIZE", "0")
    lst = [{"series_number": "None", "series_uid": "x"}]
    assert si.normalize_series_entries(lst) == 0
    assert lst[0]["series_number"] == "None"     # legacy passthrough — untouched


pytestmark = pytest.mark.property
