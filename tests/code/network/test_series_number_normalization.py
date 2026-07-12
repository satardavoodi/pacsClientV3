"""Guard: a device with no SeriesNumber must not break a study.

Root cause (Roshana center, 2026-07-12): a radiography device wrote DICOM with
no usable SeriesNumber (0020,0011). The server serialized it as the literal
string "None", and the download manager's socket metadata builder did

    int(str(series.get("series_number") or 0))   # int("None") -> ValueError

"None" is a truthy string, so `or 0` never fired. The ValueError aborted the
WHOLE study's metadata fetch -> "Failed to fetch metadata" -> the study never
downloaded -> the radiography images could never be displayed.

These tests pin the fix and, just as importantly, pin that healthy studies are
completely untouched (no regression at any other center).
"""

import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.network.series_identity import (  # noqa: E402
    SYNTHETIC_SERIES_NUMBER_BASE,
    normalize_series_entries,
    parse_series_number,
)


# --------------------------------------------------------------------------
# 1. The exact production failure
# --------------------------------------------------------------------------

def test_legacy_expression_is_the_bug():
    """Pin the original defect: `or 0` does not protect against the string 'None'."""
    value = "None"
    assert value or 0  # truthy -> the `or 0` guard never fires
    with pytest.raises(ValueError):
        int(str(value or 0))


def test_parse_series_number_rejects_the_none_string():
    assert parse_series_number("None") is None
    assert parse_series_number(None) is None
    assert parse_series_number("") is None
    assert parse_series_number("null") is None
    assert parse_series_number("N/A") is None
    assert parse_series_number("  ") is None
    assert parse_series_number("not-a-number") is None
    assert parse_series_number(True) is None  # bool is not a series number


def test_parse_series_number_accepts_every_real_spelling():
    assert parse_series_number(3) == 3
    assert parse_series_number("3") == 3
    assert parse_series_number("03") == 3
    assert parse_series_number(" 3 ") == 3
    assert parse_series_number("3.0") == 3
    assert parse_series_number(3.0) == 3
    assert parse_series_number(b"3") == 3
    assert parse_series_number(0) == 0


# --------------------------------------------------------------------------
# 2. No regression: a healthy payload is byte-identical
# --------------------------------------------------------------------------

def test_healthy_payload_is_left_completely_untouched():
    """The overwhelmingly common case: every center with conformant devices."""
    payload = {
        "series_thumbnails": [
            {"series_uid": "1.2.3.1", "series_number": "1", "modality": "CT"},
            {"series_uid": "1.2.3.2", "series_number": "02", "modality": "CT"},
            {"series_uid": "1.2.3.3", "series_number": 3, "modality": "CT"},
        ]
    }
    before = [dict(s) for s in payload["series_thumbnails"]]

    repaired = normalize_series_entries(payload)

    assert repaired == 0
    # Same values AND same types — "02" must not silently become 2, or the
    # thumbnail/folder naming for existing studies would shift.
    assert payload["series_thumbnails"] == before
    assert payload["series_thumbnails"][1]["series_number"] == "02"
    assert isinstance(payload["series_thumbnails"][2]["series_number"], int)
    # No diagnostic keys added to healthy entries.
    for series in payload["series_thumbnails"]:
        assert "series_number_synthetic" not in series
        assert "series_number_raw" not in series


# --------------------------------------------------------------------------
# 3. The fix
# --------------------------------------------------------------------------

def test_unusable_series_number_gets_a_synthetic_number():
    payload = {
        "series_thumbnails": [
            {"series_uid": "1.2.3.1", "series_number": "1"},
            {"series_uid": "1.2.3.2", "series_number": "None"},  # the outage
            {"series_uid": "1.2.3.3", "series_number": None},
        ]
    }

    repaired = normalize_series_entries(payload)
    assert repaired == 2

    numbers = [s["series_number"] for s in payload["series_thumbnails"]]
    assert numbers[0] == "1"  # untouched
    for value in numbers[1:]:
        assert isinstance(value, int)
        assert value > SYNTHETIC_SERIES_NUMBER_BASE

    # Every series now parses — no consumer can hit int("None") again.
    for series in payload["series_thumbnails"]:
        assert parse_series_number(series["series_number"]) is not None

    # The raw server value is preserved for diagnosis.
    assert payload["series_thumbnails"][1]["series_number_raw"] == "None"
    assert payload["series_thumbnails"][1]["series_number_synthetic"] is True


def test_synthetic_numbers_never_collide_with_real_ones():
    payload = {
        "series_thumbnails": [
            {"series_uid": "a", "series_number": "None"},
            {"series_uid": "b", "series_number": "None"},
            {"series_uid": "c", "series_number": "None"},
            # A (bizarre but legal) real series number inside the reserved band.
            {"series_uid": "d", "series_number": SYNTHETIC_SERIES_NUMBER_BASE + 1},
        ]
    }
    normalize_series_entries(payload)

    numbers = [parse_series_number(s["series_number"]) for s in payload["series_thumbnails"]]
    assert len(set(numbers)) == len(numbers), "series numbers must stay unique within a study"


def test_synthetic_numbers_stay_below_the_multistudy_offset_threshold():
    """Offset keys are `study_slot * 1_000_000 + series_number` — a synthetic
    number must never be mistaken for one (see _vc_cache.py: >= 1_000_000)."""
    payload = {"series_thumbnails": [{"series_uid": f"u{i}", "series_number": "None"}
                                     for i in range(50)]}
    normalize_series_entries(payload)
    for series in payload["series_thumbnails"]:
        number = parse_series_number(series["series_number"])
        assert SYNTHETIC_SERIES_NUMBER_BASE < number < 1_000_000


def test_assignment_is_deterministic_across_fetches_and_processes():
    """The UI and the download subprocess each fetch independently. They must
    agree, or the on-disk folder / thumbnail / DB row would diverge. Server list
    ORDER must not matter — only series_uid."""
    def build(order):
        return {"series_thumbnails": [{"series_uid": uid, "series_number": "None"}
                                      for uid in order]}

    a = build(["1.2.3.9", "1.2.3.1", "1.2.3.5"])
    b = build(["1.2.3.1", "1.2.3.5", "1.2.3.9"])  # same series, different order
    normalize_series_entries(a)
    normalize_series_entries(b)

    map_a = {s["series_uid"]: s["series_number"] for s in a["series_thumbnails"]}
    map_b = {s["series_uid"]: s["series_number"] for s in b["series_thumbnails"]}
    assert map_a == map_b


def test_mixed_study_only_repairs_the_broken_series():
    """The live Roshana study: 3 series, only one missing its number."""
    payload = {
        "series_thumbnails": [
            {"series_uid": "a", "series_number": "1"},
            {"series_uid": "b", "series_number": "None"},
            {"series_uid": "c", "series_number": "2"},
        ]
    }
    assert normalize_series_entries(payload) == 1
    assert payload["series_thumbnails"][0]["series_number"] == "1"
    assert payload["series_thumbnails"][2]["series_number"] == "2"


def test_bare_list_payload_is_supported():
    series = [{"series_uid": "a", "series_number": "None"}]
    assert normalize_series_entries(series) == 1
    assert parse_series_number(series[0]["series_number"]) is not None


def test_normalizer_never_raises_on_garbage():
    for junk in (None, 42, "text", {}, {"series_thumbnails": None},
                 {"series_thumbnails": ["not-a-dict", None]}):
        assert normalize_series_entries(junk) == 0


def test_kill_switch_restores_legacy_passthrough(monkeypatch):
    monkeypatch.setenv("AIPACS_SERIES_NUMBER_NORMALIZE", "0")
    payload = {"series_thumbnails": [{"series_uid": "a", "series_number": "None"}]}
    assert normalize_series_entries(payload) == 0
    assert payload["series_thumbnails"][0]["series_number"] == "None"


# --------------------------------------------------------------------------
# 4. Wiring pins — the fix must stay at the single ingestion boundary
# --------------------------------------------------------------------------

def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")


def test_socket_client_normalizes_both_series_endpoints():
    src = _read("modules/network/socket_client.py")
    assert "from modules.network.series_identity import normalize_series_entries" in src
    assert src.count("_normalize_series_identity(") >= 4  # def + 3 call sites
    assert 'endpoint="GetStudyThumbnails"' in src
    assert 'endpoint="QuerySeriesThumbnails"' in src


def test_dm_metadata_builder_no_longer_has_the_fatal_cast():
    """The exact line that took the study down must never come back."""
    for rel in (
        "modules/download_manager/network/grpc_client.py",
        "builder/plugin package/packages/download_manager/payload/python/"
        "modules/download_manager/network/grpc_client.py",
    ):
        src = _read(rel)
        assert 'int(str(series.get("series_number") or 0))' not in src, rel
        assert "parse_series_number" in src, rel
        # The per-series loop must be guarded so one bad series cannot abort
        # the whole study's metadata.
        assert re.search(r"except Exception as exc:\s*\n\s*logger\.warning\(\s*\n\s*"
                         r'"⚠️ Skipping malformed series', src), rel


def test_home_db_service_uses_the_tolerant_parse():
    src = _read("PacsClient/pacs/workstation_ui/home_ui/home_db_service.py")
    assert "get_series_by_study_and_number(study_uid, int(series_number))" not in src
    assert "parse_series_number(series_number)" in src
