# AI-PACS — Agent Control & Testing Abilities

**Latest native-evidence contract (September 15, 22:05 source launch):** collect
`native_fault.<pid>.<session-token>.log` together with historical `native_fault.log`.
The old shared file is no longer the sole/current sink. External MCP byte windows,
filter and GUI guards now discover both formats, including new children during a
window. Raw `count_native_faults_since` deliberately returns
`EXTERNAL_NATIVE_PROBE_REQUIRED` with null counts and performs no GUI-thread I/O;
use the external wrappers, not a false-zero interpretation. Historical inventory
still cannot answer exact retrospective time windows or terminal-crash counts.
Fresh Home/menu/capture smoke and two health assertions/final check passed; 77 live
actions were discovered. This does not close shutdown or heavy-patient acceptance.
The final enable-before-session-header ordering correction was made after this
launch; verify it on the next human-authorized fresh source run, not by hot reload.
The user explicitly authorized this one source launch with `run it now`; login was
not automated. See the closure audit's third follow-up for tests, limits and rollback.

**Current health-tool correction (September 15, approximately 20:37):** the
source app is reachable; ping and 83-action discovery succeeded. The external MCP
`run_scenario` now actually evaluates `assert_health` against a bounded cumulative
byte baseline with same-process liveness. Use `native_health_readonly.json` for a
resource-only smoke, not patient GUI acceptance. Two assertions plus the final
check passed in a roughly 0.45-second observation window. There is no crash-closure
claim. `snapshot_health(since_minutes=...)` explicitly reports that its untimed
historical inventory cannot certify the requested window. Do not use raw
`count_native_faults_since` as a health gate: its path/time semantics remain wrong
and its read runs on the app thread. A loaded MCP wrapper needs restart to pick up
tool edits; no application restart is needed for this tool-only slice. The separate
scenario `wait_for_download` result is still ignored and requires correction before
whole download-soak acceptance. See the closure audit's second corrective follow-up.
Earlier process-absent notices below are historical observations, not current state.

**Current acceptance clarification (September 15):** the user confirms patient-tab
native drag/drop works. Do not pursue the earlier unfinished automated drag as a
reproduced application bug or broaden that confirmation to Home/Advanced/VTK.
The latest source process is no longer available; its final log is near 17:40 and
exit intent/completion is not established. Do not improvise relaunch or recovery.
See [the crash/Unify/KPI closure audit](../reports/CRASH_UNIFY_KPI_CLOSURE_AUDIT_2026-09-15.md).

**Latest sampled download live receipt:** explicit user-requested source launch
16:51:38, main PID 1169344, human sign-in, successful documented ping/actions.
Native Home thumbnail double-click and wheel passed; exact study/series matched.
Five MR series / 117 disk files matched both terminal Overall Progress displays.
Separate document task was 1/1. Native drag stayed unfinished and was cancelled
with Escape: NOT a pass. MCP downstream switch rendered exact second-series pixels.
Full in-flight/pause/retry/collision matrices remain open. Do not repeat downloads
or claim the entire GUI gate closed. See the fresh-source receipt in
`docs/reports/DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md`; older bootstrap blockers below
are historical. No runtime edits were made during this lap.

**September 15 file-count/retry gate (latest):** 23 new synthetic guards and 217
focused/builder passes do not replace source GUI acceptance. Documented ping and
list_actions work; the 15:43:24 source session predates the edits. After human fresh
source launch/sign-in, verify multi-series Overall Progress, real local counts,
pixels and retry/resume retention; include a verified same-number/distinct-UID case
when available. `[SERIES_FILE_COUNT_CHECK]` is a lower-bound count check, not a
durable SOP-manifest completion certificate. Do not induce clinical server failures.
See `docs/reports/DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md`.

**Audience:** an AI agent (Claude Desktop/Cowork, Claude Code, Copilot, etc.) that needs to
**control and test** the AI-PACS workstation. This is the single capability overview: what you
can do, with which tool, and how the pieces fit. Read it with [`../../CLAUDE.md`](../../CLAUDE.md),
this folder's [`README.md`](./README.md), and the
[Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md).

> **Golden rule:** preserve clinical behaviour and the source-build discipline. Empowerment
> here means *knowing your tools*, not bypassing the safety rules in §6.

---

## 0. Current operating memory and mandatory acceptance (2026-09-14)

### 2026-09-24 Client / Eagle Eye control connectivity diagnosis

In bug-fix session `01a0d48f-1b24-7e73-8578-e04d4a22a329`, read-only process
inspection found the current source Client launch with `AIPACS_TEST_SERVER=0`.
`run_app.ps1` explicitly sets zero unless `-TestServer` is passed. QLocalSocket
`Invalid name` here means the expected listener was absent, not proof of an
invalid naming algorithm. The user-level Codex MCP configuration had no
`aipacs-control` registration. The Python MCP SDK is installed; an isolated actual
stdio initialize/tools-list handshake succeeded and exposed 58 tools. This only
proves the bridge process, not attachment to the app.

The local Test Control Server is created after Home/CommandBus initialization,
uses a per-Windows-user socket (or matching `AIPACS_TEST_SOCKET` overrides), and
rejects frozen builds. There is no Standard-versus-Eagle-Eye GUI role gate in
`maybe_start_test_server`: either source GUI role needs the opt-in flag and Home
ready. A headless Eagle Eye service does not construct Home or this GUI endpoint.
Separate machines/users require their own correctly targeted connection; do not
assume a local named pipe reaches a remote center.

The existing production Agent Gateway is a different authenticated transport.
On this workstation it was already enabled; certificate-verified loopback probes
returned HTTP 200 for `/health` and 401 for unauthenticated `/mcp`. Thus its
listener is reachable, but this agent has not established a paired authenticated
MCP session. No token was displayed, no pairing was bypassed, and no settings,
launch flags or LAN exposure were changed. Production integration belongs to
`docs/pipelines/agent-gateway.md`, not removal of the frozen test-server gate.

Code evidence: 75 focused test-server, MCP inventory/health and gateway tests
passed (exit 0). Live source attachment, authenticated production tools/call,
Eagle Eye GUI role and installed Client/Server acceptance remain pending.
For the next source GUI lap, the human closes the intended source instance
outside clinical work, starts the selected role with `run_app.ps1 -TestServer`
(plus `-Standard` or `-EagleEyeServer` and its existing role configuration), and
signs in. Then probe ping/actions using the documented client before performing
the affected workflows. Register the existing stdio bridge in the intended MCP
host when configuring that integration; tools/list alone is not an app health pass.

This section is the current, shared Codex/Claude operating procedure. It supersedes older
environment, lifecycle, and blanket fidelity claims below and in June runbooks. It is a
repository memory, not a promise that a cloud copy has automatically synchronized.

### Two independent gates for each runtime fix / Unify slice

**September 15 download-response gate (latest):** existing client ping and action
discovery succeed. The session launched at 15:43:24 predates the new socket client;
human fresh source bootstrap/sign-in is needed for attributable GUI acceptance.
Use an authorized test case to verify multi-series queue/details Overall Progress,
pause/resume, file-preserving retry, priority and exact-series images/counts. Do not
inject broadcasts into the clinical server or interrupt unrelated downloads.
38 synthetic wire cases and 189 adjacent passes are not a native UI/disk-completion
pass. Follow `docs/reports/DOWNLOAD_SOCKET_RESPONSE_REVIEW_2026-09-15.md`.

**September 15 browser-status gate (latest):** the source session started at
15:43:24 predates `modules/web_browser/launch.py`. Documented client ping and
action discovery are available, but that process cannot accept the new patch.
After a human fresh source launch/sign-in, verify actual first-open input and
visible wait strip, queued-click protection, recovery, existing-tab reuse and
normal Home/patient behavior. The synthetic strip preview and 160 code passes
are not native GUI acceptance. No hot reload or duplicate instance. Browser
phase=ready is construction completion, not remote-page load completion. See
`docs/reports/WEBENGINE_OPEN_WAIT_STATUS_2026-09-15.md`. Earlier connection-blocked
receipts below are historical; their remaining workflow gates still apply.

**September 15 additional gate:** OPT-60 consultation Poller retirement has 15 new
Qt guards and 367 adjacent passes, but source GUI is blocked on client ping. After
human fresh bootstrap, verify normal Home/patient workflow and normal exit; inspect
PHI-free stop-request/worker-finished markers for an already configured poller.
Do not manufacture cloud notifications or relink credentials for testing. A stop
request is not whole-app worker drain; native exit faults remain open. Details:
`docs/reports/QT_POLLER_LIFECYCLE_2026-09-15.md`.

**September 15 current gate:** the signature snapshot adapter and split thumbnail
queue/scan/delivery timing require a fresh source launch; PID 1153108 started 12:25:45
before these edits. Documented client ping was unavailable. Human bootstrap with
`AIPACS_TEST_SERVER=1` and sign-in, then existing MCP/native workflow tests are required.
Check `[QT_SIGNATURE_GUARD]` activation, exact-series pixels/counts and normal exit.
Two earlier native faults followed shutdown, not a proven image-open failure; do not
count them as resolved by the separate signature KeyError fix. See OPT-60's September 15 receipt.

**Current startup-preparation gate (updated September 15):** human source launch September 14
23:16:05, PID 1123404, contains the final patch. Existing MCP client ping failed this launch;
do not carry the earlier 77-action availability forward or improvise gateway/process recovery.
Native Home double-click, visible pixels, wheel and normal close passed for grouped Server and
Local cached cases; Local non-first series preserved 25 images after reopen. Exact UID inspection
was unavailable. The audit records scan/wait timing and remaining stalls; this is not a full
performance acceptance. Still verify cold/missing-cache behavior, Local/cine counts,
multi-study skip, and close during preparation with a surviving tab. Observe exact Study/Series
identity, pixels, counts and no duplicate viewport replacement. Compare `patient_tab_thumb_prepare`
scan/wait fields and F8/F11 evidence with the earlier 4.1-second GUI enumeration stall. The new
18-case offscreen test file is code evidence, not this GUI pass. Other GUI I/O remains staged.

**Latest sampled live receipt (21:04:04 source launch, main PID 925068):** user-requested
launch and human sign-in, then documented ping/action discovery. This process includes the
20:57:47 card-effect edit and supersedes the bootstrap blocker below. Native Home double-click
on the verified two-study case: 13 cards, exact Study/Series, 8 slices; native wheel 5/8 -> 6/8;
close, empty query (zero table/cards), restore 13, reopen same identities; tabs 5 -> 4 -> 5.
Surviving tab native card click rendered its own 5-slice series with matching Series UID.
Expired screenshot and intercepted input were recovered by fresh observation/activation, not
counted as app failures or GUI passes. Logs through 21:17:55: no new errors during the lap;
earlier attachment failure and `Response too large` download errors remain separate issues.
No access violation/deleted-Qt markers; one startup non-terminal COM event. See canonical OPT-60.
Real retry/completion/close, Advanced, progressive replacement and full stress/drag matrices
remain unverified live. Do not call the entire card-effect or Unify acceptance complete.

**Current gate (card-owned effects, after the 20:41 source launch):** 14 new Qt guards;
441 expanded passes / 1 existing GUI KPI skip, exit 0; 462 mirrors match. Documented client
ping and action discovery succeeded, but main source PID 1091952 started 20:41:10 and predates
the patch. Do not hot reload, relaunch/login automatically, or count that process as acceptance.
After human fresh source bootstrap/sign-in, use existing MCP plus native input to verify real
progress/Ready, Home replacement/empty clear, exact-series open, close/reopen with a live sibling
and independent Advanced panel. Observe pixels/identity/counts and scoped logs. No fabricated
download completion. Code proves cancellation/native deletion; GUI cannot prove wrapper GC.
The earlier 20:41 log review observed normal closes and no access violation, but had download
broadcast-limit/cancellation errors and no definitive completion marker. Those separate
OPT-04 issues and full native-crash/stress/installed acceptance remain open.

**Current gate (manager-owned callback retirement, after the 20:03 session):** code PASS,
424 adjacent passes / 1 existing skip including 17 import/overlay guards; 462 mirrors match.
Client ping failed at handoff and the prior main PID was absent. Human source bootstrap with
`AIPACS_TEST_SERVER=1` and sign-in was requested; do not recover/relaunch/login automatically.
Test small/large Home replacement, empty clearing, same-identity refresh, exact-series native
open and progress -> close/reopen with a remaining live tab. Advanced-panel ownership remains
independent. Observe actual pixels/identity/counts and session logs; no fake completion events.
The earlier sampled live receipt below predates this patch and cannot close its live gate.
Card-owned animations, crash/stress and installed acceptance remain separate.

**Fresh-source sampled live receipt (20:03:33 main PID 1113400):** source launch was explicitly
requested by the user; human sign-in, then successful client ping/action discovery. The latest
19:17 edit is loaded. Two-study Server preview 13 -> empty query 0 -> restored 13 passed.
Native Home-card double-click, wheel navigation and close/reopen passed: matching Series UID,
case-member Study UID, 8 slices, tab counts 3 -> 2 -> 3. This supersedes the connectivity
blocker below. It does NOT prove the same-identity changed-payload small swap, large/progressive
owner replacement, wrapper collection or real completion/priority behavior. Keep those gates open.
Scoped logs through 20:12:47: no ERROR/CRITICAL, deleted-object/traceback markers or access
violation; 38 stalls (maximum 1909.1 ms), one non-terminal startup COM event. No crash/performance
closure. See the canonical OPT-60 receipt for scope and remaining work.

**Observed adapter limitation:** `get_thumbnails_data` returned 1 row for the above case while
both observed panels and `get_series_info` showed 13 series. Do not use its count as the card
oracle. Use actual UI plus `get_series_info`, and compare rendered metadata's series-level
Study UID (not just the top-level primary Study UID). Investigate the adapter projection
separately before asserting its grouped-list fidelity. Never print clinical payloads to diagnose it.

**Latest gate (small same-identity refresh swap, latest edit 19:17):** code PASS, 390 expanded
passes / 1 existing GUI skip; 462 mirrors match. Separate import/overlay-crash guard recheck:
17 pass. Source live BLOCKED: documented local client ping failed; observed main.py processes
started 18:29:49, before the patch. Do not restart/recover/login automatically. After human
source bootstrap with `AIPACS_TEST_SERVER=1`, verify same-case small metadata refresh without
blanking, changed-patient/empty clearing, large-set progressive rendering and native exact-series
open. Also close the previous Home owner-retirement live gate. No PHI fixtures or fabricated
download-completion events; prior native-crash stress/installed gates remain separate.

**Newest code gate (Home render owner retirement, 18:22 edit):** 374 expanded passes, one
existing opt-in GUI KPI skip, 462 mirrors match. Existing bridge ping responds but main PID
1114928 started at 17:57:23 and does not contain this edit. Human source restart/sign-in is
required; do not hot reload or count the earlier relay live lap as proof. Exercise progressive
Home selection -> empty results -> small/immediate selection, repeated replacement, exact-series
native double-click and log review. Wrapper collection is a code guard, not inferred from the GUI.
Prior real completion/priority and full manager-disposal/drag/identity matrix gates remain separate.

**Newest code gate (patient-tab signal lifetime, after the 16:35 launch):** 364 expanded passes,
one existing opt-in GUI-only skip, 462 mirrors match. Fresh source 17:57:23 (main PID 1114928),
human login: native open/close/reopen passed for a two-study case, same Study/Series UID and
8 visible slices, no duplicate tab. Logs through 18:01:10 have no ERROR/CRITICAL or deleted-object
markers; 38 stalls (max 1773.8 ms), one non-terminal startup COM event, no access violation.
Close exit 42.5 ms and deferred GC 195.9 ms are not proof of collection or no lag. No real
worker-completion/emission markers occurred. Still exercise normal priority/completion behavior;
closed tabs must not refresh and
remaining live tabs must still respond. Do not fabricate a production download-completion event,
change clinical data, or call an old-process run a pass for this patch. Full manager disposal
and the extended identity/drag/Offline Cloud matrix remain separate gates.

**Latest live gate (16:35:43 source launch, human sign-in):** new search-retirement code is
loaded. Server 13-card preview -> empty search/zero -> restored selection and real Home
double-click into new/reused tab passed with matching Series UID, case-member Study UID and
8 slices; no duplicate tab. Local valid 6-card preview -> empty search/zero also passed.
Patient maps stayed transient; no pin configuration was changed. Pin row-remap, advanced overlap
and Offline Cloud remain code-only evidence. Scope logs through 16:41:32: no ERROR/CRITICAL or
access violation; one non-terminal startup COM event and 41 timer stalls (max 2236.1 ms).
No performance-improvement claim. This supersedes the launch-pending handoff immediately below.

**Newest code gate (search preview retirement):** 302 focused/adjacent tests pass, including
18 new synthetic guards; 462 mirror pairs match. This patch was made AFTER the 15:39 source
launch below. Its live gate is pending; do not reuse that process as proof. After human source
relaunch/sign-in, use bounded MCP selection and native Home checks: empty query clears cards
and count; subsequent valid selection/open resolves exact Study/Series identity; matching selected
pins survive, and a pending pin fetch follows row movement. Check Local/Offline clear where
available. No clinical data deletion, live DB tests, native drag or stall investigation is required
for this bounded gate. The old caller-gap wording below describes the pre-fix live observation.

**Latest live gate (15:39 source session, 15:34 Home lifecycle patch):** sampled 13/17-card
selection replacement, five bounded alternating selections and exact-series open passed.
Empty server search left the old preview visible although the table was empty; native old-card
double-click correctly opened no tab. Do not use empty search as proof that the panel's clear
was exercised: the search caller currently clears only the table. This integration gap remains
open; forced timer/destruction races retain deterministic Qt evidence only. Code gate is 197
passed; full manager disposal, native drag and stall investigation remain open. The user requested advancing independent plan work
without waiting for the latter two investigations; do not reinterpret that as their acceptance.

**Current implementation update:** the selection-adapter correction is code-verified and
source-live verified for the 15:15 session's two-study sample. `select_patient` selects one current
visible table row and queues the normal debounce timer; the result says `selection_state=queued`.
It ignores stale search-cache metadata and resolves grouped member UIDs to the canonical row.
Wait for observed thumbnail readiness before native double-click. Missing/ambiguous/hidden rows,
in-progress search and non-GUI calls fail closed. The native-row workaround below applies to
older processes only. The corrected command passed WITHOUT that workaround: native Home
double-click created/reused a tab with exact-series output, invalid ID rejection added no tab,
and wheel navigation preserved identity. See the current provenance receipt for scope and logs.

**Historical procedure correction (pre-patch 13:22 source session, September 14):** Home double-click
passed for existing-tab reuse and new-tab creation only after native selection of the actual
patient table row. `select_patient` invokes the downstream handler but does NOT establish
`results_table.currentRow()`. Therefore it is insufficient setup for this input-boundary test.
Do not call an initial adapter-only rejection a product regression or weaken the selection guard.

Efficient lap: `ping` -> `list_actions` -> one bounded query -> verify exact candidate membership
(search may also return substring matches) -> corrected `select_patient` -> observe Home cards -> native
card double-click -> compare requested/rendered UIDs locally -> bounded slice navigation ->
session log check. Use the current screenshot for coordinate input; an accessibility-only
observation may yield `coordinate input geometry is unavailable` for checkable image buttons.
Use one fresh screenshot-backed observation rather than repeatedly retrying stale element IDs.
Keep raw patient responses transient and print only counts/boolean checks.

The live inventory in this run did not expose `close_patient_tab`, `query_thumbnail_state` or
`query_download_state` even though older MCP-wrapper docs name them. Use the actual inventory;
closing the test tab used its observed native close button. One native sidebar drag did not
verify a changed target. In the 15:15 session the drag image remained active, and Escape canceled
it with the destination still empty. Native drag remains INCONCLUSIVE; never count T1 as its pass.

Current Home-thumbnail slice: code gates pass for **double-click -> normal patient open/reuse
-> exact series placement**. Single click is preview-only. The earlier source-session cache-hit
failure predates this patch; do not reuse that process's successful MCP rendering as acceptance.
The later user-confirmed 12:49 source-session Home double-click is log-corroborated for one
two-study server-open workflow. It predates the final header correction and semantic-refresh
patch, and does not close their live gates or the full multi-study/offline/cine matrix. Scope
active logs by record timestamps plus source-session PID/start time, not filesystem modification
time: open logs in this run had stale modification times while records continued arriving.
After human source restart/login, test actual double-click on unopened/existing patients, compare
the requested and rendered Study/Series UIDs locally, check repeated/unnamed multi-study series
and cine counts, and confirm ordinary name-open remains empty/manual-placement. A `change_series`
command alone bypasses the Home double-click and cannot prove it. No new authentication route
or Windows-login automation is introduced.

1. **Code gate:** demonstrate the regression guard failing for the original defect, then passing
   after the fix; run focused and adjacent suites with direct pytest and process exit codes.
   Include identity, lifecycle, thread ownership, and packaging/mirror boundaries when affected.
2. **Live GUI gate:** attach to the human-started Windows source app containing that patch;
   perform the affected workflow through the existing MCP/local command bridge and the actual
   input layer where needed. Verify destination identity, rendered output, counts, responsiveness,
   and session-specific logs. An `ok` response only proves what the adapter actually observed.

Record `PASS`, `FAIL`, or `BLOCKED` for each gate. A skipped test, fake adapter, offscreen widget,
successful dispatch, or quiet log is not a live GUI pass. Do not close a runtime slice while its
required live gate is blocked. Documentation-only edits need link/diff/content checks; they do
not claim new product validation. Installed/build acceptance remains a separate release gate.

### Discover and attach; do not relaunch the app

- Search the current callable-tool inventory for `aipacs-control`. Its implementation is
  `tools/testing/aipacs_control_mcp/server.py`; the in-app transport is
  `modules/EchoMind/secretary/test_server.py`; adapters live beside it under `adapters/`.
- If the MCP is not exposed, use the existing `AipacsControlClient` / `client.py` against the
  same `QLocalServer`. This is a transport fallback, not a second viewer implementation. MCP
  registration is not required to use that fallback; never claim registration from a CLI probe.
- The human launches and logs into one source instance with `AIPACS_TEST_SERVER=1`, outside
  clinical reading. Verify source checkout, interpreter, start time, and patch freshness. A venv
  redirector and its child can be one launch; do not count them as two GUI instances blindly.
- Start with **only `ping`, then `list_actions` after ping succeeds**. The live action inventory,
  current adapter signature, and returned errors outrank a historical example.
- The endpoint defaults to `AIPACS_TEST_<sanitized getpass.getuser()>`; an explicit
  `AIPACS_TEST_SOCKET` overrides it. On failure, check the current source session's listener
  banner and endpoint/user mismatch. Do not guess arbitrary pipes or enable a LAN listener.
- If unreachable, report the failed probe and ask the human to restart the source app with the
  test flag. Do not call lifecycle `launch_app`, `login`, `stop_app`, use force-kill launchers,
  open the installed app, or change persistent configuration to work around the blocker.
- The production paired-device Agent Gateway is a different trust boundary and is not the test
  bridge. Do not enable it for routine regression testing.

Connectivity-only commands, run from the repository root:

```powershell
.\.venv\Scripts\python.exe tools/testing/aipacs_control_mcp/client.py ping
# Run only after ping succeeds:
.\.venv\Scripts\python.exe tools/testing/aipacs_control_mcp/client.py list_actions
```

Do not run PHI-returning CLI commands with raw console output. Use the existing Python client
to hold responses locally and emit only allowlisted aggregate/alias-based test results. The MCP
server records raw command entities/results in `tools/testing/aipacs_control_mcp/sessions/`;
check ignore/retention policy before use and never commit or upload those recordings.

### Startup UI checklist (user preference, 2026-09-14)

1. Attach to the verified source window; inspect fresh state before each action.
2. If the **Disk Space Alert** is present, click **OK**. The user approved acknowledging this
   notice during GUI preflight. Do not choose **Don't show again**, disable alerts, or delete
   data. Dismissing the notice is not evidence of sufficient capacity for a large download/import.
3. At **Sign In**, leave prefilled credentials masked and unchanged. The user requested automatic
   sign-in, but the current Computer Use skill's mandatory authentication-automation restriction
   requires a human handoff. Do not use an alternate UI/CLI login route to bypass that restriction.
4. After the human signs in, observe Home, then require successful `ping` and `list_actions`.
   Resume the bounded patient/thumbnail/viewport workflow; keep code and live results separate.

Observed on 2026-09-14: **OK** dismissed the source app's disk-space notice; the login screen
remained. No credentials were exposed/changed, no authentication action was executed and no
data cleanup occurred. Live patient acceptance is still pending login.

### Current action map and fidelity limits (source-inspected)

| Workflow | Existing action / route | Required additional check |
|---|---|---|
| Search | `raw_command("list_patients", entities_json=...)` / client action `list_patients`; entities `source`, `patient_id`, `patient_name`, `date_from`, `date_to`, `modality` | This invokes search, not just table inspection. Set explicit bounded criteria. Current adapter does not enforce the MCP wrapper's `limit`; row cache can include earlier searches. Verify fresh results/current source before use. |
| Select row / Home thumbnails | `select_patient` with explicit verified patient/study identity | Corrected adapter selects one current visible row and queues normal debounced signals; wait for actual cards. Sampled source-live gate passed in the 15:15 session. Older pre-patch processes need native row selection. |
| Open patient | `open_patient` with explicit verified patient/study identity | Reaches the production open handler; does not prove double-click debounce. Opening may trigger normal downloads/visit state; stay within the agreed test scenario. |
| Load series in viewport | MCP `drag_series` -> client action `change_series`, entities `series_number`, `viewport` | `series_number` is the destination tab's current key, not a Home ordinal or guessed original DICOM number. Async handoff is not visible-image completion. |
| Scroll stack | `raw_command("scroll_slices", entities_json=...)`; `viewport` plus `index` (zero-based), signed `delta`, or `direction` (`next`, `previous`, `first`, `last`) | Adapter calls `set_slice`, clamps to available count; query resulting index/pixels. Does not test wheel/drag input or cine playback timing. |
| Observe series / viewer | `get_series_info`, `query_viewport_state`, `query_thumbnail_state`, `get_viewport_context`, `capture_viewport` | Keep PHI local; verify both study and series UID, separate object/frame counts, correct viewport, actual rendered image and loading convergence. Metadata alone cannot prove pixels. |
| Switch / close | `switch_tab`, `close_patient_tab` | Discover current indices; protect unsaved reports/annotations. Observe teardown and late callbacks, not only command success. |
| Download observation | `query_download_state`, `snapshot_health`; bounded polling | Progress/dispatch success is not manifest completion. Do not trigger new downloads or stress bursts beyond the scenario. |
| Layout | `change_layout` | Current adapter returns `NOT_IMPLEMENTED`; do not invent success or silently skip this step. |

The first-class `list_patients(limit=25)` MCP wrapper does not expose filters; use `raw_command`
for explicit criteria. Source adapter dates use compact `YYYYMMDD`; inspect current signatures
and response freshness each session. Do not infer Local hard-offline correctness from the
server-oriented cached row probe.

**Input and visual fidelity:** T1 commands share downstream application functions, not every
upstream GUI handler. In particular, `change_series` bypasses the Home `seriesActionRequested`
click signal and drag MIME creation/acceptance. The September 14 Home-click cutover therefore
requires an actual Home-card click in addition to destination/render probes. Use existing
`tests/gui/pywinauto/` only after reading the selected test's source-build and active-module
prerequisites. The Eagle Eye OLE test is not automatically a Fast Viewer or Home drag test.
Use a supported local native-input tool or a human-observed pass if that boundary is not exposed;
record it as blocked if unavailable. Never replace a real OLE regression lap with T1 commands.

Avoid the `clinical_agent_validation.py` external-brain demo for routine maintenance: its default
requires an external AI provider and records decisions. This task does not authorize exporting
patient data or generating/altering clinical reports, measurements, assignments, or approvals.

### Find representative multi-study cases without storing patient identities

Prefer a small, current PACS query first. When necessary, use the existing reception integration
read-only, following `INO_RECEPTION_API_GUIDE.md` (especially identifier and port rules).
For access to the reception computer/infrastructure, read the `alizadeh-infrastructure` skill
before connecting; do not change server services/configuration or invent credentials. Resolve
endpoints from current configuration and approved session credentials, not old example hosts.

Candidate patterns requested by the user:

- mammography plus breast ultrasound (MG + US);
- spine radiography plus lumbar MRI (DX/CR + MR);
- repeated brain MRI visits on distinct dates.

These are search heuristics, not guaranteed same-person or multi-study evidence. Numeric
`receptionID`, workflow ObjectId `receptionId`, PACS PatientID, and person identity are not
interchangeable; different admissions may have different PACS PatientIDs. Verify the reception
system's authoritative person/admission link and distinct StudyInstanceUIDs against PACS before
calling it a multi-study case. Never merge people by names, modality, or anatomy alone. Explicitly
confirm which studies the application legitimately groups in the same patient tab.

Use bounded dates/pages and the minimum necessary metadata; avoid report bodies and clinical
images during discovery. Keep transient identity lookup maps local/private. Persist only aliases
such as `CASE-MG-US`, modality pattern, verified number of studies, and expected behavior; never
real identifiers, UIDs, DOBs, screenshots, tokens, or patient paths in memory/docs/fixtures.
Missing or ambiguous linkage is a case-selection blocker, not permission to guess.

### Per-slice live matrix and evidence receipt

Select relevant rows rather than running every module or stress scenario indiscriminately:

- single-study baseline and confirmed multi-study / previous-exam case;
- duplicate/missing series names and duplicate original numbers across and within studies;
- static images vs cine: DICOM object count and displayed frame count independently correct;
- Home selection/card click, patient-sidebar switch, actual drag to intended viewport, scroll;
- rapid selection followed by close/reopen: no stale card/callback or cross-patient pixels;
- Local/offline and Server paths when affected; do not disconnect a clinical workstation's
  network without an explicitly agreed isolated offline test;
- Fast, Advanced, Eagle Eye or MPR only in their own affected execution domains.

Each receipt contains the existing OPT/Unify slice, source revision plus relevant dirty-patch
identity, process/session and startup time, case aliases, preconditions, action/fidelity tier,
expected/observed outcomes, automated command/count/exit code, live PASS/FAIL/BLOCKED, and
remaining gaps. Correlate first-image/identity/loading events with the same run; compare timings
on matched workloads and distinguish cold/warm, UI wait, server wait, and adapter overhead.
Classify native faults by session/PID; absence of new errors is supporting evidence only.
Update the existing master-plan item and regression/subsystem records, not a competing plan.

**Discovery receipt, 2026-09-14:** source code confirms the routes above. This session exposes no
callable `aipacs-control` tools; the existing CLI `ping` failed (exit 1, local socket unavailable).
No `AIPACS_TEST_*` pipe was enumerated, and the source launch was still from 10:57, before the
Home-click cutover. No patient query, clinical GUI action, relaunch, MCP registration, or endpoint
configuration change was performed. This establishes a live-preflight blocker, not a failed
viewer acceptance test and not proof of why the endpoint is absent.

The discovery/documentation check also ran the existing `test_test_server.py`,
`test_adapter_contracts.py`, and `test_mcp_server_inventory.py` under `tests/code/echomind/`
with direct offscreen pytest, `-p no:debugging --reruns 0`: **11 passed, exit 0**. These use
isolated/fake transport and source contract checks; they do not establish live connectivity
or test the running patient's GUI. No runtime source was changed for this policy update.

**Authorized restart receipt, 2026-09-14 12:10 local:** the user explicitly asked the agent to
close the VS Code source run and restart it from PowerShell/VS Code for testing. This was a
task-specific exception to the default human-launch procedure, not general lifecycle authority.
The exact source window was closed normally; the old main and venv-redirector processes exited
before launching one `.venv/Scripts/python.exe main.py` from this checkout. Launch PID 1097732,
main PID 1090784, start 12:10:46/47; base revision `5d3c72d5` plus existing dirty changes. The
new launch postdates the Home-click patch. Process-scoped flags: `AIPACS_TEST_SERVER=1`,
`AIPACS_AGENT_GATEWAY=0`, `AIPACS_CURVED_MPR_VTK_PICK=1` (matching the source launch profile),
and `QT_QPA_PLATFORM=windows`. No persistent configuration or credentials were changed.

The actual source login screen and a low-disk-space notice were observed; the human must sign
in. No authentication UI was automated. Pre-login `ping` remained unavailable (exit 1); live
GUI acceptance remains BLOCKED pending login and a successful bridge probe. A focused rerun
of the Home-action/metadata/local-projection, multistudy-projection and three control suites
passed **61 tests, exit 0**, reruns disabled (six existing SWIG warnings). This is automated
verification only, not a patient workflow or rendered-image pass.

**Post-login live update (2026-09-14):** the human completed login; the same local client now
passes `ping` and `list_actions`. Live control is available. The bounded Home-click test FAILED
because the cache producer discards card UIDs; downstream two-viewport MCP rendering and actual
wheel navigation passed for one single-study sample. Native drag was inconclusive and canceled
with Escape. Full evidence is in
[`THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md`](../plans/analysis/THUMBNAIL_AND_PRIORITY_PARALLEL_PATH_PROVENANCE_2026-09-13.md).

The live registry did NOT advertise `close_patient_tab`, `query_thumbnail_state`, or
`query_download_state`, although these names exist in older catalogs/wrappers. Do not call or
claim them as available from source inventory alone; use only the discovered actions or an
appropriate observed GUI input. No control adapter was changed as a workaround. The supported
native-control path in this session is the Computer Use skill's `node_repl` + `@oai/sky` (not
the browser-only CUA surface); read its skill/guidance/confirmation rules before use.

## 1. TL;DR — there are two testing lanes

| | **Verify lane** (fast, agent-autonomous) | **Clinical lane** (real, human-assisted) |
|---|---|---|
| Where | Current Windows `.venv` (offscreen), or supported Linux sandbox | **Windows source build** (the actual app) |
| Runs | offscreen `pytest`, ruff, import/syntax checks | the real PySide6/VTK GUI |
| Speed | seconds–minutes | full app startup |
| Use it to | catch import/logic/**regression** breakage before a live pass | verify GUI, thumbnails, viewer, real workflows |
| Setup | `bash tools/dev/sandbox_setup.sh` (see §4.1) | human bootstraps; you drive (see §3) |
| Cannot | open the GUI, render, VTK windows, Windows-only COM | — |

Every runtime fix/Unify slice must pass the **Verify lane first**, then the affected **Clinical
lane** GUI check (section 0). Documentation-only checks are recorded separately.

**To drive the live app, prefer the in-app command surface — the `aipacs-control` MCP (§3.1) —
over pixel-clicking.** It is the path the maintainers built specifically to control the
workstation faster and more reproducibly than Windows-MCP / computer-use.

---

## 2. Your toolbelt — what each tool can and cannot do here

The exact tools depend on your harness; this is the model for a **desktop-control + sandbox**
agent (the default Cowork setup). A Copilot-in-VS-Code agent instead drives the integrated
terminal directly (see [`../VSCODE_AGENT_MODE_SETUP_2026-06-02.md`](../VSCODE_AGENT_MODE_SETUP_2026-06-02.md)).

- **File tools (Read / Write / Edit)** — the primary way to inspect and patch code in the repo
  (`E:\ai-pacs\ai-pacs codes\ai-pacs beta version`). They read the real filesystem and are
  reliable. *Caveat:* the agent's Linux **bash mount** of the repo occasionally returns null
  bytes for a few very large files — when bash output looks truncated/garbled, **trust the Read
  tool** (or `rsync` the source to local fs); it is a mount artifact, not a code bug.

- **Linux sandbox shell** (`bash`) — runs the **Verify lane**: offscreen `pytest`, `ruff`,
  Python scripts, `git`. It **cannot** launch or kill Windows processes or open the GUI, and
  each call has a **~45 s limit** (for long jobs, start them and poll; see
  [`../../tools/dev/SANDBOX_TESTING.md`](../../tools/dev/SANDBOX_TESTING.md)).

- **In-app command surface — the FASTEST way to drive the GUI** (preferred over pixel-clicking,
  and the path the maintainers built to beat Windows-MCP). The app exposes its real functions via
  the EchoMind **CommandBus**; with `AIPACS_TEST_SERVER=1` (source build only) that bus is
  reachable over a `QLocalServer` pipe wrapped by the **`aipacs-control` MCP**
  (`tools/testing/aipacs_control_mcp/`). Call tools like `open_patient`, `drag_series`, `open_mpr`,
  `query_viewport_state`, `burst`, `run_scenario` — each runs the *same production code path* a
  click/drop would, at ms-latency. Full how-to in §3.1.

- **Desktop control** (computer-use: screenshot + mouse/keyboard on the real desktop) — the
  **fallback**: visual verification (screenshots of what actually rendered) and actions outside
  the command vocabulary. Apps are granted at a **tier**:
  - **Browsers → "read"**: visible in screenshots, no clicks/typing.
  - **Terminals & IDEs (VS Code, terminal) → "click"**: you can *see* and *click* (e.g. a Run
    button) but **cannot type** into them. So you cannot type a launch command into a terminal.
  - **Everything else (the AI-PACS GUI, File Explorer) → "full"**: clicks + typing.
  - You must `request_access` for an app before controlling it. **Look before you assert** —
    take a screenshot to check state rather than guessing.

- **Native / web control MCPs** (Windows-MCP, Chrome MCP) — may be present for native-Windows or
  browser tasks. Prefer a dedicated MCP or VS Code/terminal when available; the §6 discipline
  still applies.

### Why the human usually launches the app
Your shell is Linux (can't start the Windows app) and Windows terminals/VS Code are tier
**"click"** (no typing). The only fully-agent launch path is **double-clicking a `.bat` in File
Explorer**. If that's unreliable, **ask the user** to launch — don't fight window management or
open the frozen exe. This is why **human-assisted bootstrap is the default** (§3).

---

## 3. Controlling the running app

Two ways to drive the live app. **Prefer the command surface; fall back to pixel control only for
what it can't do.**

### 3.1 Fastest path — the in-app command surface (`aipacs-control` MCP)
Built specifically to control the workstation faster and more reproducibly than mouse automation.
Reference: [`../../tools/testing/aipacs_control_mcp/README.md`](../../tools/testing/aipacs_control_mcp/README.md)
· architecture [`../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md`](../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md)
· fidelity [`../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md`](../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md).

**Chain:** MCP tool → in-app **Test Control Server** (`QLocalServer`, `modules/EchoMind/secretary/test_server.py`)
→ EchoMind **CommandBus** → the real application function. Every command runs the production code
path, so cross-patient isolation and multi-study guards stay enforced (fidelity tier **T1**;
commands queue one-per-event-loop-turn — impatient-user pressure a human can't reproduce).

**Enable (source build only — NEVER during clinical reading):**
1. `& "<repo>\.venv\Scripts\python.exe" -m pip install mcp` (once).
2. Launch the source build with `AIPACS_TEST_SERVER=1` (restore the full env first so the per-user
   socket name resolves — see the README's PowerShell block). Banner confirms
   `[TEST_SERVER] LISTENING on local socket 'AIPACS_TEST_<user>'`.
3. Register the MCP (stdio) in your client (`aipacs-control` → the `.venv` python running
   `tools/testing/aipacs_control_mcp/server.py`) — works for Claude Desktop, Cowork, and Claude
   Code. Or skip MCP and use the CLI:
   `& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\client.py open_patient '{\"patient_id\": \"44704\"}'`.

**Tool vocabulary** (each = a real UI action):
- *Lifecycle:* `launch_app` (launches the source build with the test server, dismisses startup
  dialogs, clicks Sign In, moves to a monitor, waits ready), `stop_app`, `app_status`,
  `wait_app_ready`, `login`, `list_monitors`, `move_app_to_monitor`.
- *Workflow:* `list_patients`, `select_patient` (single-click + thumbnails), `open_patient`
  (double-click open), `drag_series` (the exact `change_series_on_viewer` a real drop defers to),
  `open_mpr`, `switch_tab`, `close_patient_tab`, `trigger_download`, `query_download_state`,
  `wait_for_download`, `query_viewport_state`, `query_thumbnail_state`, `snapshot_health`.
- *Pressure / repro:* `burst` (N commands as fast as the pipe allows), `run_scenario` (seeded JSON
  timelines + JSONL session recording). `list_actions` / `raw_command` reach anything else the bus
  exposes.

In a **normal** clinical run (no test server) only read + safe-navigation actions exist; the full
write surface (`change_series`, `close_patient_tab`, …) is registered **only** when the test
server is on. `change_layout` is a typed NOT_IMPLEMENTED stub for now. Contract guard:
`tests/code/echomind/test_adapter_contracts.py` — run it whenever adapters change.

### 3.2 Fallback — desktop control (computer-use)
Use pixel control only for what the command surface can't do: **visual verification** (screenshot
the viewport to confirm what actually rendered) and actions not in the vocabulary. Tiers + the
"look before you assert" rule are in §2. Manual sanity loop: tick **MR/CT** → set the date →
**Search Patients** → single-click patients (thumbnails auto-load) → open a study. Identify the
source build by its **Python (snake) taskbar icon**, not the black AI-PACS icon.

### 3.3 Launch & positioning
**Default = human-assisted bootstrap** ([`../../CLAUDE.md`](../../CLAUDE.md) → "Human-assisted bootstrap
mode"): the human launches the source build, logs in, and moves it to **Monitor 1**; you drive
from the open app. When the test server is enabled, the `aipacs-control`
`launch_app` / `login` / `move_app_to_monitor` tools can do this end-to-end; otherwise follow the
[Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md) (deterministic monitor switch =
`Win+Shift+←/→`). **If the GUI stops responding, ask the user** — never random-relaunch and never
open the frozen exe.

---

## 4. Testing the app

### 4.1 Verify lane — offscreen tests in the Linux sandbox (added 2026-06-21)
Full recipe and caveats: [`../../tools/dev/SANDBOX_TESTING.md`](../../tools/dev/SANDBOX_TESTING.md).

```bash
bash tools/dev/sandbox_setup.sh      # installs everything in requirements.txt (idempotent, resumable)
source tools/dev/sandbox_env.sh      # LD_LIBRARY_PATH (vendored libEGL/PortAudio) + QT_QPA_PLATFORM=offscreen
python3 -m pytest tests/code/<target> -p no:debugging -q
```

- **Covers:** ~1955 collectable tests — pure-Python logic **and** Qt widgets under
  `QT_QPA_PLATFORM=offscreen` (PySide6/vtk/SimpleITK/DICOM stack all import).
- **Does not cover:** the real GUI, actual rendering, VTK render windows, or Windows-only
  `comtypes` (inert on Linux). Those need the Clinical lane.
- Sandbox installs **do not persist** between sessions — re-run `sandbox_setup.sh` each session.

### 4.2 Tests on Windows — the blessed path
See [`.github/prompts/run-tests.prompt.md`](../../.github/prompts/run-tests.prompt.md) and
[`../../tests/QUICKSTART.md`](../../tests/QUICKSTART.md).
- Bootstrap-aware: `python main.py --run-tests <args>` (wrapped by `run_test.ps1`).
- Direct unit tests: `.venv\Scripts\python.exe -m pytest <args>`.
- **Always keep `-p no:debugging`** (`tests/code` shadows the stdlib `code` module).
- **Never** let a DB test write to the live `user_data/database/dicom.db` — patch
  `PacsClient.utils.data_paths.DATABASE_FILE` and clear the pool (CLAUDE.md → DB isolation).

### 4.3 GUI / live verification
Drive the patient → thumbnail → viewer workflow per §3, then confirm against the logs (§5).
This is the lane for observing real GUI behavior; the Verify lane is a pre-filter, not a
substitute. Neither lane alone establishes clinical diagnostic validity; image interpretation
requires the appropriate human/radiologist validation.

---

## 5. Logs — your control feedback loop

Primary directory: `user_data/logs/` — inventory and scan guidance in
[`.github/prompts/inspect-logs.prompt.md`](../../.github/prompts/inspect-logs.prompt.md).

- `app.log` — general application log (+ rotations).
- `download_diagnostics.log` — socket download + thumbnail pipeline. Thumbnail success =
  `right_panel_socket_start` → `right_panel_socket_done thumbnail_count=N` within ~1–3 s; failure
  = `right_panel_socket_error`, a ~45123 ms timeout, or port `105` usage.
- `viewer_diagnostics.log` — viewer / rendering / stack-drag (note: some viewer traces route
  here, **not** `app.log`).
- `db_diagnostics.log`, `com_trace.log`, `native_fault*.log` — DB, COM interop, native crashes.

**Analyze logs before major changes** — it's a project rule (CLAUDE.md).

---

## 6. Hard rules — never (recap; full list in CLAUDE.md & README §4)

- **Source build only.** Never run the frozen `d:\ai-pacs\aipacs\aipacs.exe`, the desktop icon,
  or the black taskbar icon — they ignore source edits. The source build = the **Python icon**.
- **One instance.** Never spawn multiple AI-PACS instances (the single-instance guard would just
  raise the old window, so your new code never loads).
- **Human-assisted bootstrap is default.** Don't burn cycles automating launch/login/monitor
  moves/process recovery — ask the user.
- **Preserve functionality.** No unrelated refactors; minimal safe edits; respect the
  regression-guard discipline (guard test that fails-before/passes-after + a
  `REGRESSION_CATALOG.md` row).
- **Testing rails.** Keep `-p no:debugging`; never write to the live `dicom.db`.

---

## 7. Start-of-session checklist

1. Read [`../../CLAUDE.md`](../../CLAUDE.md), this guide, and (for GUI work) the
   [Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md).
2. **Code/logic change?** Verify lane: `bash tools/dev/sandbox_setup.sh` →
   `source tools/dev/sandbox_env.sh` → run the **targeted** suite for what you changed.
3. **GUI/workflow change?** Confirm the app is open on Monitor 1 (human-assisted bootstrap, or
   `aipacs-control launch_app` when the test server is on), then drive it via the **command
   surface (§3.1)** — falling back to desktop control for visual checks — and confirm via logs (§5).
4. Ship the fix the framework's way: minimal edit **+ guard test + catalog row**, tasks tracked.

---

## 8. Cross-references

- [`../../CLAUDE.md`](../../CLAUDE.md) — project rules, subsystem regression guards, bootstrap mode.
- [`./README.md`](./README.md) — first-five-minutes onboarding + the four rituals.
- [Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md) — launch / login / monitor control.
- [`../../tools/testing/aipacs_control_mcp/README.md`](../../tools/testing/aipacs_control_mcp/README.md) — **the in-app control surface** (`aipacs-control` MCP / CommandBus / Test Control Server). Architecture: [`../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md`](../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md); fidelity vs. real clicks: [`../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md`](../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md).
- [`../../tools/dev/SANDBOX_TESTING.md`](../../tools/dev/SANDBOX_TESTING.md) — Verify-lane setup (this session's addition).
- `.github/prompts/` — [`root-cause-fix`](../../.github/prompts/root-cause-fix.prompt.md),
  [`debug-thumbnails`](../../.github/prompts/debug-thumbnails.prompt.md),
  [`inspect-logs`](../../.github/prompts/inspect-logs.prompt.md),
  [`run-tests`](../../.github/prompts/run-tests.prompt.md),
  [`regression-guard`](../../.github/prompts/regression-guard.prompt.md).
- [`../../tests/QUICKSTART.md`](../../tests/QUICKSTART.md) · [`../INDEX_BY_SUBSYSTEM.md`](../INDEX_BY_SUBSYSTEM.md) · [`../../tests/INDEX_BY_GUARD.md`](../../tests/INDEX_BY_GUARD.md).

*Created 2026-06-21 alongside the sandbox Verify-lane setup; the in-app command-surface control
path (§3.1) was documented the same day.*

### Direct Eagle Eye MCP workflow (2026-09-25, OPT-51)

The shared CommandBus now registers search_patients/read_patients and Eagle Eye
open, series, select_series, functions, run, inputs and status actions. The stdio
bridge exposes search_patients and eagle_eye; the authenticated Agent Gateway
advertises the same registered actions. No new listener, role flag, authentication
bypass or screen-input path was introduced. This is shared Standard/Server GUI
source; the headless inference service is still controlled through its job API.

Workflow: search_patients(source=local|server, patient_id=...) -> read_patients ->
open_patient(exact patient/study) -> eagle_eye(open, study_uid) -> eagle_eye(series)
-> eagle_eye(select_series, exact series_uid) -> poll eagle_eye(functions) until
that series is loaded -> eagle_eye(run, catalog function) -> poll status. Series
responses include descriptions/protocols; ambiguous UIDs are rejected, not guessed.
No claim of anatomical suitability follows from a series number or modality.

Inputs: Total Spine run requires projection=coronal|lateral. After loading, status
returns image dimensions and indexed images; inputs accepts image_index when a
series contains several images, or region=[x0,y0,x1,y1] in source pixels for coronal
analysis. Existing ROI geometry validation and worker execution are reused.
Brain requires t1_series_uid and inputs_verified=true; optional flair_series_uid
must be distinct and available in that examination. Lesions additionally require
FLAIR and an explicit clinical_context from the existing disease selector. These
are caller attestations, never automatically inferred clinical review. Structured
selection skips the modal picker and uses the existing demographics/inference
workers. Legion's separate source-viewer ROI route is not automated by this slice.

Ownership: exact study and loaded series must match before dispatch. Opening a
workspace is not analysis completion. Active jobs reject duplicate runs. Status
reads worker/UI state without filesystem work; Alignment/Spine/Brain return
running, needs_input, failed, cancelled or result_ready. Native Breast/Bone callback
completion is tracked; Lumbar idle does not certify completion, and its detailed
structured outcome remains a follow-up. Brain input changes cannot reuse a
completed result under different input selections. Read-only agents cannot run
analysis or apply a region. Read results use the current Home table, not the
accumulated server search cache, and do not launch a new empty search.

Evidence: three new guards failed before implementation. The focused combined
suite passed 163 tests (exit 0; existing SWIG warnings); 472 plugin mirror pairs
matched. A real stdio MCP initialize/tools-list handshake exposed 60 tools,
including the two new wrappers. Application ping still reports no local control
listener. Thus no new patient-level MCP acceptance, installed artifact acceptance,
Razi UI deployment or service restart is claimed. The human must select the
source TestServer test launch or paired normal Agent Gateway path; never silently
replace MCP with desktop clicks or enable a LAN gateway. Ordinary launch remains
AIPACS_TEST_SERVER=0. All new UI worker paths still require live acceptance.
