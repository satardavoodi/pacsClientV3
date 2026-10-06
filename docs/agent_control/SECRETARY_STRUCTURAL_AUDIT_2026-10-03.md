# Secretary structural audit and remaining integration gates

## Verified source boundaries

| Mode | Current implementation | Remaining requirement |
| --- | --- | --- |
| Act | Eagle Eye planning, validated typed CommandBus actions, capability digest and confirmation contracts | Live acceptance of task-specific completion |
| Ask | Dedicated server prompt; supplied loaded-list aggregates, scoped answer | Authoritative read tools for daily/report/author metrics; answer is not a database query |
| Guide | Dedicated server prompt and verified module documents | Registered tutorial targets and client overlay/navigation tools; current implementation is textual only |
| Help Ticket | Local reviewed issue form; shared open_support_issue/support_issue_status; authenticated website JSON delivery | Dedicated LLM classification and shared typed package lifecycle; full ZIP/audio upload contract |

## Packaging and transport evidence

Submission worker prepares a dated local ZIP before any network call. The archive now uses a temporary ZIP,
CRC verification and atomic publication, plus SHA-256/byte metadata. A local packaging error blocks network
submission. Frozen issue payload and identifier persist in the DPAPI retry outbox; validated matching website
receipts clear the pending outbox. Local package and receipt remain. Receipt-write failure cannot convert
acknowledged delivery into a resend. Synthetic tests cover timeout/retry, changed pairing, receipt mismatch,
local review, worker ownership, packaging failure, archive hash and audio retention.

The existing Laravel PacsIssueController accepts JSON context/diagnostics and a bounded log_archive only.
The local ticket ZIP and audio are NOT uploaded. Do not advertise complete-package upload until a versioned,
authenticated website attachment contract, storage encryption, ownership/download checks, content hashes,
size limits, idempotent retry and retention have been implemented and tested on both sides.
No real ticket or patient information was sent during this audit.

## Prompt changes in source

Ask/Guide receive client-local time and runtime capabilities as quoted evidence. Answers reject extra
executable fields. Prompts separate task execution, scoped data answers, verified instructions and support
submission; opening a form or finding a local ZIP cannot be reported as successful delivery.
These source prompt changes are NOT active Eagle Eye deployment. The active service remains unchanged.

## Acceptance still required

- A Help Ticket server prompt with strict category/description proposal and explicit missing-detail questions.
- Shared typed prepare/status/submit package actions with actual opaque handles and local consent.
- The website full-package contract and private attachment review/download flow.
- Guide MCP tutorial catalog/target resolver/overlay and read-only Ask data providers.
- Synthetic cross-project transport tests plus human-authorized native GUI and staging acceptance.

This report is a gap audit, not proof that all requested workflows are complete.


## Source implementation receipt (2026-10-03, follow-up)

Help Ticket now uses a dedicated server prompt and strict category/description draft contract.
The client prepares the existing reviewed form through shared prepare_help_ticket when its Home bus is available;
submit_help_ticket requires the local consent checkbox and normal permission gates, while help_ticket_status
returns actual asynchronous form state. Upload destination/files remain client-owned.
Full ticket ZIP transport uses support-package-v3 and a bounded 8 MiB package (16 MiB request/outbox limit),
CRC-checked atomic local ZIP, SHA-256/bytes, same retry identifier and frozen payload.
Laravel validates stored/deflated ZIP members without extraction, stores the package using encrypted casts,
provides an audited panel-gated download and purges it with the existing 90-day diagnostic retention.
The append-only migration must run with the website release. No migration ran against production.

Shared get_loaded_study_summary supplies loaded-study modality/report-status aggregates with explicit scope
and no patient identities. It does not claim all daily admissions or report-author metrics; those require an
authoritative provider. Guide uses get_tutorial_catalog/show_tutorial with three actual Home targets
(open_patient, search_patients, report_issue), a transient mouse-transparent red pulse, and visibility verification.
The server cannot invent another target. Other documented topics can receive textual guidance; unverified
viewer/reception targets are not advertised as interactive tutorials.

Automated checks: 69 Python tests passed; 13 website tests passed (87 assertions), including full-package
submission/retry, tampered hash rejection, encryption, private download and retention purge.
Source and packaged mirrors are synchronized for the changed EchoMind files. Runtime activation of the
matching Eagle Eye/source client and website revision remains separate from source implementation.
Native GUI and production transport acceptance are pending; no real issue was submitted during tests.

Mirror verification: changed EchoMind files match. One unrelated existing `viewer_chat/ai_chat_pages.py` mismatch remains; full-tree parity is not claimed. Local Test Control ping still reports QLocalSocket Invalid name. Production/staging activation and native acceptance are not automated in this source-only implementation turn.

## Structured clarification choices

Server unknown proposals may include bounded clarification question/options (one to three unique display-only ids/labels). Client validates the same shape, preserves the actual question and shows choices, custom text and Cancel. Selection replans original request plus question/answer on the existing worker with the same session/mode; it is never action confirmation. Missing choices retain plain text clarification. Cancel sends nothing. Server assets and contract changes are source-only pending deployment and actual-model acceptance. Native GUI acceptance must be reported separately.

Clarification activation update: Razi AIPacsEagleEye now uses 20261003-secretary-clarification on existing paired TLS port 8002. Four modes, settings ownership and a real synthetic choice proposal passed; no clinical commands executed. Client text-only fallback and answer-needed status passed offscreen tests. Fresh source GUI voice acceptance remains pending; see deploy-record-secretary-clarification-2026-10-03.md.
