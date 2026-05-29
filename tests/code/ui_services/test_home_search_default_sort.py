from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService


def test_default_sort_orders_by_study_date_then_time_ascending():
    studies = [
        {"study_uid": "s3", "study_date": "20250102", "study_time": "130000"},
        {"study_uid": "s1", "study_date": "20250101", "study_time": "080000"},
        {"study_uid": "s2", "study_date": "20250101", "study_time": "120000"},
    ]

    ordered = HomeSearchService._sort_studies_by_date_time_ascending(studies)

    assert [item["study_uid"] for item in ordered] == ["s1", "s2", "s3"]


def test_default_sort_uses_latest_study_fields_for_socket_payloads():
    studies = [
        {"patient_id": "p2", "latest_study_date": "20240211", "latest_study_time": "093000"},
        {"patient_id": "p1", "latest_study_date": "20240210", "latest_study_time": "101500"},
    ]

    ordered = HomeSearchService._sort_studies_by_date_time_ascending(studies)

    assert [item["patient_id"] for item in ordered] == ["p1", "p2"]


def test_default_sort_puts_unknown_dates_at_end():
    studies = [
        {"study_uid": "known-early", "study_date": "20231201", "study_time": "090000"},
        {"study_uid": "unknown", "study_date": "", "study_time": "080000"},
        {"study_uid": "known-late", "study_date": "20240101", "study_time": "090000"},
    ]

    ordered = HomeSearchService._sort_studies_by_date_time_ascending(studies)

    assert [item["study_uid"] for item in ordered] == ["known-early", "known-late", "unknown"]


def test_default_sort_normalizes_common_time_formats():
    studies = [
        {"study_uid": "sec", "study_date": "20250101", "study_time": "093001"},
        {"study_uid": "minute", "study_date": "20250101", "study_time": "0930"},
        {"study_uid": "colon", "study_date": "20250101", "study_time": "09:30:00"},
    ]

    ordered = HomeSearchService._sort_studies_by_date_time_ascending(studies)

    assert [item["study_uid"] for item in ordered] == ["minute", "colon", "sec"]
