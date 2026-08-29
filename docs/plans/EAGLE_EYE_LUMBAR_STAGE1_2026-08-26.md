# Eagle Eye — Lumbar Spine MRI, Stage 1 (capture pipeline)

**Date:** 2026-08-26 · **Status:** built, unit-tested, **NOT yet verified on a live study**
**Scope:** image selection → synchronized 3×1 layout → screenshot sweeps → session storage.
**Explicitly out of scope:** any LLM call, upload, pathology detection or report generation.
Those are **stage 2** — see `EAGLE_EYE_LLM_STAGE2_2026-08-26.md`, which consumes
exactly the session this document produces and changes nothing in it.

---

## 1. What one click does

**Automatic when confident, interactive when not.** The entire pre-flight —
which study, which protocol, which series — happens *before* the Eagle Eye tab
is created. Nothing opens on a partial mapping, because a sweep run against a
half-filled layout produces a session that looks complete and is wrong.

```
AIChatInteractorStyle.check_status()            modality == MR
  └─ _open_lumbar_eagle_eye()
       └─ resolver.resolve(ResolveContext.for_widget(pw), QtPrompts(...))
            ├─ 1. studies loaded in this tab?   one → use it · several → ASK
            ├─ 2. probe the chosen study's DICOM headers (1 read per series)
            ├─ 3. detect_protocol()             high + implemented → use it
            │                                   known-but-unsupported → refuse
            │                                   uncertain → ASK
            ├─ 4. classify_for_protocol()       score every slot
            ├─ 5. for each UNCERTAIN slot only → ASK (confident slots untouched)
            └─ 6. validate: every slot filled, no series used twice
       └─ session_request.stash(study_uid, resolution)
            └─ switch_right_panel('ai_module')  →  Eagle Eye tab
                 └─ AIPatientWidget(eagle_eye_mode="lumbar_mri")   1×3, VTK
                      └─ ImagingToolsTab._finalize_loading()
                           └─ (+600 ms) _start_lumbar_capture_session()
                                ├─ session_request.take() → _apply_resolved_mapping()
                                └─ LumbarCaptureController.start()
```

A clearly-labelled lumbar study shows **zero dialogs** — verified live: patient
55837 resolves protocol + all three slots at high confidence with `prompts
shown: 0`.

Layout, always in this order:

```
┌──────────────────┬──────────────────┬──────────────────┐
│   Sagittal T2    │   Sagittal T1    │    Axial T2      │
└──────────────────┴──────────────────┴──────────────────┘
```

---

## 2. Where the code lives

| File | Role |
|---|---|
| `modules/ai_imaging/eagle_eye_lumbar/constants.py` | slot names, direction vocabulary, manifest filenames, pipeline version |
| `modules/ai_imaging/eagle_eye_lumbar/protocols.py` | **protocol definitions** (slots, layout) + the one body-part → region table |
| `modules/ai_imaging/eagle_eye_lumbar/study_catalog.py` | the studies loaded in a patient tab, with date/description/series count |
| `modules/ai_imaging/eagle_eye_lumbar/resolver.py` | study → protocol → series → validate, with prompts injected |
| `modules/ai_imaging/eagle_eye_lumbar/selection_dialogs.py` | the three Qt pickers (study / protocol / one uncertain slot) |
| `modules/ai_imaging/eagle_eye_lumbar/session_request.py` | one-shot hand-off of the validated mapping to the Eagle Eye tab |
| `modules/ai_imaging/eagle_eye_lumbar/geometry.py` | plane from IOP, capture ordering, T2↔T1 matching, spatial-context labels |
| `modules/ai_imaging/eagle_eye_lumbar/series_classifier.py` | scores series into the three slots, with confidence + reasons + alternatives |
| `modules/ai_imaging/eagle_eye_lumbar/series_probe.py` | builds classifier candidates from headers on disk + loaded thumbnails |
| `modules/ai_imaging/eagle_eye_lumbar/session_store.py` | session folder, `session.json`, per-pass `manifest.json`, validation |
| `modules/ai_imaging/eagle_eye_lumbar/lock_sync.py` | borrows the workstation's Lock Sync for the run: enable / restore / suspend |
| `modules/ai_imaging/eagle_eye_lumbar/reference_lines.py` | which viewports may carry a reference line during each session |
| `modules/ai_imaging/eagle_eye_lumbar/capture_controller.py` | the protocol-driven capture ENGINE (the only Qt-touching file) |
| `modules/ai_imaging/eagle_eye_modes.py` | **single authority** for modality → Eagle Eye mode |
| `tests/code/ai_imaging/test_eagle_eye_lumbar_pipeline.py` | geometry / classifier / session guards |
| `tests/code/ai_imaging/test_eagle_eye_protocol_resolution.py` | protocol detection + the resolver's branches |

Everything except `capture_controller.py`, `selection_dialogs.py` and the pydicom
half of `series_probe.py` is pure python and runs with no GUI.

---

## 2a. The pre-flight (protocol, study and series resolution)

**Protocols are data, not UI logic.** `Protocol` carries an id, a modality, the
regions it covers, its layout and its ordered `ProtocolSlot`s; each slot declares
its required plane, its required weighting and a plausible slice band. The
classifier reads all of that from the protocol — adding Cervical Spine MRI later
is a registry entry plus a sweep, not edits spread through the classifier, the
layout and the dialogs.

```
LumbarSpineMRIProtocol            layout (1, 3)
├── Sagittal T2   pos 1   sagittal / T2   8–30 slices
├── Sagittal T1   pos 2   sagittal / T1   8–30 slices
└── Axial T2      pos 3   axial    / T2   9–60 slices
```

`PROTOCOLS` also carries Cervical, Thoracic, Knee, Shoulder and Brain as
**declared but not implemented**. They appear in the picker (greyed, unselectable)
so the list reads as a roadmap rather than a dead end.

**Three decisions, three rules:**

| Step | Automatic when | Otherwise |
|---|---|---|
| Study | exactly one study is loaded in the tab | picker with description · date · series count, current study pre-selected |
| Protocol | `BodyPartExamined` maps to a region **and** that protocol is implemented | picker — *unless* the region is confidently known and unsupported, which is refused outright |
| Series | every slot scores `high`/`medium` | picker for **only** the uncertain slots |

The middle row is the subtle one. A brain MR is detected with *high* confidence
and still cannot be swept. Offering a protocol picker there would invite choosing
"Lumbar Spine MRI" on a brain study — and a brain study really does contain a
sagittal T2, a sagittal T1 and an axial T2, so every slot would fill and every
captured frame would be brain anatomy inside a lumbar session. **Uncertainty is a
reason to ask; lack of support is not.**

The per-slot picker offers only series that passed that slot's hard gates. A
coronal series or a localizer must not be assignable by hand either — that is
what the gates exist to prevent — so a slot with no viable candidate is reported
as impossible rather than opened up to anything.

**Validation before anything opens:** every slot filled, and no series used for
two slots. Failing either, the layout does not open and the reason names the slot.

**Hand-off.** The mapping travels as `SeriesInstanceUID` (series number as
fallback), never as a thumbnail index — the Eagle Eye tab is a different widget
with its own thumbnail list. `session_request` parks it under the study UID;
`take()` removes it, so a resolution is consumed exactly once and a stale one
expires after 180 s. The tab re-probes, re-applies the mapping, and refuses if
any slot's series is not in its own thumbnail list.

Because the chosen study need not be the tab's primary one, the button also sets
`_preferred_eagle_eye_study_uid`, which `_pw_panels` passes to the new tab.

### 2a-i. "Eagle Eye could not load" — waiting is not the same as refusing

First live run of the 1×3 layout (patient 55991): the three panes built, and all
three slots reported *could not load*. The mapping was correct; the **series were
simply not decoded yet**.

`lst_thumbnails_data` holds only series that have actually been loaded. The tab
runs its pipeline asynchronously, and the sweep fires ~900 ms after the tab is
created — long before six MR series have been decoded — so every slot's
`thumbnail_index` was `-1`. Refusing there mistook *not ready* for *not present*.

The tab now **waits** (`_await_required_series`, 300 ms poll, 90 s budget),
re-resolving each slot's index each tick and starting the sweep the moment all
three are bound. If they have still not appeared after 8 s it calls
`load_series_on_demand` once per series as a recovery nudge — deliberately not
first, because that function is really a download-*completed* handler that
signals the pipeline orchestrator, and firing it for a local series would
perturb state that is mid-flight.

The refusal survives as the *timeout* outcome, so "never capture a layout with
empty or stale viewports" still holds — it just no longer fires on a study that
is merely still loading.

### Touched existing files

- `modules/viewer/interactor_styles/ai_chat_interactorstyle.py` — MR branch in
  `check_status`; `_open_lumbar_eagle_eye` now runs the whole resolver and stashes
  the result. **Plugin-mirrored** — `tools/dev/sync_plugin_mirrors.py` was run;
  456/456 pairs match.
- `modules/ai_imaging/ai_module_ui/overrides/patient_widget.py` — 1×3 layout, three named
  panes, reference lines ON for lumbar, MG mirror suppressed.
- `modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py` — no "Show/Hide Boxes" button
  in lumbar panes (it would be baked into every screenshot).
- `modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py` — `MR` modality, auto-run,
  progress/finished/failed handling.
- `modules/ai_imaging/ai_module_ui/ai_mainwindow.py` — normalizer delegates to the authority.
- `PacsClient/.../patient_widget_core/_pw_panels.py` — sidebar route uses `resolve_eagle_eye_mode`.
- `PacsClient/.../patient_toolbar/toolbar_manager.py` — warning text mentions lumbar MR.

---

## 2b. The region gate — corrected 2026-08-26 after a live miss

The first build gated on free text taken from the GUI's in-memory metadata, and
**a real Siemens lumbar study was refused**. What that study actually carried:

| Field | Value |
|---|---|
| `studies.study_description` (local DB) | `''` — empty |
| `series.body_part_examined` (local DB) | `NULL` on every series |
| `SeriesDescription` | `t2_tse_sag`, `t1_tse_sag`, `t2_tse_tra_msma` |
| `StudyDescription` (on disk) | `SPIN^L_S __KK` |
| **`BodyPartExamined` (on disk)** | **`LSPINE`** — the only region signal anywhere |

Two lessons, both now enforced by guards:

1. **Free text can never be the gate.** None of those series names contain
   "lumbar", and `looks_like_lumbar()` on them is correctly `False`. The coded
   DICOM `BodyPartExamined` is the authority; descriptions are the fallback.
2. **Read the headers, not the GUI.** The local DB had lost both the study
   description and the series body parts. The disk had them on every instance.
   The gate now runs the same `probe_study_series()` the classifier uses, so the
   button and the pipeline can never disagree about what the study is.

`lumbar_verdict(body_parts, texts)` returns `lumbar` / `other` / `unknown` plus a
reason string:

- **lumbar** → open the layout and sweep, no prompt (this is the automatic path).
- **other** → refuse, naming the region (`"BodyPartExamined says BRAIN/HEAD"`).
- **unknown** → ask once: *"This MR study does not say which body region it
  covers. Open the lumbar spine layout anyway?"* Refusing outright would strand
  every unlabelled study; opening silently would fill the layout from a brain or
  knee MR. The uncertainty goes to the person who can see the images.

The button also logs one line per series (`desc`, `body_part`, `plane`, `slices`,
`TE`, `TR`) so a future miss is one log line from being explained.

**Verified against the live library:**

| Study | Verdict |
|---|---|
| Lumbar (patient 55837) | `lumbar` — BodyPartExamined says LSPINE |
| Abdomen MRCP | `other` — ABDOMEN/ABDOMENPELVIS |
| Brain | `other` — BRAIN/HEAD |
| Breast | `other` — BREAST |
| Prostate | `other` — PROSTATE |

On that lumbar study the classifier then resolved all three slots at **high**
confidence: `t2_tse_sag` (79.0), `t1_tse_sag` (79.0), `t2_tse_tra_msma` (73.0),
each from TE/TR rather than the description.

**A second defect fell out of the same investigation:** `Path.glob` is
case-insensitive on Windows, so globbing `*.dcm` and `*.DCM` returned every file
twice — an 11-slice sagittal was probed as 22 slices, a 26-slice axial as 52.
Slice count feeds the classifier's plausibility scoring, so this was a real bug,
not cosmetic. `_dicom_files()` now de-duplicates by path.

---

## 3. Series detection (spec §2, §16)

`series_probe` reads **one `stop_before_pixels` header per series folder** — cheap, and it
does not require the series to be loaded into a viewport. Series already loaded contribute
their real instance list on top.

`series_classifier` then, per slot:

**Hard gates** (cannot be traded off): modality ≠ MR · wrong acquisition plane · fewer than
3 slices · localizer / scout / DWI / ADC / myelo / MIP / reformat / field-map / phase ·
`ImageType` DERIVED/SECONDARY/LOCALIZER/PROJECTION · already assigned to an earlier slot.

**Scoring**: weighting match dominates (+55 from TE/TR, +40 from text), wrong weighting −45.
Then plane wording +6, lumbar naming +8, fat-sat −12, post-contrast −18, plausible slice
count ±10/−6, missing IPP/IOP −20.

**Weighting** is resolved from acquisition parameters first and description second, because a
mislabelled protocol is common and a misreported `EchoTime` is not:

| Evidence | Verdict |
|---|---|
| `TI` 80–250 ms | STIR |
| `TE ≥ 70` | T2 |
| `TE ≤ 30` and `TR ≥ 1800` | PD |
| `TE ≤ 30` and (`TR` absent or `≤ 900`) | T1 |
| otherwise | fall through to text, else `unknown` |

Timings **override** text; the disagreement is recorded (`source: timings_over_text`).

**Confidence**: `high` (score ≥ 70 and margin ≥ 15) · `medium` (≥ 50 / ≥ 5) · `low` (≥ 25) ·
`none`. A slot in the `none` band is left **unresolved** — the run stops with
"Eagle Eye could not identify: …" rather than picking an arbitrary series. Every runner-up
and every rejection reason is written into `session.json`, which is what a future tuning
pass will read.

Assignment order is Sag T2 → Sag T1 → Ax T2, because the two sagittal slots compete for one
pool and Sag T2 is the anchor that drives the whole sweep.

---

## 4. Ordering (spec §14) and matching (spec §15)

`metadata['instances']` is **never re-sorted** — re-sorting it by IPP breaks the
reference-line engine (a standing rule of this codebase). The anatomical order lives as an
index permutation in `CaptureOrder`, and the direction actually used is written into the
manifest:

- sagittal → `right_to_left` (ascending LPS **x**, since +x is patient left)
- axial → `superior_to_inferior` (descending LPS **z**)
- no usable IPP → stack order with direction `unknown` **and a note saying so**

`InstanceNumber == 1` is never assumed to be the right side; a guard feeds the same stack in
reversed order and asserts the sweep visits the same anatomy in the same sequence.

Sag T2 ↔ Sag T1 matching goes through
`modules/viewer/fast/dicom_sync_geometry.find_closest_slice_physical` — the geometry
authority both viewer backends already use (`_pw_sync` imports it for the Advanced path
too). It is correct for different slice counts, different spacing and sparse
disc-by-disc stacks. A match further than **12 mm** is still displayed (it is the nearest
slice) but recorded as `matched: false`.

---

## 4a. Binding a series to a pane — corrected 2026-08-26 after a live miss

**Report:** "still not correct and with too much delay". Pane 1 empty, pane 2 showing the
localizer, pane 3 showing `t2_haste_COR_myelo_512`, status stuck on *"Waiting for 3 series
to finish loading"*, then `app.log`:

```
eagle_eye: protocol detection -> lumbar_mri (high): BodyPartExamined says LSPINE
Sagittal T2 -> t2_tse_sag (score=79.0, high)
Sagittal T1 -> t1_tse_sag (score=79.0, high)
Axial T2   -> t2_tse_tra_msma (score=79.0, high)
...
eagle_eye_lumbar: timed out waiting for sagittal_t2, sagittal_t1, axial_t2 to load
```

So the resolution was right and the *binding* was wrong. Two causes, both in how
`change_series_on_viewer` was being called:

1. **`series_index` is a series KEY, not a list index.** `_vc_switch.py:150` opens with
   `series_number = str(series_index)`, and everything downstream (canonical identity,
   previous-exam origin, download state) treats it as a key. Passing a position in
   `lst_thumbnails_data` asked for the series *numbered* "1" and "2" — the localizer and
   the coronal myelogram, exactly what the screenshot showed. `_series_key()` now resolves
   the candidate's SeriesInstanceUID through `patient_widget.resolve_series_key` and falls
   back to the header's series number.
2. **`flag_change_selected_widget=True` discards the target pane.** When true the method
   overwrites its own `vtk_widget` argument with `self.selected_widget`, so all three
   assignments would land in one pane. Every call site now passes `False`.

**The delay** was a second, separable mistake: the tab used to poll `lst_thumbnails_data`
until all three series appeared *before* assigning. That list holds LOADED series only, and
assignment is itself what triggers the decode — so the poll added seconds to every run and,
for a study whose other series had never been requested, waited out the whole 90 s budget on
series nobody had asked for. `_await_required_series` / `_lumbar_thumbnail_index` and their
constants are gone; `_start_lumbar_capture_session` calls `_launch_lumbar_controller`
directly. Readiness now lives where it belongs — the controller polls each *viewport* for
its wanted series plus a non-zero slice count, re-asserts a pane that drifted every ~1 s
(`_REASSERT_EVERY_TICKS`), and on timeout names what it wanted versus what the pane shows.

Guards: `test_the_tab_does_not_pre_wait_on_the_thumbnail_list`,
`test_the_controller_asks_by_series_key_never_by_list_position` (which also pins that no
call site may use `flag_change_selected_widget=True`), and
`test_the_controller_still_refuses_when_the_series_never_arrive`.

---

## 4a-ii. "1 sagittal + 8 axial frames" — readiness must mean the WHOLE series

**Report:** the panes showed Sag T2 at 5/9, Sag T1 at 9/9, Axial at 7/22, and the
status line read *"Eagle Eye session saved: 1 sagittal + 8 axial frames"*. The log
showed the whole run taking **4.7 seconds** and finishing `0 problem(s)`.

Both halves of that come from one defect. `_slot_ready` tested
`get_count_of_slices() > 0`. The tab decodes **progressively**, so a pane holding
one slice of nine passed readiness; `_prepare_geometry` then snapshotted the
instance list — one entry for Sag T2, eight for the axial — and
`build_capture_order` produced a queue of exactly that length. The sweep ran to
completion over its one sagittal frame, wrote the session, validated it, and
reported success. **Every frame in it was individually valid**, which is why
nothing downstream flagged it and why the manifests cross-checked clean.

The panes read 5/9 and 9/9 in the screenshot because the series kept decoding
*after* the sweep had already finished with them.

Three changes:

1. **Readiness compares against the count on disk.** `candidate.slice_count` is
   what the probe counted (`len(_dicom_files(folder))`, deduped for the Windows
   case-insensitive-glob trap) at resolution time, so it is the number the pane
   has to reach. `_slot_ready` now requires `decoded >= expected`. Unknown or
   multi-frame counts (one file, many frames) degrade to the old "any slice will
   do" — never to something stricter than the truth.
2. **A short capture order is refused, not swept.** `_prepare_geometry` re-checks
   the instance-list length against the same expected count *before* building the
   order, and fails with `"<slot> reports N of M images after loading finished;
   refusing to capture a partial series"`. A partial sweep is undetectable once
   written; it must never be written.
3. **A still-decoding pane is no longer re-asserted.** The periodic re-assert now
   fires only at a pane showing the *wrong series*. Re-issuing at a pane on the
   right series restarts the very load it is waiting on — which would pin a slow
   study at slice one for the whole budget.
4. **A stalled decode is refused in ten seconds, not ninety.** Demanding the full
   on-disk count introduces a new way to wait: a series whose file count and
   decodable slice count disagree would never satisfy it. `_decode_stalled`
   watches each pane's count and, once it has sat still for `_STALL_TIMEOUT_S`
   short of the total, fails with `"loading stopped short for …"`. Same verdict
   as the timeout, delivered while the reader is still watching. A pane at zero
   is *waiting to begin*, not stalled, and is excluded.

The timeout message now names progress (`"Sagittal T2 (4 of 9 images decoded)"`)
rather than a bare slot list; "timed out" alone is what sent the previous
debugging pass down the wrong path.

---

## 4b. Lock Sync — the workstation's, borrowed for the session

**Requirement:** during the sagittal pass the two sagittal stacks must scroll
*together*, using the Lock Sync the reader already has rather than a second
synchroniser grown inside Eagle Eye; ON while Eagle Eye runs, and the reader's
own setting back when it ends.

**⚠ "When it ends" means the LAYOUT closing, not the sweep finishing.** The first
build restored at the end of `_finish` — four seconds after enabling — so by the
time the reader looked at the screen Lock Sync was already off again, and
scrolling one sagittal moved nothing. A successful run now leaves it ON. That
changes nothing outside Eagle Eye: `ImagingToolsTab` constructs its **own**
`AIPatientWidget` (`imaging_tab.py:639`), so this is per-widget state that dies
with the tab and never reaches the reader's normal patient tab — which is what
"do not permanently change the user's normal workstation configuration" is
actually protecting. Only a **failed** run restores, in `_fail`, because a run
that died should not leave behind a setting nobody asked for.

`modules/ai_imaging/eagle_eye_lumbar/lock_sync.py` — `LockSyncSession` — owns
exactly three things and nothing else.

**1. Enable, by the same call sequence the toolbar uses.** Copied from
`ToolbarManager._toggle_lock_sync` deliberately, so the workstation and Eagle
Eye cannot drift apart:

```python
pw._sync_enabled = True
pw.sync_manager.set_mode(SyncMode.CURSOR)
pw._register_sync_viewers_pipeline_only()   # NOT _register_sync_viewers
pw.set_lock_sync(True)
```

`_register_sync_viewers_pipeline_only` is the point: it registers the viewers
with the sync manager **without** installing the click-to-target interactor
style or the red target cursor. The full registration would leave a red dot
baked into every screenshot and would fight the other tools.

Enabled in `_prepare_geometry`, not in `start()` — registration reads each
viewer's series UID, and at `start()` the three panes are still empty.

**Is the correspondence geometric?** Yes, and it was checked rather than
assumed. `_do_lock_sync` computes the source slice's true patient-LPS centre
from IPP/IOP for FAST viewers (explicitly *not* from the mock VTK spacing,
which is wrong for non-axial stacks), and `_map_sync_cursor`'s own comment
reads "PRIMARY: DICOM IOP/IPP mapping (same as reference_line.py)", with the
ITK direction matrix and fractional position only as fallbacks. So Sag T2 at
11 × 4 mm and Sag T1 at 15 × 3 mm land on the same anatomy. Matching slice
INDEX would pair the wrong images, and nothing downstream could detect it.

**2. Restore.** Saved at enable: `_lock_sync_enabled`, `_sync_enabled`,
`target_mode_enabled`. On restore, `set_lock_sync(previous)` runs FIRST — call
`toggle_sync_point(False)` while `_lock_sync_enabled` is still True and it takes
its keep-the-pipeline-alive branch, leaving sync half-running. The teardown
only happens when the reader had both off, mirroring the toolbar. Idempotent,
so a caller need not track whether it already ran. Called on the **failure**
path (in `_fail`, *before* anything that can itself throw) and available to a
caller tearing the layout down — not at the end of a successful sweep, per the
warning above.

**3. Suspend.** Two controller-driven moves must not propagate, and both use
`suspended()`, which holds `PatientWidget._lock_sync_updating` — **the engine's
own re-entrancy guard**, the flag `_auto_sync_on_slice_change` already checks.
Borrowing it is the difference between reusing Lock Sync and growing a second,
competing synchroniser.

- **Parking the sagittals** for the axial pass: without suspension, moving Sag
  T2 would drag the axial pane off the slice the pass is about to capture.
- **The axial pass itself**: every axial step is `_set_slice_quietly`, so the
  parked sagittals stay parked. Otherwise they would walk off mid-line frame by
  frame and the reference line — the only thing that is supposed to move —
  would be drawn on different anatomy in every screenshot.

**Lock Sync is the mechanism; DICOM geometry stays the verdict.** After the T2
slice is set, the followers are read rather than commanded, but they are still
*checked* against `match_slice_across_series`. `_map_sync_cursor` returns None
when the source point falls outside the target stack, and `_do_lock_sync` then
hides the sync overlay and leaves that pane where it was — trusting it blindly
would pair a T2 slice with a stale T1 one, invisible in the screenshot and fatal
to everything downstream. Agreement is recorded; disagreement is corrected in
place (quietly, so the correction cannot push the driver off its own slice).
Every sagittal frame carries `t1_followed_by` / `axial_followed_by`, one of
`lock_sync` · `lock_sync_corrected` · `controller`, so a manifest reader can
tell a correspondence from a correction without guessing. `session.json` carries
a `lock_sync` block with the previous state and `correspondence: dicom_ipp_iop`.

**One knock-on fixed at the same time.** Lock Sync ends every propagation with
`_schedule_reference_line_update()`, arming the 50 ms round-robin throttle. Left
running, its next tick would land inside the 130 ms settle window and repaint
ONE target — a pane half-updated at the moment of the grab. `_refresh_reference_lines`
now stands that pending tick down before doing its own full repaint.

A viewer without Lock Sync support is a **downgrade, not a failure**: the sweep
already positions every pane from geometry, the session records why, and every
frame says `controller`.

---

## 4d. Protocol-driven architecture (v1.1.0) — lumbar is a configuration

**The engine names no body part.** `capture_controller.py` reads a
`protocols.Protocol` and does what it says; `SLOT_SAG_T2`, `PASS_SAGITTAL` and the
literal `"lumbar_mri"` are all gone from it, and an AST guard keeps them out.
Adding Brain MRI is meant to be an entry in `protocols.py`, not a branch here.

**Roles, not viewports.** A slot key (`sagittal_t2`, `axial_flair`, …) IS the
semantic series role. The protocol maps roles onto viewport positions; the
controller iterates `selection.slot_order`, never a fixed triple.

**`CaptureSession` — one sweep, as data.**

| field | means |
|---|---|
| `name` / `label` | identity, and the progress text the reader sees |
| `primary` | the role that drives the sweep, one frame per slice |
| `synced` | roles that follow it each frame (Lock Sync moves them, geometry verifies) |
| `reference` | roles that provide cross-reference |
| `plane` | the primary's plane, which builds the capture order |
| `park_reference` | do the reference panes hold one slice, or follow? |
| `hide_reference_lines_on` | the panes captured CLEAN (§4e) |
| `directory` / `file_prefix` / `session_type` | the output structure |

`Protocol.sync_groups` is **derived** from the sessions rather than declared, so
it cannot contradict the sweeps that do the moving. `Protocol.implemented` now
requires slots AND sessions — slots alone are not a pipeline, and offering one
would fail mid-sweep.

Lumbar declares exactly what it did before:

```python
CaptureSession(name="sagittal", primary=SLOT_SAG_T2, synced=(SLOT_SAG_T1,),
               reference=(SLOT_AX_T2,), plane=PLANE_SAGITTAL, park_reference=False)
CaptureSession(name="axial",    primary=SLOT_AX_T2,  synced=(),
               reference=(SLOT_SAG_T2, SLOT_SAG_T1), plane=PLANE_AXIAL,
               park_reference=True)
```

**One frame builder.** `_position_frame(session, index)` replaces
`_position_sagittal_frame` / `_position_axial_frame`. It moves the primary
(quietly when the session parks its references, loudly otherwise so Lock Sync
propagates), settles each synced role against the geometric match, then either
parks or follows each reference role.

**⚠ MANIFEST SCHEMA CHANGE (1.0.0 → 1.1.0).** Frames are keyed by ROLE:

```json
{ "session": "sagittal", "driving_pane": "sagittal_t2",
  "reference_lines_hidden_on": ["sagittal_t2", "sagittal_t1"],
  "panes": {
    "sagittal_t2": {"role": "primary",   "series_uid": …, "instance": …,
                    "slice_index": 4, "position": [x,y,z]},
    "sagittal_t1": {"role": "synced",    …, "match": {…}, "followed_by": "lock_sync"},
    "axial_t2":    {"role": "reference", …, "parked": false}
  },
  "spatial_context": {…}, "axial_context": {…} }
```

The old `t2_sagittal_instance` / `axial_reference_slice_index` names are gone. A
generic controller cannot know a protocol's lumbar-shaped field names, and stage 2
has not been built yet — this is the cheapest moment the change will ever be.

**The store follows too.** `PassSpec.from_capture_session` supplies the folder,
filename prefix and `session_type` per session, so `Sagittal/` and `Axial/` are
lumbar's choices rather than the store's. `session_kind` is the protocol id and
`set_layout()` records the protocol's real layout.

Both classes were renamed (`EagleEyeCaptureController`, `EagleEyeCaptureSession`)
with their old names kept as aliases, so no caller breaks.

**Still lumbar-shaped, deliberately, and worth doing next:** the PACKAGE is still
`modules/ai_imaging/eagle_eye_lumbar/` and `series_classifier.LumbarSelection`
still carries the name. Both are cosmetic — the code inside is generic — and
renaming them touches every import plus the plugin mirrors, so it is a separate,
mechanical change rather than something to fold into this one.

---

## 4e. The pane being evaluated is captured CLEAN

**Requirement:** the yellow reference line must not be drawn over the image plane
currently being captured — it can lie across exactly the disc, canal or root the
frame exists to show, and once it is in the PNG no later stage can remove it.

A reference line is *context* for a pane you look FROM and an *obstruction* on a
pane you look AT. So per session:

| sweep | Sag T2 | Sag T1 | Ax T2 |
|---|---|---|---|
| sagittal | **off** | **off** | on (spatial reference) |
| axial | on (shows the level) | on | **off** |

Which panes those are is `CaptureSession.hide_reference_lines_on`, **derived by
default** as `primary + synced` — the panes being evaluated — so the rule and the
configuration cannot drift apart. A protocol may override it explicitly.

**Draw, then clear.** `_manage_reference_line_all_pairs` paints every viewport
from every other one and has no per-viewport switch; adding one would mean editing
a shared, plugin-mirrored authority the whole workstation uses.
`reference_lines.ReferenceLinePolicy` therefore redraws normally and then clears
the overlay on the suppressed panes, through the engine's own clearing paths
(`qt_viewer.clear_overlay_lines()` for the Qt bridge,
`reference_line.rl_hide_actor_if_any()` for VTK). One extra pass over at most
three viewports, no fork of the drawing code, and it finishes long before the
130 ms settle that precedes the grab.

**What "restore previous state" honestly means here.** Eagle Eye never mutates a
global reference-line setting — not `AIPACS_REFERENCE_LINES_ALL_PAIRS`, not the
line style, not a toolbar toggle. The only state it changes is which overlays are
currently painted, so `restore()` is one unsuppressed redraw and nothing more. A
guard pins that the policy module never reads or writes the global flag, to stop
someone "improving" this into a fake save/restore of a setting nobody touched.

Unlike Lock Sync, the reference lines **are** restored on the success path: the
suppression exists for the screenshots, and a reader left with two blank panes
would see a change they never asked for.

---

## 5. The sweeps (spec §6, §9, §10)

Both passes capture `patient_widget_container` — the **whole 3-panel layout**, via
`modules/viewer/viewport_capture.grab_widget_pixmap` (the app-wide OpenGL-safe grab).

**Sagittal pass** — Sag T2 drives, right → left. Per frame: T2 slice set → **Lock Sync
carries T1 and the axial pane to the corresponding anatomy** (§4b), verified against the
geometric match and corrected if it did not land → reference lines redrawn → capture. The
reader never scrolls the T1 stack by hand.

**Axial pass** — both sagittal panes are **parked** on their most mid-line slice for the
whole pass, so the only thing moving in them is the axial reference line, which is precisely
the craniocaudal information each axial frame needs. Axial drives, head → feet.

Reference lines use `_manage_reference_line_all_pairs` **called directly**, not the
`AIPACS_REFERENCE_LINES_ALL_PAIRS` env flag — that keeps the behaviour scoped to the Eagle
Eye widget and leaves the main viewer untouched. Two parallel sagittal planes do not
intersect, so all-pairs naturally produces sagittal↔axial lines only. The controller calls
it synchronously before each grab rather than relying on the 50 ms throttle, because the
very next thing that happens is a screenshot.

**Threading:** none. One frame per `QTimer.singleShot` tick on the GUI thread — VTK viewers
can only be driven from there, and a worker thread would buy nothing but the
"destroyed while running" crash class this codebase already paid for (OPT-51). A guard
parses the module's AST and fails if a `QThread` import or a `while` loop appears.

---

## 6. Session on disk (spec §8, §11, §12, §13)

```
user_data/ai/eagle_eye/<StudyInstanceUID>/<session_id>/
    session.json
    Sagittal/  manifest.json  sagittal_001.png …
    Axial/     manifest.json  axial_001.png …
```

`session_id` is a UTC stamp (`20260826T141530Z`); a same-second re-run gets `_2`, never
appends to the previous session. A malformed study UID is sanitised to a single safe path
segment (a guard asserts `../../etc/passwd` cannot escape the root).

Per capture (sagittal pass): capture index, image name, T2 series UID + SOP UID + slice
index + IPP, T1 series UID + SOP UID + slice index + IPP, the T1 match distance and whether
it was within tolerance, the axial reference series/SOP/index/IPP, the spatial-context
label (`side` right/left/midline, `region` central_canal / paracentral_lateral_recess /
neural_foraminal / extraforaminal, signed `offset_mm`), the axial craniocaudal context, and
the capture timestamp.

`session.json` adds patient/study identity, study date, region, the three selected series
UIDs/numbers/descriptions, the full classifier verdict (scores, confidence, reasons,
alternatives, rejections), the layout definition, per-pass capture counts and directions,
creation/completion timestamps and `eagle_eye_version`.

Manifests are written temp-then-`os.replace`, so a crash mid-write cannot leave a
half-parsed manifest.

`validate()` cross-checks disk against the manifests — gapless 1..N indices, no duplicate
filenames, no manifest entry without a file, no image on disk missing from the manifest —
and any problem is logged **and appended to `session.json` as a note**.

---

## 7. Test coverage

`tests/code/ai_imaging/test_eagle_eye_lumbar_pipeline.py` — **74 passing**, headless:

plane classification (incl. disc-angled axial and oblique) · ordering direction and the
reversed-stack guard · fallback when IPP is missing · T2↔T1 physical matching across
different slice counts · weak-match flagging · midline estimation · context bands · slot
resolution on a realistic protocol with localizer/STIR/coronal traps · TE overruling a
mislabelled description · PD not called T1 · unresolved slots staying unresolved · no series
in two slots · mode normalisation with the three delegating copies pinned to the authority ·
region veto (cervical/thoracic/brain) · session layout, filenames, manifests, validation
(missing image, orphan image), collision and path-traversal safety · controller wiring.

Plus the §2b regression set: the exact live-study field values, `BodyPartExamined` verdicts
for every region seen in the local library, body-part-beats-description precedence, and the
case-insensitive-glob double-count.

`test_eagle_eye_protocol_resolution.py` adds the pre-flight: body-part → protocol
for six regions · unimplemented protocol is never "certain" · description-only
detection is never high confidence · conflicting descriptions → low · protocol
slots/layout are data · one study is not a choice · **a clearly-labelled lumbar
study asks nothing at all** · several studies always ask · cancel at any step
opens nothing · a confidently-recognised unsupported region is refused rather
than offered a picker · only the uncertain slot is asked about · the slot picker
never offers a gate-rejected series · validation refuses a duplicate or missing
slot · the hand-off is delivered exactly once and never to another study.

Plus the §4a set: the tab must not pre-wait on `lst_thumbnails_data`, the controller must
ask by series key and never by list position, no call site may pass
`flag_change_selected_widget=True`, and the readiness wait must still refuse rather than
capture a half-loaded layout.

Plus the §4b Lock Sync set — real behaviour tests against a fake widget, not source pins,
because `lock_sync.py` is pure Python (its one Qt-adjacent import is lazy): enable turns it
on · registration is pipeline-only (no click-to-target interactor, no red dot in the
screenshots) · an OFF state is restored OFF with `set_lock_sync(False)` **before** the
teardown · an ON state is left ON and untouched · restore is idempotent · suspension holds
and correctly releases the engine's own `_lock_sync_updating`, including a nested hold · a
viewer without Lock Sync degrades instead of failing · the manifest payload records the
geometric basis · `follower_source` names all four cases. Source-pinned alongside them:
enable happens before the first sweep, the axial pass and the parking both drive quietly,
and the geometric verification is still in place.

Plus the §4a-ii set: readiness compares decoded against the probe's on-disk count · a
short capture order is refused before `build_capture_order` runs · a pane on the right
series is never re-asserted while it is still decoding · a stalled decode is refused early
rather than waited out (and a pane at zero counts as waiting, not stalled) · the timeout
says how far the decode got · and (§4b, revised) a successful run leaves Lock Sync ON while
a failed one still restores.

Plus the §4d/§4e sets: the sagittal sweep captures both sagittals clean while the axial
pane keeps its line and vice versa · hidden panes default to the ones being evaluated · a
session may override that · draw-then-clear repaints only the cleared panes · restore is
one unsuppressed redraw and is idempotent · the policy never touches the global all-pairs
flag · lumbar's two sweeps are protocol data · `sync_groups` is derived · a protocol
without sessions is not `implemented` · **a brain protocol can be declared and read back
without touching the engine** · the engine's AST contains no lumbar role, pass name or
literal · frames are keyed by role.

`tests/code/ai_imaging` → **426 passed, 8 xfailed** (all pre-existing quarantined).
`tests/code/viewer` → **2,288 passed** (no failures); the two together, 2,714 passed.
`tools/dev/verify_plugin_mirrors.py` → **456/456 match**.

`tests/code/system/test_local_search_progressive.py` has 4 failures — **pre-existing**,
proven by stashing the two `PacsClient` edits and re-running (same 4 fail). Likewise the
10 failures in `tests/code/ui_services` (`test_field_icon_chip`,
`test_local_incremental_and_import_date`, `test_report_assign_rendering`,
`test_status_report_sorting`) — a qtawesome font-directory failure plus two stale source
pins, all 10 reproduced with this work stashed.

---

## 8. What is NOT verified — do this next

**FIRST CLEAN END-TO-END RUN: session `20260826T124329Z`, patient 55778.**
9 sagittal + 22 axial frames — full coverage of both stacks. `t1_followed_by: lock_sync`
on **all 9** sagittal frames (zero corrections, so the DICOM mapping held every time).
`direction: right_to_left` / `axis: lps_x` for the sagittal pass and
`superior_to_inferior` / `lps_z` for the axial, both `from_geometry: true`. Spatial context
runs right extraforaminal → foraminal → paracentral → midline central canal → left, which
matches the images. Sagittal panes parked at #6 for the whole axial pass and stayed there.
Reference lines correct in both passes: the vertical line tracks across the axial pane as
the sagittal sweeps, and the horizontal line rotates down the sagittals as the axial
descends. No torn or mid-render frames at `_STEP_SETTLE_MS = 130`.

Items 1, 2, 2a, 2b, 2c, 3, 4, 5 and 6 below are therefore **VERIFIED**. What that run also
exposed is listed under "Open after the first clean run".

1. ~~**Series selection on real studies.**~~ **Done for one study** (patient 55837,
   Siemens): gate `lumbar`, all three slots resolved at high confidence, four other-region
   studies correctly refused. Still worth repeating on other scanners — check the console
   `[LUMBAR] verdict=…` and `[LUMBAR] <slot>: <series> score=… confidence=…` lines.
2. ~~**The 1×3 layout actually builds.**~~ **Done** — three panes rendered correctly on
   patient 55991 (first live run). What that run also exposed is fixed in §2a-i.
2a. **The three panes carry the three RIGHT series, quickly.** The §4a fix is not yet
   confirmed on hardware. Watch for `eagle_eye_lumbar: <slot> <- series key <n>` followed by
   the sweep starting; a `re-asserting …` line means a pane drifted and was recovered, and a
   `timed out loading …` line now names wanted-vs-shown for each pane.
2b. **Lock Sync actually carries T1 during the sagittal pass.** The §4b wiring is not yet
   confirmed on hardware. Expect `eagle_eye_lumbar: Lock Sync ON (was off)` in the log and,
   in `Sagittal/manifest.json`, `t1_followed_by: lock_sync` on most frames. A run full of
   `lock_sync_corrected` means the mapping is failing (look for
   `_do_lock_sync: ALL n target(s) FAILED mapping`) and the pairing is only surviving
   because of the geometric fallback — worth investigating even though the output is right.
   Also confirm the sagittal panes do NOT drift during the axial pass, and that scrolling
   one sagittal pane AFTER the sweep still moves the other (Lock Sync is left on now).
2c. **THE FRAME COUNT IS THE FIRST THING TO CHECK.** §4a-ii. A correct lumbar run should
   report roughly `<sagittal slice count> sagittal + <axial slice count> axial frames` —
   for the 2026-08-26 study, 9 + 22. Anything short means readiness passed on a
   half-decoded stack, and the session will look internally consistent while covering a
   fraction of the study. The run should now take appreciably longer than 4.7 s, because
   it waits for the decode instead of racing it.
3. **Reference lines on MR in the Eagle Eye widget.** `_manage_reference_line_all_pairs`
   needs `iv.vtk_image_data`; confirm lines appear on the axial pane during the sagittal
   sweep and on both sagittal panes during the axial sweep.
4. **Capture timing.** `_STEP_SETTLE_MS = 130`. If frames come out mid-render, raise it.
5. **Ordering direction against anatomy.** Open `Sagittal/manifest.json`, confirm
   `direction: right_to_left` matches what the images show.
7. Re-run `tests/code/ai_imaging` and `verify_plugin_mirrors.py` after any change.

8. **The reference-line policy and the generic engine (v1.1.0) on hardware.** Confirm both
   sagittal panes carry NO yellow line during the sagittal sweep (axial keeps its vertical
   line), and the axial pane carries none during the axial sweep (both sagittals keep the
   line showing the level). After the run every pane should have its lines back. The
   manifests are now role-keyed — check `panes.sagittal_t1.followed_by` where you used to
   check `t1_followed_by`, and note `reference_lines_hidden_on` per frame.

### Open after the first clean run — decide before stage 2

- **Every frame carries the tab's left sidebar.** `capture_widget` is
  `patient_widget_container`, which includes the series-thumbnail panel and the
  EAGLE EYE / Advanced Analysis rail — roughly 15% of each frame is UI chrome, not
  anatomy. Harmless for a human reviewer; for an LLM it is wasted context in every
  one of 31 images. Decide whether to capture the 3-pane grid alone.
- **PHI is burned into every frame.** The viewport overlay paints patient name, PID,
  age and sex into the pixels. That is correct for a workstation screenshot and a
  deliberate decision to make before stage 2 uploads these anywhere.
- **The axial pane is static through the whole sagittal pass.** All 9 sagittal frames
  reference axial slice 10, because every sagittal slice shares the same z-centre and
  therefore maps to the same axial level. Geometrically right, informationally empty —
  the axial pane contributes one image repeated nine times. Worth deciding what that
  pane *should* show during the sagittal sweep.
- **`session.json` demographics are empty.** `patient_id`, `patient_name`,
  `study_date` and `study_description` all came out `''`; `build_study_context` reads
  `patient_widget.metadata_fixed` / `.patient_id`, which AIPatientWidget does not
  populate. Traceability is intact (study UID + all three series UIDs are present) and
  the identity is legible in the pixels, but the JSON should not be blank.

---

## 9. Stage 2 (historical plan; implemented separately)

The implemented analysis pipeline and live results are documented in
`docs/plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md`.

Package `Sagittal/` + `Axial/` + `session.json` and send to the LLM for pathology analysis.
The manifests were designed to be that hand-off: every frame is traceable to its Series
Instance UID, SOP Instance UID and patient-space position.

---

## 10. UI boundary extraction (2026-08-28)

The Eagle Eye workflow no longer lives inside the general-purpose
`ImagingToolsTab` controller. The feature package now owns the Qt-side workflow in
`modules/ai_imaging/eagle_eye_lumbar/workflow_coordinator.py`:

- preflight mapping consumption and fallback classification;
- capture-controller construction, progress, completion, and failure handling;
- captured-session handoff to the off-thread LLM runner;
- stored-result lookup, result-panel lifecycle, and explicit reanalysis;
- close-while-running capture abort and analysis detach.

The dedicated non-modal result window moved with the feature to
`modules/ai_imaging/eagle_eye_lumbar/result_panel.py`, so the feature package does
not import a component back out of the general `service_tab` package.

`imaging_tab.py` is limited to constructing `EagleEyeWorkflowCoordinator`, wiring the
result button, scheduling `start_capture()` after the layout paints, displaying status,
and calling `teardown()` from `closeEvent`. Capture geometry, protocol resolution,
evidence preparation, model routing, GapGPT transport, prompts, and persistence were not
changed by this extraction.

`tests/code/ai_imaging/test_eagle_eye_ui_boundary.py` prevents the workflow methods from
returning to `ImagingToolsTab` and behaviorally protects mapping-by-series-identity and
safe teardown. Its architecture guard failed before the coordinator existed. The focused
boundary/resolution gate passed 56 tests, and the broader capture/resolution/LLM gate
passed 267 tests after the extraction. The complete `tests/code/ai_imaging` gate passed
518 tests with 8 pre-existing quarantined xfails.
