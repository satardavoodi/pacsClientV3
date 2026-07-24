# AI-PACS v3.5.5 — Release Record

**Version:** 3.5.5
**Release date:** 2026-07-25
**Previous stable:** v3.5.4 (2026-07-19)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor — multi-frame DICOM geometry, Offline Service delete, Report-Editor previous exams, viewport-load fixes

---

## 1. Headline

Several areas move at once, but the one with the widest clinical reach is
**multi-frame DICOM geometry**. Single-file cine and enhanced MR/CT series were
being read as if their geometry lived in top-level tags — it doesn't; it lives in
the per-frame functional groups. This release reads it from the right place, so
measurements, overlays, and reference lines are correct on those series for the
first time.

Around that: the Offline Service becomes manageable (you can delete patients from a
package, recoverably), the Report Editor learns to surface a patient's prior exams
across different Patient IDs, and a cluster of viewport-load reliability fixes land
together with a large download-client cleanup.

---

## 2. Multi-frame DICOM handling + geometry (OPT-42)

**The problem.** A single DICOM file with `NumberOfFrames > 1` (ultrasound cine,
XA, cardiac cine, enhanced CT/MR) carries its spatial geometry in the
`PerFrameFunctionalGroupsSequence` — a different Image Position / Orientation /
spacing *per frame* — not in the top-level `ImagePositionPatient` etc. The FAST
pipeline expanded such a file into N frames but gave every frame the file's
top-level (frame-0) geometry, so any per-frame measurement, overlay, or reference
line on an enhanced series was wrong.

**The fix.** A new pure `modules/viewer/fast/multiframe_geometry.py` reads per-frame
IPP / IOP / spacing from the functional groups and **classifies** the file:

- *spatial volume* (frames are stacked in space),
- *multi-dimensional* / *multi-stack* (e.g. multi-b-value diffusion),
- *temporal cine* (frames share geometry, differ in time).

The frame expansion now stamps each `SliceMeta` with its own geometry. A temporal
cine correctly shares frame-0 geometry (right for a scrollable time series); a
spatial multi-frame gets its true per-frame positions. MPR is **gated** so a
degenerate multi-frame volume cannot be built until the spatial VTK volume builder
lands.

**Untouched:** ordinary many-file single-frame series — they never enter the
multi-frame path, so the whole existing dataset renders byte-identically. Default-on
(`AIPACS_FAST_MULTIFRAME` + the geometry reader). The spatial VTK volume builder is
**staged, not built**. Review: `docs/reports/MULTIFRAME_DICOM_HANDLING_REVIEW_2026-07-24.md`.

**Status:** needs live verification on real cine / enhanced series.

---

## 3. Previous-exam mid-download grow, no layout switch (OPT-39)

A cross-PatientID previous exam (offset display key) dragged into the viewport
*while its study was still downloading* would paint its first image and then stick
there — the remaining images only appeared after the user changed viewport layout
(which forced a fresh read of the now-complete folder).

The grow watchdog (A1) that rebuilds a behind viewport from disk was only armed from
the awaiting/spinner path, and it self-stopped as soon as nothing was awaiting. A
drop that showed its first image cleared the awaiting flag, so a later stop-check
tick shut the watchdog down before the rest of the images arrived.

Both progressive-activation paths now arm the watchdog when the series is
known-incomplete, so A1 is guaranteed to sweep a progressively-loaded-but-behind
viewport regardless of await timing. It only ever rebuilds a *settled* folder, so it
never interferes with the live progressive grow. Default-on
(`AIPACS_PROGRESSIVE_ARMS_WATCHDOG`).

**Note:** the field build that reported this predated OPT-35/36, so that laptop also
needs updating.

---

## 4. Manual "Download" no longer skips the newest study (OPT-40)

The main-page **Download** button and the patient-open path used two different study
discovery pipelines. `GetPatientList` returns only the latest study UID per patient,
and the Download button used exactly that single UID from the row — ignoring the
row's full study set — and never reset a stale `COMPLETED` marker. So on a
multi-study patient a just-arrived study could be silently skipped, while opening the
same patient (which reconciles the full set) fetched it.

Download now routes through the same shared patient-study-set authority the open path
uses, so the two agree. Default-on.

---

## 5. Startup prewarm idle-gate hardened (OPT-41)

The web-browser Chromium prewarm (a ~17 s warm boot, deferred to idle) could still
land during the user's very first patient clicks, because the idle gate could fire
before any interaction had happened. The gate now requires a genuine pause *between*
two interactions, plus a longer untouched grace window, before it warms — so the
warm boot never competes with the first clicks after startup. Kept default-on with
the `=0` kill switch. Bench: `tools/dev/bench_webengine_boot.py`.

---

## 6. Offline Service — patient management (delete)

The Offline Service ("Offline Sync") was export-only. It now supports **deleting
patients** from an existing package, via a new `OfflineCloudManagerDialog`.

The delete contract is **recoverable and atomic**: snapshot `package.db` +
`manifest.json` and *move* (not unlink) the removed study folders into a timestamped
`.trash/` first; delete the DB rows; prune orphan patient rows; rebuild the DICOMDIR
(an empty package is valid, not a failure) and the manifest; validate; and if
validation fails, **roll back** from the snapshot. UIDs are never regenerated. All
mutation delegates to the engine primitives in `PacsClient/utils/offline_cloud.py` —
no sqlite / DICOMDIR / shutil logic in the dialog. Reconcile (P2) and edit (P3) are
staged. Review: `docs/plans/architecture/OFFLINE_SERVICE_MANAGEMENT_REVIEW_2026-07-21.md`.

---

## 7. Report Editor — "Previous Exams" header

The report editor gained a hidden-until-found "Previous Exams" indicator. On open it
looks up the patient's cross-PatientID reception history **off the GUI thread**; if
the patient has older Patient IDs it reveals a count and a dropdown of those prior
IDs. Selecting one shows that record's reports **read-only** — rendered on a
fixed white, bidi-correct canvas — and the active report is never mutated (a guard
test enforces that none of the previous-exam paths touch the active report). Reuses
the reception-server history path and the pure `previous_exams` / `report_history`
helpers. New `report_history.py`; `previous_exams.py`, `reception_reports_viewer.py`,
`report_editor_dialog.py` extended.

---

## 8. Engineering

- **First test-suite KPI baseline** — `tests/_kpi/kpi_baseline_2026-07-23.json`,
  with a test-suite-health report and a threading/subprocess architecture review.
- **Download-client cleanup (−670 lines)** in `socket_client.py` (and its plugin
  mirror), behaviour-preserving.
- **Security:** `config_sanitizer` now also blanks `channel_key.json` (the
  workstation's e2e channel keypair) at build — complements the v3.5.4 gitignore of
  the whole `config/agent_gateway/` runtime dir.

---

## 9. Verification status

Offscreen (test lane): new guard suites for multi-frame geometry, previous-exam
offset-key grow, manual-download discovery, resync-grows-on-server, offline-cloud
manage, report-editor previous-exams, and the prewarm idle gate all live under
`tests/code/`.

**Still required — live source-build verification** (cannot be done from the test
lane):

1. **Multi-frame:** open a real cine ultrasound and an enhanced MR/CT — frames
   display, and per-frame measurements / overlays / reference lines are correct.
2. **OPT-39:** drag a previous exam mid-download → it grows to all images with no
   layout switch.
3. **OPT-40:** manual Download on a multi-study patient fetches every study.
4. **Offline delete:** delete a patient from a package → recoverable, package still
   validates.
5. **Report Editor:** open a report for a patient with prior receptions under other
   IDs → the indicator appears and its reports show read-only.

---

## 10. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.5` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
