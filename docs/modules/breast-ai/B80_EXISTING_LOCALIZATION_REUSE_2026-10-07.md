# B80: Reuse the existing breast localization engine

Date: 2026-10-07. Status: source audit and existing synthetic-test verification.
No training, patient evaluation, runtime modification or deployment in this record.

## Finding and decision

The workstation already contains the relevant anatomy-aware machinery in
`modules/ai_imaging/ai_module_ui/cursor_3d/`. B79 did not use this subsystem;
its small bilateral benefit therefore does not evaluate this existing engine.
Reuse its pure geometry and feature extraction before building another localizer.
This audit inspected the local checkout, not the installed Razi workstation or
active server revision; deployment parity and live behavior remain unverified.

## Reusable components

- `geometry.py`: pixel spacing, nipple position, chest-wall orientation, lesion
  depth, and reference-line geometry in physical coordinates.
- `pnl_normalization.py`: source-to-target depth scaling using each view's
  posterior nipple line, with availability information and fallback behavior.
- `correspondence_arc.py`, `geometric_model.py`, `search_region.py`: existing
  cross-view search-region infrastructure; not proof of exact tissue registration.
- `lesion_feature_store.py`: breast-relative geometry and appearance records.
- `contralateral_matcher.py`: opposite-side, same-projection matching over records,
  using depth, radial distance, height, density, texture and calcium descriptors.
- `two_stage_controller.py`: existing workflow hook for contralateral analysis.

## Gaps before automatic reuse

1. The workflow uses picked landmarks and stored analyzed findings. Research images
   need label-blind landmark extraction or reviewed landmarks, native pixel spacing,
   orientation, and explicit coordinate transforms from detector input to source.
2. The contralateral matcher compares stored findings, not arbitrary normal tissue
   in the opposite breast. Extract a corresponding tissue patch even when the
   detector produced no opposite-side finding. Otherwise absence of data is confused
   with absence of a counterpart. Current empty-pool status is insufficient data.
3. `analyze_records` filters side/view but does not itself enforce patient/study
   identity. The store wrapper loads a patient's records across studies. An offline
   adapter must restrict to one verified examination and patient before matching.
   `match_contralateral` itself expects an already filtered candidate list.
4. Current bilateral geometry scoring uses absolute distances with fixed 18 mm
   tolerances; it does not use PNL fractional depth. Compare absolute and normalized
   geometry on development data rather than assuming either is optimal.
5. The runtime function `contralateral_enabled()` defaults to false, despite its
   older docstring claiming default-on. Its comment records a July close-regression
   investigation. Do not enable the GUI feature as part of this research audit.
6. Heuristic symmetry scores are not calibrated probabilities. Missing counterpart
   does not establish disease, symmetry does not establish normality, and bilateral
   comparison alone cannot establish a developing finding. Old explanatory comments
   in this subsystem must not be treated as validated clinical rules.

## Verification and evidence limits

Existing focused tests executed with the checkout `.venv` Python, offscreen Qt,
`PYTHONPATH=.` and direct pytest, with the debugging plugin disabled:
`test_cursor3d_contralateral.py`, `test_cursor3d_feature_store.py`,
`test_cursor3d_mlo_depth_projection.py`, `test_cursor3d_view_identity.py`.
Result: 50 passed, 2 expected failures, exit code 0. Expected failures concern the
old empty-counterpart expectation and guided-workflow step expectations. They are
not passes. No live GUI pass or clinical accuracy measurement was performed.
Training, checkpoint, cohort metrics and GPU telemetry are not applicable to this
source audit. Installed-source parity and anatomical correspondence accuracy are
not verified. No patient records or coordinates were added to the repository.

## Next experiment

Build an isolated adapter around the existing pure engine, scoped to one study:
native image/metadata -> landmarks and quality flags -> breast-relative candidate
geometry -> opposite-side search patch and CC/MLO search region -> appearance
features -> second-stage reranker. Return unavailable when correspondence fails;
preserve the single-view candidate. Do not hard-delete on symmetry alone.

Start with TRAIN/development studies and visually review correspondence before
fitting. Compare local-only, B79 bounding-box normalization, and existing-anatomy
features on identical candidate lists. Track correspondence availability, localization
error where reviewed, lesion-identity retention, false marks and CPU time. Keep the
exposed TEST cohort out of threshold/model selection. This is the selected reuse
path, not a completed integrated or trained model.
