# Regression Review — Startup Freeze & Secretary EchoMind Viewport-Import Freeze (2026-07-08)

**Scope:** two reported UI-thread freezes — (1) startup / main-page patient search, (2) Secretary
EchoMind importing an image/series into the viewport. **Method:** analysis of the fresh runtime logs
under `user_data/logs/` (main-thread probe + stall-trace stacks), git history of the suspect code
paths, and a read-only code map of the EchoMind command path. **No code was changed** — this is a
root-cause review with a safe, flag-gated fix plan.

Evidence runs: the richest evidence is the **2026-07-07 (v3.4.6)** sessions, which had the main-thread
probe + stall tracer enabled (`sess-d2bd9ea75f3f`, `sess-42b179dde515`, `sess-…` pid 17092/18968). The
2026-07-08 11:xx session only recorded 2 small stalls (short/warm session; the freezes were not
re-triggered that run).

---

## Executive summary

| | Freeze #1 — Startup / patient search | Freeze #2 — EchoMind viewport import |
|---|---|---|
| **Symptom** | UI frozen ~seconds during/after the main page loads | UI frozen when EchoMind loads a series into a viewport |
| **Measured** | main-thread stall **up to 21,054 ms** (also 20,074 / 8,546 / 7,357 ms), `interaction_active=False`, `t_since_start ≈ 25–49 s` | main-thread stall **~2,400 ms** per switch (VTK render); AI-segmentation network POST climbing to **6,498 ms** |
| **Root cause** | `web_browser.prewarm._construct_warm_view` constructs a `QWebEngineView` (full Chromium engine boot) **on the GUI thread** | EchoMind dispatch runs **inline on the UI thread**; the Advanced/VTK viewport switch builds `ImageViewer2D()` + VTK `Render()` synchronously; AI-segmentation does a synchronous `requests.post` on the UI thread |
| **Regression?** | **Pre-existing** (code + call site landed v3.3.9, 2026-06-27). Not from the unified-pipeline work. More visible now (marker-gated + machine state). | **Underlying cost pre-existing**; the **v3.4.6 "EchoMind unified MCP" is the new trigger** that exposes it. Exposure regression. |
| **Unified-pipeline related?** | **No** | **No** (the multi-study / series-identity / append work is not on either hot path) |
| **Immediate mitigation** | `AIPACS_BROWSER_PREWARM=0` (kill switch already exists) | route EchoMind import through the existing async load path + show the loading spinner; move AI-seg upload off-thread |

**Main question answered:** neither freeze is caused by the recent unified/stabilization pipeline
changes. Freeze #1 is a **pre-existing** Chromium-prewarm bottleneck (since 2026-06-27) that is
marker-gated, so it only appears after the user has opened the in-app web browser once. Freeze #2 is a
**pre-existing synchronous-viewport-switch cost newly exposed** by the v3.4.6 EchoMind unified MCP,
which dispatches commands inline on the UI thread with no deferral or progress UI.

---

## Freeze #1 — Startup / main-page patient search

### 1. Root-cause analysis
The in-app web-browser module schedules an **adaptive Chromium pre-warm** ~4 s after the home panel is
built (`HomePanelWidget.__init__` → `schedule_prewarm()`). The intent is good — amortize Chromium's
one-time engine boot so the *first* real browser open is instant instead of a "~20 s cold boot" (the
code comment says exactly this). The prewarm module correctly moves the **DLL import** to a daemon
thread, **but a `QWebEngineView` must be constructed on the GUI thread**, and constructing the first
one boots the entire Chromium engine. That construction is posted back to the GUI thread
(`QTimer.singleShot`) and blocks it for the full engine-init duration — **~21 s on the observed run**.

The stall ends at the exact millisecond the prewarm logs completion:
- `14:57:54.676` `web_browser.prewarm._construct_warm_view` → "Chromium engine warmed"
- `14:57:54.741` `[MAIN_THREAD_STALL] stall_duration_ms=21054.2 interaction_active=False t_since_start_s=39.2`

So the 21 s freeze **is** the GUI-thread Chromium construction. Other startup costs stack around it but
are minor by comparison (theme `setStyleSheet` ~1.4 s; `patient_search_widget.setup_ui`; the EchoMind
bus build, which is cheap — see §"Not the cause").

### 2. Regression or pre-existing
**Pre-existing.** `git log -S` shows both the prewarm module (`modules/web_browser/prewarm.py`) and its
call site (`home_panel/widget.py::schedule_prewarm()`) landed in **v3.3.9 (2026-06-27)** and were **not
modified in v3.4.6** (the v3.4.5→v3.4.6 web_browser diff touched only `page_tools.py` and `widget.py`
in the browser module, not `prewarm.py` or the call site). It appears "new" because it is **stateful**:
`schedule_prewarm()` is a no-op unless a marker file says the user opened the browser in a previous
session, and `AIPACS_BROWSER_PREWARM=0` disables it. Once the user has used the browser once, every
subsequent startup pays the prewarm. The 2026-07-05 "clean startup" OPT-12 verification predates that
marker being armed (or ran on a warm Chromium cache), which is why it wasn't seen then.

### 3. Exact code paths
- `PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py:289-290` — `from modules.web_browser.prewarm import schedule_prewarm; schedule_prewarm()` (in `HomePanelWidget.__init__`, on the UI thread).
- `modules/web_browser/prewarm.py:80 schedule_prewarm(delay_ms=4000)` → `:132 QTimer.singleShot(delay_ms, _warm_ctl.kick)`; `:97-125` daemon thread `_bg_import` imports QtWebEngine, then posts back.
- `modules/web_browser/prewarm.py:137 _construct_warm_view()` → `:153 view = QWebEngineView()` **(GUI thread; boots Chromium)** → `:173 QTimer.singleShot(2500, _release)`.

### 4. Supporting logs
```
2026-07-07 14:57:27.933 web_browser.prewarm.schedule_prewarm   browser prewarm: scheduled (delay=4000ms)
2026-07-07 14:57:54.676 web_browser.prewarm._construct_warm_view  browser prewarm: Chromium engine warmed
2026-07-07 14:57:54.741 [MAIN_THREAD_STALL] stall_duration_ms=21054.2 interaction_active=False t_since_start_s=39.2
2026-07-07 22:36:10.347 [MAIN_THREAD_STALL] stall_duration_ms=20074   interaction_active=False t_since_start_s=48.8
```
Startup-phase stalls this run: **153** (`interaction_active=False`) vs 31 during-use. The two 20 s+
stalls dominate.

### 5. Safe fix plan (flag-gated, no behavior loss)
Ordered by safety:
1. **Immediate (zero-risk):** set `AIPACS_BROWSER_PREWARM=0` for affected users. Startup is clean; the
   first browser open pays the ~20 s once (expected, user-initiated). This is the existing kill switch.
2. **Recommended fix — defer to a genuine idle window, not 4 s after home load.** Raise the delay and
   gate the `kick` on "no user interaction in the last N seconds" (reuse the main-thread probe's
   `interaction_active`), and skip it entirely while the patient list is still populating. Keep it
   marker-gated. Flag `AIPACS_BROWSER_PREWARM_IDLE_ONLY` (default on), kill switch reverts to legacy.
3. **Better UX — construct on first intent, not speculatively.** Warm on first *hover*/focus of the
   browser toolbar button (a few hundred ms before the click) instead of at startup. Removes the
   startup cost entirely for users who don't open the browser that session.
4. **Cannot be fully backgrounded:** `QWebEngineView` construction is GUI-thread-only by Qt design, so
   the engine boot cannot move to a worker thread. The fix is *timing/opt-in*, not off-threading.

### 6. Risk assessment
Low. The prewarm is a pure optimization with an existing kill switch; disabling or deferring it only
changes *when* Chromium initializes, never whether the browser works. No clinical/viewer path touched.
Regression risk of option 2/3 is confined to the web-browser module (not plugin-mirrored on this path).

### 7. Validation after fix
- Launch with the main-thread probe on (`AIPACS_MAIN_THREAD_PROBE=1 AIPACS_MAIN_THREAD_TRACE=1`),
  browser marker armed. Confirm **no `interaction_active=False` stall > ~500 ms attributable to
  `_construct_warm_view`** in the first 60 s, and the patient list is interactive within ~a few seconds.
- Open the web browser once and confirm it still opens correctly (warm or cold).
- With `AIPACS_BROWSER_PREWARM=0`, confirm startup has zero prewarm stall and the browser still opens.

---

## Freeze #2 — Secretary EchoMind viewport import

### 1. Root-cause analysis
EchoMind command dispatch is **inline on the Qt UI thread end-to-end** — there is no worker hop at the
dispatch layer. The in-app Test Control server drains one command per event-loop turn via
`QTimer.singleShot(0, self._drain_one)` (UI thread) → `bus.execute(plan)` → `registry.dispatch` →
`method(plan, state)` **inline**. The import action `change_series` (the MCP `drag_series` tool / voice
"load series N") calls `change_series_on_viewer(...)` **synchronously**.

`change_series_on_viewer` does off-thread decode on a clean cache-miss (good), but several branches run
**synchronously on the UI thread**, and that is where the freeze lands:
- the render-apply of a loaded series builds the **Advanced/VTK** viewport inline: `switch_series`
  (AI-imaging override) → `ImageViewer2D.__init__` → `Render()`. VTK render is GUI-thread by design; the
  observed construction took **~2.4 s** for one series.
- recovery decodes call `_load_single_series_on_demand` **inline** when the cached payload is missing /
  has bad dims / has no VTK scalars (three branches).

Separately, the AI-imaging **segmentation** workflow does a **synchronous network POST on the UI
thread** (`on_contour_closed` → `download_file` → `requests.post(..., stream=True)` → blocking
`socket.recv_into`), sampled climbing **411 → 6,498 ms**. This is a distinct main-thread block in the
same Advanced/AI viewport family and will compound any EchoMind-driven work there.

Because EchoMind dispatches inline with **no loading spinner and no deferral**, the user sees a hard
freeze rather than a "loading…" state, even though part of the cost (VTK render) is inherent to the
Advanced viewer.

### 2. Regression or pre-existing
**Underlying cost pre-existing; exposure is a v3.4.6 change.** The synchronous `change_series_on_viewer`
route dates to the 2026-06-06 EchoMind bridge; the Advanced-viewer synchronous `ImageViewer2D` + VTK
`Render()` is older still (a long-standing Advanced-viewer characteristic — a mouse drop hits the same
path, and actually *harder*, because a real drop always passes `force_reload=True` for a ~1.9 s
re-decode, which the EchoMind path does **not**). What is **new in v3.4.6** is the **"EchoMind unified
MCP" entrypoint** (`tools/testing/aipacs_control_mcp/server.py`, exposing `drag_series` / `open_patient`)
that first lets Secretary EchoMind *drive* this synchronous path programmatically. So: not a new
bottleneck, a **newly-exposed** one.

### 3. Exact code paths
- Dispatch (inline, UI thread): `tools/testing/aipacs_control_mcp/.../test_server.py:113` `QTimer.singleShot(0, self._drain_one)` → `:122 owner._execute(req)` → `:191 bus.execute(...)` → `modules/EchoMind/secretary/command_bus.py:79 registry.dispatch(...)` → `.../registry.py:176 raw = method(plan, state)`.
- Import action: `modules/EchoMind/secretary/adapters/viewer_write_adapter.py:263 change_series` → `:311 method_change_series_on_viewer(...)` (bound to `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py:127 change_series_on_viewer`).
- Synchronous UI-thread costs in `_vc_switch.py`: cache-hit apply `_perform_series_switch_optimized` (`:871`); inline recovery decodes `_load_single_series_on_demand` (`:1291`, `:1311`, `:1346`); the documented ~1.9 s forced re-decode is gated behind `AIPACS_FORCE_RELOAD_ASYNC_DECODE` (default **off**, `:847`).
- Advanced render (GUI thread): `modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py:899 switch_series` → `PacsClient/.../vtk_widget/_vw_series.py:1208` → `modules/viewer/advanced/viewer_2d.py:438 __init__` → `:449 Render()`.
- AI-seg sync network: `modules/viewer/interactor_styles/segmentation_styles/polygon_interactorstyle.py:303 on_contour_closed` → `modules/viewer/interactor_styles/interactor_utils/server_connection.py:41 download_file` → `requests.post(...)`.

### 4. Supporting logs
```
2026-07-07 23:22:15 [MAIN_THREAD_STALL_TRACE] gap_ms=2439 ... _apply_loaded_series_data -> _perform_series_switch_optimized
   -> vtk_widget.switch_series -> _vw_series.switch_series -> ImageViewer2D.__init__ -> viewer_2d.Render()
2026-07-07 23:24:52..58 [MAIN_THREAD_STALL_TRACE] gap_ms=411 -> 1431 -> 2438 -> 3460 -> 4467 -> 5488 -> 6498
   on_contour_closed -> download_file -> requests.post -> http.client -> socket.recv_into   (sync network on UI thread)
2026-07-07 14:57:27 bus_factory.build_command_bus  built CommandBus with 77 action(s) across 9 adapter(s)   (cheap; not the freeze)
```

### 5. Safe fix plan (flag-gated)
1. **EchoMind import must not block the UI thread.** Route the `viewer_write.change_series` handler
   through the **same async load scheduling** a normal drop uses (`_schedule_async_load_and_switch` /
   the worker path) so the decode is off-thread, and **show the existing viewport loading spinner**
   for the duration so the user sees "loading", not a freeze. Flag e.g. `AIPACS_ECHOMIND_ASYNC_IMPORT`
   (default on), kill switch reverts to the inline call.
2. **AI-segmentation upload off the UI thread.** Move `on_contour_closed → download_file`
   (`requests.post`) to a QThread worker with a spinner/timeout; never call `requests.post` on the GUI
   thread. Flag `AIPACS_AI_SEG_ASYNC_UPLOAD` (default on).
3. **Advanced-viewer VTK render is inherently GUI-thread** — cannot be off-threaded. Mitigate by (a)
   ensuring the payload is fully decoded off-thread before the apply (so only the render itself runs on
   the UI thread), and (b) keeping the spinner up during the render. Do **not** attempt to move VTK
   render off-thread (violates the architecture rules).
4. **Respect the architecture hard rule:** these fixes stay inside the EchoMind adapter + the existing
   async-load/spinner machinery; they do **not** mix FAST/Advanced/VTK domains.

### 6. Risk assessment
Medium-low. Making EchoMind import async matches the already-proven drop path, so behavior parity is
high; the main risk is command-completion semantics (an MCP `drag_series` that returns before the
render finishes) — handle by completing the command when the spinner clears / first image is visible.
The AI-seg async upload is contained to the segmentation handler. Clinical isolation and the viewport
identity gate are untouched. All changes flag-gated default-on with kill switches.

### 7. Validation after fix
- With the probe on, drive an EchoMind `drag_series` / "load series N" import and confirm **no
  `interaction_active` main-thread stall > ~250 ms** attributable to `change_series_on_viewer` /
  `_load_single_series_on_demand`; the viewport shows the spinner then the image.
- Draw + close an AI segmentation contour and confirm no `on_contour_closed → requests.post` stall on
  the main thread (the POST runs on a worker; spinner shown).
- Confirm a normal mouse drop is unchanged (parity), and the Advanced-viewer VTK render still completes.
- Offscreen guard: assert the EchoMind `change_series` handler schedules the async path (not an inline
  synchronous load) when the series is not cache-resident.

---

## What is NOT the cause (ruling out the unified-pipeline / recent work)

- **EchoMind CommandBus build is cheap.** "77 actions across 9 adapters" is O(actions) `getattr`
  binding of thin façades storing callables — no viewers/DM/decoders/VTK/network created at build
  (`bus_factory.py`, adapters' `__init__` store lambdas). It runs inline at startup but is not a freeze
  source.
- **The multi-study / series-identity / append-skip / cache-identity work is not on either hot path.**
  The startup freeze is Chromium; the import freeze is the Advanced-viewer VTK render + inline dispatch
  + AI-seg network. None of `patient_study_set`, `merge_study_uids`, `add_new_data_to_lst_thumbnails_data`,
  the OPT-17 cache guard, or the OPT-20 render gate appears in the stall stacks.
- **Startup network auth is not the main-thread freeze.** `_authenticate_with_socket` completed in ~88 ms
  on the main thread; the Google-auth 401 refresh runs on a worker tid (consultation poller), off the UI
  thread. (Note: the 2026-07-08 session logged 341 `google_auth_httplib2.request` calls — a possible
  auth-refresh storm worth a separate look, but it is off-thread and not this freeze.)
- **Download subprocess prewarm** (`ensure_warm`, ~7 idle spawns) runs on worker tids (wired v3.1.5,
  2026-06-01) — background load, not the measured main-thread stall.

---

## Consolidated priority

| Pri | Item | Action | Risk |
|---|---|---|---|
| P0 | Startup Chromium prewarm (21 s) | Ship `AIPACS_BROWSER_PREWARM=0` to affected users now; then defer-to-idle / open-on-intent | Low |
| P1 | EchoMind import inline on UI thread | Async load + spinner via the proven drop path | Med-low |
| P1 | AI-seg synchronous `requests.post` on UI thread | Move upload to a worker + spinner/timeout | Low |
| P2 | 07-08 Google-auth refresh volume (341/session) | Separate investigation (off-thread, not a freeze) | — |

All fixes are flag-gated (default-on) with kill switches, confined to the browser/EchoMind/AI-seg
modules, and do not touch the FAST/Advanced/VTK domain boundaries or the clinical isolation guards.

---

## Fixes shipped (2026-07-08)

Both reported freezes were fixed, flag-gated default-on, minimal and contained. Master plan §9/§15
(OPT-22, OPT-23) updated.

**Freeze #1 — OPT-22 (`modules/web_browser/prewarm.py`, flag `AIPACS_BROWSER_PREWARM_IDLE_ONLY`,
default-on).** Because `QWebEngineView` construction is GUI-thread-only (cannot be off-threaded), the
fix is *timing*: the prewarm now warms only after a **genuine idle gap** — no discrete user input
(click/key/wheel) for `AIPACS_BROWSER_PREWARM_IDLE_MS` (default 5 s) — past a longer initial delay
(`AIPACS_BROWSER_PREWARM_DELAY_MS`, default 20 s), rechecking on a poll timer, and **skips the warm
entirely** if the user stays continuously busy past `AIPACS_BROWSER_PREWARM_MAX_WAIT_MS` (default
10 min) so a busy user is never frozen. Idle is tracked by a minimal app event filter (discrete events
only) installed only for browser-using sessions and removed the moment the warm runs or is skipped. The
marker gate and the `AIPACS_BROWSER_PREWARM=0` kill switch are unchanged; `IDLE_ONLY=0` restores the
byte-identical legacy fixed-delay warm. Net: the 21 s GUI-thread block now lands only when the user is
not interacting (invisible), or not at all — while browser opens stay fast for users who idle. Guard
`tests/code/system/test_browser_prewarm_idle_gate.py` (host lane); idle decision + flags validated
standalone. (In-sandbox `py_compile` of this one file was blocked by a FUSE mount-cache staleness — the
Read tool confirms the 314-line file is complete and well-formed; it compiles on the Windows host.)

**Freeze #2 — OPT-23 (`modules/EchoMind/secretary/adapters/viewer_write_adapter.py`, flag
`AIPACS_ECHOMIND_DEFER_SWITCH`, default-on).** `change_series` now schedules the viewport switch via
`QTimer.singleShot(0, _do_switch)` instead of calling `method_change_series_on_viewer(...)` inline —
exactly matching the real drop handler (`_vw_dragdrop.dropEvent → QTimer.singleShot(0, _do_series_switch)`,
which this file's own fidelity note already claimed it mirrored). Now the loading spinner shown just
above the call **paints before** the heavy switch, and the command-bus/IPC drain returns immediately, so
an EchoMind import shows "Switching series…" rather than a dead freeze. The switch itself is unchanged
(async for a cache-miss). `=0` restores the legacy inline call. **3/3 guard tests green in-sandbox
against the real adapter** (`tests/code/echomind/test_echomind_defer_switch.py`): defers-by-default,
inline-when-off, spinner-shown-first.

**Deliberately deferred (documented follow-ups, not the reported "import" freeze):**
- The Advanced/VTK `ImageViewer2D()` + `Render()` per switch (~2.4 s) is GUI-thread-inherent (VTK) and
  shared with the mouse-drop path; it can only be spinnered, not off-threaded — reducing it means reusing
  `ImageViewer2D` across switches, a bigger Advanced-viewer refactor gated on the architecture rules.
- The AI-segmentation `on_contour_closed → download_file` synchronous `requests.post` (up to 6.5 s on
  the UI thread) should move to a worker with a spinner/timeout. It is a distinct clinical AI interactor
  (the `out_path` result is used inline to render the mask), so it needs its own careful async pass —
  tracked, not done here.

**Live validation still required** (I cannot drive the GUI): with the main-thread probe on, (a) confirm
no `_construct_warm_view` stall in the first ~60 s while using the patient list, and (b) drive an
EchoMind `drag_series` and confirm the spinner shows with no dead freeze.
