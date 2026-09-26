---
name: ai-pacs-bug-fix
description: Diagnose and fix AI-PACS workstation bugs, including numbered fix sessions, with root-cause evidence, regression guards, source GUI verification, and Standard Client / Eagle Eye Server build inclusion tracking. Use for corrective maintenance, crashes, freezes, and regressions; not unrelated feature design or the public website.
---

# AI-PACS Bug Fix

Turn each reported symptom into an evidence-backed, minimally invasive, regression-guarded fix. Optimize for clinical correctness, stability, architectural fit, reversibility, and maintainability rather than for the fewest changed lines or the fastest plausible patch.

## Scope and authority

- Match the user's requested scope. A request to diagnose authorizes investigation and a diagnosis, not a code change. A request to fix authorizes the complete guarded-fix workflow below.
- Treat multiple reported defects as a triaged queue. Separate unrelated root causes and deliver them in small reviewable slices; do not combine convenient refactors with a fix.
- Ask a question only when a missing fact cannot be discovered safely and a reasonable assumption could materially change the result. The user may report symptoms informally; derive the structured record from the conversation and evidence.
- Keep all repository and system changes in English, even when the conversation is in Persian.
- Never expand a maintenance task into deployment, credential rotation, infrastructure work, or a release without explicit authorization and the applicable safety workflow.

## Fix state model

### Numbered fixes and continuity

- Preserve the user's fix number and original scope. A chat called `fix 1` is a session title, not proof that every defect in it is bug #1. Qualify repeated numbers by session/date; never silently renumber historical reports. Split independent causes as A/B under the original report when necessary.
- Before revisiting a recurring defect, find its prior conversation, existing incident record, regression-catalog row and guard. Read the actual diagnosis and final evidence, including pending gates; a title or an earlier claim of success is not proof that the current bug was fixed.
- Maintain a compact English record in the existing owning incident document and link it from the regression catalog. Record: session/date and user number, symptom and expected result, owner/boundary, reproducer, root cause, changed files, fail-before/pass-after evidence, adjacent checks, source GUI result, edition/backend applicability, build-input checks, and pending artifact acceptance. Reuse existing `OPT-*` and owner records; do not create a competing backlog.
- Read [references/maintenance-evidence.md](references/maintenance-evidence.md) for recurring thumbnail/lifecycle/geometry defects and for the next-build handoff. It curates earlier fixes without importing patient data or treating old instructions as new authorization.

Use precise completion language:

1. **Reported**: symptom recorded; reproduction and cause are unknown.
2. **Reproduced**: the failure is demonstrated by a deterministic guard, controlled scenario, or decisive trace.
3. **Diagnosed**: the root cause and affected boundary are supported by evidence, with competing hypotheses falsified.
4. **Guarded**: a regression guard fails on the defective behavior before the implementation change.
5. **Fixed and verified**: the guard and proportional automated suites pass with direct process exit code 0.
6. **Live-verified**: the source build reproduces the original workflow and the expected result is observed without a new regression.
7. **Build-input verified**: applicable edition/backend source mappings, configuration, mirrors and packaging guards pass. This is evidence for the next build, not proof of an existing installer.
8. **Artifact-verified**: a separately authorized canonical build has a candidate/source receipt, applicable artifact inventory/hash evidence, and documented acceptance of the exact scenario under the current build runbook. Record each edition/backend separately; one passed artifact cannot close the others.

Do not collapse these states. In particular, automated verification is not live clinical validation, and live validation is not release readiness.

## Phase 1: Establish the evidence boundary

Before editing:

1. Read the active `AGENTS.md`, the relevant parts of `CLAUDE.md`, `docs/for-future-agents/README.md`, `docs/INDEX_BY_SUBSYSTEM.md`, `tests/INDEX_BY_GUARD.md`, the pre-development system map, and the readiness report.
2. Route to the subsystem-specific design, pipeline, incident report, and existing guards named by the indexes. Read the implementation and its callers, consumers, tests, configuration, teardown paths, and packaged mirror mapping.
3. For optimization, stability, reliability, responsiveness, freeze, or performance work, locate the existing `OPT-*` item in `docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md`. Extend that item; create a new ID there only when the concern is genuinely new.
4. Inspect `git status` and the relevant diffs. Preserve every unrelated user change. Never reset, stash, revert, broadly format, or regenerate unrelated dirty files. If the target lines overlap uncertain prior work and cannot be preserved safely, stop and explain the exact overlap.
5. Record the observed behavior, expected behavior, environment, frequency, smallest known reproduction, severity, blast radius, and available evidence. Redact patient identifiers, DICOM content, credentials, prompts, reports, and sensitive paths from conversation output and durable artifacts.
6. Establish the baseline that is trustworthy for this subsystem. The repository-wide fast lane and `run_test.ps1` are currently not proof of success; use focused direct pytest invocations and note known unrelated failures without hiding them.

For a crash or intermittent failure, prefer the narrowest decisive evidence: exception and traceback, paired before/after breadcrumbs, lifecycle counts, thread ownership, identity transitions, or a deterministic behavioral probe. Silence from a GUI-thread timer is not proof that a native-code hang did not occur.

## Phase 2: Reproduce before proposing a fix

- Reproduce the defect with the smallest safe surface. Prefer a pure or headless behavioral test over a source-text pin; use AST/source guards only when the invariant is structural and cannot be exercised behaviorally.
- Write the guard from the requirement, not from the intended implementation. It must fail for the defect for the right reason and pass only when the externally meaningful invariant is restored.
- Run the new guard before changing production code and preserve its failing output and exit status as the pre-fix proof.
- Do not use the live clinical database. Database tests must patch `PacsClient.utils.data_paths.DATABASE_FILE`, clear the connection pool, and prove the live database was not opened.
- Do not place patient data, images, real prompts/reports, secrets, or machine-specific runtime state in tests or fixtures. Use deterministic synthetic or irreversibly anonymized inputs.
- Never use `git reset`, `git checkout`, or a broad stash to manufacture a pre-fix state. When the failure must be proven against an earlier revision, use a verified, isolated temporary copy or a narrowly validated base-ref technique that cannot overwrite the worktree. If that proof is not safe, report the evidence gap rather than pretending it ran.

If the symptom cannot be reproduced, add bounded diagnostic observability or produce a focused reproduction plan. Do not change product behavior merely because one hypothesis is plausible.

## Phase 3: Diagnose the root cause

Trace the failing workflow end to end and explicitly identify:

- the authoritative patient, study, series, frame, request, or session identity;
- the owner of mutable state and the source of truth for completion;
- thread, process, timer, signal, callback, cancellation, and teardown ownership;
- network protocol, timeout, retry, authentication, and error-classification boundaries;
- database, filesystem, cache, configuration, and package-payload boundaries;
- Fast Viewer, Advanced Viewer, and VTK-module execution-domain boundaries;
- source versus packaged-mirror behavior and feature-flag or kill-switch defaults;
- security, privacy, clinical-correctness, performance, and compatibility risks.

Maintain competing hypotheses until evidence discriminates among them. For each serious hypothesis, name what observation would falsify it and obtain that observation when practical. Distinguish the trigger, the vulnerable condition, the root cause, and the visible symptom. Do not repair a downstream symptom while leaving the authoritative state wrong.

For performance work, measure the same workload before and after. Separate cold from warm behavior, handler time from scheduling delay, GUI-thread work from worker work, and algorithmic cost from I/O or antivirus first-touch cost. Do not optimize from sampled stacks alone.

## Phase 4: Select the implementation seam

Compare viable approaches against:

- root-cause correctness and preservation of existing behavior;
- architecture and execution-domain separation;
- clinical and patient-isolation safety;
- concurrency, reentrancy, cancellation, and teardown safety;
- security and privacy;
- latency, memory, I/O, and boundedness;
- backward compatibility, packaging parity, and rollout risk;
- reversibility, observability, testability, and maintenance cost.

Choose the smallest safe seam, not automatically the smallest diff. Prefer an existing service, repository, coordinator, or immutable read-only trunk over new logic in oversized UI controllers. Avoid new dependencies unless the repository cannot solve the problem safely without one. Use a feature flag or kill switch when a behavior change has meaningful live risk; do not add flag complexity to a trivial, fully guarded correction.

Never blur the Fast Viewer, Advanced Viewer, or VTK-module domains. Never move blocking filesystem, network, AI, decode, or VTK construction work onto the Qt GUI thread. Never reconnect retired gRPC download paths.

Follow section 0.2 of `docs/plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md` for workstream handoff. Shared identity/catalog/download coordination belongs to Unify; decoder/filter/render/private-cache work belongs to the viewer owner. A small-fix request does not authorize a parallel Unify slice or another workstream's in-progress payload. Preserve working clinical behavior such as overlays, measurements, reference lines and synchronization; disabling it is not a fix.

## Phase 5: Implement the guarded fix

1. Keep the failing guard in place.
2. Apply the minimal production change that corrects the authoritative cause.
3. Preserve public contracts, error semantics, cancellation, cleanup, and observability. Do not swallow errors, hardcode secrets, add placeholders, or leave untracked `TODO`/`FIXME` debt.
4. If a mirrored runtime source changes, inspect the current CLI and run `tools/dev/sync_plugin_mirrors.py --dry-run` before mutation. The synchronizer can sweep unrelated dirty payloads: do not run a global write when its proposed changes cross workstream ownership. Use the documented scoped route if available; otherwise keep mirror completion pending and resolve the scope with the owner. Then run `tools/dev/verify_plugin_mirrors.py` and relevant builder parity guards. Never hand-maintain only one copy or edit generated build output as source.
5. Add the required row to `docs/plans/architecture/REGRESSION_CATALOG.md` in the same fix. Update `tests/INDEX_BY_GUARD.md`, `docs/INDEX_BY_SUBSYSTEM.md`, and subsystem documentation when a new guard, document, contract, or invariant needs discovery.
6. For an `OPT-*` change, update the canonical item's status and validation history with the changed files, before/after measurements, guard, rollback, and remaining live gate.

## Phase 6: Verify proportionally

Run tests directly and check the process exit code. A typical focused invocation is:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest -p no:debugging <focused-test-paths> -q
```

Verification must include:

- the new regression guard;
- the affected subsystem suite;
- every adjacent boundary changed by the fix, such as UI/service, DB/cache, socket/download, viewer/identity, runtime/builder, or source/mirror;
- mirror verification and builder parity when applicable;
- a final diff/status audit proving no live database, patient data, secret, generated runtime state, or unrelated dirty file changed.

Do not claim a lint pass while Ruff is unavailable. Do not reinterpret an existing baseline failure as success; identify it as pre-existing only with concrete comparison evidence.

Use the source build for visual or live validation only. The human launches and logs in once; never open the installed executable, create another instance, improvise process recovery, or expose a clinical network for test automation. A visual imaging correction requires an appropriate known-case or synthetic check and, where clinical interpretation is involved, explicit human/radiologist confirmation.

Read section 0 of `docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md` before the live gate. Discover `aipacs-control` first; if unavailable, use its documented `tools/testing/aipacs_control_mcp/client.py` against the same local Test Control Server. Probe `ping`, then `list_actions`. Normal launches retain `AIPACS_TEST_SERVER=0`; an automation session needs an explicitly authorized source launch with test control enabled, outside clinical work, with human sign-in. A process launched before the change does not validate the change. Acknowledge a disk-space notice with OK, not Don't show again.

Exercise the actual changed input boundary: a downstream `drag_series` action does not prove native drag/drop or a Home-card click. Verify output identity, counts, rendered result, and session-scoped health/lifecycle evidence where affected. Report blocked/skipped GUI acceptance separately from passing code tests. Documentation-only skill maintenance requires document validation, not a fabricated runtime acceptance pass.

### Next-build and edition coverage

For every runtime fix, use the edition/backend matrix in [references/maintenance-evidence.md](references/maintenance-evidence.md). Read `BUILD.md` and the release/build documentation hub to resolve actual profile names and the current source-to-payload path. Check shared fixes in Standard/ARM Client and Eagle Eye Server profiles across PyInstaller and Nuitka; use evidence-backed N/A for intentionally absent features. Do not copy server-only models/features into Client to make the matrix look complete.

Record the next-build handoff in the owning fix record: corrected files and guards, applicable profiles, mirror/config/payload checks, source revision or dirty-file hash evidence, and the exact scenario still required on produced artifacts. Keep build-input verification and produced-artifact verification separate. Re-read the current Server gates; a source-service test does not prove frozen service, Session 0 or clean-host readiness.

Do not start a full build for each small fix, bump versions, publish or launch an installed executable merely to close this matrix. Build/release work follows separate user authorization, `RELEASE.md`, `BUILD.md`, and applicable deployment safety instructions. A future build must bind the fix to its immutable candidate receipt and artifact acceptance; until then report artifact verification as pending.

## Phase 7: Adversarial self-review

Before delivery, inspect the actual diff and ask:

- Does the guard fail on the real defect rather than on wording or implementation shape?
- Can the fix show the wrong patient, study, series, frame, report, or cached state?
- Can a late callback, repeated signal, close/reopen, retry, cancellation, or nested event loop re-enter destroyed or stale state?
- Is any blocking or unbounded work reachable from the GUI thread?
- Did the change cross an execution-domain, network, storage, security, or packaging boundary unintentionally?
- Are errors visible without exposing PHI, prompts, credentials, or raw clinical content?
- Is rollback safe, and does the kill switch preserve a known behavior where one is required?
- Did a broad cleanup, dependency, or refactor sneak into the fix?
- Are all claims supported by commands, exit codes, measurements, or observed live behavior?

Fix any defect found by this review and rerun the affected verification.

## Delivery contract

Lead with the outcome and report:

- the confirmed root cause and affected boundary;
- the chosen fix and why it is the safest seam;
- the regression guard and its fail-before/pass-after evidence;
- exact focused test results and process exit codes;
- mirror, index, catalog, and master-plan updates that applied;
- remaining risks, unrelated baseline failures, and any live verification still pending;
- rollback or kill-switch instructions when applicable.

Never say a defect is fully resolved while a required guard, boundary suite, mirror check, or live gate remains unverified.
