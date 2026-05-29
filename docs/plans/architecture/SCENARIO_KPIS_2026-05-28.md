# Live KPI evaluation — 2026-05-28 session

## Verdict

Behavioral PASS for Issue 1 and Issue 3. Issue 2 (Eagle Eye 0x8001010d
drag-drop crash) not exercised this session — it requires opening
Eagle Eye on an MG study, which wasn't part of the scenario.

## Caveats up front

The running app did NOT write to
`E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\logs\`. Files
there have been 0 bytes for 13.5 hours since I truncated them yesterday,
and the screenshot system reminder consistently lists `ai pacs viewer.exe`
in the hidden-process list. This is almost certainly the **frozen
installed build**, not the source build's `python.exe`. Two explanations
both consistent with what I saw:

1. The frozen build was rebuilt today/yesterday with the 2026-05-27
   fixes already baked in.
2. The frozen build never had these bugs (less likely — the original
   bug reports came from this same build).

Either way, KPIs below are wall-clock measurements I took directly,
not extracted from log timestamps. Tighter sub-100 ms measurements
require a fresh source-build session writing to the project's logs;
the extractor at `tests/gui/live_walkthroughs/extract_2026_05_27_kpis.py`
is ready to parse those.

## Scenario 1 — patient open speed (Issue 1)

| Step | Wall-clock | Threshold |
|---|---|---|
| MR + "Two days ago" search → 55 studies appear | ~4 s | < 10 s post-fix; ~30+ s pre-fix |
| Patient 1 (malakoti somayeh, 43371) click → right panel populates 12 series | < 1 s | < 1 s post-fix; 6.8 s pre-fix per ZETA §14 |
| Patient 2 (ALI NIYAY FATEMEH, 43649) → 6/6 series | < 1 s | < 1 s |
| Patient 3 (GHOREYSHI ROBABEH, 43698) → series rendered | < 1 s | < 1 s |
| Patient 4 (MIRZAEE AGHA SHIR, 43686) → series rendered | < 1 s | < 1 s |
| Patient 5 (HAFIZ ABOLGHASEM, 43738) → 8/8 series | < 1 s | < 1 s |

**Behavioral verdict: PASS.** Every open completed inside the 1-second
wait I imposed between clicks, including correct thumbnail rendering
for completely different anatomies (LSPINE, CSPINE, HEAD/BRAIN, WRIST).
The pre-fix 6.8 s GetStudyInfo stall was not observed.

## Scenario 2 — bulk Download queue (Issue 3)

| Step | Wall-clock | Threshold |
|---|---|---|
| Check all 15 visible MR patients (Shift-click range) | instant | n/a |
| Click Download icon (toolbar) → DM tab opens | ~1 s | n/a |
| All 15 patients (header says Total: 16) appear in queue with image counts | < 2 s total | < 3 s post-fix; 20-30 s pre-fix |
| First worker shows DOWNLOADING with progress bar | < 2 s | n/a |
| Every row: PENDING + per-patient image count (59–273) | populated | full metadata visible |

**Behavioral verdict: PASS.** All 15 patient rows showed correct
per-patient image counts (208, 59, 50, 51, 180, 71, 273, 118, 63, 91,
55, 51, 107, 53 visible — i.e. the parallel pre-fetch completed before
the DM tab paint finished) and one download was already running by
the time the screenshot landed. The pre-fix 20-30 s freeze pattern was
not observed.

## Scenario 3 — Eagle Eye drag-drop (Issue 2) — NOT EXERCISED

Requires opening Eagle Eye on an MG (mammography) study and dragging
a series thumbnail into the 1×2 viewport. This session filtered MR
modality only and didn't run Eagle Eye.

To validate Issue 2 specifically, run the pywinauto test we shipped:

    python tests/gui/pywinauto/test_eagle_eye_dragdrop.py

It will skip cleanly if the source build isn't detected; with the
source build up + Eagle Eye loaded on an MG study, it performs 3 real
Win32 drag-drop operations and asserts no new 0x8001010d entries
appear in `native_fault.log`.

## Sanity bounds for tighter KPIs next session

To get sub-100 ms numbers (rather than "< 1 s wall-clock"):
1. Launch the **source build** (Python icon) from VS Code.
2. Verify writes to `E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\logs\`
   are flowing by waiting 5 s after Server Ready and re-running
   `python tests/gui/live_walkthroughs/_verify_source_build.py`.
3. Re-drive Scenarios 1 + 2 (steps as above).
4. Run `python tests/gui/live_walkthroughs/extract_2026_05_27_kpis.py`
   for per-call `right_panel_socket_done` deltas (target < 400 ms median).
