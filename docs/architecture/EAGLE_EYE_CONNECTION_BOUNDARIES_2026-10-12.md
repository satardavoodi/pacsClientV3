# Eagle Eye Server and mobile/Workstation connection boundaries

Owner decision: 2026-10-12. This contract supersedes older statements that require
device pairing, client certificates, a caller-supplied provider token, or HTTPS
for ordinary Eagle Eye Server access. It does not declare legacy code migrated.

## Two independent destinations

| Connection | Features | Required connection contract |
|---|---|---|
| Windows DICOM Workstation Client to Eagle Eye Server | EchoMind, native Secretary EchoMind, CRM, Eagle Eye imaging functions | Configured HTTP IP and port, existing username/password, upstream identity and internal permission gates |
| Android/iOS to Eagle Eye Server | EchoMind, Agent targeting Secretary EchoMind, CRM/Office | The same ordinary HTTP and username/password contract |
| Android/iOS to Windows DICOM Workstation Client | Remote Agent PACS execution | Separate QR pairing and HTTPS connection; neither endpoint is assumed to have a static public IP |

Eagle Eye Server has a configured static public IP and forwarded port. LAN and
public addresses identify the same service; callers must not select a different
identity provider, certificate mode or permission policy based on network location.
Pairing belongs only to the mobile-to-Windows-Client remote Agent PACS connection.
Do not remove its QR/HTTPS protections to implement ordinary Eagle access.
Windows uses its native Secretary and does not need the mobile Agent PACS UI.
Mobile Eagle Eye image-analysis requests are not a current product feature;
their absence is intentional, not an implementation defect.

Current test endpoints are HTTP on LAN 192.168.2.222:8002 and public
81.16.117.196:8002. These are deployment examples, not hardcoded installation
defaults. HTTP does not encrypt credentials or clinical data in transit.

## Ordinary Eagle authentication and dispatch

1. The caller supplies its existing username/password to Eagle Eye Server.
   There is no separately provisioned device certificate, pairing identity,
   company key, or caller-supplied PACS/provider bearer token prerequisite.
2. The server checks PACS first. A definitive credential rejection permits a
   check with Reception. A provider outage is not a credential rejection and
   must not silently select another identity. If neither authenticates, deny.
3. The server checks its own enabled user and feature/module grants. Upstream
   administrator status or a valid product license does not replace these gates.
   Denial of the resolved user's local grant must not try another identity.
4. Dispatch the authenticated request to the matching server subsystem:

| Route family | Server subsystem | Local grant |
|---|---|---|
| `/v1/echomind/*` | EchoMind | `echomind` |
| `/v1/secretary/*`, including `/remote/*` | Secretary EchoMind | `secretary` |
| `/v1/crm/*` | CRM | `crm` |
| `/v1/jobs*`, `/v1/imaging/*` | Eagle Eye imaging | `imaging` plus requested module |

The existing implementation issues an opaque `X-Eagle-User-Session` after the
password exchange and verifies upstream identity and local grants on protected
requests. This is an internal session mechanism, not a user-supplied token or a
third admission gate. CRM may maintain a downstream workflow session; it must not
be confused with device pairing or proof that every PACS-authenticated user is
also a Reception user. Record any additional identity restriction as a gap.
Public capabilities, transport heartbeat and actual business execution are
different checks; a capability response is not proof of admission or execution.

## Implementation audit at adoption

This is source inspection plus the explicitly listed prior live evidence, not a
new comprehensive acceptance test. No runtime code or host settings changed.

| Component | Established behavior | Remaining delta or evidence limit |
|---|---|---|
| Eagle Server | `server.py` accepts ordinary access without paired bearer; `user_access.py` password mode resolves PACS then Reception and enforces enabled/feature/module grants; route families dispatch separately | Legacy `provider/upstream_token` login and optional paired-bearer access remain implemented. They are not prerequisites and are not the owner-approved ordinary client contract |
| Windows Client | Shared `eagle_eye_remote/client.py` accepts HTTP and uses the ordinary session for EchoMind, Secretary, CRM and imaging routes | `user_session.py` still falls back to caller PACS token when captured credentials are absent; optional legacy bearer/certificate settings remain in Client. Removal or migration is not completed by this document |
| Android | Shared Eagle client supports HTTP/password session; Secretary/EchoMind/CRM use it | Legacy PACS-token fallback remains. Main credentials are captured only after socket login succeeds; if that login rejects a Reception-only account, no normal UI path sends it to Eagle password fallback. The socket is RIS-proxy-aware, so rejection of all such accounts is not established and no actual account was tested. CRM downstream Reception identity must be distinguished from Eagle admission. Remote Agent PACS pairing is intentional and out of this Server workstream |
| iOS | Ordinary Eagle password session, HTTP endpoint, Secretary/EchoMind/CRM routing; no paired bearer prerequisite | Main iOS sign-in first requires PACS success, so a Reception-only account may never reach Eagle fallback. CRM reuses the same credentials for a separate Reception workflow identity. Remote Agent PACS pairing is intentional and out of this Server workstream. Platform-specific ATS coverage for arbitrary future installation addresses is not proven by the current test IP |

Prior live evidence: Android emulator LAN/public HTTP authentication and Secretary
status passed; distinct patient-list commands reached execution and failed without
a confirmed list/count receipt. iOS simulator native HTTP connection, Secretary
session/history and one command response passed transport, but the patient-list
operation failed. These are not physical-device acceptance or a pass for CRM,
EchoMind reporting or every Windows imaging function. The Secretary business
failure remains separate from HTTP authentication and pairing.

## Ownership and verification discipline

### Prepared corrections after the adoption audit

The owner subsequently authorized coordinated implementation and acceptance.
The prepared Server rejects caller upstream-token login; Windows uses captured
passwords and removes ordinary device bearer/certificate loading. Ordinary
connection settings normalize to HTTP without changing the separate Workstation
Agent PACS pairing configuration. Hosted read-only CRM delegates the already
verified Eagle identity and CRM grant to its private worker, retaining configured
Reception data authentication without requiring that person to log into Reception
again. These changes are inactive until the reviewed shared candidate is activated.

Android and iOS owners are qualifying the same existing-login fallback: only a
definitive credential rejection permits the entered credentials to be checked by
Eagle; a successful AI-only identity does not fabricate a PACS token or authorize
PACS viewing. Socket RIS-proxy integration can already admit Reception-backed users
on deployments where it is enabled; source support does not prove that a specific
Reception-only account was accepted. No new provider selector or login form is
part of this contract. Final platform build/native receipts remain authoritative.

The Secretary patient-list failure was separately traced to the legacy executor
returning a row list while verification requires a structured search/list receipt.
The prepared correction uses the registered canonical Home adapter once, then
verifies the exact read receipt and executed dates; it never replays the search to
make verification succeed. Prior failed requests remain failed historical evidence.
Code checks, staged parity, activation, native GUI and real provider/business
acceptance must still be reported independently; none is implied by this note.

The Eagle Server workstream owns ordinary ingress, upstream identity resolution,
internal permissions and subsystem dispatch. Mobile owners implement that shared
wire contract on both Android and iOS. Mobile-to-Workstation QR pairing and remote
execution belong to a separate workstream; do not count them as Server defects.
Main app PACS login, DICOM viewing/transfer, speech and report-delivery protocols
are not redefined by this ordinary Eagle ingress decision.

Future audit receipts must distinguish contract, actual source, active source,
automated checks, native UI acceptance and real business outcome. Do not label a
legacy route compliant merely because the password path also exists. Preserve
host-private credentials/data and stage documentation/source changes outside
executing Razi revisions under the Developer synchronization policy.


## Server settings enforcement (2026-10-12)

The Server Agent page retains usage and ordinary HTTP connection guidance, but does not construct the mobile gateway, generate QR pairing codes, or manage paired execution devices. Server Home skips gateway installation and startup; service installation/start methods also reject the Server role. Secretary command routing, CRM and EchoMind use the shared Eagle HTTP listener and existing upstream credential/internal grant gates. Windows Client mobile execution pairing and HTTPS remain unchanged.
