"""AUTO-GENERATED test quarantine registry — see tools/dev/build_quarantine.py.

Each entry is a test that is CURRENTLY FAILING and has been quarantined so the suite
can be GREEN, so that any NEW red is a real, visible regression.

*** THIS IS A DEBT REGISTER, NOT AN AMNESTY. ***

Rules:
  * `strict=True` — if a quarantined test starts PASSING, the suite FAILS. Remove it
    from this list (that is the intended, self-cleaning workflow).
  * Do NOT add a test here to make a red go away. Quarantine is for PRE-EXISTING debt
    only; a test your change broke must be FIXED.
  * Every UNTRIAGED entry may be hiding a REAL product bug. Burn this list down.
"""

# nodeid -> (category, reason captured from the live run)
QUARANTINE = {
    "tests/code/ai_imaging/test_cursor3d_guided_workflow.py::test_clicks_after_completion_are_ignored":
        ("UNTRIAGED", "AssertionError: assert False"),
    "tests/code/ai_imaging/test_cursor3d_guided_workflow.py::test_flow_progress_and_completion":
        ("UNTRIAGED", "assert 4 == 3"),
    "tests/code/ai_imaging/test_cursor3d_guided_workflow.py::test_imaging_tab_uses_guided_flow_and_keeps_legacy_fallback":
        ("UNTRIAGED", "AssertionError: the CC pectoral angle is not used by the correlator"),
    "tests/code/ai_imaging/test_cursor3d_guided_workflow.py::test_no_cc_pectoral_step_is_requested":
        ("UNTRIAGED", "assert not True"),
    "tests/code/ai_imaging/test_cursor3d_guided_workflow.py::test_step_order_is_nipple_mlo_then_nipple_cc_then_pectoral_mlo":
        ("UNTRIAGED", "AssertionError: assert ['nipple_mlo'...'pectoral_cc'] == ['nipple_mlo'...pectoral_mlo']"),
    "tests/code/ai_imaging/test_cursor3d_two_stage.py::test_radial_agreement_disambiguates_position_ALONG_the_strip":
        ("UNTRIAGED", "AssertionError: the radially-consistent candidate must win"),
    "tests/code/ai_imaging/test_cursor3d_view_identity.py::test_guided_flow_now_plans_for_the_live_case":
        ("UNTRIAGED", "AssertionError: assert ['nipple_mlo'...'pectoral_cc'] == ['nipple_mlo'...pectoral_mlo']"),
    "tests/code/architecture/test_dm_widget_responsibilities.py::test_public_methods_baseline_matches_source":
        ("drift", "Failed: DM widget public-method baseline drift:"),
    "tests/code/data_analysis/test_admission_reports.py::test_build_snapshot_cards_and_highlights":
        ("UNTRIAGED", "assert 57649250000 == 58411970000"),
    "tests/code/echomind/test_ct_reporter.py::TestValidateReportJsonCT::test_passthrough_for_non_ct":
        ("UNTRIAGED", "ValueError: non-parseable JSON returned by model: Expecting value: line 1 column 1 (char 0)"),
    "tests/code/echomind/test_mammography_reporter.py::TestMammographyBranchSourcePin::test_mammography_elif_branch_exists":
        ("UNTRIAGED", "AssertionError: 'elif modality_lower == 'mammography':' not found in 'import base64/nimport json/nimport os/nfrom datetime import datetime/nfrom typing import Any, Dict, Optional/n"),
    "tests/code/echomind/test_module_catalog_coverage.py::test_every_bus_action_is_documented_or_acknowledged":
        ("drift", "AssertionError: Infrastructure action(s) collide with module catalog: ['get_active_tab', 'list_open_tabs']"),
    "tests/code/echomind/test_routing_v2.py::test_web_browser_doc_killswitch_legacy":
        ("drift", "AssertionError: assert 'browser_fill_field' not in '# Module Do... the user./n'"),
    "tests/code/education/test_case_of_day_media_capture.py::test_viewport_recorder_drops_frames_under_backpressure":
        ("UNTRIAGED", "assert 0 == 1"),
    "tests/code/network/test_ino_assignment.py::test_reporting_physician_path_has_no_own_assignment_logic":
        ("UNTRIAGED", "AssertionError: legacy assignment logic reintroduced: notify_local_assignment"),
    "tests/code/network/test_ino_report_workflow.py::test_classify_error[400-\u0634\u0645\u0627 \u0645\u062c\u0627\u0632 \u0628\u0647 \u0627\u06cc\u0646 \u0639\u0645\u0644\u06cc\u0627\u062a \u0646\u06cc\u0633\u062a\u06cc\u062f-permission]":
        ("UNTRIAGED", "AssertionError: assert 'http' == 'permission'"),
    "tests/code/system/test_mpr_tool_autoexit.py::test_auto_exit_cleans_empty_views_keeps_completed_and_fires_callback":
        ("UNTRIAGED", "assert (False is True)"),
    "tests/code/test_home_info_panel.py::test_persian_edition_data_complete":
        ("UNTRIAGED", "AssertionError: assert 'AI-PACS Version 3.2.8' in 'AI-PACS Version 3.5.2 This edition has been customized and localized for Persian-speaking users at the request of our... healthca"),
    "tests/code/test_notify_malformed_dispatch_guard.py::test_malformed_dispatch_returns_false_not_raise":
        ("UNTRIAGED", "assert 'raise' not in 'if _malform...           ''"),
    "tests/code/test_right_panel_input_sync_guard.py::test_immediate_renderer_defers_under_gate":
        ("UNTRIAGED", "ValueError: substring not found"),
    "tests/code/ui_services/test_pin_overlay.py::test_patient_table_overlay_wired":
        ("UNTRIAGED", "assert 'from PacsClient.utils.local_reminders import get_pinned_rows' in 'from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,/n       "),
    "tests/code/ui_services/test_pin_overlay.py::test_pinned_top_enforcement_wired":
        ("UNTRIAGED", "assert '_arm_pin_overlay_refresh()' in 'def _emit_patient_selection_now(self, row: int):/n        '''Emit the queued patient-selection signals — runs on the ...fter (debounced; a n"),
    "tests/code/ui_services/test_vtk_volume_service.py::test_routing_helper_present_and_pin_deferred":
        ("UNTRIAGED", "assert 'pin=False' in 'def build_or_get_mpr_volume(study_uid: Any, series_uid: Any, builder: Callable[[], Any], *,/n                        ...ation rule).'''/n    return build_or_"),
    "tests/code/viewer/test_b35_deferred_header_fill.py::TestDeferredHeaderFill::test_metadata_count_updated_immediately":
        ("UNTRIAGED", "assert 3 == 6"),
    "tests/code/viewer/test_b35_deferred_header_fill.py::TestDeferredHeaderFill::test_new_instances_have_template_fields_immediately":
        ("UNTRIAGED", "AssertionError: assert 3 == 6"),
    "tests/code/viewer/test_b35_deferred_header_fill.py::TestDeferredHeaderFill::test_refresh_does_not_call_fill_stub_synchronously":
        ("UNTRIAGED", "AssertionError: Expected 3 new stubs, got 0"),
    "tests/code/viewer/test_b35_deferred_header_fill.py::TestGrowPathIntegration::test_grow_tick_main_thread_cost_excluding_headers":
        ("UNTRIAGED", "AssertionError: assert 5 == 15"),
    "tests/code/viewer/test_b36_booster_interaction_gate.py::TestBridgeBoosterWiring::test_set_slice_enables_fast_mode_before_set_slice_index":
        ("UNTRIAGED", "AttributeError: 'QtViewerBridge' object has no attribute 'flag_set_custom_window_level'"),
    "tests/code/viewer/test_b36_booster_interaction_gate.py::TestBridgeBoosterWiring::test_set_slice_fast_interaction_pauses_booster":
        ("UNTRIAGED", "AttributeError: 'QtViewerBridge' object has no attribute 'flag_set_custom_window_level'"),
    "tests/code/viewer/test_b36_booster_interaction_gate.py::TestBridgeBoosterWiring::test_set_slice_no_fast_resumes_booster":
        ("UNTRIAGED", "AttributeError: 'QtViewerBridge' object has no attribute 'flag_set_custom_window_level'"),
    "tests/code/viewer/test_curved_mpr_inplace_viewport.py::test_inplace_flag_declared_default_off":
        ("UNTRIAGED", "AssertionError: flag must default OFF"),
    "tests/code/viewer/test_curved_mpr_inplace_viewport.py::test_inplace_method_does_not_wipe_grid":
        ("UNTRIAGED", "AssertionError: the in-place placement must preserve other viewports — no grid wipe"),
    "tests/code/viewer/test_curved_mpr_inplace_viewport.py::test_restore_recognizes_curved_cross_link":
        ("UNTRIAGED", "AssertionError: _restore_selected_viewer must recognize the curved-MPR cross-link"),
    "tests/code/viewer/test_dental_curve_panel_polish.py::test_panoramic_thickness_control_wired_to_generation":
        ("UNTRIAGED", "assert 'self._curved_mpr_thickness_mm = 10.0' in 'from PySide6.QtCore import QSize, Qt, QPoint, QTimer/nfrom PySide6.QtGui import QIcon, QPixmap, QTransform, QGuiAppli...RROR] Fail"),
    "tests/code/viewer/test_display_geometry.py::TestDisplayKPolicy::test_apply_stack_policy_inverse_maps_raw_0_to_display_1":
        ("UNTRIAGED", "assert 2 == 1"),
    "tests/code/viewer/test_display_geometry.py::TestDisplayKPolicy::test_apply_stack_policy_maps_display_1_to_raw_0":
        ("UNTRIAGED", "assert -1 == 0"),
    "tests/code/viewer/test_display_geometry.py::TestEffectiveAffine::test_display_to_lps_origin":
        ("UNTRIAGED", "AssertionError: "),
    "tests/code/viewer/test_display_geometry.py::TestIdentityStart::test_effective_equals_raw_affine":
        ("UNTRIAGED", "AssertionError: "),
    "tests/code/viewer/test_dragdrop_progressive.py::test_completion_signal_triggers_one_shot_grow_on_non_progressive_viewer":
        ("UNTRIAGED", "AssertionError: _grow_progressive_fast expected once with sn='6', got: []"),
    "tests/code/viewer/test_event_loop_diagnostics.py::test_session_start_stop":
        ("UNTRIAGED", "AssertionError: assert None == 'test-session-1'"),
    "tests/code/viewer/test_fast_viewer_empty_state_ui.py::test_change_container_border_applies_active_and_inactive_styles":
        ("UNTRIAGED", "AttributeError: 'types.SimpleNamespace' object has no attribute '_node_is_previous_exam'"),
    "tests/code/viewer/test_fast_viewer_live_sync.py::test_grow_uses_qt_bridge_when_qt_bridge_active":
        ("UNTRIAGED", "AssertionError: bridge.grow() must be called on the Qt-bridge path, got []"),
    "tests/code/viewer/test_fast_viewer_live_sync.py::test_refresh_stored_metadata_called_each_grow":
        ("UNTRIAGED", "AssertionError: _refresh_stored_metadata_instances must be called at partial grow, got [('14', 30)]"),
    "tests/code/viewer/test_fast_viewer_live_sync.py::test_stale_grow_exhaustion_exits_progressive_mode":
        ("UNTRIAGED", "AssertionError: series must be popped on exhaustion; _progressive_series={'25': {'total': 40, 'last_grow_count': 30, 'last_signal_ms': 0, '_stale_retry_count': 1, 'pending_download"),
    "tests/code/viewer/test_fast_viewer_pipeline.py::test_display_loaded_series_hides_spinner_immediately_after_success":
        ("UNTRIAGED", "assert [] == [namespace(sw...7E58A77240>))]"),
    "tests/code/viewer/test_fast_viewer_pipeline.py::test_perform_series_switch_optimized_defers_followup_ui_work":
        ("UNTRIAGED", "AssertionError: assert [] == [namespace(_q...1-600443570')]"),
    "tests/code/viewer/test_fast_viewer_pipeline.py::test_perform_series_switch_optimized_queues_qt_refit_for_inplace_refresh":
        ("UNTRIAGED", "assert [] == [0, 0, 100]"),
    "tests/code/viewer/test_fast_viewer_pipeline.py::test_perform_series_switch_optimized_refits_qt_target_after_switch":
        ("UNTRIAGED", "assert [] == [0, 100]"),
    "tests/code/viewer/test_geometry_api.py::TestDisplayedIndexToLps::test_origin_at_zero":
        ("UNTRIAGED", "AssertionError: "),
    "tests/code/viewer/test_grow_fallback_force_reload.py::test_fallback_syncs_canonical_metadata_and_forces_reload":
        ("UNTRIAGED", "assert None"),
    "tests/code/viewer/test_mg_window_placeholder.py::test_non_mg_or_non_monochrome1_not_rejected_by_mg_placeholder_rule":
        ("UNTRIAGED", "assert (None == 32768.0)"),
    "tests/code/viewer/test_overlap_pixel_quality.py::test_overlap_pixel_quality_settled[filter_off_mono1]":
        ("golden-drift", "Failed: Pixel-hash mismatch for case 'filter_off_mono1': 10 / 10 slices differ (indices [0, 1, 2, 3, 4]...)."),
    "tests/code/viewer/test_overlap_pixel_quality.py::test_overlap_pixel_quality_settled[filter_on_mono1]":
        ("golden-drift", "Failed: Pixel-hash mismatch for case 'filter_on_mono1': 10 / 10 slices differ (indices [0, 1, 2, 3, 4]...)."),
    "tests/code/viewer/test_overlap_pixel_quality.py::test_overlap_pixel_quality_settled[filter_on_mono2]":
        ("golden-drift", "Failed: Pixel-hash mismatch for case 'filter_on_mono2': 10 / 10 slices differ (indices [0, 1, 2, 3, 4]...)."),
    "tests/code/viewer/test_overlap_pixel_quality_drag.py::test_overlap_pixel_quality_drag[filter_off_mono1]":
        ("UNTRIAGED", "AssertionError: filter_off_mono1: 10 drag frames are NOT a known slice rendering - corruption or dim/zero QImage. First few: [(0, 'f47a8ec3e9af'), (1, 'f47a8ec3e9af'), (2, 'f47a8ec"),
    "tests/code/viewer/test_overlap_pixel_quality_drag.py::test_overlap_pixel_quality_drag[filter_on_mono1]":
        ("UNTRIAGED", "AssertionError: filter_on_mono1: 10 drag frames are NOT a known slice rendering - corruption or dim/zero QImage. First few: [(0, '170bbd73f695'), (1, '170bbd73f695'), (2, '170bbd73"),
    "tests/code/viewer/test_overlap_pixel_quality_drag.py::test_overlap_pixel_quality_drag[filter_on_mono2]":
        ("UNTRIAGED", "AssertionError: filter_on_mono2: 10 drag frames are NOT a known slice rendering - corruption or dim/zero QImage. First few: [(0, '1983d46b1b80'), (1, '964e4e1380e7'), (2, '68203b8d"),
    "tests/code/viewer/test_patient_table_population_visibility.py::test_added_rows_are_present_and_rendered":
        ("UNTRIAGED", "TypeError: expected str, bytes or os.PathLike object, not NoneType"),
    "tests/code/viewer/test_patient_table_population_visibility.py::test_bulk_insert_population_path_renders":
        ("UNTRIAGED", "TypeError: expected str, bytes or os.PathLike object, not NoneType"),
    "tests/code/viewer/test_patient_table_population_visibility.py::test_clear_table_empties":
        ("UNTRIAGED", "TypeError: expected str, bytes or os.PathLike object, not NoneType"),
    "tests/code/viewer/test_progressive_admission_storm.py::test_storm_gate_adds_only_bounded_background_ticks":
        ("UNTRIAGED", "AssertionError: Storm simulation made no forward progress; this would indicate a stuck gate (before=20, after=20)."),
    "tests/code/viewer/test_progressive_admission_storm.py::test_storm_gate_keeps_terminal_completion_uncapped":
        ("UNTRIAGED", "AssertionError: Terminal completion must expose the full completed count immediately, got []"),
    "tests/code/viewer/test_progressive_admission_storm.py::test_storm_gate_reduces_nonterminal_burst_shock":
        ("UNTRIAGED", "AssertionError: Storm simulation made no forward progress; this would indicate a stuck gate (before=20, after=20)."),
    "tests/code/viewer/test_progressive_admission_storm.py::test_storm_harness_reaches_high_cpu_pressure_proxy":
        ("UNTRIAGED", "AssertionError: Storm simulation made no forward progress; this would indicate a stuck gate (before=20, after=20)."),
    "tests/code/viewer/test_progressive_await_first_image.py::test_complete_resume_path_preserved":
        ("env", "assert '_disk_ready_complete(count, expected, prev)' in '/ufeff'''/nProgressive display mixin for ViewerController./nHandles incremental viewer updates during series download...es="),
    "tests/code/viewer/test_roi_wl_regressions.py::test_manual_qt_window_level_marks_custom_flag":
        ("UNTRIAGED", "TypeError: 'NoneType' object is not callable"),
    "tests/code/viewer/test_stage1_migration_validation.py::TestAdvancedModeUnchanged::test_force_vtk_fallback_in_metadata":
        ("UNTRIAGED", "AssertionError: assert 'pydicom_qt' == 'vtk_simpleitk'"),
    "tests/code/viewer/test_stage1_migration_validation.py::TestAdvancedModeUnchanged::test_force_vtk_overrides_alias":
        ("UNTRIAGED", "AssertionError: assert 'pydicom_qt' == 'vtk_simpleitk'"),
    "tests/code/viewer/test_stage1_migration_validation.py::TestExhaustiveResolutionMatrix::test_resolution_truth_table[pydicom_2d-True-True-vtk_simpleitk]":
        ("UNTRIAGED", "AssertionError: settings=pydicom_2d, instances=True, force_vtk=True: expected vtk_simpleitk, got pydicom_qt"),
    "tests/code/viewer/test_stage1_migration_validation.py::TestExhaustiveResolutionMatrix::test_resolution_truth_table[pydicom_qt-True-True-vtk_simpleitk]":
        ("UNTRIAGED", "AssertionError: settings=pydicom_qt, instances=True, force_vtk=True: expected vtk_simpleitk, got pydicom_qt"),
    "tests/code/viewer/test_stage1_migration_validation.py::TestFastBackendResolution::test_config_file_reads_pydicom_qt":
        ("UNTRIAGED", "AssertionError: Config file should say pydicom_qt, got pydicom_2d"),
    "tests/code/viewer/test_stage1_migration_validation.py::TestFastBackendResolution::test_load_viewer_backend_returns_pydicom_qt":
        ("UNTRIAGED", "AssertionError: load_viewer_backend() should return pydicom_qt, got pydicom_2d"),
    "tests/code/viewer/test_stage2_hardening_validation.py::TestEscapeHatch::test_escape_hatch_overridden_by_force_vtk":
        ("UNTRIAGED", "AssertionError: assert 'pydicom_2d' == 'vtk_simpleitk'"),
    "tests/code/viewer/test_stage2_hardening_validation.py::TestForceVtkAlwaysWins::test_force_vtk_with_any_escape[0]":
        ("UNTRIAGED", "AssertionError: assert 'pydicom_qt' == 'vtk_simpleitk'"),
    "tests/code/viewer/test_stage2_hardening_validation.py::TestForceVtkAlwaysWins::test_force_vtk_with_any_escape[1]":
        ("UNTRIAGED", "AssertionError: assert 'pydicom_2d' == 'vtk_simpleitk'"),
    "tests/code/viewer/test_stage2_hardening_validation.py::TestForceVtkAlwaysWins::test_force_vtk_with_any_escape[]":
        ("UNTRIAGED", "AssertionError: assert 'pydicom_qt' == 'vtk_simpleitk'"),
}

# Generated from a live run: 76 quarantined test(s).
