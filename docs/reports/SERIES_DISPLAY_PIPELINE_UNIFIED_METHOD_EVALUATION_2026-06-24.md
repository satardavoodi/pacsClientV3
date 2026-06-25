# Series Load / Switch / Progressive / Metadata pipeline — Unified-Method Evaluation (2026-06-24)

**Scope ("these parts"):** the FAST viewer's series **load → switch → progressive-grow →
completeness → metadata** machinery I worked in this session:
`_vc_switch.py` (change-series authority), `_vc_load.py` (load authority + post-complete gate),
`_vc_progressive.py` (progressive grow + completion + disk-ready resume watchdog),
`_vc_backend.py` (`_get_series_by_number_fast`, `_resolve_series_expected_count`),
`_vc_cache.py` (disk count, canonical metadata refresh/sync, cache layers),
`vtk_widget/qt_fast_container.py` (`switch_series` apply), and the shared predicate helper
`PacsClient/utils/series_completeness.py`.

**"The unified method"** is taken from the project's own as-built records, not invented here:
`docs/pipelines/unified-patient-study-pipeline.md` (§2, §4, §7–8),
`docs/pipelines/viewer-pipeline.md` ("Metadata ownership chain", "Post-Completion Reload
Suppression", "Viewer Metadata Sync"), and `series_completeness.py`'s own docstring.

**Verdict in one line:** these parts are **unified in *design* but only convention-enforced in
*practice***. The right primitives exist (one canonical metadata source, one completeness
predicate, one backend resolver, one metadata sink), but the **orchestration is sprawled across
13+ rebuild/grow/resume entry points that each independently gather counts from 4 disagreeing
sources and must each *remember* to call the canonical sync** — there is no structural chokepoint.
The 47793/47804/47842 "series stuck at 8 of N" freezes are the predicted failure of that
convention-based unification, not isolated bugs.

---

## 1. What the project means by "the unified method"

From the as-built docs, the unified method is five concrete principles:

1. **One shared authority per concern; never fork a parallel variant.**
   `unified-patient-study-pipeline.md` §4.7: *"Callers were consolidated onto the shared authority
   … Do not add a parallel resolver/payload/enqueue variant — extend the shared authority instead."*
2. **A single source of truth for data** (disk for files; one canonical metadata dict for
   instances). `viewer-pipeline.md` "Metadata ownership chain": `lst_thumbnails_data[i]["metadata"]`
   is the **SOURCE**, `ImageViewer2D.metadata` is a copy kept in sync.
3. **The pipeline terminates at a single sink** and everything downstream is clinically protected.
   `unified-patient-study-pipeline.md` §4.2: terminates at `set_server_series_info`; must never
   reach pixel load / geometry / VTK / MPR.
4. **Legacy = kill switch, not deletion** — every change flag-gated default-on, legacy preserved.
5. **Defense-in-depth at the sinks** — the central rule *and* a guard at each sink (cross-patient
   isolation is the model).

`series_completeness.py` states the same intent for this exact subsystem outright:
> *"…so FAST paths stop re-deriving slightly different truth tables in multiple places."*

So the bar to evaluate against is: **one authority, one source of truth, one chokepoint, no
forked paths, downstream clinically protected.**

---

## 2. Map of the parts (entry points, sources, authorities)

### 2.1 The good — real shared authorities already exist
| Concern | Single authority | Status |
|---|---|---|
| Backend selection | `resolve_viewer_backend(metadata, settings)` | ✅ used everywhere (`viewer-pipeline.md` "single authority") |
| Completeness *predicates* | `series_completeness.build_series_completeness_snapshot` | ✅ 12 use sites; pure, read-only |
| Canonical instance metadata | `lst_thumbnails_data[idx]['metadata']` + `_refresh_stored_metadata_instances` → `_sync_viewer_metadata_instances` | ✅ designed as the one source (`viewer-pipeline.md`) |
| Multi-study disk identity | `resolve_entry_study_location` / `_server_series_info` entry-authority | ✅ (CLAUDE.md "drag loads exact series") |
| Study-set resolution (upstream) | `patient_study_set.merge_study_uids` → `set_server_series_info` sink | ✅ the documented unified pipeline |

### 2.2 The problem — orchestration is sprawled, sources are fragmented

**13+ entry points can rebuild / grow / resume a viewer's volume**, each making its own decision:
`change_series_on_viewer` (`_vc_switch.py:122`) **and a second** `change_series_on_viewer`
(`thumbnail_panel.py:267`), `load_series_on_demand` (`_vc_load.py:2090`),
`_display_series_after_load` (`_vc_load.py:2567`), `_start_progressive_display`
(`_vc_progressive.py:1862`), `_grow_progressive_fast` (`:2406`), `_flush_progressive_grow_impl`
(`:2060`), `on_series_download_fully_complete` (`:3031`), `_completion_verify_series_impl`
(`:3362`), `_completion_sweep_tick_impl` (`:3548`), and **`_maybe_resume_awaiting_from_disk`
(`:1205`) — the disk-ready resume watchdog added after the doc's 5-path list was written.**

**4 independent "how many slices does this series have?" sources, read at ~57 sites:**
- server `_server_series_info` (**22** sites)
- viewer `get_count_of_slices()` (**17**)
- disk `_count_series_files_on_disk()` (**13**, behind a **1 s TTL cache**)
- resolved-expected `_resolve_series_expected_count()` (**5**)

The completeness *predicate* is shared (good), but **the counts it consumes are gathered
independently by each caller** — `series_completeness.py` explicitly says *"callers remain
responsible for collecting counts."* That seam is where the truth diverges.

**The canonical-sync invariant is hand-applied at ~10 sites** (`_refresh_and_sync_metadata` /
`_refresh_stored_metadata_instances` / `_sync_viewer_metadata_instances` across
`_vc_progressive.py` ×7, `_vc_switch.py` ×2, `_vc_load.py` ×1). `viewer-pipeline.md` itself lists
"5 grow paths" that must call the sync pair — but there are now more than 5, and **nothing
structurally guarantees a given path calls it.**

---

## 3. Evaluation against each principle

| # | Principle | Respected? | Evidence |
|---|---|---|---|
| 1 | One authority, no forked variant | **Partial** | Backend/completeness/metadata authorities exist, but rebuild **orchestration is forked 13×** and there are **two** `change_series_on_viewer` methods. |
| 2 | One source of truth | **Violated in practice** | 4 count sources read at ~57 sites; they disagree under load (47842/203: metadata=8, disk=120, viewer=8→99, expected=102/120 — four "truths"). The 1 s disk cache made even *one* source self-inconsistent (47804). |
| 3 | Terminate at a sink; downstream protected | **Respected** | All of this is **downstream** of `set_server_series_info`; none of my changes touched VTK/MPR geometry, slice order, orientation, or render. The clinical boundary held. |
| 4 | Legacy = kill switch | **Respected** | Every fix this session is flag-gated default-on (`AIPACS_POSTCOMPLETE_EXPECTED_GATE`, `AIPACS_GROW_FALLBACK_FORCE_RELOAD`, `AIPACS_FORCE_RELOAD_ASYNC_DECODE`) with the legacy path intact. |
| 5 | Defense-in-depth at sinks | **Partial** | Cross-patient isolation follows it well; but completeness has **no single sink** — each of the 13 entry points is its own sink with its own (sometimes stale) count. |

---

## 4. Where it breaks — the 203 freeze as the predicted failure

The 47793 / 47842 "series 203 stuck at 8 of 120" freeze is **principle 2 failing structurally**:

1. Series 203 (secondary `1.2.840.1.99.1.47` study) loaded via the **progressive-fast** path and
   grew the *displayed* volume 33→99 — but that path **did not call the canonical sync** for 203
   (`metadata-refresh: series=203` = **0 occurrences** in the log; series 202, which took the full
   load, did sync). So the single source of truth (`lst_thumbnails_data[idx]['metadata']`) stayed
   an 8-instance stub.
2. `_get_series_by_number_fast` faithfully served that 8-stub (`source=index_seed`).
3. A **different** entry point — the disk-ready **resume watchdog** (`_maybe_resume_awaiting_from_disk`,
   not in the doc's grow-path list) — read the stub and **rebuilt the viewport *down* from 99 to
   1/8**, then looped.
4. The full-load path that *would* rebuild the canonical metadata **never ran for 203**
   (`UX_SERIES_LOAD_START series=203` = 0; it ran for 202).

No single mechanism is "wrong" in isolation — they're **competing authorities reading divergent
counts**, which is exactly what a unified method is supposed to prevent. The same family produced
44113, the 14965 re-download, and the dragdrop thrash ([[dragdrop-slow-internet-thrash-2026-06-17]]).

---

## 5. This session's fixes, judged against the unified method (honest)

| Fix | Respects unified method? | Caveat |
|---|---|---|
| **Post-complete gate** (`_vc_load.py`): gate the "already fully visible" skip on `_resolve_series_expected_count` instead of a transient disk count | **Yes** — routes the decision through the **resolution authority** + the shared completeness predicate; strengthens principle 2 at that sink. | Still one sink among many. |
| **Grow-fallback → metadata-sync** (`_vc_switch.py`): when in-place grow can't run, call `_refresh_and_sync_metadata` (the canonical updater) then force reload | **Yes** — reuses the **existing canonical authority** rather than forking; repairs the one source of truth so later reads are correct. | It is *another hand-placed* call of the sync pair — it fixes the symptom **by adding a 14th entry point**, not by consolidating. Correct, but it grows the sprawl it's compensating for. |
| **force-reload async decode** (`_vc_switch.py`, default-off) | **Yes** — reuses the existing async load path, no new decode path. | — |

**Net:** the fixes are *consistent with* the unified method (no forked resolver, no parallel
metadata store, clinical boundary respected, flag-gated). They are **not, by themselves,
unification** — they patch individual sinks. That is the right call for a clinical hotfix, but it
should not be mistaken for closing the architectural gap.

---

## 6. Connections & dependencies to other parts

- **Upstream (data-path unified pipeline):** these parts begin **where `set_server_series_info`
  ends** (`unified-patient-study-pipeline.md` §4.2). That boundary is clean and respected — the
  study-set authority feeds metadata in; pixel/volume work stays below it. **Good separation.**
- **Thumbnail pipeline** (`thumbnail-pipeline.md`): shares the **same disk truth** and the
  `_count_series_files_on_disk` 1 s cache, and the same `lst_thumbnails_data` source. A stale
  count here is visible there too (and vice-versa) — they are coupled through the cache, which is
  a benefit *if* the cache is correct and a shared failure mode if not (47804).
- **Download manager / progressive feed:** `on_series_images_progress` → progressive grow is the
  producer; these parts are the consumer. The producer keys progress by `study_uid`/series number;
  the **secondary-study key mismatch** (46713/46970, CLAUDE.md) is the same desync class surfacing
  at the producer→consumer seam.
- **ZetaBoost** (`ZETABOOST_PIPELINE_ANALYSIS.md`): a parallel cache/warm authority that also
  invalidates series — another writer to the same series state, gated by `is_active()`. One more
  actor on the shared series state.
- **Clinical downstream (protected):** VTK reslice / MPR geometry / slice order / orientation —
  **untouched** by any of this; the unified-pipeline guardrail (§7) held throughout.

---

## 7. Recommendation — make the unification *structural*, not conventional

This matches the doc's own staged tail (`unified-patient-study-pipeline.md` §7.2/§7.4: a typed
`DownloadPlan`, a `PatientStudyCatalog` read model, a `ViewerLoadPlan`). Extend that idea **one
layer down** into the viewer:

1. **One `SeriesDisplayState` read model per (viewer, series)** that owns the four counts
   (server / disk / viewer-visible / resolved-expected) behind a *single* accessor, built on the
   existing `SeriesCompletenessSnapshot`. Every entry point reads counts **only** from it — delete
   the 57 ad-hoc reads over time (flag-gated, legacy-preserved).
2. **One `ensure_series_displayed(viewer, series, intent)` chokepoint** that all 13 entry points
   funnel through. It does the decide-once logic: *if viewer-visible < disk → grow/rebuild; if
   canonical metadata < disk → refresh-and-sync first; never downgrade below current
   `get_count_of_slices()`*. The resume watchdog, progressive grow, completion, and change-series
   all call **it** instead of each re-implementing the decision. The canonical sync becomes
   **structurally guaranteed** (called inside the chokepoint), not hand-placed.
3. **Collapse the two `change_series_on_viewer`** (`_vc_switch.py` vs `thumbnail_panel.py`) — confirm
   the legacy one is dead (memory says its `ThumbnailBatchRunner` is never instantiated) and remove
   the parallel method, or route it through the canonical one.
4. **Single disk-count read authority** — keep the 1 s TTL cache but bust it at the **download-complete
   boundary** centrally (already done for the post-complete gate; generalize it) so no consumer can
   ever read a stale-low count.

Each step is a *consolidation* (principle 1) + a *single source of truth* (principle 2), is
flag-gated with the legacy path as a kill switch (principle 4), stays above `set_server_series_info`
and never touches geometry/render (principle 3), and is independently GUI-validatable. Sequence it
**after** the current hotfixes are live-verified, and behind the same `DownloadPlan`/catalog work
the unified-pipeline doc already stages — so the viewer chokepoint and the study-set authority meet
in one model rather than two.

---

## 8. Bottom line

- **Do these parts respect the unified method?** *In principle yes, in structure no.* They sit
  correctly below the unified data-path sink and reuse the right authorities where they touch them,
  but the **load/grow/resume orchestration is a convention-enforced sprawl over fragmented counts**,
  which is the opposite of "one authority, one source of truth." The 203 freeze is that gap made
  visible.
- **This session's fixes** are *compatible* with the unified method and clinically safe, but they
  **patch sinks rather than unify them** — acceptable as hotfixes, not a substitute for §7.
- **The fix that would make it truly unified** is a single `SeriesDisplayState` + one
  `ensure_series_displayed` chokepoint, staged behind the existing `DownloadPlan`/catalog plan,
  flag-gated, downstream-protected.

*No code was changed by this evaluation.*
