# AI-PACS v3.5.2 — Release Record

**Version:** 3.5.2
**Release date:** 2026-07-14
**Previous stable:** v3.5.1 (2026-07-13)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Patch — viewport load reliability, Eagle Eye Mammography 3D Cursor, DICOM VM-collapse diagnosis

---

## 1. Headline

This release is about **the viewport actually showing what you dragged.**

Two independent defects were making a dragged series silently fail to appear, and
both are fixed default-on. The common thread — and the reason they took so long to
find — is that in each case *the machinery everyone suspected was already correct*.
The spinner logic was fine; the refresh pipeline was fine. What was wrong was a
**stop condition**: a piece of code that decided "we're done here" when it had no
right to.

Alongside that, Eagle Eye gains a full **Mammography 3D Cursor**, and we finally
have the root cause of the exported-DICOM black-image problem in the third-party RT
planning system.

---

## 2. OPT-36 — a drop is never abandoned back to the previous image

**Symptom.** Drag a series while its study is still downloading; instead of waiting,
the viewport quietly reverts to the previously-displayed image. Only a manual
re-drag recovers it.

**What was NOT wrong.** The awaiting/spinner machinery. It correctly entered the
loading state and correctly waited. This was not a download bug either — the data
arrived.

**What was actually wrong.** The *resume watchdog* abandoned the drop, via two
compounding bugs:

- **The settle stop-condition bypassed the "is it actually displayed?" check.** The
  watchdog could declare a viewport settled — hide the spinner, clear the awaiting
  flag, and log a **`ViewportLoadSucceeded`** — while the viewport was *not showing
  the awaited series at all*. The state authority's `is_settled` is a high-water
  mark of *displayed slice count*; it is a livelock brake and says nothing about
  **which** series is on screen. It was being used as proof of success.
- **The completeness check never saw in-flight writes.** The download manager writes
  `<name>.part` then renames to `.dcm`. The call site computed that a `.part` file
  existed but **never passed it** to the completeness check. For a previous exam
  (not yet in the DB, so no expected image count), the weak stable-count fallback
  then declared a series that had written exactly **1 of N** files "complete".

**The rule now enforced:** *a viewport may only be declared settled when it is
actually showing the awaited series*, and *a stop-condition must never double as
"the load succeeded"*. The retry budget is additionally refunded whenever the
on-disk count grows, so the attempt cap only trips on a genuinely stuck download —
and on true exhaustion the viewport shows an explicit "still loading" state and
**keeps** the awaiting flag. It never silently reverts.

Flags: `AIPACS_SETTLE_REQUIRES_DISPLAYED`, `AIPACS_RESUME_BUDGET_ON_PROGRESS`
(default on; `=0` = legacy).
Guard: `tests/code/viewer/test_drop_never_abandoned_to_previous_image.py` (19).

---

## 3. OPT-37 — thumbnails refresh when the server gains images

**Symptom.** Clicked a study showing 3 series. Five minutes later the remaining 24
series / 1148 images had arrived on the server, but the thumbnails never updated —
until the patient-code filter was cleared and the list switched to "Yesterday".

**What was NOT wrong.** The refresh machinery. The auto-resync already re-renders
with a forced server merge when it detects growth.

**What was actually wrong.** A **flat 5-minute per-study throttle on the change
detector** — applied to *every* study, including one the previous check had *just
found incomplete*. That is precisely the study that will change, and five minutes is
precisely the window in which it changes. So every click for five minutes returned
"nothing changed" in 0.2 ms without contacting the server at all.

The TTL is now completeness-aware: the full 5 minutes once a study is *confirmed
complete* (which preserves the "not every click hits the network" contract), and a
short TTL while it is still growing.

**Known residual, documented not fixed:** a patient-code search and a date-filtered
list route the same click down **two different render paths**, and only one of them
has a staleness check. That is why changing the filter "fixed" it — not cache
invalidation, a different code path. The grouped path still depends entirely on the
resync firing.

Flags: `AIPACS_RESYNC_TTL_INCOMPLETE`, `AIPACS_RESYNC_TTL_INCOMPLETE_S` (default on).
Guard: `tests/code/ui_services/test_resync_ttl_incomplete_study.py` (19).

---

## 4. Eagle Eye — Mammography 3D Cursor

Merged selectively from upstream (`1c01b3e4`, `50179c9c`) — **mammography only**, 23
files, all under `modules/ai_imaging/` and `tests/code/ai_imaging/`.

- 13 new `cursor_3d` modules: anchor nipple / validation / interaction, pectoral
  picker + pectoral line anchor & interaction, arc probability, arc renderer,
  `correlator_v2`, Hungarian matching, distance computation, quadrant consistency,
  coord utils.
- Workflow gains a **pectoral-line picking step** after nipple picking, and an **arc
  probability heatmap** on the target view.
- `_clear_3d_cursor_actors()` — arc / nipple / pectoral actors are cleared on series
  switch, so they no longer persist across studies.
- Bone Age is untouched (54 references before, 54 after).

**Deliberately excluded from the upstream commit:** an 8,241-line stale MPR resource
file (`NewMPR2SlicerApp/Resources/App_rc.py`), the collaborator's test-environment
`config/*.json`, and a `socket_patient_service.py` change that would have touched the
OPT-24c connection-pool work.

**Known limitation:** `scipy` is not a project dependency. The imports in
`hungarian_matching.py` and `arc_probability.py` are guarded, so nothing fails — but
lesion matching currently runs on a **greedy, non-optimal** fallback rather than the
real Hungarian solver. Promoting it means adding `scipy` to `requirements.txt` *and*
to the PyInstaller/Nuitka spec; deferred as an explicit decision.

---

## 5. DICOM multi-valued-element collapse (ImageType) — root cause

Exported studies rendered as **black images** in a strict third-party RT planning
system, while our viewer and Limbus displayed them correctly.

**Root cause: the server collapses multi-valued string elements into a Python list
*repr*.** Every downloaded/exported DICOM carries:

```
ImageType = "['ORIGINAL', 'PRIMARY', 'AXIAL']"
```

`ImageType` is Type 1 (required) with VR `CS`, whose character repertoire does not
permit `[`, `]`, `'`, or `,`. Tolerant parsers shrug; a strict one rejects the image.

This is a **server-side defect, not an export-code defect** — which matters, because
it means the three `_sanitize_specific_character_set` band-aids already in the
codebase are all treating the same underlying bug. Ships as a diagnosis report plus
a repair tool (`tools/diagnostics/repair_dicom_vm_collapse.py`) for already-exported
studies.

---

## 6. Also included

- Reception / INO: assignment details, assignment status model, error reporting,
  shared HTTP session layer (`modules/network/http_session.py`).
- Eagle Eye: guided picker / guided workflow / view identity, dataset identity and
  grouping.
- Test suite additions across viewer, network, UI services, and `ai_imaging`.

---

## 7. Verification status

| Check | Result |
|---|---|
| `tests/code/ai_imaging` | 61 passed |
| Mammography 3D Cursor anchor/nipple suite | 43 passed |
| `cursor_3d` + shared files compile | clean |
| Bone Age references preserved | 54 → 54 |
| MPR / config / network files touched by the merge | none |

**Still required — live source-build verification** (cannot be done from the test
lane):

1. **OPT-36:** drag a previous-exam series the instant its study starts downloading.
   The loading indicator must persist until the images appear, with **no**
   intermediate revert to the previous image.
2. **OPT-37:** open a study that is still growing on the server; thumbnails must
   refresh as new series land, without changing the list filter.
3. **3D Cursor:** pick nipples → draw pectoral lines → confirm the probability
   heatmap renders and actors clear on series switch.

---

## 8. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.2` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
