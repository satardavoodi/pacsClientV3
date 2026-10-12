# Education review and authoring contract

## Instructor workflow follow-up - OPT-61 (2026-09-29)

This follow-up supersedes the initial review's editor-routing and authoring findings
where explicitly closed below. User scope: easier course building and dependable
instructor presentation. Existing unrelated changes remain intact.

### Delivered behavior

- My Courses editing opens Build Course. Downloaded Library resources remain read-only.
- Back to Card Data / Save and Continue updates the same course identity, preserving
  slides, imported taxonomy values and outline metadata. It no longer inserts another
  course. A failed cover copy retains the draft identity for retry.
- Switching/adding/moving slides, saving/finishing and previewing flush pending slide
  edits. A failed slide write retains the input and restores the previous selection.
  Ctrl+S saves the draft. Save status distinguishes pending edits from saved work.
- Item reordering validates complete slide ownership and commits in one transaction.
  An injected second-write failure no longer leaves duplicate partial order values.
- Course-card fields scroll; slide controls have less rigid minimum sizing, current
  slide title wraps, text is included in type help, and double-click edits an item.
- `Save and Return to My Courses` saves a draft without claiming educational completion.
  An empty draft can be retained but cannot launch a content-free preview.
- `Preview / Present` reloads the just-saved course and opens a dedicated window around
  the existing Education viewer. Resource availability is checked on a worker before
  the instructor presses Start Presentation. Warnings identify slide/item positions.
  The check verifies availability, not codecs, clinical correctness or permission.
- Page Down / Page Up visit resources within slides before moving between slides;
  F11 toggles full screen and Escape returns to the normal presentation window.
- Item and cover asset copies run off the GUI thread. Dialog cancellation and window
  close retain their worker until completion; pending cover work cannot switch course
  identity and resumes the requested preview/save action on success.
- Late deferred media callbacks cannot replace a newer selection. Empty/error messages
  switch away from the old DICOM page. Closing invalidates pending item deliveries.
- External document/media fallback is explicit: it offers an Open button instead of
  launching another application automatically during the lecture.
- DICOM content selection fails closed: missing study identity never reuses the previous
  study; an explicit missing series never falls back to the first series; a blank folder
  never means the current working directory. Successful exact-series selection remains
  supported, including series number zero. Decoder/render/cache implementations were
  not changed.

### Reproduction and acceptance

Fail-before evidence: five authoring failures; two stale-navigation/error-page failures;
one partial-reorder failure; one automatic external-open failure; three invalid DICOM
selection failures. All were reproduced with synthetic input before their respective
fixes. Separately, a probe executing the backed-up `_pick_source` confirmed its copy
ran on the GUI thread; current worker tests confirm it runs outside that thread.
No lecture-scale latency or throughput claim is made.

Guards: `test_authoring_flow.py`, `test_presentation_navigation.py`,
`test_presenter_tasks.py`, and the worker/cancel addition in `test_build_course_items.py`.
They include actual Qt controls, isolated database rollback, worker retirement,
saved-preview delivery, a successful DICOM reference control and presentation-shell
navigation with a synthetic viewer. The shell test does not load clinical images.
Final suite and parity receipts are appended at the end of this follow-up.

Final direct pytest receipt: **196 passed, 1 xfailed, 3 existing SWIG deprecation
warnings in 21.78 seconds; exit 0**. Selection: `tests/code/education`,
`tests/code/education_online_consultation`, and
`tests/code/builder/test_plugin_package_registry.py`, with `-p no:debugging -q
--tb=short --reruns 0`, `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=.`. The xfail is
the pre-existing recorder backpressure quarantine, not a pass. Mirror verifier:
**488 pairs match, zero plugin-only files, exit 0**. Skill validation passed.
All five owned runtime files parse and match their payload byte-for-byte. The
database diff preserves all pre-existing code outside the new reorder helper.
The shared master-plan file retains a pre-existing terminal blank line reported by
`git diff --check`; this unrelated whitespace was not rewritten.

Final source/payload SHA-256:
- `education_module_redesigned.py`: `cec5e8f9fc3953f586edb1f5fea2c68341ba2f97200ce71192469ead27740f40`
- `educational_patient_viewer_widget.py`: `31940756889f8ca8dd7e84df5e03673a02f8de7d2ee4423408ce2115402a05d5`
- `course_database.py`: `d5b2bb484a126b36203b687fbbbe4cebe107d0e4131a89a0904978a6429ef319`
- `authoring_tasks.py`: `1fddebdfb1b42b936d1dad88f9667be2c024b03658c66f4b1f82ba364648c88f`
- `presentation_window.py`: `9f0f370e1e765a816d8e2381340707a29d824eba73876fad1bd1fa3641f33e71`

A synthetic 1180x800 Build Course layout was rendered and inspected offscreen with an
explicit local font; controls were visible. This is layout evidence only. The source
control bridge was probed again and remained unavailable (ping exit 1, local endpoint
not found). Fresh human source launch/sign-in and real text/image/audio/video/PDF/DICOM
presentation acceptance remain **BLOCKED**, not passed. No installed build was run.

Fresh-source scenario: create a synthetic course; add text and permitted media; edit
slide notes, switch and return; edit card and confirm one course; reorder resources;
Preview / Present; inspect preflight; start; use Page Up/Down and F11/Escape; change
rapidly after video; exercise missing files and exact DICOM identity; close/reopen.
Verify rendered output and session health, not merely accepted control commands.

### Scope and handoff

Backup: `C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-presenter-20260929-081506`.
It contains pre-follow-up code/docs, owned existing payload copies, a hash manifest and
the synthetic layout image. The skill implementation map was updated with the new route.

Owned runtime files: `education_module_redesigned.py`, `course_database.py`,
`educational_patient_viewer_widget.py`, plus `authoring_tasks.py` and
`presentation_window.py`. All belong to the existing Education source-tree package;
no module ID, feature flag, dependency or schema was added. The existing Standard,
ARM64-emulated and Eagle Eye GUI package matrix below applies; produced installer
acceptance remains pending for both backends.

Remaining boundaries: portable cross-machine export is not implemented by a local
resource preflight; remote Library transfer/publishing remains separate; bulk importer
transaction/staging work and heavy media/DICOM decode responsiveness were not rewritten.
Existing decoder owners retain their execution domains. This follow-up does not certify
an entire course or all possible media. A cancelled copy can leave an unreferenced copied
asset; no broad storage cleanup was performed. Roll back only owned changes after
comparing with the backup and checking for newer edits.

Date: 2026-09-29. Scope: workstation Education code review, reusable authoring/development skill, and guarded item-editor corrections. This is not a release, remote publishing implementation, or full clinical validation.

## Current structure

| Area | Actual code path | Assessment |
|---|---|---|
| Education shell | `education_module_redesigned.py::EducationModuleRedesigned` | Library, My Courses, Build Course, and gated consultation composition |
| Build Course | `BuildCoursePage` and `ItemMetaDialog` | Two-stage course card/slides/items authoring; writes through `course_database.py` |
| Course persistence | `course_database.py` | SQLite courses/slides/slide_content with JSON item payloads; course asset folders and import manifests |
| Course viewer | `educational_patient_viewer_widget.py::EducationalCourseViewerWidget` | Text, image, media, PDF, Word and external-resource fallback; DICOM has separate folder/reference loading paths |
| Legacy editor/viewer | `course_editor_widget.py`, `slide_editor_widget.py`, `presentation_viewer_widget.py` | Still present, different capabilities; current `on_course_edited` opens the legacy editor |
| Library | `LibraryPage.on_detail_action` | Local catalog flag changes for importing free resources; no network download in this inspected handler |
| Imported packages | `course_importer.py` | DICOM grouping, enrichment, source preservation, materialization and manifests |
| Case of the Day | `case_of_day_widget.py`, `case_of_day_database.py`, `case_media_capture.py`, `case_of_day_viewer_widget.py` | Local packages and non-modal capture; overlay suppression and bounded encoder queue are existing safeguards, not a public de-identification certificate |
| Online Consultation | `online_consultation/`, `modules/cloud_consultation/`, `modules/Identity/` | Separate gated transport/state workflow. Existing export callable stages, de-identifies and returns the package before upload. Actual remote round-trip not exercised. |

The root `WORKSPACE.md` routes website bridges to the separate website project. Its historical statements about endpoint availability are not fresh evidence of the current backend.

## Reproduced and corrected

The owned seam is `ItemMetaDialog` in the redesigned shell. No schema, viewer decoding, download, network, or consultation transport was changed.

| Defect | Root cause | Correction |
|---|---|---|
| Cannot author/reopen teaching text | Type selector omits `text`, although the actual viewer supports it | Add a plain-text teaching field; require nonblank text and retain line breaks |
| Type switch can save an image file as audio/video/PDF | Selector changes its label but retains the previous source payload | Clear source/type-specific state on a user type change; require selecting a new source |
| Imported document/unknown items cannot round-trip | An unrecognized type falls back to the DICOM selection | Preserve imported types and metadata; allow name/description edits without silently converting them |
| Imported DICOM folder confused with clinical study reference | Both used `dicom` as the editor selection key | Use an internal `dicom_reference` selector key, retaining persisted `dicom_study`/`dicom_series` values; preserve imported `dicom` folder payloads |
| Series zero absent from source label | Truthiness check rather than a missing-value check | Display series number zero as a valid value |

Unknown imported content is preserved, not declared playable. Its file replacement control remains disabled until a supported authoring type is chosen. Existing missing-media handling remains the viewer's responsibility.

## Findings requiring separate implementation and acceptance

These are code-review findings, not completed fixes or measured performance results:

- **Editor routing:** `BuildCoursePage.load_course_for_edit` exists but the shell's edit handler opens the older editor. Unification needs unsaved-change, course-switch, metadata-save and compatibility guards before routing all edits into Build Course.
- **Draft/completion semantics:** `_finish_course_setup` accepts course metadata without checking whether slides have useful content. Keep drafts possible, but design a distinct reviewed/readiness result before describing a lesson as complete.
- **Online semantics:** the reviewed Library import sets `is_my_course`, `is_downloaded`, and `content_origin`; it does not establish a transferred remote artifact. A true remote catalog/download workflow needs its actual backend contract, integrity checks, progress/cancellation and failure handling. `visibility` in `outline` is metadata, not proof of publication.
- **GUI work:** `_pick_source` calls synchronous `save_course_asset` (`shutil.copy2`); import handlers also perform synchronous work. Large-file latency was not measured. Any responsiveness fix must join the canonical optimization master plan with an owned `OPT-*` item and use workers with cancellation/retirement tests.
- **Import durability:** course, slide and item functions commit separately. Failure partway through an import can leave a partial draft/assets. Define staging/rollback policy before implementing transaction changes; do not bulk-clean user data.
- **Privacy:** local Case of the Day metadata and captures need a separate public-export review. Hiding corner overlays does not establish removal of burned-in identifiers, audio identity or document metadata. Consultation's default de-identification is a separate boundary and was not changed.

## Reusable skill and authoring conventions

Installed personal skill: `C:/Users/Dr.Alizadeh/.codex/skills/aipacs-education/SKILL.md`.

It contains an implementation map, content contract and `assets/course-template.json` with three synthetic text slides. The existing importer normalizer accepted the template with no warnings; no live import was performed. Content convention: audience, objectives, question, evidence, explanation, take-home points, references/review date. Assessment content does not imply an implemented exam/scoring engine.

Primary technical references checked for the skill:

- [DICOM PS3.15 Annex E](https://dicom.nema.org/Medical/dicom/current/output/chtml/part15/chapter_E.html), especially confidentiality options for pixels/graphics in addition to metadata.
- [W3C WAI audio/video guidance](https://www.w3.org/WAI/media/av/) for captions, descriptions and transcripts.

These inform authoring/privacy practices; no SCORM, xAPI, accessibility certification or regulatory-conformance claim is made.

## Verification evidence

- Before production edits: `test_build_course_items.py` produced **9 failed, 6 passed**, process exit **1**. Failures cover missing text, stale source state and imported-type round trips.
- A further imported-DICOM-folder guard failed after the initial correction: **1 failed, 15 passed**, exit **1**; then the selector distinction was corrected.
- Final targeted guards: **19 passed**, exit **0**. Real Qt dialog/signal behavior is exercised with synthetic payloads. The persistence-to-viewer text check uses the repository's isolated database fixture and the actual `_show_text` implementation with Qt text rendering. Class/method extraction avoids workstation startup; it is not a live GUI pass.
- Initial adjacent selection: **168 passed, 1 xfailed**, exit **0** in Education, Education consultation and plugin registry. The xfail is the existing quarantined recorder backpressure test; it is not counted as a pass. Final rerun evidence is recorded below.
- Final adjacent selection after the DICOM-folder and storage/viewer guards: **172 passed, 1 xfailed, 3 deprecation warnings**, exit **0** in 19.43 seconds. Command: `.venv/Scripts/python.exe -m pytest -p no:debugging tests/code/education tests/code/education_online_consultation tests/code/builder/test_plugin_package_registry.py -q --tb=short --reruns 0`, with `QT_QPA_PLATFORM=offscreen` and `PYTHONPATH=.`.
- Final mirror verifier: **486 pairs match, zero plugin-only files**, exit **0**. Scoped `git diff --check` produced no whitespace errors. The existing quarantine and SWIG deprecation warnings are not fixed by this slice.
- Skill validator: **valid**, using the bundled dependency Python. Runtime/build Python lack PyYAML; no project dependency was changed.
- Source control bridge `client.py ping`: exit **1**, local endpoint unavailable (`QLocalSocket::connectToServer: Invalid name`). No `list_actions` or live workflow could follow. Human source launch/sign-in was requested; **live GUI acceptance remains blocked**, not passed.

Required fresh-source acceptance: Build Course -> create synthetic lesson -> add text -> save -> open the actual course viewer -> verify text/line breaks -> reopen item -> change an image to video and confirm source reselection is required -> cancel without changing the saved item. Check existing image/PDF/audio/DICOM selection and source session health. Do not use patient content for this test.

## Backup, packaging and rollback

Pre-edit source, payload and documentation snapshots with SHA-256 manifest:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-20260929-075604`.
Only code/docs were backed up; no patient database or asset archive was copied.

The mirror tool dry run identified only the owned Education file. Scoped `add_paths` copied that file to its existing payload. The package definition uses `source_tree` for `modules/education`; no new runtime module, flag or registration was introduced.

Final SHA-256 evidence:
- Source and its Education payload: `4d81e1a13abd22f9053cd6f0ff5eed169e1b76d9c32d6f8c16f4d663a218db73`.
- New guard file: `3e3adaf84205086a689d79e3aead6ab13669c6e64a24a4f2677023ab6d912fff`.

| Build target | Source applicability | PyInstaller / Nuitka artifact acceptance |
|---|---|---|
| Standard Client | Shared Education source/payload | Pending separately authorized candidate build and acceptance |
| ARM64-emulated Client | Same Python source/payload; no native change | Pending separately authorized candidate build and acceptance |
| Eagle Eye Server GUI | Same Education source if installed/enabled; headless service N/A | Pending separately authorized candidate build and acceptance |

No version bump, build, commit, push or installation was performed. Existing unrelated dirty changes were preserved. To roll back, compare current files to the backup first and remove only this dialog change plus its owned mirror; do not overwrite later edits or revert the pre-existing Education search changes. Keep evidence records when reverting a runtime fix.


## Compact Build Course workspace (2026-09-29)

The user-provided screenshot showed excessive vertical chrome above slide editing.
The title and stage indicators now share one compact row, the repeated explanatory
sentence is available as a title tooltip, and save status remains visible in a
footer. Outer margins and stage padding are reduced. Course metadata retains its
own wrapping row so narrow windows do not squeeze it between action buttons.
The slide editor and item list receive the reclaimed vertical space.

The geometry regression failed before the change at both 1180x800 and 1024x700:
slide editing began 233px below the page top. Both now pass a maximum 160px header
budget, at least 70% editor height, and visible-button containment checks.
Synthetic offscreen rendering with Segoe UI at 1180x800 places the editor at y=128
with 639px height. This is layout evidence, not live application acceptance.

Verification: 198 passed, 1 existing quarantined xfailed, 3 SWIG warnings; direct
pytest process exit 0 across Education, consultation, and plugin registry guards.
The documented control client ping still fails because the local source test
endpoint is unavailable; fresh source GUI acceptance remains pending.
Backup and synthetic preview:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-layout-20260929-085559`.
No installer build, installation, or release was performed.

Updated source SHA-256: `13cb4da2f0d487e261c5bfb16569ed8aed7ca1028ed30031d15d9549fd8e928d`.


## Portable local Education transfer (2026-09-29)

Education's header now opens **Transfer Education**. Export selects all saved
courses/resources, all local Cases of the Day, or both, into one `.aipacs-edu`
ZIP64 package. On the destination, Import Package adds new rows and rewrites media
references into its own `EDUCATION_DIR/transfers/package_<uuid>` tree. Existing
content is never updated or replaced. Unsaved editor changes must be saved first.

Included: course/card metadata, downloaded flags and resource types (including
books/videos), ordered slides/content, covers, referenced media, whole managed
course asset trees (including archived originals), case DICOM packages and sibling
screenshots, videos, attachments, cards and notes. Local study/series references
become folder-backed DICOM items with their study/series identity preserved, so
course playback does not require the source computer's PACS database.

The package is a private transfer, not a publication or de-identification format:
original patient information and file contents remain intact; no encryption is
claimed. Online Consultation packages and cloud request/account state use separate
clinical/cloud workflows and are not included. No network operation occurs.

### Integrity and persistence contract

- `portable_transfer.py` snapshots Education tables, copies files in chunks on a
  worker, detects source changes, records SHA-256/size for each asset, and atomically
  replaces the chosen output only after completion. Missing referenced files fail
  the export rather than silently producing an incomplete package.
- Import rejects traversal/Windows unsafe names, duplicate ZIP names, external
  media references, missing members and checksum failures. It checks free space,
  stages verified assets, allocates fresh row identities, and commits all imported
  records in one transaction. Failure/cancellation rolls back rows and removes only
  newly allocated staging/published directories belonging to that operation.
- The additive Education-owned table `education_portable_imports` is created
  transactionally on first import. It contains package UUID, manifest fingerprint,
  JSON mappings of imported record keys to archived media trees, and import time.
  The same package is skipped on repeat import; exporting a new package produces a
  new identity. This is additive transfer, not a merge/synchronization or deleted-
  content restoration tool. Receipts retain archived trees for subsequent exports.
- `transfer_dialog.py` owns the worker through completion, keeps I/O off Qt's GUI
  thread, supports cooperative cancellation, and refreshes Library/My Courses/Cases
  only after successful import. Native save-dialog suffix handling preserves the
  overwrite confirmation for the actual output filename.

### Verification and packaging

Tests in `test_portable_transfer.py` cover a clean destination database/storage,
source paths going offline, media and notes round trips, retained downloaded flags,
re-export of archived originals, standalone DICOM references, duplicate import,
checksum/path/schema/reference attacks, rollback after partial SQL insertion,
cancel cleanup, and protecting previous exports. `test_transfer_dialog.py` checks
actual off-GUI execution, post-import refresh and close/cancel worker lifetime.
All fixtures patch the canonical database path and clear the connection pool.
Synthetic dialog rendering was inspected; this is not a live source GUI pass.

The latest direct Education/consultation/package-registry suite passed 212 tests
with 1 pre-existing quarantined xfail and 3 SWIG deprecation warnings (exit 0).
The source test-control bridge remains unavailable (ping exit 1), so real source
GUI acceptance and a physical second-computer trial remain pending. No patient
content was exported during development.

Both helpers live inside the existing Education `source_tree` package; no new
runtime module identity, feature flag, configuration family, installer component
or dependency was added. Mirrors are synchronized through scoped `add_paths`.
No release build, installation, commit or push was performed.

Backup and synthetic UI preview:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-transfer-20260929-091630`.
Rollback must remove only these transfer helpers/header integration and matching
payloads after checking for later edits. Do not remove imported content or receipts
as part of a code rollback, and preserve all earlier authoring/layout work.


Final transfer verification: after save-dialog suffix handling, dialog plus release
parity selection produced 15 passed and 1 failed. The failure is the untouched
existing stage configuration gate: missing staged `eagle_eye_client.json` and stale
sanitized expectations for `echomind_settings.json`, `modality_grid.json`, and
`printing_config.json`. This is not an installer acceptance pass; no generated
stage was modified. Mirror verification separately passed: 490 pairs match,
zero plugin-only files. The 212-test Education selection above remains the runtime
code evidence; the final changed dialog's focused tests also passed.

Transfer source/payload SHA-256 values:
- `portable_transfer.py`: `b6ece6d30296d61dce8a63bb37ca5011dcfcae4aa65ee51bcc825f57d189934a`.
- `transfer_dialog.py`: `a0d591bdb773f5a47f08f04fa88c67ad9d4ddc1a973a659cc88dfd0d32dcae09`.
- `education_module_redesigned.py`: `a946bb7e808c4c3c11dc3c9314dadb518cd4862c865f29654cceb2cbb7de4e0b`.


## Settings transfer entry points (2026-09-29)

Settings > Consultation & Education now starts with a Local Education - Export /
Import section. Separate buttons open the shared transfer dialog in export/import
mode; import mode hides export-category controls. Local transfer checks the installed
Education module, without requiring a cloud sign-in. Successful Settings imports
refresh an already-open Education workspace without loading its viewer unnecessarily.
The Education header entry point remains available.

Verification: 44 passed, exit 0 across consultation/education Settings, transfer
UI and portable transfer tests. New button-click tests cover selected-mode routing
and disabled-module handling; real Qt tests check mode-specific visible controls.
Settings is main application source, not an Education payload mirror; the shared
transfer dialog payload was synchronized. No installer build was performed.
Backup: `C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-settings-transfer-20260929`.
Live source GUI acceptance remains pending availability of the test-control endpoint.


## Single-row item actions and DICOM sources (2026-09-29)

Build Course item actions now share one horizontal row. DICOM Image Set offers
Patient ID / Study selection and Choose DICOM Folder; the dialog also accepts a
single local folder URL dropped anywhere that propagates to the dialog. Invalid,
remote or multiple URLs are rejected; folder validation/copy runs on a worker.

The study picker now constructs correctly (missing QWidget import fixed), defaults
to exact Patient ID matching, offers All fields search, and clears hidden/stale
selections on filter changes. Database reads run on retained QThreads; late series
results are generation-checked and dialog close waits for queries to retire.

Folder import reads per-instance Study/Series/SOP identity and copies original
bytes into the existing numeric-series educational layout without decoding or
changing transfer syntax. Extensionless Part 10 files are accepted. Multiple studies,
conflicting Series Numbers, invalid identities or empty/unreadable DICOM folders
produce an explicit error instead of merging studies. Choose a single-study folder;
this does not add a general multi-study folder browser or new rendering support.
Replacing a system reference with a folder removes the old patient/series linkage.
Cancellation retains the worker; a completed cancelled copy may leave an unused
course asset tree, as with the existing item-copy flow.

Before fixes, two guards failed: picker construction raised NameError and actions
occupied two rows. Final broad selection: 222 passed, 1 existing quarantined xfailed,
3 SWIG warnings, exit 0. Tests cover exact ID filtering, off-GUI database reads,
synthetic Qt URL drop dispatch, source replacement, raw-byte preservation,
extensionless files, numeric-series layout and mixed-study/series rejection.
These are automated/offscreen checks, not native OLE drag or DICOM rendering
acceptance. Test-control ping still fails; live source GUI acceptance remains pending.

New folder-import helper stays within the existing Education source-tree payload;
no feature flag, dependency, runtime module identity or installer component added.
Backup: `C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-dicom-picker-20260929-095513`.
No build, install or release performed.


## Downloaded course edit permissions (2026-09-29)

User decision: downloaded courses/resources are editable unless the exporter
explicitly disables editing. The former `is_downloaded` edit gate is removed.
An additive `courses.is_editable INTEGER NOT NULL DEFAULT 1` schema migration
makes existing downloaded records editable on source application startup without
changing their download status or needing a new download. No live database was
modified during development; tests use isolated storage.

Export now has an enabled-by-default "Allow editing exported courses and learning
resources" checkbox. Disabling it sets the exported copy to read-only without
locking the original. Existing explicit locks survive re-export. Transfer format
version 2 ensures older importers reject the new contract; the new importer still
accepts version 1 packages, whose absent permission field defaults to editable.
This permission applies to courses and learning resources, not Case of the Day.
It is application-level behavior, not encryption or tamper-resistant DRM.

Build Course and the legacy editor respect explicit locks, and database mutation
helpers guard course metadata, slides/items and reorder operations. Local library
bookkeeping and deleting an entire local course remain available. Imported content
is inserted transactionally through the existing portable import path.

Verification: the old downloaded-edit guard failed before the gate change; updated
broad selection passed 225 tests with 1 existing quarantined xfail and 3 SWIG warnings
(exit 0). Added tests cover default/legacy editable imports, locked export with an
unchanged original, all nine mutation routes, retained restriction on re-export,
and editor refusal for explicitly locked content. A further focused suite includes
a pre-column database migration test preserving downloaded status while enabling edits.
Live test-control ping remains unavailable; fresh source GUI acceptance is pending.
Backup: `C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-editability-20260929-100400`.
The schema is main application source; all five changed Education payload files are
synchronized. No installer build, install, release or live-data update performed.


## Authoring thumbnails and educational patient names (2026-09-29)

Build Course slide and item lists now show 96x64 previews in compact 76px rows.
A slide uses its first visual item (or first text item); image/DICOM items show
actual previews and other types receive labeled badges. `authoring_thumbnails.py`
uses two background workers, detached request data, cancellation/generation checks,
and QImage-only worker output; QPixmap creation stays on the GUI thread. Existing
patient series PNGs are read through ThumbnailImageSourceService without modifying
shared caches. When no PNG exists, a local preview-only pydicom adapter renders one
frame, capped at 32 MiB estimated decoded data and 64 MiB source size. Unsupported,
missing or oversized media retain a type badge. No diagnostic-rendering claim is
made, and no Fast/Advanced/VTK viewer internals or clinical cache writers changed.

DICOM authoring exposes Change patient name in the educational copy, a replacement
Family^Given name, and Keep Patient ID for future lookup (default on). Both a local
folder and a system-selected study/series use the same copy worker when a name
change is requested. Save also applies options selected after choosing the source.
The worker rewrites PatientName/OtherPatientNames in the copied dataset, normalizes
text encoding to UTF-8, and optionally replaces patient-ID fields with one generated
educational ID per import. Study/Series/SOP UIDs and original pixel encoding remain.
Source files are never rewritten. The copy marks `patient_name_changed` so authoring
previews do not reuse a potentially name-bearing original thumbnail.

This is explicitly name replacement, not full de-identification: image/pixel labels,
private tags and other identifiers may remain. The UI states this boundary. No
clinical files or names were used in development or copied into test artifacts.

Verification: 231 passed, 1 existing quarantined xfailed, 3 SWIG warnings, exit 0
in the broad Education/consultation/package-registry selection. A further focused
UI test passed for name options chosen after selecting a source. Synthetic guards
verify source-byte preservation, copied patient name, preserved or replaced ID,
unchanged pixel bytes and transfer syntax, real image/DICOM preview output,
asynchronous icon delivery and stale-generation rejection. The offscreen preview
was rendered and inspected with synthetic pixels; it is not live application
acceptance. The documented control bridge remains unavailable (ping exit 1).

Backup and inspected preview:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-thumbnails-name-20260929-101135`.
The helper is inside the existing Education source-tree package, with no new
runtime module identity, flag, dependency or installer component. No build or
installation was performed. Fresh source GUI/media and physical drag acceptance
remain pending.


## Responsive slide/title layout (2026-09-29)

The user's screenshot showed truncated slide titles beside a disproportionately
wide item editor. The fixed 370px slide-panel ceiling is removed. A non-collapsible
horizontal splitter starts with roughly 35% of available width for slides, and
users can resize both panes. Minimum widths keep action controls usable.
`authoring_list.py` wraps full titles beside 96px thumbnails and computes row
height from the actual viewport width, including long unbroken words. Both lists
retain native selection, focus, keyboard behavior and icons. The thumbnail loader
no longer forces a fixed row height that would clip wrapped text.

The wide-layout guard failed before correction (311px slide panel at 1860px page
width). Final selection: 234 passed, 1 existing quarantined xfailed, 3 SWIG warnings,
exit 0. New guards cover wide-screen allocation, disabled elision and increased
row height after narrowing a column. A 1500x800 synthetic screenshot with long
labels was visually inspected; complete titles wrap in the available space.
The local test-control endpoint is still unavailable, so this is not a live source
acceptance claim. Backup and preview:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-list-layout-20260929-102416`.
The new helper is covered by the existing Education source-tree package; no new
runtime identity or flag. Owned mirrors synchronized; no installer/build performed.


## Dense authoring workspace (2026-09-29)

Slide Name and Save Slide Metadata now share the left metadata column, beside
Slide Description. Course actions occupy the title/stage row; the course summary
has its own compact row. Slide Items use a left-to-right two-column grid when the
viewport is at least 700px wide, reverting to one column below that width. Complete
wrapped titles, thumbnail selection and item ordering remain intact. Grid sizing
reserves space for scrollbar/layout margins to avoid Qt wrapping every card into
one column. Selection survives resizing.

The new grid geometry guard exposed the intermediate one-column layout before
correction. Guards verify actual item rectangles, five items fitting in three rows,
narrow-window reflow, retained selection, side-by-side metadata and compact header.
Final automated selection: 236 passed, 1 existing quarantined xfailed, 3 SWIG
warnings, exit 0. All 493 source/mirror pairs match. A synthetic 1500x800 Qt render
was visually inspected; it shows five items without scrolling. Backup and preview:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-dense-layout-20260929-104409`.
Fresh live GUI acceptance remains pending: the documented local control ping failed
with an unavailable local socket. No installed app, build or release was started.


## Authoring visual hierarchy (2026-09-29)

Added a full-width 4px blue divider between course metadata and the slide workspace.
Item ordering prefixes use bold text at 150% of the surrounding font size, including
pixel-sized fonts. QTextLayout measures the emphasized prefix together with wrapped
titles, preserving original accessible text and selection colors.
Two new regression guards failed before implementation. Final focused authoring and
package-registry selection: 26 passed, exit 0; 493 mirror pairs match. Synthetic Qt
preview visually inspected at 1500x800. Live control ping remains unavailable;
fresh source GUI acceptance is pending. Backup and preview are in
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-hierarchy-20260929`.


## Case of the Day display modes (2026-09-29)

Local case results now offer Large cards (existing 320x290), Small cards (240x170),
and List (full-width 96px rows) through the results-header selector. The selected
mode remains active during search/refresh and while the page remains alive; it is
not a persisted application preference. Card columns adapt to viewport width,
reflowing existing widgets without additional database reads. Switching modes uses
the current filtered results, immediately hides retired widgets and preserves the
case_pk open signal. Cards support Enter/Space as well as mouse input. The Server
tab remains its existing placeholder; no server catalog or transport was added.

Verification: 32 passed, 1 pre-existing quarantined xfailed, exit 0 (new mode,
resize/filter/empty-state/open-identity guards, media capture and package registry).
Synthetic Small/List renders inspected. All 493 mirror pairs match. Source-control
ping is unavailable; live GUI and produced-installer acceptance remain pending.
No build or installed executable was launched. Backup and synthetic renders:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/case-view-modes-20260929`.


## Text files and PowerPoint previews (2026-09-29)

Root cause: inline text read only content_data.text, ignoring file-backed text;
presentation attachments always offered external opening. Viewer dispatch now
recognizes text and presentation suffixes before legacy stored types/placeholders.
Text reads run on a worker, support UTF-8/BOM and UTF-16/BOM (system encoding
fallback), reject binary NUL content and limit preview reads to 2 MiB with a visible
truncation notice. HTML is escaped by the existing notes view. File-backed text
passes preflight when its local source exists.

PowerPoint/Impress conversion runs off the GUI thread using local LibreOffice,
an isolated profile with macro security set to Very High, hidden subprocesses,
a 120-second timeout and 512 MiB source limit. Conversion outputs are static PDFs
under education/presentation_previews, keyed by the file SHA-256. Sources are not
modified. PPX is accepted only when its ZIP structure identifies a PPTX. PPT/PPTX,
PPS/PPSX, PPTM/PPSM and ODP route to conversion; unknown formats retain the external
fallback. Failures have explicit messages and an original-file action. Cached PDF
output is not a portable course asset; another computer needs LibreOffice to
regenerate it. The original presentation remains available for animation/video.
Queued results check item generation and closing state before changing the view.

With explicit user approval, winget installed TheDocumentFoundation.LibreOffice
26.8.0.3, verifying the installer hash. Installation exited 0; Windows Installer
requested a deferred system restart. No reboot performed. Engine --version passed.
A real synthetic three-slide PPTX converted successfully; QPdfDocument verified
three pages and slide-two text, and its rendered page was visually inspected.
No patient assets were used. This is real converter/PDF evidence, not a live
workstation GUI acceptance pass: the control endpoint remains unavailable.

Automated Education/consultation/package-registry selection: 245 passed, 1 existing
quarantined xfailed, 3 SWIG warnings, exit 0. An additional cache/content-invalidation
guard and final text changes then passed the focused 34-test selection. New helpers
are in the existing Education source-tree package, with no new module identity or
feature flag. Owned mirrors match; a later global verifier found two concurrent
EchoMind drifts outside this task (remote_backend.py and viewer_chat/ai_chat_pages.py).
No release/build was performed. Backup, synthetic source, PDF and rendered evidence:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-documents-20260929`.
Next artifact acceptance: install LibreOffice on the destination, open a real course,
verify fonts/layout and page navigation, then switch away during conversion.


## Standalone Education DICOM activation / OPT-61 (2026-09-29)

Reported: course folder resources show a failed-series message and empty rail.
Read-only inspection confirmed local files and matching study/series identities;
the requested series contained 21 instances in one SeriesInstanceUID. First/last
instances decoded to 256x256 arrays. No clinical images or identifiers were exported.
The logged SeriesRef derived-path mismatch was investigated and excluded as a direct
cause: the loader deliberately does not apply non-authoritative derived paths.

The controller starts with _tab_active=False and rejects synchronous loads before
its decode path unless activated or explicitly interactive. The standalone Education
host never forwarded the patient-tab lifecycle, and preloaded synchronously before
calling change_series_on_viewer, making a False return terminate the workflow.
Education now forwards show/hide activation to its existing patient controller.
Folder resources activate that controller, reveal/build their viewport and call
the normal asynchronous interactive series switch directly. Clinical viewer decoding
and identity internals are unchanged. Opening a folder no longer calls the legacy
random-identifier rewriting routine; source files remain untouched by this route.

The new guard failed before correction on the direct synchronous preload. Final
navigation, lifecycle, presenter, document and builder-registry selection: 23 passed,
exit 0. A real Qt show/hide/show guard verifies lifecycle forwarding. All 495 source/
mirror pairs match. Live control ping remains unavailable: actual Fast Viewer pixels,
rail counts, repeated course-study switching and produced-artifact acceptance remain
pending. No installed executable or second app was launched. Backup:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-dicom-activation-20260929`.


## Education rail revisit ownership (2026-09-29)

The user observed six-series count with an empty rail after returning to a DICOM
slide. This is a local Education adapter defect at the shared thumbnail contract,
not evidence of a new decoder or global catalog failure. The fix 1 thread's latest
thumbnail convergence/completeness work was compared with current source. Education
manually deleted grid widgets without retiring ThumbnailManager registrations and
its asynchronous build generation. The shared scheduler then saw retained entries
for cards Education had scheduled for deletion.

Correction stays in Education: retain live cards for the same study/path identity;
on identity change, invalidate/cancel the previous sidebar build, call the existing
ThumbnailManager.reset_all_states(), then retire grid widgets and reuse the shared
show_exist_thumbnails/scheduler path. Failed/empty settled builds may retry. No new
thumbnail loader/cache/renderer, shared-trunk edits or viewer-domain edits were made.

A real Qt/qasync test using the production shared scheduler and ThumbnailManager
failed before the fix with deleted/detached cards on revisit. Final integration
covers A-to-A retention, A-to-B-to-A replacement (same numeric series keys), live
card membership and six-card completeness. Adjacent selection: 49 passed; final
extended revisit/navigation selection: 10 passed, exit 0. Existing SWIG warnings.
495 mirrors match. Fresh live control ping still fails; user screenshot confirms
prior DICOM visibility but is not acceptance of this new rail fix. No new source
instance or installed app was launched. Backup:
`C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-rail-revisit-20260929`.


### Presenter header, collapsible browser and video recovery (2026-09-29)

The content header now displays the course author_name as Presenter on its right;
no separate presenter profile is available in the current course schema. The footer
has Hide slides / Show slides, retaining navigation controls and list selections
while reclaiming the slides/resources body height for the content viewport.

A video failure previously replaced and deleted the persistent QVideoWidget,
breaking subsequent resource playback. Keep its sink alive, pause on error and
reuse one plain-text error label. Loading the next valid video restores the same
surface. The regression failed before correction (sink missing from layout).
Three new Qt guards cover viewport height/selection, repeated errors, and actual
synthetic MJPEG frames after a missing file, pause and error/reload.
An initial test harness fault was traced to Mock class attributes on a PySide
QWidget subclass; ordinary no-op methods remove that test-only native failure.
Fresh live control ping is unavailable; offscreen playback is not live workstation
acceptance or proof of every codec/audio device. No application was launched.

Final automated selection: 252 passed, 1 existing quarantined xfail, 6 SWIG
deprecation warnings; pytest exit 0. All 495 source/payload pairs match.

### Case display icon buttons (2026-09-29)

Replaced the view combo with three adjacent exclusive icon buttons: single card,
four-card grid and list. Tooltips and accessible names identify each mode; checked
state remains visible. Existing Qt checks updated to click buttons and verify
exclusive selection, card sizes, filtering and case opening: 2 passed. Live
source GUI acceptance remains pending local test-control connectivity.


### Slide covers and readable document tiles (2026-09-29)

Build Course provides Thumbnail... and Automatic actions per slide. An owned worker
validates and normalizes a selected image to a bounded PNG in the course asset
store, then saves slides.thumbnail_path. The idempotent startup migration preserves
old slides. Covers take priority over automatic content previews; missing covers
fall back to content. Text and attachments now use legible document-type tiles
(TEXT, PDF, PPT or extension) instead of squeezed text/Attachment placeholders.
Portable transfer already walks thumbnail_path fields: a synthetic export/import
verified copied assets, rebased paths and preview retention after removing the
original selected image. Reset restores automatic preview without deleting assets
that another reference could retain. No content item slot is consumed by a cover.

Verification: broad Education/consultation/builder selection 255 passed, one
existing quarantined xfail; final cover/migration selection 4 passed. Six existing
SWIG warnings in broad selection. Actual QWidget workflow covers choosing/resetting
and preserving selected slide. Live source GUI remains unverified: local control
ping unavailable. No running app was restarted or live database modified. Startup
migration takes effect on the next normal source launch. Bounded source backup:
C:/Users/Dr.Alizadeh/AppData/Local/AI-PACS/task-backups/education-slide-covers-20260929.


### 2026-10-09 - Shared Secretary/MCP text course authoring (OPT-61)

Eight typed commands prepare, inspect, revise, load, save, check operation status,
open Build Course and preview a local text course. Actual draft handles and optimistic
revisions preserve corrections in the same course. SQLite writes and snapshot reads
run on a bounded worker; an atomic transaction and durable request receipt prevent
partial courses and duplicate successful retries. Existing media and unknown metadata
are retained. External/manual edits and unsaved human editor changes block overwrite.
Initial command editor loading consumes a prepared snapshot without GUI database reads.
Failed UI completion remains failed when polled again.

Planning and course-writing instructions remain in the Eagle Eye Server catalog;
the local shared CommandBus executes validated proposals. MCP advertises the same
registered actions and schemas. The test-control tool redacts authoring bodies from
generic receipts. No client-direct AI route, generated code execution, DICOM import,
patient matching, medical image interpretation or publishing is added by this slice.

Synthetic regression suites: tests/code/education/test_command_authoring.py and
tests/code/echomind/test_course_authoring_commands.py. Initial service guards failed
before implementation because the service did not exist. The first broad verification
passed 277 tests with one pre-existing quarantined xfail; final verification is recorded
in the protected session receipt. Production voice acceptance and source live GUI are
pending: the existing local Test Control Server ping was unavailable. The human has
been asked to launch and sign in to one source TestServer instance outside clinical work.
No running application or active Eagle Eye service is restarted by this work.

Developer backup and synchronization evidence is protected outside the repository at
C:/Users/Dr.Alizadeh/Documents/AI-PACS Courses/ICR41-OCD-Staging/developer-backup-20261009.
Source parity and activation are separate gates; do not infer active deployment from
an updated non-running Developer candidate.


Final session state (2026-10-09): local broad verification passed 294 tests,
with two skipped staged-build checks and one existing quarantined xfail.
After catalog line-ending correction, the focused selection passed 37 tests.
The non-running server candidate initially passed 71 tests and a declared
8,392-file / 14-engine-file audit. Concurrent local Secretary conversation work
then changed service.py and introduced conversation.py while parity was being
verified. A repeated copy exposed the missing conversation dependency on the
candidate. That incidental service copy is backed up and the candidate is restored
to the independently tested course-authoring service overlay; unrelated local work
is preserved. The protected final receipt records the repeated candidate test.

Full two-way Developer parity and build handoff are BLOCKED until the concurrent
Secretary conversation slice and its dependencies/mirrors are reconciled by its
owner. This slice does not claim completed synchronization, live GUI acceptance,
active server catalog deployment or end-to-end spoken-command acceptance.
The global plugin verifier additionally reports three unrelated existing/in-progress
mismatches (memory_store.py, orchestrator.py, remote_planner.py); owned course-authoring
mirrors match. No unrelated payloads are synchronized to resolve that gate.


### 2026-10-09 - Unified Add Item and composed multimedia (OPT-61)

New items expose four choices: Multimedia, PDF, PowerPoint and DICOM Image Set.
Multimedia stores optional formatted teaching text plus one optional image/audio/video
source in a single content_data object. Six layouts (text, media right/left, text
above/below media, media only), three color themes, custom background color, title
position, font family/size, headings, bold/italic, alignment, text color and bullet/
numbered lists are available. Layout changes retain content; clearing media retains
text. Background-image authoring and arbitrary multi-object canvas editing are not
implemented in this slice.

PDF uses the full content width and FitToWidth, with an optional item title above or
below. PowerPoint import uses the existing isolated LibreOffice converter on an owned
QThread, then copies both the original and resulting PDF into managed course assets.
The accepted payload points to the PDF and nests the original under original.path
so existing portable asset traversal retains both. Conversion failure publishes no
payload; the dialog remains editable. This is a static preview, not animation playback.
Legacy individual text/image/audio/video and imported resource types retain their
saved type and metadata when reopened; only the new-item picker is simplified.
DICOM references and folder imports retain the existing separate pipeline.

The current educational viewer composes its existing media stack with a formatted
text region. Formatting is allowlisted; embedded HTML files, images, scripts and links
are not accepted through rich-text paste. Actual media uses managed file selection.
The shared Secretary/MCP course service creates Multimedia for new text items and
updates existing Multimedia text in place, preserving media/layout metadata. A changed
plain-text command clears obsolete rich_text so stale formatting cannot conceal its
correction. Formatting-only commands and media-path transport are not added to the
server action schema by this slice.

Verification: four initial guards failed before implementation. The final local
Education/authoring-command/builder selection passed 218 tests, with two skipped
staged-build checks and one existing quarantined xfail. Ten focused new guards passed,
including real Qt composition geometry, the actual viewer dispatch method, rich-text
reopening, worker import failure and retained media under command correction.
All 520 canonical/plugin mirror pairs matched after owned-file synchronization.
A synthetic actual LibreOffice conversion and PDF readback receipt is recorded in the
protected session folder when available. The standalone Qt composition was visually
inspected; this does not replace the required live source acceptance.

Source GUI acceptance remains pending: the documented test-control ping cannot reach
AIPACS_TEST_Dr_Alizadeh. The human has been asked to launch one source TestServer and
sign in outside clinical work; no installed app, clinical service or recording is
restarted. Developer parity and remote verification are tracked separately in
C:/Users/Dr.Alizadeh/Documents/AI-PACS Courses/multimedia-backup-20261009.
No installer/build acceptance is claimed.


Multimedia final Developer evidence: the previously selected Developer source is now
executing, so it was not modified. A separate non-activated Education candidate was
staged from its current verified source inventory plus the owned delta. Both sides
matched 8,398 declared source files and 14 required engine assets before the final
document-receipt update. The server feature suite passed 206 tests with one existing
quarantined xfail; the two owned plugin/file-set guards passed. The broader server
selection had four config-template failures, 213 passes, three skips and one xfail:
config/ was intentionally excluded to preserve host-private runtime state, so those
release-template checks cannot qualify this isolated candidate for a build. Source
parity excludes host config, identities, databases, logs and the shared interpreter
environment; it does not assert installer/config-template readiness.

Actual LibreOffice conversion of a one-slide synthetic presentation passed, including
PDF text/page readback and retention of the original file. Actual Qt dialog and
composition captures were inspected with an explicitly loaded font because the
standalone offscreen platform has no default system-font inventory. This is synthetic
rendering evidence, not the pending live source application gate. The final acceptance
state remains: code and owned payloads verified; Developer snapshot parity recorded;
active server unchanged; live Client workflow and build handoff pending.


### 2026-10-09 - Compact teaching viewport and audience display (OPT-61)

The instructor photograph exposed UTF-8 mojibake in Review, navigation and zoom
labels, plus three redundant title/header rows above composed teaching content.
Review/navigation controls now use ASCII labels, secondary Review buttons have
subdued contrast, and duplicate content/presenter/media headings no longer reserve
viewport height. The slide's authored title remains visible. Existing slide/resource
selection and collapse behavior are preserved.

Present moves the existing composed media surface into a full-screen audience
window on the first other screen (or the current screen when only one is present).
It does not create another player, PDF decoder, course database or clinical viewer.
The workstation retains slide/resource selection, reviews, timer and media toolbar;
Escape, End presentation, output-screen removal and owner close restore the surface.
Arrow/Page keys use the existing slide navigation. DICOM is deliberately retained
in its original execution domain; selecting it blanks previous audience media and
displays an explicit workstation-viewer message. DICOM audience output is not
implemented or qualified by this change.

Four targeted guards failed before production edits. The Education suite passed
199 tests with one pre-existing quarantined xfail and six SWIG warnings. Following
final parent/keyboard cleanup, the focused presenter/navigation/multimedia/builder
selection passed 35 tests, with one staged-build skip and three deselections.
Synthetic Qt rendering and restoration are separate from real two-monitor/source
application acceptance. The documented local control bridge and live GUI result,
Developer source parity, activation and packaging are recorded separately below.
No installer or build is produced. Protected exact-file backups are under
C:/Users/Dr.Alizadeh/Documents/AI-PACS Courses/presenter-ui-backup-20261009.

Final presenter follow-up: a fifth regression demonstrated that the workstation's
broad QWidget theme painted the composed content host black despite its selected
background. Host/title backgrounds are now transparent; the corrected pixel guard
fails against the protected baseline and passes against the current surface.
Actual Qt layout captures were inspected for compact controls, authored color,
original Radiopaedia image and content-only audience rendering. These captures
use a synthetic host, not the live clinical application. The final combined local
Education/course-command/session-source selection passed 220 tests with one existing
quarantined xfail and six SWIG warnings. The current Test Control ping is unavailable
(AIPACS_TEST_Dr_Alizadeh has no listener); live source and physical-display acceptance
remain pending. No source GUI or service was restarted for this slice.

The final theme guard captures the containing workstation, not only the child
widget: QWidget.grab() can paint a child background even when normal ancestor
painting does not. WA_StyledBackground plus transparent host/title now preserves
the selected color in the actual containing-window capture. The containing-window
guard failed before that final attribute and passes afterward.

### Presenter identity and composed text sizing (2026-10-09, OPT-61)

Presenter identity now occupies the Items heading, with plain text and wrapping. Multimedia exposes A-/A+ beside image controls; text and title scale together within bounded view-only limits, preserving rich formatting and relative sizes. Each slide starts at its authored size. Image zoom and saved course payloads remain independent. Two failing-before guards reproduced hidden identity and missing composed zoom. Live source GUI acceptance remains pending.

### Readable Items browser (2026-10-09, OPT-61)

The fixed 432px Items column left most width unused in Resources. A non-collapsible horizontal splitter now allocates 60% to Items by default and permits manual resizing. Items use 16px type, wrapped titles and taller rows; section headings use 14px. Expanded dock height is 240-280px; hiding slides still restores content space. Resources retain drag, selection, wrapping and scrolling with no new count restriction. The actual-layout guard failed before the change (420px Items versus 984px Resources) and passes at 1500px and 1050px owner widths. Live source GUI acceptance remains pending; Test Control Server is unavailable. Both Client/Server Education payload inputs are synchronized; no installer produced.

### Image zoom rendering (2026-10-09, OPT-61)

The QGraphicsPixmapItem defaulted to FastTransformation despite the enclosing view smooth-pixmap render hint. Explicit SmoothTransformation now interpolates visible pixels from the unchanged original pixmap. FullViewportUpdate redraws the small teaching-image surface after transform/pan, avoiding dependence on partial dirty rectangles. Scene bounds use the item logical rectangle, respecting device pixel ratio. Fit retains aspect ratio and full image; zoomed content outside the viewport remains accessible by pan/scroll. Synthetic pixel guards cover interpolation through zoom cycles, unchanged source pixels, high-DPI bounds and pan-visible regions. The interpolation guard failed before the fix. Source GUI acceptance remains pending. No changes to DICOM rendering domains or image assets.

### Responsive numbered slide cards (2026-10-09, OPT-61)

Replace long full-width Items rows with numbered cards in two columns when the Items pane has at least 600px usable width, otherwise one column. Cards use 18px wrapped titles and 32px number badges, 88px grid rows, static ordering and full-title tooltips. The small SlideSelector widget owns resize/layout behavior; the course viewer retains selection/navigation. Resources and content rendering remain unchanged. The actual-footer two-column guard failed before the change; synthetic selector guards cover wide/narrow reflow, actual mouse selection, unchanged order and scrolling. Visually inspected the actual layout render. Live source GUI remains pending because the documented test bridge is unavailable. Client/Server build inputs synchronized, no installer produced.

### Scoped media arrow navigation (2026-10-09, OPT-61)

Add an owner-scoped Qt event filter for unmodified arrows while the Education media page is active. Left/Right select previous/next slides; Up/Down select and open previous/next resources through the existing item-dispatch generation guard. Boundaries do not wrap or reload. ShortcutOverride prevents duplicate/conflicting child shortcuts, including the audience window. DICOM page and selected DICOM payloads bypass interception, including the deferred-switch interval. Editable fields, modifiers, modal dialogs and popups retain their keys; unrelated windows are outside scope. The QObject is viewer-owned and removed with it. Synthetic real-key tests cover routing, boundaries, resource dispatch, modified keys, field editing, audience shortcut precedence, and DICOM cursor-key pass-through. Initial guard failed before implementation; source GUI acceptance pending (documented control bridge unavailable). No clinical viewer key handlers changed. Client/Server Education payload inputs synchronized; no installer produced.

### Course content cleanup and uncropped covers (2026-10-09, OPT-61)

User-authorized maintenance reviewed 14 local courses. The private transaction converted 11 legacy text resources to multimedia, retained original payloads in metadata, preserved an archive as an accessible attachment, normalized resource order in 52 slides and split eight oversized resource groups into continuation slides. Two incomplete wrist courses received draft title items and covers only; no clinical findings or cases were invented. All 195 resulting slides have readable thumbnails; 186 new slide thumbnails include 168 from existing imaging/media and 18 conceptual anatomy previews. Existing case/image/DICOM payloads and original files were preserved. Backups, planned/readback inventories and receipts remain outside source in the protected course-maintenance directory. No patient material is copied into Developer synchronization.

ModernCourseCard used KeepAspectRatioByExpanding in a 168px square and left-aligned the box. Legacy CourseCardWidget also expanded images into a shorter region shared with badges, causing clipping. Both cards now contain the full image; the modern card is centered with an inset for its border, and the legacy image region is bounded to the actual space above badges. Build Course cover previews also preserve aspect ratio. Four wide/portrait Qt card guards failed before the fit change, and two centering guards failed before the alignment change. Actual saved conceptual course covers were rendered offscreen to inspect the fit; this is not live GUI acceptance.

Source GUI acceptance remains pending: documented control client ping returned QLocalSocket Invalid name. Concurrent server-console Developer differences were observed outside Education; the protected parity receipt distinguishes owned Education hashes from unresolved whole-snapshot parity and blocks build handoff while reconciliation is pending. No service restart or installer build was performed.


### Education selection clearing (2026-10-09)

OPT-61: Slide/resource navigation now retires the previous thumbnail build and DICOM load requests, clears the study rail and identity, and uses the existing viewer teardown before displaying new content. Empty resources and empty courses invalidate pending media callbacks and show an empty presentation message. Stored course content and DICOM files are unchanged. The empty-resource regression failed before the fix; focused navigation guards pass. Source GUI acceptance is pending because the local test-control socket is unavailable. Full Developer parity and build handoff remain blocked by the previously recorded concurrent server-console deltas; no service was activated.


### Responsive Education filters (2026-10-10)

OPT-61: Library and downloaded-course filter sidebars previously constrained two columns to 300 pixels without scrolling. The fail-before geometry guard found 126-pixel controls requiring 208 pixels for their full labels. The shared FilterPanel now uses a resizable scroll viewport, preserves checkbox/group minimum geometry, and selects one or two columns from current label size hints and available viewport width. Short windows scroll rather than compress rows. Clear Filters can grow vertically with font metrics. Synthetic geometry checks cover heights 400/650/900, widths 260/300/440 and 12/18-point text; selection and clearing survive reflow. No database or clinical viewer changes. Live source GUI acceptance remains pending: the documented test-control socket is unavailable. No installed executable, service activation or release build was used. Complete Developer parity remains blocked by concurrent source deltas; owned source is staged separately with hashes.


### Education lifecycle diagnostics (2026-10-10)

OPT-61: Added normal-operation, PHI-free sidebar lifecycle/worker timings and Education import/page/query/card/event-loop timing. Coordinated with fix 1; no renderer retry or root-cause claim. See [diagnostic contract](EDUCATION_CONTENT_DIAGNOSTICS_2026-10-10.md). Synthetic guards cover cancellation, invalidation, visibility and native destruction. Live source and installed ARM acceptance remain pending.


### OPT-61 - Education lazy tabs (2026-10-10)

The owner separated click-to-open Education delay from DICOM. The shell now creates lightweight slots; only the selected page is built on demand, with retained state and real-widget compatibility for Secretary and deep links. Import refresh touches loaded pages only. Six shell guards and a Settings refresh guard failed before implementation; twelve synthetic cases cover lifecycle, selection, retry and availability. See [scope and evidence](EDUCATION_LAZY_TABS_2026-10-10.md). Live source/installed ARM and complete Developer reconciliation remain pending; no prewarm, activation or release.


### Education workspace layout follow-up (2026-10-10, OPT-61)

Library card columns previously used stale pre-layout viewport dimensions. Reflow now
observes viewport resize and moves existing cards without rebuilding selection state.
Details width can grow from 340 to 540 pixels; course actions live outside the details
scroll area, and cover images fit within 360 by 180 pixels without cropping. Build
Course uses available width up to 1440 pixels and top-aligned form fields instead of
stretching gaps between controls. No course database migration or viewer changes.

Guard: `tests/code/education/test_workspace_layout.py` (three failures before the fix,
three passes after). Full Education suite recorded in the protected layout receipt.
Source GUI control ping unavailable (QLocalSocket invalid name); live GUI acceptance
and installed ARM acceptance remain pending. No installer produced or activated.
Developer/Razi reconciliation remains pending; historical lazy-tab candidate is unchanged.


### Unified course presentation shell (2026-10-10, OPT-61)

The preflight window was 1280x800 before any content existed. It now opens at
640x320 with navigation hidden until the live viewer starts. Library Open Course
uses the same independent viewer shell as Build Course Preview / Present; a clean
preflight starts it automatically, while missing-resource issues remain reviewable.
Present offers single-monitor fullscreen or an explicitly selected audience screen.
The dual-display host moves the existing viewer, retaining the DICOM execution
session, and keeps the Education item/resource footer on the controller. The viewer's
imaging tools remain with the viewer. Closing the audience host or removing its
screen restores the viewer; no duplicate decoding session is created.

Guards in test_presenter_tasks.py: two new failures before implementation; compact
preflight and single-monitor guards pass after, plus audience-host restoration.
Synthetic offscreen checks do not establish physical two-monitor or clinical GUI
acceptance. Source control bridge unavailable; live GUI, physical screen unplug,
Developer/Razi reconciliation and installed ARM acceptance remain pending. No build,
activation or installed executable changes performed.


### OPT-61 Education manual DICOM viewport admission (2026-10-10)

Owner requested no automatic first-series display when selecting an Education DICOM
resource. The course shell now starts without resolving/preloading its first future
DICOM study. Folder, study and explicit-series resources establish the selected
study identity, activate the existing controller, create empty comparison viewports
and populate the full shared thumbnail rail. They no longer call the synchronous
single-series loader or change_series_on_viewer during resource selection. Explicit
series metadata remains stored but does not trigger display; thumbnail selection or
drag uses the unchanged viewer route. Existing selection clearing retires old viewer
requests before building the empty layout, so the prior case cannot remain visible.
Normal workstation patient-open behavior is outside this Education-only change.

Three changed navigation guards failed before the runtime edit; after it, the full
Education suite reports 254 passed and one existing quarantined xfail. Source/payload
mirror verification reports 528 pairs matching. Full series inventory, revisits and
selection-clearing guards remain green. No field latency claim is made. Fresh source
GUI observation and actual mouse/OLE drag, local/Razi Developer parity and installed
artifact acceptance remain pending. No release or remote activation performed.


### OPT-61 Education presentation branding (2026-10-10)

Added the existing AI-PACS SVG logo and AI-PACS wordmark in a compact, right-aligned
footer beneath the resource list. It participates in layout rather than overlaying
resource cards, ignores mouse input, and follows footer collapse and dual-display
controller placement. Existing logo is reused from IMAGES_LOGIN_PATH; no new asset
or network request. Guard verifies logo availability, wordmark, visible placement
below resources, resize, and collapse without losing slide selection. Guard failed
before implementation; 23 presenter/navigation/task checks pass after. Education
source/payload hashes match. Global mirror check observes four unrelated EchoMind
drifts; those were not changed or swept. Synthetic offscreen geometry checked; live
source GUI and full Developer/Razi parity remain pending. No installer/activation.


### 2026-10-11: OPT-61 bounded card work and stable presentation

The initial Library/My Courses path constructed every card and decoded cover files on the GUI thread. Card creation now yields between entries; cover QImage decoding uses the existing two-worker AuthoringThumbnails pool, with GUI-owned QPixmap delivery and cancellation/generation checks. Search/filter semantics are unchanged. A replacement filter cancels the old grid generation.

First live source acceptance showed Library construction at 166 ms versus about 1.5 s previously, but the user reported visibly jumping cards. That timing alone is not a UX pass. The follow-up keeps an opaque, stationary loading surface over the grid while cards and covers settle, then reveals the populated grid together. It tracks resize and covers the scrollbars as well as partial cards. The cover wait has a two-second bound; missing/corrupt covers retain their fixed-size placeholder. No artificial animation, forced repaint, nested event loop, or clinical thumbnail pipeline was added. A 150 ms minimum prevents a loading-label flash on very short builds. Rendering remains incremental behind the surface.

Synthetic identical 14-cover runs measured maximum GUI heartbeat gap about 695 ms before versus 49 ms after the first slice; wall time about 705 versus 422 ms. These are synthetic local measurements, not clinical or installed acceptance. Actual first-slice card maxima reached 165 ms. New stable-presentation acceptance requires a fresh source process; the currently open process predates that follow-up. Guards: `test_card_grid_responsiveness.py`, `test_course_cover_fit.py`. Education mirrors must be synchronized for the next build. Server Developer activation and complete snapshot parity remain separate gates.

Verification update (2026-10-11): combined Education/MPR checks finished with 508 passed and one pre-existing quarantined xfail; final focused checks passed 16/16. Education mirrors verified 531/531. Immutable Razi review delta verified 16/16 hashes, without active-source changes; complete snapshot parity and fresh GUI acceptance remain pending.
