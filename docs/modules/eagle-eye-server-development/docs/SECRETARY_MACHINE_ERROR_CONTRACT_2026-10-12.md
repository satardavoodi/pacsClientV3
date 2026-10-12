# Secretary fixed error descriptors

Secretary planning errors preserve the existing localized `error` display and optionally add a fixed `error_code`. Only values in `secretary_errors.py::CODES` are accepted. The code is derived from a fixed server failure message before localization; arbitrary provider text and unrecognized values never become codes. Client checks the allowlist, then falls back to recognized legacy English messages. Authentication, permissions, routing, request limits and provider selection are unchanged.

Distinct categories cover request fields, session files, invalid JSON, route, conversation metadata, plan, clarification, workflow, answer and planning failure. The final category preserves the existing broad planning-failure classification and does not prove an upstream network failure. A valid client preflight does not prove a provider response or action plan was valid. A generic HTTP 422 alone does not identify the failure stage.

Future private failed history retains only the fixed code alongside the existing accounting snapshot. Historical failures contain accounting without cause. Mobile and planner request UUIDs are distinct; no retrospective one-to-one correlation is claimed. No patient payloads, prompts, generated plans or private configuration are exported by this diagnostic change.

Offline regression tests reproduce the old language/code loss. Live acceptance, immutable remote synchronization and mobile test results remain separate gates; this source slice has not been activated.

The pure error contract is included in the explicit stdlib Slicer client payload. Approved categories also pass the orchestrator patient-list receipt whitelist; ordinary unknown codes still fail closed.
