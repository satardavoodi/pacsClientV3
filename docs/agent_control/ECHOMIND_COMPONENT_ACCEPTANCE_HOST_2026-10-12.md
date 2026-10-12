# EchoMind synthetic component-host preparation

Status: FROZEN SOURCE-ONLY, NOT ACTIVATED. The owner narrowed live testing to Secretary/CRM connection only. No TestControl integration was added, no current process was patched, and no restart is authorized by this receipt.

`tools/testing/echomind_acceptance_host.py` is an unintegrated developer prototype. It defines 22 fixed synthetic fixtures, an actual shared composer/history/ApiWorker surface, isolated History storage and a committed prewire UUID receipt, and the existing authenticated Client transport. It is not a production OneChatPage acceptance runner. No patient database, reception filing, provider keys, arbitrary payload or path control is included. No module executes a request on import.

The eight focused synthetic guards pass: fixture immutability/schema, committed prewire ordering, prewire receipt failure, mismatched response identity with no replay, reservation race/closed-owner fencing, and three source/env gate variants. All eight failed before the module existed. These are component preparation guards, not native/provider acceptance.

Pending independent review before any integration: inspect native worker retention through finished versus done signals, UI duplicate-send/close races, and transport source identity/actual per-grant response. The existing UnifiedComposer constructor performs legacy capture cleanup; the prototype refuses construction unless that cleanup is already complete or explicitly disabled for a reviewed test session. It does not change that setting. The prototype is not approved for live activation by the passing unit checks.

Mirrors: only tools/testing and tests changed for this prototype; no runtime module/mirror or server source was changed. Do not include this unintegrated developer tool in an installed payload. Preserve the current dirty worktree and coordinator synchronization policy.

Actual current Client connection acceptance is recorded separately in the private connection-convergence receipt: documented TestControl ping/discovery and existing read-only verify_eagle_eye_connection operation. A successful capability/authentication probe does not establish Secretary/CRM-specific grants, planning/provider execution or full native-page rendering.
