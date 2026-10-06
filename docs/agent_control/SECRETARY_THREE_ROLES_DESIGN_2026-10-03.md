# Secretary EchoMind: three-role contract and user experience

Status: implementation design; existing action execution is available, complete analytics and guided teaching are not shipped.

## Common entry

One voice/text entry point and one conversation. Eagle Eye classifies each request as execute, answer or teach before proposing tools. The client validates role plus typed tools and applies existing identity/permissions. An optional Auto / Act / Ask / Guide chooser allows explicit user intent; Auto is the default. Mixed requests become explicit ordered segments; ambiguity involving mutation needs clarification. Memory stores role and task scope so a data question cannot inherit permission to execute an earlier command.

## Execute

Reuse existing CommandBus, adapters, workflow handles and completion verification. User sees Understanding command, Applying action, Waiting for approval and Done / Failed. Accepted asynchronous work is Running, not Done; poll terminal operation status. Completion reply names the actual outcome rather than repeating raw tables. Show a compact task receipt and optional details.

## Answer from current data

Add read-only query/aggregation services with typed date interval, source/center, study/modality scope, report state and authenticated reporter identity. Suggested contracts: get_workload_summary and get_report_workload. These are proposals, not current capabilities. Use authoritative database/reception/PACS data with source and freshness receipts. Retrieve entire requested scope or aggregate at source; never count the first 25 visible rows as the whole day.

Define unique patients, studies and admissions separately. Define pending, draft, signed and delivered report states; missing status is Unknown, not automatically pending. "Reported by me" binds the logged-in user's authoritative identity and report author/signature fields, never names or assignment alone. Date filters distinguish study date, admission date and report completion date, using center timezone. If only local downloads are accessible, label the answer as local coverage. Do not fabricate unavailable counts.

Client/repository computes exact aggregates; Eagle Eye interprets the question and explains the returned values. Send minimized aggregates rather than raw patient lists when possible. Queries run on workers and preserve UI filters by default. UI shows Reading data then Answer ready; answer card contains scope/date, counts, unknown/unavailable metrics, source and retrieval time. Refresh and optional authorized Show matching studies are separate interactions.

## Teach

Use the versioned help catalog and live target registry described in SECRETARY_GUIDED_HELP_DESIGN_2026-10-03.md. Eagle Eye returns bounded topic/step proposals; local controller resolves controls for active page/domain. A red mouse-transparent pulsing ring follows the real widget/item. It never moves the operating-system cursor or clicks. Allow safe page navigation with explicit tutorial context; entering a password or applying/deleting settings stays with the human and existing confirmation policy.

UI shows Guiding, step N/M, explanation, Previous/Next/Exit and Waiting for your action. Observe real user events where reliable; otherwise require Next. Re-resolve on page resize/search/sort, and stop if context is stale. Reception connection tutorial uses verified actual settings controls and installation availability; do not invent labels/endpoints or collect credentials in chat.

## Role enforcement

Execution: existing permission and confirmation checks.
Answer: allowlisted read tools; no writes or UI filter changes as an implicit side effect.
Teach: allowlisted help/navigation/overlay tools; no clinical/storage mutations, even when instruction mentions Delete.

Each server proposal carries role, normalized request and tool/step intent. Role validation is local; model classification alone is not a security boundary. Error messages distinguish ambiguous question, unavailable data, unavailable control, blocked permission and execution failure.

## Delivery order

1. Common typed role envelope and status presentation; preserve legacy actions while migrating server and client contracts together.
2. Answer vertical slice: today's study/report workload with fixture-backed source definitions, authenticated reporter attribution, unknown coverage and full-scope totals.
3. Teach vertical slice: opening a patient, followed by reception connection and viewer/domain-specific rotation/annotation.
4. Integration: mixed-role conversations, New memory, stale handles, repeated voice requests and asynchronous action completion.

## Acceptance

Tests must fail on role confusion, incomplete-list counting, assignment-versus-author confusion, unknown state coercion, wrong date/source scope and stale UI targets. Use synthetic records, isolated DB and cleared connection pool. Mandatory source live GUI validates real controls, input boundaries, unchanged query filters, exact visible outcome and terminal receipts. Sync mirrored files, runtime packaging and server capability digest/catalog when implementing. This document changes no runtime or server deployment.

## Source implementation update

Act/Ask/Guide selector, strict server request enum, separate server prompts, non-action text responses and local execution isolation implemented. Ask currently receives minimized current-loaded-list count/modality aggregates with explicit incomplete scope; full daily workload/report-author queries remain unavailable. Guide currently provides grounded textual steps; live target overlays remain unimplemented. Server source is changed; active deployed service and live GUI acceptance must be verified separately.
