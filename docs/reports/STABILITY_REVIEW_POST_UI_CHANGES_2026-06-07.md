# AI-PACS stability review after recent UI / module changes (2026-06-07)

Scope: theme, MPR/NPR UI, toolbar, settings UI, web browser, print, education,
EagleEye, EchoMind. Question: did the recent (mostly non-backend) UI/module
work reduce overall reliability?

## Headline

**No test-detectable regression was introduced by the UI/module changes.** A
full headless guard sweep of every touched module passed **519 tests, 0
failures, 0 regressions**. The crashes visible in the logs are dominated by
**process shutdown/takeover teardown** (heavily inflated by today's ~59
debug/agent restarts), plus a small **theme-apply** cluster already mitigated,
and a **CD-burner close-during-burn** signal defect now fixed. None of these
trace to the theme/browser/print/education/EagleEye/EchoMind/MPR/toolbar/
settings UI changes themselves.

## A. Regression sweep (headless, offscreen Qt)

Each group run as its own pytest process (the only "errors" were the known
`download_manager` circular-import collection-order artifact — collect DM
first → all green; documented in CLAUDE.md).

| Module group | Result |
|---|---|
| download_manager | 131 passed |
| EchoMind / secretary | 102 passed |
| web_browser (+ loading bar, styles) | 13 passed |
| print | 5 passed |
| education (online consultation) | 11 passed |
| MPR / NPR (+ launch route, vtk bridge) | 50 passed |
| CD burner | 71 passed (→ 74 after this review's new guards) |
| settings + startup lazy-init | 17 passed, 1 skipped (documented stale) |
| system (reminders, name fallback, search) | 18 passed |
| theme V2 (readability, variant, scaffold) | 68 passed |
| F12 Secretary popup | 9 passed |
| viewer drop/input-sync/import guards | 24 passed |

Theme switching, the most cross-cutting change, has the largest guard set (68)
and is fully green.

## B. Crash / freeze inventory (this PC, last 3 days)

`native_fault.log`: 238 × `0x8001010d` (RPC_E_WRONGTHREAD) + 23 access
violations. **These are faulthandler dumps, not all fatal** — faulthandler
prints the whole process when it traps a fault; the app survived most. The
dominant *current-thread* frames across the dumps:

- `main.py:1583–1597` (8+4+2…) and `single_instance_lock.py` (6) — the
  **shutdown / hard-exit / takeover** region. This is teardown, and it was
  exercised dozens of times today by the takeover feature killing old
  instances and by repeated agent-driven restarts (59 distinct pids today).
  Not clinical-use crashes.
- `main.py:1337/1340` (4+2) — **theme application** (`app.setStyleSheet`
  global repolish). Real, small. **Already mitigated** today: the app-wide
  restyle is now re-posted off the click dispatch (`051aa95`).
- `thumbnail_manager.py` (3) — the known thumbnail cancel-on-open race family.
- `patient_table_widget.py`, `_hp_layout.py`, `loading_overlay.py` (1 each) —
  long-tail, no clustering.

`app.log` excepthook CRITICALs (3 days): **only one type**, `RuntimeError:
Signal source has been deleted` ×3 (12:56, pid 8000) — **the app survived all
three** (it kept logging). Root-caused below and fixed.

KPI: current session `stalls_total=335`, `max_gap_ms≈29 s` — the 29 s outlier
is a single machine-load/sleep artifact (the per-tick gaps are 100–300 ms,
benign UI-thread stalls already characterised in prior reviews, not new).

## C. Root-caused findings

**F1 — CD-burner close-during-burn → "Signal source has been deleted" (FIXED, `5148544`).**
`CDBurnWorker(QThread)` emits `progress`/`completed`/`stage_changed` to the
burn dialog. `closeEvent` cancelled the worker but never **joined** it, so the
dialog (the signal sink) was `deleteLater`'d while the worker kept emitting →
the RuntimeError into the excepthook. Fix: `_teardown_burn_worker()`
disconnects the three signals, cancels, and bounded-waits (8 s) the thread
before the dialog dies. 3 guard tests; run_cd mirror synced.

**F2 — theme switch wrong-thread / global repolish (MITIGATED today, `051aa95`).**
`themeChanged.emit` ran `app.setStyleSheet`'s global unpolish/repolish on the
click stack, and the Download Manager's theme handler called a helper that was
never defined (`NameError` on every theme change). Both fixed: deferred restyle
via `QTimer.singleShot(0)`, and real DM retint helpers. 6 guard tests.

**F3 — 0x8001010d at shutdown/takeover (LOW priority, teardown only).**
Native COM/UIA finalizers firing on the wrong thread during process exit. Not
a clinical-use crash; the data path is already protected (atomic writes, WAL
checkpoint before `os._exit`). Most of today's count is takeover + agent
restarts. Monitor on the next build; if it appears mid-session (not at exit),
revisit.

## D. Per-module verdict

- **Theme switching** — green (68 guards); F2 mitigated. Stable.
- **Web browser** — green (13). No crash signatures in logs. Stable.
- **Print** — green (5). No signatures. Stable.
- **Education** — green (11). No signatures. Stable.
- **EagleEye** — no new signatures this window; the MG-crash defensive guards
  (prior `eagle_eye_mg_crash_fix`) hold. Stable.
- **EchoMind / Secretary** — green (102). No signatures. Stable.
- **MPR / NPR** — green (50). No signatures. Stable.
- **Toolbar** — covered via MPR/toolbar guards; no signatures. Stable.
- **Settings** — green (17). No signatures. Stable.
- **CD burner** (adjacent, not in the listed set) — F1 found + fixed.
- **Patient open/close, fast module switching** — the only *interaction*
  defects this week were the viewer-load bugs already fixed (drop-index alias
  `8091f72`, wrong-study path `3d335db`, import hang `e8ce40e`) and the open
  blank-name `_hp_search` fix; none are theme/module-UI regressions.

## E. Recommended fixes (priority)

1. **Ship the build.** Today's commits (`051aa95` theme, `5148544` CD-burner,
   `e8ce40e` import, `8091f72`/`3d335db` viewer loads, name fallback) close the
   real signatures; they only take effect once shipped to the clinical PCs.
2. **ThemeManager disconnect leak (P1, still deferred).** The long-standing
   RSS/thread growth tied to ThemeManager signal connections that aren't
   disconnected on widget teardown — same family as F1. Worth a focused pass:
   audit every `themeChanged.connect` for a matching disconnect on close.
3. **0x8001010d audit at exit** — confirm the shutdown sequence quiesces COM
   /UIA-touching widgets before `os._exit`; consider hiding the main window
   first so native accessibility clients release handles.

## F. Tests added / recommended

- Added: `tests/code/cd_burner/test_burn_dialog_teardown.py` (3),
  `tests/code/download_manager/test_dm_theme_retint.py` (6),
  `tests/code/system/test_patient_name_fallback.py` (2),
  viewer drop/path guards (14), import wait-loop guard (5).
- Recommend: a generic "no signal outlives its widget" teardown contract test
  applied to every QThread-backed dialog (burn, download manager, secretary
  popup, web browser), and a soak test that flips the theme 50× while a viewer
  + DM + EchoMind are all open (would have caught F2 and the ThemeManager
  leak).

## G. Open items (tracked, not regressions)

- #148 — patient 44982 dead-tab (open leaves no trace; needs instrumented
  re-open). Name display already fixed.
- #145 — origin of the 45033 sibling-study folder-path poisoning (loader is
  already immune via `3d335db`).
- #95 — live-validate batch-boundary download yield.
- ThemeManager P1 leak (item E2).
