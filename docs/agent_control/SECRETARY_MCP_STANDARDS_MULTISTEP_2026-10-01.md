# Secretary MCP standards and sequential result binding

Source implementation receipt, 2026-10-01. Not deployed or live accepted.

## Protocol baseline

The Gateway negotiates MCP 2025-06-18. Official references:
- https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle

Tools now advertise an outputSchema and return structuredContent alongside serialized JSON text for compatibility. Unknown tools return JSON-RPC invalid-params errors before dispatch; business execution failures return isError with structured failure data. Read-only/destructive annotations are hints; existing permission and confirmation checks remain authoritative. This slice is not a complete protocol certification. Experimental tasks, cancellation, notifications and progress extensions are not newly implemented.

Gateway calls support the existing entities envelope. Put a status action's operation_id inside entities; the root operation_id is the transport retry identity.

## Sequential contract

Runtime capability snapshots negotiate workflow_binding_version 1, included in their digest. The matching server planner may use $draft_id, $recording_id and $operation_id after their registered producer. Without negotiation, or with invented literal dependent handles, the server retains the safe prefix only. Local execution substitutes actual result fields; missing references fail before dispatch and stale captured handles are cleared.

The workflow engine executes serially. Default verification polls bounded read actions for terminal resource/theme/support results, delivered Comment Sync, prepared/saved voice and successful PACS voice upload. Failed, unknown or timed-out outcomes stop later steps. Async polling yields to the event loop. Confirmation remains enforced; patient adapters recheck identity. PACS voice upload does not assert reception delivery. Recording is not automatically stopped without a separate instruction.

This supersedes the earlier alignment receipt's blanket handle-prefix restriction for negotiated clients only. Deploy matching server and client sources together; legacy snapshot-free requests retain compatibility. Multi-step workflows are enabled by default, consistent with existing runtime settings.

## Verification and limits

Fail-before guards: three structured MCP results tests, three sequential receipt tests, and one negotiated server binding test. Final affected selection: 164 passed, exit 0, with three existing TLS datetime deprecation warnings. Synthetic inputs only. Owned mirrors synchronized without unrelated workstream changes; server manifest refreshed.

Source GUI acceptance remains pending: the existing local control client cannot connect to AIPACS_TEST_Dr_Alizadeh (invalid local socket name). No app restart, login, production Gateway enablement, patient send, server deployment or release was performed. Education case save, authoritative reception voice delivery and other previously documented gaps remain open.
