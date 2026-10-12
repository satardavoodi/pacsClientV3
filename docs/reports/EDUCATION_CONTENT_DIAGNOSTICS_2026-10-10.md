# Education content lifecycle diagnostics (2026-10-10)

Scope: OPT-61 and the shared-pipeline observability boundary. Instrumentation
only; no retry, cache repair, identity-guard relaxation or rendering replacement.
The owner authorized coordination with `fix 1`, which reviewed terminal coverage,
worker separation, counter semantics and privacy and reported no conflicting edits.

## Evidence and limits

Protected installed-laptop logs show a series inventory/reservation without a
corresponding completion record. A different resource completed earlier. Existing
logging cannot distinguish silent invalidation, visibility suspension, executor
delay or blocked image/completeness work. The previously displayed series count
can survive clearing and is not proof of admitted cards. Canonical local assets
were checked separately; this does not establish laptop cache parity.

The laptop runtime reports an ARM-related/emulated package profile. This is not
proof that emulation caused the Education delay. Previously there were no click,
import, construction or event-loop timing boundaries. Eager page construction,
synchronous database queries and cover/card creation are measured, not declared
the root cause. Patient identifiers and private log paths are intentionally absent.

## Records

New records use `[CONTENT-DIAG]` in the existing asynchronous application logger.
They are enabled at normal INFO level without a test-only feature flag. Random
owner aliases join Education selection and sidebar activity within one session;
random trace aliases distinguish operations. Numeric item generations and sidebar
tokens join selection clearing to subsequent scheduler generations. These aliases
are not derived from clinical identifiers. Clinical formatter context is explicitly
neutralized, including study, series, download and action context. No paths, names,
patient IDs, UIDs, content text, exception messages or traceback are included in
these new records. Existing unrelated logging is unchanged.

Sidebar lifecycle:

- `scheduled`, `plan_worker_started` (queue delay), `plan_prepared` (inventory).
- `reserved` distinguishes inventory and newly reserved rows.
- `first_card_worker_started`, `first_card_prepared` separately measure executor
  queue delay, image preparation and local completeness checks.
- `first_card_applied` distinguishes attempted application from admission of a
  live card into the layout; completion includes aggregate counts/max apply time.
- `visibility_wait` / `visibility_resume` expose suspension.
- At most three five-second watchdog samples expose the current waiting phase.
- Exactly one `completed`, `cancelled`, `invalidated` or `failed` terminal,
  including empty plans and cancellation before coroutine entry. Invalidation
  records equality/retirement flags without their clinical values. A done callback
  can emit a terminal without dereferencing a destroyed owner. Unreached stages
  remain absent rather than reporting fabricated zero durations.

Terminal records include the last explicitly allowlisted phase. Safe numeric error
classification is OS=1, value=2, runtime=3, memory=4, other=5; synchronous setup
errors re-raise after a terminal record. First application and terminal snapshots
capture owner/container visibility, updates-enabled state, thumbnail panel index
when available and one representative card's visibility. Admission alone is not
visibility, and neither establishes paint. Missing/deleted children are reported
as unavailable without masking the original cancellation/error. The watchdog uses
the Qt loop: its silence cannot distinguish a blocked GUI from an unexecuted
callback. Retain independent native/stall evidence for that distinction.

Workers receive detached primitive snapshots and diagnostics, not live Qt state.
Cancellation does not wait for worker I/O. Terminal diagnostics do not change
existing cancellation, visibility or rendering behavior.

Education opening:

- `requested`, `module_import_start/end`, `module_construct_start/end`.
- Separate Library, My Courses, Build Course, Case-of-Day import/construction and
  optional consultation construction spans.
- Aggregate query counts/durations, cover reads and course-card construction;
  no per-course record or course metadata. Cover reads are included in card time,
  and card/query time is included in page construction; do not sum nested spans.
- `tab_activated` identifies reuse versus new construction.
- A zero-delay callback marks event-loop readiness. This is not first-paint,
  clinical-image readiness or thumbnail-rail completion.

## Verification and follow-up

Four initial scheduler lifecycle guards failed before instrumentation because no
scheduled/terminal records existed. Expanded synthetic guards exercise actual
qasync scheduling, pre-entry cancellation, inactive/resume, preparation failure,
path invalidation after reservation, cancellation in a worker, native owner
destruction, empty plans, successful card admission and neutralized log context.
Additional guards cover synchronous setup failures and admitted-but-hidden cards.
Launcher guards execute the real launch method with synthetic page construction
and no database access, checking create/reuse/error and event-loop boundaries.

Live source acceptance remains pending: the documented local test-control socket
is unavailable. Installed ARM acceptance, a new diagnostic laptop session and
root-cause confirmation remain pending. No installed executable was launched,
service activated or release built. Owned files are staged in a separate immutable
Razi candidate with a protected hash/test receipt. Full Developer parity and build
handoff remain blocked by existing concurrent source differences and live gates.

Once the diagnostic source is accepted and packaged through the normal release
workflow, collect a fresh laptop session: first Education open, resource selection,
wait for the rail, switch away/back, then close normally. Compare import/page/query/
card spans and the terminal flags/worker milestones. Preserve raw logs privately;
share only sanitized aggregate findings with the shared-pipeline owner.
