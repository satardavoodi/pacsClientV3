# Eagle Eye dataset workspace integration

Date: 2026-09-13
Status: source review and proposed implementation contract; not implemented.

Implementation amendment: the subsequent [template and case form delivery](EAGLE_EYE_DATASET_TEMPLATES_AND_CASES_2026-09-13.md)
implements native collection creation, editable templates, current-study enrollment
and saved-case editing. The broader shared image-review migration and server design
below remain proposed; they are not implied by completion of the form workflow.

## Decision

Evolve the existing Data Set tab into a native PySide6 dataset workspace backed by
shared Python services. Organize collections by modality, anatomy and task, while
keeping case images and annotations independent of the currently open viewer.
Reuse the tested lumbar preparation, report proposal, geometry, review and export
logic. Do not make the standalone HTML server or its fixed C-drive directory the
application's permanent runtime dependency.

The HTML page is a presentation layer, not the dataset format. Its Python backend
already owns persistence and validation. Those rules can support both the existing
browser tool and a native editor without maintaining two annotation implementations.

## Verified current implementation

| Source | Existing behavior | Integration gap |
|---|---|---|
| `modules/ai_imaging/ai_module_ui/ai_mainwindow.py::_ensure_lazy_tab` | Creates Data Set with study UID and Eagle Eye mode; creates Training and Reception lazily | No collection catalog or dataset membership context |
| `service_tab/dataset_tab.py::DataSetTab` | Reads supplied rows/providers or discovers study attachment CSV files; refresh and column selection | Read-only table/tree; no add-case, annotation editor, dataset creation or transfer workflow |
| `service_tab/dataset_tab.py::_normalize_module_mode` | Recognizes mammography and bone age | Brain/lumbar are not dedicated dataset types; file preference is sorting, not strict filtering |
| `service_tab/dataset_identity.py` | Normalizes CSV study/series/instance identifiers and groups study -> CSV -> row | Legacy display identity is insufficient for collection membership, person partitions and annotation revisions |
| `ai_module_ui/feedback_schema.py` and `service_tab/feedback_collector.py` | MG and bone-age human feedback, review status and training collectors | No generic multiview, per-level lumbar review contract |
| `service_tab/model_tab.py` and `training_data_settings_tab.py` | Bone Age/Mammography settings and local training dispatch | No current lumbar MONAI release/job binding |
| `service_tab/reception_data_service.py` | Configured reception API and worker-based retrieval | Prints patient URL/response text; waits synchronously for a previous worker; results need explicit request/study binding before reuse |
| Local `review_app/review_server.py::Store` | Native planes, separate locator, report prefill, evidence checks, history and revision-aware saves | Fixed lumbar root/layout, cached current cohort, five-level schema and in-process lock; not a generic application repository |
| Local `tools/prepare_regional_candidates.py` | Native acquisition groups, sagittal overlap crops, geometry/hash checks | Batch/root-dependent tooling must become parameterized per-case services |
| Local `tools/export_reviewed_regional_release.py` | Reviewed level samples, masks and patient partitions | Must be selected by dataset adapter, not invoked through MG training |

The `service_tab/` paths above are relative to
`modules/ai_imaging/ai_module_ui/`. The local tool paths are relative to
`C:\AI-PACS-Datasets\lumbar-mri\v0.1`.

The inspected dataset path stores `export_status` and `server_sync_status`, but
does not implement a dataset transfer protocol. Reception report/attachment upload
is a different contract. Existing Linux staging scripts are operational tooling,
not an installed workstation dataset API. No remote server capability was probed
in this review.

## User workflow

1. Open Eagle Eye on a study and select Data Set. This action does not start AI.
2. Select modality, anatomy, then a named dataset. Examples: MRI / Lumbar Spine /
   Lumbar Pathology; MRI / Brain / Brain Segmentation. Display MRI while storing
   the DICOM modality code MR. A dataset also has a task and schema version.
3. View its saved cases, review progress and quality holds. Switch between all
   dataset cases and memberships of the current study. Dataset browsing does not
   silently switch the clinical viewer's active patient.
4. Choose Add Current Study, Add Another Study or Import Existing Dataset.
   Another study uses the existing PACS search/download services, with an explicit
   selected study identity. Adding the same study again opens its existing entry.
5. Prepare the case in the background: validate/download selected acquisitions,
   retain the original report snapshot, reuse valid Eagle Eye artifacts, build
   missing native groups/cards, and populate report proposals.
6. Open the anatomy-specific editor. For lumbar: level selection, complete native
   axial/sagittal groups, source report text, proposed findings, uncertainty list,
   per-target corrections, image evidence and review controls.
7. Save a draft or save reviewed observations. Return to the collection and see
   the updated count of reviewed targets and unresolved requirements.
8. Select cases or a collection version, prepare a release, review its contents
   and destination, then send it. Show queued, transferring, server-validating,
   accepted or failed state with resumable retry. Upload does not start training.
9. Model Training selects an accepted compatible release and an explicit training
   job configuration. Results bind to that exact release and model version.

Show clinical labels and status in the ordinary workflow. Keep raw UIDs, file
paths, schema names and hashes in a details panel rather than the main case table.
New anatomy collections can exist before an annotation adapter is available, but
their unsupported annotation/export actions must remain visibly unavailable.
Brain segmentation support does not imply an implemented brain pathology schema.

## Data model and storage

Use separate concepts for:

- Dataset definition: stable ID, name, modality, anatomy, task, schema version,
  required sequence roles, target vocabulary, evidence/quality policy and exporter.
- Case: center-scoped private study identity, person group, acquisition versions,
  report versions, source completeness and local artifact references.
- Membership: dataset ID + case ID; prevents repeated imports and allows one study
  to belong to several tasks without copying its DICOM files for every category.
- Sample: case + anatomical target + immutable input selection/version. A lumbar
  level may contain several findings and native acquisition groups.
- Annotation revision: target values, unknown/normal distinction, origin, report
  evidence, image evidence, reviewer, coverage, quality disposition and source hash.
- Release: immutable manifest of exact sample/annotation revisions, partitions,
  file hashes and export policy. Transfer receipts and training jobs reference it.

Patient ID alone is not a portable primary key. Match center, study UID and
reception/exam linkage; use a separate person grouping key for leakage prevention.
An MRI may occur after admission: do not reject a correct report merely because
its admission date differs from the MRI date. Multiple studies or reports for the
same person still require exam-specific matching, not simply the most recent report.

Keep C:\AI-PACS-Datasets as this workstation's configured dataset root. Register
the existing lumbar-mri/v0.1 directory in place rather than relocating its data.
Proposed root additions are `catalog.sqlite`, `collections/<dataset-id>/` and
`transfers/`. Future case packages can use `cases/<case-id>/`; the first adapter
must continue resolving the existing patient/exam/research layout.

Use a dedicated dataset catalog, not the live PACS dicom.db. Store searchable
membership/status metadata in SQLite; retain clinical artifacts and immutable
annotation revisions in case packages. Publish a revision atomically before a
transaction updates the current revision pointer. A crash before the transaction
leaves an unreferenced immutable file, not a partially written active annotation.
Use expected-revision checks and one coordinated writer across UI clients; the
old HTTP server's process-local lock cannot protect a separate native writer.

Retain original DICOM, native NIfTI, geometry/source membership, pipeline outputs,
cards, reports and review history locally. Cards are presentation/evidence artifacts;
native volumes and spatial metadata remain the lumbar model's image inputs.
Keep datasets outside viewer cache cleanup. Existing references into temporary
PACS storage must be materialized/verified before a case is declared self-contained.

Pathology lists are indexed views, not exclusive patient folders. For example,
one patient can contribute L4-L5 protrusion and L5-S1 extrusion; one level may
contribute extrusion and recess stenosis. A reviewed normal level is also a sample.
Do not call an unmentioned or unreviewed level normal. Retain patient-based splits
across levels, repeat studies and overlapping collections in the same experiment.

## Shared core and native presentation

Proposed package: `modules/ai_imaging/eagle_eye/datasets/`.

| Component | Responsibility |
|---|---|
| `definitions.py` | Versioned modality/anatomy/task schemas and capability registry |
| `repository.py` | Collection membership, source references, revisions and persistent catalog |
| `case_preparation.py` | Parameterized resumable per-case preparation, immutable input snapshot |
| `report_proposals.py` | Report linkage, extracted proposals, conflicts and source provenance |
| `review_service.py` | Shared save/quality/evidence validation for native and HTML clients |
| `release_service.py` | Immutable release selection, validation and export |
| `transfer_service.py` | Destination capabilities, resumable transfer and receipts |
| `adapters/lumbar.py` | Existing five-level/15-target native MONAI contract |
| `ui/` | Catalog browser, case queue, schema-driven fields and owned image review pane |

These are proposed file boundaries, not new modules already delivered.
Separate generic membership/revision mechanics from lumbar-only anatomy and
geometry assumptions. Do not generalize the current axial/sagittal renderer into
brain or CT behavior without a tested adapter.

The native paired-image pane can render the existing Python-produced native
planes with Qt, preserving physical aspect, slice indices, pixel-to-world mapping
and the separate locator. It owns its image cache and lifecycle. Never borrow a
mutable Fast Viewer/VTK actor, render window or cache. Import read-only source
artifacts by identity through the documented trunk only.

Web embedding is possible: this repository already uses QWebEngine in its browser
module. However, embedding http://127.0.0.1:8841 alone would retain the fixed cohort,
separate process lifecycle and missing catalog/case creation features. It is an
optional transition, not the full requested integration. A transitional web editor
would need an app-owned service, dataset/case routing, bounded navigation, private
browser state and the same save API; it must not share the ordinary browser profile.
The preferred final interface is native PySide6 with a shared Python core.

## Preparation and clinical review boundaries

- Opening a dataset must not rerun screening, diagnosis or report extraction.
  Reuse only artifacts matching the source identity and compatible pipeline/schema.
  Rebuild a changed stage as a new version, retaining previous human revisions.
- Existing clinical MRI analysis keeps the canonical geometry -> anatomy ->
  screening -> diagnostic card -> diagnosis sequence. Research collection may
  retain normal/unreviewed native groups without invoking diagnostic inference.
  Screening positivity must not become the sole eligibility gate for a training
  collection, which also needs reviewed negatives and missed-positive examples.
- Lumbar labels are per target: report_suggested, human draft, image reviewed;
  unknown targets remain masked. Partial reviewed levels can be exported under the
  existing contract, with completion policy visible at collection and case level.
- Do not merge or reorder native geometry groups. Evidence retains parent group,
  native slice index and source hash. Full acquisition context and a locator do not
  replace explicit target evidence. Central canal, recess and foramen stay distinct.
- Queue preparation, API retrieval, volume decode, hashing, export and network
  transfer outside the Qt GUI thread. Use bounded workers, progress and cancellation.
  Tag every result with dataset/case/study/revision and reject stale arrivals.
- Reuse reception configuration and parsing semantics, but correct the observed
  sensitive logging and blocking worker waits before adopting that service for
  rapid case switching. Preserve existing Reception behavior with regression guards.
- Report prefill remains the existing offline rule method unless a separately
  configured extraction provider is selected. No provider is invoked by tab entry.

## Server contract to implement and verify

The server address, authentication and capability discovery belong in settings,
not in a dataset schema or hardcoded workstation SSH command. Required capabilities:

1. Negotiate supported dataset/task/schema and runtime versions.
2. Create an idempotent upload session for a release ID and manifest hash.
3. Return missing objects/chunks; stream with bounded memory and resume after failure.
4. Verify size/hash, safe paths, reference consistency and schema on the server.
5. Atomically accept the complete release and return a receipt. A transport success
   alone must not set `synced` or `ready_for_training`.
6. Create a separate explicit training job tied to an accepted release; expose
   progress, metrics/checkpoints and failure state without changing local labels.

Define two independent export policies: a minimal training release and, only for
an appropriately configured destination, a full case archive. Default lumbar model
input excludes raw reports, identity linkage and diagnostic text; these remain
local provenance and must not become target-leaking model features. De-identification
must account for headers and burned-in image text, not merely pseudonymous filenames.
Training upload never automatically interrupts EchoMind. GPU allocation/restoration
continues under the existing server maintenance contract.

Actual endpoint support/authentication, quota and retry behavior are unverified;
this review does not claim an existing server already provides this protocol.

## Delivery sequence and acceptance

1. Extract the existing local Python core and synthetic guards into application
   source with parameterized roots. Register the current lumbar collection in place.
   Verify hashes, revisions, report proposals and frozen splits are unchanged. Route
   the old browser frontend through the same writer before enabling native writes.
2. Add the native collection/case browser and lumbar editor. Retain the old CSV
   results view for MG/bone age. Verify add/reopen, duplicate prevention, another-study
   selection, stale-result rejection, draft recovery and partial review end to end.
3. Connect per-case preparation to existing PACS/reception and Eagle Eye services.
   Test missing series, date-offset report linkage, source changes, quality holds,
   no-report cases, cancellation and multi-level/normal sample preparation.
4. Implement release/transfer with a server adapter and mocked failure/resume tests;
   verify one actual accepted server release before enabling its training action.
5. Add further anatomy/task adapters with their own labels, evidence requirements,
   image contracts and training backends. Do not reuse lumbar labels for Brain.

Acceptance includes concurrent edits from two windows/clients, application restart,
partial network failure, immutable release retries, patient split leakage, source
geometry preservation and absence of clinical content in routine logs. Packaging
must include the extracted Python/static assets using existing runtime/catalog and
mirror rules; no customer runtime may import developer scripts from this C-drive.
Async/lifecycle follow-ups belong to existing OPT-01/OPT-27/OPT-51/OPT-58 work, not
a parallel performance plan. No runtime optimization is claimed by this design.

## Evidence for this review

Read the current dirty working-tree Eagle Eye entry, Data Set, identity, feedback,
training, reception, canonical MRI pipeline and local review/preparation/export code.
Re-ran the local synthetic review, report-prefill, split, regional-input and reviewed
export suite: **51 passed, exit 0** on 2026-09-13; existing SWIG deprecation warnings.
This verifies the reusable local foundation, not a completed in-app integration.
No patient data was exported; no clinical label, app runtime, server or model was
changed. No live workstation session, server upload or training job was exercised.
