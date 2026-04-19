# FAST Pipeline Job Block Inventory

## Purpose

This inventory is the first concrete pass over the jobs involved in two user-critical flows:

1. **open new patient**
2. **stack / scroll image**

The goal is simple:

- list the jobs in one place
- assign every job to a block
- assign every job an owner file and worker model
- avoid orphan jobs with unclear ownership

This document is paired with the machine-readable contract:

- `tests/performance/pipeline_job_block_model.json`

and enforced by:

- `tests/performance/test_pipeline_job_block_model.py`

## Rules

A job is **not allowed** to be orphaned.

Every job in these two flows must have:

- a scenario
- a block owner
- a concrete owner file
- a worker/process model
- an orchestration note

## Scenario 1 — Open new patient

### Block 1 jobs

- `open_request_guard`
- `study_path_resolution`
- `tab_create_activate`
- `download_manager_start_priority`
- `download_signal_wiring`
- `server_series_info_push`
- `right_panel_series_info_schedule`
- `attachment_download_background`
- `thumbnail_ready_projection`

### Block 2 jobs

- `first_series_preview_load`
- `full_series_async_load`
- `single_series_full_load`
- `display_series_after_load`
- `activate_progressive_mode`

### Block 3 jobs

- `pending_series_dedup`
- `progressive_start`
- `progressive_grow`
- `deferred_viewer_refresh`
- `background_completion_skip_gate`
- `terminal_completion_finalize`

## Scenario 2 — Stack / scroll image

### Block 2 jobs

- `qt_set_slice_present`
- `rendered_frame_fetch`
- `display_qimage`
- `settled_exact_rerender`

### Block 3 jobs

- `fast_interaction_record`
- `pipeline_slice_index_prepare`
- `booster_pause_resume`
- `interaction_settle_timer`
- `slider_sync`
- `lock_sync_callback`
- `reference_line_schedule`
- `stack_drag_policy_resolution`

## Why these jobs are grouped this way

### Block 1

Block 1 owns upstream data/state and side-panel state.

If a job's purpose is:

- getting data
- persisting data
- wiring download state
- updating right-panel / thumbnail state

then it belongs to Block 1.

### Block 2

Block 2 owns visible image production.

If a job's purpose is:

- decode
- preview
- full series load for visible display
- render frame production
- present exact image to user

then it belongs to Block 2.

### Block 3

Block 3 owns control-plane behavior.

If a job's purpose is:

- scheduling
- dedup
- progressive lifecycle
- defer / admit / finalize
- scroll policy
- settle / redraw follow-up

then it belongs to Block 3.

## Anti-orphan rule

The anti-orphan rule for this inventory is:

$$
\forall j \in J,\; owner(j) \neq \varnothing
$$

where each job $j$ must resolve to exactly one primary block owner.

If a job interacts with multiple blocks, one block still owns it and the others are dependencies only.

## Immediate use

This inventory should now be used for three things:

1. **runtime refactor sequencing**
   - collapse orphan-prone coordination into Block 3 owners first
2. **performance KPI design**
   - map scenario timings to the jobs in this inventory
3. **test design**
   - fail fast if a newly added job has no owner block

## Next refactor target

Based on this inventory, the most fragile nontrivial cluster is:

- `pending_series_dedup`
- `progressive_start`
- `progressive_grow`
- `terminal_completion_finalize`
- `interaction_settle_timer`
- `slider_sync`
- `lock_sync_callback`
- `reference_line_schedule`

These are all Block 3 jobs and are the best next candidates to collapse under a single orchestration owner so they do not drift into orphan behavior.
