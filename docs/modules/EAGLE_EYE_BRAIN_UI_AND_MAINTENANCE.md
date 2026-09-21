# Eagle Eye Brain UI and maintenance

Current source contract: 2026-09-07. Read this with
[customer delivery](EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md),
[Eagle Eye ownership](EAGLE_EYE_DEVELOPMENT_CONTRACT.md) and
[reference setup](EAGLE_EYE_BRAIN_REFERENCE_SETUP.md).

## User journey and code ownership

1. The open MRI study routes through `AiMainWindow` in `brain_mri` mode.
2. `BrainVolumetryWidget` offers whole-brain analysis and explicit T1 series
   selection. Lesion detection remains unavailable. Selection must match the
   active study; the user confirms coverage and protocol.
3. A background worker calls `study_workflow.run_study_analysis` and `service`:
   DICOM preparation, SynthSeg, isolated Slicer, published references, image
   evidence and PDF. Patient/study ownership is established from DICOM.
4. Completion displays a compact result card, not the full 29-page report HTML.
   It lists measurement count and anatomical coverage. Primary action:
   **Save PDF report...**; secondary actions: **Open PDF report** and
   **Open result folder**. Opening uses the system PDF viewer. Saving runs
   atomically in the worker and preserves the original report in User Data.
5. Starting a new analysis or regeneration clears the old card and disables
   its actions. Export failure preserves the completed result for retry.

Keep expensive report rendering, file access and measurement outside the GUI
thread. The result card reads only the completed in-memory result. Do not render
`report_html` inside the widget or insert the complete report into a tiny browser.
The UI uses Qt widgets and existing application styling; no web runtime or new
third-party dependency is needed. PDF absence disables both PDF actions.

## Report contract

`organized_report.py` is the shared source for the normal service and regenerated
reports. Global volumes precede dedicated white matter, cortical summary,
hemisphere cortex, six cortical groups, CSF, basal ganglia, deep gray matter,
brainstem, cerebellum and medial temporal pages. Right and left are adjacent;
midline structures have single measurements. Headers and numeric cells are
centered; text is left aligned. The reference appendix and scientific sources
remain part of the PDF. Page count can change with coverage; never hardcode it
in the UI. Preserve unavailable references and atlas-analogue qualification.

## Verification and customer acceptance

The full local adult DICOM service run produced 101 posterior and 98 binary
measurements and a 29-page PDF. All page furniture, DICOM identity, visual layout
and atomic export were checked. Private evidence is stored under the Brain
validation directory in User Data, never copied into an installer or fixture.

The updated result card is tested with synthetic completion and visually reviewed
in a separate Qt widget harness. The actual completed DICOM result was also passed through the card and its save
button worker; exported bytes matched the original PDF and save returned to ready.
This is not a new workstation login/session.
Regression coverage lives in `test_eagle_eye_brain_study_workflow.py`;
installed lookup and payload/profile coverage live in the customer-path and
builder tests. Run pytest directly and check its exit code.

Source success is not clean-client certification. Follow `BUILD.md` for packaging,
with the exact portable model, reference hashes and external Slicer worker.
Outstanding delivery gates remain documented in customer delivery: actual asset
redistribution evidence, canonical candidate creation and clean Windows testing
without developer paths, Python, Linux or network access. Test the real chooser,
completion card, external PDF viewer, save/cancel/retry and writable User Data
under a normal user account, including display scaling. Do not mark these gates
passed based on mocked installed-path tests.

## Activity feedback (2026-09-14)

Every background operation starts an indeterminate activity bar and monotonic
elapsed timer: series discovery, analysis, regeneration and export. The current
worker stage remains visible above it. The timer is elapsed duration, not proof
of model progress or an ETA. No percentage is invented. Cancellation displays
that stopping is pending; completion or failure removes the busy animation and
retains the elapsed duration. The existing worker and GUI polling boundaries
remain unchanged. Long model validation can still delay cancellation.

Verification: 23 progress/workflow tests passed; a synthetic Qt widget screenshot
was inspected. Source live acceptance is pending: the documented local control
client could not connect to the Test Control Server. The human must launch/sign
in to one source app with AIPACS_TEST_SERVER=1 before the affected live workflow
can be accepted. Do not equate the isolated widget harness with a live pass.

## Same-study T1 and FLAIR selection (2026-09-14)

Study-bound source rows now open the current study series picker rather than
filesystem dialogs. The picker requires one confirmed primary T1 and optionally
a distinct confirmed 3D FLAIR. Unavailable FLAIR series are not selectable.
The study service re-reads DICOM identity for both inputs, verifies Study and
Series UIDs and existing patient/frame compatibility, and passes FLAIR to the
registration pipeline. Previously this caller discarded FLAIR by passing an
empty string. Standalone unbound developer imports keep file selection.
25 workflow/progress guards passed. Live acceptance remains pending because the
existing Test Control Server was unreachable; no workstation was restarted.

## Multiple T1 design background (superseded by implementation below)

One primary 3D T1 remains the minimum input and the report's measurement source.
A future extension should allow up to two optional same-study T1 consistency
inputs in this same picker, with explicit acquisition/geometry review. Axial,
coronal and sagittal names alone do not establish independent acquisitions.
Inspect ImageType, SourceImageSequence, acquisition metadata and voxel geometry;
unknown provenance must remain unknown. Reformat agreement is sensitivity to
reconstruction, not independent evidence of increased accuracy.

Run the pinned segmentation separately on each accepted volume and retain each
job's geometry, QC and source. Compare like-for-like native labels, absolute
volumes, ICV-normalized volumes and percentage differences against the designated
primary. Register images/labels for boundary overlay review using label-safe
interpolation. Review discordant amygdala, accumbens, thalamic and medial temporal
boundaries. Do not automatically choose whichever result falls inside a normal
range, average normative endpoints, or replace the primary report with a merged
result. Additional processing failures must be explicitly visible. Improvement
requires validation against reviewed boundaries, not agreement alone.

Official SynthSeg documentation describes multiple scans as batch inputs, not
multi-view fusion: https://surfer.nmr.mgh.harvard.edu/fswiki/SynthSeg
FreeSurfer recon-all documents motion correction and averaging of multiple
source acquisitions: https://surfer.nmr.mgh.harvard.edu/fswiki/recon-all
That is a different pipeline and does not validate averaging arbitrary MPR
reconstructions in this SynthSeg implementation. No FreeSurfer dependency or
fusion algorithm was added by this change.

## Multiple T1 implementation and simplified form (2026-09-14)

`multi_t1.run_multi_t1` accepts one primary and at most two supplementary series.
All supplementary study/series identities and existing patient/frame compatibility
are checked before processing. Each series runs the existing pinned single-input
service independently. Progress identifies input N / total. The primary PDF stays
unchanged; a separate `t1-consistency.pdf`, per-input CSVs and JSON audit are saved
alongside it. Signed percent difference is 100 * (other-primary) / primary;
zero or missing denominators yield unavailable. Each input's own ICV denominator
is used. The result card exposes Open T1 comparison PDF. Partial supplementary
failure records incomplete status, preserves completed jobs and publishes no
successful combined result. A repeat with the same primary Series UID is rejected.

No image fusion, cross-series label overlay, acquisition-independence classifier
or correction of segmentation boundaries is implemented. The report explicitly
marks acquisition independence unverified. This is a consistency-review tool;
it does not claim increased accuracy. Each input's QC and Slicer scene remain
available in its own job directory. Selection is limited to three inputs to bound
cost. Processing time grows with input count.

The form shows images, patient details and an emphasized Analyze action. Technical
reference/profile/regeneration controls are collapsed under Advanced options.
Selecting images reads DICOM demographics in a worker, fills visible fields and
waits for explicit Run; it no longer immediately starts segmentation. Recorded
fields are locked; missing fields stay editable. New selection clears stale
visible demographics before reading. FLAIR remains optional registration-only in
this anatomical workflow; MS lesion detection is a different feature.

35 focused automated tests passed. Live workstation gate remains pending because
the local Test Control Server is unavailable. A real two-input service test is
tracked privately under User Data. The initial exploratory test was correctly
rejected because the old folder labels referred to T2 SPACE; actual MPRAGE series
were then discovered from DICOM metadata. An overlong nested validation path also
failed Windows process startup; use the ordinary patient-scoped application root
for this probe. Arbitrary long installation/User Data paths are not certified.


Full service acceptance completed: two actual same-study T1 DICOM inputs ran
through SynthSeg and Slicer independently, producing standard primary/supplementary
PDFs plus a 9-page comparison of 101 region volumes. All comparison pages were
rendered and visually reviewed; running headers and signed percentage arithmetic
passed. The private receipt is in the multi-T1 validation folder under User Data.
This is service acceptance, not a live workstation button-click or three-input
clinical validation. No fusion or anatomical accuracy improvement was demonstrated.


## Function picker after empty entry (2026-09-15)

Opening Eagle Eye before a source image was selected left the controller with
an empty modality. Selecting an MRI inside the workspace did not refresh that
initial snapshot, so Choose Function remained disabled. The controller now
reads the selected workspace viewer metadata at click time, rejects a selected
series belonging to another study, and updates the window/imaging-tab mode.
It does not read DICOM or access the database on the GUI thread. Source-owned
Legion identity is unchanged. A selected but unclassified series does not
inherit a previous brain mode.

Live tracing exposed a second case: the Advanced viewer supplied MR and brain
mode but omitted SeriesInstanceUID. Form selection now accepts the loaded
viewer modality with the same-study check, without requiring that optional
viewer field. Analysis-specific series selection and Legion identity checks
remain separate. The missing-UID regression failed before this correction.
All 32 workspace-entry tests pass, and all 462 plugin mirror pairs match.
Fresh source GUI acceptance passed with AIPACS_TEST_SERVER=1: entering before
series selection, selecting T1 by thumbnail, and pressing Choose Function
enabled both brain options. White-matter Lesions opened its input form and
the same-examination list populated all 20 series, including original T1 and
3D FLAIR. No new segmentation or PDF was generated in this acceptance run;
this pass does not establish WMH normative percentile availability.
# Manual correction slice (2026-09-15)

Result panels offer an isolated interactive Slicer correction session. Original
image/mask files remain unchanged. Save correction in Slicer, then recalculate
in PACS. The worker rejects changed source hashes, mismatched geometry, unknown
labels and overlapping segments. Lesion revisions recompute candidate counts,
volumes and same-study SVD/MS localization; cached reference outputs are cleared.
No exact percentile or clinical sign-off is inferred from a manual edit.

Whole-brain edits create a separately identified binary-volume addendum with
before/after volumes and available original-examination reference intervals.
They do not overwrite SynthSeg posterior estimates or infer cortical thickness.
Longitudinal results need a new comparison after editing individual examinations.

Both launch preparation and recalculation use the existing worker executor.
PACS remains independent of the external Slicer process; a pending worker
prevents duplicate actions in that widget. This functionality does not depend
on AIPACS_TEST_SERVER, which is solely the source test-control connection.
Automated receipt: 67 focused tests passed. Real native Slicer Erase + Save
removed nine voxels from a synthetic 1 mm labelmap; worker recalculation changed
1.728 cm3 to 1.719 cm3 with the original hash preserved. A rendered binary
addendum was inspected. Refreshed PACS result-button acceptance still awaits
human login; source was restarted with AIPACS_TEST_SERVER absent in both launcher
and application environments. No global optimization claim.

Live import found a NumPy bool / VTK type mismatch; segment arrays now use
uint8. Controls use their own nonmodal panel because the custom viewer hides
its status bar. No synthetic test images represent a patient or clinical validation.
