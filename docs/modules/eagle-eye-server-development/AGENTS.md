# Eagle Eye Server local development agreement

Read README.md and docs/CURRENT_STATE.md before changing anything. All project,
system, source, comments, logs and documentation additions are written in English.

The user authorized source development under `D:\Eagle Eye Server`. This does not
make unfinished models clinically qualified. Preserve the live PACS, CRM and legacy
Breast processes. Existing coordination rules and the user's current instructions
take precedence over this local guide.

- Inspect current state and source differences before editing. Do not overwrite
  another developer's uncommitted work or an executing source revision.
- Keep credentials, patient identifiers, DICOM, reports and private logs out of Git,
  documentation, screenshots and external AI services. Use synthetic regression data.
- Use the dedicated environment; never install packages into shared system Python.
- Do not replace System32 DLLs or globally upgrade runtimes to fix this pilot.
- Do not kill processes by name. The scheduled task alone did not stop its listener;
  follow the ownership and empty-queue verification in docs/OPERATIONS.md.
- A capabilities response is transport evidence, not model readiness. Empty PACS
  allowed_roots is deliberate until authoritative source mapping is validated.
- Slicer/build changes belong to the build workstream. Shared PACS acquisition,
  identity and cache coordination belong to Unify. Eagle Eye consumes those contracts.
  Preserve separate Fast, Advanced and VTK viewer execution domains.
- Runtime fixes require a fail-before regression guard and relevant acceptance.
  Run guards on the canonical repository when not present in this subset. Never let
  tests open the live clinical database. Record automated and live gates separately.
- Use a new versioned candidate for source, environment or asset updates. Record
  hashes, test receipts, limitations and rollback before activation.
- Update CURRENT_STATE, BACKLOG and HISTORY after a change. Do not silently edit
  deployment.json to claim a result that was not observed.

Two isolated development hosts exist: the original manual task on 8042 and the
automatic SCM service on 8043. Read docs/SERVICE_AUTH.md before lifecycle work.
Reboot, real account, full model, resource and installer qualification remain required.
