# One Windows report Send action

Owner instruction supersedes separate Turbo action/selector behavior. The report
composer exposes one labeled, accessible Send button. Turbo button construction,
layout, enable/visibility wiring and separate report/correction handlers are
removed. The client no longer imports the Turbo route constant or accepts a
`workflow=turbo` report choice / `turbo=True` correction choice.

Company Send posts one normal `report` request to the authenticated shared Eagle
Eye Server. The server alone selects Turbo/ChatGPT first and its company fallback.
There is no client provider retry, second report request, local Turbo prompt or
forced-company correction. Personal API mode continues through the existing own
key/endpoint and explicit user prompt boundary; it cannot fall back to company.

Attachments remain attached on failure. A server 502 on an attachment report
shows that processing failed, sources remain in the composer and Send can be
retried; no text-only fallback silently discards source material. Authentication
and module-grant errors retain their specific messages.

Three new guards failed before runtime changes. The final selected report UI,
transport, shared-route, EchoMind core and reference suite passed 92 tests, exit 0.
The GUI component guard is offscreen QWidget verification, not native acceptance.
Pure server attachment fallback prompt assertions remain server-owner scope: the
old report_attachments guard expected a Turbo prompt only for the explicit Turbo
route, while the new server applies it to normal reports too. Its earlier failure
was reported separately rather than described as a client pass.

Mirrors and exact source hashes are recorded in the private final receipt. No
active Razi source, service, login, installer or release was changed. Final union
parity and affected-workflow live GUI acceptance remain separate qualification
gates. Android is separately owned; iOS requires authoritative Mac source access.

The company normal-report transport has a bounded 480-second call/read timeout,
covering the server's two sequential 180-second upstream read budgets plus connect
allowances. Chat/correction retain 360 seconds. Personal API timeout settings are
unchanged. One new report-budget guard failed at 360 before the fix; the final
92-test run includes other-workflow budgets and the existing no-timeout-replay guard.
