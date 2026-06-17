# Evaluation: Unified Patient-Study Pipeline Review — verdict, safety boundary, and safe plan

Date: 2026-06-17
Status: **Evaluation + Phase-1 foundation.** This report changes documentation only.
The accompanying code change adds a NEW, UNWIRED, pure-Python module + tests
(`PacsClient/utils/patient_study_set.py`, `tests/code/ui_services/test_patient_study_set.py`);
it changes **no** existing behavior and touches **no** rendering/geometry code.

Reviews the proposal in
`docs/reports/UNIFIED_PATIENT_STUDY_PIPELINE_REVIEW_2026-06-17.md` against the live
codebase. Companion to `MULTI_STUDY_OPEN_VS_SELECT_DIVERGENCE_46630_2026-06-17.md`
and the 2026-06-16 architecture/code-change reviews.

---

## 1. Verdict

The proposal is **accurate, well-scoped, and the correct direction.** I verified its
pipeline map and its central claim — *authority fragmentation* — against the current
code, and both hold. Its recommendation (a canonical `PatientStudySet` object produced
by one service, consumed by many intent-specific UI callers) is the right "authority
collapse," and it correctly insists on a facade-first, no-big-bang migration.

Two things I add that the document under-specifies, both essential for this codebase:

1. **The clinical-safety boundary is not drawn explicitly.** The unified pipeline is a
   *study-set resolution + payload assembly* layer. It must terminate at the existing
   merge-aware metadata sink `set_server_series_info` and the thumbnail/download payload
   builders. It must **never** reach into series pixel loading, IPP/IOP geometry,
   slice ordering, orientation, VTK render windows, or MPR reslice. The document treats
   the viewer as "a consumer" but does not state the invariant that the refactor stops
   *above* the rendering boundary. That invariant is what makes this refactor safe to do
   at all — it should be Phase 0 invariant #1.

2. **The download payload must inherit the 2026-06-16/06-17 DM identity guards.** A
   unified `DownloadPlan` must carry real `(study_uid, series_uid, original
   series_number)` and never a synthetic viewer display key — i.e., it must preserve the
   membership-validation + canonical-identity work just hardened in the Download Manager.

With those two additions, I endorse the plan and have implemented its Phase-1 foundation
(see §8).

---

## 2. Claims verified against the live code

| Doc claim | Verified | Evidence |
|---|---|---|
| Multiple independent study-set resolvers exist | Yes | `_resolve_patient_study_uids` (`_hp_patient_open.py:150`), `_resolve_patient_study_uids_async` (`:317`), `_enumerate_studies_for_row` (`:349`), `_reconcile_patient_studies_on_click` (`_hp_series.py:599`), `_resync_patient_studies_from_server` (`_hp_series.py:314`), `on_plus_button_clicked` (`_hp_modules.py:516`), `_on_download_requested` (`_hp_download.py:35`) |
| Single-click uses a *fresher* source than open | Yes | reconcile does a fresh `search_patients_sync` + reads `studies`/`study_list`/`study_uids`/`latest` (`_hp_series.py:652–706`); open reuses the compact cached `_server_patient_meta_by_pid` + gated enumeration (`_hp_patient_open.py:336,370,381`) |
| Late discovery updates the home panel, not the open viewer | Yes | resync re-render targets `_show_grouped_patient_studies` (`_hp_series.py:558`); the only open-viewer sink is the already-open refocus branch (`_hp_patient_open.py:671–697`) — confirmed in the 46630 report |
| The viewer series path is a *consumer*, not an authority | Yes | `set_server_series_info` (`_pw_thumbnails.py:86`) ingests a series list it is given; it cannot infer missing studies |
| `set_server_series_info` is merge-aware | Yes | first-call builds, subsequent calls add only new series and never clobber image counts (`_pw_thumbnails.py:91–134`) |

The document's path map (its §4) matches the code. Its coverage matrix (§5) and its
46630 explanation (§7) are consistent with my independent 46630 root-cause report.

---

## 3. The clinical-safety boundary (the most important addition)

This is the direct answer to the "be extremely careful with VTK/MPR/geometry" rule.

**Where the unified pipeline STOPS:** `widget.set_server_series_info(series_list)`
(`_pw_thumbnails.py:86`). I read it in full. It is **metadata-only** and merge-aware:
it builds `_server_series_info` (by series number), `_series_uid_to_number`, the
per-study `_studies_series` index, calls `_rebuild_multistudy_series_index()` (the
collision-free `study_slot*1_000_000 + original_series_number` offset keys), and
schedules thumbnail prefetch. It contains **no** pixel read, **no** geometry, **no**
VTK, **no** MPR, **no** slice ordering, **no** orientation.

**What stays DOWNSTREAM and MUST NOT be touched** (the clinically verified result is
produced here, from disk, at series-load time — out of scope for this refactor):

- series pixel/volume loading in `_vc_load.py` / `_vc_switch.py`;
- z-spacing derived from **IPP deltas** (not `slice_thickness`/`spacing` tags) in
  `source_geometry.py` and FAST `pydicom_2d_backend._attach_spacing_between_slices`
  (see `GEOMETRY_EVAL_VTK_MPR_2026-06-14.md`);
- MPR reslice (SimpleITK on IPP-sorted files) and VTK render windows;
- orientation handling and the final rendered anatomical result.

**Invariant to freeze (Phase 0):** *The unified study-set pipeline produces metadata
and payloads only. Its sole viewer touchpoint is `set_server_series_info` (and the
thumbnail/download payload builders). It must never call a viewer geometry/render/reslice
method, and must never reorder, reorient, or reshape series pixel data.* Because the
refactor is entirely **upstream** of the rendering boundary, it cannot change the final
clinical image — provided this invariant holds. Any change below the boundary is a
*separate* effort with its own geometry test gate, explicitly excluded here.

Note: FAST and Advanced/VTK viewers diverge in *rendering*, which is downstream; they
both consume the same series **metadata** sink. The unified path treats them identically
(it hands metadata to the widget); it does not, and must not, choose or alter a render
mode.

---

## 4. Where the document is right (endorsed)

- **Authority fragmentation is the real root** (its §6) — not any single bad helper.
  This matches the 46630 finding precisely: open and single-click disagree because they
  *resolve* the study set differently.
- **One canonical `PatientStudySet`, many intents** (its §3/§8.4) is the right shape. The
  intent matrix (preview vs open vs refresh-open vs manual) correctly keeps the path
  "one contract, policy-driven side effects" rather than "one expensive path."
- **Facade-first, migrate callers one by one** (its §13/§17.1) is the only safe way to do
  this in clinical software and matches the project's "minimal safe edits" rule.
- **Late-discovery needs a universal sink** (its §12.2) — exactly the missing
  `study-set-grew → update the open viewer tab` path from the 46630 report.
- **Preserve the recent guards** (its §11) — DM membership validation, canonical viewer→DM
  identity, immutable totals, sync manifest, sync-mode policy, cross-patient guards. Agreed.

---

## 5. Gaps / refinements to the document's plan

1. **State the geometry boundary as Phase-0 invariant #1** (see §3 above). Without it, a
   future contributor could "helpfully" let the service call a viewer load method and
   silently put geometry at risk.
2. **`set_server_series_info` already IS the merge-aware sink.** The doc lists it only as a
   "consumer to migrate." In fact it is the asset that makes Phase 2 small: the open-viewer
   back-fill needs no new viewer machinery — the unified path just calls the existing
   merge-aware sink with the full study set. Phase 2 is therefore *resolution* work, not
   *viewer* work.
3. **DownloadPlan must carry canonical identity** (real `series_uid`/original number), so it
   composes with the just-hardened DM membership validation. Add this to the doc's §8.3
   step 10 and §10.3.
4. **Open-latency guard.** A single resolver that force-fetches per-study series for *open*
   must keep the "fast first paint" contract (its §10.1): open the tab immediately from
   `local_fast`, resolve the full set in the background, then back-fill via
   `set_server_series_info`. Make this a test assertion, not just prose.
5. **Cross-patient guard stays at the sinks too.** The doc says centralize ownership (agreed)
   but also keep defense-in-depth at the sinks (its §17.5). Concretely: do **not** delete the
   STEP-3.5 / reconcile / grouped-thumbnail owner checks when the service lands — demote them
   to cheap asserts, don't remove (the project's "don't delete a path until the new one
   covers it" rule).
6. **DOC-study download policy** (its §10.4) should be explicit that, on *open*, a
   late-discovered DOC study's missing series **is** queued (the 46630 gap was that it was
   skipped as `single_click_auto_no_download`). Single-click stays no-download.

---

## 6. Duplicated paths → merge map (concise)

| Concern | Today (fragmented) | Unify into |
|---|---|---|
| "Which studies does this patient have?" | `_resolve_patient_study_uids(_async)`, `_enumerate_studies_for_row`, `_reconcile_patient_studies_on_click`, row metadata, `_patient_study_uid_map`, `_server_patient_meta_by_pid`, right-panel payload | `PatientStudySetService.resolve()` → `PatientStudySet` (selected-first, deduped, owner-validated, per-modality-complete) |
| "Which series + sync state per study?" | per-study fetch in open STEP 3.5, reconcile loop, resync loop, manual-download prefetch | one per-study metadata + `sync_manifest.evaluate_sync` pass inside the service |
| "What to render?" | `show_patient_studies`, `_show_grouped_patient_studies`, `set_server_series_info` (consumer) | `build_thumbnail_payload` / `build_viewer_payload` → existing sinks unchanged |
| "What to download?" | open STEP 3.5 assembly, resync enqueue, `_on_download_requested` prefetch | `build_download_plan` (missing/partial only, canonical identity) |
| "Update an already-open viewer" | only the refocus branch (`_OPEN_REFRESH_ALREADY_OPEN`) | a universal `apply(study_set)` → `set_server_series_info` on first-open growth too |

Preserve (do not remove until the unified path demonstrably covers them): cross-patient
owner checks, contentVersion fast-gate, disk-aware manifest, sync-mode policy,
missing-only enqueue, multi-study offset keys, render coalescing, DM membership validation.

---

## 7. Risk assessment

- **Clinical rendering: LOW**, *provided* the §3 boundary invariant holds. The refactor is
  upstream of all geometry. The biggest risk is accidental scope creep into the viewer —
  mitigated by the invariant + the rule that the only viewer call is `set_server_series_info`.
- **Open latency: MEDIUM** if the resolver force-fetches synchronously on open. Mitigated by
  fast-first-paint + background resolve + back-fill (§5.4).
- **Behavior regressions: MEDIUM** during caller migration. Mitigated by facade-first +
  per-caller flag gating + keeping sink guards + a Windows test run per phase.
- **Patient-identity (multi-ID): OUT OF SCOPE** for the study-set unification (the doc's §12.5
  agrees). Do not couple it to this work.

---

## 8. What I implemented this turn (Phase-1 foundation only)

Per "implement only after the unified path is clearly defined" and "facade-first, no
big-bang," I implemented the **behavior-neutral foundation** and nothing that touches a
clinical path:

- `PacsClient/utils/patient_study_set.py` — the canonical immutable data contract
  (`PatientStudySetRequest`, `SeriesDescriptor`, `StudyDescriptor`, `PatientStudySet`) **and**
  the single pure authority `merge_study_uids(...)` that consolidates the union + dedup +
  selected-first ordering + cross-patient owner filtering that is today duplicated across the
  resolvers. Pure Python (stdlib only); imports nothing heavy; nothing in the app imports it
  yet → **zero behavior change, zero geometry risk.**
- `tests/code/ui_services/test_patient_study_set.py` — unit tests for the contract and the
  merge authority (union/dedup, selected-first, whitespace filtering, foreign-owner drop,
  unknown-owner keep, selected-always-kept).

This gives the project the canonical object and the single "which studies?" authority the
document calls for, in a form that is unit-testable in isolation, before any caller is
migrated.

**Deferred (next phases, each gated on review + a Windows test run):**
- Phase 2: wire `merge_study_uids` into `_resolve_patient_study_uids` behind a default-off
  flag (`AIPACS_PATIENT_STUDY_SET_SERVICE`), in shadow/observe mode first (compute + log the
  unified set vs the legacy `all_study_uids`, change nothing), to gather real evidence on
  46630-class patients.
- Phase 3: the open-viewer back-fill (study-set-grew → `set_server_series_info` on first
  open) — the actual 46630 fix.
- Phase 4+: single-click, resync, plus-button, manual download become consumers; centralize
  the DownloadPlan; centralize sync state. Patient-identity model is a separate track.

---

## 9. Validation & build inclusion

- Run the foundation tests on Windows:
  `python -m pytest tests/code/ui_services/test_patient_study_set.py -q -p no:debugging`
  (pure Python; should also run anywhere PySide6-free).
- The foundation module is plain source under `PacsClient/utils/` — it ships with the app
  automatically once a caller imports it; no spec/plugin-mirror change is needed until a
  caller is migrated. When Phase 2 wires it into the home panel, follow the new-module /
  feature-flag checklist (CLAUDE.md) and re-run `tests/code/ui_services` + the multi-study
  suites.
- No `set_server_series_info`, `_vc_load`, `_vc_switch`, MPR, or VTK file is modified by this
  work.

---

## 10. Decision

Endorse the proposal with the geometry-safety boundary made explicit and the DM-identity
guards folded into the download payload. The authority-collapse is the right next
architectural move and is **clinically safe because it stays entirely upstream of the
rendering boundary**. Proceed facade-first: the Phase-1 foundation is in place and tested;
the first behavior-affecting step (Phase 2 shadow wiring → Phase 3 open back-fill) should
land behind a default-off flag after a Windows test run.
