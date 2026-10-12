# Server readiness hardening - 2026-10-10

Owner backlog: OPT-51 / OPT-55 / OPT-56. Clinical activation is intentionally
separate from this source repair. The active Razi r3 must not be overwritten.

## Repaired source boundaries

- Model worker, CRM child and Server edition dispatch use the shared frozen
  detector for both PyInstaller and Nuitka. Synthetic backend guards failed
  before the repair; they do not constitute installed artifact acceptance.
- The owning service supervisor observes actual listener-loop progress. After
  progress stalls it requests the existing private correlated admission drain.
  Only a fresh CLOSED, zero-inflight, completion-certain certificate permits
  recovery of the owned process tree. Busy or unreachable control remains alive;
  a completely deadlocked admission controller still needs manual diagnosis.
  No public restart endpoint or forced clinical cancellation was introduced.
- New model stdout/stderr is drained into a private bounded 1 MiB worker log.
  A failed sink continues draining and fails the job rather than letting a full
  pipe hang the worker. Indeterminate process cleanup retains priority over log
  errors. Historical logs/results are preserved; retention remains open.
- Installed Server and Client have distinct AppIds, default folders, configuration,
  local state and package roots. Server storage is under AIPacs/EagleEyeServer.
  The release marker selects storage only; verified role/release admission still
  authorizes execution. Developer source paths and Client legacy paths are retained.
- Server setup rejects existing targets and disables automatic application
  closing. It cannot use the generic Client previous-uninstaller path. This is
  a protective fence, NOT the missing coordinated Server upgrade adapter.
- Audit fixtures now supply authenticated human ownership, an admission-capable
  synthetic CRM job owner and sealed synthetic engine inputs. Timeout verification
  observes behavior instead of requiring an obsolete source-code string.

## Verification and remaining gates

Local direct pytest: 103 focused/packaging tests and 45 adjacent lifecycle tests
passed, exit 0. The 528 plugin mirror pairs match. Individual fail-before receipts
and combined XML are in generated-files/eagle-eye/server-hardening-20261010.
Sanitized inactive-candidate parity and remote test receipts belong there too.
They are not proof that active r3 contains these fixes.

Ordinary authenticated read-only active CRM health returned HTTP 200, status ok,
39 tools and writes disabled. This does not reproduce or close the earlier
provider/reception timeout, nor exercise patient queries or write commands.

OPEN P0: protected durable Windows installer host adapter, retained complete
old/new core and model/native payload manifests, host-private Server enrollment,
qualified shortcut/service selection and rollback/reboot recovery. Existing Server
targets deliberately fail closed until that adapter is qualified.

OPEN acceptance: clean Windows Session 0 fresh install/upgrade/rollback/reboot for
both backends; exact clean-commit release and credential-audit gates; affected live
source GUI; same-revision Function Tester/provider and three-platform acceptance.
No frozen application or production restart is authorized by these source tests.

OPEN capacity: measure mixed-engine peak RAM/CPU before increasing serial clinical
inference. Per-workflow total/queue deadlines, privacy-aware retention and indexed
terminal history require separate evidence and policy; the fixed 7200-second model
budget is unchanged. No patient files, queues, credentials or host settings were
copied, deleted or rewritten.

## Remote qualification refinement

The first inactive r1 run passed143 and failed5 tests: four packaging fixtures
implicitly depended on local VMTK assets, and one canonical Git inventory test
cannot run in a transferred source tree without .git. VMTK staging now receives
an explicit sealed synthetic bundle too (12 local native/payload tests pass).
The canonical Git inventory guard remains unchanged and is verified locally;
remote snapshot hash parity is its separate Razi boundary. Do not count that
Git-only guard as a remote pass.

The owner selected Windows A100 for installer QA. Read-only verification found
Windows Server2019, active demo PACS/MongoDB, occupied104/8000/8005/8085 and no
sampled8002 listener. It is not a clean Windows10/11 baseline. Preserve its demo
services; use isolated installation/state/ports and record reboot/rollback
qualification separately. No QA installation or reboot has occurred.


## Independent server stability qualification, 2026-10-11

Owner backlog: OPT-51/55/56. Three new dedicated server guard files cover model
scheduling (9 cases), LLM hub isolation/paid-call safety (10), repeated recovery
(4). Temporary job/history stores, synthetic providers and explicitly owned
Windows child processes only; no clinical database, patient input, provider call,
SCM transition or private configuration change.

Local combined direct pytest: 131 passed, three dependency deprecation warnings,
exit 0, 30.23 seconds, retries disabled. Matching existing Razi selection:
108 passed, exit 0, 30.63 seconds. New Razi overlay initially: 23 passed, exit 0,
5.22 seconds. One new log-pressure guard had a test-only rollover observation
race, corrected by retaining its first positive observation. Final no-retry
remote results and exact hashes are retained in the frozen stability receipt.

Coverage: FIFO cancellation, independent CPU/RAM admission budgets, 16-job
saturation/reuse, 20 worker failures then successful recovery, owner isolation,
restart/duplicate idempotency, concurrent hub/accounting/history isolation,
provider/history failures without duplicate paid calls, 100 drain/resume cycles,
30 sticky-uncertainty attempts, actual child crash/hang cancellation, descendant
cleanup, bounded output and oversized/stale supervisor receipt flooding.

A synthetic scheduler experiment on Razi completed 160 serial jobs in 8.182 s
(19.56 jobs/s, terminal p95 593.30 ms), then 160 with four admitted jobs in
5.668 s (28.23 jobs/s, p95 382.80 ms). Observed peaks: one and four. Reservations
returned to zero; Python thread count returned from one to one. Work is a 30 ms
synthetic wait plus tiny artifact writes. These single-run plumbing measurements
are not actual AI throughput, CPU/RAM peaks, clinical speedup or a prolonged soak.

Fresh SCM selected 20261011-native-secretary-r15, LocalService, Running. Historical
states: 43 succeeded, 9 failed, 1 cancelled; no nonterminal inventory state. That
is not proof every synchronous API/native request is idle. Local server.py matches
active R15 SHA256 cefa7555e9ef158a6a734272a86ec2fb9cbe4449050c84920c2dc5a99e21d888.
Complete dirty-local/Razi parity remains OPEN; preserve unrelated Brain/build
changes. New owned tests/docs are staged outside executing R15.

Open P1: resource profiles are admission accounting, not actual CPU/RAM process
limits; Windows Job Object enforces kill-on-close only. Queue/retrieval/LLM total
deadlines remain absent; 7200 s begins at model worker execution. Busy/uncertain
work deliberately prevents forced watchdog recovery. Open P2: unbounded retained
imaging history, linear quota/recent scans, retention/index policy. Hub history
save failure may leave running records although duplicate paid calls remain
blocked. Semaphore stripe collisions may reject unrelated human owners as busy.

No production defect was patched in this qualification slice. Real mixed-engine
capacity, provider/PACS/CRM acceptance, 24/72-hour soak, service reboot, fresh
native GUI and both frozen installers on WinA100 remain separate unpassed gates.
Preserve local-build -> WinA100 -> customer acceptance. Evidence:
generated-files/eagle-eye/stability-20261011. Include exact frozen owned files
in the next immutable Developer inventory before completion/build handoff.
## Real model lifecycle measurements, 2026-10-11

On Razi, two sequential real-weight runs per engine used generated synthetic
images and the existing portable worker selected from R15. No patient input,
service transition, bundle modification or qualification activation was used.
The harness and sanitized receipts are in generated-files/eagle-eye/stability-20261011.

| Engine | Full bundle verification, seconds | Worker, seconds | Peak process-tree private memory, MiB |
| --- | --- | --- | --- |
| Bone age | 18.527 / 10.570 | 19.985 / 18.866 | 1374.4 / 1375.0 |
| Breast tissue | 29.659 / 16.925 | 35.078 / 32.392 | 1449.0 / 1450.1 |

All four runs returned successful results and all observed owned processes
exited. Sampling interval was 50 ms; memory is sampled aggregate process-tree
private memory, not whole-server demand or a guaranteed peak. Second runs may
benefit from OS file caching; neither run establishes cold-cache performance.
Worker time includes interpreter startup, imports, model loading and inference.
These are synthetic input measurements, not clinical accuracy, real-image
throughput, mixed-engine capacity or prolonged leak qualification. Breast tissue
alone does not qualify the concurrent tissue-plus-calcium branch.

Read-only lifecycle review found fresh processes and checkpoint loads per request
across Bone age, Breast, Brain, lesions, Alignment, Total Spine, assist models and
Lumbar. Bone age reuses a loaded model across images within one job only. Full
bundle verification repeats across jobs; Total Spine also verifies its Alignment
runtime. Current execution favors isolation and memory release over repeated-job
latency. No cross-request resident model pool is implemented by these adapters.

Breast dual executes tissue and calcium concurrently inside one admission
reservation. Its resource profile must cover their combined demand. Scheduler
CPU declarations currently do not set the hard-coded child thread budgets.
Observed tree thread counts (Bone 74; tissue 160) include auxiliary/native threads
and do not represent that many simultaneously busy CPU cores.

Optimization remains OPEN: first separate import/load/inference phase metrics;
then evaluate verification reuse tied to a sealed immutable bundle revision while
preserving input checks. Evaluate resident workers only with bounded RAM, idle
eviction, version invalidation, request-state reset and replacement on hang.
Do not remove integrity checks or enable unmeasured mixed-engine parallelism.
No runtime optimization or production defect fix was applied in this slice.



## OPT-51 HTTP listener settings correction, 2026-10-12

The owner-approved ordinary Eagle HTTP/password contract was blocked by save_listener_options requiring TLS for every non-loopback listener. The minimal correction allows an empty certificate/key pair for independently service-managed IPv4 listeners. Port/address/schema and optimistic revision checks, configured legacy TLS pair validation, unmanaged-host rejection and legacy paired-CA removal guard remain enforced. The Server panel exposes address/port and existing-account/grant guidance; dormant legacy certificate fields remain hidden and retain loaded values rather than silently migrating private host settings. Mobile-to-Windows Agent PACS pairing is untouched.

New guard tests produced four failures before the change: two HTTP saves, one UI contract and the legacy guard masked by the earlier rejection. Afterward26 focused guards passed,3 dependency deprecation warnings,2.86s,exit0,reruns0;531 mirror pairs match and no owned mirror exists. Existing TestControl ping/actions succeeded; fixed-source Server settings GUI acceptance has NOT run. No running Razi code, configuration, listener or process was changed. Exact owned source hashes and XML evidence: generated-files/eagle-eye/server-readiness-20261012. Stage outside executing source; full Developer reconciliation and installed PyInstaller/Nuitka acceptance remain open. Do not treat this local correction as build readiness.
