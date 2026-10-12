# Current-request narrative language contract

Owner decision: 2026-10-10. This document records reviewed local source behavior,
not activation or completed local/Razi Developer parity.

## Shared behavior and wire

Resolve language from the original current user request, never history, tool JSON,
record names, screenshots or quoted documents. A positive explicit response or
translation target wins; otherwise use the dominant unquoted Persian/English
script. Mixed, empty or nonlinguistic text uses the selected preference (English
by default). Negated targets do not select the prohibited language. A negative
target alone falls through to script detection; it is not an inferred translation.

`language_preference` is an optional `fa`/`en` fallback, not authority. Secretary
keeps its required legacy `language` (`fa`/`en`/`auto`) for compatibility. With no
new preference, a legacy `fa`/`en` supplies fallback; `auto` falls back to English.
Current text still wins. All schema keys, action names, enums, executable argument
literals, handles, numbers and structured result data remain unchanged. Models,
credentials, routing, identity checks, permission and confirmation do not change.

The additive Eagle capability is:

```json
{"request_language":{"protocol":1,"preference_field":"language_preference","supported_preferences":["fa","en"],"workflows":["secretary","crm"]}}
```

Only configured workflows appear. CRM source readiness was authorized by its owner
after the frozen-helper run; the worker timeout below is still an acceptance gap.
The Windows planner sends the additive field only when this protocol, field,
supported language and `secretary` workflow are advertised. Older strict servers
receive the legacy shape. PACS gateway `response_language` negotiation is separate
from Eagle `request_language`; mobile/server capabilities must not be interchanged.

## Frozen helper and owned components

`modules/ai_imaging/eagle_eye_remote/response_language.py` SHA-256:
`fe752fa333eda568045e9174f3ea52b9b5bf7bc999fe15393c64b075c7248b85`.

Stable API: `resolve_reply_language(current_text, preference='en')`,
`request_language(current_text, preference='en')` context manager,
`current_reply_language()`, and `response_language_instruction(language=None)`.
ContextVar tokens restore on exceptions and nested/overlapping requests. The caller
must pass original current text only. This is a bounded two-language heuristic,
not a general language classifier or authorization mechanism.

Secretary `service.py` owns strict request validation, whole-request scope,
completion policy and deterministic narrative/error translations. Its snapshot
manifest tracks the changed service. Windows `remote_planner.py` owns negotiated
transport. `server.py` adds the capability without removing `lumbar_vision`.
CRM integration and native PACS final messages remain owned by their respective
threads; this work does not duplicate their source edits.

Android affected components: Agent settings/preferences, Office and Eagle request
transport, Secretary transport and native desktop-bridge final/confirmation/error
messages. iOS affected components: Agent settings/preferences, Office/PACS and
Secretary request transport on `/Users/macvps-11/dev/aipacs-ios`. Native platform
implementations stay separate; Windows iOS copies are not authoritative.

## Verification and outstanding gates

Helper fail-before: two Persian suffix-prohibition cases failed, 19 passed. After
the minimal suffix filter, 22 passed including English do-not/never, quoted/tool
exclusion, explicit targets, mixed fallback, overlapping scopes and nested reset.
Secretary fail-before: optional preference rejected and three completion-policy
cases failed (four failures); the exception check initially passed only because
schema rejection preceded processing, then was strengthened to assert localized
502 and cleanup after actual processing failure.

Local command:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:debugging tests/code/echomind/test_request_language.py tests/code/echomind/test_secretary_request_language.py tests/code/echomind/test_secretary_server.py tests/code/echomind/test_secretary_remote_planner.py tests/code/echomind/test_secretary_server_runtime_contract.py -q
```

Result: 110 passed, exit 0. Synthetic provider stubs only. This includes strict
legacy/new validation, current text over preference, per-request policy and cleanup,
localized fixed clarification, old-server omission, per-workflow capability and
existing auth/license/proposal guards. No live provider calls were made.

CRM owner receipt: `generated-files/crm/language-20261010.json`; 113 passed and one
known isolated worker test deselected after helper freeze. Worker startup/read
timeouts remain unresolved and were not hidden by increasing timeouts. Root also
independently verified 50 helper/CRM language cases. Neither result proves worker
acceptance, generated response quality or native UI behavior.

Android owner reports 322 JVM tests/build, native selector visible on emulator,
11 bridge unit tests, 24 integration checks and seven relay checks. iOS selection
and compatible transport UI tests were reported successful on iPhone/iPad; final
scoped receipt and actual generated-server acceptance remain separate. These are
owner-reported platform results, not tests executed by this Secretary owner.

Pending: full immutable local/Razi source inventory reconciliation and parity,
safe CRM drain/service transition, native Android and iOS end-to-end server/provider
acceptance, and affected Windows live GUI acceptance. Do not overwrite executing
source, activate, release, publish or hand off a qualified build from this receipt.
The last reported active Razi source remains `20261010-ordinary-human-r2`; this
language change is not claimed active there. The Eagle owner coordinates staging.
