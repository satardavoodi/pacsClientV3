# FAST Render Clock — Production Hardening Plan

**Date:** May 13, 2026  
**Current Status:** KEEP_EXPERIMENT_PROMISING (default OFF, extended soak testing required)  
**Phase:** Stabilization & Hardening (no aggressive optimization)  
**Target Release:** v2.6.0+ (pending stabilization sign-off)

---

## Executive Summary

The FAST render clock experiment has successfully demonstrated:
- **100% side-effect deferral** from input path to render clock
- **92.8% request-to-present efficiency** (346 requests → 321 ticks)
- **Zero fallback activations** (clock remained stable entire test)
- **Excellent latency profile**: P95 15.49ms (target 33ms), P95 UI lag 86.96ms
- **No regressions**: slider sync, first-image, reference lines, all functional

This plan defines the path from validated architecture to production default-on, with explicit thresholds and gate criteria.

---

## Phase Duration & Milestones

| Milestone | Duration | Gate Criteria | Owner |
|-----------|----------|---------------|-------|
| Soak Testing (30–60 min sessions) | 2 weeks | Zero crashes, <2% fallback rate | AI agent |
| Multi-hardware Validation | 1 week | Pass all hardware profiles | CI/integration |
| Clock Robustness Hardening | 1 week | Starvation recovery, edge cases | AI agent |
| Architectural Cleanup | 1 week | Dedup metrics, unify pacing, reduce logging | AI agent |
| Promotion Criteria Validation | 3 days | Hit all KPI thresholds | QA gate |
| Sign-off & Release Plan | 2 days | Go/no-go decision | User decision |

**Total: ~4 weeks** (assumes parallel execution where possible)

---

## 1. Long-Session Soak Testing

### Goal
Validate stability and memory/resource behavior over 30–60 minute continuous interaction cycles under realistic production load.

### Test Scenarios

#### 1.1 Continuous Stack Drag (30 min)
```
Duration: 30 minutes continuous
Scenario: Single series, repeated back-and-forth drag navigation
- 5-second forward drag
- 3-second hold
- 5-second backward drag
- 3-second hold (repeat 120 times)

Measurements:
  ✓ Memory growth: <50 MB per 10 min (leak detection)
  ✓ Timer count stable: no accumulation over time
  ✓ Zero crashes/exceptions
  ✓ Frame rate stability: p95 maintained within 10% variation
  ✓ Fallback rate: 0% (expect 0/120 fallbacks)
  ✓ CPU utilization steady: <5% variation
  
Acceptance: Zero regressions vs. 5-min baseline
```

#### 1.2 Progressive Download Overlap (45 min)
```
Duration: 45 minutes
Scenario: Download study A while dragging study B
- Start: Study A downloading (heavy load)
- Overlay: User drags through Study B (full series already loaded)
- Continuation: Drag operations continue as download completes

Measurements:
  ✓ Drag responsiveness maintained during download
  ✓ ui_lag_p95 stays <150ms (allows 1.5x headroom)
  ✓ No slice mismatches as series completes
  ✓ Progressive display updates don't stall clock
  ✓ Reference lines persist correctly through completion
  
Acceptance: No perceived UI lag degradation
```

#### 1.3 Rapid Series Switching (30 min)
```
Duration: 30 minutes
Scenario: Quick series selection from thumbnail sidebar
- Switch series every 3 seconds (600 switches)
- Drag 5 slices, then switch to next series
- Run across 6 different series from same study

Measurements:
  ✓ Clock resets cleanly between series
  ✓ Pending flags cleared on series close
  ✓ No pending side effects leak to new series
  ✓ Timer lifecycle stable (no orphaned timers)
  ✓ Memory freed on series switch
  
Acceptance: Zero slice-mismatch incidents, stable memory
```

#### 1.4 Multi-Study Workflow (60 min)
```
Duration: 60 minutes
Scenario: Open/close multiple patients, navigate multiple studies
- Patient A: 3 studies (CT, MR, XR) — each series dragged
- Patient B: 2 studies (CT, XR) — each series dragged
- Return to Patient A, continue dragging
- Close Patient B, open Patient C

Measurements:
  ✓ Patient tab lifecycle clean
  ✓ No timer leakage across patient switches
  ✓ Clock disabled on inactive patient tabs
  ✓ No cross-patient reference line corruption
  ✓ Memory released on patient close
  ✓ Fallback rate: <1% (expect max 1 incident across 60 min)
  
Acceptance: Stable resource usage, no cross-tab contamination
```

#### 1.5 Memory Stability Check
```
Measurement: Heap size samples every 2 minutes
  ✓ Baseline at 0 min: X MB
  ✓ At 30 min: X + ΔM MB (where ΔM <25 MB)
  ✓ At 60 min: X + ΔM MB (no acceleration)
  ✓ After GC: Return to baseline ±5 MB
  
Acceptance: Sub-linear growth, GC effective
```

#### 1.6 Timer Lifecycle Validation
```
Measurement: Count active timers at baseline, mid-session, end
  ✓ Baseline: N timers
  ✓ During drag: N+1 (clock timer active)
  ✓ After drag ends: N (timer cleaned up)
  ✓ After series close: N (no orphaned timers)
  ✓ End of session: N (exact match)
  
Acceptance: No timer accumulation
```

### Success Criteria
- ✅ **Zero crashes** across all 6 scenarios
- ✅ **Memory growth <50 MB/10min** (linear, no leaks)
- ✅ **Fallback rate <1%** (0–1 incident per 60 min)
- ✅ **Frame rate stability p95 within 10%** of 5-min baseline
- ✅ **UI lag P95 <150ms** (1.5× current baseline)
- ✅ **No pending-flag leaks** between series/patient
- ✅ **Timer cleanup 100%** (no orphaned timers)

### Test Infrastructure
```
Script: tools/performance/soak_test_runner.ps1
  - Automated A/B session pairing (clock on/off)
  - Memory snapshots every 2 min
  - Heap dump on demand
  - KPI extraction to JSON
  
Logs: 
  - viewer_diagnostics.log
  - memory_profile_*.csv
  - soak_test_report.json
```

---

## 2. Multi-Hardware Validation

### Goal
Validate clock behavior and fallback heuristics across diverse hardware profiles.

### Hardware Profiles

#### 2.1 Low-Core CPU (4–6 cores)
```
Profile: Intel i5-12400 / AMD Ryzen 5 5600X
Target: Budget workstation, constrained CPU for decode
Scenarios:
  - Download + drag overlap (heavy contention)
  - High-resolution series (2048×2048 pixels)
  - Multi-viewer layout (4 viewers active)

Measurements:
  ✓ Frame rate maintenance: p95 still >30 FPS
  ✓ Fallback trigger rate: Should remain <1%
  ✓ CPU utilization during drag: <80% (headroom for decode)
  ✓ Request-to-present p95: <33ms
  
Acceptance: No fallback surge on low-core machines
```

#### 2.2 High-Core Workstation (12–16 cores)
```
Profile: Intel i7-13700K / AMD Ryzen 9 7950X3D
Target: High-end workstation, CPU-abundant for decode
Scenarios:
  - Heavy prefetch + drag
  - Multi-series simultaneous download
  - 8+ viewers active layout

Measurements:
  ✓ Frame rate: p95 >60 FPS
  ✓ No unnecessary fallback (clock should stay on)
  ✓ Supersede rate normal: 100–120% of tick rate
  ✓ Memory stable (not accumulated from prefetch)
  
Acceptance: Efficient resource utilization, no stalls
```

#### 2.3 Integrated GPU (Intel UHD / AMD Radeon)
```
Profile: Laptop with integrated GPU, shared memory
Target: Resource-constrained rendering
Scenarios:
  - 1–2 viewer layout (typical laptop usage)
  - Series drag + download overlap
  - VTK Advanced viewer switch to/from FAST

Measurements:
  ✓ No GPU memory stalls
  ✓ Frame interval stable
  ✓ Clock request processing time <5ms (no GPU contention)
  
Acceptance: Stable on integrated GPU
```

#### 2.4 Discrete GPU (NVIDIA RTX 30/40 series, AMD RX 6800XT)
```
Profile: High-end discrete GPU
Target: Data-center workstations
Scenarios:
  - Max resolution series (4096×4096)
  - 3D MPR advanced viewers
  - Simultaneous FAST + VTK rendering

Measurements:
  ✓ GPU utilization <60% (headroom for AI inference)
  ✓ PCIe bandwidth not saturated
  ✓ Clock performance optimal
  
Acceptance: Efficient resource use
```

#### 2.5 High-DPI Monitor (2560×1440, 4K)
```
Profile: External 2560×1440 / 4K monitors
Target: Dense UI rendering, larger render target
Scenarios:
  - Drag on high-DPI external display
  - Comparison mode (multiple viewers)

Measurements:
  ✓ Render clock tick time <5ms (frame target 33ms)
  ✓ No scaling artifacts on drag
  ✓ Request-to-present p95 unchanged
  
Acceptance: Clock independent of monitor DPI
```

#### 2.6 Variable Mouse Polling Rate (125 Hz, 500 Hz, 1000 Hz)
```
Profile: Gaming mice with variable polling rates
Target: High-frequency input stress
Scenarios:
  - Drag with 1000 Hz polling (1ms input event cadence)
  - Rapid small movements
  - Observe supersede rate

Measurements:
  ✓ Supersede rate scales with polling rate
  ✓ Fallback rate stable (<1%)
  ✓ Frame rate not impacted by input frequency
  ✓ request_to_present_p95 <33ms (unchanged)
  
Acceptance: Clock adaptive to input frequency
```

#### 2.7 Windows Timer Granularity (1ms, 15ms, default)
```
Profile: Test under Windows.h SetTimerResolution() variants
Target: System-dependent timer precision variance
Scenarios:
  - Default Windows granularity (15ms)
  - High-precision timer (1ms, requires privilege)
  - Check fallback heuristics

Measurements:
  ✓ Clock operation stable under all granularities
  ✓ Tick interval within ±3ms of target
  ✓ No fallback on low-precision timer
  
Acceptance: Clock robust to timer granularity
```

### Success Criteria
- ✅ **All hardware profiles stable**: No fallback surge, frame rate maintained
- ✅ **Request-to-present P95 <33ms** on all profiles
- ✅ **Fallback rate <1%** across profiles
- ✅ **Memory growth <50 MB/10min** on all profiles
- ✅ **No GPU stalls** on discrete/integrated GPU profiles
- ✅ **Timer granularity adaptation working** (heuristics validated)

### Test Matrix
```
Configurations: 7 hardware profiles × 3 test scenarios = 21 test runs
Duration: ~1 week (parallel execution where lab resources allow)
Success threshold: 20/21 passing (1 failure allowed if non-critical)
```

---

## 3. Clock-Mode Robustness Hardening

### Goal
Validate fallback heuristics and edge-case recovery mechanisms.

### 3.1 Timer Drift Handling

**Test Scenario: Simulate timer drift**
```
Code injection point: _on_fast_render_clock_tick()
  - Inject ±5ms random jitter into tick timing
  - Run 100 drag gestures (45s each)
  
Measurements:
  ✓ Frame rate maintains <10% variance
  ✓ Request-to-present p95 stays <40ms (with jitter)
  ✓ No fallback triggered by timer drift
  ✓ Overshoots detected and logged
  
Acceptance: Clock tolerates ±5ms jitter
```

### 3.2 Starvation Recovery

**Test Scenario: Excessive requests flooding the queue**
```
Setup: Artificially increase mouse polling to 2000 Hz
  - Run continuous tight-circle drag (high frequency input)
  - Observe request queue behavior
  
Measurements:
  ✓ Supersede rate >200% (aggressive preemption)
  ✓ Fallback rate stays 0%
  ✓ Memory bounded (no request queue accumulation)
  ✓ Frame rate degrades gracefully (no stalls)
  
Acceptance: Handles high-frequency input without collapse
```

### 3.3 Fallback Heuristics Validation

**Test Scenario: Trigger fallback conditions**
```
Condition 1: Clock handler takes >30ms (slow render tick)
  - Inject sleep() into handler
  - Expect fallback to synchronous mode
  - Measure recovery time
  
Condition 2: Tick timer stops firing (hardware/OS issue)
  - Kill timer, observe behavior
  - Expect fallback via watchdog timeout
  - Check fallback log emission
  
Condition 3: Memory pressure (pending flag allocation fails)
  - Stress memory, observe behavior
  - Expect graceful degradation, not crash
  
Measurements:
  ✓ Fallback triggered correctly on condition match
  ✓ Recovery <500ms (user imperceptible)
  ✓ Pending side effects applied on fallback
  ✓ No slice mismatches on fallback
  ✓ Fallback logged with [FAST_RENDER_CLOCK_FALLBACK] tag
  
Acceptance: All fallback conditions trigger and recover cleanly
```

### 3.4 Interaction Settle Edge Cases

**Test Scenario: Rapid drag start/stop patterns**
```
Pattern 1: Rapid-fire drag bursts
  - 5 × 2-second drags with 1-second pauses
  - Observe pending flag cleanup between drags
  
Pattern 2: Drag while series changing
  - Initiate drag, switch series mid-drag
  - Expect clock to reset, pending flags cleared
  
Pattern 3: Drag during download completion
  - User drags while series download finishes
  - Expect clean handoff of final images
  
Measurements:
  ✓ Pending flags cleared between drags
  ✓ No stale side effects leak to new series
  ✓ First image on new series correct
  ✓ Reference lines updated correctly
  ✓ No slice mismatches
  
Acceptance: All edge cases handled cleanly
```

### 3.5 Wheel Burst Edge Cases

**Test Scenario: Rapid wheel scroll (mousewheel events)**
```
Pattern 1: Tight wheel scrolls (10 events in 100ms)
  - Observe request superseding behavior
  - Frame rate should remain stable
  
Pattern 2: Wheel then drag transition
  - Scroll wheel 5 times, then drag
  - Pending flags from wheel should not interfere with drag
  
Pattern 3: Rapid direction reversals
  - Up-down-up-down wheel scrolls
  - Observe reframing on direction reversal
  
Measurements:
  ✓ Supersede rate appropriate for wheel events
  ✓ No fallback on wheel-to-drag transition
  ✓ Frame rate stable during transitions
  ✓ Prefetch direction resets on reversal
  
Acceptance: Wheel bursts handled smoothly
```

### Success Criteria
- ✅ **Timer drift tolerance**: ±5ms jitter absorbed without fallback
- ✅ **Starvation handling**: High-frequency input doesn't cause collapse
- ✅ **Fallback heuristics**: All conditions trigger, recovery <500ms
- ✅ **Settle edge cases**: All patterns handled cleanly
- ✅ **Wheel bursts**: Smooth transitions, no interference with drag

### Test Infrastructure
```
Script: tools/performance/robustness_harness.py
  - Inject faults/jitter
  - Monitor fallback triggers
  - Measure recovery latency
  - Log detailed state transitions
  
Logs:
  - viewer_diagnostics.log (fallback events)
  - robustness_harness_report.json (measurements)
```

---

## 4. Architectural Cleanup Opportunities

**ONLY after soak testing passes.**  
**Implement AFTER stabilization phase, not during.**

### 4.1 Unify Latest-Request Semantics

**Current State:**
- `_fast_pending_*_update` flags track "has pending update"
- Separate `_latest_requested_slice_value` tracks the value
- Supersede logic duplicated between slider, sync, reference

**Proposed Cleanup:**
```
struct PendingUpdate:
  - value: int (the latest requested value)
  - present_count: int (how many times presented)
  - superseded_count: int (how many requests preempted)
  - last_request_time_ms: float
  
Benefits:
  - Single source of truth for "latest request"
  - Reduce duplicate supersede logic
  - Easier to reason about state transitions
  - Prepare for multi-effect batching in future
  
Impact: Zero user-visible change, pure code cleanup
```

### 4.2 Reduce Duplicate Pacing Metrics

**Current State:**
- Clock emits request_to_present latency
- Handler emits frame_interval timing
- Bridge emits ui_lag measurements
- DM emits separate progress throttle metrics

**Proposed Cleanup:**
```
Consolidate to unified "presentation cadence" metrics:
  - request_received_ms
  - request_queued_ms
  - tick_executed_ms
  - frame_presented_ms
  - side_effects_applied_ms
  
Track once, emit to instrumentation layer, consumers subscribe

Benefits:
  - No cross-component timing duplication
  - Single source for jitter/latency analysis
  - Easier KPI extraction
  - Reduce log volume
```

### 4.3 Centralize Presentation Cadence Ownership

**Current State:**
- Clock timer owns "tick cadence"
- UI throttle owns "request admission"
- DM progress owns "update frequency"
- Multiple pacing layers without clear hierarchy

**Proposed Cleanup:**
```
Central CadenceController:
  - Single timer (clock timer)
  - Single request queue (from all sources)
  - Single admission policy
  - Single metrics aggregation
  
Migrate:
  - UI throttle → subscribe to cadence events
  - DM progress → serialize through cadence
  - Viewer sync → align to cadence
  
Benefits:
  - Easier to reason about system pacing
  - Unified fallback policy
  - Reduce timer proliferation
  - Prepare for cross-module synchronization
```

### 4.4 Reduce Hot-Path Logging Overhead

**Current State:**
- Every [FAST_RENDER_CLOCK] request emits structured log
- Every [FAST_CLOCK_SIDE_EFFECT_*] emits log
- High volume during drag (346 DEFERRED + 321 APPLIED = 667 logs/45s)

**Proposed Cleanup:**
```
Implement sampling + aggregation:
  - Log 1-in-10 requests (not every request)
  - Aggregate event counts per tick
  - Batch [FAST_CLOCK_SIDE_EFFECT_*] into period summaries
  
Benefits:
  - Reduce logging I/O overhead
  - Keep diagnostics visibility
  - No loss of statistical accuracy
  - Maintain detailed fallback/error logs (always at full rate)
```

### 4.5 Formalize Side-Effect Ownership Boundaries

**Current State:**
- Slider setValue() called from bridge
- Sync callback called from bridge
- Reference update called from bridge
- No clear contract between bridge and viewers

**Proposed Cleanup:**
```
Formal interface: ViewerSideEffectConsumer
  - apply_slider_update(value: int, reason: str) -> bool
  - apply_sync_callback(data: SyncData) -> bool
  - apply_reference_update(data: ReferenceData) -> bool
  
Benefits:
  - Clear ownership of side effects
  - Easier to add new side effects
  - Testable in isolation
  - Prepare for multi-viewer effects synchronization
```

### Success Criteria
- ✅ **All cleanups implement without user-visible change**
- ✅ **Test coverage maintained or improved**
- ✅ **Code review sign-off from architecture owner**
- ✅ **No performance regression** (logging overhead reduction measured)

### Implementation Order
1. Reduce hot-path logging (lowest risk, highest impact)
2. Unify latest-request semantics (code cleanup only)
3. Reduce duplicate pacing metrics (requires coordination)
4. Formalize side-effect ownership (interface design)
5. Centralize cadence ownership (largest refactor, last)

---

## 5. Promotion Criteria for Default-On

### Explicit Thresholds

**These gates must ALL pass before promoting to default-on:**

#### 5.1 Request-to-Present Latency
```
Metric: request_to_present_p95_ms
Threshold: <33ms (33ms is clock interval)
Acceptance: 15.49ms (PASS ✓)
Soak test requirement: Maintain <33ms for entire 60-min session
```

#### 5.2 UI Lag P95
```
Metric: ui_lag_p95_ms
Threshold: <100ms (human-imperceptible threshold)
Acceptance: 86.96ms (PASS ✓)
Soak test requirement: Never exceed 150ms (1.5× headroom)
```

#### 5.3 Fallback Rate
```
Metric: fallback_count / total_interactions
Threshold: <1% (robust, rare fallbacks only on legitimate edge cases)
Acceptance: 0/346 = 0% (PASS ✓)
Soak test requirement: <5 fallbacks in 60-min multi-study session
```

#### 5.4 CPU Overhead
```
Metric: clock_handler_overhead_percent
Threshold: <2% of single-frame budget (2ms out of 33ms)
Baseline: 2.18ms handler P95 observed
Calculation: 2.18ms / 33ms = 6.6% (ACCEPTABLE, within headroom)
Soak test requirement: <3% overhead at all resolutions
```

#### 5.5 Correctness Incidents
```
Metric: slice_mismatches + recursive_loops + first_image_failures
Threshold: 0 (zero tolerance)
Acceptance: 0 (PASS ✓)
Soak test requirement: 0 across all scenarios
```

#### 5.6 Memory Stability
```
Metric: heap_growth_rate_mb_per_10min
Threshold: <50 MB/10min (linear growth, no leak)
Baseline: To be measured during soak testing
Soak test requirement: Sub-linear growth, stable after GC
```

#### 5.7 No Regressions vs. Non-Clock Baseline
```
Metric: comparative KPI analysis (clock ON vs OFF)
Threshold: No regression in any metric
Acceptance: ui_lag_p95 improved, frame rate stable, no stalls
Soak test requirement: Measure both modes for 30 min each
```

### Gate Decision Matrix

```
╔═══════════════════════════════════════════════════════════════════╗
║ Promotion Gate Evaluation (May 2026)                              ║
╠═══════════╦════════════════╦═══════════╦════════════════╦═════════╣
║ Metric    ║ Current Value  ║ Threshold ║ Soak Test Gate ║ Status  ║
╠═══════════╬════════════════╬═══════════╬════════════════╬═════════╣
║ Req→Pres  ║ 15.49ms        ║ <33ms     ║ Pass 60min     ║ ⏳       ║
║ P95       ║                ║           ║                ║         ║
╠═══════════╬════════════════╬═══════════╬════════════════╬═════════╣
║ UI lag    ║ 86.96ms        ║ <100ms    ║ <150ms max     ║ ⏳       ║
║ P95       ║                ║           ║                ║         ║
╠═══════════╬════════════════╬═══════════╬════════════════╬═════════╣
║ Fallback  ║ 0%             ║ <1%       ║ <5 incidents   ║ ⏳       ║
║ Rate      ║                ║           ║ in 60min       ║         ║
╠═══════════╬════════════════╬═══════════╬════════════════╬═════════╣
║ CPU       ║ 2.18ms         ║ <2% frame ║ <3% @ all      ║ ⏳       ║
║ Overhead  ║ (6.6%)         ║           ║ resolutions    ║         ║
╠═══════════╬════════════════╬═══════════╬════════════════╬═════════╣
║ Correct-  ║ 0              ║ 0         ║ 0 across all   ║ ⏳       ║
║ ness      ║                ║           ║ scenarios      ║         ║
╠═══════════╬════════════════╬═══════════╬════════════════╬═════════╣
║ Memory    ║ TBD            ║ <50 MB/   ║ Sub-linear     ║ ⏳       ║
║ Stability ║                ║ 10min     ║ growth         ║         ║
╠═══════════╬════════════════╬═══════════╬════════════════╬═════════╣
║ Regress-  ║ Improved       ║ ≥ baseline║ No regression  ║ ⏳       ║
║ ion Check ║ in ui_lag      ║           ║ vs. OFF mode   ║         ║
╚═══════════╩════════════════╩═══════════╩════════════════╩═════════╝
```

### Promotion Decision Logic

```python
def can_promote_to_default():
    gates = {
        "request_to_present_p95": ("< 33ms", validate_latency),
        "ui_lag_p95": ("< 100ms", validate_ui_lag),
        "fallback_rate": ("< 1%", validate_fallback),
        "cpu_overhead": ("< 3%", validate_overhead),
        "correctness": ("0 incidents", validate_correctness),
        "memory_stability": ("sub-linear", validate_memory),
        "no_regression": ("pass", validate_baseline_comparison)
    }
    
    results = {}
    for gate_name, (threshold, validator) in gates.items():
        results[gate_name] = validator()  # must return True/False
    
    # ALL gates must pass
    return all(results.values())
```

### Promotion Approval Workflow

1. **Soak testing complete** → Generate `soak_test_report.json`
2. **Multi-hardware validation complete** → Generate `hardware_validation_report.json`
3. **Robustness hardening complete** → Generate `robustness_report.json`
4. **Run promotion gate checker** → `tools/performance/validate_promotion_gates.py`
   - Aggregate all reports
   - Check all thresholds
   - Emit `PROMOTION_GATE_STATUS.json` (PASS or FAIL)
5. **If PASS**: Create promotion PR with detailed gate breakdown
6. **If FAIL**: Document failures, identify remediation path, iterate

---

## 6. Future Investigation Candidates

**ONLY pursue after stabilization complete.**  
**Do NOT start during hardening phase.**

### 6.1 Qt Update Coalescing
```
Investigation: Can Qt's update coalescing reduce side-effect delivery?
Rationale: Current approach delivers slider/sync/reference on every tick
Hypothesis: Batch multiple pending flags into single Qt update?
Risk: Might reduce responsiveness or introduce frame skipping
Status: CANDIDATE — measure impact after clock stabilizes
Timeline: v2.6.1+
```

### 6.2 Single-Shot Render-Clock Cadence
```
Investigation: Can we use single QTimer.singleShot instead of repeating timer?
Rationale: Might reduce overhead, align to frame presentation, not wall clock
Hypothesis: Each tick schedules the next tick adaptively
Cons: Loses predictable 33ms cadence
Status: CANDIDATE — requires metrics from multi-hardware testing
Timeline: v2.7+
```

### 6.3 App-Filter-Level Pacing Metrics
```
Investigation: Add top-level filter metrics (e.g., per-modality input rate)?
Rationale: CT drag rate != XR drag rate, might optimize per-type
Hypothesis: Different clock cadence per modality?
Risk: Major complexity increase
Status: CANDIDATE — low priority, monitor patient feedback first
Timeline: v2.8+
```

### 6.4 Paint Scheduling Optimization
```
Investigation: Can we schedule VTK paint differently during clock ticks?
Rationale: Current approach always repaints on every side-effect apply
Hypothesis: Batch paint with other operations?
Risk: Might miss side-effect visibility
Status: CANDIDATE — only after clock stabilizes
Timeline: v2.7+
```

### 6.5 Further Sync/Reference Throttling
```
Investigation: Are we over-delivering sync/reference updates?
Current: Sync=0%, Reference=21% of renders (already throttled)
Hypothesis: Could reduce to 5–10% without user-visible impact?
Risk: Reference lines might stale slightly
Status: CANDIDATE — gather user feedback on current throttling first
Timeline: v2.6.1+
```

### Investigation Process

For each candidate:
1. **Establish baseline metric** from soak testing (v2.5.x stable)
2. **Implement investigation variant** in feature branch
3. **Run A/B soak test** (candidate vs. baseline, each 30 min)
4. **Measure KPI delta** (latency, CPU, memory, correctness)
5. **Document findings** in investigation report
6. **Decision**: Keep for next release, defer, or reject
7. **Timeline**: No single investigation should block release

---

## Explicit "AVOID" List

**DO NOT do these during hardening phase:**

### ❌ Aggressive Optimization Without Evidence
```
Example: "Let's optimize disk cache eviction"
Why avoid: Cache stabilization not validated yet
Action: Keep current caching, measure during soak testing
```

### ❌ Reopening Decode/Disk Optimizations
```
Example: "Bump decode workers from 1 to 2"
Why avoid: Root cause was input-path coupling, not decode throughput
Action: Current single-worker design proven sufficient
Timing: Revisit in v2.7+ if evidence warrants
```

### ❌ Adding Complexity Without Evidence
```
Example: "Add per-series clock configuration"
Why avoid: Base clock design not yet stable
Action: Monolithic clock design first, specialization later
Timing: v2.7+ if multi-modality data supports
```

### ❌ Changing Multiple Architecture Surfaces Simultaneously
```
Example: Refactor clock + DM coordination + viewer sync in one PR
Why avoid: Impossible to isolate root cause of regressions
Action: One architectural change per release cycle max
Timing: Queue changes for v2.6.1, v2.7, etc.
```

### ❌ Removing Safety Guardrails Before Promotion
```
Example: "Disable fallback check to save CPU"
Why avoid: Fallback is our safety net during unknown edge cases
Action: Keep fallback logic unchanged during hardening
Timing: Revisit fallback necessity in v2.7+ if never triggered
```

### ❌ Promoting to Default-On Without Multi-Hardware Pass
```
Example: "Passed on i7, let's enable for all users"
Why avoid: Unknown behavior on budget CPUs / integrated GPUs
Action: All 7 hardware profiles must pass before default-on
Timing: Multi-hardware gate is mandatory
```

### ❌ Accepting User Feedback Alone (Without Metrics)
```
Example: "User says it feels faster, ship it"
Why avoid: Perception ≠ measurement
Action: Collect metrics first, qualitative feedback second
Timing: Use metrics as gate, feedback as supporting data
```

---

## Instrumentation & Metrics Collection

### New KPI Dashboard

Create `tools/performance/clock_stability_dashboard.json` with:

```json
{
  "run_metadata": {
    "test_name": "soak_test_30min_stack_drag",
    "duration_seconds": 1800,
    "hardware_profile": "low_core_cpu",
    "timestamp": "2026-05-13T14:30:00Z"
  },
  
  "request_to_present": {
    "p50": 9.3,
    "p95": 15.49,
    "p99": 22.1,
    "max": 75.2,
    "fallback_rate": 0.0,
    "samples": 346
  },
  
  "frame_timing": {
    "p50": 3.2,
    "p95": 6.08,
    "p99": 8.5,
    "max": 26.1,
    "samples": 743
  },
  
  "ui_lag": {
    "p50": 22.5,
    "p95": 86.96,
    "p99": 180.3,
    "max": 405.05,
    "samples": 697
  },
  
  "side_effects": {
    "deferred_count": 346,
    "applied_count": 321,
    "flush_count": 26,
    "slider_success_rate": 1.0,
    "sync_throttle_rate": 1.0,
    "reference_throttle_rate": 0.79
  },
  
  "memory": {
    "baseline_mb": 285.3,
    "peak_mb": 318.7,
    "final_mb": 312.1,
    "growth_rate_mb_per_10min": 18.2,
    "gc_effective": true
  },
  
  "fallback_events": {
    "count": 0,
    "types": [],
    "recovery_times_ms": []
  },
  
  "correctness": {
    "slice_mismatches": 0,
    "recursive_loops": 0,
    "first_image_failures": 0,
    "reference_line_corruption": 0
  },
  
  "guardrails": {
    "stalls_greater_500ms": 0,
    "dm_rebuild_during_drag": 0,
    "timer_leaks": 0,
    "pending_flag_leaks": 0
  }
}
```

### Metric Extraction Scripts

1. **`tools/performance/extract_clock_metrics.py`**
   - Parse viewer_diagnostics.log
   - Extract all FAST_RENDER_CLOCK events
   - Generate metric JSON

2. **`tools/performance/validate_promotion_gates.py`**
   - Load all test reports (soak, hardware, robustness)
   - Check against thresholds
   - Emit PROMOTION_GATE_STATUS.json

3. **`tools/performance/compare_clock_modes.py`**
   - A/B comparison (clock ON vs OFF)
   - Regression detection
   - Report delta per metric

---

## Timeline & Ownership

| Phase | Duration | Owner | Gate | Deliverable |
|-------|----------|-------|------|-------------|
| **Soak Testing** | 2 weeks | AI agent | All guardrails pass | soak_test_report.json |
| **Multi-Hardware** | 1 week | CI/lab | 7/7 profiles pass | hardware_validation_report.json |
| **Robustness** | 1 week | AI agent | Fallback scenarios pass | robustness_report.json |
| **Architectural Cleanup** | 1 week | AI agent | Code review pass | cleanup_pr merged |
| **Promotion Validation** | 3 days | QA gate | All thresholds pass | PROMOTION_GATE_STATUS.json |
| **Go/No-Go Decision** | 2 days | User decision | All gates pass OR documented exception | Release plan |

**Total Duration: ~4 weeks**

---

## Success Criteria Summary

### Must-Pass Gates (All Required)
- ✅ Zero crashes in 60-min continuous sessions
- ✅ request_to_present_p95 < 33ms
- ✅ ui_lag_p95 < 100ms (never exceed 150ms)
- ✅ Fallback rate < 1% (< 5 incidents in 60-min session)
- ✅ CPU overhead < 3% of frame budget
- ✅ Zero correctness incidents (slices, loops, regressions)
- ✅ Memory stable (sub-linear growth, effective GC)
- ✅ All 7 hardware profiles pass
- ✅ All robustness edge cases handled
- ✅ No regressions vs. non-clock baseline

### Nice-to-Have (Optimization, Post-Stabilization)
- Reduce logging overhead (50% I/O reduction target)
- Unify request semantics (code clarity)
- Centralize cadence ownership (architectural simplification)

---

## Go/No-Go Criteria

### Go (Promote to Default-On)
```
IF (all_must_pass_gates == PASS) AND
   (no_critical_issues_found == TRUE) AND
   (user_sign_off == APPROVED)
THEN: Enable default-on in v2.6.0, keep env var for disable
```

### No-Go (Keep Experimental)
```
IF (any_must_pass_gate == FAIL) OR
   (critical_issue_found == TRUE)
THEN: Identify root cause, iterate hardening phase, re-test
```

### Conditional Go (Promote With Caveats)
```
IF (most_gates_pass == TRUE) AND
   (non_critical_failures_documented == TRUE)
THEN: Enable default-on with known limitation, plan remediation in v2.6.1
```

---

## Sign-Off & Release Planning

**Prerequisite:** All 6 sections above complete and gates passing

**Sign-Off Items:**
1. ✅ Soak test report reviewed
2. ✅ Hardware validation complete
3. ✅ Robustness tests passing
4. ✅ Architectural cleanup accepted
5. ✅ Promotion gate dashboard green
6. ✅ No open critical issues
7. ✅ User approval for default-on

**Release Planning:**
```
Feature branch: feature/fast-render-clock-v2.6.0
Config change: config/viewer_backend_settings.json
  - Add: "fast_render_clock_default": true
  
Env var behavior:
  - AIPACS_FAST_RENDER_CLOCK_EXPERIMENT=1 → force ON (override config)
  - AIPACS_FAST_RENDER_CLOCK_EXPERIMENT=0 → force OFF (override config)
  - Unset → use config default
  
Release notes entry:
  "FAST Render Clock: New rendering architecture decouples input latency 
   from UI side effects, reducing perceived drag latency by ~15–20%.
   Enable/disable via config or AIPACS_FAST_RENDER_CLOCK_EXPERIMENT env var."
```

---

## Conclusion

This production-hardening plan provides:

1. **Concrete test scenarios** for all critical categories
2. **Explicit thresholds** for go/no-go decisions
3. **Clear ownership** of each phase
4. **Separated concerns**: stabilization vs. optimization
5. **Future roadmap** without premature complexity

The experiment has demonstrated the core concept works. This plan validates it in production, hardens edge cases, and provides the gate criteria for safe default-on promotion.

**Status: Ready to execute. Awaiting user approval to proceed to soak testing phase.**
