"""Download Manager Widget — V/P/C structural contracts (Phase 2.1 prep).

Architecture review (`docs/plans/ARCHITECTURE_REVIEW_2026-04-30.md` Phase 2)
recommends splitting ``DownloadManagerWidget`` into three real classes::

    DownloadManagerView       — pure widget (no state mutations).
    DownloadManagerPresenter  — observer subscriptions (state → view).
    DownloadManagerCommands   — user-action handlers (calls coordinator/store).

Today these live as 9 ``_dm_*.py`` mixins. The split is *recognized in
practice* (drag-drop ghost-signal R22, table-rebuild storm R22, the recurring
"who writes the combo" question) but not yet enforced structurally.

This module is the **specification**:

1. Three :class:`typing.Protocol` definitions describing the eventual
   public surface of each layer.
2. The :data:`MIXIN_RESPONSIBILITY_MAP` table that classifies every current
   ``_dm_*.py`` mixin into View / Presenter / Commands.
3. The :data:`MIXIN_PUBLIC_METHODS` baseline so a drift test can flag any
   method that disappears or migrates between layers without an explicit
   plan update.

This file ships **no behavior**. It is read by:

* ``tests/architecture/test_dm_widget_responsibilities.py`` — drift detector.
* Future Phase 2.1 extraction work — uses :data:`MIXIN_RESPONSIBILITY_MAP`
  as the migration plan.

If you add a new public method to any ``_dm_*.py`` mixin, also add it to
:data:`MIXIN_PUBLIC_METHODS`. If you add a new mixin, also add it to
:data:`MIXIN_RESPONSIBILITY_MAP`. The drift test will fail loudly otherwise.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence, Tuple, runtime_checkable


# ---------------------------------------------------------------------------
# 1. Layer enum (string constants — keep identifiers stable for tests).
# ---------------------------------------------------------------------------

VIEW = "view"
PRESENTER = "presenter"
COMMANDS = "commands"
MIXED = "mixed"  # transitional: mixin straddles two layers, must split.

ALL_LAYERS: Tuple[str, ...] = (VIEW, PRESENTER, COMMANDS, MIXED)


# ---------------------------------------------------------------------------
# 2. Typed Protocols (the future public surface).
# ---------------------------------------------------------------------------

@runtime_checkable
class DownloadManagerViewProtocol(Protocol):
    """Pure widget surface. NEVER mutates state_store or calls coordinator.

    All combo writes are wrapped in ``blockSignals(True/False)`` (R22).
    All updates are property-idempotent (skip when already in target state).
    Methods here are safe to call from any thread that has marshaled to the
    Qt main thread.
    """

    # Construction
    def setup_ui(self) -> None: ...
    def apply_theme(self, theme: Mapping[str, str]) -> None: ...

    # Row lifecycle
    def add_download_row(self, study_uid: str, *, priority: str) -> None: ...
    def remove_download_row(self, study_uid: str) -> None: ...

    # Idempotent property writes
    def update_progress_bar(self, study_uid: str, percent: float) -> None: ...
    def update_status_badge(self, study_uid: str, status_text: str) -> None: ...
    def update_priority_badge(self, study_uid: str, priority: str) -> None: ...
    def update_action_buttons(
        self, study_uid: str, *, enabled: Mapping[str, bool]
    ) -> None: ...

    # Details panel
    def show_details(self, study_uid: str, payload: Mapping[str, Any]) -> None: ...
    def clear_details(self) -> None: ...


@runtime_checkable
class DownloadManagerPresenterProtocol(Protocol):
    """Observer subscriptions. Translates state events → view updates.

    NEVER calls ``intent_coordinator.<method>`` directly; if a state change
    requires a coordinator action, the presenter raises a Command (passing
    through the Commands layer). NEVER mutates Qt widgets directly; goes
    through the View.
    """

    def attach(self) -> None: ...
    def detach(self) -> None: ...

    # State → view fan-out
    def on_state_changed(self, study_uid: str, field: str, value: Any) -> None: ...
    def on_worker_progress(
        self, study_uid: str, downloaded: int, total: int
    ) -> None: ...
    def on_worker_completed(self, study_uid: str) -> None: ...
    def on_worker_error(self, study_uid: str, error: str) -> None: ...
    def on_selection_changed(self, study_uid: str | None) -> None: ...


@runtime_checkable
class DownloadManagerCommandsProtocol(Protocol):
    """User-action handlers. Calls coordinator / state-store / worker pool.

    Always called from a user gesture (button click, combo change, drag
    drop). NEVER writes to Qt widgets directly except via the View. NEVER
    subscribes to observers (that is the Presenter's job).
    """

    def pause_study(self, study_uid: str) -> None: ...
    def resume_study(self, study_uid: str) -> None: ...
    def cancel_study(self, study_uid: str) -> None: ...
    def retry_study(self, study_uid: str) -> None: ...
    def retry_series(self, study_uid: str, series_number: str) -> None: ...
    def change_priority(self, study_uid: str, priority: str) -> None: ...
    def request_critical_series(
        self, study_uid: str, series_number: str
    ) -> None: ...
    def set_viewed_series(
        self, study_uid: str, series_number: str
    ) -> None: ...
    def start_priority_download(
        self, task: Any, *, priority: str
    ) -> None: ...


# ---------------------------------------------------------------------------
# 3. Mixin classification (Phase 2.1 migration plan as data).
# ---------------------------------------------------------------------------

#: Which layer each existing ``_dm_*.py`` mixin will migrate into.
#: ``MIXED`` means the mixin straddles two layers and MUST split during the
#: Phase 2.1 extraction; the second column lists the secondary layer.
MIXIN_RESPONSIBILITY_MAP: Mapping[str, Tuple[str, str | None]] = {
    "_dm_ui_setup": (VIEW, None),
    "_dm_theming": (VIEW, PRESENTER),       # _on_app_theme_changed is observer
    "_dm_queue": (VIEW, None),
    "_dm_details": (MIXED, PRESENTER),      # selection + render mixed today
    "_dm_workers": (PRESENTER, COMMANDS),   # _start_*_worker are Commands
    "_dm_reception": (PRESENTER, None),
    "_dm_controls": (COMMANDS, None),
    "_dm_retry": (COMMANDS, None),
    "_dm_priority": (COMMANDS, None),
}


#: Public-ish methods owned by each mixin TODAY. Drift detector compares
#: this to live source. Add new methods here when introducing them; remove
#: when migrating during the Phase 2.1 extraction. The leading underscore
#: is preserved because everything in these mixins uses the convention of
#: prefixing with ``_`` even when called externally via attribute access
#: on the composed widget.
MIXIN_PUBLIC_METHODS: Mapping[str, Sequence[str]] = {
    "_dm_ui_setup": (
        "_create_toolbar_separator",
        "_setup_details_panel",
        "_setup_download_queue",
        "_setup_header",
        "_setup_toolbar",
        "_setup_ui",
    ),
    "_dm_theming": (
        "_apply_v106_styling",
        "_on_app_theme_changed",
        "_update_speed_display",
        "log_message",
    ),
    "_dm_queue": (
        "_calculate_overall_progress",
        "_create_task_from_dict",
        "_do_update_action_buttons",
        "_do_update_priority_badge",
        "_do_update_progress_bar",
        "_do_update_status_badge",
        "_find_row_for_study_uid",
        "_get_series_image_count_map",
        "_get_study_uid_for_row",
        "_rebuild_row_index",
        "_update_status_label",
        "add_download_row",
        "add_downloads",
        "refresh_table_order",
        "remove_download_row",
        "update_action_buttons",
        "update_current_series",
        "update_priority_badge",
        "update_progress_bar",
        "update_status_badge",
    ),
    "_dm_details": (
        "_add_download_row_to_table",
        "_add_priority_group_header",
        "_add_priority_group_spacer",
        "_clear_details_panel",
        "_dm_rebuild_caller_frame",
        "_log_patient_comprehensive_info",
        "_on_group_collapsed",
        "_on_selection_changed",
        "_on_table_cell_clicked",
        "_on_table_item_clicked",
        "_refresh_table_order",
        "_reset_reception_fields",
        "_select_study_row",
        "_update_button_states",
        "_update_details_panel",
        "_update_series_breakdown_from_task",
    ),
    "_dm_workers": (
        "_apply_throttled_progress",
        "_check_auto_resume",
        "_check_auto_retry",
        "_cleanup_task_state",
        "_on_pool_slot_freed",
        "_on_worker_completed",
        "_on_worker_error",
        "_on_worker_progress",
        "_pipeline_health_check",
        "_reconstruct_task_from_database",
        "_start_download_worker",
        "_start_next_pending",
    ),
    "_dm_reception": (
        "_apply_reception_data",
        "_load_reception_data",
        "_on_reception_data_error",
        "_on_reception_data_received",
    ),
    "_dm_controls": (
        "_on_cancel_selected",
        "_on_clear",
        "_on_pause",
        "_on_pause_selected",
        "_on_play",
        "_on_priority_changed",
        "_on_refresh",
        "_on_reset_all",
        "_on_retry_selected",
        "_on_start_selected",
    ),
    "_dm_retry": (
        "_on_per_patient_cancel",
        "_on_per_patient_pause",
        "_on_per_patient_resume",
        "_on_per_patient_retry",
        "_on_series_retry",
    ),
    "_dm_priority": (
        "_find_object_request_context",
        "_negotiate_priority_change",
        "_object_file_path_for",
        "_pause_all_active_downloads",
        "_pause_downloads_for_preemption",
        "_schedule_priority_start_retry",
        "clear_viewed_series",
        "has_object",
        "request_critical_series_download",
        "request_object",
        "set_viewed_series",
        "start_priority_download_immediately",
    ),
}


__all__ = [
    "VIEW",
    "PRESENTER",
    "COMMANDS",
    "MIXED",
    "ALL_LAYERS",
    "DownloadManagerViewProtocol",
    "DownloadManagerPresenterProtocol",
    "DownloadManagerCommandsProtocol",
    "MIXIN_RESPONSIBILITY_MAP",
    "MIXIN_PUBLIC_METHODS",
]
