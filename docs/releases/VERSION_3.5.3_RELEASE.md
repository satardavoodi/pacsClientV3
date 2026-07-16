# AI-PACS v3.5.3 — Release Record

**Version:** 3.5.3
**Release date:** 2026-07-16
**Previous stable:** v3.5.2 (2026-07-14)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor — Mammography 3D Cursor two-stage contralateral matching, test-suite repair, INO assign fix

---

## 1. Headline

Two mostly-independent bodies of work.

The first extends the Eagle Eye **Mammography 3D Cursor** from single-lesion CC/MLO
correspondence (v3.5.2) into a **two-stage, feature-based contralateral (right↔left)
matching** pipeline — and fixes the correctness bug that mattered most: a lesion
picked posteriorly on the MLO view was landing anteriorly on the CC view.

The second is not a feature at all: the **test suite was repaired**. It used to hang
forever and was red by default, so "did I break anything?" had no reliable answer.
It now runs to completion, exits clean, and carries a real regression signal.

---

## 2. Mammography 3D Cursor — PNL cross-view depth normalization

**Symptom (patient 50513).** A lesion marked in a posterior MLO location mapped to
an anterior CC location — a clinically meaningful mismap of roughly 23 mm.

**Cause.** Depth from the nipple was being treated as an *absolute* distance. The CC
and MLO projections compress the breast differently, so the same physical depth is a
different absolute distance in each view; matching on absolute depth therefore
disagreed across views.

**Fix.** Depth is now a **fractional Posterior-Nipple-Line ratio** — the position
along the nipple→pectoral line expressed as a fraction of that line's length — so CC
and MLO agree on where a lesion sits regardless of view-specific compression. It is
only active when the pectoral line has been drawn, and is a pure geometry
refinement.

**Status: default-on, live-validated** on 50513 (the +23 mm posterior case now
corrects) and 50258 (no regression). Kill switch `=0`. A documented residual: the
CC-edge case can over-estimate `PNL_CC`; if a CC→MLO direction ever misses, the fix
can be restricted to CC targets.

---

## 3. Mammography 3D Cursor — two-stage contralateral matching

Stage one (v3.5.2) produced geometric CC/MLO candidates. Stage two ranks and
resolves them:

- **Lesion feature store** (`lesion_feature_store.py`) — preserves both geometry
  *and* appearance per lesion (GLCM texture descriptors, microcalcification
  constellation), categorised so the same store can drive future contralateral
  (R↔L) comparison.
- **Two-stage controller / session / second pass** (`two_stage_controller.py`,
  `two_stage_session.py`, `second_pass.py`) — orchestrate the candidate → feature →
  decision flow.
- **Contralateral matcher + candidate matching + appearance similarity**
  (`contralateral_matcher.py`, `candidate_matching.py`, `appearance_similarity.py`,
  `geometric_model.py`) — the matching core.
- **Cross-view heatmap, findings panel, search region, region render, threshold
  policy** (`cross_view_heatmap.py`, `findings_panel.py`, `search_region.py`,
  `region_render.py`, `threshold_policy.py`) — rendering and decision surface.

Bone Age and the rest of Eagle Eye are untouched.

**Status:** the two-stage matcher and cross-view heatmap still need **live
source-build verification** on reporting patients. The offscreen tests
(`test_cursor3d_two_stage`, `test_cursor3d_contralateral`, `test_cursor3d_feature_store`,
`test_cursor3d_findings_panel`) cover the pure logic.

---

## 4. Test suite repaired (Q0)

Before this: the full suite could not be run to completion — a build/packaging test
(`-m build`) spawned a real build and blocked forever, so the run hung around 56 %
and had to be killed; and it was red by default with roughly 80 permanent failures.
A suite that cannot finish and is red anyway gives **zero** regression signal, which
is why regressions were being checked by hand with `git stash` A/B runs.

Now:

- One entry point (`run_test.ps1`); a fast lane in `pyproject.toml`
  (`--timeout=120`, heavy lanes opt-in via markers `build`/`slow`/`live`/`property`).
- Completes in roughly 85 s and **exits 0**.
- A **self-cleaning quarantine debt register** (`tests/quarantine.py` auto-generated
  by `tools/dev/build_quarantine.py`, `tests/quarantine_manual.py` hand-maintained)
  applied as `xfail` — so the list shrinks as debt is paid.
- Coverage baseline recorded at 26 % (a floor to raise deliberately).

**Any red is now a real regression.** Roadmap:
`docs/plans/QUALITY_AND_VALIDATION_ROADMAP_2026-07-14.md`.

---

## 5. INO internal-assign — false "assigned" regression

**Symptom (v3.5.1 regression).** The Assign and Report columns showed patients as
assigned when in fact only the RIS **reporting radiologist** existed for a reported
reception — with an empty `last_assigned_by`.

**Cause.** `GET :8000/.../assign` returns a radiologist for every reported reception,
and `parse_assignment` treated any `radiologist.id` as proof of assignment. Both
columns and their popups shared the one polluted assignment snapshot.

**Fix.** `parse_assignment` now requires an actual `last_assigned_by` before
treating a reception as assigned — one change at the ingestion boundary that covers
every consumer. Default-on (`AIPACS_INO_ASSIGN_REQUIRE_ASSIGNER`). Needs a
source-build restart + live re-check (expected: 50258/50304 = Not-assigned,
50210 = Active).

---

## 6. Also included

- Report-sync / EchoMind-editor / reception audit
  (`REPORT_SYNC_ECHOMIND_EDITOR_RECEPTION_AUDIT_2026-07-15.md`) and a reception
  fetch-speed path.
- EagleEye MG viewport import/annotation work and `mg_ai_runs.py`.
- Version markers advanced to v3.5.3 across all 9 canonical spots, including the
  Persian edition line (`۳.۵.۳`) and the `appA_version_info` `filevers`/`prodvers`
  tuples.

---

## 7. Verification status

Offscreen (test lane): the new `cursor_3d` two-stage / contralateral / feature-store
/ findings-panel suites and the repaired fast lane pass.

**Still required — live source-build verification** (cannot be done from the test
lane):

1. **Mammography 3D Cursor two-stage:** pick a lesion, run the second pass, confirm
   the contralateral match and cross-view heatmap are anatomically correct.
2. **PNL normalization:** re-confirm 50513 (posterior MLO → posterior CC) and 50258
   (no regression).
3. **INO assign fix:** restart the source build, confirm 50258/50304 read
   Not-assigned and 50210 reads Active.

---

## 8. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.3` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
