# Secretary patient search readiness

A successful initial search acceptance is not terminal completion. Direct search
commands execute their initiating action once, then use only read_patients
probes through the existing asynchronous execution driver. The existing bounded
90-attempt / 0.5-second readiness policy applies. No command replay, authentication
retry, force-success mapping or GUI-thread blocking wait is introduced.

Pending Home searches receive a private canonical search_id bound to the exact
Home search task object and resolved local/server source. The adapter retains at
most 16 bindings. Unknown, evicted, replaced-task or changed-source bindings fail
closed. Ready initial results instead pin the actual list_id and source. A ready
probe must match the initiating binding before its actual count and executed date
bounds are used. Unbound legacy reads remain available; verified completion never
infers provenance from text or the current clock. Legacy workflow search/list
aliases now use the same readiness verification. Failed verification keeps the
existing VERIFY_FAILED semantics and never establishes successful completion.

The source-only TestControl action secretary_terminal_diagnostic observes a
bounded fixed-shape result retained under the original request UUID, even when
no terminal receipt exists. All three supplied UUIDs must be canonical and match
current session/runtime ownership. Closed runtimes, foreign sessions/owners,
wrong threads and missing results return NOT_FOUND. At most 256 entries are held;
no runtime or memory store is created by lookup. Output contains allowlisted
action/state/type enums and booleans only: no text, row data, count value, paths,
patient identities or credentials. This is not a public Agent Gateway operation
and adds no mobile wire DTO field. Existing aggregate terminal receipts remain
conservative.

Nine new guards failed before implementation: four direct asynchronous search
aliases, three legacy verifier aliases and the unknown-result diagnostic lookup and uncertain-search repair suppression.
Additional guards cover task/source identity, forged and evicted handles, missing
initial binding, different ready lists, bounded probe expiry, async yielding,
canonical identifiers, wrong thread/session/owner, retention bounds and malformed
result shapes. Older synthetic workflow fixtures now provide actual initiating
binding evidence; their original search/selection assertions remain intact.

Seven EchoMind source files have matching plugin payload mirrors. The native GUI
runtime has no matching plugin mirror. Exact frozen bytes and measured focused
checks are recorded in the private generated-files receipt. Source tests do not
establish Razi activation, real-provider success or affected-workflow GUI
acceptance. The coordinator owns immutable R17 reconciliation and activation;
R16 remains the running target until that controlled transition succeeds.
