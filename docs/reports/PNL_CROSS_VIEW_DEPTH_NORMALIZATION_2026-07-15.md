# PNL cross-view depth normalization — pectoralis-reference upgrade (2026-07-15)

**Patient:** 50513 (haji^fakhryeh), R breast, MLO→CC.
**Reporter:** the radiologist — "a posterior MLO lesion near the pectoral maps to a near-anterior
location in CC; localization cannot be based only on distance from the nipple; the distance to the
pectoralis reference should help."
**Status:** implemented, **PROMOTED to default-ON 2026-07-15** after live validation in both
directions (`AIPACS_CURSOR3D_PNL_NORMALIZE=0` = legacy kill switch). Only active when the pectoral
line is drawn.

## Live validation (2026-07-15) — both directions

- **50513 (MLO→CC, the reported bug):** region moved **55 → 78.4 mm anterior (+23 mm posterior)**; the
  CC band shifted to the posterior third near the chest wall, matching the posterior MLO lesion. ✓
- **50258 (CC→MLO, regression guard):** region at **19.0 mm, ±32 mm band** still covers the true MLO
  detection — no coverage regression. The nominal moved anterior (~37 → 19 mm), absorbed by the band;
  the CC-edge-as-chest-wall reference over-estimates `PNL_CC` for a left breast whose nipple sits far
  from the edge, which is the known CC→MLO axis approximation. If a future case shows a miss here,
  restrict normalisation to CC targets (see caveat). ✓

## Root cause (measured on 50513)

The MLO lesion is posterior **and** superior (55 mm back + 55 mm up from the nipple; radial 78 mm).
The GM locus preserves the **absolute** nipple→lesion anterior depth. But the breast is **not the
same depth** in the two views — the MLO includes more posterior tissue (axillary tail, pectoral) than
the CC. Three ways to measure the MLO depth diverge by up to 23 mm:

| measure | MLO lesion | CC matched box | preserved? |
|---|---|---|---|
| horizontal nipple-distance (what GM uses) | 55.0 mm | 52.1 mm | numerically yes |
| **proximity to the pectoral / chest wall** | 70.6 mm | 30.6 mm | **no — 40 mm off** |

The matcher accepted the CC box because the **absolute** nipple-distance matched (52 ≈ 55). But by the
anatomically faithful **pectoral-proximity** measure the source lesion is deep (70 mm) while the
matched CC box is shallow (30 mm) — a 40 mm error. Absolute depth is preserved; **fractional** depth
(how close to the chest wall) is not, because the two views have different breast depths.

## The fix — Posterior Nipple Line (PNL) normalization

Express the lesion depth as a **fraction of the nipple→pectoral distance** (the PNL — a standard
mammography QA line) and rescale it to the target view's own PNL:

```
f            = depth_source / PNL_source                       (fractional depth, view-invariant)
depth_target = f · PNL_target = depth_source · (PNL_target / PNL_source)
```

`PNL_target / PNL_source` is the **correction ratio** between the views (the CC PNL is typically
~10 % shorter than the MLO PNL). `depth_source` is the **perpendicular** (chest-wall-normal) depth —
the same axis the PNL is measured along.

- **CC PNL** = horizontal nipple → posterior image **edge** (the pectoral muscle is not imaged in CC).
  Always available.
- **MLO PNL** = perpendicular nipple → **pectoral muscle line**. Needs the pectoral line *position*,
  which the guided workflow already captures as two clicks (superior→inferior) — previously reduced
  to just the angle; now the line **point** is also threaded through to the MLO geometry.

## Implementation (all pure, flag-gated, default-OFF)

- `geometry.py` — `MammogramGeometry.pectoral_ref_point_mm` (new, optional) +
  `pectoral_reference_distance_mm()` (CC edge; MLO perpendicular-to-line; `None` when unavailable —
  the MLO image edge is **never** substituted for the muscle).
- `pnl_normalization.py` (new, stdlib) — `compute_pnl_normalization()` → `PnlResult` (legacy
  horizontal depth, perpendicular depth, normalized depth, both PNLs, ratio, availability/reason).
  Flag `AIPACS_CURSOR3D_PNL_NORMALIZE` (default OFF).
- `geometric_model.py` — `raw_anterior_distance_mm()` helper; in `sample_gm_points_px`, when the flag
  is on **and** both PNLs exist, the target locus is placed at the normalized depth. **Byte-identical
  legacy when off or unavailable.** Only the anterior depth is scaled — the locus orientation and the
  factor-2 height prior are untouched.
- `search_region.py` — attaches the `PnlResult` diagnostic to every GM region (independent of the
  flag), so the numbers can be validated live.
- `imaging_tab.py` — threads the picked pectoral line **midpoint** onto the MLO geometry
  (`pectoral_ref_point_mm`). Auto-detect-only path (no manual line) → PNL unavailable → legacy.
- `two_stage_controller.py` / `two_stage_session.py` — logs `[3D-Cursor][PNL]` and persists the full
  PNL block into `mg_3dcursor_sessions.json` for offline analysis.

## Verification

- **Pure math (sandbox):** exact synthetic checks all pass — CC edge PNL, MLO perpendicular-to-line
  distance (0°, 45°, arbitrary), MLO-without-line → `None`, correction ratio, fractional-depth
  preservation (`a_norm / PNL_target == depth_source / PNL_source`), availability gating, legacy
  passthrough when unavailable.
- **Guard tests:** `tests/code/ai_imaging/test_cursor3d_two_stage.py` — 8 new `test_pnl_*` (edge vs
  perpendicular reference, availability, ratio, flag-off byte-identical, flag-on applies, flag-on
  no-op when unavailable, diagnostic serialisable). *(Full pytest must run on Windows — the sandbox
  FUSE mount was truncating the larger edited files this session; the pure math was validated via
  `importlib`, which reads the real bytes.)*

## HONEST CAVEAT — the correction's DIRECTION depends on the real PNLs (validate live)

The math is correct, but whether the normalization pushes the 50513 prediction **posterior** (the
fix) or anterior depends entirely on the **measured** `PNL_MLO` vs `PNL_CC` — which requires the user
to draw the pectoral line. With a guessed pectoral point the correction can go either way. So this is
default-OFF and must be validated live:

- **50513 (MLO→CC, the reported bug):** the target is CC, where PNL = horizontal edge and the placement
  axis is exact — the clean case.
- **50258 (CC→MLO, must not regress):** the target is MLO; the normalized (perpendicular-derived)
  depth is placed on GM's horizontal locus, a mild axis approximation. If live shows a regression,
  restrict the normalization to CC targets.

Read the `[3D-Cursor][PNL]` log line (legacy vs normalized depth + both PNLs + ratio) after a live run
and compare the two predicted boxes against the true lesion before promoting to default-on.

## Follow-up additions (2026-07-15, second pass)

Three refinements after the first live validation:

1. **CC PNL from the posterior TISSUE boundary, not the image edge.** The CC chest-wall reference was
   the raw image edge, which over-estimates `PNL_CC` when the breast does not fill the image (the
   50258 residual). Now `MammogramGeometry.cc_reference_distance_mm` holds the nipple → posterior
   breast-tissue-boundary distance, computed from the segmentation contour (pure
   `geometry.cc_posterior_tissue_distance_mm`: chest-wall-side extreme of the contour — max x for R,
   min x for L). `pectoral_reference_distance_mm()` prefers it and falls back to the edge only when
   the contour is unavailable. Wired in `imaging_tab._start_two_stage_matching` (numpy/cv2 allowed
   there; the pure geometry stays pure). This should pull the 50258 CC→MLO nominal back toward the
   true depth. Guard: `test_cc_posterior_tissue_distance_from_contour`,
   `test_cc_pnl_prefers_measured_tissue_boundary_over_edge`.

2. **Show ALL confident corresponding lesions (multiple / bilateral).** The single-dominant focus is
   replaced by `candidate_matching.focused_indices` — every `MATCH` entry, strongest first — so a
   study with two real corresponding lesions (two on one side, or bilateral) shows BOTH results;
   ambiguous/no-match regions still stay out of the focus list (no scatter). A single lesion reads
   exactly as before. The per-entry region + candidate overlay was already drawn for every unpaired
   lesion and both lateralities. Guard: `test_focused_indices_shows_all_confident_matches_strongest_first`.
   NOTE: true bilateral needs all 4 views loaded; the current EagleEye flow pairs one laterality (2
   views) at a time, so cross-side pairing in one run is a separate, larger follow-up.

3. **Second-pass predicted boxes are CYAN, not yellow/amber.** `region_render` now draws the
   lower-threshold predicted lesion in cyan (`COLOR_MATCH`) and ambiguous alternatives in light blue
   (`COLOR_ALTERNATIVE`, was amber) — distinct from the first-pass AI detections (green boxes). NOTE:
   the yellow *fill* the radiologist saw is the shared AI **segmentation overlay**
   (`viewer_2d.overlay(color=(1,1,0))`), triggered by the main detection flow, not the cursor
   second-pass (which is not segmented). Recoloring that per-threshold is a separate, shared-rendering
   change (the `overlay()` colour param makes it feasible) — deferred pending confirmation that the
   cyan candidate box is what was meant.

## Multiple-findings UX (2026-07-15, third pass)

Once all confident matches showed, 2–3 findings cluttered the viewport (overlapping boxes, detached
labels, stacked heatmaps). Flag `AIPACS_CURSOR3D_FINDINGS_UX` (default on; `=0` = the legacy
draw-everything view). New behaviour:

- **Declutter — review one at a time.** `two_stage_controller._render_findings` draws ONLY the
  selected finding's full overlay (cyan box + region band + heatmap); every OTHER finding is a small
  dim numbered marker. `_build_findings` orders findings by score (strongest first, no-match last);
  the top one is selected by default. `_select_finding(i)` re-renders. So the whole breast is never
  highlighted at once.
- **Leader lines.** `region_render.draw_finding` offsets each label off the box and draws a thin
  leader line back to it, so text is never detached (`_leader_actor`, `COLOR_LEADER`).
- **Two synced pickers.** An on-image corner panel (`findings_panel.FindingsOverlayPanel`, a Qt
  overlay on the destination viewport, click a row to review) AND a sidebar list
  (`imaging_tab.cursor3d_set_findings` → a `QListWidget`), kept in sync through the controller's
  selection state. The sidebar list is the reliable fallback if the Qt-over-VTK corner overlay does
  not paint on a given machine. Both hidden for a single finding (reads as before).
- **Colours:** selected = bright cyan (`COLOR_MATCH`), other findings = dim blue markers
  (`COLOR_FINDING_OTHER`).

Guarded/tested: `region_render.py` + `findings_panel.py` compile clean; the panel index-mapping guard
is `tests/code/ai_imaging/test_cursor3d_findings_panel.py` (Qt-offscreen). The VTK overlay render, the
on-image placement over the viewport, and the sidebar wiring **need live source-build verification**
(the sandbox has no PySide6/VTK this session). `AIPACS_CURSOR3D_FINDINGS_UX=0` reverts to the previous
all-at-once render.

## Step 3 — preserve + categorise every lesion's features (2026-07-15)

**Directive:** store all of a lesion's measured characteristics (geometry AND the box's appearance/
pattern matrix), because the same data answers a SECOND clinical question beyond CC↔MLO matching —
**contralateral** comparison in the SAME view (**R-CC vs L-CC**, **R-MLO vs L-MLO**), where a true
lesion often has no symmetric counterpart. Determine which subset of the data is useful for each of
the three comparison types.

**The pattern descriptor (the box "matrix" features).** `appearance_similarity.describe_region(pixels,
box, spacing_mm)` (numpy, additive — the existing histogram scoring path is byte-identical) returns a
serialisable dict:
- **first-order:** mean, std, skew, kurtosis, entropy, p1/p99, high-density fraction;
- **GLCM/Haralick** (rotation-AVERAGED over 0/45/90/135° → orientation-independent so it survives the
  CC↔MLO rotation): contrast, homogeneity, ASM, correlation, entropy. Falls back from the robust
  p1–p99 range to min–max so a few bright microcalcifications on a flat field still yield texture
  instead of collapsing to None;
- **microcalcification constellation:** high-pass (integral-image box blur) → bright-blob threshold →
  connected components → count, mean size (mm²), mean nearest-neighbour spacing (mm). This is the
  radiologist's "four bright dots here → expect four bright dots there" — the most view-STABLE cue;
- a coarse, explicitly **NON-diagnostic** `lesion_type` tag (`microcalc_like` / `dense_mass_like` /
  `indeterminate`) used only to keep like matched to like.

**The store.** New pure-stdlib `cursor_3d/lesion_feature_store.py` persists one self-identifying
`LesionFeatureRecord` per lesion (patient / study / series / laterality / view / box + a raw geometry
block + the appearance dict) to `mg_lesion_features.json` under
`ATTACHMENT_PATH/<study_uid>/` — atomic write, never raises, keyed by `lesion_uid`.
`load_features_for_patient()` aggregates across a patient's studies (the entry point a future R↔L or
prior-exam pass needs). Geometry is stored RAW (per-view, un-normalised) so a consumer can apply
whichever transform its comparison needs.

**The categorisation — `COMPARISON_FEATURE_APPLICABILITY` (the deliverable).** An explicit,
guard-tested matrix giving, per comparison kind, the geometry transform + the role
(PRIMARY/USEFUL/WEAK/INVALID) of every stored feature:

| | CC↔MLO (same breast) | R-CC↔L-CC | R-MLO↔L-MLO |
|---|---|---|---|
| geometry transform | **cross-view** (uncompress/rotate; depth via **PNL fraction**) | **mirror** (flip medial-lateral; **absolute** geometry) | **mirror** (absolute; + pectoral/PNL + S-I height) |
| depth signal | `pnl_fractional_depth` (PRIMARY) | `axial_depth_mm` absolute (PRIMARY) | `axial_depth_mm` absolute (PRIMARY) |
| height (S-I) | WEAK (unobservable in CC) | PRIMARY (med-lat, mirrored) | PRIMARY (sup-inf, MLO↔MLO comparable) |
| pectoral angle | WEAK (MLO only) | **INVALID** (not imaged in CC) | USEFUL (should mirror) |
| box shape / aspect | WEAK (rotates between views) | USEFUL (same projection) | USEFUL |
| GLCM texture | USEFUL (rotation-averaged only) | **PRIMARY** (same projection → full texture) | **PRIMARY** |
| microcalc count/size | PRIMARY (very view-stable) | PRIMARY | PRIMARY |
| density mean / histogram | PRIMARY / USEFUL | PRIMARY / PRIMARY | PRIMARY / PRIMARY |

The key insight encoded here: **same-view contralateral is a MIRROR of an identical projection**, so
appearance transfers ALMOST FULLY (including shape and near-pixel texture that are unreliable
cross-view) and geometry is directly comparable in ABSOLUTE terms — a different, richer subset than
CC↔MLO. `mirror_x_px()` and `contralateral_pair_kind()` are the pure helpers the future R↔L consumer
will use.

**Wiring.** `two_stage_controller._store_lesion_features(entry, match)` (called from `_persist`) writes
a record for the source lesion (and the corresponding candidate on a confident match). GEOMETRY is
always stored (cheap, no pixels); the APPEARANCE pattern is captured by REUSING the pixel arrays factor
3 already decoded (`entry["_source_pixels"]` / `_target_pixels`) — **no extra GUI-thread read**, so it
is populated when `AIPACS_CURSOR3D_APPEARANCE=1`, geometry-only otherwise. Flag
`AIPACS_CURSOR3D_FEATURE_STORE` (default ON; `=0` disables). Storage is non-clinical and never raises.

Reserved for the step-1/2 geometry refinement: `positioner_primary_angle_deg` +
`body_part_thickness_mm` fields exist on the record (None until the DICOM read is wired).

**Validated (sandbox, numpy+stdlib):** `describe_region` detects the 4-dot constellation
(count 4, `microcalc_like`, GLCM non-None via the min–max fallback), flat region → no constellation,
bad box → `ok:False`; store round-trips + replace-by-uid + patient aggregation; the applicability
matrix asserts cross-view=PNL / contralateral=mirror, `pectoral_angle_deg` INVALID for R-CC↔L-CC,
`box_shape_aspect` WEAK cross-view but USEFUL same-view. Guard:
`tests/code/ai_imaging/test_cursor3d_feature_store.py`. The controller wiring **needs live
source-build verify** (no PySide6/VTK in the sandbox; the FUSE mount also served a stale copy of the
edited `appearance_similarity.py`, so the math was validated by inlining the exact functions). None of
the `cursor_3d/*` files are plugin-mirrored.

**Future (not built — the payoff this preserves):** the contralateral R↔L matcher itself — load both
breasts' records for a patient, mirror the geometry, and score symmetry with the same-view feature
subset to flag asymmetries. The data is now captured for it.

## DICOM acquisition geometry wired in (2026-07-15)

The step-1/2 research identified the one unexploited geometry lever: we ASSUME the MLO obliquity (~45°)
instead of READING it, even though it is in the header. Now wired:

- **`_read_dicom_pixel_geometry` (imaging_tab.py)** additionally reads **Positioner Primary Angle
  (0018,1510)** — the true MLO gantry obliquity — and **Body Part Thickness (0018,11A0)** — compressed
  breast thickness (mm). Both are carried on `ViewData` (additive optional fields) through both view
  builders.
- **`geometry.pectoral_angle_from_positioner_angle(ppa)`** (pure, tested): folds the vendor's
  sign/quadrant convention (`abs`, wrap to [0,180], reflect across 90) to a positive "angle from
  vertical" MAGNITUDE — the geometry applies the left/right sign itself from laterality. Returns None
  (→ legacy behaviour) for an absent/garbage value or one outside the plausible MLO band [10°, 80°], so
  a CC's ~0° or a ~90° lateral is never fed in as a pectoral tilt.
- **MLO pectoral-angle fallback (`_start_two_stage_matching`):** when the radiologist has NOT drawn the
  pectoral line, the MLO pectoral angle now falls back to the DICOM obliquity instead of leaving the
  MLO depth-normal horizontal (undefined). The **manual line stays authoritative** (the fallback only
  runs when `pectoral is None`). Flag `AIPACS_CURSOR3D_DICOM_ANGLE` (default **OFF** — geometry-
  affecting, needs live validation; the gantry angle is a per-unit APPROXIMATION of the pectoral-line
  angle). Logs `[3D-Cursor][PNL] MLO pectoral angle from DICOM PositionerPrimaryAngle=… -> …°`.
- **Both raw values are STORED** on every lesion record (`LesionGeometryFeatures.
  positioner_primary_angle_deg` / `body_part_thickness_mm`, default-on) — populated from the view data
  in `_store_lesion_features`. `Body Part Thickness` is not yet used in any calculation; it is preserved
  for the future GM uncompression model (which needs the true acquisition angle + compressed thickness).

**Safety.** Reading the tags and storing them is non-clinical and byte-identical when the tags are
absent. The only geometry-affecting change (the pectoral fallback) is flag-gated default-off and never
overrides a drawn line. Pure normalizer validated in the sandbox (45/−45/135 → 45; 200 → 20; 0/90/5/NaN/
None/"bad" → None); guard `tests/code/ai_imaging/test_cursor3d_feature_store.py`. The imaging_tab wiring
+ the on-image fallback **need live source-build verify** on a unit that actually populates 0018,1510
(many mammography units leave it empty — then the fallback is inert and nothing changes).

## Contralateral (R↔L) symmetry matcher — the second clinical question (2026-07-15)

The payoff of the feature store. The 3D Cursor answers "where is this lesion in the OTHER VIEW of the
same breast?" (CC↔MLO). The contralateral matcher answers the complementary question radiologists use
to decide whether a finding is real: **"does the OTHER BREAST have a matching finding at the mirror
location?"** (R-CC vs L-CC, R-MLO vs L-MLO). A finding with a good symmetric counterpart is usually
benign; a finding with **no** counterpart is a developing/asymmetry — the output is INVERTED versus the
cross-view matcher (a match here LOWERS concern; no match RAISES it).

**Why it is a pure engine over the stored records.** The store already keeps each lesion's geometry in
BREAST-RELATIVE coordinates (depth measured from the nipple toward that breast's OWN chest wall via the
laterality-aware depth normal, plus radial nipple distance and height offset). For a symmetric finding
these are ~EQUAL in the two breasts — **the mirror is already baked into the coordinates**, so no pixel
flipping is needed. The persisted appearance descriptors (density, rotation-averaged GLCM, the
microcalcification constellation count/size/spacing, the lesion-type tag) are all mirror-INVARIANT, so
they compare directly. `contralateral_matcher.py` therefore reads ONLY the record dicts — no images,
Qt, VTK, or numpy — and is fully sandbox-testable.

- **`score_symmetry(query, candidate)`** → [0,1] over geometry (dominant: axial-depth/radial/height
  decays, wide 18 mm tolerances that respect natural L/R asymmetry) + mirror-invariant appearance
  (density, GLCM, microcalc constellation, lesion type). Weights renormalise over available components,
  so a geometry-only record still scores on position alone.
- **`match_contralateral(query, candidates)`** → SYMMETRIC (counterpart clears the floor) / AMBIGUOUS
  (several plausible mirrors) / **ASYMMETRIC (no counterpart → `asymmetry_flag=True`)** — the case to
  surface.
- **`analyze_records()` / `analyze_patient_symmetry_from_store(patient_id, attachments_path)`** — pair
  every 'picked' lesion against same-view/opposite-laterality lesions and flag the lone ones; the store
  convenience loads a patient's records across studies.

**Clinical posture — decision support, NOT diagnosis.** "No contralateral counterpart" means "possible
asymmetry — review", never "malignant". Tolerances are deliberately wide; the engine never downgrades a
lesion on its own, it only raises a review flag. The gate that lets any UI SURFACE the flag is
`AIPACS_CURSOR3D_CONTRALATERAL` (default **OFF** — showing an asymmetry call is a clinical action to be
validated and enabled deliberately); the pure engine can be called regardless.

**Validated (sandbox, pure):** symmetric pair 0.96 → SYMMETRIC; geometry mismatch 0.31 → ASYMMETRIC;
geometry-only renormalises to 0.97; a microcalc-presence mismatch lowers the score (0.87 vs 1.0); the
lone R-MLO lesion is asymmetry-flagged; only same-view/opposite-laterality records are considered; and an
end-to-end persist→`analyze_patient_symmetry_from_store` pass reproduces the same statuses. Guard
`tests/code/ai_imaging/test_cursor3d_contralateral.py`. `contralateral_matcher.py` is not plugin-mirrored.

**Wired into the workflow (2026-07-15).** `two_stage_controller._run_contralateral_analysis(scored)`
runs at the end of `_try_match` — AFTER every lesion of the run is persisted, so the store holds both
breasts. It derives the patient id from the processed views, calls
`analyze_patient_symmetry_from_store`, logs one `[3D-Cursor][SYMMETRY]` line per lesion, and stashes a
`self._symmetry_note`. That note is appended to the findings panel text (both the default
`_findings_report_text` and the legacy report path), headed **"⚠ ASYMMETRY REVIEW — finding(s) with no
contralateral counterpart"** for flagged lesions, or a one-line "every finding has a mirror counterpart"
when all are symmetric. The whole pass is gated by `AIPACS_CURSOR3D_CONTRALATERAL` (default **OFF**) and
wrapped so it can never raise into the Qt-signal finalize (which `main.py::notify` would turn into an app
crash). Source-pinned by the guard test.

## Defaults promoted to ON (2026-07-15, per directive)

Three previously flag-gated-OFF additions were switched **default-ON** (each keeps its `=0` kill
switch):

- **`AIPACS_CURSOR3D_CONTRALATERAL`** — the R↔L asymmetry pass now runs and surfaces the note by
  default. Safe: pure engine, text-only surface, decision-support (never a diagnosis, never downgrades),
  wrapped so it can't raise into the Qt finalize.
- **`AIPACS_CURSOR3D_APPEARANCE`** — factor-3 appearance scoring AND the pattern-matrix capture into the
  feature store now run by default, so the microcalc/texture descriptors are preserved for every match
  (this also means the contralateral matcher gets appearance, not geometry-only). KNOWN caveat kept as a
  tracked follow-up: the source+target pixel read is on the GUI thread (bounded — 2 decodes per finding
  at match-finalize, cached; not per-candidate). Moving it off-thread is the remaining optimisation.
- **`AIPACS_CURSOR3D_HEATMAP`** — the dense factor heatmap overlay renders by default; the render is
  wrapped (`_maybe_draw_heatmap` logs + never raises) so a VTK issue degrades to "no overlay".

**`AIPACS_CURSOR3D_DICOM_ANGLE` stays OFF** (not selected) — it is geometry-affecting and still needs
live validation on a unit that populates 0018,1510.

Validated: `contralateral_enabled()` default-ON + kill switch (pure); the two controller flag defaults
source-pinned (`"1"`). Guard `tests/code/ai_imaging/test_cursor3d_contralateral.py`.

## LIVE VERIFICATION + two fixes (2026-07-16, patient 50513 L-MLO→CC)

First live run of the promoted defaults. The log (`app.log.1`) + the on-disk `mg_lesion_features.json`
confirmed the whole pipeline runs end-to-end with **no errors/tracebacks**:

- `[3D-Cursor][FEATURES] stored lesion descriptors (L MLO->CC, appearance=yes)` ×2 — feature store +
  appearance (default-on) working. The stored record carries the full geometry AND the pattern matrix:
  the **microcalcification constellation was detected — 30 and 45 bright dots**, mean spacing 2.3 / 1.6
  mm, plus first-order + GLCM + `lesion_type: microcalc_like`. The DICOM read landed too —
  `positioner_primary_angle_deg: -45.0`, `body_part_thickness_mm: 64.0` (stored even though the
  angle-USE fallback is off, as designed).
- `[3D-Cursor][3-FACTOR]` ×6, `[PNL]` ×6 — appearance scoring + PNL diagnostics active.

**Two issues the log surfaced, both fixed:**

1. **Empty `patient_id` → the symmetry pass skipped** (`[SYMMETRY] no patient id — contralateral pass
   skipped`; every stored record had `patient_id: ""`). Root cause: `ViewData` never carried a patient
   id. Fix (same pattern as the DICOM tags): `_read_dicom_pixel_geometry` now reads **PatientID
   (0010,0020)**, `ViewData` gains a `patient_id` field, and both view builders thread it through — so
   the feature store and the contralateral pass key on the real id.
2. **Absence of data must not read as asymmetry.** Once patient ids populate, a normal *unilateral* run
   would have flagged its own lesions "asymmetric" only because the other breast hadn't been analysed.
   Added a distinct **`INSUFFICIENT`** outcome: no analysed finding in the contralateral breast →
   "insufficient data, NOT an asymmetry" (`asymmetry_flag=False`). `ASYMMETRIC` is now reserved for the
   real signal — a counterpart EXISTS but does not match. The panel note distinguishes all three
   (asymmetry review / all symmetric / not-analysed).

Guards updated (`INSUFFICIENT` vs `ASYMMETRIC`, the distinguishing analyze-records case). **NEEDS a
re-run on the source build** (the running process predated these two fixes): confirm records now carry
`patient_id`, and that a study with findings in BOTH breasts produces a real `[3D-Cursor][SYMMETRY] …
symmetric/asymmetric` line (not "no patient id"). Heatmap overlay + appearance decode confirmed working
live with no stall on this study. An on-viewport visual marker for asymmetric findings (vs the text
panel) remains a follow-up.

## EAGLE EYE MG sidebar redesign (2026-07-16)

Reported: the left (EAGLE EYE) panel is too crowded and several fields are too small for their text.
The panel was a flat vertical `addWidget` stack of ~26 widgets (`_build_mg_sidebar_ui`, imaging_tab.py).
Redesigned into **four collapsible sections** (checkable `QGroupBox` — click the title to expand/collapse):

- **Finding** (expanded) — Detail Box + Status radios as compact form rows, finding status/summary,
  Classification.
- **Findings Report** (expanded) — the 3D-cursor findings list + the report/symmetry text
  (`feature_view`, now min-height 130 so it actually shows the findings + asymmetry note).
- **Review & Correction** (collapsed) — Validation + Reviewer as form rows, Correction Notes, and the
  four actions (Confirm/Reject/Correct/New) in a **2×2 button grid** instead of four full-width rows.
- **AI Results** (collapsed) — model-run combo + Apply.

Sizing fixes for "fields too small": combos get `Expanding` policy + 150px min width; the summary label
wraps; notes/feature text areas get sane min/max heights; form rows put the label beside the field
(compact) instead of above it.

**Safety:** the redesign ONLY re-arranges the SAME pre-created widgets (all created + wired in
`_init_mg_widgets`) — it creates/removes/rewires nothing, so every signal/handler is intact. The whole
V2 path is gated `AIPACS_EAGLE_EYE_SIDEBAR_V2` (default ON); `=0` falls through to the **byte-identical
legacy flat stack** (kept in place, non-ASCII comments untouched). New methods: `_eagle_sidebar_v2_
enabled`, `_mg_group`, `_build_mg_sidebar_ui_v2`. Syntax validated standalone (the sandbox mount can't
reliably read the large edited file). **NEEDS live source-build verify**: open EAGLE EYE on an MG study
and confirm the four sections render, collapse/expand works, text fits, and every control still
functions; if anything looks off, `AIPACS_EAGLE_EYE_SIDEBAR_V2=0` restores the old panel instantly. Only
the MG sidebar changed — the DX (Bone Age) sidebar is untouched. A scroll area for very tall expanded
states is a possible follow-up.

**Header-clip fix (2026-07-16, live follow-up, 2 passes):** first render showed each section title
overlapped by its content (the classic checkable-`QGroupBox` issue — no space reserved for the title).
Pass 1 (`subcontrol-origin: margin`) made the titles visible but the title-above-frame drew too close to
the box above (mild vertical overlap between sections). Pass 2 (final) draws the title INSIDE its own
frame: `QGroupBox{border:1px solid rgba(128,128,128,.35); border-radius:6px; margin-top:6px; padding-
top:18px}` + `QGroupBox::title{subcontrol-origin:padding; subcontrol-position:top left; left:8px;
top:3px}`, with the content layout top-margin at 2px. Each header is now fully contained in its section,
so adjacent boxes can't overlap; the `margin-top:6px` gives a clean gap between frames. NEEDS the same
live re-verify.

**Checkbox alignment + theming (2026-07-16, final).** (a) Two competing constraints, resolved after a
few passes. `subcontrol-origin:margin` (title above the frame) preserves native checkbox↔text alignment
BUT overlaps the box above, because Qt's layout does not reliably reserve the CSS top-margin for the
title (recurring overlap). Overriding `::indicator` position to "fix" alignment made it worse (it
decouples the checkbox from the title). FINAL: `subcontrol-origin:padding` — the title is drawn INSIDE
the frame in a reserved `padding-top:22px` strip, so it lives fully within its own box and CANNOT overlap
the neighbour (frames separated by `margin-top:8` + layout spacing 8); NO `::indicator` override, so the
checkbox keeps the style's native alignment with the title text. Two lessons: (1) draw a collapsible
section title inside the frame (padding), not in the margin, to guarantee no overlap; (2) never override
a QGroupBox `::indicator` subcontrol-position. FOLLOW-UP: when COLLAPSED the header sat at the top of the
(short) box, not centred. Made the title vertical position STATE-DEPENDENT — `subcontrol-position:center
left` when collapsed (title+checkbox vertically centred), `top left` when expanded (unchanged, content
below). Only the colour-free `QGroupBox::title` rule is swapped on `toggled` (via string replace on the
current sheet), so the box geometry doesn't move and any retinted border colour is preserved. (b)
THEMING EVALUATION (user asked):
the EagleEye module does NOT follow the Windows OS light/dark theme — by design it runs its OWN theme
(`AiMainWindow._apply_dark_theme` sets a global stylesheet with the Eagle Eye palette hex; on app-theme
change `_on_app_theme_changed`→`_ee_retint_widget_tree` REGEX-swaps those hex to the live app theme via
`_ee_theme_color_map`). The input fields (`QLineEdit/QComboBox/QTextEdit`) ARE covered by that global
themed stylesheet, so they follow the APP theme. The fix: my new group border had used a raw
`rgba(128,128,128,.35)` that the retint can't remap (not a palette hex) — switched to the palette
**`#2d3748`** so the sections retint WITH the theme like every other border; the title text inherits the
themed `#f7fafc`. Following the OS theme instead of the app theme would be a separate, larger change
(the whole module is app-themed on purpose).
