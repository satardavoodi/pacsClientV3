# Stability / Freeze / Connectivity investigation — laptop, 2026-07-13

**Evidence:** `C:\Users\Dr.Alizadeh\Desktop\log on other pc\laptop khodam\`
(`app.log` 7 990 lines, `download_diagnostics.log` 2 063, `viewer_diagnostics.log` 10 252,
`native_fault.log` 166, `db_diagnostics.log`).
**Machine:** `[RUNTIME_ARCH] process_arch=AMD64 native_arch=AMD64 emulated=False frozen=True
python=3.13.5 exe=AIPacs.exe cpu_id='Intel64 Family 6 Model 126'` — plain x64, **not** the WoA/ARM box.
Installed/frozen build (`C:\Program Files\AIPacs`), user `vahid`.
**Server:** profile `razi` → **81.16.117.196:50052** — a **remote server over the public internet**
(the dev machine talks to a LAN server; this is the single biggest environmental difference).

**Answer to the headline question: these are NOT one bug. There are TWO independent root causes
plus one reporting defect.** They interact — the network fault produces the failure storm, and the
storm is what exposes the crash — but they must be fixed separately.

| # | Symptom reported | Root cause | Confidence |
|---|---|---|---|
| A | Freeze / no results / "slow search" / everything fails after the internet blips | **Stale pooled socket handed out as healthy — no liveness check, no retry** (`modules/network/socket_client.py`) | **Proven from logs + code** |
| B | App closed unexpectedly / crashed several times | **Native access violation in `QTableWidget.setRowCount(0)`** inside `patient_table_widget.clear_table()`, driven from the async search while other timers mutate the same table | **Crash stack captured; mechanism strongly evidenced** |
| C | Sync Status: tab closes, THEN an error appears | **`_sync_worker` emits `sync_completed` even when the report-status update failed**; the queued `statusError` dialog arrives after the tab is gone | **Proven from logs + code** |

---

## 1. Sessions and what actually happened

`app.log` contains **three** main-app sessions (not eight — the extra `session start` lines in
`native_fault.log` are the *download subprocesses*, which re-exec `AIPacs.exe` and share the log):

| pid | start | end | how it ended |
|---|---|---|---|
| 1424 | 11:49:29 | 13:12:30 | **clean** (`Released single-instance lock`) — user restart |
| 7432 | 13:12:34 | 13:14:21 | **clean** — user restart |
| 21460 | 13:14:28 | **13:36:00.788** | **HARD CRASH — no shutdown line** |

Last line written by pid 21460:

```
13:36:00.788 | [SEARCH-PERF] search_ms=208 rows=5 probed=False params={'limit':100, ...}
```

The **very next statement** in `home_search_service.search_server` is
`home.patient_table_widget.clear_table()` (line 699) — and that is exactly where
`native_fault.log` says the process died.

---

## 2. Root cause A — stale pooled socket (the connectivity root cause)

### The evidence

`download_diagnostics.log`, every socket ERROR of the session (deduplicated):

```
11:58:30 ❌ send_request endpoint=UpdateReportStatus:            Invalid response length header
11:58:30    Update report status failed: No response
11:58:47 ❌ send_request endpoint=GetPatientReceptionHistory:    Invalid response length header
11:59:42 ❌ send_request endpoint=GetPatientList:                Invalid response length header
11:59:42 ❌ Patient list request failed: No response
11:59:53 ❌ send_request endpoint=GetPatientReceptionHistory:    [WinError 10053] An established
            connection was aborted by the software in your host machine
12:58:30 ❌ GetPatientList: Invalid response length header
12:58:32 ❌ GetPatientList: Invalid response length header      <- back-to-back = poisoned pool
13:00:58 ❌ GetPatientList: Invalid response length header
13:01:02 ❌ GetPatientReceptionHistory: Invalid response length header
13:08:10 ❌ GetPatientList: Invalid response length header
13:26:52 ❌ UpdateReportStatus: Invalid response length header  <- the Sync Status failure
13:27:00 ❌ GetPatientReceptionHistory + GetPatientList
13:29:03 ❌ GetPatientList: Invalid response length header
```

Matching `app.log` ERRORs: `❌ Search returned None` (×7) and
`Update failed - no response from server` (×2).

**There is not a single timeout in the whole log.** These are not "the network was slow" errors.

### Why "Invalid response length header" means a *dead pooled connection*

`modules/network/socket_client.py`:

```python
def is_connected(self) -> bool:
    return self.connected and self.socket is not None     # :173  ← a FLAG, never validated

def _recv_exact(self, size):
    nbytes = self.socket.recv_into(...)
    if not nbytes:
        return bytes(buf[:pos])                            # :187  ← EOF returns SHORT

def send_request(self, endpoint, params):
    if not self.connected or self.socket is None:          # :198  ← skipped, flag says "connected"
        if not self.connect(): return None
    ...
    self.socket.sendall(length_bytes); self.socket.sendall(request_bytes)   # succeeds into a dead socket
    response_length_bytes = self._recv_exact(4)
    if not response_length_bytes or len(...) != 4:
        raise Exception("Invalid response length header")  # :245  ← EOF lands HERE
    ...
    except Exception as e:
        self.connected = False; self.socket.close(); self.socket = None
        return None                                        # :326-335  ← NO RETRY
```

and the pool:

```python
class SocketConnectionPool:                                # :851
    def get_connection(self):
        while self.connections:
            client = self.connections.pop()
            if client.is_connected():                      # :872  ← trusts the stale FLAG
                return client
    def return_connection(self, client):
        if len(self.connections) < self.pool_size:
            self.connections.append(client)                # :887  ← returned unconditionally,
                                                           #        even after a failed request
```

**The sequence:**

1. A pooled `PatientListSocketClient` sits idle. Over the public internet the server / NAT /
   firewall closes it (or a brief internet drop kills it). Nothing tells the client — TCP half-open.
2. `is_connected()` still returns `True` (it only reads `self.connected`), so the pool hands the
   dead client to the next caller and `send_request` **skips its reconnect branch**.
3. `sendall()` succeeds (the bytes go into the kernel buffer). The following `recv` returns **EOF**.
4. → `Invalid response length header` → `return None` → **no retry** → the caller reports
   `Search returned None` / `Update failed - no response from server`.
5. The failure is user-visible even though *one reconnect would have worked* — and it recurs
   (12:58:30 and 12:58:32) because more than one stale client is in the pool.

This is why the problem shows up on **this** PC and not in the lab: the LAN server never idles a
connection out, the internet path does. It also explains why the app "never really recovers after
the internet comes back" — the poison is in the pool, not in the network.

### Why the download engine survives while the patient list does not

There are **two different socket clients**:

* `modules/download_manager/network/socket_client.py` — used by the DM. Has
  `REQUEST_MAX_RETRIES=3`, `connect_with_retry`, `RECONNECT_MAX_RETRIES=5`. It **rides out** the
  same fault (the log shows GetSeriesImages still succeeding at 13:37 with 4.4 s / 5.7 s RTTs).
* `modules/network/socket_client.py` — used by **patient list, report status, reception history
  (Previous Exams)**. **Zero retries, flag-only health check.** Every UI-facing server call is on the
  fragile path.

That asymmetry *is* the bug.

---

## 3. Root cause B — the crash (native access violation)

`native_fault.log`, current thread (Qt main thread):

```
Windows fatal exception: access violation

Current thread 0x000040fc (most recent call first):
  patient_table_widget.py, line 5310 in clear_table            <-  self.results_table.setRowCount(0)
  home_search_service.py, line 699 in search_server            <-  home.patient_table_widget.clear_table()
  _hp_search.py, line 435 in search_patients_from_server_async
  asyncio/events.py, line 89 in _run
  qasync/__init__.py, line 307 in timerEvent
  main.py, line 801 in notify
  main.py, line 801 in notify                                  <-  nested dispatch
  qasync/__init__.py, line 404 in run_forever
  main.py, line 1339 in <module>
```

State at the moment of death (from `app.log`, pid 21460):

* A **download was live** — `[LIFECYCLE-SHADOW] grow_lane_drop ... on_disk=292/420` still ticking
  seconds earlier.
* The previous search had put **45 rows** in the table; the new one returned **5**.
* Each row carries **up to 4 `setCellWidget` widgets** (select / status / report / assign) →
  `setRowCount(0)` destroys ~180 child widgets synchronously.

### Why it blows up

`clear_table()` (`patient_table_widget.py:5286`) does a bare `setRowCount(0)` with **no re-entrancy
guard and no coordination with the other things that are mutating the same `QTableWidget` from the
same event loop**:

1. **`_refresh_statuses_chunked`** (`:3134`) — a self-rescheduling `QTimer.singleShot(0, ...)` chain
   that walks rows calling `update_study_download_status()` → `setCellWidget(row, status_col, …)`
   (`:3018`). Its only guard is a token against a *newer refresh* — **nothing stops it when the
   table is cleared underneath it.**
2. **`_rebuild_status_cells_for`** (`:803`) — DM-driven `setCellWidget` on matching rows.
3. **`_apply_pinned_overlay`** (`:4845`) — a debounced `QTimer` that *adds rows and re-sorts*.
4. The search coroutine itself, which `await`s between insert chunks — so the event loop **runs
   these timers in the middle of a table rebuild**.

`search_server` also checks `home._search_generation != _my_search_gen` **only inside the insert
loop (line 703) — not before `clear_table()` (line 699)**, so two overlapping searches can both
reach the clear.

Corroborating evidence that Qt is already dispatching events to objects being destroyed in this app:

```
11:58:47 WARNING notify() skipped malformed dispatch: receiver=QEvent event=QChildEvent
         ('PySide6.QtWidgets.QApplication.notify' called with wrong argument types...)   ×4
```

A `QChildEvent` whose *receiver* unmarshals as a `QEvent` is a Shiboken wrapper-lookup failure —
the classic signature of an event being delivered to a **partially-destroyed** QObject. The
`main.py::notify` guard (added for the Curved-MPR teardown race) is *masking* this; the AV is the
same family of fault reaching C++ instead of Python.

`main.py:1199 _f11_sampler` was armed and shows **no long stall** at the crash — this was not a
hang, it was an instantaneous memory fault.

**Verdict:** the table is mutated by four independent event-loop producers with no shared "rebuild
in progress" lock, and `setRowCount(0)` mass-destroys ~180 cell widgets synchronously in the middle
of that. The network failure storm (root cause A) is what made the user hammer searches while a
download was running — i.e. it *scheduled* the crash, it didn't cause it.

---

## 4. Root cause C — Sync Status closes the tab, then reports failure

`PatientSyncService._sync_worker` (`PacsClient/pacs/patient_tab/utils/patient_sync_service.py`):

```python
status_response = report_service.update_report_status(study_uid, SYNC_REPORT_STATUS, ...)
if status_response:
    result['status_updated'] = True
else:
    result['errors'].append("Failed to update report status")      # :203  ← recorded…
...
self.sync_completed.emit(study_uid, result)                        # :221  ← …and then SUCCESS anyway
```

`sync_failed` is emitted **only on an exception**. A failed upload or a failed status update just
lands in `result['errors']` — and `sync_completed` still fires.

`toolbar_manager.on_sync_completed` (`:10096`) then **never looks at `result['errors']` or
`result['status_updated']`**:

```python
progress_dialog.close()
self.patient_widget.report_status = _synced_status          # :10114  claims "physician_approved"
home_widget.patient_table_widget.update_visited_status(study_uid, status='synced')   # green
if close_after_sync: self.patient_widget.close_and_remove_patient_tab()              # :10128
```

Meanwhile `update_report_status` already emitted `statusError` (queued, cross-thread) →
`patient_table_widget._on_report_status_error` (`:5143`) →
`QMessageBox.warning(self, "Status Change Error", "Error: Update failed - no response from server")`
— which lands on screen **after** the tab has closed. Exactly the reported behaviour.

Log proof, twice:

```
11:58:30.662  ERROR  Update failed - no response from server
11:58:35.036  WARN   [VOICE-DELETE-GUARD] kept saved voice on non-user teardown   <- tab closing
13:26:52.313  ERROR  Update failed - no response from server
13:26:54.890  WARN   [VOICE-DELETE-GUARD] ...                                     <- tab closing
```

**Clinical severity: this is the worst of the three.** The workstation marks the study
**Physician Approved / synced (green)** locally while **the server never received the status**, and
it closes the tab as a success. The attachments themselves are safe (local-first persistence + the
non-destructive reconcile hold), but the *reported state* silently diverges from the server. This is
the same class as the known INO reception status-sync gap.

---

## 5. Patient-list search performance — measured, and it is NOT a client regression

Every `[SEARCH-PERF]` line in the session:

| time | rows | search_ms | probed |
|---|---|---|---|
| 11:49:52 | 45 | **489** | yes |
| 13:24:59 | 45 | **538** | yes |
| 13:35:36 | 45 | **504** | yes |
| 13:36:00 | 5 | **208** | no |

And the one-shot A/B probe (OPT-24d) answers the question definitively:

```
[SEARCH-ENRICH-PROBE] with_study_count_ms=489 without_study_count_ms=434 delta_ms=55 rows=45
  -> SCAN is the cost (not enrichment) -> needs a SERVER-side index; no client fix helps
```

So:

* **~0.5 s is server-side scan time** (date + modality scan over the public internet). This matches
  OPT-24 exactly — the fix is a **server-side index**, as already done for the other centre.
* The *client* adds: a **pre-flight `test_connection()`** which is a **full extra `GetPatientList`
  round-trip** (`probed=True` on the first search of a session and after any empty result), and
  `[SEED_CONFIG]` re-runs the config-seed scan **7-10 times per search** (visible all over the log —
  cheap but pure waste).
* **The "sometimes noticeably slow" is root cause A.** When the pool hands out a dead client, the
  search returns `None` → empty result → the code re-probes (`test_connection`) → possibly another
  dead client → another round-trip. A search that should be 0.5 s becomes several seconds of
  probe/fail/probe, and can end in an empty table plus a modal "Connection Failed" dialog.

No recent code change explains it. Nothing in the search path regressed.

---

## 6. How the app currently behaves on network loss — the honest picture

| Concern | Current behaviour | Verdict |
|---|---|---|
| Temporary network loss | Pooled client stays "connected"; next call fails hard | ❌ **broken** (A) |
| Server unavailable | `connect()` fails → `QMessageBox.critical` modal | ⚠️ blocking modal |
| Connection timeout | `CONNECTION_TIMEOUT = 30.0 s` — runs in a thread-pool executor, so it does **not** block the UI thread | ✅ off-thread |
| Socket disconnection | Detected only *after* a failed request; the socket is torn down but the failure is surfaced to the user | ⚠️ no recovery |
| Automatic retry | **DM client: yes** (3× + reconnect). **UI/patient-list client: NONE** | ❌ **asymmetric** |
| Exception handling | Broad `except` everywhere; failures degrade to `[]` / `None` | ⚠️ silently returns `[]` for "no patients" AND "dead link" → the table gets **cleared** |
| UI-thread blocking | Search/upload/status all run off-thread. The blockers are **modal dialogs** (`QMessageBox.critical` in `_show_conn_failed`, `QMessageBox.warning` in `_on_report_status_error`) which each spin a nested event loop on the GUI thread | ⚠️ "frozen" feel, and re-entrancy risk |
| Crash / unexpected close | Root cause B | ❌ **broken** |

Note also: after the main app died, its **download subprocess kept running** (GetSeriesImages still
logging at 13:37, ~90 s after the crash) — an orphan. `terminate_all_download_subprocesses()` only
runs on a *clean* shutdown; a native AV bypasses it.

---

## 7. Proposed fixes — minimal, isolated, reversible

Ordered by (clinical risk × confidence). Every item is flag-gated with the legacy path preserved,
per project convention.

### FIX-1 — Socket connection-pool health + one automatic retry  *(root cause A — do this first)*
`modules/network/socket_client.py` (+ the two services that own pools)

1. `SocketConnectionPool.get_connection()`: **validate liveness instead of trusting the flag** —
   `select.select([sock], [], [], 0)` → readable-with-0-bytes ⇒ EOF ⇒ discard and create fresh.
   Also stamp `last_used` and **discard any connection idle > `AIPACS_SOCKET_POOL_IDLE_S` (default
   30 s)** — that alone eliminates the NAT/idle-timeout class.
2. `return_connection()`: **never re-pool a client whose last request errored** (add a `healthy`
   flag set in `send_request`'s `except`).
3. `send_request()`: on a **connection-level** failure where the server sent **zero bytes**
   (EOF / reset / broken pipe — i.e. exactly the stale-socket case), **reconnect once and resend**.
   Guard it to *read* endpoints by default (`GetPatientList`, `GetStudyThumbnails`,
   `GetPatientReceptionHistory`, `GetPatientStatus`); `UpdateReportStatus` is an idempotent
   status *set*, so a single zero-byte retry is safe there too — but ship it behind
   `AIPACS_SOCKET_WRITE_RETRY` so it can be turned off.

Expected effect: the "Invalid response length header" family disappears; a search after an internet
blip reconnects transparently instead of returning an empty table.

### FIX-2 — Sync Status must not report success on failure  *(root cause C — highest clinical severity)*
`patient_sync_service.py` + `toolbar_manager.py`

* `_sync_worker`: emit **`sync_failed`** (not `sync_completed`) when
  `result['errors']` is non-empty or `status_updated` is False.
* `on_sync_completed`: **do not** close the tab, **do not** set `report_status = physician_approved`,
  and **do not** paint the row green unless `result['status_updated']` is True and
  `attachments_failed == 0`. Partial success → keep the tab open, show what failed, offer Retry.
* Suppress the duplicate `statusError` `QMessageBox` while a sync is in flight (the sync dialog
  already owns that error) so the orphan popup after tab close can't happen.

### FIX-3 — Make `clear_table()` crash-proof  *(root cause B)*
`patient_table_widget.py` + `home_search_service.py`

* Add one **`_table_rebuilding` re-entrancy guard**. `clear_table()` and the bulk insert set it;
  `_refresh_statuses_chunked`, `_rebuild_status_cells_for`, `update_study_download_status`,
  `_apply_pinned_overlay` and the progressive-scroll insert **return early** while it is set.
* At the **start** of `clear_table()`: bump `_status_refresh_token` (kills the in-flight chunked
  chain) and `_pin_overlay_timer.stop()`.
* Destroy cell widgets **deferred, not synchronously**: `setUpdatesEnabled(False)` +
  `blockSignals(True)`, explicitly `removeCellWidget()` each one and `deleteLater()` it, *then*
  `setRowCount(0)`. Deferred deletion is the standard cure for exactly this AV class.
* `search_server`: check `home._search_generation != _my_search_gen` **before** line 699's
  `clear_table()`, not only inside the insert loop.

### FIX-4 — Stop the modal-dialog freezes on connection failure
* `_show_conn_failed()` → replace `QMessageBox.critical` with the existing non-modal connection
  indicator + a status-bar/toast message. A failing auto-search must never open a modal.
* `_on_report_status_error` → rate-limit / route to the indicator instead of a modal warning.

### FIX-5 — Cheap wins
* Kill the redundant `[SEED_CONFIG]` re-scan (7-10× per search — pure waste; see OPT-24's
  "client waste removed" item).
* Skip the pre-flight `test_connection()` round-trip once FIX-1 makes a stale socket self-heal.
* Register the download-subprocess kill in a `faulthandler`/`atexit` path that also runs on an
  abnormal exit, so a crash cannot orphan a downloader.
* **Server-side:** the ~0.5 s `GetPatientList` scan needs the same date+modality **index** that was
  applied at the other centre (OPT-24). No client change will fix it.

---

## 7b. Follow-up recheck — "did any OTHER component fail to reach the net? Did EchoMind hang or crash the app?"

Asked after the first pass. Two questions, two separate answers.

### Was anything else failing to connect in that session? — and was EchoMind involved?

Full sweep of all five logs for every network-touching subsystem:

| Component | Activity in the crash session | Verdict |
|---|---|---|
| Socket (patient list, thumbnails, report status, reception history, downloads) | The OPT-28 stale-socket failures | ✅ **fixed** (FIX-1) |
| **EchoMind / AI** | **Adapter registration only — ZERO network calls all session** (no report, no chat, no STT) | ✅ **NOT implicated in the crash or the freeze** |
| Reception REST hydration | 4× `GET http://81.16.117.196:8080` → **HTTP 404** | ⚠️ handled gracefully (no crash); the endpoint is **not deployed / mis-configured** on this server, so the REPORT column's physician name never hydrates → **OPT-34** (server/config, not a client bug) |
| Web-browser Chromium prewarm | idle-gated, never fired | ✅ |
| Identity / cloud consultation / license / update check | no activity | ✅ |

**Python-level crashes: zero.** All five logs contain **0** `CRITICAL`, **0** `EXCEPTION in Qt event
dispatch`, **0** `Traceback`. (The two "critical" grep hits are the word inside
`request_critical_series`.) So there was exactly **one** unexpected close in that session — the
native access violation (OPT-29) — and **nothing** in the network stack raised an unhandled
exception into `main.py::notify`, which re-raises and would terminate the app.

### Can EchoMind hang or crash the app when the internet drops? — one real defect found

**It cannot crash it.** Every AI call runs on an `ApiWorker` **QThread** (`ai_chat_api.py:64`) whose
`run()` is wrapped in try/except and emits `failed` → the user gets
*"❌ Connection error. Please check your internet connection…"*. The app survives.

**But it can hang forever.** All ten `requests.post(...)` calls in
`modules/EchoMind/viewer_chat/openai_reporter.py` were issued with **no `timeout=`** — requests then
waits indefinitely. On a *clean* refusal (connection reset / DNS failure) it errors out fine; on a
**half-open** connection — a link that dies mid-request, which is **exactly what this laptop's
network does** (OPT-28) — the worker thread **never returns**:

* the "typing…" bubble spins forever,
* the Send button stays locked (`lock_btn`),
* the `QThread` leaks — and every retry leaks another one.

That is the "EchoMind attenuates / hangs when the net drops" symptom, and it is real. **Fixed**
(OPT-33): `timeout=_request_timeout()` → `(connect 10 s, read 180 s)` on all ten calls. A connect must
fail fast; a long LLM completion legitimately needs a generous read budget. The timeout turns an
infinite hang into the **error path that already exists** — the user gets the "Connection error"
bubble and can retry. Tunable with `AIPACS_ECHOMIND_HTTP_TIMEOUT=<read seconds>`; `=0` restores the
legacy wait-forever.

`openai_reporter.py` **is plugin-mirrored** — the mirror was synced on the Windows host (413/413
match), otherwise the installed build would still ship the hanging version.

**Everything else was already safe:** a full sweep of `requests.*`, `urlopen`, `urllib.request`,
`http.client` and `socket.create_connection` across `modules/` and `PacsClient/` found **no other
call without a timeout** (`retry.py:87` is a docstring example, not code). The AI-segmentation POST,
the INO report workflow, Identity/OAuth, the STT provider, `llm_client`, the admission API and the
reception tab all already pass `timeout=`.

## 8. IMPLEMENTED — 2026-07-13 (all default-on, all kill-switched)

Master plan: **OPT-28 / OPT-29 / OPT-30 / OPT-31** (§9 backlog + §15 validation history).

| Fix | Files | Flag (default) | Legacy path |
|---|---|---|---|
| **FIX-1** pool liveness + idle eviction + one zero-byte reconnect-retry | `modules/network/socket_client.py` | `AIPACS_SOCKET_RECONNECT_RETRY=1`, `AIPACS_SOCKET_POOL_IDLE_S=30` | `=0` → byte-identical single attempt |
| **FIX-2** strict sync result; tab stays open on an unconfirmed sync | `patient_sync_service.py`, `toolbar_manager.py`, `patient_table_widget.py` | `AIPACS_SYNC_STRICT_RESULT=1`, `AIPACS_SUPPRESS_SYNC_OWNED_STATUS_ERROR=1` | `=0` → legacy always-`sync_completed` |
| **FIX-3** crash-proof `clear_table` | `patient_table_widget.py`, `home_search_service.py` | `AIPACS_SAFE_CLEAR_TABLE=1` | `=0` → `_clear_table_legacy()` (byte-identical; the code that crashed) |
| **FIX-4** non-modal network-failure feedback | `home_search_service.py`, `patient_table_widget.py` | `AIPACS_MODAL_CONN_FAILED=0`, `AIPACS_MODAL_STATUS_ERROR=0` | `=1` → the old modals |

### FIX-1 detail — what makes the retry safe

The retry is deliberately narrow:

* Retried **only** when the failure happened **before a single response byte arrived**
  (`_last_error_zero_byte`). A half-open socket means the server process had already dropped the
  connection, so it cannot have seen — let alone applied — the request. That makes the resend safe
  even for a write endpoint like `UpdateReportStatus` (no double-apply is possible).
* A failure **mid-response** (header read, body truncated) is **never** retried — the server may
  have applied the request.
* A clean "no response in time" on a live connection is **never** retried — the server was
  reachable and answering.
* `is_socket_alive()` uses a zero-timeout `select`: not-readable ⇒ alive (the cheap common path);
  readable-with-zero-bytes ⇒ EOF ⇒ dead; readable-with-bytes before we sent anything ⇒ stream
  desync ⇒ also unusable. It never raises and fails safe (a false negative costs one fresh connect).

### FIX-2 detail — the clinical half

A sync is successful **only** when no error was recorded **and** `status_updated` is True **and**
`attachments_failed == 0`. Anything else now emits `sync_failed` → the tab **stays open**, the study
is **not** marked `physician_approved`, the row is **not** painted green, and the user gets one Retry
dialog with "your files are still saved locally". The toolbar re-validates the same pure predicate
before it closes the tab, so a legacy emit cannot slip through. Local attachment persistence is
untouched (the local-first save and the non-destructive reconcile guards still hold).

### Tests

**39 new guard tests**, all green:

* `tests/code/network/test_socket_pool_health.py` (16) — EOF/desync/idle detection, pool discard,
  never-repool-a-failed-client, retry-once-on-zero-byte, never-retry-mid-response, kill switch.
* `tests/code/ui_services/test_sync_status_strict_result.py` (14) — the pure predicate, and an
  ordering pin that the toolbar's bail comes **before** the approve + close.
* `tests/code/ui_services/test_clear_table_crash_guard.py` (14) — guard raised/released, timers
  cancelled, deferred widget delete precedes the model reset, every producer backs off, the search
  checks its generation before the clear.

**Regression proof:** `tests/code/{network,ui_services,system,download_manager,storage}` →
**1219 passed**. The 7 remaining failures are byte-identical to the same suites run with the edits
`git stash`ed (ino ×2, pin_overlay ×2, vtk_volume, mpr_tool_autoexit — all pre-existing; the
echo_popup mirror drift comes from separate uncommitted EchoMind work in the tree). **Zero new
failures.** None of the five edited source files is plugin-mirrored (verified against all 413).

Two **existing** guards had to be repaired, not weakened: `test_pin_overlay::test_stable_pinned_
section_wired` and `test_study_downloaded_cache::test_invalidation_wired_into_status_update` pinned
`clear_table` / `update_study_download_status` with a **fixed byte-window** (1400 / 1600 chars), so
documenting those functions pushed the asserted code out of the window. Both now extract the real
function body via `ast` — same assertions, exact scope, no longer fragile.

## 9. NOT done — and what still needs live verification

**Not implemented (deliberately):**

* **FIX-5 / OPT-32 — the server-side `GetPatientList` index.** The in-app A/B probe already proved
  the ~0.5 s is the server's date+modality SCAN, not enrichment. No client change helps; this is the
  same index fix already applied at the other centre.
* The redundant per-search `[SEED_CONFIG]` re-scan (7-10× per search) and the pre-flight
  `test_connection()` extra round-trip — both are pure waste but neither is a correctness bug, and
  the probe becomes redundant only once FIX-1 has soaked.
* Killing the download subprocess on an **abnormal** exit (the crash orphaned a downloader that kept
  running for 90 s).

**Needs live verification on that laptop — none of this is proven in the field yet:**

1. **FIX-1:** pull the network → search (expect a clean "connection failed" indicator, no modal) →
   restore the network → search again → it must recover **silently**, with no
   `Invalid response length header` in `download_diagnostics.log`.
2. **FIX-3:** 45+ rows in the table, a download running, two back-to-back searches with different
   result counts → no crash, no new `native_fault.log` entry.
3. **FIX-2:** Sync Status with the network down → the tab **stays open**, one Retry dialog, and the
   study is **not** green/approved. With the network up → unchanged: success, silent close.

The FIX-3 mechanism is inferred from the crash stack plus the `malformed dispatch` warnings, not
from a native symbol trace. If the crash cannot be reproduced on demand, the fix is still correct
defensively (it removes unguarded re-entrancy and defers ~180 destructors out of the model reset),
but we will not have a hard before/after.

Also still open, independent of all of the above: `[WinError 10053] connection aborted by the
software in your host machine` can be a **local firewall / antivirus** interfering with port 50052 on
that laptop — worth checking its security software.

## 9. Open questions / needs live verification

* The AV mechanism (FIX-3) is inferred from the crash stack + the `malformed dispatch` warnings, not
  from a native symbol trace. To confirm before/after, reproduce with: 45+ rows in the table, an
  active download, then fire two searches back-to-back with a different result count. If it cannot
  be reproduced on demand, FIX-3 is still correct defensively (it removes the unguarded re-entrancy),
  but we will not have a hard before/after.
* `[WinError 10053] connection aborted by the software in your host machine` at 11:59:53 can also be
  a local firewall / AV interfering with port 50052 on that laptop — worth checking that machine's
  security software, independently of FIX-1.
