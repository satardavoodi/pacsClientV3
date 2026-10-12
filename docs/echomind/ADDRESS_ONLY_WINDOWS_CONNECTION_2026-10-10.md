# Ordinary Windows Eagle Eye connection - 2026-10-10

Owner contract: ordinary EchoMind, imaging, Secretary and CRM calls need the
server HTTP/HTTPS address and existing human PACS/Reception sign-in. They do
not require device pairing. Agent PACS pairing is separate and unchanged.

Client accepts address-only configuration. Capabilities and auth-session calls
do not require a human header; protected calls retain X-Eagle-User-Session,
profile/generation validation and bounded response protections. Existing login
capture and authority resolution remain unchanged; no extra provider/login UI.
Optional valid legacy token and HTTPS client certificate provisioning still
works. Missing legacy device files do not prevent ordinary address-only use.
The settings UI hides legacy device fields while preserving their saved values.
Optional HTTPS CA trust remains available; absent CA files use system trust,
never trust-all. Invalid certificates still fail normal TLS verification.
HTTP is allowed by explicit owner decision. No automatic downgrade is added.
Logout omits the device Authorization header when no legacy device token exists.

Verification: four new guards failed before the change. Fifty focused guards
pass afterward, covering address-only HTTP/HTTPS, TLS trust, missing old pairing
files, human-session header, settings, automatic login and scoped session safety.
The prior HTTP-forbidden settings fixture now uses unsupported FTP instead.
No backend/auth-service edits, live authentication, provider calls, active config
changes or deployment occurred. Coordinator owns immutable reconciliation and
activation; native GUI acceptance remains pending.

Subsequent integration run after adding two admission/legacy guards: 51 passed,
1 failed in the existing job-monitor fixture that creates device-owned jobs
and expects them in the human-session listing. Backend ownership migration is
concurrent; coordinator must reconcile that fixture without weakening isolation.
The initial 50-pass run is historical, not the current whole-suite verdict.
