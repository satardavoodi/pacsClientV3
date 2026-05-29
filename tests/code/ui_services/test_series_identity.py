from PacsClient.utils.series_identity import (
    get_series_number,
    get_series_uid,
    resolve_series_identifier,
)


def test_get_series_helpers_normalize_known_fields():
    info = {
        "series_number": 201,
        "series_instance_uid": "uid-201",
    }

    assert get_series_number(info) == "201"
    assert get_series_uid(info) == "uid-201"


def test_resolve_series_identifier_prefers_known_series_number_key():
    assert resolve_series_identifier(
        "201",
        known_series_numbers={"201", "202"},
        uid_to_number_map={"uid-201": "201"},
    ) == "201"


def test_resolve_series_identifier_uses_uid_map_before_series_info_scan():
    assert resolve_series_identifier(
        "uid-201",
        uid_to_number_map={"uid-201": "201"},
        series_info_map={
            "202": {"series_uid": "uid-201"},
        },
    ) == "201"


def test_resolve_series_identifier_scans_series_info_map_when_needed():
    assert resolve_series_identifier(
        "uid-203",
        series_info_map={
            "203": {"series_instance_uid": "uid-203"},
        },
    ) == "203"


def test_resolve_series_identifier_returns_original_key_when_unknown():
    assert resolve_series_identifier("unknown-series") == "unknown-series"