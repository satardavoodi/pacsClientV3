from pathlib import Path

from tools.performance import storm_knob_sweep as sweep


BASELINE_RUNS = [
    {
        "profile_key": "baseline",
        "label": "Baseline",
        "description": "baseline",
        "overlap": {
            "kpis": {
                "first_image_visible_ms": 200.0,
                "set_slice_present_p95_ms": 15.0,
                "set_slice_present_max_ms": 40.0,
                "cpu_p95_pct": 90.0,
                "slow_frame_count_16ms": 30.0,
                "thread_count_p95": 22.0,
            }
        },
        "common": {
            "kpis": {
                "first_image_visible_ms": 180.0,
                "set_slice_present_p95_ms": 10.0,
                "set_slice_present_max_ms": 20.0,
                "cpu_p95_pct": 50.0,
                "slow_frame_count_16ms": 2.0,
                "thread_count_p95": 14.0,
            }
        },
    },
    {
        "profile_key": "lazy_workers_1",
        "label": "Lazy workers 1",
        "description": "single worker",
        "overlap": {
            "kpis": {
                "first_image_visible_ms": 210.0,
                "set_slice_present_p95_ms": 11.0,
                "set_slice_present_max_ms": 25.0,
                "cpu_p95_pct": 70.0,
                "slow_frame_count_16ms": 10.0,
                "thread_count_p95": 13.0,
            }
        },
        "common": {
            "kpis": {
                "first_image_visible_ms": 190.0,
                "set_slice_present_p95_ms": 11.0,
                "set_slice_present_max_ms": 22.0,
                "cpu_p95_pct": 49.0,
                "slow_frame_count_16ms": 2.0,
                "thread_count_p95": 13.0,
            }
        },
    },
]


def test_profile_map_contains_expected_keys():
    profile_map = sweep.get_profile_map()
    assert "baseline" in profile_map
    assert "lazy_workers_1" in profile_map
    assert profile_map["admit_batch_small"].env["AIPACS_PROGRESSIVE_ADMIT_BATCH"] == "5"


def test_within_tolerance_uses_10_percent_upper_bound():
    assert sweep.within_tolerance(109.9, 100.0, 0.10)
    assert not sweep.within_tolerance(111.0, 100.0, 0.10)


def test_build_summary_rows_ranks_improved_profile_before_baseline():
    rows = sweep.build_summary_rows(BASELINE_RUNS)
    assert rows[0]["profile_key"] == "lazy_workers_1"
    assert rows[0]["storm_index"] < 1.0
    assert rows[1]["profile_key"] == "baseline"
    assert rows[1]["storm_index"] == 1.0


def test_markdown_summary_mentions_best_profile_and_dataset():
    rows = sweep.build_summary_rows(BASELINE_RUNS)
    markdown = sweep.summary_to_markdown(
        rows,
        dataset=Path("user_data/patients/dicom/example/202"),
        clearcanvas_reference={"source_root": "C:/AI-Pacs codes/ClearCanvas-master/ClearCanvas-master"},
        clearcanvas_payload=None,
    )
    assert "`lazy_workers_1`" in markdown
    assert "Best current balance" in markdown
    assert "user_data/patients/dicom/example/202" in markdown
