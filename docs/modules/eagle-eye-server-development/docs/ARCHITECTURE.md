# Server purpose and architecture

Eagle Eye Server centralizes heavyweight AI execution. Standard remains a complete
DICOM workstation for local viewing, navigation and interaction, but sends references
for Eagle Eye computation. It must not download model weights or silently fall back
to client inference when the server is unavailable.

Data flow: Standard client -> authenticated job API -> source verification/acquisition
on the server -> resource queue -> isolated module worker -> verified derived result
-> client review. Source DICOM comes from PACS on the server side; client requests
contain study/series/SOP references, selected parameters and an idempotency ID.

Results contain masks, landmarks, measurements, reports and input/model provenance.
Client and result identities must match before rendering. No server paths, arbitrary
commands or source image uploads are accepted as client instructions.

## Existing contract

- GET /v1/capabilities: protocol and registered operations, not model readiness.
- POST /v1/jobs: bounded reference request; owner/request-ID deduplication.
- GET /v1/jobs: own recent jobs only.
- GET /v1/jobs/{id}: own job state.
- POST /v1/jobs/{id}/cancel: explicit cancellation.
- GET /v1/jobs/{id}/artifacts: verified derived-artifact archive.

Current operations: breast, bone-age, brain, brain-lesions, lumbar, alignment,
total-spine. They are adapter names, not a claim that assets are installed on Razi.
Client saves a reconciliation handle before POST; connection loss does not cancel
server work. Client.resume can reconcile a lost acknowledgement using the same ID.
Automatic client recovery UI and download byte-range resume remain open.

Legacy Breast /api/v1/run_by_study and /api/v1/run_full_analysis are different APIs.
Reusing8002 does not migrate old clients. Keep the legacy service until updated
client behavior, capacity and rollback are tested.

## Server lifecycle target

Production requires independent SCM service hosting, durable transactional queue,
bounded stop/drain, recovery after reboot, readiness, resource/device scheduling,
retention and operator diagnostics. Python SCM/owned-child foundation exists in
source but the active pilot uses a scheduled task. Current JSON recovery marks
unfinished jobs interrupted; it is not automatic resumption or checkpoint recovery.

CPU/RAM reservations are admission estimates, not hard OS limits. GPU/VRAM policy
and measured module budgets remain open. PACS cache-miss download must use the Unify
headless producer contract; do not introduce a competing downloader or retired gRPC.

Phase two adds client editing with versioned point/box/contour/mask changes and
server recomputation. Immediate navigation/window-level/preview stays local.
Phase one remains reliable remote analysis and result retrieval.
