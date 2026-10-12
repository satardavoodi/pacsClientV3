# Education on-demand page construction (2026-10-10)

OPT-61. Owner scope: improve click-to-open Education itself, independently of
DICOM loading and the shared sidebar investigation. No startup prewarm is wanted.

## Confirmed structural problem

The previous shell synchronously constructed Library, My Courses, Build Course,
Case of the Day and optional Online Consultation before returning to its caller.
Hidden constructors query storage, build cards and initialize their own workflow.
This is verified source behavior, not a measured attribution of the ARM laptop's
full delay. Six synthetic shell guards failed before the change because all five
enabled pages were built immediately; a Settings refresh guard separately exposed
construction of three unvisited pages after import.

## Implemented behavior

- Shell construction creates only lightweight tab slots. First display schedules
  the currently selected page; there is no idle preload of the other pages.
- Selecting another tab constructs only that page. Case-of-Day and consultation
  page imports are inside their factories. Consultation uses the existing gate.
- Real pages replace slots at the same index. Public page properties still return
  the real widget, supporting Secretary/MCP `setCurrentWidget(page)`, course editing
  and consultation deep links. Explicit programmatic page access is demand.
- Pages, signals, selected controls and drafts are retained on revisit. Signals
  are wired once when a page is created. Newly created pages use the current theme.
- Superseded selections, hidden shells and natively deleted owners do not perform
  queued page construction. A failed selection offers Retry in the same tab.
- Transfer/import refreshes only already loaded pages, both from Education and
  Settings. Unvisited pages query fresh data on first access.
- Existing PHI-free opening diagnostics are preserved. On-demand construction has
  its own page trace and existing aggregate query/card timings. Event-loop readiness
  is not a claim of first paint.

Qt widget construction remains on the GUI thread. This slice removes unnecessary
hidden-page work; it does not move the selected page's existing database/cover work
to workers, eliminate cold Python imports or establish installed ARM latency.
Those boundaries remain separately measurable. No DICOM pipeline, provider route,
identity gate, service activation or release change is included.

## Evidence and acceptance limits

Twelve synthetic guards cover initial zero-page construction, selected-page-only
loading, state reuse, real-widget identity for Secretary, loaded-only refresh,
explicit retry, consultation deep link/gate, rapid selection, hidden/native-deleted
owners and the Settings import path. Database access is forbidden in these guards.

A protected five-sample offscreen comparison used the same synthetic five enabled
pages, each with an identical 8 ms constructor delay, with module imports already
warm. Median shell construction changed from 46.68 ms to 3.33 ms; the first-page
event-loop boundary changed from 49.92 ms to 16.43 ms. Before: five pages constructed;
after: zero before display and one after the event turn. These are synthetic
structural measurements, not laptop, real-database, cold-import or paint results.

Live source GUI acceptance remains pending: the documented control socket is
unavailable. Installed ARM acceptance is pending and the installed Client is
unchanged. Packaged mirror and scoped inactive Razi candidate hashes/tests are
recorded in protected receipts. Complete Developer reconciliation belongs to the
active Eagle Eye coordinator; a scoped candidate is not whole-source parity,
activation, clinical qualification or release readiness.
