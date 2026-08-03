# Review — `satardavoodi/pacsClientV3` branch `satar` ("UI improvement")

**Reviewed:** 2026-08-02 · **Branch head:** `fb671ae9` · **Base:** `dd8a6d34` (v3.5.6) — *exactly your current local HEAD*
**Commits:** `ad46fe91 "ui improvment"` (2026-07-29), `fb671ae9 "ui 2"` (2026-08-01), both by satar davoodi
**Size:** 23 files · +2,624 / −979 · 5 new files (3 source, 2 test)

---

## Verdict

**Do not merge as-is. The UI work itself is good and mostly well-built — but two changes riding along with it are unsafe, and one makes a settings field unusable.**

The good news first, because it directly answers your main concern: **this branch is clean on threading.** I swept the entire diff:

| Risk you asked about | Result |
|---|---|
| New threads / workers / thread leaks | **None.** Zero `QThread`, `QThreadPool`, `QRunnable`, `threading.Thread` added |
| Blocking ops on the GUI thread | **None added.** No `time.sleep`, `processEvents`, `.wait()`, `.join()`, `requests`, raw `socket`, `subprocess`, `os.walk`, `listdir`, `disk_usage` |
| New DB / SQL access | **None.** The only DB touch is one `cleanup_connection_pools()` call |
| Duplicate workers | **None.** No worker is created twice |
| Unnecessary timers | **One** `QTimer.singleShot(0, …)` deferral — benign, not a repeating timer |
| Repeated signal connections | **None found.** Connects stay in `__init__`/`setup_ui`, not in refresh paths |
| Viewer / VTK / MPR / thumbnail / download pipelines | **Untouched.** No FAST-mode or VTK rule violated |

The real problems are **not** performance. They are **data integrity, shutdown integrity, and one usability regression.** Details below, each verified by me against the actual code (not inferred from the diff).

---

## What the branch actually does

1. **New shared style library** `PacsClient/utils/login_form_styles.py` (1,107 lines) — composite field widgets (`LoginLineField`, `LoginComboField`, `LoginDateField`, `LoginNumberField`) that replace raw `QLineEdit`/`QComboBox`/`QDateEdit`/`QSpinBox` across login, patient search, data-access panel and server settings. This removes ~900 lines of copy-pasted QSS. **Architecturally this is a genuine win.**
2. **New title-bar account menu** `PacsClient/pacs/workstation_ui/user_account_menu.py` — replaces the direct account-popup pill with a dropdown (Account / Settings / Internal Assignments / Connected Accounts).
3. **Redesigned** patient search widget, data access panel, server settings dialog, account popup, login form.
4. **Exit confirmation dialog** on closing the main window.
5. **Disk-alert improvements** — "Don't show again" persistence + `AIPACS_DISK_SPACE_ALERT=0` kill switch. *Cleanly built.*
6. **Runtime server/profile switching** — new `modules/network/runtime_server_refresh.py`, replacing the previous "restart required" behaviour.
7. Notification UI strings changed **Persian → English**.
8. Colleague's local server config committed by accident.

Items 6, 4, 7 and 8 are the ones that are not really "UI".

---

## Findings

### 🔴 BLOCKER 1 — Runtime centre switch splits clinical data across two centres

**Files:** `PacsClient/utils/data_paths.py:290` (`reload_active_profile_paths`), `:277` (`_sync_config_path_exports`), `modules/network/runtime_server_refresh.py:26-44`, `PacsClient/app_handler.py` (`_show_server_settings`), `modules/network/server_settings_dialog.py:578`

**What changed.** In the base, `ServerSettingsDialog.save_settings` ended with `# self.accept()` — *commented out* (base line 538). That made the `if dialog.exec() == QDialog.Accepted:` branch in `app_handler` unreachable dead code. The branch **un-comments it** (`:578`), which brings that branch to life, and fills it with a new call to `apply_saved_server_settings_runtime(profile_switched=True)`.

That function rebinds the clinical path globals to the newly-selected centre and calls `cleanup_connection_pools()`.

**Why it breaks.** `reload_active_profile_paths()` reassigns *module attributes*:

```python
cfg.SOURCE_PATH     = DICOM_IMAGES_DIR
cfg.ATTACHMENT_PATH = ATTACHMENTS_DIR
cfg.THUMBNAIL_PATH  = THUMBNAILS_DIR
```

But **33 production modules bind those names by value at import time** (verified count):

```
modules/network/zeta_adapter.py:24                      SOURCE_PATH      ← download output dir
modules/download_manager/download/executor.py:21        THUMBNAIL_PATH   ← thumbnail writes
modules/network/upload_download_attchments.py:11        ATTACHMENT_PATH
PacsClient/.../home_ui/home_db_service.py:30            SOURCE_PATH
PacsClient/.../home_ui/home_download_service.py:24      SOURCE_PATH
PacsClient/.../home_ui/home_search_service.py:23        SOURCE_PATH
PacsClient/.../home_ui/patient_table_widget.py:18       SOURCE_PATH, ATTACHMENT_PATH
PacsClient/pacs/patient_tab/utils/utils.py:16           all three
modules/storage/sync_manifest.py:31, patient_cleanup_manager.py:19
… and 24 more
```

All of them are already imported **before the login screen exists** — the chain is `main.py:642 → app_handler.py:24 → mainwindow_ui.py:10 → AIPacs_ui.py:19 → home_ui/__init__ → home_db_service.py:30`. Rebinding the attribute afterwards cannot reach them.

**Meanwhile the database *does* follow the switch**, because `database/_pool.py:271` resolves `DATABASE_FILE` with an *in-function* import, and the branch explicitly drops the pool so the next connection opens the new centre's `dicom.db`.

**Net effect: rows go to centre B's database; DICOM files, thumbnails and attachments go to centre A's folders.** Studies then "don't display" (the reader looks in B, the pixels are in A), and centre A's tree silently accumulates another centre's patient images. That is exactly the collision the `servers/<slug>` layout exists to prevent.

**This is live on your machine, not theoretical.** I checked: `config/server_profiles.json` has `"enabled": true`, `active_profile_id: razi`, profiles `razi` + `mehr` — and **`user_data\servers\mehr\` already exists on disk** alongside `user_data\patients\`. Both roots are real.

The base handled this correctly and deliberately: it showed *"AI-PACS will now close — please reopen it to load this center's data and connection"* and called `QApplication.quit()`. The base docstring even states the reason: *"data root + socket resolve at startup"*.

**Fix (minimal, safe):** keep `apply_saved_server_settings_runtime` for the **same-profile** host/port/timeout case — that part is a real improvement — and restore the restart for `profile_switched=True`. A true hot-switch is possible later, but it first requires converting all 33 by-value imports to attribute access (`from PacsClient.utils import config` → `config.SOURCE_PATH`), guarded by a test that forbids module-level imports of those names. That is a separate, test-gated project — not a login-screen feature.

> Note: this is the same defect class already recorded in your CLAUDE.md for voice-to-text — *"built at import time and imported by value, so reassigning `AI_BASE` changed nothing."*

---

### 🔴 BLOCKER 2 — Exit-confirmation modal in `closeEvent` with no programmatic bypass

**File:** `PacsClient/pacs/workstation_ui/mainwindow_ui.py:1362-1391`

```python
def closeEvent(self, event):
    if not getattr(self, "_exit_confirmed", False):
        if not self._confirm_application_exit():   # modal QMessageBox.exec()
            event.ignore()
            return
        self._exit_confirmed = True
```

`_exit_confirmed` has **exactly one writer — this line**. There is no bypass, no `event.spontaneous()` check, and no env kill switch (which breaks your house rule that behavioural changes ship flag-gated with a byte-identical legacy path).

**Correction to a claim you may see elsewhere:** the single-instance takeover is **not** broken in the normal case. `single_instance_lock._initiate_shutdown` uses `QTimer.singleShot(0, app.quit)`, and `QApplication::quit()` does *not* deliver `closeEvent`. I verified this. The real exposure is narrower but still real:

1. **Windows logoff / shutdown / "End task"** deliver a close event → an unattended modal dialog blocks the shutdown.
2. **Takeover arriving while the dialog is open** — `app.quit()` cannot unwind a nested modal loop, so the 8-second `os._exit(0)` failsafe fires. Its own comment says exactly this: *"a modal dialog or stuck teardown must not block the takeover forever."* `os._exit(0)` skips `main.py`'s `finally`: no `terminate_all_download_subprocesses()`, no DB WAL checkpoint, no clean lock release. Orphaned download subprocesses are a leak you have already fixed twice.
3. **Most important:** your own uncommitted diagnostic in this very function records that *"a live session showed `spontaneous=False` with no attribution"* — i.e. **something in production is closing this window programmatically and you don't yet know what.** If that path exists, this dialog will intercept it and pop a modal prompt at a moment nobody expects one.

**Fix:** skip the prompt when `not event.spontaneous()`; set `_exit_confirmed = True` from `single_instance_lock._initiate_shutdown()` and any programmatic close path; gate the whole feature behind `AIPACS_CONFIRM_EXIT` with the legacy path intact.
**You already have the signal for this** — see "Conflict with your uncommitted work" below.

---

### 🟠 HIGH 3 — Port and Connection Timeout can no longer be typed

**Files:** `PacsClient/utils/login_form_styles.py:227-323` (`LoginNumberField`), used at `modules/network/server_settings_dialog.py:423` and `:437`

I read the whole class. The value is rendered in a **`QLabel`**. There is no `QLineEdit`, no `keyPressEvent`, no validator, no `setAutoRepeat` on the steppers. The only inputs are `_step_up`/`_step_down` (**±1**) and `wheelEvent` (**±1**). Range is 1–65535.

**Changing the socket port from 50052 to 104 requires ~49,948 clicks.** Timeout 30 → 120 s is 90 clicks. The base was a `QSpinBox` — type the number.

This also contradicts your existing guard that Host / Port / AE Title / Connection Timeout must be *real editable inputs* (they used to be a read-only hint label, and that was fixed deliberately).

**Fix:** back `LoginNumberField` with a `QLineEdit` + `QIntValidator`, keeping the styled shell and chevrons. `configure_login_spinbox(QSpinBox)` already exists unused at `login_form_styles.py:1103` if you prefer to revert those two fields.

---

### 🟠 HIGH 4 — Plugin mirror drift → the release gate will fail

`modules/cloud_consultation/ui/account_hook.py:44` was edited in core, but its payload copy under `builder/plugin package/packages/consultation/payload/…` was **not** synced. (`account_popup.py` *was* synced — this is a partial sync.) I diffed the pairs directly and confirmed the drift.

`builder/release_gate.py` checks `plugin_mirrors — payload mirrors SHA-equal to canonical sources`. **The release build fails** unless `--skip-release-gate`.

**Fix:** `tools/dev/sync_plugin_mirrors.py`, then `verify_plugin_mirrors.py` (must report all pairs matching).

---

### 🟠 HIGH 5 — The new shared refresh helper reads a stale socket host

`modules/network/runtime_server_refresh.py:19-21` reads host/port from `get_socket_config()`. That singleton is seeded from the active profile **once, at creation**. On a *profile switch* nothing re-seeds it, so the helper pushes the **previous** centre's host into the live patient service.

Today the login-gear path escapes this only by accident — `save_settings` happens to write `socket_host` first. The helper's contract is still wrong, and it is now shared code.

**Fix:** when `profile_switched`, re-seed from the profile (`socket_config._seed_from_active_profile(config)` / `get_active_profile()`) instead of reading the stale singleton.

---

### 🟠 HIGH 6 — "Live update after connecting an account" is now a silent no-op

`mainwindow_ui.py:872-877` swaps `attach_account_popup` → `attach_user_account_menu`. `attach_account_popup` now has **zero callers**, so its registrations (`app._aipacs_account_pill`, `app._aipacs_account_auth_user`, `container._account_popup_open`) never happen.

`refresh_account_area_after_connect` (still called after a successful Google connect) starts with `getattr(app, _ACCOUNT_PILL_ATTR, None)` → now always `None` → **returns immediately**. Consequences:

- the pill badge is not force-refreshed (stale for up to 90 s), and
- **`ensure_consultation_poller` is never re-armed for the new identity** — it now runs only once, at title-bar construction, when no identity was linked yet. Consultations silently stop being polled until restart.

Also `_attach_identity_extras` (`user_account_menu.py:110-125`) wraps the badge attach *and* the poller start in **one** `try` — a badge failure now also prevents the poller from starting. Everything is swallowed at `logger.debug`.

**Fix:** re-register the two app attributes and `_account_popup_open` in `attach_user_account_menu`, split the try blocks, and restore the `QEvent.Resize → _position_pill_badge` branch (the pill is now elastic, so the badge no longer follows it).

---

### 🟠 HIGH 7 — Five committed guard-test assertions are now red

`tests/code/system/test_titlebar_userinfo_clamp_guard.py` pins `setMaximumHeight(`, `QSizePolicy.Fixed`, `setMinimumHeight(70)` — satar uses `setMaximumWidth(168)`, `QSizePolicy.Expanding`, `setMinimumHeight(48)`.
`tests/code/ui_services/test_login_server_picker.py` pins `"QComboBox" in src`, `self.port_input = QSpinBox()`, `self.timeout_input = QSpinBox()` — all now false.

The branch updated its own `test_patient_search_improvements.py` but left these. Your rule is *"the suite is GREEN by default; any red = a real regression."*

**Fix:** update both guards to pin the *new* invariants, with the rationale recorded.

---

### 🟠 HIGH 8 — The login gear creates server profiles outside the single authority

`server_settings_dialog.py:193` (`_prompt_add_server`) mints an id and calls `sp.upsert_profile()` + `sp.write_profile_to_servers_json()` **directly**, bypassing `save_to_json` → `_sync_server_profiles` → `reconcile_profiles`. Your own code states the rule verbatim (`settings_ui/server_settings.py:1121`):

> **SINGLE AUTHORITY (2026-07-13).** Every mutation in this screen — add, edit, rename, DELETE — funnels through `save_to_json` … reconciling here (**and ONLY here**).

Consequences: the new profile ships `modules={}` (every per-centre endpoint unset — `ai_breast`, `ai_boneage`, `ai_segmentation`, `reception_api`, `pacs_http`, …), `dicom_port` is hard-coded 104 while your razi profile uses 105, and there are now two different id-minting rules.

**Fix:** route the gear's add through the same authority, or restrict the gear to *selecting* an existing centre.

---

### 🟡 MEDIUM

| # | Finding | File |
|---|---|---|
| 9 | **Stylesheet churn in the startup path.** `setStyleSheet` calls go +39/−13 across the diff. In `_apply_field_styling` the per-pass count goes 15 → 28, and both it and `_apply_date_field_styling` are called **outside** the OPT-01 theme-dedup guard, so construction runs 3 passes: **45 → 84 calls** (+87%). This is the exact function OPT-01 blamed for a measured 2.3 s startup freeze. `data_access_panel.apply_theme` has **no** dedup guard at all. *Not measured in wall-clock — needs a `[STARTUP_STAGE]` timing run on Windows to quantify.* | `patient_search_widget.py:413,464`; `data_access_panel.py:557` |
| 10 | **`QGraphicsDropShadowEffect` on a top-level `Qt.Tool` window with no `WA_TranslucentBackground`.** Forces the whole popup subtree into an offscreen image + 28 px blur on every repaint, and the shadow is clipped anyway — cost with no visual benefit. The popup repaints often (storage worker, refresh, mark-read). | `account_popup.py:159, 689-698` |
| 11 | **Title bar loses drag zones.** Two new widgets (`title_bar_right`, `window_buttons_host`) cover the top-right region but are not in `drag_surfaces`, and the hit test uses `w is surface`. You can no longer drag the window from there. The existing drag-surface test still passes, so this regresses silently. | `mainwindow_ui.py:715, 769-787` |
| 12 | **Persian → English UI strings** in internal assignments: notification title/body, window title, "Mark all read", "No notifications". The title/body are **persisted**, so old rows stay Persian and new ones are English — a mixed-language list. **Product decision — needs your sign-off, not a silent merge.** | `ino_notifications.py:267-268, 414, 423-433` |
| 13 | **Colleague's environment committed.** `servers.json`, `socket_config.json`, `server_profiles.json`: razi host `192.168.2.222` → `81.16.117.196` (while that profile's `ai_breast`/`ai_boneage`/`ai_segmentation` still point at `192.168.2.222` — inconsistent). `generated-files/runtime_profile.json` carries only regenerated timestamps. Shipped installs are protected by `builder/config_sanitizer.py`, but **every teammate running the source build silently retargets their PACS.** | `config/*.json` |
| 14 | **Core reaches into plugins' private API** — `from …account_hook import _attach_pill_badge` and `from …account_menu_hook import _open_identity_panel`. Both leading-underscore, both across a plugin-mirrored boundary, both swallowed at `logger.debug`, so a rename in the payload silently removes the badge and the Connected-Accounts action. | `user_account_menu.py:117, 301` |
| 15 | **`runtime_server_refresh` uses private globals and refreshes only one consumer** — `getattr(sps, "_socket_patient_service", None)` instead of the canonical `get_socket_patient_service()` (which already does the OPT-24c change-aware reload); imports from private `database._pool` although `database.core` re-exports it. It refreshes only the patient service — `socket_report_status_service` and the download-manager clients keep the old target. | `runtime_server_refresh.py:40, 49` |
| 16 | **New synchronous file I/O inside a repeating timer slot** — `check_now()` now reads and JSON-parses the prefs file every 5 minutes. Tiny, but cache it in the service and invalidate on write. | `disk_alert_service.py:137` |
| 17 | **First-run server flow changed** — the combo is now gated on `_profiles_enabled` rather than "profiles is non-empty", removing the free-text host fallback that existed *"otherwise a new centre could never add its first server."* The "+ Add Server…" flow restores the capability but has no fallback if it errors, and with zero profiles the marker is the only item, so re-selecting it emits nothing and the dialog dead-ends. | `server_settings_dialog.py:145, 194, 407` |

### ⚪ LOW

- One `QMessageBox` leaks per cancelled exit (parented, so C++ keeps it) — add `WA_DeleteOnClose`. `mainwindow_ui.py:1363`
- `LoginNumberField.wheelEvent` accepts unconditionally → an accidental scroll silently changes Port. Gate on `hasFocus()`. `login_form_styles.py:317`
- `_toggle` has no pending-open guard — two fast presses create two popups. `user_account_menu.py:79`
- Segment buttons are `setCheckable(True)` but a re-click returns early, leaving Qt's checked state desynced (harmless only because no `:checked` QSS rule exists yet). `data_access_panel.py:187`
- `LoginComboField` forwards only 9 methods; `setItemData`, `insertItem`, `removeItem`, `setEditable`, `model()`, `view()` are absent, and `isinstance(x, QComboBox)` is now `False` for 8 fields — fine today, a trap for future generic sweeps.
- Duplicated `if hasattr(self, "refresh_local_button")` block. `data_access_panel.py:568, 615`
- `attach_account_popup` / `attach_identity_account_menu` are now dead public API shipped in two mirrored payloads, with docstrings that are no longer true.

---

## What is genuinely good — keep all of it

- **`login_form_styles.py` is a real de-duplication win** — ~900 lines of copy-pasted QSS collapsed into one shared module. This is the kind of shared component your architecture asks for.
- **The wrapper widgets are drop-in compatible.** An attribute sweep across every call site found **no missing method** — no latent `AttributeError`. `blockSignals` on `LoginComboField` works correctly (signals are forwarded via the wrapper's own `emit`).
- **No public contract broken.** `data_access_panel.get_result()` still returns `"Local"/"Server"/"Import"`, so the Advanced-Search routing authority is intact; the EchoMind `home_widget_adapter` index mapping still matches tab order.
- **Server enumeration still goes through the canonical helpers** (`get_all_selectable_servers` / `get_selectable_server`) — no re-implemented lookup or connectivity probe.
- **`disk_alert_service` is well-built** — env kill switch, atomic `.tmp` → `os.replace` write, never raises, idiomatic prefs location. Its new test is the one genuinely behavioural test in the branch.
- **`config/server_profiles.json`'s `pacs_http` key is the JSON catching up to existing code**, not a schema change — `server_profiles.py:77` already has it. Keep it.
- **`returnPressed` on patient-name and study-ID** now triggers search (base only wired patient-ID). Nice additive fix.
- No base tests break other than the two guard files in HIGH 7.

**On `test_patient_search_improvements.py`:** partially weakened, but *not* to hide a regression. The deleted assertions (`QDateEdit::down-arrow`, `width: 30px`) pinned a widget class that no longer exists; the two behavioural guarantees (calendar popup, Saturday first-day) are kept and genuinely honoured. Two caveats: `assert field.calendarPopup() is True` is now **vacuous** (the wrapper hard-codes `return True`), and the icon-alignment invariant from the 2026-06-06 fix is no longer guarded (it still holds by construction via `_ICON_RAIL_W = 34`).

---

## Conflict with your uncommitted work

Your tree has ~90 modified files. Only three are also touched by this branch, and after normalising line endings (your working copy is CRLF, the repo is LF) the picture is small:

| File | Your uncommitted delta | Branch delta | Conflict |
|---|---|---|---|
| `main.py` | 45 lines | 15 lines | **none** — auto-merges |
| `generated-files/runtime_profile.json` | timestamps | timestamps | excluded anyway |
| `mainwindow_ui.py` | 38 lines | 225 lines | **1 hunk** |

**The single conflict is worth reading closely.** Both changes land on the first line of `closeEvent`. Yours (dated 2026-08-01) is the `[SHUTDOWN-INITIATOR]` diagnostic you added to chase "the app just closed by itself" — it logs `event.spontaneous()` and, when the close is programmatic, dumps the call stack.

The two are trivially co-mergeable (diagnostic first, then the confirm). More usefully: **your diagnostic already computes exactly the signal that fixes BLOCKER 2.** The correct merged shape is

```python
def closeEvent(self, event):
    <your [SHUTDOWN-INITIATOR] block — computes _spont>
    if _spont and not getattr(self, "_exit_confirmed", False):   # ← only ask on a user-initiated close
        if not self._confirm_application_exit():
            event.ignore()
            return
        self._exit_confirmed = True
    <existing lifecycle shutdown>
```

And your diagnostic's own note — *"a live session showed spontaneous=False with no attribution"* — is the argument for why that guard is not optional.

---

## Proposed integration plan

Nothing has been written to your codebase. This is the sequence I'd run on your approval.

**Stage 0 — safety**
1. `git fetch satar satar` into your local repo (the remote is already configured as `satar`).
2. Create `integrate/satar-ui` from `dd8a6d34`. Your dirty working tree stays untouched.

**Stage 1 — land the clean parts (no behaviour risk)**
3. Cherry-pick both commits onto the branch, then immediately revert out of the working set:
   - `config/servers.json`, `config/socket_config.json`, the `host` field in `config/server_profiles.json`, `generated-files/runtime_profile.json` — **keep** the `pacs_http: null` keys.
4. Run `tools/dev/sync_plugin_mirrors.py` + `verify_plugin_mirrors.py` until all pairs match.

**Stage 2 — required fixes before it can run (BLOCKERs)**
5. **B1:** restore the restart for `profile_switched=True`; keep runtime apply for same-profile host/port edits only. Re-seed the socket config from the profile (fixes HIGH 5 at the same time).
6. **B2:** merge your `[SHUTDOWN-INITIATOR]` block first, then gate the confirm on `event.spontaneous()`, set `_exit_confirmed` from `single_instance_lock._initiate_shutdown()`, and put the whole feature behind `AIPACS_CONFIRM_EXIT`.

**Stage 3 — usability + correctness (HIGHs)**
7. `LoginNumberField` → `QLineEdit` + `QIntValidator` inside the styled shell; keep the chevrons.
8. Re-register `_aipacs_account_pill` / `_aipacs_account_auth_user` / `_account_popup_open` in `attach_user_account_menu`; split the try blocks; restore the resize→reposition branch.
9. Route the gear's "+ Add Server" through `save_to_json`.
10. Update the two guard tests to the new invariants.

**Stage 4 — optimisation pass (this is where the UI work gets *better*, not just accepted)**
11. Extend the OPT-01 theme-dedup guard to `_apply_field_styling` / `_apply_date_field_styling` so construction collapses 3 passes → 1; hoist theme-independent widget setup (icon creation, fixed sizes, cursor, focus policy) out of `apply_theme` into `__init__`. Add a dedup guard to `data_access_panel.apply_theme`.
12. Drop `_apply_shadow()` from `AccountPopup`.
13. Add `title_bar_right` + `window_buttons_host` to `drag_surfaces`.
14. Cache the disk-alert prefs in the service; add `WA_DeleteOnClose` to the exit box; add the `_toggle` pending guard.
15. Point `runtime_server_refresh` at `get_socket_patient_service()` and `database.core`; extend it to the other live socket consumers.

**Stage 5 — verification gate**
16. `py_compile` all changed files on the Windows venv (**not** through the sandbox mount — it serves stale copies).
17. `pytest tests/code` — full fast lane, must be green, including the two updated guards.
18. `verify_plugin_mirrors.py` → all pairs match.
19. GUI smoke on your machine, on the large monitor: startup timing with `[STARTUP_STAGE]` (compare against your current build to confirm the stylesheet fix), login → gear → change port by typing → save, patient search across multiple patients and studies, thumbnails, open a study, title-bar drag from all regions, account menu + internal assignments, disk alert, and close (confirm appears on Alt+F4, does **not** appear on a second-instance launch).
20. Only then merge `integrate/satar-ui` into `beta-version`.

**Decisions I need from you (Stage 0):**
- **Persian → English notification strings** — accept, revert, or make it follow the app language setting?
- **The exit confirmation** — do you want this feature at all? It is the source of BLOCKER 2, and it is easy to simply drop.
- **Runtime centre switching** — accept the restart as the fix for now (recommended), or schedule the 33-import conversion as its own work item?

---

*Reviewed against base `dd8a6d34`. Every finding above was verified by reading the referenced code in both trees; the diff alone was not treated as sufficient evidence. Where a claim could not be measured (startup wall-clock in finding 9), that is stated explicitly.*
