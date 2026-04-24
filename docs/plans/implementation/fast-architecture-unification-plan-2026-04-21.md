# FAST architecture unification plan — 2026-04-21

## Goal

This document answers one question from a true top-down view:

> Is the FAST app now architecturally unified, or is it still a set of patchy islands that only happen to cooperate?

Short answer:

- **better than before:** yes
- **fully unified yet:** no
- **salvageable with incremental refactoring:** absolutely yes

The recent fixes improved consistency, but the system still has multiple adjacent truth sources for:

- series identity
- expected slice count
- completion state
- terminal download authority
- disk-vs-viewer-vs-metadata reconciliation

That means the current runtime is **coordinated**, but not yet **single-authority**.

---

## What is already better now

The recent conservative refactor slices moved the app in the right direction:

1. `PacsClient/utils/series_identity.py`
	 - shared identity normalization for UID/series-number resolution

2. `PacsClient/utils/series_completeness.py`
	 - shared normalization for expected/disk/metadata/viewer completeness decisions

3. controller-side expected-count routing improved
	 - remaining controller callsites in `_vc_switch.py` and `_vc_load.py` now use
		 `_get_series_expected_slices(...)`
	 - this is better than controllers reaching back into widget-local
		 `_get_expected_series_image_count(...)`

These changes matter because they reduce accidental disagreement in the hottest FAST paths.

---

## Top-down verdict

## The current app is **functionally layered** but not yet **authority-unified**

From above, the FAST runtime today is roughly this:

- **Block A**
	- download bootstrap
	- thumbnail/server-series projection
	- DM → widget progress normalization

- **Block B**
	- first visible image
	- explicit viewer-target admission
	- release barrier for deferred open work

- **Block C**
	- progressive grow
	- viewer-visible admission gating
	- completion repair
	- cache warm / post-completion follow-up

- **DB / disk / metadata side**
	- persistent study/series/instance facts
	- runtime repair when DB is stale or incomplete during active download

This is a valid architecture shape.

What is still missing is a single shared **facts layer** that composes the truth consumed by all of those blocks.

Right now, each block is more disciplined than before, but several still build or resolve the same facts locally.

That is why the app can still feel like:

- one part is “controller truth”
- one part is “thumbnail truth”
- one part is “DM truth”
- one part is “disk truth”
- one part is “viewer truth”

instead of one coherent system with clear ownership.

---

## What is unified today

## 1. Terminal DM projection is mostly unified

`PacsClient/pacs/workstation_ui/home_ui/home_download_service.py` is now the real viewer-facing terminal authority.

That is good architecture.

It already owns:

- provisional progress filtering
- duplicate completion suppression
- normalized final completion pulse
- DM → widget fan-out gating

This means raw DM signals are no longer allowed to spray inconsistent completion behavior directly into the viewer path.

That is a strong unification win.

## 2. Progressive lifecycle has a clearer single owner than before

`_vc_progressive.py` is the real owner of:

- progressive state map
- done/inflight guards
- terminal-complete guard
- finalization guard
- Layer 2b / Layer 3 / Layer 4 completion repair

That is also better than before.

## 3. Controller count lookup is improving

`_vc_backend.py::_get_series_expected_slices(...)` is becoming the controller-side authority for expected slice counts.

That is the right direction.

---

## What is still patchy

## 1. Expected-count authority still exists in two adjacent worlds

There are still two different places answering “how many slices should this series have?”

- controller side:
	- `_vc_backend.py::_get_series_expected_slices(...)`

- thumbnail/widget side:
	- `_pw_thumbnails.py::_get_expected_series_image_count(...)`

These are similar, but not identical in ownership or call graph.

That is still a structural smell.

### Why it matters

If Block B / C and thumbnail state do not compose expected count the same way, then:

- a thumbnail can say complete while a viewer still thinks incomplete
- a viewer can skip work while thumbnail/DM still thinks the series is partial
- warmup and progressive repair can make different choices for the same series

## 2. Completeness is normalized, but count collection is not yet unified

`series_completeness.py` is intentionally read-only.

That was the correct first step.

But it means callers still collect these inputs themselves:

- expected count
- metadata count
- disk count
- viewer-visible count

The comparisons are now more consistent.
The **count gathering** is not fully consistent yet.

This is the biggest remaining reason the FAST path still feels architecturally distributed.

## 3. Identity is improved, but not owned by one metadata authority

`series_identity.py` helped, but series identity is still assembled from multiple local maps:

- thumbnail uid→number map
- widget `_server_series_info`
- DM task series list
- DB lookup patterns

The helper is shared, but the underlying sources are still spread across layers.

## 4. Block C still mixes correctness policy and performance policy

`_vc_progressive.py` still contains both:

- correctness
	- finalization
	- completion repair
	- stale recovery
	- lifecycle closure

- performance
	- grow cadence
	- protected UI deferral
	- cache warm admission
	- viewer-visible admission rate

This works, but it means tuning performance can still affect correctness behavior indirectly.

## 5. DB is a persistence authority, but not yet wrapped by a runtime metadata authority

The DB layer is doing the right low-level thing:

- uses `get_db_connection()`
- commits writes explicitly
- exposes update/fetch helpers

But runtime FAST code still has to decide when to trust:

- DB count
- server count
- DM task count
- `metadata['instances']`
- disk file count

That decision is still distributed.

The DB is clean enough.
The runtime authority above it is what is still missing.

---

## Architecture truth table: what each layer should own

To stop the app feeling patchy, each layer needs exactly one job.

## Block A should own only projection and bootstrap

Block A should be responsible for:

- download bootstrap
- DM → widget projection
- thumbnail projection
- initial metadata seeding

Block A should **not** be deciding viewer completeness or late disk repair logic.

## Block B should own only explicit viewer admission

Block B should be responsible for:

- first visible image
- explicit viewer-target load/switch
- release of deferred open work

Block B should **not** be recomputing its own series facts independently.

## Block C should own viewer lifecycle, not raw facts composition

Block C should be responsible for:

- progressive lifecycle
- viewer-visible admission
- terminal finalization
- repair ticks
- cache-warm scheduling

Block C should consume already-composed series facts.
It should not need to keep building them ad hoc.

## DB should own persistence, not active runtime truth

DB should provide durable facts.

Runtime should decide active truth using a shared metadata/facts layer, not direct one-off per-caller interpretation.

---

## The missing architecture piece

The app needs one shared **Series Facts / Metadata Authority** layer.

This should be a small reusable service/helper layer, not a mega rewrite.

It should answer these questions consistently for all FAST consumers:

- what is the canonical series number?
- what is the best expected image count?
- what is the metadata instance count?
- what is the disk file count?
- what is the viewer-visible count?
- is the series incomplete?
- is disk complete?
- is viewer complete?
- which source won and why?

That would convert the system from:

- “many smart local decisions”

to:

- “one shared facts model consumed by local policies”

That is the architectural difference between a system and a collection of careful exceptions.

---

## Recommended refactor program

## Phase 1 — finish shared facts composition

Add one controller-side helper/service that returns a structured snapshot like:

- `series_number`
- `expected_count`
- `metadata_count`
- `disk_count`
- `viewer_visible_count`
- `source_flags`

Candidate direction:

- `PacsClient/utils/series_facts.py`
	or
- controller-local helper in `_vc_cache.py` first, then promote once stable

This should be used in:

- `_vc_switch.py`
- `_vc_load.py`
- `_vc_progressive.py`

## Phase 2 — bridge thumbnail world onto the same facts layer

Replace or thin `_pw_thumbnails.py::_get_expected_series_image_count(...)` so it delegates to the shared facts composition path instead of maintaining a second near-duplicate authority.

Important:

- thumbnail UI can still project its own state
- but expected-count truth should not be locally reinvented there

## Phase 3 — separate correctness policy from cadence policy in Block C

Keep in `_vc_progressive.py`:

- lifecycle transitions
- finalization
- repair ownership

Move or isolate:

- cadence decisions
- defer/admit policy
- cache-warm retry pacing

so that performance tuning cannot quietly redefine completion behavior.

## Phase 4 — introduce an explicit runtime metadata authority contract

Not necessarily a large class.

Even a narrow module with documented entry points would help:

- resolve identity
- compose counts
- explain chosen authority order
- provide “best runtime truth” snapshots

That becomes the contract between:

- DM projection
- thumbnails
- viewer controller
- progressive logic
- DB repair logic

---

## Smallest next code slices

These are the safest high-value steps.

### Slice 1

Create shared controller-side series facts builder and switch these callsites first:

- `_vc_switch.py`
- `_vc_load.py`
- `_vc_progressive.py`

### Slice 2

Refactor `_pw_thumbnails.py::_get_expected_series_image_count(...)` to delegate to the same facts source.

### Slice 3

Add focused tests that prove the same composed facts are used by:

- thumbnail completeness
- same-series switch logic
- post-completion reload suppression
- Layer 2b / 3 / 4 completion repair

That is the point where the architecture starts feeling truly unified.

---

## Performance impact of this architecture work

This is not just code prettiness.

It directly helps performance because unified authority removes duplicated work and contradictory control paths.

Expected gains:

- fewer redundant reload decisions
- fewer stale-cache races
- fewer duplicate completion actions
- fewer “show stale then repair” cases caused by inconsistent counts
- lower control-plane churn during download overlap
- less main-thread decision overhead from repeated local truth assembly

Most importantly, it improves **timing predictability**.

FAST systems feel smooth not only when they are fast on average, but when they avoid surprising re-entry, duplicate work, and UI-thread bursts.

---

## Final verdict

If I look at the whole pipeline from above today:

- **it is not random anymore**
- **it is not fully unified yet**
- **it still has patchy adjacent authorities**
- **the right next move is architectural consolidation, not another pile of local fixes**

So the answer to the core question is:

> No, the app is not yet fully “one consistent unified architecture.”
> It is now a much more disciplined multi-block system, but it still needs one shared runtime metadata/facts authority to stop feeling like coordinated islands.

That is the next step that will improve both:

- correctness
- performance stability
- timing smoothness
- maintainability

---

## Definition of success

The FAST pipeline will feel architecturally unified when these are true:

1. every FAST layer resolves series identity the same way
2. every FAST layer composes expected/disk/metadata/viewer counts the same way
3. Block A projects, Block B admits, Block C lifecycle-manages
4. DB persists, but runtime truth is composed by one shared facts authority
5. performance throttles do not own correctness decisions

When those five are true, the app stops being “patchy but careful” and becomes “architected and predictable.”
