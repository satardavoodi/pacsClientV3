# Razi client/server path acceptance - 2026-09-30

## Verified active routing

The Standard source client uses the existing paired TLS connection to Razi port 8002. The Windows service runs the 20260930-echomind Developer source revision under LocalService. The existing Razi GUI MCP returned ping and registered Eagle Eye actions; no alternative control interface was created.

EchoMind sends initial text and allowlisted workflow context such as modality, correction note and selected template text. System prompt composition, provider credentials and model settings remain server-owned. The server rejected client model/system_prompt/api_key/source_path fields with HTTP 422 and an invalid token with HTTP 401. This is actual transport verification, not credential disclosure or a clinical security certification.

A fresh paired workstation-to-Razi run passed all 15 synthetic requests across 14 workflows: Report, Turbo, Standard, Assist Standard, ordinary/Turbo Correction, report/text translation, Chat, Breast Assistant, Radiopaedia Assistant, Textbook/DI search, cited Web Search, template organization and linked template translation. Structured-report parsing and required search citation rendering passed. A separate execution through the production desktop remote_backend adapter passed Report, Chat and Web Assist; this is frontend adapter verification, not on-screen composer rendering. The targeted EchoMind remote/core suite passed 55 tests, process exit 0.

## Imaging execution

Fresh actual reference-only requests from the paired workstation caused server-owned acquisition and inference, followed by client identity/artifact verification. No client DICOM upload was used.

| Module | Current source recheck | Elapsed seconds |
|---|---|---|
| Bone Age | Result received and verified | 97.70 |
| Lower-limb Alignment | Result received and verified | 126.06 |
| Total Spine | Result received and verified | 37.75 |
| White-matter lesions | Result received and verified | 235.04 |
| Brain volumetry | Source preflight rejected: absent from PACS and current configured server-local cache | Not run |
| Lumbar | Correct authorized lumbar MR case requested from owner | Not run |
| Breast classifier | Existing feature-schema/weight mismatch, optimization deferred by owner | Not qualified |

These are execution/artifact-plumbing checks, not accuracy, radiologist acceptance, interactive review or clinical qualification. They do not cover every alternate model/profile/projection or correction path. Retained outputs remain in private user_data/ai_validation, with no clinical data in this report.

## GUI boundary and next acceptance

PACS search and study-matched patient open/select succeeded through the existing MCP. The workspace's series inventory remained empty; the download action returned ADAPTER_INCOMPLETE because the command adapter looks for legacy download methods while the real Home port exposes download_studies. The port mismatch is confirmed, but not all empty-series symptoms are attributed to it. This shared download/input defect was handed to its existing owner under the documented workstream boundary: [Unify evidence](../../../reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md#2026-09-30-razi-eagle-eye-mcp-download-handoff).

Remaining: register/locate the authorized Brain source in the actual server local catalog, obtain the lumbar case, resolve the shared MCP download bridge, and verify native result display, manual corrections, exports and EchoMind composer rendering on fresh source clients. Preserve the deferred Breast limitation. No installer/release/whole-server acceptance is claimed.

Private generated receipts: generated-files/eagle-eye/echomind-20260930/client-recheck-workflows.json, desktop-backend-recheck.json, security-boundary-recheck.json and model-recheck-combined.json. No response bodies, credentials or patient identities are retained in these receipts.

## Human-triggered EchoMind/Assist route observation

A metadata-only passive observation of the active Standard GUI process recorded two new connections to Razi port 8002. Both were independently matched to the service using the client ephemeral port. The service also established two upstream HTTPS connections. No request or response bodies were captured. Client/server clocks differ, so raw timestamps are not used as a correlation key.

One additional client HTTPS connection occurred about 24 seconds before the first observed port-8002 connection. Its purpose remains unclassified; it must not be described as usage telemetry or direct inference without evidence. TCP polling cannot identify the patient or workflow, prove response rendering, or exclude requests on persistent or unsampled sockets. Therefore this observation supports the EGLI route for two requests, but is not exclusive-routing or workflow-specific completion proof. The production remote adapter has no automatic direct-provider fallback when the remote route is selected.

Private metadata receipt: generated-files/eagle-eye/echomind-20260930/user-route-verification.json.

## Read-only case history inspection

The requested case has persisted Standard Client ai_sessions/ai_messages records in user_data/database/dicom.db. The latest Turbo report and Web Search requests each have a nonempty assistant response. Their creation times coincide with the two previously observed client connections to port 8002; corresponding service connections were independently matched by ephemeral port. This strengthens the workflow/time correlation, but no shared request identifier exists for exact end-to-end reconciliation. No clinical content or identity is included here.

Server inspection covered the service's configured PACS database, current candidate GUI database and baseline Developer GUI database. None contains ai_sessions/ai_messages tables. The current server EchoMind folder and private configuration directory have no session logs. The hosting path validates and executes a request, then returns the result without persisting a case-linked transcript. Secretary session_logs are a separate workflow and do not provide this remote reporting history. Imaging job logs do not replace EchoMind transcripts.

Required follow-up: use private user_data storage for server-owned request/response history, with authenticated client ownership and authoritative case/session context; return a common request identifier and persist its relation in the existing client conversation repository. Keep bodies out of general diagnostic logs. Do not reconstruct or relabel old requests without provenance. No runtime persistence fix or service restart was performed during this read-only inspection.

Receipt: generated-files/eagle-eye/echomind-20260930/case-history-verification.json.
