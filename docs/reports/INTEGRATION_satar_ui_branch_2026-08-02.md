# Integration record — `satar` UI branch → `integrate/satar-ui`

**Date:** 2026-08-02 · **Base:** `dd8a6d34` (v3.5.6) · **Branch head:** `62e196e4`
**Source:** `satardavoodi/pacsClientV3` @ `satar` (`fb671ae9`)

## Where it is

| | |
|---|---|
| Branch | `integrate/satar-ui` (in your repo) |
| Worktree to test from | `E:\ai-pacs\ai-pacs codes\_integrate-satar-ui` |
| Bundle (backup) | `_recovery\satar-ui-integrated.bundle` |
| **Your `beta-version` tree** | **untouched — still 91 uncommitted files, nothing stashed or reverted** |

Open the worktree folder in VS Code and run `main.py` from there to smoke-test. It is a
real git worktree, so it shares the object store with your repo but has its own checkout.

Remove it when you're done: `git worktree remove "E:\ai-pacs\ai-pacs codes\_integrate-satar-ui"`

## Commits

```
62e196e4  perf: optimization pass on the redesigned UI
362375d3  fix(HIGH-6/HIGH-8, M1, M12): identity refresh, single-authority add-server,
          drag surfaces, Persian strings
9b4313c2  fix(HIGH-3/HIGH-7): make Port and Connection Timeout typeable; repair the two
          red guard tests
2daab257  fix(BLOCKER-2): gate the exit-confirmation dialog; never prompt on a
          programmatic close
79a4f3f1  fix(BLOCKER-1): a server-profile switch must RESTART, not rebind paths at runtime
73d39fef  integrate: drop the colleague's local env config; keep pacs_http schema keys;
          sync consultation plugin mirror
2f39d9f3  ui 2                 ← colleague, unmodified
87370c4f  ui improvment        ← colleague, unmodified
```

The two colleague commits are cherry-picked **verbatim**; every change of mine is a separate,
reviewable commit on top.

## Verification

| Lane | Result |
|---|---|
| **Windows venv** (authoritative) — `tests/code/{system,ui_services,network,storage}` | **1235 passed, 8 failed** |
| Same 8 failures re-run in **your own working tree** | **8 failed** — identical, pre-existing |
| Offscreen Linux lane, integration vs v3.5.6 baseline | failure sets **byte-identical**; **+29 passing tests** |
| `py_compile` on all 23 changed files | clean |
| `tools/dev/verify_plugin_mirrors.py` | **`[OK] 408 pair(s) match`** (was DRIFT) |

**Zero regressions on either lane.**

The 8 pre-existing failures are in files this branch never touches and are unrelated debt you
may want to look at separately:
`test_local_search_progressive.py` (4), `test_local_incremental_and_import_date.py` (3),
`test_report_assign_rendering.py::test_login_carries_the_user_identity_ids` (1).

## Decisions applied

| Decision | Outcome |
|---|---|
| Centre switching | **Restart required** — as you specified |
| Persian → English notification strings | **Reverted.** `ino_notifications.py` is now byte-identical to v3.5.6 |
| Colleague's server config | **Excluded.** `servers.json`, `socket_config.json`, `runtime_profile.json` reverted; only the `pacs_http: null` schema keys kept |
| Exit-confirm feature | **Kept, gated, default OFF** — reasoning below |

### Why the exit-confirm ships dark

You asked me to decide. I kept your colleague's feature rather than deleting it, but it is
behind `AIPACS_CONFIRM_EXIT` and **off by default**, for three reasons:

1. It opens a **nested modal event loop inside `closeEvent`**. That is the one place in the app
   where blocking has consequences beyond a slow dialog — the 8-second `os._exit(0)` failsafe in
   `single_instance_lock` skips `main.py`'s `finally` entirely (download-subprocess termination,
   DB WAL checkpoint, clean lock release).
2. Your own uncommitted `[SHUTDOWN-INITIATOR]` diagnostic records that a live session showed
   `spontaneous=False` **with no attribution** — something in production closes this window
   programmatically and you don't yet know what. Adding a modal dialog to that code path while
   the investigation is open would muddy the very signal you're collecting.
3. House rule: behavioural changes ship flag-gated with a byte-identical legacy path, and unverified
   ones default OFF until live-verified.

It is safe to enable — the `event.spontaneous()` guard means it can never intercept a programmatic
close. Set `AIPACS_CONFIRM_EXIT=1`, smoke-test it (checklist below), then flip the default in
`_should_confirm_exit` if you like it. That is a one-character change.

## What changed, by finding

**BLOCKER 1 — centre switch split clinical data.** `runtime_server_refresh` now returns
`RESTART_REQUIRED` for a profile switch and performs no path rebind; `app_handler` shows the
switch notice and quits cleanly through the event loop; `login_ui` restored to the base restart.
Same-profile host/port edits still apply live — the genuine improvement in the branch is kept.
`cleanup_connection_pools` now comes from the public `database.core`, not private `database._pool`.
`reload_active_profile_paths`'s docstring states the constraint so nobody re-enables it by accident.
Kill switch: `AIPACS_PROFILE_SWITCH_RESTART=0`.
New guard: `tests/code/network/test_profile_switch_requires_restart.py` (13 tests) — it also pins
the two structural facts the rule rests on, so if the 33 by-value importers ever get converted,
the test tells you to revisit the restart requirement deliberately rather than by accident.

**BLOCKER 2 — exit-confirm.** `_should_confirm_exit(event)` with three gates; `_exit_confirmed`
now set on every close so a second `closeEvent` in the same shutdown can't re-prompt;
`WA_DeleteOnClose` on the box (it was parented, so it outlived the Python local and leaked one
per cancelled exit). The branch's own test now tests the **bypass behaviourally**, not just the
dialog strings.

**HIGH 3 — Port/Timeout typeable.** `LoginNumberField`'s value is a `QLineEdit` + `QIntValidator`
inside the same styled shell. The suffix (`" s"`) is a separate trailing label so it can never end
up inside the editable text. Up/Down step like `QSpinBox`; steppers auto-repeat when held; the
wheel only steps a **focused** field and otherwise propagates, so a stray scroll over the form
can't silently change the port. Verified offscreen: typed `104` → 104, typed `99999` → clamped to
65535, empty/invalid → reverts.

**HIGH 4 — plugin mirror.** `account_hook.py` synced. Verifier back to `408 pair(s) match`, so
the release gate will pass.

**HIGH 6 — identity live-refresh.** `_register_account_pill` restores the three registrations
(`_aipacs_account_pill`, `_aipacs_account_auth_user`, `_account_popup_open`) that moved out of
`attach_account_popup`. Without them `refresh_account_area_after_connect` early-returned, so after
linking a Google identity the badge stayed stale **and the consultation poller was never re-armed**
— consultations silently stopped being polled until restart. Also: the badge/poller try blocks are
now separate (a badge failure no longer blocks the poller), the `Resize → reposition` branch is
back (the pill is elastic now), and `_toggle` can't queue two popups in one event-loop turn.

**HIGH 8 — single authority.** The gear's "+ Add Server" now reconciles through
`server_profiles.sync_profiles_with_servers` — the documented single authority every server-list
mutation must funnel through — and takes ports/AE title from the `ServerProfile` dataclass defaults
instead of a hard-coded `dicom_port=104` (your razi profile uses 105).

**M1 — title-bar drag.** `title_bar_right` and `window_buttons_host` added to `drag_surfaces`.
The hit test compares widget identity, so without them the window could no longer be dragged from
the whole top-right region — and the existing drag-surface test still passed, so it would have
regressed silently.

**Optimization pass.** Theme-signature dedup added to `_apply_field_styling`,
`_apply_date_field_styling` (both bypass `apply_theme`'s OPT-01 guard by being called directly from
`setup_ui` and `_create_search_fields`) and to `data_access_panel.apply_theme` (which had none at
all). Construction went from three full passes of an ~1.9× heavier styling body to one.
`QGraphicsDropShadowEffect` disabled on `AccountPopup` — it's a top-level `Qt.Tool` window with an
opaque background, so the shadow was clipped into its own edges while forcing the whole subtree
through an offscreen render + blur on every repaint (`AIPACS_ACCOUNT_POPUP_SHADOW=1` restores it).
Disk-alert prefs cached instead of stat+read+parse on every 5-minute GUI-thread tick. Segment
buttons no longer desync on a re-click.

**Guard tests repaired** (`test_titlebar_userinfo_clamp_guard`, `test_login_server_picker`) with
the rationale recorded in each, per house style — and in the login-picker case the weakened
`QSpinBox` pin was replaced by two **stronger** tests that pin the real requirement (typed input,
validator, key stepping, focused-only wheel) rather than a class name.

## Your uncommitted work — one conflict, and it's useful

Only three of your 91 modified files overlap with the branch. After normalising line endings
(your checkout is CRLF, the repo is LF — a naive diff makes the whole file look changed):

| File | Your delta | Branch delta | Conflict |
|---|---|---|---|
| `main.py` | 45 lines | 15 lines | none |
| `generated-files/runtime_profile.json` | timestamps | — | excluded |
| `mainwindow_ui.py` | 38 lines | 225 lines | **1 hunk** |

The conflict is at the first line of `closeEvent`. Your `[SHUTDOWN-INITIATOR]` diagnostic and my
confirm gate both insert there. Resolve it like this — your diagnostic first, then the gate:

```python
def closeEvent(self, event):
    # ── your [SHUTDOWN-INITIATOR] block, unchanged ──
    ...
    if self._should_confirm_exit(event):
        if not self._confirm_application_exit():
            event.ignore()
            return
    self._exit_confirmed = True
    # ── existing lifecycle shutdown ──
```

Both compute `event.spontaneous()` independently, so neither depends on the other.

## Smoke checklist (source build, from the worktree)

Run `main.py` from `_integrate-satar-ui` in VS Code — not the frozen exe, not the black taskbar
icon, one instance only.

1. **Startup timing** — compare `[STARTUP_STAGE]` against your current build. The stylesheet
   dedup should show up here; this is the one number I could not measure from the sandbox.
2. **Login gear → Port** — type `104` directly. Confirm it accepts typing, clamps out-of-range,
   and that Up/Down and hold-to-repeat work. Same for Connection Timeout (suffix ` s` outside the
   editable text).
3. **Centre switch** — gear → pick the other centre → Save. Expect the "AI-PACS will now close"
   notice and a clean exit. Reopen and confirm it comes up on the new centre with its own data root.
4. **Patient workflow** — search across several patients and studies, thumbnails, open a study,
   multi-study / previous exams. Nothing here was touched, so this is a no-change check.
5. **Title bar** — drag the window from the far top-right (over and beside the window buttons).
6. **Account menu** — pill → menu → Settings / Internal Assignments / Connected Accounts. Confirm
   the notification list is Persian again.
7. **Disk alert** — trigger it, tick "Don't show again", restart, confirm it stays suppressed.
8. **Close** — Alt+F4 should close directly (confirm is off by default). Then set
   `AIPACS_CONFIRM_EXIT=1` and check: the prompt appears on Alt+F4, and launching a **second**
   instance still takes over cleanly with no dialog and no 8-second stall.
9. **Full lane** — `.\run_test.ps1 -Fast` from the worktree.

## Merging

When the smoke test passes:

```
git switch beta-version          # (commit or stash your WIP first)
git merge integrate/satar-ui     # resolve the one closeEvent hunk as shown above
```

Then `tools/dev/verify_plugin_mirrors.py` once more and rebuild.
