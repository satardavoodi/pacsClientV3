# FAST Viewer Performance Roadmap (Planning-First)

**Date:** 2026-04-14  
**Scope:** FAST viewer only (`BACKEND_PYDICOM_QT`) with concurrent download/viewing reality.  
**Purpose:** Controlled, KPI-driven execution order before implementation.

## 1) Why this roadmap exists

Performance work can no longer optimize isolated viewer paths only. Real usage includes overlap of:
- slice scrolling
- decode/render
- progressive download
- filtering and overlays
- sync/reference updates
- metadata/background operations

This roadmap enforces **one bottleneck at a time**, **one measurable change at a time**, and **stop/go checkpoints** after every step.

## 2) Known performance problems (current state)

1. **GIL convoy risk in decode path** during cache miss overlap (main thread + decode workers).
2. **Hardcoded worker sizes** do not adapt well across low-end and high-end systems.
3. **Weak cross-subsystem coordination**: queue pressure, stale work, and cancellation signals are not centrally governed.
4. **Timer overlap pressure**: progress/grow/debounce timers can collide with hard-interactive frames.
5. **Evidence fragmentation**: component metrics and system contention metrics were not previously cataloged in one KPI model.

Primary reference evidence: `CONCURRENCY_ANALYSIS_v2.3.3.md`.

## 3) Goals

### Short-term (Planning + Baseline)
- Establish complete KPI catalog (component + system-level).
- Define workload priority classes and scheduling policy.
- Define standard scenario matrix for repeated KPI capture.
- Capture baseline numbers for each scenario and hardware profile.

### Mid-term (Incremental optimization)
- Improve hard-interactive responsiveness first (slice/paint/frame readiness).
- Reduce contention-induced jank under download overlap.
- Reduce stale/canceled work waste and queue buildup.

### Long-term (Architectural stabilization)
- Introduce robust resource governance and adaptive tuning.
- Keep FAST mode Qt-native and Advanced mode isolated.
- Sustain KPI guardrails in CI/manual loops.

## 4) Ordered execution phases

## Phase P0 — Planning hardening (this phase)
**Outputs:**
- master plan performance section update
- KPI catalog
- workload/contention model
- scenario test plan
- execution strategy and review checklist

**Checkpoint P0 (GO/NO-GO):**
- all required docs exist and cross-reference each other
- first dominant problem selection protocol is explicit
- no implementation optimization merged yet

## Phase P1 — Baseline instrumentation + capture
**Bounded scope:**
- add/verify KPI probes needed by catalog only
- run scenario suite in baseline mode
- collect profile data for low/mid/high hardware

**Checkpoint P1:**
- baseline KPI sheet complete (no empty required fields)
- logs/test traces reproducible
- baseline accepted by reviewer

## Phase P2 — Hard-interactive bottleneck #1
**Bounded scope:**
- choose dominant bottleneck using protocol
- implement one contained change
- run targeted scenarios + compare deltas

**Checkpoint P2:**
- hard-interactive KPIs improved
- no system-level contention regression
- visual correctness unchanged

## Phase P3 — Contention and scheduling pass
**Bounded scope:**
- one scheduling/cancellation/backpressure improvement at a time
- verify queue-depth and stale-task reduction under load

**Checkpoint P3:**
- foreground wait and jank KPIs improve
- no starvation or fairness regressions

## Phase P4 — Adaptive tuning by hardware profile
**Bounded scope:**
- profile-based worker budgets and queue limits
- low-end profile protection first, then high-end unlock

**Checkpoint P4:**
- low-end stability/responsiveness pass
- high-end throughput gains without hard-interactive regressions

## Phase P5 — Stabilization and documentation closure
**Bounded scope:**
- lock in accepted knobs/limits
- remove temporary probes if no longer needed
- update release/performance docs

**Checkpoint P5:**
- acceptance checklist fully green
- docs reflect final operational guidance

## 5) Dependencies between phases

- P1 depends on P0 docs + KPI schema.
- P2 depends on P1 baseline evidence.
- P3 depends on at least one completed P2 bottleneck iteration.
- P4 depends on validated scheduling behavior from P3.
- P5 depends on stable KPI trend from P2–P4.

## 6) Stop/Go policy for each optimization step

After every optimization step:
1. Compare KPI deltas against baseline and previous step.
2. Apply decision:
   - **GO**: measurable hard-interactive gain, no major regressions.
   - **REVISE**: mixed results or weak confidence.
   - **STOP/REVERT**: hard-interactive regression, starvation increase, or correctness risk.
3. Update docs immediately (roadmap + KPI + scenario notes).

## 7) Execution constraints

- No broad rewrite.
- No optimization without KPI evidence.
- One bottleneck per iteration.
- One bounded change per iteration.
- Preserve Advanced mode behavior.
- Do not reintroduce VTK into FAST mode.
- Prioritize user responsiveness over background throughput.

## 8) Cross-reference map

- Workload/contention model: `CONCURRENCY_ANALYSIS_v2.3.3.md`
- KPI definitions: `FAST_VIEWER_KPI_CATALOG.md`
- Scenario plan: `FAST_VIEWER_TEST_SCENARIOS.md`
- Current implementation notes: `FAST_VIEWER_PERF_OPTIMIZATION.md`
