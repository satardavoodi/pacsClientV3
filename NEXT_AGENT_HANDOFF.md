# NEXT AGENT HANDOFF — Block A / Block B / KPI / ClearCanvas

**Date:** 2026-04-20  
**Scope:** FAST mode only unless explicitly stated otherwise. Advanced viewer is out of scope for this handoff.

---

## 1. Read this first

Start here:

- `docs/plans/BLOCK_A_B_KPI_CLEARCANVAS_HANDOFF_2026-04-20.md`

That file is now the canonical handoff for:

- what was already completed,
- how Block A / Block B / Block C should be optimized next,
- what the KPI evidence currently says,
- what was actually done with the ClearCanvas comparison/simulation.

---

## 2. Short current status

### Already completed

- Block A structural cleanup moved thumbnail flow closer to a projection pipeline.
- Block B hot path was narrowed so first-visible work stays immediate while lower-priority follow-up runs later.
- Fresh Qt viewer startup now queues one guarded next-tick refit, fixing the “last series inserted into layout has wrong zoom” regression.
- Small-stack FAST interaction policy was tightened so stacks `<= 24` use `fast_prefetch_radius = 4` instead of a wider fast band.

### Current KPI truth

- Recent runtime logs show the visible drag path is already very fast when cache-hot.
- Recent sampled scroll frames were in the low-millisecond class with `decode_ms = 0.0`.
- CPU can still spike during overlap / cold-open windows.
- That means the next bottleneck is more likely background/control-plane pressure than foreground decode.

### ClearCanvas status

- Static comparison work is done and documented.
- Benchmark harness + execution flow are prepared.
- AI-PACS baseline/common/overlap simulation captures already exist (`run_001`, `run_002`).
- Real ClearCanvas runtime benchmark is still blocked by environment/build prerequisites.

---

## 3. What to do next

1. Read the canonical handoff doc.
2. Collect a fresh runtime log for the small-stack drag scenario after the `fast_prefetch_radius = 4` change.
3. Compare CPU and scroll behavior against the earlier manual log findings.
4. If CPU is still too high, optimize admission/fan-out/control-plane work before touching decode again.

---

## 4. Critical guardrails

Do **not**:

1. remove the Qt startup refit fix,
2. widen the small-stack fast prefetch radius again without new measurements,
3. move Block C work back into the first-image-visible path,
4. treat ClearCanvas runtime benchmarking as “done” yet.

---

## 5. Core interpretation to preserve

The current roadmap center is:

> keep Block A as cheap projection, keep Block B as first-frame authority, and keep Block C from spending CPU early unless the user already has a stable visible image.
