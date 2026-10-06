# Secretary ordered-list identity across sorting (2026-10-06)

The latest bounded local session projection showed a row-1 open proposal with a list receipt, local confirmation, then STALE_LIST. No patient identifiers or request contents are retained in this report.

Previously Home opening required the entire ordered patient/study identity hash to match after confirmation. A legitimate sort therefore invalidated the proposal. The shared Home CommandBus adapter now keeps at most 16 client-owned read receipts, each holding only the source and offered patient/study identity pairs. Original one-based row indices resolve against their captured receipt, then require exactly one matching identity in the current rows. Current voice requirements are rechecked. Names and mutable status fields never define identity.

Sorting, repeated sorting, adding unrelated results or removing other rows can preserve the target. Missing/ambiguous target, source changes, changed required voice evidence and unknown changed-list receipts remain rejected. Snapshot-free callers retain strict current-order validation. Selection/media workflows retain their own exact-list contract; this change applies only to opening a single bound study.

Four regression cases failed before the source change. Automated verification includes the actual Secretary pending-confirmation round trip through the shared CommandBus with synthetic Home rows. Native source acceptance is pending: the documented Test Control ping was unavailable. No clinical patient was opened, no source app restarted and no data deleted. A successful command receipt is not proof of rendered native viewer acceptance.

Focused verification: 113 passed, zero failures, direct pytest exit 0; six existing SWIG warnings. Owned adapter mirror equality verified. Global mirror verification retains the unrelated pre-existing `viewer_chat/ai_chat_pages.py` drift; that file was not changed or synchronized.
