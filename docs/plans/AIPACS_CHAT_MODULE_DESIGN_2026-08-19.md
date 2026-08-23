# AiPacs Chat — manager module for the Windows DICOM Workstation
## §11 design deliverables — for review before any UI code

Date: 2026-08-19 · Author: engineering session · Status: **awaiting owner approval**

Verified against the two real repositories, not against the handoff brief:

| | |
|---|---|
| Workstation | `E:\ai-pacs\ai-pacs codes\ai-pacs beta version` |
| Laravel backend | `D:\laragon-www\ai-pacs\public_html\consult-form\laravel-back` (module `modules\PatientChat`) |

Everything below that states a number, a field name or a route was read out of those files. Where a
thing does **not** exist, it is called out explicitly rather than assumed.

---

## 0. Five things that change the plan

These were found during the read and are more important than anything else in this document.

**0.1 — `/forms-panel/sync` has authentication but NO authorization. This is a blocker.**
`StaffConsoleController::sync()` does `PatientCase::findOrFail($request->query('case'))` with no
ownership, role or center check, and `rows[]` / `counts` / `events[]` span **every case in the
system**. Under `['web','auth']` that is an admin console with one user class. Re-exposed under
`auth:sanctum`, *every* token minted by `/api/v1/auth/workstation/pair` and
`/auth/workstation/link-google` — i.e. every paired physician workstation — would inherit read
access to every patient's full transcript and PHI. The code comment ("scoped by findOrFail so a
tampered id is a 404 rather than another patient's transcript") describes 404-on-nonexistent, not an
ownership check. **An authorization gate must be added before `/api/v1/chat/*` is opened.** See §9.0.

**0.2 — `GET /forms-panel/sync` is not a pure read. A GET performs writes.**
Through `CaseSync::forStaffThread` → `CaseFlow::touchStaff()` it writes `staff_last_seen_at`,
**sets `unread_for_staff = 0` unconditionally whenever it is non-zero**, **nulls `notify_staff_due_at`
(cancelling the queued staff notification e-mail)**, and writes `staff_last_read_at` when
`visible=true`. So a second client polling `?case=N` silently clears the web console's unread badge
and cancels its notification e-mails. Two clients on the same case fight over this state. The
workstation must therefore be treated as a *co-equal operator*, not a passive mirror — and
`visible=0` must be sent explicitly (the server default is `true`).

**0.3 — There is no `httpx` and no `QSystemTrayIcon` in the workstation.**
The handoff assumes both. The repo uses `requests` (pinned `requests[socks]>=2.31.0`), and has
**zero** `QSystemTrayIcon` / taskbar-overlay usage. The existing unread-count UI is the red numeric
`QLabel` badge on the account pill (`modules/cloud_consultation/ui/badge_core.py` +
`account_hook.py`). The chat module will reuse that badge pattern and an in-app popup, not a tray icon.

**0.4 — The module opens as a singleton tab, not a window.**
"Like education / web browser / print" means: a plain `QWidget`, opened through
`home_module_tabs.activate_or_create_module_tab(...)` into the main `QTabWidget`, one instance
enforced by a `tab_flag_key`. Not a `QDialog`, not a `QMainWindow`. §6 follows that exactly.

**0.5 — Auth already exists and must not be duplicated, but it is missing two things.**
`modules/Identity/providers/aipacs_web.py` already does `POST <base>/api/v1/auth/workstation/pair`,
stores `{token, base_url}` in Windows Credential Manager under service `AIPacs-Identity`, account
`aipacs_web:<subject_id>`, and sends `Authorization: Bearer <token>`. What it does **not** have:
(a) any retry/backoff, (b) any 401 → re-pair path — a 401 becomes a generic
`AipacsWebError("Your AI-PACS Consultation session expired — sign in again.")` with **no status code
on the exception**, so 401 can only be detected by string matching today. §5 proposes the one minimal
shared-file change: add `status_code` to `AipacsWebError`.

---

## 1. Architecture map

```
                    ai-pacs.com  (Laravel, modules/PatientChat)
    ┌───────────────────────────────────────────────────────────────────┐
    │  Services/CaseSync ── Support/SyncCursor ── Support/ConsoleEvents │
    │  Models: PatientCase · CaseMessage · CaseFile · Visitor · …       │
    │  Business logic lives HERE and is not forked.                     │
    └──────────┬──────────────────────────────────┬─────────────────────┘
               │                                  │
   routes/staff.php                     routes/api.php  ← NEW, §9
   middleware ['web','auth']            /api/v1/chat/*  behind auth:sanctum
   session cookie, Blade, back()        + an authorization gate (§9.0)
               │                                  │
               ▼                                  ▼
   ┌────────────────────────┐        ┌──────────────────────────────────┐
   │  Web manager console   │        │  AiPacs Chat (this module)       │
   │  (existing, unchanged) │        │  modules/aipacs_chat/            │
   └────────────────────────┘        │                                  │
                                     │  ui/    PySide6 only, no HTTP    │
                                     │  services/  no Qt imports at all │
                                     └──────────────────────────────────┘
                                            inside AIPacs.exe, as a tab
```

Two clients, one server, one protocol. Nothing in the workstation re-derives a business rule the
server already computes (`editable`, `status_tone`, `ago`, `deliveryState`, the summary lines).

### Where it sits in the workstation

```
AIPacs_ui.py :: ControlPanelWindow
  ├ setup_left_menu()          → self.chat_btn = _create_menu_button(...)
  ├ connect_left_navigation()  → self.chat_btn.clicked.connect(self.open_aipacs_chat)
  └ open_aipacs_chat()         → delegates to self.home_widget.open_aipacs_chat()

home_ui/home_panel/_hp_modules.py :: _HPModulesMixin
  └ open_aipacs_chat()         → feature gate → lazy import →
                                 activate_or_create_module_tab(tab_flag_key='is_aipacs_chat_tab', …)

patient_tab/ui/patient_ui/custom_tab_manager.py
  └ add_aipacs_chat_tab(widget=None)   ← copy of add_web_browser_tab, icon fa5s.comments
```

---

## 2. Backend endpoint inventory

### 2.1 Already JSON today (staff, session-authenticated)

| Method | URI | Returns |
|---|---|---|
| GET | `/forms-panel/sync` | `{t, cursor, cold, thread, counts, events, rows}` — the everything-poll |
| GET | `/forms-panel/inbox-list` | `{counts, ev, events, rows}` — legacy, superseded by sync |
| GET | `/forms-panel/inbox/{case}/poll` | legacy per-thread poll, superseded by sync |
| GET | `/forms-panel/visitors/live` | `{counts, html, as_of}` — **sends rendered HTML, not rows** |
| GET | `/forms-panel/visitors/count` | `{online, on_form, submitted_today}` |
| GET | `/forms-panel/drive/cases` | `{rows:[…]}` case picker |
| POST | `…/message/{id}/react` | `{id, mine, reactions}` (uses `wantsJson()`) |
| POST | `…/inbox/{case}/send` | `201 {message: toStaffArray()}` (uses `expectsJson()`) |
| POST | `…/inbox/{case}/price` | `201 {message: toStaffArray()}` — **except** the "no amount for tier" error path, which returns `back()` even for XHR |
| POST | `/forms-panel/drive/case/{case}/…` (4 routes) | `{ok:true, …}` / `422 {ok:false, error}` — **this is the template to copy** |

### 2.2 Redirect-only today — need JSON variants (§9)

`status`, `upload`, `rotate-link`, `message/{id}/email`, `links`, `links/{file}/primary`,
`links/{file}/forget`, `message/{id}/pin`, `message/{id}/edit`, `message/{id}/remove`,
`inbox/{case}/pin`. Exact fields and validation are in §9.3.

### 2.3 Does not exist anywhere — must be built

- `GET /api/v1/chat/cases/{case}` — the full case payload the side panel needs (summary lines,
  journey, visitor, files, e-mail sends, pinned messages). Today that data is assembled inside a
  Blade view and never serialized.
- `GET /api/v1/chat/saved-replies` — `case_saved_replies` is rendered straight into
  `console-thread.blade.php`; there is no JSON reader.
- `GET /api/v1/chat/pricing` — `config/patientchat.php` `pricing.tiers`; no endpoint.
- `GET /api/v1/chat/visitors` — `visitors/live` returns HTML; the row array exists internally as
  `StaffVisitorController::row()` but is never emitted as JSON.
- **Any authorization gate at all** (§9.0).

### 2.4 Deliberately out of scope

`/forms-panel/greetings*` (automation rules), `manifest.webmanifest`, `/sw.js`, `/offline`, the whole
patient surface (`routes/patient.php`, magic-link cookie auth, recovery flow).

---

## 3. Real-time — cursor semantics and event list

### 3.1 Request

`GET /api/v1/chat/sync` — **all cursor and filter parameters are read from the query string only**
(`SyncCursor::intFrom` uses `$request->query()`). A JSON body is silently ignored; a body-based
client looks permanently cold. `visible` and `typing` use `$request->boolean()` which *does* read the
body — so a body-based client would be half-broken, which is worse.

| Param | Type | Default | Meaning |
|---|---|---|---|
| `m` | int | 0 | highest message id already drawn |
| `rev` | int (unix s) | 0 | anything `updated_at >` this is stale on screen |
| `ev` | int | 0 | highest `case_events.id` already announced |
| `req` | int | 0 | client request counter, echoed untouched |
| `case` | int | 0 | open conversation; 0/absent → `thread: null` |
| `visible` | bool | **true** | **must be sent explicitly as 0 when hidden** |
| `typing` | bool | false | effective typing = `typing && visible` |
| `show` | `open`\|`all`\|`closed` | `open` | list filter |
| `attn[]` | `unread`\|`stalled` | — | multi |
| `presence` | `any`\|`online`\|`offline` | `any` | |
| `price` | `any`\|`none`\|`priced` | `any` | |
| `source[]` | `form`\|`widget`\|`crisp` | — | multi |
| `status[]` | any of the 15 statuses | — | multi |
| `q` | string ≤120 chars | `''` | search |

Clamp on all four cursor ints: non-scalar/non-numeric → `0`; then `max(0, min((int)$v, PHP_INT_MAX-1))`.

### 3.2 Response envelope

7 top-level keys: `t, cursor, cold, thread, counts, events, rows`.

- `thread` — `null`, or exactly `{case, m, messages[], revised[], patient_online, patient_typing, read_at, seen_at, status, status_tone}`
- `counts` — exactly 4 keys: `{unread, online, stalled, none}`
- `rows[]` — exactly 10 keys: `{id, unread, online, at, ago, preview, sender, status, tone, pinned}`
  — note the key is **`tone`**, not `status_tone`, in rows
- `events[]` — exactly 9 keys: `{key, kind, case, ref, who, title, body, url, at}`
- `messages[]`/`revised[]` — exactly 14 keys, see §4.

There is **no top-level `ev`** on a sync response — the event cursor is only in `cursor.ev`.
(`/forms-panel/inbox-list` does have a top-level `ev`; do not copy that.)

### 3.3 Cursor rules — every one exists because of a real bug

1. **Order by `id`, never by timestamp.** New = `id > cursor.m`, limit 100. Guarded by
   `RealtimeDeliveryTest::test_messages_in_the_same_second_are_both_delivered`.
   ⚠ Neither `newMessages()` nor `revisedMessages()` has an explicit `orderBy('id')` — ordering
   relies on the storage engine default. **The client must sort by id itself.**
2. **`messages` and `revised` are disjoint.** Revised = `id <= cursor.m AND updated_at > cursor.rev`.
3. **Apply `revised` before `messages`.**
4. **Drop any response whose `cursor.req` is lower than the newest applied.** One request in flight
   at a time.
5. **Drop a `thread` whose `case` is not the currently open one** — compare against the id captured
   when the conversation was opened, never a mutable variable.
6. `cold: true` ⟺ exactly three conditions: `rev <= 0`, or `now - rev > 900` (**`MAX_REV_AGE = 900`
   confirmed**), or `rev > now + 60` (**60 s future tolerance confirmed**). `m`, `ev`, `req` never
   affect `cold`. On cold: **replace state wholesale, do not merge**; the server skips the revision
   sweep entirely.
7. **Next cursor:** `m` and `ev` use `max()` and never go backwards; `rev` is stamped from
   *response-build time*, never from the newest row (a row written mid-request would fall in the gap).
8. **A failed request must not move the cursor.** Every request is already a catch-up request.
9. **Presence and typing must be applied on every answer, including empty ones.**
10. **Read-receipt comparison is `>=`, not `>`** — the server compares the same way (`gte`).
11. **Applying the same answer twice must change nothing.**

### 3.4 Cadence (mirrored from `console-script.blade.php`)

| State | Interval |
|---|---|
| Active (something moved in the last 30 000 ms) | **800 ms** |
| Visible, idle | **3 000 ms** |
| Hidden < 15 min | **15 000 ms** |
| Hidden ≥ 15 min, notifications ON | **45 000 ms** |
| Hidden ≥ 15 min, notifications OFF | **stop** |
| First poll after open | 400 ms |
| Backoff after >2 consecutive failures | `min(30000, 800 · 2^min(misses,5))`, reset to 0 on success |

Resume on becoming visible: **250 ms if it had died, else 60 ms**. Typing flag:
`typingUntil = body.strip() ? now+4000 : 0`, costs no request of its own. Server-side write
throttles keep cadence ≠ write rate: presence written only if stale by >15 s; read stamp only when
it would actually change a tick.

**Desktop adaptation.** "Visible" for a tab inside `QTabWidget` is not `document.hidden`. Proposal:
`visible = window is active AND the AiPacs Chat tab is the current tab AND the app is not minimised`.
This preserves the meaning of `seen` (§4.3) — a badge on a background tab is not "read".

### 3.5 Notification events

`ConsoleEvents::KINDS = ['message', 'request', 'status', 'unsubmitted']`.
`LOOKBACK_MINUTES = 30`, `SCAN = 60` rows/poll, `MAX = 8` events/poll,
unsubmitted: after 10 min, within 48 h, max 3. `spam` cases are skipped.

- `message` — **patient** messages only (`meta['by'] === 'patient'`); staff and automation are silent.
- `request` — new consultation (`CASE_CREATED`).
- `status` — suppressed when the actor is the viewer themselves.
- `unsubmitted` — a standing condition query, appended on **every** branch including cold start.

`key` is `'e'+event_id` or `'u'+case_id`, so ids can never collide in a seen-set.

**`ev` cursor traps, verified:**
- The returned `cursor` is **always** the head of `case_events` — on cold start, on a future cursor,
  on empty rows, and after the `MAX = 8` trim. **Events dropped by the 30-minute lookback or the
  trim are never re-offered.**
- `cursor <= 0` or `cursor > head` → cold start: announces nothing from the log (only unsubmitted).
- **The web client resets its `ev` cursor if the stored one is older than 5 minutes**
  (`localStorage aipacs.notify.ev`, `EVC_MAX_AGE = 5 min`). This is the documented bug from §12 of
  the handoff. **The desktop module persists `ev` with no age limit**, in QSettings, so a restart is
  not a cold start.
- Web chimes on `message` and `request` only. The handoff asks for **both**, which matches — the
  "silently dropped one" complaint refers to `status`/`unsubmitted`, which are correctly silent.

---

## 4. Data models — Python dataclasses

All in `modules/aipacs_chat/services/models.py`. **No Qt imports in this file.**

### 4.1 Message

```python
MESSAGE_TYPES = ("text", "file", "link", "system", "price_offer", "payment_link", "report")
# payment_link and report: constants exist server-side but NOTHING creates them today.

@dataclass(frozen=True, slots=True)
class Reactions:
    patient: int | None = None      # 1 | -1 | None
    staff_up: int = 0
    staff_down: int = 0

@dataclass(frozen=True, slots=True)
class ChatMessage:
    id: int
    sender_type: str                # patient | staff | system
    sender: str | None              # staff member's name
    type: str                       # see MESSAGE_TYPES
    body: str                       # display-safe; "This message was deleted" when removed
    meta: dict | None               # None when removed; raw server meta otherwise
    ai_action: str | None
    edited: bool
    removed: bool
    editable: bool                  # SERVER-COMPUTED — never re-derive (§12)
    reactions: Reactions
    my_reaction: int | None         # 1 | -1 | None
    is_automated: bool
    at: datetime                    # ISO-8601 on the wire
```

`meta` by type, as actually written:

| type | keys |
|---|---|
| `text` | `{}` |
| `file` | `file_id, file_name, file_size, mime, is_image` |
| `link` | `url, host, file_id` |
| `price_offer` | `amount, currency` always; `tier`, `url` **absent** (not null) when unset |

⚠ `toStaffArray()` does **not** whitelist `meta` (unlike the patient array). Internal routing hints
and staff notes stored in `case_messages.meta` are exposed verbatim. Acceptable for an operator
console; a reason the authorization gate in §9.0 matters.

### 4.2 Conversation row

```python
@dataclass(frozen=True, slots=True)
class ConversationRow:
    id: int
    unread: int
    online: bool
    at: datetime | None
    ago: str | None        # server-rendered, localized, goes stale — display only, never cache
    preview: str           # ≤180 chars
    sender: str            # patient | staff | system
    status: str
    tone: str              # fresh|wait|work|good|alert|done  — NOTE: key is "tone", not status_tone
    pinned: bool
```

### 4.3 Thread / cursor / counts / events

```python
@dataclass(frozen=True, slots=True)
class SyncCursor:
    m: int = 0
    rev: int = 0
    ev: int = 0
    req: int = 0

@dataclass(frozen=True, slots=True)
class Thread:
    case: int
    m: int
    messages: tuple[ChatMessage, ...]
    revised: tuple[ChatMessage, ...]
    patient_online: bool
    patient_typing: bool
    read_at: int | None
    seen_at: int | None
    status: str
    status_tone: str

@dataclass(frozen=True, slots=True)
class Counts:
    unread: int = 0
    online: int = 0
    stalled: int = 0
    none: int = 0          # "not priced yet"

@dataclass(frozen=True, slots=True)
class ConsoleEvent:
    key: str               # 'e<id>' | 'u<case>'
    kind: str              # message | request | status | unsubmitted
    case: int
    ref: str
    who: str
    title: str
    body: str
    url: str               # absolute WEB console URL — see gap G7
    at: int

@dataclass(frozen=True, slots=True)
class SyncResponse:
    t: int
    cursor: SyncCursor
    cold: bool
    thread: Thread | None
    counts: Counts
    events: tuple[ConsoleEvent, ...]
    rows: tuple[ConversationRow, ...]
```

**Delivery state.** Server returns only `delivered` | `seen`; there is deliberately no `sending`
state — the composer owns that until the row exists. `seen` is written only when the operator's
window was actually in front of them. `CaseMessage.read_at` exists as a column but **nothing writes
it**; all read state is case-level (`patient_cases.staff_last_read_at` / `patient_last_read_at`).

### 4.4 Case detail (for the side panel)

This is the shape the *new* `GET /api/v1/chat/cases/{case}` must return. Every string here is
computed by an existing `PatientCase` method — the endpoint serializes, it does not invent.

```python
@dataclass(frozen=True, slots=True)
class CaseSummaries:
    imaging: str      # imagingSummary()   "Google Drive + 2 more" | "3 files attached" | "No study yet"
    drive: str        # driveSummary()     "Folder + 3 files" | "Not filed yet"
    location: str     # locationSummary()  "Athens, Greece" | "Australia" | "Not resolved"
    case: str         # caseSummary()      "MRI · second opinion"
    source: str       # sourceSummary()    "Google Search → Brain MRI Second Opinion"
    visit: str | None # visitSummary()     "/mri-second-opinion · 4 pages · 6 min on site"

@dataclass(frozen=True, slots=True)
class CaseDetail:
    id: int
    public_id: str
    reference: str
    display_label: str
    initials: str
    status: str
    status_tone: str
    stage_label: str
    stage_note: str
    email: str | None
    phone: str | None
    country_code: str | None
    location_line: str | None
    location_approximate: bool
    local_time: datetime | None
    device_label: str | None
    entry_page_label: str | None
    landing_title: str | None
    journey_steps: tuple[JourneyStep, ...]
    summaries: CaseSummaries
    source: str                 # form | widget | crisp
    source_label: str
    mirrored: bool
    external_url: str | None
    modality: str | None
    files: tuple[CaseFileRef, ...]
    primary_study_file_id: int | None
    drive: DriveFolderRef | None
    email_sends: tuple[EmailSend, ...]
    pinned_message_ids: tuple[int, ...]
    visitor: VisitorRow | None
    pinned: bool

@dataclass(frozen=True, slots=True)
class JourneyStep:
    kind: str          # landing | read | before
    label: str
    url: str | None
    note: str | None

@dataclass(frozen=True, slots=True)
class CaseFileRef:
    id: int
    storage_kind: str        # local | drive | link
    uploaded_by: str         # patient | staff
    host_label: str          # KNOWN_HOSTS[host] ?? bare hostname — NEVER reject an unknown host
    external_url: str | None
    short_url: str | None
    original_name: str | None
    mime: str | None
    bytes: int | None
    is_primary: bool

@dataclass(frozen=True, slots=True)
class EmailSend:
    id: int
    kind: str                # update | message | confirmation
    case_message_id: int | None
    queued_at: datetime | None
    accepted_at: datetime | None
    opened_at: datetime | None
    open_count: int
    # display: sent / opened / not opened
```

`VisitorRow` mirrors `StaffVisitorController::row()` verbatim (24 keys incl. `current_label` /
`entry_label`, which the server already percent-decodes and strips of control characters and bidi
overrides — the client must **not** re-decode, and must keep the raw value for the link).

### 4.5 Statuses and tones (ship the server's, never a local copy)

15 statuses → 6 tones. `status_tone` / `tone` arrives on the wire and is used directly. The map is
recorded here for reference only, and **must not be re-implemented in Python**:

`new`→fresh · `awaiting_images`→wait · `images_received`→work · `images_rejected_quality`→alert ·
`priced`→wait · `awaiting_payment`→wait · `payment_failed`→alert · `paid`→good · `in_reporting`→work ·
`report_ready`→good · `follow_up`→wait · `closed`→done · `patient_unresponsive`→alert ·
`refunded`→done · `spam`→alert. Unknown status → `work`.

The **status picker** in the UI needs the list of statuses and their labels, so
`GET /api/v1/chat/statuses` (or an embedded block on `/pricing`) is added to §9 — otherwise the
client would hard-code the list, which is exactly the drift trap.

---

## 5. Auth / session design

**Reuse `modules/Identity` completely. No second auth mechanism, no session cookie, no keyring code
of our own.**

```
base_url        env AIPACS_WEB_BASE_URL  →  <config_root>/identity/aipacs_web.json {"base_url","enabled"}
                default: "" (module reports "not configured")
URL rule        f"{base_url.rstrip('/')}/api/v1{path}"      # so we pass path="/chat/sync"
token custody   keyring service "AIPacs-Identity", account f"aipacs_web:{subject_id}"
                payload {"token": ..., "base_url": ...}
                fallback when keyring unavailable: Fernet-encrypted file under
                <config_root>/identity/secrets/  (already implemented)
identity lookup find_aipacs_web_identity(aipacs_user) -> ExternalIdentity | None
client          get_aipacs_web_client(aipacs_user) -> AipacsWebClient | None
pairing (GUI)   Identity.ui.aipacs_web_dialog.open_signin_dialog(service, parent,
                    on_success=..., on_finished=...)      # MODELESS by contract — never exec()
aipacs_user     IdentityService.resolve_aipacs_user(auth_user)
```

`AipacsWebClient` sends `Authorization: Bearer <token>` + `Accept: application/json`, timeout 15 s,
and `thread_guard.assert_off_gui_thread()` raises if called from the GUI thread. That guard is a
feature for us: it makes an accidental GUI-thread poll fail loudly.

### What we add (minimal, and only one of them touches a shared file)

1. **`AipacsWebError.status_code`** *(shared file — `modules/Identity/providers/aipacs_web.py`)*.
   Today a 401 is indistinguishable from any other failure except by matching the message string.
   One attribute, set in `_extract_error`'s caller, additive, no behaviour change. Guarded by a test.
2. **`services/chat_client.py`** in *our* module — a thin wrapper over `AipacsWebClient` adding:
   - the `/chat/*` path helpers,
   - retry/backoff (there is none in Identity): the house pattern from
     `ConsultationPoller` — double on error, cap `MAX_BACKOFF_INTERVAL_MS = 600000`, reset on success;
     for sync specifically we use the web console's own curve (§3.4) which is tighter,
   - proxy + timeout: **route through `modules/EchoMind/echomind_http`'s
     `requests_proxies()` / `resolve_timeout()`** rather than deriving a third copy of the proxy dict
     (documented rule; `"direct"` must return `{}`, not `None`),
   - 401 → discard secret (`secure_store.delete_secret("aipacs_web", subject_id)`) + emit
     `authRequired` so the UI can call `open_signin_dialog`. **Never retry a 401 silently.**
3. **Client rebuild on user switch.** The secret is scoped `aipacs_web:<subject_id>` per
   `aipacs_user`; nothing invalidates it for us. The poller rebuilds its client when
   `resolve_aipacs_user(auth_user)` changes.

**Not doing:** storing anything in QSettings except non-secret cursor state (`ev`, last open case,
filter state, notification on/off). No token, ever.

---

## 6. PySide component tree and the signal/slot contract

### 6.1 Package layout

```
modules/aipacs_chat/
  __init__.py
  feature_flags.py             AIPACS_CHAT env var + config/aipacs_chat/aipacs_chat.json
  services/                    ── NO Qt imports at all ───────────────────
    models.py                    the dataclasses of §4
    chat_client.py               REST over Identity's AipacsWebClient; retry; 401 policy
    sync_engine.py               cursor, cold resync, req-ordering, cadence, visibility
    cursor_store.py              QSettings-free persistence of ev / last case / filters
  qt/                          ── the ONLY bridge ────────────────────────
    repository.py                ChatRepository(QObject) — the single thing the UI talks to
    workers.py                   QThread subclasses + the _LIVE_CHAT_WORKERS strong-ref set
  ui/                          ── PySide6 only, NO HTTP ──────────────────
    chat_widget.py               AiPacsChatWidget(QWidget) — the tab root, QSplitter
    conversation_list.py         QListView + QAbstractListModel + QStyledItemDelegate
    chat_view.py                 QListView + message delegate
    message_delegate.py          bubbles, ticks, edited/removed, reactions, Read more
    composer.py                  QPlainTextEdit; Enter sends, Shift+Enter newline
    case_panel.py                collapsible sections with one-line summaries
    filters_popover.py           ONE compact popover
    notifications.py             in-app popup + account-pill badge feed
    styles.py                    QSS builders from theme tokens
```

### 6.2 Widget tree

```
AiPacsChatWidget (QWidget, tab root)
└ QStackedWidget            states: not-configured / signed-out / loading / error / content
  └ content: QSplitter(Horizontal)
     ├ ConversationPane (QWidget)
     │   ├ header: search QLineEdit + FiltersPopoverButton (badge = activeCount) + counts chips
     │   └ ConversationListView (QListView + ConversationModel + ConversationDelegate)
     ├ ThreadPane (QWidget)
     │   ├ ThreadHeader   identity · status pill (tone) · presence dot · pin · actions ▾
     │   ├ ChatView       (QListView + MessageModel + MessageDelegate)
     │   ├ TypingStrip    patient typing / offline
     │   └ Composer       QPlainTextEdit + saved-reply picker + price + attach + Drive
     └ CasePanel (QScrollArea)
         identity → imaging → drive → location → CASE → provenance → mail → actions
         (order is deliberate: phone number and the patient's own words near the top)
```

Responsive: below a width threshold the splitter collapses to a single pane with back navigation
(`QSplitter.setSizes` + an inner `QStackedWidget`) — the same call the web console makes at 1024 px.

### 6.3 The signal/slot contract — `ChatRepository`

`ChatRepository` is the **only** object the UI imports from outside `ui/`. It owns the sync engine
and the workers; widgets never see HTTP, never see a thread, never touch a dataclass they did not
receive through a signal.

```python
class ChatRepository(QObject):
    # ── state / lifecycle ──────────────────────────────────────────
    stateChanged      = Signal(str)                 # notconfigured|signedout|loading|ready|error
    authRequired      = Signal(str)                 # human message; UI opens the sign-in dialog
    errorRaised       = Signal(str)                 # transient, non-fatal

    # ── list ───────────────────────────────────────────────────────
    rowsReplaced      = Signal(object)              # tuple[ConversationRow, ...]  (cold / filter change)
    rowsPatched       = Signal(object)              # tuple[ConversationRow, ...]  (delta)
    countsChanged     = Signal(object)              # Counts

    # ── thread ─────────────────────────────────────────────────────
    threadReplaced    = Signal(int, object)         # case_id, tuple[ChatMessage, ...]   (cold)
    messagesAppended  = Signal(int, object)         # case_id, tuple[ChatMessage, ...]
    messagesRevised   = Signal(int, object)         # case_id, tuple[ChatMessage, ...]
    presenceChanged   = Signal(int, bool, bool)     # case_id, patient_online, patient_typing
    receiptsChanged   = Signal(int, object, object) # case_id, read_at, seen_at
    caseStatusChanged = Signal(int, str, str)       # case_id, status, tone

    # ── side panel ─────────────────────────────────────────────────
    caseDetailLoaded  = Signal(object)              # CaseDetail

    # ── notifications ──────────────────────────────────────────────
    eventsArrived     = Signal(object)              # tuple[ConsoleEvent, ...]  (already de-duped by key)

    # ── optimistic write feedback ──────────────────────────────────
    sendAccepted      = Signal(str, object)         # local_id, ChatMessage
    sendFailed        = Signal(str, str)            # local_id, message

    # ── slots the UI calls (all return immediately; never block) ───
    @Slot(int)          def openCase(self, case_id: int) -> None
    @Slot()             def closeCase(self) -> None
    @Slot(object)       def setFilters(self, filters: Filters) -> None
    @Slot(bool)         def setVisible(self, visible: bool) -> None
    @Slot(bool)         def setTyping(self, typing: bool) -> None
    @Slot(str)          def sendMessage(self, body: str) -> str      # returns local_id
    @Slot(int, str)     def editMessage(self, message_id, body) -> None
    @Slot(int)          def removeMessage(self, message_id) -> None
    @Slot(int, object)  def react(self, message_id, value) -> None   # 1 | -1 | None
    @Slot(int)          def pinMessage(self, message_id) -> None
    @Slot(int)          def emailMessage(self, message_id) -> None
    @Slot(str, str)     def setStatus(self, status, note) -> None
    @Slot(object)       def sendPrice(self, offer: PriceOffer) -> None
    @Slot(str, bool)    def saveLink(self, url, primary) -> None
    ...
```

**Threading rules, taken from the codebase's own scar tissue:**

- Every network call runs in a `QThread` subclass with `done`/`failed` Signals. No `QThreadPool`.
- **A running worker always has a module-level strong reference.** `qt/workers.py` defines
  `_LIVE_CHAT_WORKERS: set` and `_retire_chat_worker(w)`, exactly like `_LIVE_AI_WORKERS` in
  `modules/viewer/interactor_styles/ai_chat_interactorstyle.py`. Dropping the last Python ref to a
  running `QThread` aborts the interpreter with *"QThread: Destroyed while thread is still running"*
  — no traceback, the log just stops.
- **On tab close / cancel: detach, never wait.** Disconnect `done`/`failed`/`finished`,
  `setParent(None)`, push onto `_ORPHANED_CHAT_WORKERS`, and release on `finished` — the EchoMind
  `cleanup()` pattern. The tab widget may be `WA_DeleteOnClose`.
- **A worker touches no Qt object.** It returns dataclasses; the GUI slot does the widget work.
- `QTimer.singleShot()` does not fire from a plain worker thread — use a bridge QObject created on
  the GUI thread.
- The poll tick itself is a `QTimer` on the GUI thread that does nothing but start a worker
  (`ConsultationPoller.poll_once` is documented as "never add a network call here: this froze the UI
  for 3–20 s per poll", and there is a test that fails if it takes >100 ms).

**Theming:** `get_theme_manager()`, `current_theme()` for tokens, connect `themeChanged`, restyle in
the slot. Never hard-code hex. `apply_global_app_theme` is already applied at app level (the OS
light/dark immunity fix) — the module inherits it and must not fight it.

**Feature flag:** `AIPACS_CHAT` env → `config/aipacs_chat/aipacs_chat.json {"enabled": true}` →
**default OFF**, in the exact `modules/cloud_consultation/feature_flags.py` idiom. Combined gate:
`aipacs_chat_available() = identity_module_enabled() and aipacs_chat_enabled() and is_module_enabled("aipacs_chat")`.

---

## 7. Gap analysis — web manager vs desktop module

### Reproduced in full

Conversation list with the compact filter popover, search, counts · chat view with in/out bubbles,
delivered/seen, timestamps, edit + withdraw own staff messages, copy, like/dislike, pin, Read-more
collapse · real-time via the cursor · case side panel with collapsible sections and one-line
summaries in the documented order · imaging links incl. unknown hosts · saved replies and pricing
tiers · notifications for `message` and `request` · e-mail sent/opened state and "e-mail this
message" · conversation identity display · visitor list · WordPress→form attribution in the panel.

### Deliberately NOT reproduced — and why

| # | Not built | Why |
|---|---|---|
| G1 | Patient chat UI, magic-link cookie auth, recovery flow | Separate surface, separate security model. Handoff §0.4. |
| G2 | `/forms-panel/greetings*` automation rules editor | Server-side automation config; belongs in the web console. Editing it from two places invites drift. |
| G3 | PWA plumbing (`manifest.webmanifest`, `sw.js`, `/offline`) | Browser-only concepts. |
| G4 | Crisp inbound mirroring administration | Read-only display of `source: crisp` + `external_url`; no management. |
| G5 | Server-side Drive credentials | The server holds **no** Google credential. Desktop keeps the same split: system-browser OAuth + loopback redirect, token in keyring, resumable upload **straight to Google**, only the *association* posted back. A 400 MB study must never pass through Laravel. |
| G6 | Row HTML rendering / `visitors/live` HTML fragment | We consume JSON rows only; §9.6 adds the JSON endpoint rather than parsing HTML. |
| G7 | Following `events[].url` | Every event carries an absolute **web console** URL (`/forms-panel/inbox/{id}`). The desktop module ignores it and opens the case in-app by `event.case`. Noted so nobody "fixes" it later. |
| G8 | Legacy `/inbox-list` and `/inbox/{case}/poll` | Superseded by `/sync`. Two templates for the same rows always drift. |
| G9 | Client-side status→tone map, `editable` derivation, `ago` computation | All server-computed. Duplicating them is the documented drift trap. |
| G10 | Multi-operator assignment / `assigned_to` management | Column exists; the web console has no UI for it either. Out of scope. |

### Open risks

- **R1 (blocking): authorization.** §0.1 / §9.0.
- **R2: shared write state.** §0.2 — the desktop client clearing `unread_for_staff` and cancelling
  `notify_staff_due_at` is correct *if* the manager is genuinely reading in the workstation, and
  wrong if they are not. Mitigated by an honest `visible` signal (§3.4) and by treating the two
  consoles as one operator, which is the truth today (single manager).
- **R3: `orderBy('id')` is absent server-side.** Client sorts defensively; a follow-up server fix is
  cheap and worth doing.
- **R4: no throttle on sync.** `/forms-panel/sync` has none; the patient twin has `throttle:240,1`.
  The API route gets an explicit throttle (§9.1).
- **R5: `Qss/main.qss` is a build artifact**, and the packaged copy of `modules/Identity` under
  `builder/plugin package/packages/identity/payload/...` will drift if we edit the shared
  `aipacs_web.py`. The `plugin_mirrors` release gate catches this — a mirror failure is a **shipping
  defect, never noise**.

---

## 8. Implementation plan — reviewable slices

Each slice is independently mergeable, ships with tests, and leaves the app working with the module
flag OFF. Nothing in the viewer, MPR, download or patient-list paths is touched at any point.

### Phase A — Laravel (`D:\...\laravel-back`), must land first

| Slice | Content | Tests |
|---|---|---|
| **A0** | **Authorization gate.** A `ChatAccess` policy/middleware answering "may this principal read the staff inbox / this case". Decide the rule with the owner (see the question below). Applied to *every* `/api/v1/chat/*` route. | Feature test per rule: paired-but-unauthorized token → 403 on sync, on `cases/{case}`, on every write |
| **A1** | `routes/api.php` → `Route::prefix('v1')->middleware(['auth:sanctum', ChatAccess::class, 'throttle:120,1'])->prefix('chat')`, delegating to the **same** controllers. No logic forked. | route-registration test; 401 without token |
| **A2** | `GET /chat/sync` → `StaffConsoleController::sync()` verbatim (already pure JSON). Add explicit `visible` handling docs. | mirror `RealtimeSyncTest` against the new URI |
| **A3** | JSON variants of every write in `StaffInboxController`, using `StaffDriveController`'s existing `done()`/`refuse()` pattern. Fix the one `price` error path that returns `back()` even for XHR. Pass `$viewerId` into `toStaffArray()` on `send` (today it is omitted, so `my_reaction` is always null). | one feature test per behaviour — module convention |
| **A4** | `GET /chat/cases/{case}` — full panel payload (§4.4), serializing the existing `PatientCase` summary methods. | shape test asserting every summary line is present |
| **A5** | `GET /chat/saved-replies` (tokens rendered server-side via `Pricing::render`), `GET /chat/pricing`, `GET /chat/statuses` | shape tests |
| **A6** | `GET /chat/visitors` — JSON rows from `StaffVisitorController::row()`, not the HTML fragment | shape test |
| **A7** | Defensive `orderBy('id')` in `CaseSync::newMessages()` / `revisedMessages()` (R3) | ordering test |

**Do not run `php artisan route:cache` in this project** — it freezes a conditional route prefix and
404s the consultation portal's login. `config:cache` and `view:clear` are fine.

### Phase B — Workstation (`E:\...\ai-pacs beta version`)

| Slice | Content | Tests (`tests/code/aipacs_chat/`) |
|---|---|---|
| **B0** | Package skeleton + `feature_flags.py` (default OFF) + `MODULE_CATALOG` entry + plugin-package definition + installer `.iss` lines | flag test (4 cases, the `test_feature_flags.py` template); `test_release_parity_guards` must stay green |
| **B1** | `services/models.py` + parsers, `chat_client.py` on top of `AipacsWebClient`, `AipacsWebError.status_code` | fake-session tests in the `tests/code/identity` idiom; 401 → `status_code == 401` |
| **B2** | `services/sync_engine.py` — pure, Qt-free, fully unit-testable: cursor arithmetic, cold resync, req-ordering, disjointness, cadence curve, backoff, `ev` persistence | the highest-value test file in the module: one test per rule in §3.3 and §3.4 |
| **B3** | `qt/repository.py` + `qt/workers.py` with `_LIVE_CHAT_WORKERS` / `_ORPHANED_CHAT_WORKERS` | off-thread guard test (`poll tick < 100 ms`, no network on `threading.main_thread()`); worker-lifetime test |
| **B4** | Tab wiring: left-menu button, `_HPModulesMixin.open_aipacs_chat`, `custom_tab_manager.add_aipacs_chat_tab`, `QStackedWidget` states, theming | offscreen-Qt open/close test; theme-change test |
| **B5** | Conversation list — model/view + delegate, filters popover, search, counts | model test with 500 synthetic rows |
| **B6** | Chat view + message delegate — bubbles, ticks, edited/removed, reactions, Read more (copy must copy the **whole** message, not the clamped text) | delegate size-hint + copy test |
| **B7** | Composer + writes — optimistic `sending` state owned by the composer, `sendAccepted`/`sendFailed`, edit/withdraw/react/pin, saved replies, pricing | write-path tests against a fake client |
| **B8** | Case side panel — collapsible sections in the documented order, one-line summaries from the server, journey/visitor, e-mail state, imaging links | panel-render test |
| **B9** | Notifications — in-app popup + account-pill badge (`badge_core` pattern), `ev` persisted with **no age limit**, banner for both `message` and `request` | event de-dup test; restart-is-not-a-cold-start test |
| **B10** | Drive — system-browser OAuth (`QDesktopServices.openUrl` + loopback), keyring token, resumable upload direct to Google, association posted to Laravel | association-only test (assert no bytes go to Laravel) |
| **B11** | Visitors pane | rows test |
| **B12** | Packaging + release-gate green: `plugin_mirrors`, `stage_plugin_packages`, `frozen_runtime_pyz`, `stage_config_parity`; `CONFIG_FAMILY_VERSIONS` + `FEATURE_FLAG_CONFIG_FILES` updated | `run_test.ps1` full pass |

Suggested review points: after **A0** (the authorization rule is a product decision), after **B2**
(the protocol engine is the whole reliability story), and after **B4** (first thing you can see).

---

## 9. Detail for the Laravel work

### 9.0 The authorization gate — needs your decision

`/forms-panel` today is "anyone who can log into the panel sees everything". Sanctum tokens are a
much wider audience. One of these rules must be chosen before A1:

- **(a) Role/ability gate** — only users with a `staff`/`manager` role (or a Sanctum token minted
  with a `chat:manage` ability) may reach `/api/v1/chat/*`. Everyone else gets 403. Simplest, and
  matches the single-manager reality today.
- **(b) Center scoping** — cases are filtered to the caller's center/clinic. More work; only worth it
  if more than one clinic will ever share the backend.
- **(c) Explicit allow-list** of user ids permitted to use the desktop console.

Recommendation: **(a)**, implemented as a Sanctum *ability* checked by middleware, plus a role check,
so a general workstation token cannot reach chat at all unless it was minted for it.

### 9.1 Route shape

```php
Route::prefix('v1')->group(function (): void {
    Route::middleware(['auth:sanctum', \App\Http\Middleware\ChatAccess::class, 'throttle:120,1'])
        ->prefix('chat')->group(function (): void {
            Route::get('/sync',                 [StaffConsoleController::class, 'sync']);
            Route::get('/cases/{case}',         [ChatCaseController::class, 'show']);
            Route::get('/saved-replies',        [ChatCatalogController::class, 'savedReplies']);
            Route::get('/pricing',              [ChatCatalogController::class, 'pricing']);
            Route::get('/statuses',             [ChatCatalogController::class, 'statuses']);
            Route::get('/visitors',             [StaffVisitorController::class, 'rows']);
            // writes → the SAME StaffInboxController / StaffDriveController methods
        });
});
```

### 9.2 The JSON pattern to copy (already in `StaffDriveController`)

```php
private function done(Request $request, array $payload) {
    return $request->expectsJson()
        ? response()->json(['ok' => true] + $payload)
        : back();
}
private function refuse(Request $request, string $field, string $message) {
    return $request->expectsJson()
        ? response()->json(['ok' => false, 'error' => $message], 422)
        : back()->withErrors([$field => $message]);
}
```
Note the module currently uses **both** `expectsJson()` (Drive) and `wantsJson()` (reactions).
Standardise on `expectsJson()`.

### 9.3 Writes needing a JSON variant

| URI (under `/chat`) | Fields / validation | JSON response |
|---|---|---|
| `POST /cases/{case}/send` | `body` req\|string\|max:4000; `ai_action` nullable\|max:32 | `201 {ok, message}` — pass `$viewerId` |
| `POST /cases/{case}/price` | `amount` nullable\|numeric\|1..100000; `currency` req\|size:3; `tier` nullable\|max:32; `body` nullable\|max:4000; `with_link` nullable\|bool | `201 {ok, message}` / `422 {ok:false, errors:{amount}}` |
| `POST /cases/{case}/status` | `status` req + `CaseStatus::isValid` (422); `note` nullable\|max:1000 | `{ok, status, status_tone, stage:{label,note,needs_action}}` |
| `POST /cases/{case}/upload` | `file` req; `is_report` nullable\|bool; ext ∈ jpg/jpeg/png/webp/heic/heif/pdf, sniffed mime must match, ≤20 MB | `{ok, message, file:{id,name,size,mime,url}}` |
| `POST /cases/{case}/rotate-link` | — | `{ok, link}` — token shown once, never stored or logged |
| `POST /cases/{case}/pin` | — (toggle, `saveQuietly`, no `updated_at` bump) | `{ok, pinned}` |
| `POST /cases/{case}/messages/{m}/edit` | `body` req\|max:4000; `isEditableByStaff` else 403 | `{ok, message}` |
| `POST /cases/{case}/messages/{m}/remove` | `isEditableByStaff` else 403 | `{ok, message}` |
| `POST /cases/{case}/messages/{m}/react` | `value` → normalised to 1/-1/null; 403 if removed | `{ok, id, mine, reactions}` |
| `POST /cases/{case}/messages/{m}/pin` | toggle, `saveQuietly` — **pins do NOT travel on the revision poll** | `{ok, pinned, pinned_at}` |
| `POST /cases/{case}/messages/{m}/email` | throttle:20,1; 4 guard failures | `{ok, send:{id,kind,state}}` / `422 {ok:false,error}` |
| `POST /cases/{case}/links` | `url` req\|max:2000 + `CaseFile::safeUrl`; `message_id` nullable\|int; `primary` nullable\|bool | `{ok, file:{…}, existing}` |
| `POST /cases/{case}/links/{f}/primary` | toggle | `{ok, primary_study_file_id}` |
| `POST /cases/{case}/links/{f}/forget` | staff-uploaded only, else 403 (patient links are evidence) | `{ok, deleted}` |
| Drive: `folder`, `folder/forget`, `attach`, `detach/{f}` | already JSON | unchanged |

⚠ **Message pins use `saveQuietly()` with timestamps off**, so a pin never appears in `revised[]`.
The client must refetch the case detail after pinning rather than waiting for the sync to carry it.

### 9.4 `payment_link` and `report` message types

Both constants exist and are branched on, but **nothing creates a message of either type**. The
client will render them defensively (unknown type → plain text body) rather than assuming they never
appear.

---

## 10. What I need from you before Phase A

1. **The authorization rule** (§9.0 a / b / c). This is the one genuine product decision and it
   blocks everything.
2. **Confirm the shared-write behaviour is wanted** (§0.2): when you read a conversation in the
   workstation, the web console's unread badge clears and its queued staff notification e-mail is
   cancelled. That is correct for a single manager and surprising for two.
3. **Confirm `AIPACS_WEB_BASE_URL` / `config/identity/aipacs_web.json` is already pointed at the
   production site on the workstations** that will run this — the chat module reuses it and does not
   introduce its own base URL.
4. Any objection to the one shared-file change (`AipacsWebError.status_code`), given the packaged
   Identity mirror under `builder/plugin package/` will need re-syncing.

---

*Nothing has been written to either repository yet. On approval I start with Phase A0/A1.*
