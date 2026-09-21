# OPT-04: Download Manager response framing and broadcast review

**Later bounded follow-up:** [file-count gate and retry destination ownership](DOWNLOAD_FILE_COUNT_GATE_2026-09-15.md)
adds guarded completion/accounting and collision-safe retry corrections. The
unchanged-boundary statements below describe this response-framing slice, not the
later follow-up. Neither slice closes durable study-manifest completion or GUI acceptance.

## Decision and scope

Correct the reproduced socket-response boundary only. This is a reliability fix,
not a scheduling/performance cutover, completion-model rewrite or UI redesign.
The frozen-manifest/disk completion gate remains a prerequisite to further
download-path optimization. A progress bar or successful worker notification
alone still does not prove complete local study content.

Reviewed the current pipeline, historical Zeta review, Overall Progress contract,
Home/Download Manager authority, worker bridge, cancellation/retry, persistent
socket handling and packaged payload. No claim is made that every historical DM
finding is closed. The other runtime trees and pre-existing dirty work are preserved.

## Evidence and provenance

The September 15 15:43:24 source run recorded one request failure at 15:44:26 in
its download child: three ERROR records describe the same `GetSeriesImages`
attempt reaching ten broadcast frames without accepting a response. These are
not three independent failed downloads. The trace cannot establish whether the
server subsequently sent the requested response; it does prove that the client
stopped listening because of its fixed notification-count limit.

Git history matters here: `44a454bf` introduced the earlier configurable broadcast
limit and tolerant JSON text decode. `7662e10e` (July 25) removed those helpers,
the payload-key compatibility helpers, and restored the hard limit of ten.
Current source already had those removals before this slice; associated tests
remain in the repository. This explains the discrepancy between old claims and
the current baseline, but the commit message alone does not establish why they
were removed. Do not blindly restore the entire historical file.

Three reproduced receive/connection defects:

1. Ten legitimate broadcasts cause failure even when a valid reply is next.
2. One `recv(4)` was assumed to return the complete length prefix. Fragmented
   prefixes can yield zero/incorrect lengths and lose stream alignment.
3. `_send_request_once` acquires the client lock, then calls `connect` if needed;
   `connect` acquires that same non-reentrant lock, producing a self-deadlock.

Additional safety at the same seam: partial/invalid frames must retire the socket
even on the last attempt. Otherwise unread data can contaminate a later request.
These are local client defects. No server configuration, clinical data, routing,
credentials or live database was changed, and server correctness is not asserted.

## Chosen correction

Only `modules/download_manager/network/socket_client.py` and its existing plugin
mirror change at runtime:

- Read all four prefix bytes before interpreting the length; preserve exact body
  reads, the 500 MiB allocation ceiling and linear `bytearray.extend` accumulation.
- Skip complete broadcast frames without interpreting them as request retries.
  Use the existing configured socket timeout (default 30 seconds) as the elapsed
  wait budget, checked between broadcast frames. After a broadcast, header reads
  use the remaining budget rather than restarting a full timeout per fragment.
- Restore the ordinary receive timeout before each frame body. A legitimate large
  body retains the existing per-receive timeout: no new whole-batch deadline or
  short polling timer is introduced. This is **not** a hard deadline for reading,
  decoding or processing an entire large frame; an in-progress frame may exceed
  the between-frame budget. Changing that is a separate transport policy.
- Check cancellation before/between header reads and retain existing body/backoff
  cancellation. Discard invalid/partial/expired streams before reuse. Zero-length
  or non-object JSON envelopes are rejected. Valid server errors remain unchanged.
- Use an owner-reentrant lock so an already serialized request may connect safely;
  other threads are still excluded. No extra thread or GUI work is introduced.
- Log one PHI-free `[SOCKET_RESPONSE]` summary when a response follows broadcasts.
  Do not log their payloads or invent download completion from that marker.

UTF-8 decoding, base64/gzip/DICOM normalization, image numbering, file writes,
batch sizes/indexes, retry budgets, connection targets and authentication remain
unchanged. In particular this slice does not restore lossy text replacement or
alternate payload keys merely to make old tests green.

The Python [socket guide](https://docs.python.org/3.13/howto/sockets.html#using-a-socket)
requires callers to accumulate partial receives, including the length prefix;
[`recv`](https://docs.python.org/3.13/library/socket.html#socket.socket.recv) returns
up to the requested size. The synthetic guards exercise this contract directly.

## UI / worker boundary review

| Boundary reviewed | Preserved behavior / qualification |
|---|---|
| Home/thumbnail/viewer intent | Existing DM task and SeriesIntentCoordinator remain the authority; no GUI-side direct download fallback added. |
| Queue row and right-hand Overall Progress | Same state counters and authoritative manifest; UID-keyed accumulator, monotonic numerator and duplicate-series-number handling unchanged. |
| Progress throttling | Worker bridge cadence and main-process batched state/signals unchanged; no per-broadcast Qt signal, new GUI I/O or per-image widget work. |
| Selected/bulk controls | Pause/cancel/resume/retry and protected-drag rebuild rules untouched. Resume and keep-files guards run. |
| Priority | Same-study yield versus cross-study preemption remains distinct; resumable data is not deleted by this correction. |
| Completion | Worker computes success against frozen totals/failed-series state; UI projects worker success. This is not independent disk-manifest convergence proof. |
| Process/package | Existing spawn-safe worker entry and optional DM payload; no runtime catalog/config-family/module additions. Mirror verified, installer not built. |

Residuals deliberately not bundled: durable manifest-on-disk completion proof;
terminal IPC delivery audit (the worker's final `result_queue.put` is currently
unbounded, while progress/manifest puts use different policies); stale UI-row
convergence; and historical payload/encoding compatibility. Resolve the completion
contract before claiming complete studies or making further scheduling changes.

## Verification

- Before runtime changes, the initial new synthetic file reported **31 failed /
  4 passed, exit 1**. Failures cover fragmented prefixes, >=10 broadcasts, stream
  retirement, cancellation and reconnect self-deadlock. The deadlock guard releases
  its test-only lock after the timeout so no blocked test thread remains.
- Final new file: **38 cases**, including 0/1/9/10/11/75 broadcasts, 1/2/3-byte
  fragmentation, consecutive replies, notification-only expiry, remaining header
  timeout/restoration, slow legitimate bodies, malformed/partial frames, unchanged
  server errors, cancellation and reconnect. Real loopback `socketpair` exchange
  also passed; no PACS account, patient fixture or clinical DB is used.
- Expanded selection: **189 passed, 6 SWIG warnings, exit 0**, 46.50 seconds.
  Includes Overall Progress, UI initialization, retry file retention, resume,
  critical yield, cancellation escalation, protected-drag rebuilds, worker cleanup,
  priority dedupe, multi-study identity, folder collisions and retry classification.
- Builder selection: **5 passed, exit 0** (plugin registry plus fresh-mirror guard).
  One DM source mirror synchronized; **465 matching pairs**, zero plugin-only files.
- Final focused rerun after routing the summary through the existing IPC log
  component: **70 passed, 6 warnings, exit 0**, including all new wire guards and
  builder checks. This keeps the summary visible under the current log levels.
- Scoped whitespace/diff review: only the response client/payload change at runtime.
  UI/controllers, series downloader, encoding/normalization and storage are untouched.

### Known pre-existing baseline failures (not hidden)

Initial collection including `test_instance_payload_key_variants.py` failed because
`_INSTANCE_PAYLOAD_KEYS` is absent. A second baseline selection reported **5 failed /
28 passed**, including four missing tolerant-decode contracts and one old
configurable-count-limit assertion in `test_socket_payload_tolerant_decode.py`.
These failures existed before this patch and match the July 25 removals. The old
count-limit assertion is additionally superseded by the tested elapsed-budget
decision here; it has not been silently deleted or treated as a pass. The broader
DM suite is **not declared green**. No quarantine changes, encoding restoration,
heavyweight build or full installed acceptance were performed.

## Remaining source GUI gate

Existing `aipacs-control` tools were absent from the tool inventory; its documented
`client.py` successfully performed ping and action discovery. The running source
session predates this change. Do not count a worker spawned from mixed old/new
runtime state as full acceptance. Human fresh source launch with the test server,
disk-notice OK and sign-in is required; no installed launch, duplicate instance,
hot reload, invented control path or authentication automation.

Use an authorized nonclinical test case to exercise queue/details Overall Progress
across multiple series, selected pause/resume, safe retry retaining files and series
priority. Check rendered images, exact Study/Series identity and actual local counts.
Inspect phase summaries, errors and terminal state for that fresh session. If no
broadcast burst occurs, ordinary download acceptance does not reproduce this edge;
the deterministic wire tests remain its direct proof. Do not inject broadcasts into
the production server or cancel an unrelated clinical download to force a scenario.

## Rollback

Revert only this response-client diff and resynchronize its existing payload. There
is no schema, file-format, UI or configuration migration to undo. Keep the evidence
and guards so the prior failure is explicit. Do not roll back the whole dirty
worktree or unrelated files. Full OPT-04 remains staged rather than closed.
