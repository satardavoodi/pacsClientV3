# Secretary conversation identity

Each memory has a canonical UUID independent of mode, a short English title,
topic, goal and rolling context summary. Explicit mode remains authoritative.
New and automatic ten-cycle rollover create a fresh identity and empty context;
rollover occurs before planning reads old history. Older memories remain private.

The authenticated Eagle Eye router derives descriptions in its existing model
request; there is no extra inference request or client provider route. The server
binds identity and mode itself, validates bounded fields and quotes metadata in
Act planning and Ask/Guide/Help Ticket answers. Missing upstream descriptions keep
prior metadata. An old server that cannot acknowledge conversation identity fails
closed with an update message. This requires the matching server revision.

Metadata is context, not permission, tool availability or proof of completion.
Live facts still require typed MCP reads and execution still requires local
CommandBus/confirmation checks. The title prompt excludes patient identifiers and
secrets; local memory and metadata remain private sensitive conversation data.
Do not export them into fixtures or public diagnostics.

The compact footer shows mode, title and existing memory/cycle counters. Its
plain-text tooltip contains the full identity, topic, goal and summary. Mode
switching retains identity; New also resets the pending session namespace.
Metadata is saved alongside the memory text as .conversation.json on cycle close.
No new GUI-thread filesystem or network work was added to the footer refresh.

Verification: three new guards failed before implementation. Seven synthetic guards
plus existing focused server/memory/English/response/Ask tests pass: 67 tests.
Qt presentation was tested offscreen; this is not native acceptance. The existing
control client ping cannot reach the local test listener. No app or service was
restarted, and no clinical actions were executed.

Developer synchronization and activation are separate: the owner-scoped delta is
staged in the inactive Razi Developer candidate with hash receipts in the private
parity workspace. Complete inventory parity must be evaluated from that receipt;
unrelated concurrent differences block full completion/build handoff. No asset,
model weight, credential, database or host configuration is changed by this work.
