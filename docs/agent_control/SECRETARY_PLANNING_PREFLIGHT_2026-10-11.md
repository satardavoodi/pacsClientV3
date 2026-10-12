# Secretary planning preflight and private diagnostics

The existing Client.open serializer uses json.dumps(body, allow_nan=False).encode()
with ASCII escapes and standard separators. The server's logical size check uses
the same representation. The former Secretary preflight counted ensure_ascii=False
UTF-8 bytes, undercounting the actual transmitted request for non-ASCII context.
The correction measures the existing wire representation. Client/server transport,
HTTP ingress, prompts, models, credentials and limits are unchanged: 128 KiB for
ordinary planning, 512 KiB with UI context, 12 MiB with session sources. The general
HTTP planning ingress remains 12 MiB; it does not replace logical request limits.

A pure worker preflight reuses the server Request schema and existing UI snapshot/
context binding checks, then checks exact wire size before Client construction and
again immediately before Client.open after capability-negotiated optional fields.
It performs no network, Qt access, memory mutation or retry. The body is not modified.
Invalid requests return fixed SERVER_REQUEST_INVALID, SERVER_REQUEST_TOO_LARGE or
UI_CONTEXT_MISMATCH codes. Existing fixed server planning/HTTP codes survive the
Act unparsed-result path instead of being collapsed into a generic unavailable code.

Only a sanitized descriptor is retained under the original native request through
the existing source-only terminal diagnostic. It contains allowlisted stage, field
root and error type, a boolean valid flag and bounded wire/limit byte counts. It
contains no field values, validation messages, request text, patient rows, filenames,
credentials or Qt objects. Unknown names/types are reduced to unknown; counts clamp
at 12 MiB plus one. Existing owner/session/runtime/UUID/thread/closed fences remain.
Successful local preflight on a subsequent HTTP failure means local validation
passed, not that a provider ran or a command completed. No descriptor is added to
public mobile DTOs or outgoing planning bodies.

Three guards failed before implementation: oversized Unicode context reached the
fake Client.open; safe pure preflight was absent; specific codes were collapsed.
Further synthetic checks cover unchanged valid ASCII/Unicode wire, exact ordinary
boundary, UI binding and image/source limits, privacy clamps, valid-preflight HTTP
rejection, original UUID fences and public DTO exclusion. A pre-existing HTTP-error
fixture needed a synthetic ordinary-user session stub so it reaches its fake opener;
production authentication is unchanged. Measured focused checks and frozen byte
copies are in the generated-files receipt. The actual earlier R17 HTTP 422 cause
remains unproven. This slice fixes independently demonstrated undercounting and
provides evidence for a future controlled test; it does not claim actual acceptance.

Only remote_planner, orchestrator and patient_list_receipt runtime source and their
three EchoMind payload mirrors change. No active Razi source or service transition
is performed here. The coordinator owns immutable candidate reconciliation and
separate real-function / GUI acceptance.
