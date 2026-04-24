# NEXT AGENT READING ORDER — Block A / Block B / KPI / ClearCanvas

Read in this order before making the next change.

---

## Priority 1 — Read first

### 1. `docs/plans/analysis/BLOCK_A_B_KPI_CLEARCANVAS_HANDOFF_2026-04-20.md`

**Why first:**  
This is the current canonical handoff for the block roadmap, KPI interpretation, and ClearCanvas simulation/comparison state.

### 2. `docs/plans/implementation/block-structure-roadmap-2026-04-19.md`

**Why second:**  
This is the clearest block-by-block ownership roadmap and already records the structural Block A work that landed.

### 3. `docs/plans/analysis/block-priority-review-clearcanvas-2026-04-19.md`

**Why third:**  
This explains the A → B → C priority model, the Block B hardening logic, and why ClearCanvas matters as an ownership reference.

---

## Priority 2 — Read before changing performance behavior

### 4. `docs/plans/plan.md`

Focus on:
- current benchmark truth,
- `run_001` / `run_002` interpretation,
- current KPI priorities.

### 5. `docs/performance/PERFORMANCE_STATUS.md`

**Why:**  
Use this when checking whether a proposed change is moving the measured performance story in the right direction.

### 6. `docs/analysis/CLEARCANVAS_BENCHMARK_EXECUTION.md`

**Why:**  
This is the practical runbook for the ClearCanvas comparison/simulation workflow and its current blockers.

---

## Priority 3 — Read when touching code

### 7. `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_series.py`

Focus on:
- `_queue_qt_startup_refit()`
- `_start_qt_viewer()`

**Why:**  
This contains the fresh-start Qt refit fix for the wrong-zoom-on-last-series issue.

### 8. `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py`

Focus on:
- `_perform_series_switch_optimized()`
- `_schedule_post_switch_followups()`

**Why:**  
This is the main Block B first-frame authority area.

### 9. `modules/viewer/fast/stack_cache_profile.py`

**Why:**  
This contains the current small-stack fast-interaction radius policy.

### 10. `modules/viewer/fast/lightweight_2d_pipeline.py`

Focus on:
- `_compute_adaptive_radius(...)`
- `_prefetch_around(...)`

**Why:**  
This is where the live runtime actually consumes the cache/prefetch profile.

---

## Priority 4 — Read when validating the latest change

### 11. `tests/viewer/test_stack_cache_profile.py`

### 12. `tests/viewer/test_b34_interaction_aware_policy.py`

### 13. `tests/viewer/test_qt_stack_drag_bridge.py`

**Why:**  
These cover the recent small-stack prefetch policy and the Qt startup refit behavior.

---

## Immediate practical next step

After reading the items above:

1. capture a fresh runtime log for the small-stack drag scenario,
2. compare CPU + `[B3.8_SCROLL]` behavior against the prior manual findings,
3. only then choose the next Block B/Block C optimization target.
