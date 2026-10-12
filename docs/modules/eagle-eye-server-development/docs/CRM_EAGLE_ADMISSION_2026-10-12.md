# Hosted CRM admission

Ordinary CRM admission uses the existing Eagle human authentication (PACS or Reception), followed by the Eagle CRM grant. A second personal Reception login is not required. The outer handler remains responsible for fresh identity and grant verification on every request.

The host supplies a bounded opaque subject through a private header after overwriting caller input. The loopback worker first verifies its private internal token, then derives a per-request Eagle principal. A ContextVar isolates concurrent identities. The hosted tool guard allows only read-safety tools with read or plan permission actions; execute and all non-read safety remain denied. This preserves read-only report planning. Standalone Reception authentication and policy are unchanged.

Reception data access still authenticates through the configured Reception connection. No user is impersonated as a Reception account, no service credential is returned to clients, and no downstream authorization is bypassed. Unavailable or unauthorized configured data access remains an error.

The session route is optional compatibility support and mints a device/subject-bound token without forwarding personal Reception credentials. A supplied token must match its existing binding; absent tokens are acceptable under current Eagle admission. Bodies cannot set the worker principal. Private headers alone without the worker internal token fail closed.

Offline synthetic checks cover missing private authorization, missing subject, forged body identity, per-request reset, mismatched subject/center, write denial, and optional session admission. Live Android/iOS acceptance, immutable Razi staging/activation and full build qualification remain pending. No active clinical files or services were changed.
