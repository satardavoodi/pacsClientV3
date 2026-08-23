# AI-PACS Chat in the DICOM Workstation — capability, gaps, and what to build

**For:** the AI development agent working inside
`E:\ai-pacs\ai-pacs codes\ai-pacs beta version`
**Written:** 2026-08-22, from a line-by-line reading of the code as it stands
today — not from the roadmap, not from memory, not from screenshots.
**Reference implementation:** the Laravel web console at
`ai-pacs.com/consult-form/forms-panel` (`modules/PatientChat`).

---

## 0. Read this first

**The module is already built.** `modules/aipacs_chat/` is 4,654 lines of
working, tested, three-layer Python that already does most of what a manager
console has to do. Several things that look missing from the outside are
present; several things that look present are wired to nothing.

So this document is deliberately shaped as three lists, in this order:

1. **What exists** (§2–§4) — do not rebuild any of it.
2. **What is built but unreachable** (§6) — the cheapest wins in the project.
   Six capabilities already have a client method or a signal and simply have
   no UI attached. These are hours of work, not days.
3. **What genuinely does not exist** (§7) — real new work, priority-ordered.

**The single most important instruction in this document:** before you write
any code, open the file named in the "Evidence" column of §5 and read it. This
codebase carries its reasoning in its docstrings, and most of those docstrings
exist because something failed in production once. A change that contradicts
one of them is a change that re-opens a closed bug.

### The three numbers that frame the work

| | |
|---|---|
| Workstation chat module today | **4,654 lines**, 16 files, 6 test files |
| Server endpoints available at `/api/v1/chat/*` | **27** |
| Server endpoints the workstation client can call | **23** (of which **13** reach a UI control) |

The gap is not mostly *protocol*. It is mostly *the last 15cm between a working
client method and a widget the operator can click*.

---

## 1. Deliverables

This document is the first of ten. Each is named here so the receiving agent
can track them; §11 gives the suggested order and sizing.

| # | Deliverable | Where |
|---|---|---|
| **D1** | Capability inventory of the existing workstation module | §2–§4 (this document) |
| **D2** | Capability inventory of the web console (the reference) | §5 (this document) |
| **D3** | **The gap-analysis matrix** | §5 (this document) |
| **D4** | Wire-contract reference: endpoints, DTO fields, cursor rules | §8 |
| **D5** | Invariants that must not be broken | §9 |
| **D6** | Architecture and threading guidance for new code | §10 |
| **D7** | Prioritised implementation plan with sizing | §11 |
| **D8** | Auth, roles and Google-identity model | §12 |
| **D9** | Desktop layout, readability and performance guidance | §13 |
| **D10** | Test plan for each new capability | §14 |

---

## 2. What exists — the shape of the module

```
modules/aipacs_chat/
├── __init__.py            PEP 562 lazy re-export; importing the package
│                          pulls nothing but the flag module
├── feature_flags.py       the 3-condition gate (see §12)
├── services/              NO Qt IMPORTS AT ALL — unit-testable headless
│   ├── models.py    597 l frozen dataclasses mirroring the server DTOs
│   ├── chat_client.py 387 l the /api/v1/chat/* client + error taxonomy
│   └── sync_engine.py 439 l cursor, cadence, visibility, backoff, dedupe
├── qt/                    the ONLY bridge; widgets never see HTTP or threads
│   ├── workers.py   206 l QThread lifecycle (three rules, see §10.2)
│   └── repository.py 530 l signals in, slots out, one request in flight
└── ui/                    PySide6 only, NO HTTP
    ├── chat_widget.py      688 l the tab root: 5 states, 3 panes
    ├── message_view.py     509 l transcript model/view/delegate
    ├── conversation_list.py 274 l list model/view/delegate
    ├── case_panel.py       339 l 8 collapsible sections
    ├── composer.py         236 l reply box + 3 dropdowns
    └── styles.py           213 l QSS from theme tokens; no hex outside it
```

The layering rule is stated in `__init__.py` and it holds throughout: services
know nothing about Qt, the UI knows nothing about the network, and the
repository is the only thing that knows both. **Keep it.** It is why the sync
rules can be tested without a `QApplication`, and that is the difference
between a poll loop you can trust and one you can only hope about.

### Integration points (all present and working)

| Surface | File |
|---|---|
| Left-menu button | `PacsClient/pacs/workstation_ui/AIPacs_ui.py:467–473, 1024, 1127–1133` |
| Tab factory | `.../home_ui/home_panel/_hp_modules.py:146–192` (`open_aipacs_chat`) |
| Singleton tab | `.../patient_tab/ui/patient_ui/custom_tab_manager.py:1257–1301` (`add_aipacs_chat_tab`) |
| Settings panel + "Test connection" | `.../settings_ui/consultation_education_settings.py:119–125, 1034–1067, 1176–1200, 1361–1382` |
| Tests | `tests/code/aipacs_chat/` — 6 files: client, widget, transcript, sync engine, repository off-thread, feature flags |

The tab is a singleton by design — `custom_tab_manager` refuses a second one
because "the console holds one poll loop and one cursor, and a second copy
would fight the first over the same read state." That is correct; do not add
a second entry point that bypasses it.

---

## 3. What exists — capability by capability

Every row below was verified in the source. Nothing here needs building.

### 3.1 Conversation list — `ui/conversation_list.py`

- `QAbstractListModel` + `QStyledItemDelegate`, **not a widget per row**, because
  the list repaints as often as every 800 ms and sixty widget trees would not
  survive that.
- Each row paints: presence dot (server-computed 45-second window), title with
  fallback (`label` → `#ref` → `#id`), server-rendered `ago` string, unread
  badge (red, "9+" cap), one-line preview prefixed `You:` for staff messages,
  status text in the status tone colour, `PINNED ·` marker, and a 3px tone
  spine down the left edge.
- **Selection survives a refresh** (`set_rows` re-selects the open case by id).
  This matters: rows reorder as messages arrive.
- `row_for_case()` resolves by id rather than by "whatever is selected", so a
  conversation opened from a notification or a deep link still resolves.

### 3.2 Transcript — `ui/message_view.py`

- Model/view/delegate again, keyed by message id, `_index_by_id` for O(1) merge.
- **Order is by id, never by timestamp** — timestamps collide at one-second
  resolution.
- `replace` (cold) / `append` (new) / `apply_revised` (patch in place), and the
  repository already emits revisions *before* appends.
- **Read receipts:** one tick = delivered, two = an operator had the
  conversation in front of them after the message was written. Derived from a
  single `read_at` timestamp so one number updates every row.
- **Auto-scroll only when already at the bottom** — it will not yank the view
  down while the operator is reading history.
- Long messages clamp at 12 lines with a clickable **Read more / Show less**.
- **Copy copies the whole body, never the clamped text.**
- Reactions line: "Patient liked", `+n` / `-n` staff tallies.
- System messages render centred with no bubble; automated staff messages get
  an amber left border rather than a badge.
- Context menu: **Copy · Like · Dislike · Clear my reaction · Pin/unpin ·
  Email to patient · Edit… · Withdraw**. Edit and Withdraw appear **only when
  the server said `editable`** — the rule is never re-derived locally.

### 3.3 Composer — `ui/composer.py`

- **Enter sends, Shift+Enter (or Ctrl+Enter) newlines.**
- **Saved replies** dropdown — bodies arrive with `{pay_basic}`/`{reference}`
  already substituted server-side; picking one *inserts* rather than sends.
- **Send a price…** dropdown — tier keys only, never a typed amount, because
  the amount-to-checkout-link pairing is owner-confirmed on the server.
- **Change status…** dropdown — filtered to `manual_only` transitions.
- 4,000-character clamp matching the server's validation.
- **The composer owns "sending"**: text is held in `_pending`, cleared on
  `confirm_sent()`, and **restored on failure** so nothing is lost to a dropped
  packet.
- Typing is a side effect of text, not an event — each keystroke pushes a
  4-second deadline that rides the already-scheduled sync.

### 3.4 Case side panel — `ui/case_panel.py`

Eight collapsible sections, each carrying a **one-line summary while collapsed**
so the whole case reads at a glance. Order is deliberate and was arrived at by
use: `Identity → Imaging → Drive → Location → Case → How they found us →
Email → Actions`. Identity opens by default.

Rendered content includes: name/reference/email/phone (as `mailto:`/`tel:`
links), online state, Crisp-mirrored note, imaging files with a ★ on the
primary study, Drive folder link or the suggested folder name, location line +
country + **the patient's local wall-clock time** (the field exists so nobody
calls a patient at 3am) + approximate-from-IP caveat, device label, modality,
status, stage label and note, the *"no price sent yet"* leak warning, source
label, landing page, referrer, journey steps, and the email-send list rendered
as **"sent"/"opened"** — deliberately not "delivered", because SMTP acceptance
says nothing about reaching an inbox.

All patient- and visitor-supplied strings are HTML-escaped (`_esc`) because the
labels render rich text so links work.

### 3.5 Real-time — `services/sync_engine.py`

This is the strongest part of the module and it is a faithful port of the web
console's own loop. Cadence, in milliseconds:

| State | Interval |
|---|---|
| Something moved in the last 30 s | **800** |
| Visible, idle | **3,000** |
| Not in front of the operator | **15,000** |
| Hidden > 15 min, notifications on | **45,000** |
| Hidden > 15 min, notifications off | **stop** |
| First poll after the tab opens | 400 |
| Became visible again | 60 (250 if it had gone dead) |
| Backoff after >2 consecutive misses | 800·2ⁿ, capped at 30,000 |

Implemented rules, each of which prevents a specific failure:

- **Out-of-order discard** — an answer whose `req` is older than the last
  applied one is dropped whole.
- **Wrong-conversation discard** — a thread for a case the operator has left is
  dropped, but the list, counts and events in the same payload are kept.
- **Cold answers replace, never merge** — merging one is how a read message
  goes unread again.
- **A failed request does not move the cursor** — every request is already a
  catch-up request, so there is no separate reconnect path to get wrong.
- **Event de-duplication on `event.key`**, never on `case`, with a 300-key ring.
- **The event cursor is persisted across restarts with no age limit**
  (`QSettings`, `notifications/event_cursor`). The web client expired its
  cursor after five minutes and silently lost roughly half its notifications;
  the desktop client deliberately does not repeat that.
- **`visible` is computed strictly** — current tab, active window, not
  minimised — because `visible=1` is what makes the server write
  `staff_last_read_at`, which is the patient's second tick. Over-reporting it
  would show a patient "read" for a screen nobody looked at.

### 3.6 States, theming, teardown — `ui/chat_widget.py`

- Five states in a `QStackedWidget`: not-configured / signed-out / loading /
  error / content. A transient error while the console is *already usable* does
  not blank the screen.
- Three-pane `QSplitter` at 320 / 760 / 320.
- Search box debounced at 350 ms (the server LIKE-scans message bodies).
- Four count chips: Unread · Online · Stalled · **No price** (the server calls
  it `none`; the label is spelled out because "None 4" means nothing).
- Full theme-token styling with live `themeChanged` re-styling.
- `cleanup()` **detaches** in-flight workers and never waits — a 15-second
  socket timeout on the close path would look like a hang.

---

## 4. What the tests already prove

`tests/code/aipacs_chat/` — 6 files. Notable coverage:

- the tab opens on **loading**, not on an empty list;
- each state shows its own page;
- **the selection survives a refresh**;
- a transient error does not blank a usable console;
- search is debounced and reaches the filters;
- **visibility is false for a tab that is not on screen**;
- closing stops the loop and persists the event cursor;
- the 401 policy: token discarded, no retry, and the discard never masks the
  401;
- a 404 on the chat routes reports "this server needs updating" rather than
  "conversation not found";
- an unpaired workstation is a **state**, not a crash.

Anything you add should arrive with tests in this register: behavioural, named
after the failure they prevent.

---

## 5. THE GAP MATRIX

Legend: **✅ done** · **🔌 built, not wired** (client method or signal exists,
no UI) · **❌ missing** · **—** not applicable

| # | Capability | Web console | Workstation | Evidence |
|---|---|---|---|---|
| 1 | Conversation list with presence, unread, preview, status | ✅ | ✅ | `ui/conversation_list.py` |
| 2 | Free-text search over name/ref/phone/message | ✅ | ✅ | `chat_widget.py:_apply_search` |
| 3 | **Faceted filters** (show/attention/presence/price/source/status) | ✅ `console-filters.blade.php` | 🔌 `Filters` model complete; only `term` reachable; count chips are `QLabel`, not buttons | `models.py:Filters`, `chat_widget.py:_chip` |
| 4 | Unread badge + bold row | ✅ | ✅ | `conversation_list.py` delegate |
| 5 | Unfiltered counts row | ✅ | ✅ | `models.py:Counts` |
| 6 | Open a conversation | ✅ | ✅ | `repository.openCase` |
| 7 | Transcript with ordering, revisions, cold replace | ✅ | ✅ | `message_view.py` |
| 8 | Delivered / read ticks | ✅ | ✅ | `MessageDelegate.paint` |
| 9 | Copy message | ✅ | ✅ | context menu |
| 10 | Edit message (server-gated) | ✅ | ✅ | `editable` flag honoured |
| 11 | Withdraw message | ✅ | ✅ | confirmed client-side |
| 12 | Like / Dislike / Clear reaction | ✅ | ✅ | `reactRequested` |
| 13 | Pin / unpin a message | ✅ | ✅ (action) | `repository.pinMessage` |
| 14 | **Pinned-message strip** at the top of the thread | ✅ `console-thread.blade.php:220,415` | ❌ — `GET /chat/cases/{id}` already returns a `pinned: [ids]` array that `CasePanel` ignores | `ChatApiController::case` |
| 15 | Email a message to the patient | ✅ | ✅ | `emailRequested` |
| 16 | **Reply / quote a specific message** | ⚠️ composer is labelled "Reply to …"; there is **no** reply-to field on the wire | ❌ same | `CaseMessage::toStaffArray()` has no parent/reply key |
| 17 | Saved replies | ✅ | ✅ | `composer.set_saved_replies` |
| 18 | Send a price (tier) | ✅ | ✅ | `composer.set_pricing` |
| 19 | Change status | ✅ | ✅ | `composer.set_statuses` |
| 20 | **Render a `price_offer` as an amount block** | ✅ | ❌ renders body text only | `console-thread.blade.php:274` |
| 21 | **Send an attachment** (`files[]`, images + PDF) | ✅ drag-and-drop + picker, ≤5 files, ≤20 MB | ❌ `ChatClient.send()` posts JSON only; composer has no attach control and no drop target | `chat_client.py:send`, `StaffInboxController::send` |
| 22 | **Render a received attachment** (thumbnail + open) | ✅ 44px thumbnail → `/file/{id}` | ❌ a `type='file'` message paints as its caption text | `message_view.py:paint` |
| 23 | **Open/download an attachment** | ✅ | ❌ no client method for `GET /chat/cases/{c}/file/{f}` | `routes/api.php:88` |
| 24 | **Final-report workflow** (PDF in chat + email + auto message) | ✅ `is_report` → `ReportDelivery` | ❌ `is_report` is never sent; depends on #21 | `ReportDelivery.php` |
| 25 | Case side panel with collapsible sections + summary lines | ✅ | ✅ | `ui/case_panel.py` |
| 26 | Email-send state (sent / opened) in the panel | ✅ | ✅ | `case_panel.py` mail section |
| 27 | Visitor presence / live-visitor strip | ✅ page + `/visitors/live` | 🔌 `ChatClient.visitors()` exists; no repository slot, no UI; `/visitors/count` not in the client | `chat_client.py:213` |
| 28 | **Pin a case** | ✅ | 🔌 `repository.pinCase` exists and is called by nothing; `CasePanel.pinCaseRequested` is declared, never emitted | `case_panel.py:105` |
| 29 | **Rotate the patient's access link** | ✅ | 🔌 `ChatClient.rotate_link` exists; no repository slot; `CasePanel.rotateLinkRequested` declared, never emitted | `chat_client.py:305` |
| 30 | **Imaging links: save / set primary / forget** | ✅ per-message "Save link" + panel controls | 🔌 all three client methods exist; no repository slot, no UI | `chat_client.py:310–330` |
| 31 | **Google Drive association** (link folder, attach, detach) | ✅ `/forms-panel/drive` | 🔌 all four client methods exist; no repository slot, no UI, no Google sign-in on the workstation | `chat_client.py:338–360` |
| 32 | **Notifications: banner / toast / sound** | ✅ ~400-line `console-notify.blade.php` + Notification API | 🔌 `repository.eventsArrived` is emitted and **connected to nothing**; `setNotificationsEnabled` is never called | `chat_widget.py:_connect_repository` |
| 33 | **Unread indicator outside the chat tab** (taskbar / tab badge / tray) | ✅ PWA app badge | ❌ none | — |
| 34 | **Jump to the conversation from a notification** | ✅ | ❌ `ConsoleEvent` carries `case`; nothing calls `openCase` from an event | `models.py:ConsoleEvent` |
| 35 | Auth: paired Sanctum token, 401 → re-pair, never retry | ✅ session | ✅ | `chat_client.py`, `Identity/providers/aipacs_web.py` |
| 36 | Operator authorisation | ✅ `EnsureStaff` | ✅ server-side `EnsureChatOperator` | see §12 |
| 37 | Google identity mapping | ✅ GIS token model (Drive, GSC) | ✅ different mechanism — Gmail **attestation**, id_token only, nothing stored | `aipacs_web.py:313–455` |
| 38 | Greetings CRUD | ✅ | ❌ no API route exists — out of scope | `routes/staff.php:125–137` |
| 39 | Metrics / Search Console page | ✅ | ❌ no API route exists — out of scope | `routes/staff.php:62` |
| 40 | **AI-agent (Secretary / CommandBus) control of the console** | — | ❌ the tab factory returns the widget "so the CommandBus can reach it", and nothing registers a command | grep of `modules/EchoMind/secretary` → 0 matches |
| 41 | `ai_action` tagging on an outbound message | ✅ accepted | 🔌 `ChatClient.send(ai_action=…)` exists; `repository.sendMessage` drops it | `repository.py:sendMessage` |

**Summary:** of 41 capabilities, **21 are complete**, **8 are built but
unreachable**, **10 are genuinely missing**, and **2 are out of scope** (no API
route exists for them). One of the ten — reply/quote (#16) — is missing from
the web console too, so it is a product decision rather than a parity gap.

---

## 6. Built but unreachable — the cheap wins

These are the highest value-per-hour items in the project, because the hard
part (the protocol, the threading, the error taxonomy) is already done and
tested. Each is "add a slot, add a control, connect them".

### 6.1 Notifications — the biggest one (matrix #32, #33, #34)

`ChatRepository.eventsArrived` fires with a tuple of already-de-duplicated
`ConsoleEvent`s on every poll that carries new ones. **`chat_widget.py` never
connects it.** The de-duplication, the persisted cursor, the 45-second watch
cadence and the `should_alert` policy (`message` and `request` interrupt;
`status` and `unsubmitted` do not) are all implemented and doing nothing.

What to build:

1. Connect `eventsArrived` in `_connect_repository`.
2. A non-modal, auto-dismissing in-app banner near the top of the content page,
   showing `event.title` / `event.body` / `event.who`. **Never a `QMessageBox`** —
   a modal that steals focus while a radiologist is reporting is worse than no
   notification.
3. Clicking it calls `self._on_case_activated(event.case)`. **Use `event.case`,
   never `event.url`** — the `url` is an absolute *web console* address and the
   model's docstring says so explicitly, so nobody later "fixes" the module by
   opening a browser.
4. A tray notification via `QSystemTrayIcon.showMessage` when the workstation
   window is not active, gated on `event.should_alert`.
5. An unread count on the tab title and/or the left-menu button, driven by
   `countsChanged`.
6. A Settings checkbox wired to `repository.setNotificationsEnabled()` — the
   engine already uses it to decide whether a long-hidden console keeps a slow
   watch or stops entirely.

### 6.2 Faceted filters (matrix #3)

`Filters` is fully modelled — `show`, `attention[]`, `presence`, `price`,
`sources[]`, `statuses[]`, `term` — with correct wire names (single-value
groups post bare, multi-value groups post bracketed), an `active_count` that
mirrors the server's badge, and defaults omitted from the query string. Only
`term` is reachable.

Cheapest useful step: **make the four count chips clickable toggles.**
"Unread" and "Stalled" map to `attention`, "Online" to `presence`, "No price"
to `price`. That is four `QPushButton`s and one `setFilters` call, and it
covers the questions an operator actually asks. A full popover mirroring
`console-filters.blade.php` can follow.

### 6.3 Case actions: pin and rotate link (matrix #28, #29)

`CasePanel` declares `pinCaseRequested` and `rotateLinkRequested`, emits
neither, and its Actions section currently contains a note telling the operator
to *"use the conversation menu"* — a menu that does not exist. Add two buttons,
emit the signals, connect them in `chat_widget.py`. `repository.pinCase`
already exists; `rotateLink` needs a four-line repository slot around
`ChatClient.rotate_link`.

**The rotated link is shown once and never stored.** Present it in a dialog
with a copy button; do not write it to `QSettings`, a log, or the panel.

### 6.4 Imaging links (matrix #30)

`save_link`, `set_primary_link` and `forget_link` all exist on the client.
Add repository slots and:

- a **Save link** action in the transcript context menu, enabled when the
  message body contains a URL (mirroring the web's per-message button);
- **Set as primary** / **Forget** actions on the rows the Imaging section
  already renders.

**`forget_link` only works on a link an operator saved** — the server refuses
to forget a patient's link, because a link the patient sent is evidence of what
they sent and when. Surface the refusal, do not hide the control.

### 6.5 Visitors (matrix #27)

`ChatClient.visitors(live_only=…)` exists. `GET /chat/visitors/count` exists on
the server and is *not* in the client — add it (two lines). A small "N visitors
on the site now" strip above the conversation list, refreshed on the same
cadence, is the whole feature.

### 6.6 `ai_action` (matrix #41)

`ChatClient.send()` accepts it; `ChatRepository.sendMessage()` does not pass it
through. One parameter. Needed the moment anything automated writes a message
(see §15).

---

## 7. Genuinely missing — real work

### 7.1 Attachments (matrix #21, #22, #23) — **the top priority**

This is the largest functional hole and the one an operator will hit first.
The server side is complete and shared with the web console:

```
POST /api/v1/chat/cases/{case}/send        multipart: body?, files[], is_report?
POST /api/v1/chat/cases/{case}/upload      multipart: file, is_report?
GET  /api/v1/chat/cases/{case}/file/{file} the bytes
```

Limits, from `CaseFileStore`: **5 files, 20 MB each.** Validation is
**all-or-nothing** — the controller pre-flights every file with `problemWith()`
before writing any of them, because there is no unsend. Match that in the UI:
reject the whole batch with one message rather than sending three of five.

**Receiving is easier than sending and should ship first.** A `type='file'`
message already arrives with everything needed — `toStaffArray()` sends `meta`
raw (not the patient whitelist), so `message.meta_value('file_id')`,
`'file_name'`, `'file_size'`, `'mime'` and `'is_image'` are all available in
`MessageDelegate.paint` **today**. Draw a small attachment chip; on click, fetch
`/file/{id}` on a worker and open it with `QDesktopServices.openUrl` from a temp
file.

Sending, in order of value:

1. A paperclip button opening `QFileDialog` (images + PDF).
2. `setAcceptDrops(True)` on the composer with a drop overlay — this is the
   feature the owner asked for on the web side and the reason it exists there.
3. Ctrl+V of an image from the clipboard.
4. A removable thumbnail tray above the reply box; text sends as the caption of
   the **last** file (that is what the server does).

Client work: `ChatClient.send()` needs a multipart path. The Identity module's
`AipacsWebClient.request_json` takes `json_body`; check whether it can carry
`files=` and extend it there rather than opening a second `requests` session in
`aipacs_chat` — the whole point of `chat_client.py` is that there is one client.

### 7.2 The final-report workflow (matrix #24)

Depends entirely on 7.1. Once attachments send, this is **one checkbox**:
"This is the final report", which adds `is_report=1` to the multipart body. The
server then, in this order: posts the PDF in the chat, sends the predefined
"your report is ready" message, transitions the case to `report_ready`, and
emails the PDF to the patient (≤12 MB) — with the email last and fallible on
purpose, so a mail failure can never undo the delivery.

The workstation must **not** re-implement any of that. Send the flag; render
the returned `report` payload.

### 7.3 Pinned-message strip (matrix #14)

`GET /chat/cases/{id}` already returns `pinned: [message_id, …]`.
`CasePanel.set_case()` reads `d.get("pinned")` only as a case-level boolean and
ignores the array.

**A pin never arrives on the poll.** It is written with `saveQuietly()` and
timestamps off — deliberately, because an operator's private annotation must
not look like patient activity — so it can never appear in `revised[]`. The
client learns about a pin from exactly two places: the `pinMessage` POST
response, and a refetch of the case. `chat_widget._on_write_succeeded` already
refetches on `pin_message`; you only need to render the result.

### 7.4 Price-offer rendering (matrix #20)

`type='price_offer'` messages carry `amount`, `currency` and `tier` in `meta`
and currently paint as plain body text. A small amount block in the delegate,
mirroring `console-thread.blade.php:274`.

### 7.5 Reply / quote (matrix #16) — **needs a server change first**

Be careful here: **the web console does not have this either.** Its composer is
*labelled* "Reply to <name>", and `console-styles.blade.php` has a `quote`
class for rich-text blockquotes, but `CaseMessage::toStaffArray()` has no
parent-message field and neither client can express "this message replies to
that one". Building it means a migration, a DTO field, and both clients. Treat
it as a product decision, not a parity gap.

---

## 8. D4 — the wire contract

### 8.1 Endpoints (`/api/v1/chat`, behind `api` + `auth:sanctum` + `EnsureChatOperator` + throttle)

| Method | Path | In the workstation client? |
|---|---|---|
| GET | `/sync` | ✅ |
| GET | `/cases/{case}` | ✅ |
| GET | `/saved-replies` | ✅ |
| GET | `/pricing` | ✅ |
| GET | `/statuses` | ✅ |
| GET | `/visitors` | ✅ (no UI) |
| GET | `/visitors/count` | ❌ |
| POST | `/cases/{case}/send` | ✅ (JSON only — no `files[]`, no `is_report`) |
| POST | `/cases/{case}/price` | ✅ |
| POST | `/cases/{case}/status` | ✅ |
| POST | `/cases/{case}/rotate-link` | ✅ (no UI) |
| POST | `/cases/{case}/pin` | ✅ (no UI) |
| POST | `/cases/{case}/upload` | ❌ |
| GET | `/cases/{case}/file/{file}` | ❌ |
| POST | `/cases/{case}/messages/{m}/email` | ✅ (throttle 20/min) |
| POST | `/cases/{case}/messages/{m}/edit` | ✅ |
| POST | `/cases/{case}/messages/{m}/remove` | ✅ |
| POST | `/cases/{case}/messages/{m}/react` | ✅ |
| POST | `/cases/{case}/messages/{m}/pin` | ✅ |
| POST | `/cases/{case}/links` | ✅ (no UI) |
| POST | `/cases/{case}/links/{file}/primary` | ✅ (no UI) |
| POST | `/cases/{case}/links/{file}/forget` | ✅ (no UI) |
| GET | `/drive/cases` | ❌ |
| POST | `/drive/case/{case}/folder` | ✅ (no UI) |
| POST | `/drive/case/{case}/folder/forget` | ✅ (no UI) |
| POST | `/drive/case/{case}/attach` | ✅ (no UI) |
| POST | `/drive/case/{case}/detach/{file}` | ✅ (no UI) |

### 8.2 The sync cursor

Four numbers, echoed back verbatim, **all in the query string** — the server
reads them through `$request->query()` exclusively, and a client that sends a
JSON body looks permanently cold: `rev=0` every poll, full state every time,
forever.

```
m     highest message id already drawn
rev   unix seconds; anything updated after this is stale on screen
ev    highest console-event id already announced
req   the client's own counter, echoed back untouched
```

Plus `visible` (0/1), `typing` (0/1), `case`, and the filter pairs.

**`visible` defaults to TRUE server-side when the parameter is absent.** A
client that forgets it claims to have read everything.

### 8.3 Envelope shapes

- `rows[]` → `ConversationRow`. Note the key is **`tone`** here and
  **`status_tone`** on the thread. They are genuinely different keys.
- `thread.messages` (new) and `thread.revised` (patched) are **disjoint by
  construction**. Apply `revised` first, then `messages`.
- `counts` is **unfiltered on purpose** — a manager filtered to one view must
  still be told a consultation arrived outside it.
- `cold: true` means replace state wholesale.
- Timestamps mix forms deliberately: `rows[].at`, `read_at` and `events[].at`
  are unix ints; `messages[].at` is ISO-8601. `models._ts` normalises both.
- `ago` is **rendered and localised server-side**. Display it; never cache it,
  never recompute it.

---

## 9. D5 — invariants that must not be broken

Each of these is enforced somewhere in the code and each exists because of a
real failure. Breaking one is a regression even if every test still passes.

1. **The server decides `editable`, `tone`, `ago`, and delivery state.** A
   client that re-derives any of them shows a button the controller refuses,
   or paints a chip a different colour from the web console.
2. **A withdrawn message is a tombstone, not a gap.** Keep the row.
3. **Never leave the previous patient's words on screen** while the next
   conversation loads. `_on_case_activated` clears the transcript *immediately*,
   before the answer lands. This is the one mistake this module must never make.
4. **Guard every thread signal with `_is_open(case_id)`.** A case-detail fetch
   is a separate request with its own flight time, and painting the wrong
   patient into an open panel is the failure this module is most careful about.
5. **`visible` must mean an operator is actually looking.** Do not relax
   `_is_really_visible()` to make the ticks "work better".
6. **One request in flight at a time.** The cursor is single state.
7. **A running `QThread` always has a module-level strong reference**, and
   teardown **detaches** — never `wait()`. See §10.2.
8. **A worker touches no Qt object.** It returns plain data.
9. **The poll tick starts a thread and returns.** There is a test elsewhere in
   this repo that fails if a poller tick takes more than 100 ms.
10. **401 discards the token and stops.** Never retry a dead token — a silent
    retry loop against a revoked credential is indistinguishable from an attack.
11. **A 404 on `/chat/*` means the server build is old**, not "case not found".
    Keep `ChatApiMissingError` distinct.
12. **The event cursor is persisted with no age limit.**
13. **Never send an amount from the client.** Tiers only.
14. **The rotated access link is shown once and never stored.**
15. **`forget_link` is operator-links only.** The server enforces it.
16. **No Google credential ever reaches Laravel.** The Drive design is
    association-only: the client talks to Drive directly and posts back only
    the fact that a folder belongs to a patient. A 400 MB study must never pass
    through the web server.
17. **The module is import-cheap.** Importing `modules.aipacs_chat` must not
    pull PySide6, `requests`, or the Identity module. Keep heavy imports inside
    the functions that need them.
18. **The gate is `aipacs_chat_available()`** — all three conditions. Never
    check `aipacs_chat_enabled()` alone.

---

## 10. D6 — architecture and threading guidance

### 10.1 Where new code goes

| If it… | It belongs in |
|---|---|
| parses a wire shape | `services/models.py` |
| calls an endpoint | `services/chat_client.py` |
| decides *when* or *whether* | `services/sync_engine.py` |
| runs off the GUI thread or emits a signal | `qt/repository.py` |
| draws or takes a click | `ui/…` |

If you find yourself importing `requests` inside `ui/`, or `PySide6` inside
`services/`, the code is in the wrong file.

### 10.2 The three worker rules (`qt/workers.py`)

A running `QThread` whose last Python reference is dropped is finalised by the
garbage collector while still running, and Qt answers with `qFatal` — `abort()`,
no traceback, no faulthandler entry, the log simply stops. This codebase has
paid for that twice (OPT-51 Eagle Eye, 2026-08-03; EchoMind `ApiWorker`,
2026-07-12).

1. **A running worker always has a module-level strong reference**
   (`_LIVE_CHAT_WORKERS`), not an attribute on a widget that dies with it.
2. **Teardown detaches, never waits** — disconnect, `setParent(None)`, park in
   `_ORPHANED_CHAT_WORKERS`, release on `finished`.
3. **A worker touches no Qt object.**

Use `start_chat_worker(...)` for every new call. Do not hand-roll a `QThread`.

### 10.3 Adding a capability — the shape

```python
# 1. services/chat_client.py — the endpoint
def download_file(self, case_id: int, file_id: int) -> bytes: ...

# 2. qt/repository.py — a signal, and a slot that runs it off-thread
fileDownloaded = Signal(int, object)

@Slot(int)
def downloadFile(self, file_id: int) -> None:
    case_id = self._engine.open_case
    if not case_id:
        return
    self._write("file", lambda: self._ensure_client().download_file(case_id, file_id))

# 3. ui/ — a control that emits, and a slot that draws
```

Nothing else. If a new capability needs a fourth step, it is probably deciding
something the server already decided.

---

## 11. D7 — prioritised plan

Sizing is relative: **S** ≈ hours, **M** ≈ a day, **L** ≈ several days.

| Order | Item | Size | Why here |
|---|---|---|---|
| 1 | **Notifications wired end-to-end** (§6.1) | **M** | The engine already does the hard part. Without it, the console only works while somebody is staring at it — which defeats the point of putting it in the workstation. |
| 2 | **Render + open received attachments** (§7.1, receive half) | **M** | The data already arrives. Today an operator is told "Sent an image" and cannot see it. |
| 3 | **Send attachments** (§7.1, send half) | **L** | The largest genuine hole; the owner's stated priority on the web side. |
| 4 | **Final-report checkbox** (§7.2) | **S** | One flag, once #3 lands. |
| 5 | **Count chips become filter toggles** (§6.2) | **S** | Four buttons over a complete model. |
| 6 | **Pin / rotate-link buttons** (§6.3) | **S** | Removes a panel note that points at a menu that does not exist. |
| 7 | **Pinned-message strip** (§7.3) | **S** | Data already fetched. |
| 8 | **Imaging-link actions** (§6.4) | **M** | Three client methods already written. |
| 9 | **Price-offer rendering** (§7.4) | **S** | Cosmetic but it is how an operator checks what was quoted. |
| 10 | **Visitors strip** (§6.5) | **S** | |
| 11 | **Full filter popover** (§6.2) | **M** | After the chips prove the shape. |
| 12 | **Drive association UI** (matrix #31) | **L** | Needs a Google sign-in path on the workstation; largest new surface; lowest daily value. |
| 13 | **Secretary / CommandBus commands** (§15) | **M** | Do after the UI settles, so the commands drive real slots. |
| — | Reply/quote (§7.5) | — | Needs a server change and a product decision. Not a parity gap. |

---

## 12. D8 — auth, roles, Google identity

### 12.1 How the workstation authenticates

There is **no chat-specific login.** The module has no credentials of its own —
that is stated in `feature_flags.py` and it is why the Identity module is one of
the three gate conditions.

```
Operator pairs the workstation once (Settings → AI-PACS Consultation)
   → POST {base}/api/v1/auth/workstation/pair   {email+password | pairing_code}
   → Sanctum token
   → stored in the OS keychain / DPAPI via modules.Identity.secure_store
   → every /api/v1/chat/* call is Bearer that token
```

- The base URL is the **Identity module's** (`AIPACS_WEB_BASE_URL` /
  `config/identity/aipacs_web.json`), deliberately not a setting of this
  module's own — a second copy of the address is a second thing to get wrong
  the day the site moves.
- Raw credentials are never persisted. The token never touches the AI-PACS
  server login.
- On 401 the token is deleted from the keychain but the identity row stays,
  because that row is what tells the console *which account* to offer to sign
  back in as.
- `Identity.thread_guard.assert_off_gui_thread` raises if any of this is called
  on the GUI thread. That is a feature — an accidental GUI-thread poll fails
  loudly instead of freezing the workstation for twenty seconds.

### 12.2 The three-condition gate

`aipacs_chat_available()` is true only when **all three** hold:

1. the Identity module is enabled,
2. `AIPACS_CHAT` (env) or `config/aipacs_chat/aipacs_chat.json` says on
   — **default OFF**, and the build sanitizer forces it back to OFF in a
   shipped build,
3. `aipacs_runtime.is_module_enabled("aipacs_chat")` — the commercial registry,
   which **fails open** so a licensed module never silently refuses to open.

### 12.3 Roles and permissions

**Authorisation is entirely server-side**, and that is the correct design — a
desktop client cannot be trusted to enforce it.

`EnsureChatOperator` (after `auth:sanctum`):

- 401 without a token;
- **403 unless the token carries `ChatOperators::ABILITY`** — deliberately
  inert today, because `WorkstationPairController` mints tokens with `['*']`;
  the check exists so that the day pairing learns to issue scoped tokens, an
  unscoped one is refused without anyone remembering to add it;
- **403 unless `ChatOperators::allows($user)`** — `users.is_admin`, or the
  `PATIENTCHAT_CONSOLE_OPERATORS` allow-list.

The workstation therefore needs no role model. What it *should* do is render a
403 clearly: `ChatTransportError` carries `status_code`, so a 403 can say
*"this account is not a chat operator"* rather than *"could not reach the
server"*. Today it does not — a small, worthwhile fix.

### 12.4 Google identity — three separate identities, by design

Do not conflate these. They are independent and must stay so:

| | Identity | Mechanism | Storage |
|---|---|---|---|
| A | Workstation ↔ AI-PACS web | email+password or pairing code → Sanctum token | OS keychain |
| B | Google Drive (the clinic hub account) | GIS token model, browser-side | a JS closure; **no refresh token** |
| C | Google Search Console | GIS token model, browser-side | a JS closure |

The workstation adds a fourth, distinct thing: **Gmail attestation**
(`aipacs_web.py:313–455`, ADR-0008). The operator proves ownership of a Gmail
through a *transient* Google OAuth with `openid` + `email` scopes **only —
never Drive**; the resulting id_token goes to Laravel's `link-google`, which
verifies it and returns a Sanctum token. The critical invariant is stated in
the source: **the OAuth credentials are discarded, and no personal Google
identity is stored.**

If you build the Drive UI (matrix #31), it needs a *new* Google sign-in on the
workstation with Drive scope, and it must not reuse or contaminate the
attestation path.

---

## 13. D9 — layout, readability, performance

### 13.1 Layout

The current three-pane splitter (320 / 760 / 320) is right for a workstation
monitor and should stay. Two things worth adding as the panes fill up:

- **Persist splitter sizes** in the existing `QSettings` group — an operator
  who widens the transcript should not lose it on the next launch.
- **Collapse the case panel** below a window width where 320px of panel costs
  more than it gives.

### 13.2 Readability

The delegate already handles the hard parts: 72%-width bubbles, per-character
breaking for a URL longer than the bubble (visitor-supplied strings do this
routinely), a 12-line clamp with Read more, and three visual voices
(patient / operator / automated). Two things are missing and both are cheap:

- **Day separators** in the transcript. Only `HH:MM` is shown per message, so a
  conversation spanning three days reads as one block.
- **A selectable transcript.** `QListView.NoSelection` plus a paint-based
  delegate means an operator cannot select a phrase — only "Copy message" for
  the whole body. Consider a "Copy selection" affordance or a read-only detail
  view for long clinical text.

### 13.3 Performance

The existing choices are correct and should be preserved: model/view everywhere,
no widget per row, one HTTP request in flight, catalogue fetched once per
session rather than per poll, and search debounced at 350 ms.

Things to watch as you add:

- `ChatView.message_by_id` is a linear scan over the model. It is called from
  the edit path only, so it is fine today; if you call it per paint it will not
  be.
- `MessageDelegate._layout` re-wraps text on **every** `sizeHint` and every
  `paint`. On a thousand-message transcript at 800 ms that will show. If the
  transcript starts to feel heavy, cache the wrap by
  `(message.id, bubble_width, expanded)` before optimising anything else.
- The attachment work (§7.1) must **not** decode thumbnails on the GUI thread.
  Fetch and scale on a worker, cache by `file_id`, hand the delegate a
  ready-made `QPixmap`.

---

## 14. D10 — test plan

The suite is green by default in this repo and must stay that way. Run
`.\run_test.ps1 -Fast`, or `python -m pytest tests/code/aipacs_chat -q -p no:debugging`.

Write tests in the existing register — behavioural, named after the failure:

| Capability | Tests to write |
|---|---|
| Notifications | a `message` event raises exactly one banner; the same event key twice raises one; a `status` event raises none; clicking opens the case **by id, not by url**; the cursor survives a restart |
| Attachments (receive) | a `type='file'` message renders a chip carrying `meta.file_id`; a *removed* file message renders no chip (the server nulls `meta` on a tombstone — verify this, it is easy to miss) |
| Attachments (send) | six files are refused as a batch with one message and **nothing is uploaded**; a 21 MB file is refused before any request; a failed send restores the text **and** the tray |
| Final report | `is_report` is present in the request exactly when the checkbox is ticked |
| Filters | each chip produces the right query pairs; multi-value groups repeat their bracketed key; defaults are omitted |
| Pin strip | a pin arrives from the POST response and from a case refetch, and **never** from a sync answer |
| Rotate link | the link is displayed and appears in no persisted store |
| Price offer | an amount block renders; a `price_offer` with no amount falls back to the body |

For anything touching the sync loop, add to `test_sync_engine.py` — it needs no
`QApplication` and no network, which is exactly why the rules live there.

---

## 15. AI-agent capabilities inside the workstation

Today: **nothing.** `open_aipacs_chat` returns the widget with a docstring
saying "so the Secretary CommandBus can reach it later", and a search of
`modules/EchoMind/secretary` finds no reference to chat at all.

The module is unusually well-shaped for this, because `ChatRepository` is
already a clean command surface — eleven `@Slot` methods with primitive
arguments. A CommandBus adapter should call those slots, **never** the client
directly, so that every automated action goes through the same cursor,
threading and error handling as a human click.

A safe first command set:

| Command | Slot |
|---|---|
| open the console | `_hp_modules.open_aipacs_chat` |
| open a conversation | `repository.openCase(case_id)` |
| read the current transcript | `ChatView.message_by_id` / model read |
| draft a reply into the composer | `composer.editor.setPlainText` — **draft, do not send** |

**Two rules for anything automated:**

1. **A machine must not send a message to a patient without a human pressing
   send.** Draft into the composer; let the operator read it. This is a
   clinical-communication product, and the composer's own design already
   assumes a human adds a sentence to every saved reply.
2. **Anything a machine does write must carry `ai_action`** (matrix #41,
   §6.6). The server stores it and the transcript can then distinguish an
   automated line from a typed one — the same reason `is_automated` gets an
   amber left border today.

---

## 16. Two open questions for the owner, not for the agent

1. **Reply/quote (§7.5)** — neither client has it and the wire has no field for
   it. Worth building, or is "Copy message" enough?
2. **Drive on the workstation (matrix #31)** — the client methods exist, but
   the UI needs a Google sign-in with Drive scope on the desktop, which is a
   fourth Google identity path in a product that already carefully keeps three
   apart. Confirm this is wanted before building it.

---

## 17. Where to look — quick index

| To understand… | Read |
|---|---|
| Why any of it is shaped this way | `modules/aipacs_chat/__init__.py` |
| The wire shapes | `services/models.py` |
| Every endpoint + the 401/404 policy | `services/chat_client.py` |
| Cadence, cursor, visibility, backoff | `services/sync_engine.py` |
| Thread safety | `qt/workers.py` |
| Signals and slots | `qt/repository.py` |
| States, panes, visibility, teardown | `ui/chat_widget.py` |
| The gate | `feature_flags.py` |
| Pairing and the token | `modules/Identity/providers/aipacs_web.py` |
| The server's own reasoning | `modules/PatientChat/routes/api.php` (Laravel) |
