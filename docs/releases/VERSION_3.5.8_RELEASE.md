# AI-PACS v3.5.8 — Release Record

**Version:** 3.5.8
**Release date:** 2026-08-04
**Previous stable:** v3.5.7 (2026-08-02)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor — redesigned UI merged into stable, bidirectional reference lines, multi-frame geometry, local-list O(N) render

---

## 1. Headline

The **redesigned interface is now on the stable line.** The `satar-ui` UI work —
reviewed, blocker-fixed, and integrated — is merged on top of v3.5.7. v3.5.7 is not
lost: it is a parent of the merge commit and every one of its fixes is in history.

On top of that merge sit several substantial viewer and performance fixes that
landed since v3.5.7: **bidirectional reference lines**, **Siemens multi-frame
geometry** from the vendor CSA protocol, the **local patient list made linear**
(OPT-50), and a **form-field icon restyle**.

---

## 2. Redesigned UI (merged from satar-ui, reviewed + fixed)

The redesign was integrated through a review branch, not merged blind. The fixes
that gated it:

- **BLOCKER-1 — a server-profile switch must RESTART, not rebind at runtime.** Data
  paths are resolved once at startup; a live rebind left stale handles pointing at
  the old profile. Switching profiles now restarts the app.
- **BLOCKER-2 — the exit-confirmation dialog is gated.** It never prompts on a
  *programmatic* close (only a real user-initiated exit).
- **HIGH-3 / HIGH-7 — Port and Connection-Timeout fields are typeable again**, and
  the two red guard tests that covered them are repaired.
- **HIGH-6 / HIGH-8, M1 / M12** — single-authority add-server, identity refresh,
  drag surfaces, and Persian strings; plus a **UI performance pass**
  (`62e196e4`).
- **Config hygiene** — the colleague's local env config was dropped during
  integration; ours is preserved (servers `razi` 192.168.2.222 + `mehr`
  5.57.36.202, `active_profile_id: razi`, socket `192.168.2.222:50052`), and the
  consultation plugin mirror was re-synced.

Review record: `docs/reports/REVIEW_satar_ui_branch_2026-08-02.md`,
`INTEGRATION_satar_ui_branch_2026-08-02.md`.

---

## 3. Reference lines are bidirectional

**The bug.** A reference line was structurally single-source. The engine took one
source — the last-clicked viewport — computed its plane once, and drew it on the
others; there was no (source, target) pair loop. And selection is *click-only*
(wheel-scrolling never selects), so scrolling a non-selected sagittal view kept the
source pinned to the last-clicked (usually axial) viewport. So axial→sagittal/coronal
worked, but sagittal→others and coronal→others never appeared.

**The fix.** Every viewport is now **both a source and a target**. For each target
viewport the engine intersects its slice quad against every *other* viewport's plane
and accumulates the segments — so axial ↔ sagittal ↔ coronal all update when any of
them changes slice. New pure `PacsClient/utils/series_pairing.py`. The Qt path
already stored/painted N segments; the VTK path gained per-pair actor **slots** (slot
0 keeps the original single-line attributes byte-identical) so a pair that stops
intersecting can't leave a stale line. Default-on
(`AIPACS_REFERENCE_LINES_ALL_PAIRS`).

---

## 4. Siemens multi-frame geometry from the CSA protocol

The v3.5.5 multi-frame reader reads per-frame geometry from the DICOM functional
groups. A **Siemens "syngo" multi-frame Secondary Capture** (one file, N frames)
stores a real 2-D slice stack, but its geometry lives in the **top-level tags plus
the private CSA protocol**, with *no* functional groups — so the reader classified it
geometry-less and stamped every frame with the frame-0 position, and reference lines
couldn't tell the frames apart.

The fix parses the Siemens CSA ASCCONV protocol
(`sSliceArray.asSlice[i].sPosition.d{Sag,Cor,Tra}`) for the true per-slice positions
and anchors the displacements on the file's own top-level IPP. This is the vendor
protocol, **not a guess** — a uniform-step heuristic was measured wrong on this
scanner (a coronal stack landed ~160 mm off) and is disabled by default. A protocol
that does not enumerate the frames (a 3-plane scout/localizer, an MPR reformat, a
multi-b-value DWI, or a 3D slab) is **refused** rather than guessed, so those series
simply show no reference line. Default-on; MPR stays gated so a degenerate volume is
never built. Review: `docs/reports/MULTIFRAME_DICOM_HANDLING_REVIEW_2026-07-24.md`
(extended).

Also: scrolling large / multi-frame series is smoother — the per-instance
window/level resolver (which re-read the DICOM header on every wheel tick) is
memoised, and a multi-frame file's decoded dataset is cached rather than re-decoded
per frame.

---

## 5. Local patient list is O(N), not O(N²) (OPT-50)

The local list became unusable past ~2000 studies (v3.5.6's OPT-43 fixed only the
first paint; the background streamer still paid the whole bill). Four per-row costs
were quadratic or per-row I/O:

- the per-study dedup scanned the entire table (≈2M item lookups at 2000 rows), and
  so did the report-status lookup — now gated by a presence **set** + a render-pass
  memo;
- `check_patient_visited` and the imported-on resolver each opened a **DB connection
  per row** (4000 connections) — now one prefetch query each, primed into the
  widget;
- `_finalize_bulk_insert_ui` ran whole-table anti-alias + re-sort + count **every
  batch** while streaming — now incremental over the new row range with one debounced
  settle-sort;
- three JSON assignment/report stores were re-opened **three times per row** — now
  mtime+size-guarded read caches.

Result at 2000 studies: full load **42.7 s → 13.9 s**, worst GUI block **1139 → 271
ms**, first paint **285 → 114 ms**, SQLite round-trips **4000 → 1**. What remains is
linear widget construction; going materially faster would need DB-side paging or a
model/delegate rewrite, deliberately not done. Report:
`docs/reports/LOCAL_PATIENT_LIST_RENDER_OPT50_2026-08-03.md`.

---

## 6. UI polish & build

- **Form-field trailing icon buttons** restyled from a never-flush "rail" (that
  floated inside its shell and never lined up) to a clean rounded **chip**. This is
  one change in `PacsClient/utils/login_form_styles.py` that deliberately covers
  Home **and** login **and** settings — they all build these buttons through the
  same two helpers, so the change is never local. `AIPACS_FIELD_ICON_CHIP=0`
  restores the rail.
- **ARM64 Nuitka restore patch** — `builder/docs/ARM64_RESTORE_nuitka_2026-08-02.patch`,
  toward restoring the dual-arch (PyInstaller + Nuitka) build that regressed.

---

## 7. Verification status

Offscreen (test lane): guard suites for the redesigned-UI fixes (server-profile
restart, gated exit-confirm, typeable Port/Timeout), bidirectional reference lines,
multi-frame CSA geometry, the OPT-50 render path, and the field-icon chip live under
`tests/code/`.

**Still required — live source-build verification** (this release merges a large UI
change and warrants a full clinical-lane pass):

1. **Redesigned UI:** Home / login / settings render correctly; a server-profile
   switch restarts the app; Port and Timeout are typeable; a programmatic close does
   not prompt.
2. **Reference lines:** three orthogonal series in three viewports — scroll each in
   turn; the other two lines track every time.
3. **Multi-frame:** open a Siemens multi-frame series → reference lines track in all
   three planes; a scout/reformat shows none (not a wrong one).
4. **Local list:** open a large local archive (≥2000 studies) → the list is
   responsive.

---

## 8. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.8` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
