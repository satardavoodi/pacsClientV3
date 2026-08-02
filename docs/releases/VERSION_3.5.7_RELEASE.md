# AI-PACS v3.5.7 — Release Record

**Version:** 3.5.7
**Release date:** 2026-08-02
**Previous stable:** v3.5.6 (2026-07-26)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor (large) — MPR crash/perf hardening, DB + download resilience, EchoMind Phase-1 overhaul, per-series export

---

## 1. Headline

The biggest release in the 3.5 line — a full week of stability, reliability, and
reporting work (91 files changed, ~9,500 insertions). Four themes:

1. **MPR** no longer crashes on very large studies, and opens/scrolls faster
   (OPT-47/48/49).
2. The app **stays responsive under heavy load** and survives a crash mid-download
   (OPT-45 role-aware DB timeout, OPT-46 crash-durable queue, status column off the
   GUI thread).
3. **EchoMind** received a deep Phase-1 reliability overhaul.
4. Export and workflow polish — per-series CD/offline selection, a local Patient-ID
   correction alias, and Advanced-Search Local/Server routing.

---

## 2. MPR — crash and performance (OPT-47 / 48 / 49)

**OPT-47 — large-study first-open crash.** On a ~700-800 slice study, MPR crashed
and closed the app on the first attempt (a relaunch then opened the same study
fine). Three compounding causes:

- The GPU volume budget was a fixed `512 MB`, which VTK multiplies by its 0.75
  memory fraction = ~384 MB = **exactly 768 slices** — and the mapper is
  `vtkGPUVolumeRayCastMapper` with **no CPU fallback**, so exceeding it was a
  driver-level access violation with no Python traceback.
- The ITK→VTK host path made **three full copies** of the volume (~1.26 GB
  transient at 800 slices).
- Teardown released the GPU + volume but not the render graph, so VRAM accumulated
  across opens — which is exactly why a relaunch (fresh VRAM) succeeded.

All three fixed (GPU budget scales with the volume + disables gradient opacity /
MSAA on large volumes; a single ITK→VTK copy; a full teardown), with reconstruction
geometry unchanged.

**OPT-48 — open/scroll performance.** The L-R flip moved off the GUI thread;
enlarged reconstructed panes no longer shake on scroll.

**OPT-49 — lifecycle.** Exactly one open may be in flight (re-entrancy guard —
modal progress dialogs pump the event loop, and the EchoMind command bus can open
MPR programmatically); `cleanup()` marks closed first so deferred VTK callbacks
can't fire into a finalized window; and close is the inverse of open (every actor,
container, timer, and cross-module reference released), fixing monotonic memory
growth across repeated open→close→open. Geometry safety is enforced by guard tests
that forbid every geometry setter in the changed code.

Reports: `docs/reports/MPR_LARGE_STUDY_CRASH_TRIAGE_2026-08-01.md`,
`MPR_SLOW_HIGH_SLICE_COUNT_52827_2026-08-01.md`, `MPR_VTK_LIFECYCLE_REVIEW_2026-08-01.md`,
`MPR_ENLARGED_SCROLL_JITTER_2026-08-01.md`.

---

## 3. Responsiveness & durability (OPT-45 / OPT-46 / status-async)

**OPT-45 — role-aware `dicom.db` busy-timeout.** `dicom.db` is WAL, so only a
GUI-thread *write* can block — and it could block for the full flat `120 s`
busy-timeout behind the download subprocess's insert burst, producing up-to-2-minute
UI freezes. The **main GUI process now fails fast (5 s)** while the **download
subprocess keeps the full 120 s** (detected by process name + an explicit role
marker) — so the UI stays responsive and no clinical instance row is ever dropped.
Default-on kill switch.

**OPT-46 — crash-durable download queue.** The pending/failed/priority queue was
in-memory only, so a crash lost it (downloaded data was always safe — disk + atomic
`.part`→`os.replace`). It now writes each enqueued study's sanitised re-enqueue spec
to `<SOURCE_PATH>/<study_uid>/.dm_task.json` (never the DB — that would reintroduce
the OPT-45 main-thread write load) and auto-resumes interrupted downloads ~9 s after
restart, reusing the normal `add_downloads` path. **Default-off** until live-verified.

**Status column off the GUI thread.** Rendering the local list did per-row disk I/O
(attachment `os.walk` + reception JSON + DB queries) on the GUI thread — multi-second
freezes right after an import on a ~2000-study store. The bulk render now reads the
status cache only and computes misses on a background worker, filling the chips in
via a queued signal. Default-on.

---

## 4. EchoMind — Phase-1 reliability overhaul

A large, multi-batch audit and fix pass. Highlights:

- **One transport authority** (`echomind_http.py`): every AI/voice call goes through
  a single `post`/`get` that honours the Settings proxy — previously the four chat
  modes and every voice upload passed no proxy at all, so the "all EchoMind calls
  tunnel through the proxy" promise was false for half the module. Correct
  connect/read timeouts; retry only on a connect-phase failure (never a
  report-generating ReadTimeout, which could double-submit).
- **Honest error classification** — no-key / auth / quota / model / server / network
  are distinguished instead of all flattening to "check your internet", while still
  redacting endpoint/credentials.
- **No blocking I/O on the GUI thread** — the reception send (~50 s), both Settings
  "Test Connection" probes, and the Secretary voice command's *planning* phase moved
  to workers; teardown uses detach-don't-wait (never `wait()`, never GC a live
  QThread).
- **The two AI backends are one product** — the `openai` twin previously ran a
  ~1,100-character generic prompt (no BI-RADS rules, no temperature clamp, no output
  validation); report and correction prompts are now shared authorities called by
  **both** backends, with a parity guard test.
- **Normal Template workflow** — physicians' normal-report templates now persist on
  disk (`normal_templates.py`, pure stdlib) instead of being re-uploaded from a file
  dialog every launch, with a fenced, schema-deferring merge prompt and a manage
  dialog (`normal_template_dialog.py`).
- **Reception dedupe + safer storage** — a byte-identical still-`pending` report no
  longer inserts twice; image attachments and transcripts can't cross a session
  boundary; a Windows file-race in the assignment state store was closed; and no
  clinical content is written to logs or stdout.

All EchoMind files are plugin-mirrored and synced (422/422). ~20 new EchoMind guard
suites under `tests/code/echomind/` plus `tests/gui/`.

---

## 5. Export & workflow

- **Per-series export selection.** Both the CD-burn and Offline-export pop-ups now
  offer Select-All ▸ per-study ▸ per-series checkboxes (default: everything). One
  shared widget (`series_selection_widget.py`); filtering happens at the on-disk
  copy/enumeration layer, so `package.db`, the series folders, and the DICOMDIR all
  agree automatically. Default-on.
- **Local Patient-ID correction alias.** A reception typo corrected locally used to
  revert to the server's value on the next search (the server has no
  demographic-write endpoint). A new display-only alias (`database/patient_overrides.py`)
  keeps the corrected ID shown while the cell's real value stays the server ID (the
  identity/join key ~25 call sites depend on). **Default-off** (opt-in).
- **Advanced Search follows the Local/Server tab.** The More-Filters search always
  hit the server regardless of the active data-source tab; it now routes by that tab
  (Local → local DB, Server → the selected server), and clears the table on a mode
  switch so stale rows never linger.
- **Shutdown-initiator logging.** Diagnostic hooks that attribute an unexplained "the
  app just closed" to its real cause — a clean shutdown, a real crash, or a
  single-instance takeover — after a "crashed repeatedly" report turned out to be
  zero crashes (a whole-PC reboot + the takeover killing an idle instance). Also
  fixed an orphaned download-subprocess leak.

---

## 6. Verification status

Offscreen (test lane): extensive new guard suites across `tests/code/echomind`,
`tests/code/viewer` (MPR safety/lifecycle/latency/scroll), `tests/code/system`
(DB busy-timeout, shutdown-initiator), `tests/code/download_manager` (queue
persistence, prewarm registration), `tests/code/offline_cloud_server` +
`tests/code/cd_burner` + `tests/code/ui_services` (series selection, patient-ID
overrides, status async, advanced-search routing), and `tests/gui`.

**Still required — live source-build verification** (cannot be done from the test
lane), and this release is large enough to warrant a full clinical-lane pass:

1. **MPR:** open a 700-800 slice study → no crash; open/close ×2 then another
   reconstruction while watching RSS; rapid double-click logs "open ignored".
2. **Load:** heavy multi-series download → UI stays responsive; kill mid-download →
   interrupted studies resume ~9 s after relaunch (OPT-46 must be enabled).
3. **EchoMind:** generate a report on each backend; reception send doesn't freeze the
   UI; a Normal Template merges correctly.
4. **Export:** untick a series in each pop-up → only the chosen series on the
   disc/package + DICOMDIR.
5. **Patient-ID alias:** correct an ID with the flag on → it survives a refresh;
   assignment + reports still work via the original server ID.

---

## 7. Note on the satar-ui branch

The `satar-ui` UI-integration work is being reviewed/fixed in a **separate worktree**
(`_integrate-satar-ui`); the `beta-version` tree is untouched by it apart from two
review documents included here (`REVIEW_satar_ui_branch_2026-08-02.md`,
`INTEGRATION_satar_ui_branch_2026-08-02.md`). It is not part of this release's code.

---

## 8. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.7` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
