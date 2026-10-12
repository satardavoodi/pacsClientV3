# Eagle AI Brain authority - 2026-10-09

Company AI uses one shared private server identity. Server 1 is the existing
GapGPT connection; models/prompts remain unchanged. AI > Connection is its
operator configuration surface. Public clients retain PACS/Reception identity
and independent per-user module grants; a Brain code never replaces those gates.

Enforced at the hosted HTTP boundary:
- GapGPT calls without a private request context are rejected.
- Disabled/unknown Brain selection or an invalid center registry code rejects a
  company call before network activity or usage admission.
- The shared private provider identity replaces caller Authorization headers.
- Unregistered company destinations are rejected. Registered native Assistant
  and company-report services remain distinct, but require the shared authority.
- Per-request company center-code overrides are rejected.
- Hosted CRM diagnostics use the same Brain provider; retired unreachable direct
  senders were removed from the vendored client. Missing hosted context fails.
- Existing user-owned personal API mode and speech routing remain separate;
  this change does not introduce a company fallback on clients.

The operator Test Server 1 connection button uses the same private authority,
server-selected existing probe model and usage ledger on a worker. It sends a
synthetic Ping only when explicitly pressed. It returns connection status, never
raw provider output or credentials. No real provider request was performed in
this development session.

Local verification: 93 focused synthetic guards. Remote final receipt belongs to
revisions/20261009-brain-authority-r2/source, separately from the active SCM
revision. Source scope parity is not complete repository/model/native parity.

Active Razi service inspection: education-presenter source remains on TLS 8002;
its configuration has no user_access. Observed retained jobs/text histories had
no pending rows, but this is not a locked admission/drain guarantee. No service
was stopped or reconfigured. The GUI control ping failed because the source
Test Control endpoint was absent. No test flag, login or clinical process was
changed by that probe. Full Developer parity and native/provider acceptance
remain required before switching this shared clinical service.
