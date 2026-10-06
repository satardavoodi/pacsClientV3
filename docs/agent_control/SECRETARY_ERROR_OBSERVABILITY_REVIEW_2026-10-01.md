# Secretary error observability review

This is a code review and proposed implementation contract, not a diagnosis of
the current machine. No patient logs, Windows event messages or crash dumps were
exported. No runtime changes are made by this review.

## Current coverage

| Evidence | Existing path | Limit |
| --- | --- | --- |
| Function availability | Shared registry `list_actions`, typed entity schemas, CommandBus permission decisions | Registration proves callable access, not successful end-user behavior |
| Function failure | `CommandResult`, registry `UNKNOWN_ACTION`/`ADAPTER_ERROR`, execution receipts and Secretary session tracing | Some adapters return initiation or dialog-open success; later workers need separate terminal receipts. Registry exception messages can contain technical details and need presentation filtering |
| Resource pressure | `snapshot_resources`; asynchronous settings `diagnose_resources` plus operation polling | Resource samples do not prove the root cause of a download/viewer defect |
| App/component logs | `diagnostic_logging.py`: `app.log`, `viewer_diagnostics.log`, `download_diagnostics.log`, `db_diagnostics.log` under resolved runtime log root, asynchronous file logging | No unified production Secretary action for bounded sanitized retrieval/correlation |
| Native exceptions/hangs | `native_fault_log.py`, process/session-exclusive sinks, hang watchdog; external `native_fault_probe.py` | Legacy shared history has unreliable attribution/time. A native exception record is not automatically a terminal crash |
| Test MCP health | `snapshot_health`, `run_scenario` actual baseline and liveness checks | Test tooling is distinct from production Secretary. Retrospective native inventory is explicitly inconclusive |
| Visible error dialog | Existing UI and test lifecycle dialog helpers | No general structured error registry for Secretary; startup dismiss helpers are not error analysis |
| Windows Application/WER | `collect_windows_crash_evidence.py`, `collect_pc_crash_evidence.ps1` | Offline engineering collectors, not shared Secretary actions. Existing Python filter ORs generic crash providers/messages and therefore includes unrelated apps; it returns raw messages and uses unbounded whole-file log reads before tailing |

## Proposed shared diagnostic service

Expose finite read-only actions through the existing CommandBus, then thin MCP
wrappers. Proposed names are not currently registered:

1. `get_recent_operation_failures`: bounded terminal receipts keyed by action,
   operation/session ID, status, sanitized error code, start/end time and retry
   eligibility. Link background saves/sends to their originating action; retain
   partial/unknown outcomes. Do not automatically replay clinical writes.
2. `get_visible_app_errors`: app-owned error events and active-dialog descriptors
   gathered on the GUI thread without file/network work. Prefer stable category
   and message codes. Do not scrape arbitrary QTextEdit content, login controls,
   reports or patient windows. Uninstrumented messages require local inspection;
   generic screenshot delivery would need its own sensitive-image contract.
3. `collect_support_diagnostics`: worker-owned bounded tails from fixed runtime
   log filenames and current-session native sources, resource samples, download
   and relevant workflow status. No caller-controlled paths or shell commands.
4. `get_app_windows_events`: worker/helper query for local Application events
   attributable to this product, with a time window, hard record/byte limits and
   explicit coverage/access status. This action must survive loss of app IPC by
   running in an external support helper when the desktop is hung or closed.
5. `analyze_support_diagnostics`: sanitized evidence to authenticated Eagle Eye
   Server; structured findings mapped to plain-language local presentation.
   The diagnostic server request/schema is still outstanding. No direct company
   provider route, automatic arbitrary code or speculative ticket receipt.

Bind evidence to process start time as well as PID, app version and session token.
Use timestamped app records and action correlation IDs. For native records use
actual before/after byte windows; file mtime is not an event timestamp. If the
GUI heartbeat stops, a timeout means unresponsive/unavailable, not proof of crash.
Polling a live app's CommandBus cannot itself diagnose a dead GUI process.

## Windows Application implementation requirements

Microsoft supports filtered `Get-WinEvent` queries and native structured
`EvtQuery`/`EvtRender`; native bookmarks can resume subsequent queries. See
[Get-WinEvent](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.diagnostics/get-winevent)
and [Querying for Events](https://learn.microsoft.com/en-us/windows/win32/wes/querying-for-events).

- Query the local Application channel only, bounded by time and known relevant
  providers/event types. Use structured XML/EventData for attribution, not a
  localized Message substring such as "Faulting application".
- Require exact installed executable identity/path or an approved executable
  identity plus supporting attribution. Source runs use generic `python.exe`:
  that basename alone cannot prove an AI-PACS event. Correlate with verified
  process/session/path evidence; otherwise mark unverified and exclude it from
  confirmed product failures. Time/PID alone can be ambiguous after PID reuse.
- Return a bounded safe projection: UTC time, record ID, provider, event ID,
  severity, validated exception code and allowlisted fault-module category.
  Keep raw XML, messages, command lines and full paths local. Generic WER reports
  and memory dumps may contain sensitive data and are not automatic uploads.
- Execute fixed queries with parameter validation and subprocess deadlines (or
  a native API worker); no arbitrary PowerShell supplied by the model. Limit
  query candidates as well as final matches. If a limit is reached, mark coverage
  partial; zero matches never certifies absence outside the covered window.
- Distinguish no matches, access denied, unsupported platform, query timeout,
  incomplete scan and malformed event. Do not silently suppress errors and
  present a clean result. No automatic elevation or event-log clearing.
- Normal access depends on the machine/channel ACL. Report an access restriction
  if present; do not require running the entire clinical app as administrator.

## Privacy and user-facing findings

Local technical evidence and server-safe evidence are different products.
Prefer known structured codes/counts to exporting raw logs with regex redaction.
Never include patient identity, DICOM, report/prompt text, credentials, tokens or
arbitrary user files in the remote diagnostic payload. Preserve local evidence
for authorized support review without adding it to conversation history.

Findings need evidence references, observed versus inferred cause, confidence and
safe next steps. Present "The download did not complete" or "Windows recorded a
crash in the imaging component" only when evidence supports it. Otherwise say the
cause is not confirmed. CPU pressure is an observation, not a diagnosis of MPR.
No company ticket/reference is reported until a future transport acknowledges it.

## Acceptance and ownership

Implement under existing OPT-23 Secretary control ownership, with native/crash
evidence coordinated with OPT-21 and existing subsystem owners. Do not alter
viewer decoding/render internals as part of diagnostic collection.

Synthetic verification must cover unrelated-app rejection, generic Python
attribution, sensitive fields, event access failures, no-match distinction,
timeouts/truncation, rotated/partial logs, PID reuse, GUI-thread isolation and
asynchronous completion. Live source acceptance must verify a controlled app
error, its operation receipt, local evidence and displayed explanation; Windows
crash attribution is a separate gate. Never induce a clinical crash to test it.

For this review, source and Microsoft API documentation were inspected and the
document validated. No live error workflow, Event Log access or server diagnostic
endpoint was tested. The proposed production actions remain unimplemented.

Follow-up: bounded support collection, visible severity and recent function-result
projection are now source implemented; see
[implementation receipt](SECRETARY_SUPPORT_COMMUNICATION_IMPLEMENTATION_2026-10-01.md).
Root-cause analysis and exact-session Windows attribution remain outstanding.
