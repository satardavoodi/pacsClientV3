# Eagle Eye execution corrections

Date: 2026-09-22. Source fixes, not deployment or clinical qualification.

## Current acceptance ledger

This ledger supersedes historical pending/investigation statements in the
chronological evidence below. Passing computation does not imply clinical review.

| Surface | Latest established result | Open boundary |
| --- | --- | --- |
| Brain Standard / Robust | Integrated inference, measurement and 29-page derived reports pass after the CPU allocation correction; masks and QC equal their baselines | Native display, representative clinical and hardware qualification |
| LST lesion ensemble | Two complete post-registration correction runs pass with identical final masks and metrics, equal input hashes and model manifest | Native and representative clinical review; broader reproducibility qualification |
| MS / SVD | Fresh same-source anatomy fallback passes; derived report packets have 15 / 12 pages and portable previews | Native display and physician assessment |
| Bone Age | Selected-case computation and earlier native prediction display pass; independent two-client run passes | New settings GUI and deployment qualification |
| Breast | Detection output and prior native findings display pass; classifier remains explicitly unavailable | Owner deferred optimization and classifier reconciliation |
| Alignment / Total Spine | Selected-case inference and finite candidate geometry pass, including both Total Spine engines | Current native display, corrected anatomy/level review and clinical measurements |
| Lumbar | Backend segmentation passes; CTK bridge fix guarded | Native entry blocked by the separate presentation workstream |
| Server / client | Unified settings, owner-scoped queue, explicit parallel reservations, authenticated HTTP execution and synthetic TLS transport verified | Native settings, uncached PACS acquisition contract, separate-machine service and installer qualification |

Interactive editing synchronization remains phase two. Current server sources are
completed workstation cache or configured PACS storage; automatic acquisition of
uncached studies is not claimed. No server deployment or release was performed.

## Reproduced defects and changes

1. Server staging rejected every DERIVED image, including stitched DX/CR inputs accepted by the existing Alignment engine. Staging now accepts a derived radiograph only for Alignment/Total Spine and only when the request selects its exact SOP. Study/series/count/hash checks and downstream image guards remain mandatory. Derived MR remains excluded.
2. Brain PDF rendering treated an explicit section as one physical page. A real published-reference section exceeded the page and prevented completion after successful segmentation. Qt now paginates each section, preserving explicit section starts, table headers, page furniture and all rows. A 45-row wrapped synthetic table proves no row is lost or duplicated.
3. Windows Qt offscreen operation exposed zero font families and produced PDFs with no extractable text. The unmodified writer reproduced that behavior in an isolated baseline call. The writer now registers the installed Arial family when font discovery is empty, and fails explicitly if fonts remain unavailable.
4. Lesion jobs used a deeply nested patient directory as the Windows child working directory. A real run failed with WinError 267 before inference. Inference now uses an owned temporary directory, retains the identity-scoped destination, copies final outputs and private diagnostics, and cleans temporary inputs on success, failure and cancellation. No failed or cancelled mask is published.
5. The Lumbar Slicer bridge called a nonexistent CTK `seriesForInstance` method before submitting a request. It now snapshots instance IDs and the database filename, then resolves all instances using a worker-owned read-only SQLite connection. Missing, duplicate and mixed-series inventories fail closed; no database work or CTK connection crosses the GUI-thread boundary.
6. MS fallback anatomy inherited the nested lesion output directory as its child cwd. A separate Windows probe reproduced WinError 267 with a 309-character cwd; three synthetic fallback guards failed before the correction. Fallback anatomy now executes in owned short scratch, retains completed anatomy and provenance inside the lesion job, and removes scratch on success, failure and cancellation.
7. SVD relied on a sibling brain analysis, which is absent in isolated server jobs. The lesion pipeline now supplies its verified T1 input so SVD can compute same-job anatomy through the shared short-scratch helper. Both MS and SVD can reuse their retained, completed, same-study anatomy for later review; incomplete or mismatched anatomy is excluded. Private process diagnostics survive scratch cleanup without entering the artifact packet. Three SVD dependency guards, two completed-anatomy reuse guards and three diagnostic-retention cases failed before their respective corrections.

## Verification

The initial four synthetic regressions failed before production edits for source rejection, PDF overflow and excessive child cwd length. The Lumbar start regression separately reproduced the missing CTK method. The initial ten execution guards passed after correction. The earlier focused model/protocol/report selection passed 201 tests; the subsequent execution and affected builder selection passed 19 tests. Reported passing selections used direct pytest with retries disabled and exit code 0. Counts describe separate selections, not an additive total.

The Advanced MPR Lumbar mirror was synchronized with the supported tool. All 470 existing mirror pairs matched. No unrelated payload was synchronized.

Actual authenticated loopback Robust brain inference, independent Slicer measurement, PDF creation and result retrieval succeeded. The returned 29-page PDF has text, an AI-PACS header and review-required footer on every page; a reference page was rendered and visually inspected. No DICOM source was uploaded or returned. These are local private test results, not clinical approval.

The first actual Standard rerun terminated inside the computation runtime with Windows exit code `0xc0000409`; its private diagnostic is retained. A separately recorded retry succeeded in 432.4 seconds, including a 29-page PDF with text and headers on every page and derived-result retrieval. The intermittent native failure remains unresolved; one passing retry does not establish stability.

The complete corrected lesion workflow succeeded in 3512.9 seconds on CPU, including the actual LST computation, mask, eight-page PDF and authenticated derived-result retrieval. Every PDF page has extractable text; all eight rendered pages were visually inspected for content, page furniture and mask previews. The returned mask passed source geometry and binary-value checks, and temporary inference scratch was removed. No DICOM source was uploaded or returned. The resulting mask differs voxelwise from the earlier diagnostic run despite identical T1/FLAIR input hashes; reproducibility is not established, and downstream assessments must remain bound to their actual mask.

The final execution/MS/SVD/lesion/manual-review/reference selection passed 89 tests with retries disabled and exit code 0, including 20 execution guards. An actual nested MS fallback, independent Slicer measurement and registration to FLAIR succeeded in 479.5 seconds; durable anatomy and the mapped labelmap were retained, and temporary scratch was removed. Actual isolated SVD fallback also succeeded in 498.8 seconds with five spatial compartments and twelve regional rows. These isolated tests reused the earlier geometry-verified LST mask only after matching both original T1/FLAIR hashes exactly. They do not replace the full current lesion transport run or native MS/SVD display.

After the full lesion run completed, both downstream assessments were recomputed using its new mask and the retained same-study anatomy: MS succeeded in 25.4 seconds and SVD in 51.0 seconds. Source FLAIR hashes matched exactly, identity checks selected the completed nested anatomy, and both new mapped labelmaps were retained. Separate private receipts bind these assessments to the new mask hash. These are execution tests of the assessment paths; no disease indication, clinician review or specialized clinical report was supplied or inferred.

The user-selected complete Alignment radiograph was downloaded through the native thumbnail workflow and visually verified. Fresh authenticated loopback execution with corrected staging returned 16 finite landmarks in 51.0 seconds without returning DICOM. The selected Total Spine study was downloaded; its complete AP image was visually distinguished from regional and lateral images despite misleading series descriptions. Fresh authenticated ISBI and ScolioVis jobs returned 17 and 16 candidates in 23.6 and 29.1 seconds. Neither engine predicts verified anatomical level names. Candidate execution is not a reviewed Cobb-angle report or clinical acceptance.

Both Alignment sides produced finite measurements; scale remained explicitly unverified. All 17 ISBI and 16 ScolioVis candidate outlines passed convexity/order checks and yielded finite endplate angles. No anatomical level assignment or reviewed clinical measurement was invented.

A private overlay comparison was rendered and visually inspected. Proposal extents differed, including inferior proposals needing anatomical correction. Finite coordinates and convex outlines demonstrate executable geometry, not vertebral detection accuracy or readiness for automatic level assignment.

## Remaining live gates

### Brain registration repeatability follow-up

The same verified T1/FLAIR input pair was registered twice with the installed
`picsl_greedy 1.4.0.3` runtime. Both affine transforms differed with the original
two-thread/default-seed configuration. A nonzero seed alone still differed.
The fixed seed plus one registration thread produced exactly equal T1 and FLAIR
matrix arrays in two repetitions. This isolates a demonstrated source of variation
before lesion inference; it does not prove that all later inference is deterministic.

The source adapter `tools/eagle_eye/lesion_runner.py` now adds `-seed 1729` to
Greedy calls and binds registration's `n_threads` parameter to one, including
omitted defaults and explicit overrides. Model PyTorch thread limits, registration
metric/jitter amplitude, model weights and segmentation thresholds are unchanged.
The new synthetic guard failed first for the missing seed and then for the
unbounded registration thread setting; 36 affected execution/lesion tests and
three lesion payload tests subsequently passed with retries disabled, exit code 0.

The documented `finalize_lesion_bundle.py` route refreshed the local development
runner and manifest (23,187 files); the previous runner/manifest are retained in
private audit storage. The final resealed adapter was exercised again with callers
requesting two registration threads: both repeated transforms were exactly equal.
This is not an installer build or deployment. Any acceptance
bound to the earlier manifest is not acceptance of the new adapter. Two full
post-change lesion inference runs, native result review and clinical comparison
remain pending. The live control bridge responds to ping and exposes 77 actions;
connectivity is not a post-change GUI workflow pass.

The Standard abort remains unresolved: its retained process diagnostic contains
TensorFlow initialization output but no decisive failure cause, and Windows records
`0xc0000409` in `ucrtbase.dll`. Do not attribute it to registration or claim it fixed
by the lesion adapter change. No automatic rerun or model switch was introduced.

The installed Greedy help documents seed zero as stochastic. The upstream
[registration reference](https://github.com/pyushkevich/greedy/blob/master/docs/reference.rst)
also explains random sampling jitter; repeatability claims here are based on the
installed-runtime experiment rather than an assumption about current upstream code.

The user completed source sign-in; documented ping and action discovery succeeded. The source app began at 11:56, before the 12:00 staging fix, so its native Alignment attempt still failed before inference while displaying the correct complete image. The independent fresh service passed that exact input. A human source restart/sign-in was requested; the agent did not restart, duplicate or hot-reload the app. Alignment, Total Spine and Lumbar post-fix native GUI gates remain open. The requested radiograph source files are now downloaded.

The documented `download_patient` action reported `ADAPTER_INCOMPLETE`; native thumbnail loading successfully downloaded the selected study. This control-adapter defect was not modified as part of Eagle Eye inference.

A fresh owned Advanced Viewer rendered the verified lumbar MR input. Its current curated module menu omits the registered Lumbar module, with no alternate native entry found. This blocks the post-fix Lumbar button/overlay gate before inference; the owning presentation handoff is recorded in `VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md`. The agent did not alter concurrent presentation work or bypass it using Python-console injection.

Breast's previously diagnosed final-classifier feature mismatch remains a separate model-artifact blocker. No missing training features, medical conclusions or reviewer approvals have been invented. GPU, separate-client LAN/TLS, clean-machine packaging and release qualification remain separate gates.

## Ownership and rollback

### Native Brain abort evidence (2026-09-22 follow-up)

Owned Brain processes now retain bounded numeric diagnostics: executable basename,
UTC start, PID, elapsed time, sampled process-tree peak RSS, minimum available
physical memory, outcome and exit code. No arguments, patient paths, environments
or raw worker output enter this record. Short-scratch lesion/MS/SVD paths retain
it privately; artifact export excludes it. Failure evidence, timeout/cancellation
and scratch-retention/export guards pass in the 119-test combined selection.

A fresh Standard workflow passed in 387.0 seconds. A later diagnostic repetition
failed again: 117.8 seconds end to end, computation exit `0xc0000409` after 94.0
seconds, sampled peak tree RSS 12,864,794,624 bytes and minimum available physical
memory 23,141,650,432 bytes. Windows recorded the same `ucrtbase.dll` failure offset.
Local dump inspection found a C++ exception record whose compiler type metadata
resolves to `std::bad_alloc` in the TensorFlow native module. This identifies an
allocation failure, not its root cause; physical RAM availability alone does not
establish commit headroom or the failed allocation size. A monitored repetition
is collecting system commit and process-private allocation counters. No automatic
retry, model switch, memory-limit change or numerical workaround was introduced.

That monitored baseline completed in 402.7 seconds, but its computation child
reached 69,605,953,536 bytes of private allocation and sampled system commit
headroom fell to 44,920,832 bytes. Automatic Windows pagefile growth accompanied
the peak. This demonstrates severe commit pressure even on a successful run;
it does not retrospectively measure the previous failure's exact headroom.
The process diagnostic now also records peak private allocation and minimum
system commit headroom. A synthetic physical-versus-commit guard failed before
the extension; all 25 study-workflow tests then passed with exit code 0.
An isolated same-input experiment explicitly enables TensorFlow's oneDNN CPU
operations to measure whether the alternate convolution implementation avoids
the large allocation. Production numerical execution is unchanged while that
experiment and output comparison are pending.

The dump remained local. Compiler exception-type decoding follows
[Microsoft's debugging reference](https://devblogs.microsoft.com/oldnewthing/20100730-00/?p=13273);
raw stack-address candidates are not represented as a fully unwound symbolic stack.
The two full post-registration-change lesion repetitions remain running/pending;
exact final-mask repeatability is not yet claimed.

### Brain CPU allocation correction

The alternative CPU experiment completed twice, in 216.7 and 208.6 seconds versus
402.7 seconds for the monitored default baseline. The first alternative run's peak
private allocation was approximately 26.5 GB versus 69.6 GB in the baseline.
Both returned masks are exactly equal to the baseline at all 10,812,000 voxels,
with matching geometry and identical source hashes. All eight QC values are equal.
The 101 probabilistic volume entries differ by at most 0.07 cubic millimetres
(maximum relative difference approximately 0.00031%). This measured difference is
reported, not silently described as bitwise equality of every result.

`service.py` now explicitly supplies `TF_ENABLE_ONEDNN_OPTS=1` only to the owned
SynthSeg process, before TensorFlow import. It records
`cpu_backend=tensorflow-onednn-cpu` in completed results. Standard/Robust model
weights, two computation threads, full image coverage, parcellation, QC and
segmentation thresholds are unchanged. The existing timeout, cancellation and
failed-result guards remain in force; there is no automatic retry or silent
Standard-to-Robust switch. Both historical crash dumps resolve to `std::bad_alloc`.
This correction avoids the demonstrated high-allocation default CPU path; it is
not a promise that every possible study fits the available machine memory.

Four Standard/Robust success/report-failure guards failed before explicit backend
selection and metadata recording. The affected Brain/workflow/execution/lesion/
transport selection then passed 129 tests, direct exit 0, retries disabled.
A fresh Robust job without an ambient backend override passed through the integrated
normal execution path in 251.6 seconds; a corresponding fresh Standard job passed
in 210.6 seconds. Both completed server inference, independent Slicer measurement,
29-page PDF publication and authenticated derived-result retrieval. All PDF pages
contain text and an AI-PACS header; returned results record the selected CPU backend.
Both masks are exactly equal to their same-source, same-profile baselines and all
eight QC values match. Robust's 101 probabilistic volumes differ by at most 0.26
cubic millimetres (maximum relative difference approximately 0.00034%); Standard
retains the measured 0.07 cubic millimetre bound. No source DICOM was uploaded or
returned. Full new native GUI acceptance and representative clinical
equivalence remain open. The independent full LST repeats are unchanged by this
SynthSeg-only setting.

The option is documented in the upstream
[TensorFlow CPU optimization RFC](https://github.com/tensorflow/community/blob/master/rfcs/20210930-enable-onednn-ops.md)
and [Windows TensorFlow 2.10 release notes](https://blog.tensorflow.org/2022/09/whats-new-in-tensorflow-210.html).
All timing, allocation and numerical comparisons above come from the installed
local runtime, not extrapolation from upstream performance claims.

### SVD anatomical geometry boundary

Adversarial review found that SVD accepted same-sized anatomy labels even when
their spacing, origin or direction differed from the anatomical source image.
Applying the source-image transform to those labels could produce incorrect
anatomical localization. The SVD boundary now uses the same physical-geometry
check as MS before registration. Three synthetic SVD cases failed before this
change; the matching three MS cases already passed. Afterward, 79 affected
execution/MS/lesion-context/manual-review/lesion tests passed, retries disabled,
direct exit 0. This prevents inconsistent geometry; it does not establish clinical
registration accuracy. Fresh actual MS/SVD fallback execution is tracked separately.

Fresh actual MS and SVD fallback runs using the newly completed LST mask passed
in 224.1 and 264.7 seconds. Each independently computed missing T1 anatomy through
the normal oneDNN backend, matched its T1 source hash to the lesion job and saved
anatomy mapped into FLAIR space. This verifies the computation boundary; it does
not infer an MS/SVD diagnosis or physician review from the selected input.

An authenticated cancellation after actual TensorFlow startup also passed: all
three owned Python processes stopped, the reservation returned to zero and no
completed artifact archive appeared. The first probe incorrectly required every
descendant to disappear at the exact instant the parent terminal state arrived.
A bounded follow-up measured 0.060 seconds of Windows descendant cleanup after
that state; total startup/cancel probe duration was 28.8 seconds. No production
process-control change was made on the basis of the initial probe assertion.

### Portable lesion report previews

The derived packet's lesion HTML referenced server-only `file:///` preview paths,
while its PDF already contained the images. A regression guard removed the source
PNGs and demonstrated that the HTML could not carry its preview images to a client.
`lesion_report.py` now embeds the unchanged PNG bytes, as other Brain reports do.
No image selection, physical aspect ratio, mask or measurement changed. The guard
passes after correction, and 103 affected lesion/transport/assessment tests pass
with retries disabled and direct exit 0.

Fresh reports from the actual MS/SVD fallback outputs were published and unpacked
through the production artifact contract. They contain 15 and 12 PDF pages,
respectively, all with text and the AI-PACS header, the context-specific assessment,
the lesion mask and six decodable embedded previews each. Source DICOM and FLAIR
volumes were excluded. The report context was explicitly marked engineering
verification; no clinical indication or sign-off was inferred. These artifact
checks do not replace native client display acceptance. Rollback of this isolated
report change restores the nonportable server file references.

### TLS listener isolation

A real local TLS acceptance test initially confirmed trusted-certificate operation
and rejection of untrusted/wrong-host certificates. Extending it with a TCP peer
that never started TLS reproduced a different defect: the listener blocked during
`accept`, so a second authenticated client's TLS handshake timed out. The server
now uses `do_handshake_on_connect=False`; TLS runs in the individual connection
handler under the existing 30-second socket timeout. The second client now receives
capabilities while the stalled peer remains open, and certificate checks plus
authenticated synthetic job/result retrieval still pass. The affected transport,
scheduling, roles and settings selection passed 45 tests, retries disabled,
direct exit 0. No production certificate, trust store, firewall or service changed.
Separate-machine qualification and connection-count/rate limits are not established
by this test. Removing handshake deferral restores the reproduced stall.

### Completed full LST repetition

Both complete post-registration-correction runs finished successfully in 3484.8
and 3897.8 seconds, respectively. They have identical T1/FLAIR input hashes and
model-manifest hashes. Final native-FLAIR binary masks are exactly equal, with
zero differing voxels; the published measurement dictionaries are also identical.
Each mask passes native FLAIR physical-geometry validation. Recomputing measurements
after NIfTI serialization preserves component counts and agrees within relative
tolerance 1e-6 (absolute tolerance 1e-8); it is not bitwise equality of volume
values because stored NIfTI spacing has lower precision than the original in-memory
spacing. The between-run published metrics are exactly equal.

Each authenticated result retrieval contains an eight-page PDF with text on all
pages and six embedded preview images, without source DICOM. The first run predates
the HTML embedding correction; the second run's HTML contains portable embedded
previews. The audit service exited normally and removed its temporary access token.
This closes the two-run, same-input engineering comparison for the resealed adapter;
it does not establish universal deterministic execution, segmentation accuracy,
native GUI acceptance or clinical qualification. No inference settings or model
weights were changed between these two runs.

### Latest native GUI preflight

The final control-client probe returned `pong`, and `list_actions` succeeded.
Read-only native observation found the source workstation in active clinical use
with voice-recording controls active. No navigation, patient switch, setting change,
recording interruption, restart or duplicate workstation launch was performed.
The earlier unreachable-control observation is therefore historical; current
settings/result GUI acceptance remains pending because the live session is in use,
not because control discovery failed. Connectivity is not a workflow acceptance pass.

The owner explicitly deferred Breast optimization on 2026-09-22. Its unresolved
classifier contract remains visible; no inferred feature order or replacement
weights are introduced while continuing Brain and server/client work.

This extends OPT-51 Eagle Eye job ownership and OPT-56 Advanced Analysis integration. Only the Eagle Eye reference bridge in the Slicer module changed; viewer decoding/rendering and shared download coordination were not modified. Revert the isolated changes in `source.py`, `organized_report.py`, `lesions.py`, `ms_assessment.py`, `svd_assessment.py`, the internal `anatomy_context.py` helper and `AIPacsOfflineLumbar.py` together with its mirror to roll back; preserve all pre-existing worktree edits. The CPU allocation correction is isolated to SynthSeg's process environment and result backend metadata in `service.py`; removing it restores the demonstrated high-allocation path. Model weights, classification thresholds and clinical validation state are unchanged. The separately recorded lesion adapter manifest refresh is explicit above.
