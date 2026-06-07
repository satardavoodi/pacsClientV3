# Other-PC crash analysis — two crash-and-close events (2026-06-07)

**Logs:** `C:\Users\Dr.Alizadeh\Desktop\log on other pc` (source build, v3.2.x
vintages) · **Fix commit:** `051aa95` · **Related:** dump pair in
`native_fault.log` (created 06-02, both dumps from 06-07).

## Process timeline (06-07, from app.log pids)

| pid | ran | end |
|---|---|---|
| 9184 | 06-05 22:55 → 09:02:48 | **CRASH 1** — AV during shutdown teardown |
| 52528 | 09:09 → 09:17 | short session, no fault dump (clean exit) |
| 26524 | 09:25 → 10:49:50 | **CRASH 2** — AV on theme-preview click |
| 55728 | ~10:53 → ? | theme click again → **NameError** (excepthook CRITICAL, not an AV) |
| 57208 | 11:48 → 14:23+ | still running when logs were copied |

## Crash 2 — 10:49:51, access violation on theme click (fixed/mitigated)

native_fault dump 2, current thread:
`_on_theme_preview_clicked → _apply_selected_theme → set_active_theme →
themeChanged.emit → main.py _apply_application_theme:1317 =
app.setStyleSheet(...)` → **AV inside Qt's global unpolish/repolish**.

The emit is synchronous, so the application-wide restyle ran **inside the
button-click dispatch** — and at 10:49:28 (22 s earlier) a patient open with
progressive load was still mutating viewer widgets. Repolishing the whole
widget tree from inside a click stack while native widget churn is in flight
is the same hazard family as the 0x8001010d input-synchronous crashes.

**Fix:** `main.py` now connects `themeChanged` to a deferred wrapper that
re-posts `_apply_application_theme` via `QTimer.singleShot(0, …)` — the global
repolish always runs on a clean event-loop turn, never inside emit/dispatch.

## The 10:53 follow-up — NameError on every theme change (hard bug, fixed)

```
CRITICAL aipacs.crash._aipacs_excepthook
  File "modules\download_manager\ui\widget\_dm_theming.py", line 21, in _on_app_theme_changed
    _dm_retint_widget_tree(self, self._app_theme)
NameError: name '_dm_retint_widget_tree' is not defined
```

Verified in OUR source too: the Phase-2 DM split copied PatientWidget's
`_on_app_theme_changed` pattern but **never created the DM retint helper** —
every theme change with the Download Manager widget alive raised. Fixed by
implementing `_dm_theme_color_map` / `_dm_retint_stylesheet` /
`_dm_retint_widget_tree` in `_dm_theming.py` (maps the DM v106 hardcoded
palette to live theme tokens; per-widget try/except + shiboken validity; the
handler itself can never raise). DM plugin mirror synced (308 pairs OK).

## Crash 1 — 09:02:48, AV during shutdown (documented, no code change)

pid 9184's last lines show the **orderly close path** (single-instance lock
release logged at 09:02:48.221) and dump 1's main thread sits at module level
in the final teardown region — between log-flush/subprocess-kill and
`os._exit(0)` — with one native (`<no Python frame>`) thread alive. The AV hit
in that last-millimetre window on the 06-05 vintage.

Data-safe by construction: lock release, DB WAL checkpoint, and log flush had
already completed. The current shutdown sequence (post 06-05/06-06 commits)
keeps that window minimal; a Python-side fix cannot catch a native AV there.
Action: monitor on v3.2.3+ — if it recurs on current code, capture a native
dump (WER/procdump) on that machine.

## Version-drift note
Dump 1 shows `disk_pixel_cache.py:268`, dump 2 shows `:294` for the same
function — the two crashes ran **different code vintages** (machine was
updated between). Keep the other PC on the current build; theme fixes land
with the next sync/build.

## Verification
`tests/code/download_manager/test_dm_theme_retint.py` — 6 green (helper
existence, hardcoded-color retint, None/empty-theme safety, handler
never-raises incl. missing-attribute path, main.py deferred-wiring source
guard). `verify_plugin_mirrors.py`: 308/308.
