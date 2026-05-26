# Responsive UI Scaling Plan — Pre-Implementation Review
**Reviewer:** AI-PACS engineering agent
**Date:** 2026-05-26
**Plan reviewed:** `docs/plans/RESPONSIVE_UI_SCALING_PLAN.md` (created 2026-05-20, revised 2026-05-26)
**Verdict:** **Approved and locked (2026-05-26).** All three open gates resolved by user. Standards verification against Qt 6.11 official documentation confirms `sf()` is the recommended pattern for in-app user-controllable UI scaling on top of Qt's native HiDPI pipeline. Plan is safe to begin Phase 0 implementation.

---

## 1. Verdict at a glance

| Aspect | Assessment |
|--------|------------|
| Architectural approach (`sf()` helper, identity at 1.0) | Sound. Minimal-intrusion, easy to revert, performance-safe. |
| Inventory completeness | Mostly complete; added `reception_panel_widget.py` in revision. Spot-checks confirm line-numbers in plan match live code. |
| Regression safety | Acceptable, provided the per-tier gate on Phase 5 is enforced and the multi-study regression-guarded files are touched only at the literal numbers. |
| Persistence design | **Was broken** for frozen builds (wrote to non-writable code dir) — fixed in revision. |
| Auto-detect on first launch | **Was unsafe** (would double-scale on top of Qt 6 native scaling) — now opt-in via Settings only. |
| Effort estimate | Original ~13 h too optimistic; revised ~15 h end-to-end is realistic. |
| Visual regression tooling | Missing. Manual screenshot diff is acceptable for the identity gate, but a Pytest-Qt + image-hash harness would be a sensible follow-up. |

---

## 2. What was wrong with the original plan

### 2.1 Critical — Config persistence into a non-writable directory
`§3.1` wrote to `BASE_PATH / "config" / "viewer_backend_settings.json"`. In a frozen Nuitka build `BASE_PATH = PROJECT_ROOT` resolves to the install directory (e.g. `d:\ai-pacs\aipacs\`), which is **not user-writable**. Every save attempt in production would silently fail (`save_scale_to_config()` swallows the `PermissionError` in `except: pass`), and the user-visible "Apply" button in Settings would do nothing. The dev mode worked, masking the problem.

**Fix applied:** Persistence now resolves via `PacsClient.utils.config.SOCKET_CONFIG_PATH`, which is the project's standard writable-config dir (`roaming_config_root()` in frozen mode, `BASE_PATH/config` in dev mode). The key now lives in a dedicated `ui_settings.json` rather than being mixed into the viewer-backend config consumed by `modules/viewer/viewer_backend_config.py`.

### 2.2 Critical — Silent double-scaling on first launch
`§3.2` set the startup scale to `detect_screen_scale()` if no saved value existed. PySide6 / Qt 6 **already auto-scales** on high-DPI displays — there is no opt-out (the Qt 5 `AA_EnableHighDpiScaling` attribute was removed). Confirmed `main.py` does **not** disable Qt's auto-scale and does not set `AA_Use96Dpi` either. So the original auto-detect would have stacked on top: at 150% Windows scaling the UI would render at ~2.25× target size on first launch.

**Fix applied:** Startup default is `_scale_factor = 1.0`. The user adjusts via Settings → restart. `detect_screen_scale()` is kept as a function but is no longer invoked at startup; it remains available for future "suggest a scale" UX.

### 2.3 Important — Phase 5 was a single 4 h commit on a 6900-line file
`toolbar_manager.py` has 21 `QSize/setIconSize` call sites alone and the plan listed 5 different size tiers (badge / button / icon / font / logo). A single commit across all five would have been very hard to revert cleanly if any one tier broke layout.

**Fix applied:** Phase 5 is now 5 separate commits with a toolbar smoke test gate between each. Each commit can be reverted independently.

### 2.4 Important — Multi-study regression-guarded files not flagged
Project `CLAUDE.md` calls out a specific set of files protected by the 2026-05-24 multi-study fix (`_vc_load.py`, `_vc_switch.py`, `_pw_panels.py`, `patient_widget_core/widget.py`). The plan touches two of them (`_pw_panels.py`, `widget.py`) without referencing the multi-study guard.

**Fix applied:** Risk #12 added; phase 4 header now explicitly references the multi-study regression guard.

### 2.5 Minor — Missing file
`reception_panel_widget.py` has 10 `font-size: 14px` matches plus a few `setFixed*` calls and is sibling to the panel widgets being scaled. Omitting it would leave the reception panel visibly inconsistent with the rest of the sidebar.

**Fix applied:** Added to Phase 4 inventory.

### 2.6 Minor — External QSS files
The plan did not state whether external `.qss` files exist. **Verified:** none on disk. All Qt stylesheets are embedded Python strings, so the inventory is complete on that dimension.

---

## 3. What the original plan got right (and we kept)

- **`sf()` identity at 1.0** — zero-overhead and pixel-identical when off. This is exactly the right safety invariant for a project where "no regression" is rule #1.
- **`__init__`-time scaling only** — never inside paint / wheel / set_slice. The performance rules P1–P5 in `§6` are correctly framed for this codebase.
- **Phased rollout with atomic commits** — each phase is independently revertable.
- **Explicit out-of-scope list** — `vtk_widget.py`, `lightweight_2d_pipeline.py`, MPR 3D, download manager UI, etc. are correctly excluded. The viewer hot-paths are the right places to stay clear of.
- **Plugin mirror sync rule (Phase 7)** — single-source-of-truth via SHA equality is the established pattern in this repo.
- **CSS-as-f-string at __init__** — the right idiom for scaling pixel literals embedded in stylesheets.
- **`sf_pt()` for fonts** — distinguishes from `sf()` for geometry. Combined with the `28px → sf_pt(18)pt` conversion in R6, this respects Qt's font system correctly.

---

## 4. Technical feasibility

**High.** The core mechanic is a 1-line function call wrapping integer literals. It is:

- **Reversible** — `git revert HEAD` per phase.
- **Testable** — identity check at 1.0 confirms zero regression; 1.25/0.85 smoke confirms scaling actually applies.
- **Performance-safe** — every call is `__init__`-time and identity-fast at 1.0.
- **Localised** — no architectural change to widget hierarchy, signals, layouts, threading, or data flow.

The hard parts are not technical; they are operational:
- Maintaining discipline across ~20 files of literal-number replacements.
- Avoiding accidental refactor or restructure inside a "scaling" commit.
- Catching layout overflow on monitors the developer doesn't have. Mitigated by clamp range `[0.75, 1.50]` plus the optional 1.25/0.85 smoke tests.

---

## 5. Implementation strategy (recommended order)

1. **Phase 0** — `ui_scaling.py` (new file, zero risk). Land this and ship it. Confirm `from PacsClient.utils.ui_scaling import sf, sf_pt, sf_f` works from any module.
2. **Phase 1** — `mainwindow_ui.py`. Title bar / window buttons are visually isolated; ideal first real consumer.
3. **Phase 2** — `AIPacs_ui.py` constants. Only 6 lines change, propagation is automatic, broad coverage with minimal edits.
4. **Phase 3** — `patient_tab_widget.py`. Tab chips. Self-contained.
5. **Phase 6** — Settings UI (deliberately *before* Phase 4). The Settings tab is non-critical to clinical workflow; getting it right gives us a place to put the user-facing slider in Phase 10 before we touch sensitive viewer code.
6. **Phase 4** — Viewer sidebar (5 files, multi-study regression-guarded). Re-read `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` before this phase. Run multi-study smoke test after.
7. **Phase 5** — Toolbar (Tier A → B → C → D → E, each its own commit + smoke test).
8. **Phase 7** — `printing_widget.py` + plugin mirror. Phase-out the cohabitation between `_scaled()` and `sf()` (decision: keep both; documented).
9. **Phase 8** — `cd_burn_dialog.py`.
10. **Phase 9** — `web_browser/widget.py`.
11. **Phase 10** — Wire `main.py` startup + Settings slider. Last so we don't surface the knob until everything it controls is actually scaled.

The reordering (6 before 4) makes the *user-visible* deliverable (a working scale slider in Settings) ready before we touch the highest-risk viewer code.

---

## 6. Programming standards & best practices

The plan now embodies the following standards (encoded in `§14` and `§15` of the revised plan):

1. **Pass logical pixels to Qt.** Qt 6 handles physical-pixel multiplication for high-DPI; `sf()` is an additional *user-preference* layer on top.
2. **`pt` for fonts.** Qt scales `pt`-typed fonts by DPI correctly. `sf_pt()` composes with Qt's font pipeline.
3. **One `setStyleSheet()` per widget per lifetime.** Build the CSS string at `__init__`, store it, never re-apply it on resize/scroll/paint.
4. **Single source of scale** — `ui_scaling.py` owns the factor; `PrintingWidget._scaled()` is the documented exception for per-screen accuracy on multi-monitor setups.
5. **No hot-path calls.** Grep gate before each commit: `git diff --staged | rg "sf\(" | rg "paintEvent|wheelEvent|set_slice"` — must be empty.
6. **Identity gate.** Every commit must keep `_scale_factor = 1.0` pixel-identical to baseline.
7. **Per-phase atomic commits.** Each phase rolls back with a single `git revert HEAD`.
8. **No collateral edits.** A scaling commit changes literal numbers only. No rename, no reorder, no add/remove widget.

These align with PySide6/Qt 6 community best practices for retrofitting scaling into a mature codebase: minimise intrusion, leverage Qt's native pipeline, give the user a manual override, avoid auto-magic that could double-scale.

---

## 7. Open risks & how we mitigate them

| Risk | Mitigation |
|------|------------|
| Phase 5 toolbar drift (6900 lines) | Per-tier commits + smoke gate between each tier |
| Multi-study regression (Phase 4 touches guarded files) | Re-read `MULTI_STUDY_SINGLE_TAB_PLAN.md` first; touch only literal numbers; full multi-study test pass after |
| Multi-monitor drift between `_scaled()` and `sf()` | Documented as known limitation; both are `__init__`-time so drift is minor and visible only on cross-monitor drag-and-redock |
| Frozen-build settings persistence | Fixed via `SOCKET_CONFIG_PATH` |
| Qt 6 auto-scale stacking | Fixed by defaulting to 1.0 startup |
| Pixmap blur on icons at non-integer scales | Out of scope for this plan; flagged as follow-up — SVG migration would be the long-term fix |
| Visual regression infrastructure | Manual + screenshot diff for now; pytest-qt harness flagged as follow-up |

---

## 8. Gates — RESOLVED 2026-05-26

User answered all three open questions:

1. **(Q1) — Restart-on-apply.** Settings slider writes preference + shows "Restart required" prompt. No live re-application.
2. **(Q2) — Manual screenshot diff for now.** Plan saves a pre-phase baseline screenshot under `docs/plans/responsive_ui_baselines/`. A `pytest-qt` perceptual-hash harness is filed as a non-blocking follow-up.
3. **(Q3) — Range [0.75, 1.50] confirmed, with 25% step quantisation** per Qt 6.11 official guidance: "Integer scale factors are preferred; 25% increments also give good results."

Phase 0 may begin on user go-ahead.

## 9. Standards verification (Qt 6.11 official docs, fetched 2026-05-26)

Verified against [doc.qt.io/qt-6/highdpi.html](https://doc.qt.io/qt-6/highdpi.html). Full citation appears in `RESPONSIVE_UI_SCALING_PLAN.md` §17. Key conclusions:

- **Qt 6 already handles platform-level DPI scaling automatically** on Windows ("Qt uses the Windows display scale settings automatically; no specific settings are required"). At `_scale_factor = 1.0` the app inherits correct rendering at any Windows scale.
- **`QT_SCALE_FACTOR` is unsuitable.** Qt docs label it "for debugging and testing purposes." It also scales globally (including VTK render windows), which violates the project's "never scale viewer hot paths" rule.
- **`QT_SCREEN_SCALE_FACTORS` is unsuitable.** Qt docs: "not recommended since it prevents Qt from using system DPI values."
- **Qt provides no end-user facility for in-app UI scale adjustment.** Quote: "Qt does not provide end-user facilities to configure the behavior of Qt's high-DPI support." This confirms our custom `sf()` helper is the standard pattern when an app needs an in-app user-controllable scale layered on top of Qt's automatic HiDPI.
- **25% step quantisation is officially recommended.** Slider values 0.75 / 1.00 / 1.25 / 1.50 match Qt's "preferred" granularity.
- **Performance overhead at default scale is zero.** `sf()` is identity-fast at 1.0 (one integer comparison + return). All call sites are `__init__`-time. No hot-path inclusion.

**Conclusion:** the `sf()` approach matches the only documented Qt pattern available for selective, user-controlled scaling. It is standard, not novel.

## 10. Bottom line — updated

Plan is approved and locked. All three gates resolved. Standards verified against Qt 6.11 official documentation. Implementation may begin Phase 0 on user go-ahead. Estimated end-to-end ~15 h with verification.

---

## 9. Bottom line

The original plan was conceptually solid but had two production-breaking bugs (write to non-writable dir; silent double-scale at startup) and one high-risk operational choice (single commit for the 6900-line toolbar file). All three are now corrected in the saved plan. With the per-tier gating on Phase 5, the explicit Qt 6 interaction notes in §14, and the multi-study regression-guard cross-reference, the plan is safe enough to move into Phase 0 once the three open questions in §16 are settled.

No regressions are expected at `_scale_factor = 1.0` if the per-commit identity gate is enforced. The risk profile of the implementation is **low** at default settings, **medium** at user-chosen non-default scales, and the worst-case failure mode is "the toolbar looks slightly off at 1.25×" — which is recoverable with a single `git revert` of the offending tier commit.
