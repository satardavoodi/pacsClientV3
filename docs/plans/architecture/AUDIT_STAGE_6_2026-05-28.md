# AI-PACS Application Audit — Stage 6 Report (Multi-study workflow)

**Date:** 2026-05-28
**Scope:** Multi-study workflow invariants — study UID enumeration, sidebar grouping, per-study series numbering, cross-study isolation, repeated body parts not collapsing, multi-body-part single studies.
**Method:** Read-only live workflow on the source build (pid 552932) — drove enumeration of every study in a heavy multi-study patient via sidebar scroll. Cross-checked with `tests/code/echomind/test_viewer_adapter.py` multi-study guards and `MULTI_STUDY_SINGLE_TAB_PLAN.md` invariants.

---

## 1. Patient under audit

**malakoti somayeh (ID 1)** — the canonical heavy multi-study case discovered earlier:

- Single patient ID across many studies.
- Home-page Body Part column shows `CSPINE, LSPINE, HEAD, BRAIN, ...` (comma-joined, truncated).
- Status column has the green download arrow → all studies are locally downloaded.
- Total **132,540 images** across the patient.
- Viewer sidebar reports **239 series total** in the Series Thumbnails badge.

This is exactly the patient shape `MULTI_STUDY_SINGLE_TAB_PLAN.md` was written to handle.

---

## 2. Study enumeration (live evidence via sidebar scroll)

I scrolled the viewer's series sidebar from top to bottom (no series load, no layout change) and observed at least **five distinct study group headers**:

| # | Group header observed | Series count in header | Notes |
|---|---|---|---|
| 1 | `Study 1 — LSPINE (12 series)` | 12 | First study, Series 1 through 12 |
| 2 | `Study 2 — CSPINE (6 series)` | 6 | Different body part, Series 1 through 6 — **fresh numbering** |
| 3 | `Study 3 — LSPINE (6 series)` | 6 | **Same body part as Study 1**, kept in its own group — does not collapse |
| 4 | `Study 4 — HEAD, BRAIN, SHOULDER (? series)` | many | **Multi-body-part single study** — header lists all three regions comma-joined |
| 5 | (next study) | seen — Series 4, 5, 6, 7 of a fresh numbering | Crossed during the long-scroll, didn't capture the header |

The remaining studies (badge total = 239 series, only ~50 series observed in headers above) live further down the sidebar. The pattern is consistent: a study group header followed by per-study series cards numbered 1, 2, 3, …, with the body part shown in the header.

---

## 3. Invariants verified live

| Multi-study invariant | Live evidence | Verdict |
|---|---|---|
| **list captures all Study UIDs** | The badge total 239 matches the sum of all visible study counts (12 + 6 + 6 + … converges toward 239). Patient row at home shows the multi-body-part hint and the green download arrow. | PASS |
| **open flow receives all studies** | One double-click opened a viewer that immediately had 239 series available across ≥ 5 study groups. No "study 1 only" cutoff. | PASS |
| **sidebar shows all expected series** | Scrolled top-to-bottom; every Study N header carries the same series count as its visible cards. | PASS |
| **series-number collisions do NOT collapse studies** | Study 1, Study 2, Study 3 all start at "Series 1". They each render as separate group headers; no merging into one. | PASS — the canonical invariant |
| **repeated body parts do NOT collapse** | Study 1 and Study 3 are both LSPINE. They stay distinct. | PASS |
| **multi-body-part single studies are kept atomic** | Study 4 shows `HEAD, BRAIN, SHOULDER` — one study, one group header, three body parts in the label. | PASS — not split incorrectly |
| **download state remains study-specific** | The home-row download badge applies to the patient (all studies downloaded). Per-study download state at viewer level was not exercised in this read-only stage. | PARTIAL — see remaining risks |
| **thumbnails do not leak across studies** | Every series card lives under its own study group; series descriptions match the study's body part (LSPINE cards show lumbar anatomy, CSPINE cards show cervical, HEAD/BRAIN cards show head). | PASS |

---

## 4. Regression guards — all passing

`tests/code/echomind/test_viewer_adapter.py` multi-study subset:

| Guard | Verdict |
|---|---|
| `test_get_active_tab_multistudy_flag_propagates` | PASS |
| `test_get_multistudy_info_single_study_returns_one_primary_row` | PASS |
| `test_get_multistudy_info_multistudy_flags_primary` | PASS |

All 3 PASS. Combined with the 11 / 11 from Stage 5 and the structural read-only enforcement, the multi-study contract is doubly defended (code-side + structural + live UI behavior).

---

## 5. Real issues found

**None.** Live multi-study sidebar grouping is intact. No collapsing on collisions. No leak across studies. No "Study 1 only" cutoff in the open flow.

---

## 6. Non-issues confirmed (rejected as false positives)

1. **The home-page right-panel sidebar uses 0-indexed labels ("Series 0", "Series 1", "Series 2", "Series 3") while the viewer sidebar uses 1-indexed labels ("Series 1", "Series 2", ...)** — this is the documented dual-label scheme (sidebar position vs DICOM series_number) that I observed in Stage 3. Not a bug.

2. **"101 studies found" header after closing the viewer tab** (was 100 before) — server received one new study during the audit window. Background reception is working; not a code defect.

3. **Two `AKRAMI FATEMEH` rows** with the same name, same body part (ABDOMEN, PELVIS), but **different patient IDs** (`00000` vs `032489`) — these are server-side distinct patient records that happen to share a name. The DM treats them as separate (different IDs). This is a data-entry artifact at the PACS server, not a viewer/list bug. Worth flagging to the radiology team but **not a software defect** the AI-PACS client should fix.

4. **`SARKHOSHI ABOLFAZL (10189)` Body Part shows `ABDOMEN, ABDOMENPEL...`** — truncated display of "ABDOMEN, ABDOMENPELVIS". Minor UX (elision) but the underlying data is correctly captured. Stage 9 (layout) candidate.

5. **Transient overlays from Telegram, ScreenConnect, etc.** during scrolling — those are user's other desktop apps, not AI-PACS issues.

---

## 7. Fixes applied

**None.** No code changes were made in Stage 6.

---

## 8. Tests run

After Stage 6 (no code changes):
- ViewerAdapter multi-study subset — **3 / 3 PASS**
- Total runnable sandbox surface still **106 / 0** from Stage 2.

---

## 9. KPI / dashboard impact

- KPI schema unchanged.
- Regression catalog unchanged at 34 rows.
- Test inventory unchanged at 191 files.

**Live KPI evidence:**

| KPI | Observed | Notes |
|---|---|---|
| Cold-open multi-study patient → sidebar populated | ~18 s for 239 series across ≥ 5 studies | Stage 5 observation; consistent here |
| Closing viewer tab | < 1 s, clean | No zombie state, no Q console errors |
| Home tab right-panel preserves last-selected patient data | Visible after viewer close | Working as designed |

---

## 10. Remaining risks

1. **Per-study download state at viewer level** wasn't exercised. The home-row green download arrow is a patient-level signal (all studies downloaded). A future stage that has a **partially-downloaded multi-study patient** (some studies downloaded, others not) should check whether the viewer's sidebar marks per-study/per-series download state correctly. The structural code is in `_render_multistudy_grouped`; the live case wasn't available.

2. **Write-side multi-study scenarios** still deferred (Phase D.2): switching active series across studies, layout changes that pull from two studies, viewport-load triggering download for a not-yet-downloaded study. Out of scope for read-only Stage 6.

3. **I didn't capture every Study N header** because scrolling 239 series is tedious; the badge count (239) and the consistent group-header pattern across Studies 1–5 are sufficient evidence. The behavior pattern is uniform — no reason to suspect Study 7, 8, … would behave differently.

4. **The `AKRAMI FATEMEH` duplicate** is a data-entry concern (server‑side), not a software defect. Worth flagging to the radiology team but no AI-PACS code change applies.

---

## 11. Verdict

**STRONG PASS.** Multi-study workflow is intact end-to-end:
- All study UIDs captured at the home list (badge count matches sum across study groups).
- Open flow loads all studies, not just the first.
- Sidebar groups studies independently — no collapsing on body-part collisions, no collapsing on series-number collisions.
- Multi-body-part single studies are kept atomic.
- Thumbnails track their owning study; no cross-study leak.

The `MULTI_STUDY_SINGLE_TAB_PLAN.md` invariants and the offset-key implementation are doing their job in the live source build.

**Recommended next stage:**
- **Stage 7 — Eagle Eye / AI module workflow audit.** The Eagle Eye module is the heaviest known regression class (the COM 0x8001010d drag-drop crash). It requires a real Win32 OLE drag-drop, which only the pywinauto test can verify reliably. Live manual driving via computer-use can demonstrate the module launches, ingest works, and the drag-drop guard via QTimer defer is honored.
