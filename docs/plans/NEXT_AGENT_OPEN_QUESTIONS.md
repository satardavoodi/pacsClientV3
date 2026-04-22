# NEXT AGENT OPEN QUESTIONS — Block A / Block B / KPI / ClearCanvas

These are the current open questions that matter for the next phase of the roadmap.

---

## Q1 — Did the small-stack fast-prefetch reduction actually lower overlap CPU?

**Why it matters:**  
The visible drag path was already fast in the recent manual log review. The purpose of reducing small-stack `fast_prefetch_radius` to `4` was to cut background CPU without hurting visible interaction.

**What answers it:**
- collect a fresh runtime log after the radius change,
- compare CPU peak / CPU summary against the prior manual run,
- verify sampled `[B3.8_SCROLL]` frames remain low-latency and mostly `decode_ms=0.0`.

**If yes:** keep the tighter radius and move to the next control-plane hotspot.  
**If no:** inspect remaining non-visible work before touching decode.

---

## Q2 — Is the remaining bottleneck now mostly admission/fan-out rather than decode?

**Why it matters:**  
Current evidence strongly suggests the visible frame path is no longer the first suspect.

**Current best guess:** yes.

**Evidence already pointing that way:**
- cache-hot runtime drag frames were already cheap,
- `decode_ms=0.0` appeared in sampled scroll logs,
- CPU still spiked,
- older headless overlap captures also kept stale/control-plane pressure suspiciously high.

**What answers it better:**
- fresh runtime log after the latest radius trim,
- comparison of visible-frame cost vs background CPU,
- inspection of non-interactive admissions during the same interval.

---

## Q3 — What is the next safest Block B split inside `_vc_switch.py`?

**Why it matters:**  
Block B improved, but `_vc_switch.py` still owns too much. The next cleanup should reduce ownership without destabilizing the first-visible-image path.

**Current best guess:**
Split further into:
1. request validation / token checks,
2. first-frame apply path,
3. deferred follow-up orchestration.

**Constraint:**
The current startup/layout zoom fix and immediate spinner/layout stabilization must stay intact.

---

## Q4 — How much Block A state authority still lives in UI code?

**Why it matters:**  
Block A is cleaner than before, but the sidebar should keep moving toward projection-only behavior.

**What to inspect next:**
- `thumbnail_panel.py`
- `thumbnail_manager.py`
- any remaining direct fallback or state-decision logic inside panel/widget code

**Desired answer:**
The sidebar should consume canonical state, not invent or arbitrate it.

---

## Q5 — When should ClearCanvas runtime benchmarking be resumed?

**Why it matters:**  
The architecture comparison and harness prep are done, but the actual same-machine runtime benchmark is still blocked.

**Current best answer:**
Resume only if environment/setup work is allowed and useful now.

**Blocking prerequisites already known:**
- .NET Framework 4.0 targeting pack
- `ReferencedAssemblies`
- successful ClearCanvas viewer build

Until then, keep using the existing AI-PACS simulation/common/overlap captures as the practical KPI baseline.
