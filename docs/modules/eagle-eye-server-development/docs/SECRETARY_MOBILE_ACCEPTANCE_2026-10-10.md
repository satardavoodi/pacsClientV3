# Shared Android and iOS Secretary acceptance

Status: preparation only. No test in this matrix has run. Active Razi revision r4
is not the reviewed candidate and must not be reported as candidate acceptance.
The Windows workstation client is the next phase and is outside this matrix.

## Shared behavior and scope

Both mobile applications use ordinary authenticated Eagle Eye Secretary access.
The existing `vahid` account must pass the upstream identity check and the Server
Secretary permission check. Keep passwords, tokens and patient data private.
IP/port reachability, authentication and permissions are separate results.

Secretary executes through the dedicated native Server runtime/session. Record
its exact source selection, runtime identity, session and owned action boundary
before submission. A mobile UI result alone does not establish native execution.
Use device pairing or a client certificate only when the actual Agent PACS
action contract requires it. Do not add device pairing to ordinary Secretary
authentication. Preserve TLS verification and the existing trusted server
identity; never disable certificate validation to obtain a pass.

Reply in the language of the submitted text. An English request requires an
English answer; a Persian request requires a Persian answer. Interface language
selection must not override an unambiguous request language.

## Candidate and device prerequisites

- Reconcile and hash the reviewed local and Razi source snapshots. Record staged
  parity separately from activation and verify the running process selects that
  exact candidate. Do not overwrite executing source or interrupt clinical work.
- Record the authoritative Android source/revision on Windows and the authoritative
  iOS source/revision on the Mac, their build identifiers and installed device builds.
- Verify the dedicated native runtime/session is ready, bound to the reviewed
  Server, and authorized for the intended read-only patient-list action.
- Record current Server Brain connection readiness separately from upstream
  provider execution. A capability or health response is not provider acceptance.
- Confirm `vahid` has the Secretary grant. Record permission denial as a denial;
  do not bypass it with super-admin credentials or alternate routes.
- Devices must be ready in their native apps. iOS availability is confirmed for
  preparation; a device/UI execution receipt is still required.

## Primary route matrix

Each primary row submits exactly one today-patient-list request after its
prerequisites pass. No duplicate submission is permitted after a lost response.
The chosen request language and clinical local date/timezone must be recorded
privately before submission; the result must cover that same date.

| Case | Platform and route | Exact configured endpoint | Request | Initial status |
| --- | --- | --- | --- | --- |
| IOS-WAN-SECRETARY-01 | iOS external network | `https://81.16.117.196:8002` | Owner's exact Persian today-patient-list request, entered privately once | Not run; candidate activation pending |
| ANDROID-LAN-SECRETARY-01 | Android internal network | `http://192.168.2.222:8002` | Owner's exact Persian today-patient-list request, entered privately once | Not run; candidate activation pending |
| ANDROID-WAN-SECRETARY-01 | Android public endpoint from the local test network | `https://81.16.117.196:8002` | Owner's exact Persian today-patient-list request, entered privately once | Not run; candidate activation pending |

Record the actual network route on the device. The owner requested Android access
through both the LAN and public addresses while Android is local; a successful
public-address hairpin route satisfies that address test but does not establish
independent cellular/external-network acceptance. iOS uses the external Mac route.
Do not change firewall rules, port forwarding or TLS trust as part of this matrix.

All three primary requests use the owner's exact Persian text and require a
Persian response. Keep that text in the private execution receipt to preserve
the repository's English-only policy. Existing English-language tests are
separate evidence; these rows do not establish English behavior or authorize
extra inference requests.

## Exact native action contract

The native owner confirmed the read-only sequence:

`advanced_search_patients(date_from=client_local_date, date_to=client_local_date)`
followed by `read_patients` for the verified ready count. Both date fields use
the same client local date in `YYYYMMDD` format. Use the existing active/server
source; do not substitute another source to manufacture a result. Correlate the
search completion, ready state, read result and terminal receipt/history.

Only safe state, aggregate count and source metadata may reach the mobile result
or shared evidence. Patient records remain private. This action does not download
images, load studies or mutate a viewer. Native scoped implementation/freeze is
pending; every primary test remains `Not run`.

## Independent receipt dimensions

Keep one private evidence bundle per case. Publish only aggregate status/counts
and sanitized evidence references or digests. Do not include patient names, IDs,
images, full lists, clinical prompts, report text, credentials or raw logs here.

| Dimension | Required evidence | A passing result does not establish |
| --- | --- | --- |
| Source | Android/iOS source revision; Server source manifest/hash; parity and active-process selection | Build or device execution |
| Build | Build command/result, exit code, app build ID and installed build match | Native UI or connectivity |
| Device/UI | Device/session, actual Secretary screen, one submission, rendered answer and error state | Server action completion |
| Network | Device route, endpoint, timing and TLS verification outcome for WAN | Authentication or permission |
| Authentication | Existing `vahid` identity accepted by the approved Server flow; sanitized receipt | Secretary grant |
| Permission | Explicit Secretary permission decision for this account/session | Action execution |
| Native runtime | Exact dedicated runtime/session identity and owned action boundary | Terminal success |
| Action | Correlated request/action identity, terminal action receipt and matching history entry | Correct displayed result |
| Result | Aggregate returned count/status, correct local date, matching request language and UI delivery | Image loading or download |

An HTTP 200, accepted job, action proposal, capability response, spinner completion
or textual claim by the LLM is not a verified terminal action. Require the actual
terminal receipt and history correlation from the owned native action executor.
Record failed, canceled, refused and completion-unknown states distinctly.

## Fetched, loaded and downloaded are different

For this patient-list test, a successful read-only fetch is the expected scope.
Report the count of fetched records and the displayed aggregate result. Loading
a study into a viewer and downloading image data are separate actions and are
not requested or implied. Mark them `Not requested`, not `Passed` or `Completed`.
Do not allow a generated answer to claim images were loaded or downloaded when
only the list was fetched.

## Failure and lost-response handling

1. Record the initial request/action correlation once and retain it privately.
2. If delivery or polling fails after submission, use only the existing GET
   status/history/result routes to resolve that same operation. Preserve bounded
   deadlines and distinguish transport failure from terminal action failure.
3. Do not resend the submission, execute the proposal twice, repeat a mutation,
   or change identity to obtain a result. If the response was lost before a
   correlation identity was obtained, use an existing read-only lookup for that
   submission if supported; otherwise mark completion unknown and stop that case.
4. Verify terminal receipt/history before rendering a success conclusion. A
   retained prior answer must not be mistaken for the current request's result.
5. Do not inject failures into clinical PACS or restart services for this matrix.
   A controlled lost-response test requires a separately recorded nonclinical
   setup; ordinary transient failures can be audited without causing another.

## Completion record

| Case | Source | Build | Device/UI | Network/TLS | Auth | Grant | Native session | Terminal receipt/history | Result/date/language | Fetched / loaded / downloaded |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| IOS-WAN-SECRETARY-01 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending / Not requested / Not requested |
| ANDROID-LAN-SECRETARY-01 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending / Not requested / Not requested |
| ANDROID-WAN-SECRETARY-01 | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending | Pending / Not requested / Not requested |

Do not mark the shared workstream complete until both platforms and required
routes have their independent receipts. A blocked route or language is an
explicit coverage gap with its next action; another platform's pass is not a
substitute. Installer/A100 qualification, store publication and the workstation
client remain separate workstreams.
