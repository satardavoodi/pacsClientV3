# Client AI connection settings — 2026-10-08

## User-requested behavior

Standard Client Settings > AI now has EchoMind, Eagle Eye, Agent and Connection
subtabs. Connection is the fourth tab when EchoMind is enabled. The Server role
retains the original three tabs and its existing listener/PACS/service settings.
Source remains shared and synchronized; behavior is selected by the existing
settings role, without a new feature flag or alternative connection configuration.

Connection hosts the existing Eagle Eye authenticated URL, credential-file and
TLS pairing controls; this shared connection serves company Eagle Eye, EchoMind
and Agent AI requests. Existing Save/Test/Reload workers and assistant refresh
receipts keep the same form owner and persisted format. Eagle Eye retains its
job table and refresh action. The Server Settings connection shortcut selects
Connection on Client and Eagle Eye on Server.

EchoMind backend selection, proxy, personal OpenAI-compatible API fields and
voice-to-text connection controls move to Connection. Personal prompt editors
and functional templates stay in EchoMind. Direct personal mode still requires
user-owned credentials and explicit personal prompts; no company-provider
fallback or new direct provider route was introduced. Client company credential
controls are hidden, and company authentication/usage refresh no longer invokes
the upstream provider from this settings page. Server controls retain their
existing behavior; unmigrated unrelated legacy paths are not certified here.

Agent Gateway status, transport, pairing, MCP and relay controls move to Connection.
Device permissions and documentation remain in Agent. Gateway transport is local
workstation control, distinct from the shared outbound server AI connection.
No gateway was enabled, paired or restarted during verification.

## Implementation and verification

Existing controllers own their handlers and fields. Separate connection panels
are reparented into one lazy Connection page; revisiting other tabs does not
create duplicate forms or worker owners. No saved credential or endpoint was
changed or printed. No server listener configuration or active process changed.

Guards failed before the new layout (three failures; unchanged Server role passed).
A separate guard reproduced the prohibited Client company provider refresh before
its correction. Final local focused gate: 100 passed, covering role-specific
navigation, single-owner reparenting, field persistence patches, server settings,
worker boundaries and packaging inputs. Mirror dry-run found no affected payload
pair. No full build or installed-artifact acceptance was performed.

Live source-GUI acceptance is pending. Existing control MCP ping reports no local
listener; the human was asked to launch one fresh source Client with explicit test
control and sign in outside clinical work. Offscreen QWidget guards are automated
verification, not a live GUI pass. Razi runtime/role guards passed (99 passed,
one Git-dependent packaging guard deselected on the repeat run). The earlier
complete Razi run had 99 passes and that one failure because the copied candidate
has no .git metadata. The canonical Git snapshot guard passed locally. Verify page visibility, scrolling, backend
switching, Save/Test on the configured authenticated server and repeated navigation
in that session. Do not restart clinical work or enable the LAN gateway for tests.

The same role-aware source, tests and documents must be hash-verified in the Razi
non-running Developer candidate per DEVELOPER_SYNC_POLICY.md. Active SCM remains
separate. Required Server/Client PyInstaller and Nuitka artifact acceptance belongs
to BUILD.md/RELEASE.md; the new settings module is in the existing full-core source
package, with no new plugin or configuration-family format.

## Follow-up: simplified embedded control and colocated PACS

The owner confirms Eagle Eye Server is colocated with PACS. The source form now
loads the explicitly active workstation profile through an owned settings worker,
without migrating missing profile configuration. It preserves metadata scheme,
port and path, changes the host to loopback, and reuses DICOM/socket ports. If no
active profile exists, current server values are the fallback. Credentials,
source database, storage mappings and result folders are not copied or overwritten.
The preset updates the form only; Save and controlled restart remain separate.
Encrypted service credentials are still entered once for unattended service use;
interactive login credentials must not be silently reused by a Windows service.

The main Client connection view shows the shared Eagle Eye address. Pairing and
certificate paths are in a collapsed Advanced panel. Mobile access is a single
named section with Enable, status and pairing QR. Transport/address/port/TLS,
relay and built-in MCP details are in collapsed Advanced mobile settings. The
embedded MCP route is read-only in UI, defaulting to the software's existing
/mcp endpoint. Previously saved custom routes remain preserved for paired-device
compatibility; no external MCP-server address or parallel command registry exists.
Network addresses and device credentials cannot safely be hardcoded per host.
Default-off access, authentication and device permission checks are unchanged.

The PACS/storage details are likewise collapsed on Server, with a visible source
summary and a Use saved PACS settings button. A local HTTPS preset still needs a
certificate valid for loopback; TLS is never disabled automatically.

Four new simplification guards failed before implementation. Local focused suite:
104 passed, plus 19 gateway-wiring passes. These verify collapsed controls retain
values, legacy MCP routes survive Save, the preset reads off the GUI thread, and
role/payload behavior is retained. Live GUI acceptance remains pending a fresh
human source launch and existing MCP attachment. No gateway/service activation,
credential change, clinical request or full build was performed.

Razi follow-up: 121 applicable guards passed. Two environment-dependent guards
are excluded from the repeat gate: the Git snapshot test (no .git in this copied
revision), and the live developer Gateway config-template presence test (private
host config deliberately excluded from source synchronization). Both pass locally.
The first expanded Razi run had 121 passes and one config-presence failure, with
the previously documented Git guard deselected. No local private gateway config
was copied to Razi to manufacture a pass; code default-off and builder shipping
checks remain verified. These exclusions do not certify a produced installer.


## Follow-up: retained AI usage in each functional tab

Eagle Eye, EchoMind and Agent now have Server processing usage panels: accepted
requests, completed, failed/cancelled/interrupted, pending, reported input/output/
total tokens, and requests without complete token records. Refresh runs in an
owned worker. Unknown tokens read Not reported; missing histories, unavailable
servers or incompatible server versions read Unavailable, never fabricated zero.
These are retained server records, not network packet counts or billing balances.

Authenticated GET /v1/usage uses the existing pairing and owner identity. A Client
sees only its own records; the local Server UI explicitly labels all clients.
No clinical text, identifiers or credential values are returned. There is no
client-direct company provider fallback. Personal OpenAI mode retains its existing
personal usage controls. Historical requests without accounting cannot be backfilled.

Server EchoMind/Agent collectors record upstream response usage across stages in
the existing private history, including available usage on failed processing.
Eagle Eye jobs retain top-level reported usage when present; non-token inference
or models without reported counts remain unknown. Providers that omit usage or
calls outside this collector are not represented as fully accounted billing.

Four initial guards failed before implementation. Six usage guards now verify
owner isolation, retained history, unknown counts, upstream collection, worker
execution and failure presentation. The focused suite has 106 local passes.
The legacy capability guard was corrected to compare the canonical module catalog
instead of its obsolete seven-module count; Agent contract guards now assert the
additional accounting metadata while preserving the existing response contract.
All 517 packaged mirror pairs match. Live GUI acceptance remains pending: the
existing control client ping could not reach a source Test Control listener.
The staged Razi Developer revision is separate from the still-running r4 service;
no service activation, clinical test or installer build is claimed by this work.


## Follow-up: usage by named module / function

The usage table now has one row per Eagle Eye module, EchoMind workflow or Agent
function, with columns for accepted requests, completed, failed, pending,
reported input/output/total tokens and missing token records. Overall counters
remain in the API for compatibility; the UI presents the detailed named rows.

Eagle Eye covers all eight canonical inference modules: Breast, Bone age, Brain
volumetry, Brain white matter lesions, Lumbar spine, Lumbar bone marrow, Lower
limb alignment and Total spine alignment. EchoMind distinguishes Report, Turbo/HQ,
Chat, Radiopaedia Assist, Textbook / DI Assist, Web Assist and the other supported report,
translation and template functions. Agent separates action routing/planning/repair
from Ask, Guide and Help ticket. Ask/Guide/Help ticket rows combine their internal
phases; they are server-request counts, not distinct conversations or actions.

Grouping uses retained server module/workflow fields and only the Agent mode
metadata extracted by SQLite; no clinical text is loaded for usage grouping.
Each row respects authenticated owner filtering. All known functions are listed,
including ones without requests. Unknown legacy labels are combined under Other /
unclassified without exporting arbitrary stored strings. Tokens remain unknown
when not recorded. A server that supports only aggregate metrics shows Unavailable
instead of presenting totals as if they belonged to a specific function.

Three guards failed before this extension. Ten usage guards now include named
catalog coverage, separate workflow/module counters, owner isolation, aggregate
reconciliation and detailed UI rows; the focused local suite has 143 passes.
All 517 packaged mirror pairs match. The existing MCP ping still cannot reach a
source Test Control listener; live GUI acceptance is pending. Synchronization
targets the selected non-running Developer revision, not the active r4 service.


## Follow-up: Server usage by authenticated sender and request tests

The local Server settings view includes an Authenticated client column and a
client selector. Default separate rows show active function/client combinations;
module totals and each client's full function catalog are available in the selector.
Filtering uses the cached worker snapshot and does not trigger additional I/O.
The standard Client view remains scoped to its own authenticated pairing identity;
other client identities and sender summaries are never added to /v1/usage.

Server-only administration groups persisted job states and private text history
by their server-authenticated owner. Human physician/login usernames are not
recorded by this protocol and must not be inferred from a paired client ID or
trusted from an arbitrary request field. The displayed sender is the paired
client, not a verified individual user. Monetary provider charges are not inferred
from token counts; the panels remain reported consumption, not billing balances.

Three sender guards failed before the extension. The focused local suite has
178 passes. A new loopback HTTP matrix sends requests separately for all eight
Eagle Eye modules, 15 EchoMind workflows and six Agent functions, through two
independent authenticated clients. It checks successful dispatch, persistence,
per-function counts/tokens, owner isolation and both worker-backed usage tables.
Two additional failed-processing requests preserve available tokens and sender;
spoofed owner fields and invalid authentication are rejected without creating usage.

All model/provider outputs in this matrix are synthetic and no paid upstream,
clinical PACS study or clinical model inference is used. Running the matrix on Razi
verifies its Developer execution path, not the installed/running clinical service.
The configured real service's usage endpoint currently returns HTTP 404. Existing
MCP ping has no source control listener; live GUI acceptance remains pending a
fresh human source launch/login. Independent Server license provisioning and
controlled activation remain open as documented in the source parity record.
All 517 packaged mirror pairs match; no active service or installed app is changed.
