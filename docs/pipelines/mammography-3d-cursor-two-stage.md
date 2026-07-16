# Mammography 3D Cursor — Two-Stage Matching Workflow (as-built, 2026-07-14)

**Module:** `modules/ai_imaging/ai_module_ui/cursor_3d/`
**Entry point:** the **3D Cursor** button in the Eagle Eye MG toolbar
(`service_tab/imaging_tab.py::_on_3d_cursor_clicked`).
**This is NOT the 2D-viewer 3D cursor.** No code is shared between them.

Read this before editing anything under `cursor_3d/`. Companion documents:
- `docs/plans/mammography/EAGLEEYE_3D_CURSOR_ACCURACY_PLAN_2026-07-14.md` — the
  accuracy plan and the literature these decisions rest on.

---

## 1. Clinical purpose

At the routine analysis threshold (**0.45**) the AI typically detects a lesion in
**only one** mammographic view. That is expected — a lesion that is obvious in both
views rarely needs help. The clinically hard case is the one-view finding: the
radiologist must decide whether it is real, and to do that they must find it in the
other view.

The Two-Stage 3D Cursor answers exactly that question:

> *"The AI found something in the CC view. Where is it in the MLO — and did the AI
> nearly see it there too?"*

It combines two independent sources of evidence:

1. **Geometry** — where anatomy says the lesion *must* be.
2. **A second, more sensitive AI pass** — what the detector sees *there* when you
   ask it to look harder.

Neither alone is sufficient. Geometry cannot confirm a lesion; a lower threshold
alone floods the view with false positives. Their **intersection** is the signal.

---

## 2. The initial analysis threshold

- Set by the user in the Eagle Eye analysis dialog (`AISettingsDialog`, a 0–100
  slider), default **0.45**.
- Passed to the backend as `det_eval_thr` in the `POST /api/v1/run_full_analysis`
  payload (`MamoWorker.run`).
- Persisted only in two places: the **CSV filename**
  (`updated_csv_with_boxes_0.45.csv`) and the `threshold` field of
  `mg_ai_manifest.json`.
- The two-stage workflow reads it back via
  `two_stage_controller.current_threshold()`, which resolves the manifest's
  **active** run. If it cannot be determined, it falls back to **0.45** —
  deliberately the *high* value, because guessing low would make the second pass a
  no-op or a duplicate of the run already on screen.

---

## 3. Stage 1 — geometric localization

**Module:** `cursor_3d/search_region.py` (pure: stdlib + `math` only).

Inputs — all already collected by the guided picker and the correlator:

| Input | Source |
|---|---|
| Lesion box in the source view | AI detection CSV (`box` / `new_box`) |
| Nipple, both views | **Manual** pick (guided picker step 1 & 2) |
| Pectoral line (MLO) | **Manual** pick (guided picker step 3) |
| Image dimensions, pixel spacing | DICOM (`Rows`/`Columns`, `ImagerPixelSpacing`) |
| Breast boundary | `breast_contour.segment_breast_contour()` (optional clip) |
| Laterality / view | `view_identity.resolve_view_identity()` |

### The output is a REGION, never a point

The CC→MLO mapping is under-determined. Every published method predicts a
curve or a band; none predicts a coordinate. `SearchRegion` therefore carries:

- `points_px` — the nominal locus (a line or an arc),
- `inner_band_mm` — the high-confidence band (default **±8 mm**),
- `outer_band_mm` — the search band (default **±32 mm**),
- `deviation_mm(point)` — closed-form distance from any point to the locus.

That one `deviation_mm` function serves three purposes — the accuracy metric,
Stage-2 candidate scoring, and the "is it inside?" test — so the three can never
drift apart.

### Which method, and why

Two loci are implemented. **SS is the default.**

- **SS — Straight Strip (default).** Assumes the **axial** distance `dl` (the
  lesion's projection onto the centreline through the nipple, perpendicular to the
  chest wall) is preserved across views. Locus = a straight line perpendicular to
  that centreline.
- **AB — Annular Band.** Assumes the **radial** distance `dr` (the Kopans
  nipple-to-lesion distance) is preserved. Locus = an arc centred on the nipple.

SS is the default because two independent cohorts agree it is more accurate:

| | Zheng 2009 (n=200) | Wang 2025 (n=711) |
|---|---|---|
| Search width for 100 % capture | SS **28 mm** vs AB **68 mm** | SS ±32 mm vs AB ±39 mm |
| Median absolute error | — | SS **4.59 mm** vs AB **5.78 mm** |
| CAD false positives removed | SS **25.0 %** vs AB **11.9 %** | — |
| Cross-view correlation | — | axial **0.923** vs radial 0.917 |

Select with `AIPACS_CURSOR3D_LOCUS = ss | ab`.

### Two defects fixed here (do not reintroduce)

1. **The chimera.** The legacy `correspondence_arc.py` draws an **AB arc** but
   feeds it the **SS distance** (`compute_lesion_depth_mm`). It honours neither
   method's assumption. `geometry.compute_lesion_radial_distance_mm()` was added so
   an arc can be given its *own* correct radius.
   **Rule: `dl` is for strips, `dr` is for arcs. Never cross them.**

2. **The left-breast mirror.** The legacy arc used
   `centre_angle = chest_wall_angle − θ_pec` for *both* lateralities. For a LEFT
   breast (`chest_wall_angle = π`) that yields `sin > 0` — the arc swept
   **inferiorly**, into the wrong quadrant, contradicting both the anatomy and the
   file's own comment. `search_region.py` takes its direction from
   `geometry.depth_normal_unit_vector()`, the single laterality-aware,
   pectoral-tilted definition of "toward the chest wall", so **L and R cannot
   diverge**. Guard: `test_arc_sweeps_superiorly_for_BOTH_lateralities`.

Also fixed: **anisotropic pixel spacing** is now honoured per-axis (the legacy arc
collapsed spacing to a scalar mean, distorting the locus).

---

## 4. Automatic threshold reduction — the escalation ladder

**Module:** `cursor_3d/threshold_policy.py` (pure — split out of `second_pass.py`
precisely so it can be tested and reused without Qt).

The first rung is the spec's **−0.05**. But one step is often not enough, so the
workflow **escalates** until a detection lands *inside* the predicted region, or a
floor is reached.

```
threshold_ladder(0.46) -> [0.41, 0.31, 0.21]
threshold_ladder(0.45) -> [0.40, 0.30, 0.20]     (routine default)
threshold_ladder(0.20) -> []                     (already at the floor)
```

### Why a ladder — live finding, study 50016 (2026-07-14)

The lesion was detected in **L-CC at 0.4627**. The second pass ran correctly at
**0.41** — and **L-MLO came back empty**. Checking every run on disk, L-MLO had
**zero detections at 0.41, 0.42, 0.43, 0.44, 0.45 and 0.46**. The corresponding
lesion simply scores below 0.41. A single −0.05 step could never have surfaced it.

(The pass itself was healthy: at 0.41 it *did* find new boxes — one in **R-CC**
(0.431) and a second in **L-CC** (0.418). They were in the wrong views. The
"No reliable corresponding lesion found" message was accurate, not a bug.)

### Why escalating is safe

A 0.21 threshold on its own would bury the radiologist in false positives. **The
region is what buys us the right to look that deep**: we never show raw detections,
only ones that fall inside a geometrically-constrained band. This is the same logic
as the published two-view search areas, which remove ~25 % of single-view false
positives. **Stage 1 is the precondition for Stage 2 being aggressive.**

- Offsets grow (`0.05, 0.15, 0.25`) so we reach a genuinely low threshold in **at
  most 3 backend calls** — each rung is a real AI-server round trip.
- Floor `0.20` (`AIPACS_CURSOR3D_LADDER_FLOOR`): below this the detector is noise.
- Existing runs are **reused**, so re-opening the cursor on the same study does not
  re-run rungs already on disk.
- **Rounded to 2 dp — not cosmetic.** The backend writes its result to
  `updated_csv_with_boxes_{threshold:.2f}.csv`, and the manifest re-parses the
  threshold back *out* of that filename with a regex. An unrounded `0.44999999`
  would be written as `_0.45.csv` and **silently collide with the first-pass
  result**.

Flags: `AIPACS_CURSOR3D_LADDER` (default `0.05,0.15,0.25`),
`AIPACS_CURSOR3D_LADDER_FLOOR` (default `0.20`).
Guards: `test_ladder_escalates_because_one_step_is_often_not_enough` and 4 others.

---

## 5. Stage 2 — the second backend analysis

**Module:** `cursor_3d/second_pass.py` (`SecondPassController`).

Fired the instant the 3D Cursor button is pressed — **before** the guided picker
opens — so it runs while the user places landmarks.

### Why it does not reuse `start_mg_process`

`AIChatInteractorStyle.start_mg_process` cannot be used, for three reasons:

1. It shows an **application-modal** overlay
   (`ai_chat_interactorstyle.py:834`, `setWindowModality(ApplicationModal)`), which
   freezes the entire app — including the picker the user is meant to be using.
   **That single line is what made this workflow impossible before.**
2. It opens a threshold dialog and a Re-run/Open/Cancel prompt. The second pass is
   automatic and must ask nothing.
3. It parks the worker on the **transient interactor style**, which is replaced on
   every Eagle Eye trigger — orphaning a running `QThread`.

`SecondPassController` instead launches `MamoWorker` directly, with no overlay, and
holds the reference on the **long-lived `ImagingToolsTab`**.
**`start_mg_process` is untouched — the normal user-initiated analysis path is
byte-identical.**

### Reuse before rerun

If a run at the target threshold already exists on disk
(`mg_ai_runs.find_run_by_threshold`), it is reused. Re-running costs minutes of AI
server time and litters the dropdown with `_2`, `_3`, `_4`… duplicates for zero
clinical gain.

---

## 6. Candidate ranking and matching

**Module:** `cursor_3d/candidate_matching.py` (pure).

Candidates are the second-pass detections belonging to the **target** view's
series, loaded through the widget's own `get_series_ai_data_from_df` (its four-way
row-matching chain is not forked). Boxes the user already **rejected** (`removed`
column) are excluded.

Seven weighted components, each normalised to [0, 1], weights summing to 1.0:

| Component | Weight | Rationale |
|---|---|---|
| `region_fit` | 0.35 | Deviation from the Stage-1 locus — the published error metric itself |
| `axial_agree` | 0.20 | `dl` agreement; correlates 0.923 across views — the strongest single cue |
| `radial_agree` | 0.15 | `dr` (Kopans/NOD) agreement; correlates 0.917; an *independent* cue |
| `ai_score` | 0.10 | The detector's own confidence |
| `size_agree` | 0.10 | Physical size survives compression better than shape does |
| `class_agree` | 0.05 | Same predicted finding label in both views |
| `shape_agree` | 0.05 | Weakest — compression genuinely deforms lesions differently per view |

**Side/view consistency** is structural, not a score: candidates are only ever drawn
from the target view of the same laterality, so an inconsistent candidate cannot
enter the pool.

**Pectoral reference** enters through `axial_agree`: the MLO chest-wall normal is
tilted by the drawn pectoral angle, so `dl` *is* the distance measured relative to
the pectoral line.

### An emergent and useful property

A strip cannot say *where along itself* the lesion sits — every point on it has the
same `dl`. The **radial** component supplies exactly that missing cue, because
`dr = hypot(dl, t)` grows with distance `t` from the foot. Combining them is, in
effect, Zheng's third "mixed" search area (strip on the chest-wall side, arc on the
nipple side). Guard:
`test_radial_agreement_disambiguates_position_ALONG_the_strip`.

### The weights are NOT validated

There is no ground-truth correspondence set yet — the same blocker CL-Net's authors
hit (DDSM ships no correspondence labels). These are principled starting values,
ordered by what the literature says carries signal. **Calibrate them against a
labelled set before trusting them** (accuracy plan, Phase 0). The session store
(§9) is what makes that calibration possible.

---

## 7. UI states

Driven through `ImagingToolsTab.set_processing_status`; strings live in
`two_stage_controller.State` (single source of truth).

| State | When |
|---|---|
| `Calculating corresponding region…` | Landmarks in, Stage 1 running |
| `Running lower-threshold analysis…` | Second pass dispatched |
| `Waiting for AI result…` | Region ready, backend still in flight |
| `Evaluating candidate lesions…` | Both arms in, ranking |
| `Corresponding lesion found` | `MATCH` |
| `Multiple possible matches — review alternatives` | `AMBIGUOUS` |
| `No reliable corresponding lesion found` | `NO_MATCH` |
| `Predicted region shown (no AI candidates)` | Second pass failed/disabled |

The two arms (region, backend) converge in `_try_match()`, which fires only when
**both** are in — **in whichever order they arrive**. The user is never blocked
waiting for the backend, and an early backend result is never dropped.

### Visual language (`cursor_3d/region_render.py`)

| Element | Meaning |
|---|---|
| Solid cyan line | The predicted locus |
| Dashed cyan | Inner / high-confidence band (±8 mm) |
| Faint cyan | Outer / search band (±32 mm) |
| **Green** box + `MATCH 0.xx` | One confident correspondence |
| **Amber** boxes + `ALT n` | Near-tied alternatives — no winner asserted |
| **Grey** boxes | Considered and rejected |

**Green is reserved for a claim we are willing to stand behind.** There is
deliberately no green box in the `AMBIGUOUS` or `NO_MATCH` states.

The full score breakdown (every component) is printed to the Eagle Eye summary
panel, so a radiologist can see *why* a candidate ranked where it did.

---

## 8. Uncertainty and failure handling

Three outcomes only, and the algorithm is **required** to say "I don't know":

- **`MATCH`** — the best candidate clears the score floor (`0.55`) **and** beats the
  runner-up by the margin (`0.10`). Only this sets `is_confident`.
- **`AMBIGUOUS`** — several candidates within the margin. **`best` is `None`.** All
  are shown as equal amber alternatives.
- **`NO_MATCH`** — nothing clears the floor, or nothing lies within
  `outer_band × 1.5`. The geometric region **stays on screen**; the user is told no
  reliable AI correspondence was found and invited to review manually.

Every failure — backend down, no detections, unusable region, persistence error —
degrades to **Stage 1 only**: region visible, honest message. We never invent a
match, never widen the bands to manufacture a hit, and never present an ambiguous
result as confirmed.

> **The reasoning:** a false "confirmed match" in a cancer workflow is worse than an
> honest "unknown". It moves the radiologist's eye *away* from the true lesion. A
> coin-flip presented as an answer is a harm, not a feature.

Bad or missing landmarks degrade gracefully: a nipple pick is *required* (the flow
aborts without it), and a missing pectoral line falls back to the auto-detector,
then to a default angle. **Do not replace the manual nipple pick with
auto-detection** — DL nipple segmentation errs by ~7.4 mm, which propagates 1:1 into
the locus and would exceed the entire error budget.

Thresholds: `AIPACS_CURSOR3D_MIN_SCORE`, `AIPACS_CURSOR3D_MIN_MARGIN`.

---

## 9. Result persistence

### AI runs — `mg_ai_manifest.json` (`mg_ai_runs.py`)

- The backend **already** never overwrites: `_with_threshold_and_no_overwrite`
  appends `_2`, `_3`… on collision. Every run is preserved.
- `mg_ai_runs.append_run(..., set_active=False)` registers the second-pass run in
  `available[]` so it is **selectable from the AI Results dropdown**, but leaves
  `active` alone.
  **This is deliberate:** repointing `active` would swap every box in every
  viewport out from under a radiologist mid-workflow. The two-stage flow reads the
  second-pass CSV *by path* and renders candidates as a distinct overlay.
- New keys `run_id`, `created_at`, `source` give a run a real identity (previously a
  "run" was only its filename, and two runs at the same threshold collided into
  `Threshold 0.45` / `Threshold 0.45_2` with no semantics). Back-compatible:
  `load_mg_ai_runs` splats entries with `**run`, and every read is a `.get()`.

### Correspondence sessions — `mg_3dcursor_sessions.json` (`two_stage_session.py`)

Records the full provenance chain the spec's Data Model requires:

```
source lesion + source view + original run + original threshold
  -> predicted region (method, distance, bands)
    -> second-pass run_id + threshold + CSV
      -> candidates (all, with per-component scores)
        -> selected candidate + match score + margin
```
plus the landmarks (nipple both views, pectoral angle), so any result on screen can
be re-derived and audited.

**`human_confirmed` defaults to `None` and is NEVER inferred from display.** A
displayed match is not a confirmed one.

> **Why this matters beyond audit:** every human-confirmed session is a labelled
> CC/MLO correspondence pair — precisely the data that does not exist publicly.
> Persisting sessions turns routine clinical use into the validation set needed to
> calibrate the bands and the Stage-2 weights. Nothing else in the accuracy plan
> unblocks without it.

Atomic writes; a persistence failure logs and returns `None` — it never breaks the
clinical workflow.

---

## 9b. Diagnostics — use the LOGGER, never print()

**All `[3D-Cursor]` diagnostics go through `logging.getLogger(__name__)`**, which
lands in `user_data/logs/app.log`.

This is a hard rule, learned the hard way. The feature originally used `print()`
throughout. Prints go to **stdout**, which a VS Code source run shows in the
terminal and then loses — so `app.log` contained **zero** `[3D-Cursor]` lines, and
the first live failure (study 50016) had to be diagnosed by reading the detection
CSVs by hand. Modules that use the logger (e.g. `[TrainingUI]`) *do* reach app.log.

The single most useful line is the per-rung summary, which states what the pass
found **and in which image**:

```
[3D-Cursor][2-STAGE] rung threshold=0.41: 0 detection(s) in the target view,
    in_region=False (IMG-68304=1 IMG-68306=2 IMG-68308=1 IMG-68310=0)
```

On study 50016 that would have shown instantly that the target view
(L-MLO = `IMG-68310`) was empty while other views had detections — i.e. the AI, not
the code, was the limit. Do not remove it.

---

## 10. Validation and testing

**Guard tests:** `tests/code/ai_imaging/test_cursor3d_two_stage.py` (23 tests).

The Stage-1/Stage-2 core (`geometry`, `search_region`, `candidate_matching`,
`threshold_policy`) is **pure — no Qt, no VTK, no numpy** — and a guard test enforces
that (`test_stage1_stage2_core_imports_without_qt_or_vtk`). This is not fastidiousness:
the offline accuracy harness must be able to import the geometry without a GUI stack.

| Spec scenario | Test |
|---|---|
| Lesion in CC but not MLO / MLO but not CC | `test_direction_cc_to_mlo_and_mlo_to_cc_both_supported` |
| Clear match after lowering threshold | `test_scenario_clear_match_after_lowering_threshold` |
| Multiple candidates in the region | `test_scenario_multiple_similar_candidates_are_ambiguous_not_forced` |
| No candidate in the region | `test_scenario_no_candidate_in_the_region`, `test_scenario_no_detections_at_all` |
| Low-confidence candidate | `test_low_score_candidate_is_never_presented_as_a_match` |
| Left/right correctness | `test_arc_sweeps_superiorly_for_BOTH_lateralities`, `test_strip_is_mirror_symmetric_between_lateralities` |
| Threshold step-down | `test_second_pass_threshold_*` (3) |
| Anisotropic spacing | `test_anisotropic_spacing_is_honoured_per_axis` |
| Accuracy metric | `test_absolute_error_matches_the_published_metric` |

Run: `python3 -m pytest tests/code/ai_imaging/test_cursor3d_two_stage.py -q -p no:debugging`

### The accuracy metric

`search_region.absolute_error_mm(region, true_centre_px)` implements the **published
AE metric** (shortest distance from the true lesion centre to the predicted locus),
so our numbers are directly comparable to the literature:

| Method | Median AE | AE > 10 mm |
|---|---|---|
| GM (3D uncompress→rotate→recompress) | 3.03 mm | 7 % |
| **SS (our default)** | **4.59 mm** | **15.5 %** |
| AB (arc — the legacy locus) | 5.78 mm | 27.4 % |

### STILL NEEDS LIVE VERIFICATION

Everything above is unit-verified and compile-clean, but **not yet run against the
real source build**. Outstanding:

- Bilateral studies and multiple lesions per breast (logic handles them — every
  unpaired lesion gets its own region — but unverified on real data).
- Repeated 3D Cursor runs at different thresholds (reuse path).
- Studies with previous AI results already present.
- Whether the second pass actually completes within the landmark-picking window on
  the real AI server.
- The band widths (±8 / ±32 mm) are **literature placeholders**. Replace them with
  values measured from our own session store.

---

## 11. Flags

| Flag | Default | Effect |
|---|---|---|
| `AIPACS_CURSOR3D_TWO_STAGE` | on | Master. `=0` → legacy 3D Cursor, byte-identical |
| `AIPACS_CURSOR3D_SECOND_PASS` | on | `=0` → Stage 1 only (region, no AI candidates) |
| `AIPACS_CURSOR3D_LOCUS` | `gm` | `gm` (default, see §14) \| `ss` (kill switch) \| `ab` |
| `AIPACS_CURSOR3D_GM_OBLIQUITY_DEG` | `45` | GM CC↔MLO obliquity fallback |
| `AIPACS_CURSOR3D_GM_CURVATURE` | `0.0` | GM quadratic bow (0 = straight locus) |
| `AIPACS_CURSOR3D_INNER_BAND_MM` | `8.0` | High-confidence band |
| `AIPACS_CURSOR3D_OUTER_BAND_MM` | `32.0` | Search band |
| `AIPACS_CURSOR3D_THRESHOLD_STEP` | `0.05` | Second-pass step-down |
| `AIPACS_CURSOR3D_MIN_SCORE` | `0.55` | Confidence floor |
| `AIPACS_CURSOR3D_MIN_MARGIN` | `0.10` | Margin over runner-up |
| `AIPACS_CURSOR3D_HEIGHT_SIGMA_MM` | `35` | Factor 2 height-prior width (wide; see §15) |
| `AIPACS_CURSOR3D_APPEARANCE` | off | Factor 3 (histogram) in scoring — reads pixels; §15 |
| `AIPACS_CURSOR3D_HEATMAP` | off | Dense three-factor visual heatmap overlay (VTK) |

None of these files are plugin-mirrored.

---

## 12. Overlay ownership — only ONE locus is ever drawn

When the two-stage workflow takes over, it **owns the overlay**: the legacy arc
(`draw_3d_cursor_results`) and the probability heatmap are **not drawn**.

This is deliberate and clinically important. The legacy `correspondence_arc` is an
annular band fed the *straight-strip* distance, and it mirrors to the wrong side for
LEFT breasts (it sweeps inferiorly). Painting that curve next to the corrected strip
would show the radiologist **two different answers with no way to tell which to
trust** — worse than either alone. One locus on screen, the correct one.

Because the legacy renderer is suppressed, `region_render.draw_search_region` now
draws the **nipple crosshair** itself. Without it the radiologist could not see the
landmark their own click established — and the entire locus is measured *from* that
point, so it must remain visible for them to sanity-check the result.

`on_landmarks_ready()` returns **False** when every lesion was already paired (i.e.
nothing for this workflow to do). The caller then falls back to the legacy arc +
summary, so a fully-paired study is never left with a silent viewer.

---

## 13. Known gaps / follow-ups

- **FIXED (2026-07-14):** `MamoWorker` no longer calls `resp.raise_for_status()`,
  which discarded the response **body** — the one place the AI server puts the
  actual cause. A 502 used to surface as a bare "Bad Gateway" while the discarded
  body said e.g. *"PACS request failed: 127.0.0.1:8000 … actively refused"* (the AI
  server's own PACS backend being down). It now reads the body and includes it in
  the error. Benefits the normal analysis path too.
  ⚠️ `ai_chat_interactorstyle.py` **is plugin-mirrored** — both copies were updated;
  re-sync if you touch it again.
- The **classification join** upstream uses exact float box equality and often
  fails. `two_stage_controller._lookup_class` applies a 2-px tolerance to recover
  labels; a missing label scores **neutral (0.5)**, never zero — a plumbing artefact
  must not count as evidence against a candidate.
- **The probability heatmap is now unreachable in the two-stage path** (it was drawn
  on the legacy arc). It remains in the legacy path. It has never been validated —
  once the accuracy harness can measure it, either prove its peak beats the geometric
  nominal point, or remove it.
- **GM (the geometric-model locus) is now IMPLEMENTED** (`cursor_3d/geometric_model.py`),
  opt-in via `AIPACS_CURSOR3D_LOCUS=gm`. See §14 below.

---

## 14. GM — the Geometric Model locus (Phase 4, 2026-07-15)

**Module:** `cursor_3d/geometric_model.py` (pure: stdlib + `math`). Reached via
`compute_search_region(method="gm")`. **GM is the DEFAULT as of 2026-07-15**
(promoted after the live 50258 validation below); SS is the kill switch,
`AIPACS_CURSOR3D_LOCUS=ss`.

### Why it exists — the 50258 failure

On patient 50258 the SS strip landed **18–25 mm** from the true corresponding
detections (outside the 8 mm inner band → the workflow correctly returned
`no_match`). Root cause: the lesion sits far **superior** to the nipple, and SS
measures its "axial" distance along the **pectoral-tilted** axis, which projects
that vertical offset into the distance — inflating the source's 36.6 mm to 55 mm in
MLO. **No pectoral angle fixes it** (tested 15–50°; the error only grows).

### What GM does differently

GM goes through a 3-D intermediate (Duan et al., IEEE Access 2019; Wang et al., BMC
2025 — median AE 3.03 mm):

1. Decompose the source lesion into an **anterior** distance (nipple→lesion toward
   the chest wall) and an in-plane tangential offset; the depth along the source
   X-ray beam is unknown and sweeps the breast thickness.
2. **Rotate** by the CC↔MLO obliquity about the anterior axis (the step SS/AB skip).
3. **Project** into the target view — the unknown depth traces a curve.

The key: the anterior distance is a physical 3-D length that rotation about the
anterior axis **cannot change**, so GM preserves it along the target's **untilted**
nipple line, and lets the superior-inferior position be the free (curve) parameter.

### Measured result — LIVE on 50258, both directions (2026-07-15)

| Direction | SS: best dev / score / outcome | GM: best dev / score / outcome |
|---|---|---|
| CC→MLO | 18.0 mm / 0.38 / `no_match` | **4.5 mm** / 0.52 / `no_match` (borderline) |
| MLO→CC | 11.5 mm / 0.45 / `no_match` | **2.96 mm** / 0.57 / **`ambiguous`** |

The geometry error collapsed ~4× (18/11.5 → 4.5/2.96 mm — the literature's ~3 mm GM
median), flipping a wrong flat `no_match` into real candidates honestly presented as
alternatives. The offscreen guard on the same geometry: GM 1.7 mm vs SS 17.9 mm to
the nearest detection. Guards: `test_gm_lands_the_lesion_where_ss_missed_50258` + 4.

### Status / caveats

- **Default = GM** (promoted 2026-07-15 on the live 50258 wins). `AIPACS_CURSOR3D_LOCUS=ss`
  is the one-env-var kill switch. GM does not regress the easy (on-nipple-line) case,
  pinned by `test_gm_and_ss_agree_for_a_lesion_on_the_nipple_line`.
- **Validated on ONE patient (two directions).** Keep collecting confirmed pairs
  (every run auto-saves a session) to widen the evidence; revert to SS instantly if a
  future case regresses.
- The **quadratic bow** (`AIPACS_CURSOR3D_GM_CURVATURE`, default 0 = straight locus)
  is Duan's second-order refinement; it needs the labelled set to calibrate and is
  off until then. The dominant win (anterior preservation) is already in the straight
  locus.
- The **obliquity** (`AIPACS_CURSOR3D_GM_OBLIQUITY_DEG`, default 45°) only sets the
  nominal point and sweep rate — NOT the anterior placement — so GM is far less
  sensitive to it than SS is to the pectoral angle.
- GM slots into the existing `SearchRegion` (same `deviation_mm` closed form as SS,
  with the untilted anterior axis), so the renderer, candidate matcher, AE metric,
  and session persistence need **no changes**.

---

## 15. Four-factor cross-view heatmap + dominant-lesion focus (2026-07-15)

The candidate score and the visual heatmap combine FOUR factors, then a single
dominant lesion is selected as the focused result. Factors 1, 2, 4 are live in
scoring by default; factor 3 (pixels) and the visual overlay are flag-gated.

**Factor 1 — geometric** (`cross_view_heatmap.geometric_score`). Distance across the
GM/SS locus, in the ±8/±32 mm band. The well-constrained direction.

**Factor 2 — medial-lateral → MLO height** (`cross_view_heatmap.height_score`,
`SearchRegion.height_offset_mm`). The lesion's medial-lateral position in CC biases
WHERE ALONG the locus it sits: lateral-in-CC → higher in MLO, medial-in-CC → lower.
This is the `x_CC·cos θ` term (the locus nominal).
**It is a WIDE, SOFT prior (σ=35 mm), never a hard pin** — measured on 50258, this
term explains only ~34 % of the true height; the CC-invisible superior-inferior
depth drives the other ~66 %. Narrowing the region to the predicted height would
REGRESS accuracy (a guard test pins that the true detection still scores ~0.37, not
0). This matches the published dual-view *uncertainty ellipse*: narrow across the
locus, long and weighted along the height.

**Factor 3 — appearance / histogram similarity** (`appearance_similarity.py`, numpy).
The source box's intensity signature (dense microcalc vs fatty lipoma vs iso/hyper-
dense mass) compared to candidate regions over a **shared** intensity range
(source p1–p99), combining distribution shape (histogram intersection) with density
level (mean agreement). Neutral 0.5 when pixels are unavailable — never a penalty.

**Factor 4 — lower-threshold AI detection support** (`cross_view_heatmap.region_overlap_fraction`
+ `detection_support`, weight 0.20). The second-pass rerun at the reduced threshold
(the escalation ladder, §4) yields the candidates; factor 4 rewards a candidate that
is BOTH a confident detection AND overlaps the predicted region. `region_overlap_fraction`
integrates the geometric confidence over the whole box area (a larger low-threshold box
covering more of the band scores higher — the "bigger boxes" the radiologist noted);
`detection_support = ½·ai_score + ½·overlap` so a box needs both — a confident detection
in the wrong place, or a well-placed box the detector barely believes in, each score
only moderately. (The old standalone `ai_score` component is folded in here — no
double-count.)

**Combination** (`cross_view_heatmap.combine`, `candidate_matching._weighted_total`):
weights **renormalise over the available factors**, so an absent appearance signal
does not dilute the ranking. Scoring weights: region_fit 0.25, height_agree 0.12,
appearance_sim 0.18, detection_support 0.20, + geometry sub-signals.

**Single dominant lesion** (`candidate_matching.dominant_index`,
`two_stage_controller._dominant_focus`). Clinical assumption: a breast has ONE
dominant suspicious focus, so the output must be one lesion, not many. Across all
source lesions / views, the single strongest **confident** correspondence (highest
`MATCH` score) is promoted to the FOCUSED result (`★ FOCUSED corresponding lesion …`
in the summary + `[3D-Cursor][FOCUS]` log). Ambiguous or no-match entries never
qualify, so unrelated regions are never asserted as pathological. This is what keeps
the result *focused* rather than a scatter of unfiltered detections, and it extends
to bilateral studies (the single most-consistent lesion wins across breasts).

### Status

- **Factors 1 + 2 are live in scoring by default** (pure, guard-tested).
- **Factor 3 is flag-gated OFF** (`AIPACS_CURSOR3D_APPEARANCE=1`): it reads the
  source+target pixel arrays, which currently happens on the GUI thread — fine for a
  validation run, but **production must move the read off-thread before default-on**.
- **The dense visual heatmap is flag-gated OFF** (`AIPACS_CURSOR3D_HEATMAP=1`,
  `region_render.draw_heatmap_field`) — VTK render, **NEEDS LIVE SOURCE-BUILD VERIFY**.
- Guards: `test_factor2_height_prior_is_wide_and_soft`,
  `test_factor3_appearance_matches_density_signature`,
  `test_appearance_factor_enters_scoring_and_breaks_a_tie`,
  `test_combine_renormalises_when_appearance_absent_no_dilution`,
  `test_heatmap_field_builds_with_a_peak` (+ factor 1).
- **Calibration pending** (Phase 0): the height σ, the factor weights, and the
  appearance metric all want tuning against the labelled session store — every run
  keeps saving one.
