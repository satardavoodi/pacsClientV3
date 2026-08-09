# Double-click on patient 53516 freezes the app — 2026-08-07 21:28 (IMP-3)

**Symptom.** Double-clicking patient 53516 in the patient list froze the whole
app for ~20 s (user report, live session pid 288604, app started 21:27:06).
The patient itself is fine — it opened normally once the freeze cleared.

## Evidence (user_data/logs, 2026-08-07)

| Time | Source | Event |
|---|---|---|
| 21:27:35.082 | app.log | `schedule_prewarm`: idle-gated (delay 20 s, idle gap 5 s, first-interaction required) |
| 21:27:57.085 | app.log | `_check_idle`: "idle 6062ms >= 5000ms after first interaction -> warming now" |
| 21:28:01.826 | app.log | `_warm_webengine_files`: 152.1 MB read off-thread → `construct.emit()` |
| **21:28:01.8–21:28:20.9** | viewer_diagnostics | **MAIN_THREAD_STALL 19 067 ms** — stack: `_on_construct → _construct_warm_view → view.setUrl(QUrl("about:blank"))` (`prewarm.py:492`) |
| 21:28:20.780 | app.log | "browser prewarm: Chromium engine warmed" |
| 21:28:21.812 | viewer_diagnostics | `_on_patient_double_clicked_async` finally runs — the 53516 open was queued behind the construct the whole time |
| 21:28:22–21:28:47 | viewer_diagnostics | residual 0.1–1.4 s stalls: normal patient-open pipeline (tab build, loading overlay, thumbnails) |

The stall sampler produced **no trace during the first ~11 s** of the block —
the GIL was held inside the native Chromium construct, which is why the freeze
reads as a hard hang.

## Root cause

The OPT-22 idle verdict goes **stale**. `_check_idle` approved the warm at
21:27:57 while the user was pausing before their next action; `kick()` then
spent ~4.7 s in its background phase (QtWebEngine DLL import + file warm),
and `_on_construct` fired on the GUI thread at 21:28:01.8 **without
re-checking input** — `_finish_watch` had even removed the input filter, so
the double-click during that window was invisible. The user's idle→act rhythm
makes this collision *systematic*, not unlucky: a 5 s pause is exactly what
precedes opening a patient. Third live occurrence of this construct blocking
a user action (2026-07-23 ~17 s, 2026-08-05 39.7 s under a modal, today 19 s).

Also confirmed: the 152 MB file pre-read did **not** shorten the construct
this session (19 s despite warm files) — cold-boot cost partially lives in
the `QtWebEngineProcess` spawn (AV-on-execute / Proxifier hook), so
collision-avoidance is the only reliable defense.

## Fix (IMP-3, `modules/web_browser/prewarm.py` only)

1. `_finish_watch(warm=True)` now **keeps the input filter installed** through
   `kick()`; it is removed only when the construct runs or is skipped.
2. `_on_construct` re-checks, at construct time, that the idle gap still
   holds: recent discrete input (< `idle_ms` ago) defers the construct via the
   existing IMP-1 poll/deadline machinery (bounded; skips the session's warm
   past the deadline, never forces a freeze).
3. Legacy fixed-delay path untouched (`_seen_input` False → veto inert).
4. "Chromium engine warmed" log line now includes the construct duration.

Kill switch: `AIPACS_BROWSER_PREWARM_RECENCY_VETO=0` (default on).

## Tests

`tests/code/web_browser/test_prewarm_recency_veto.py` — 13 new pins (recent
input defers; stale input constructs; legacy path inert; kill switch
reproduces the collision; filter lifetime through warm/give-up/construct/skip;
shared deadline; flag parsing; source pins).
Full run: `tests/code/web_browser` + `tests/code/system/test_browser_prewarm_idle_gate.py`
→ **72 passed** (all pre-existing OPT-22/IMP-1 pins green).

## Residual risk & open observations

* The ~19 s construct still exists; it can now only land after a ≥5 s quiet
  gap verified at construct time. A click landing *mid*-construct still waits
  it out — unavoidable while the warm strategy exists (Qt requires GUI-thread
  construction). Disable entirely with `AIPACS_BROWSER_PREWARM=0` if preferred.
* Requires app restart to take effect (running instance already warmed).
* Unrelated minor stalls seen today (candidates, no action taken): AI-chat
  module import ~0.5 s + typing-widget build ~0.8 s on open; thumbnail
  `_is_series_downloaded` `Path.stat()` on the GUI thread ~0.4 s at 21:30:00.
* A second idle `main.py` process (pid 224316, 0 CPU, started 21:27:05 —
  1 s before the app) never initialized fault logging; likely a launcher
  wrapper, worth confirming some quiet day.
* VS-1 (switch dedupe) and VS-2 (cv2/viewer prewarm) remain tracked as
  tasks #24/#25 — separate from this freeze.
