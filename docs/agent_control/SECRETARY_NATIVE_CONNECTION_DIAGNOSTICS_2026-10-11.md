# Native Secretary connection diagnostics

The source-only TestControl `secretary_lifecycle` observation retains a sanitized
nested `pipe` object from the existing GUI connector. Fields are fixed `stage`,
fixed `category`, and boolean `acknowledged`. No token, owner, request text,
exception message, path or patient data is exposed. ACK becomes true only after
a validated admission response; it does not prove command completion.

Stages distinguish session check, connection, peer verification, hello send,
admission ACK, receive, dispatch and response send. Liveness distinguishes
`owner_changed` from `pipe_thread_stopped`. Failure details survive teardown in
memory. A later receive failure can originate in server authentication heartbeat
or transport; these diagnostics alone do not prove the server-side cause.

There is no reconnect, retry, authentication change, new runtime, cancellation
of dispatched work or service transition. Existing verification and grants remain
mandatory. Seven synthetic guards failed before implementation. Focused six-file
verification passed 136 tests with six existing SWIG warnings before the added
sanitization guard; final receipt records the updated count. Razi source staging,
activation and actual GUI diagnosis remain separate coordinator-owned gates.
