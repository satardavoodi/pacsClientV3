# Eagle Eye development contract

Total Spine amendment (2026-09-17): [Total Spine Alignment](EAGLE_EYE_TOTAL_SPINE_ALIGNMENT.md)
adds a separate coronal/lateral DX/CR function, local ISBI-2020 corner proposals,
manual sagittal/rotation review and private reports. It remains an existing Eagle
Eye/Advanced MPR feature and reuses Alignment's isolated CPU runtime. Clinical and
fresh-source GUI acceptance remain pending; it is not a new installer module.

Alignment amendment (2026-09-14): [Alignment View implementation and evidence](EAGLE_EYE_ALIGNMENT_VIEW.md)
defines local SGR inference, geometry, calibration, manual correction, private
reports and existing Advanced MPR ownership. Live GUI acceptance is separate.

Updated 2026-09-07. Applies to Brain, Lumbar and future anatomy features.

Dataset integration review (2026-09-13): [native dataset workspace proposal](EAGLE_EYE_DATASET_WORKSPACE_DESIGN_2026-09-13.md).
This is a source-reviewed design for modality/anatomy collections, case review and
versioned server export; it is not an implemented runtime capability.

The subsequent [native template and case form delivery](EAGLE_EYE_DATASET_TEMPLATES_AND_CASES_2026-09-13.md)
implements the collection/template/enrollment/editing subset in source. Image-review
migration, cohort import, server transfer and training activation remain separate.

Workspace entry amendment (2026-09-11): [workspace-first UI contract](EAGLE_EYE_WORKSPACE_ENTRY_2026-09-11.md).
Opening or revisiting Eagle Eye never selects or starts a function. Use the
in-workspace Choose Function action; Brain tools open in an owned popup while
the common imaging workspace and lazy data/training/reception tabs remain available.

## Ownership and installation

Eagle Eye is the product feature umbrella. Brain and Lumbar are features inside
it, not independent installer products. Keep the existing anatomy routing and
background-worker boundaries. Shared Slicer remains part of Advanced MPR and is
also used outside Eagle Eye; do not uninstall it when retiring a Brain dependency.

`modules/ai_imaging/eagle_eye/assets.py` declares current asset ownership. Brain
assets live at `advanced_mpr/eagle_eye/brain` within module runtime storage, with
ProgramData package fallback. Lumbar retains `advanced_mpr/offline_lumbar` to keep
existing installations compatible; that historical path does not change its
Eagle Eye ownership. Do not introduce a second optional-module identity merely
to rename this directory.

The Eagle Eye edition installs both feature payloads and shared Slicer. Standard
and ARM retain Slicer and exclude the Eagle Eye model assets. Future anatomy
features must join the same edition policy and have explicit manifests, runtime
lookup, package allowlists, dependency notices and synthetic packaging guards.

2026-09-14 amendment: Brain white-matter lesion analysis is a separate Eagle Eye
function using T1 + 3D FLAIR and an isolated LST-AI payload at
`advanced_mpr/eagle_eye/brain-lesions`. Standard/ARM exclude these assets too.
See [MS lesion implementation and acceptance](EAGLE_EYE_BRAIN_MS_LESION_DESIGN.md).
This adds lesion candidate burden, not an automatic MS diagnosis or a normative
volumetry extension. Customer release requires the model-bound acceptance record.

## Brain contract

- Primary workflow: selected study T1 -> SynthSeg -> isolated headless Slicer
  measurement -> volBrain reference attachment -> organized single-study PDF.
- Use the selected DICOM identity and examination demographics. Save originals
  under patient/study-specific User Data; export only completed PDFs atomically.
- Only published volBrain intervals are active. Retired IDs must fail explicitly.
  Never restore old reference selection, age clamping or cross-model fallback.
- Do not infer cortical thickness or lobar white matter from cortical volume.
  Do not add marginal reference endpoints or invent missing normal ranges.
- Keep cortical atlas analogues marked and separate from matched diagnostic
  claims. The red threshold is a >25% endpoint-distance attention rule.
- The patient-specific longitudinal comparison is a private validation artifact,
  not part of Eagle Eye's standard workflow or installer.
- No FreeSurfer reconstruction, WSL or R invocation belongs in the current Brain
  runtime. Retain scientific atlas citations where they describe measurement
  anatomy; removing an obsolete normative calculator does not remove the atlas.

## Development and release evidence

Follow [Brain references](EAGLE_EYE_BRAIN_REFERENCE_SETUP.md) and
[Brain delivery](EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md). Use the canonical `BUILD.md`
route. A local preparation or CLI probe is not clean Windows acceptance. No
release owner may substitute a fabricated approval record for actual rights and
installation evidence. Never copy private patient jobs into a model bundle.

The retired reference data/configuration were moved to the reversible
`generated-files/retired-brain-references-20260907` archive after execution review
rejected permanent folder deletion. Only volBrain remains in active reference
storage. R and FreeSurfer were removed using their official uninstall/package
managers. Shared Slicer, WSL and patient measurement evidence were preserved.
The archive and failed candidates are outside the customer payload. Retirement
does not establish that the research publications themselves were disproved.

## Anatomical report organization (2026-09-07)

The standard renderer owns explicit pages for cerebral white matter, cortical
summary, hemisphere cortex, each of the six cortical groups, CSF/ventricles,
basal ganglia, other deep gray matter, brainstem, cerebellum and medial temporal
structures. Bilateral measurements stay in adjacent right/left columns. Midline
CSF and brainstem use single measurements. Unassigned future atlas pairs remain
visible in an explicit fallback section. Do not mix CSF, cerebellum and cerebral
tissue in one regional table. Keep the scientific reference appendix and QC pages.

A full local Windows service rerun from the existing adult follow-up DICOM series
completed with 101 posterior measurements, 98 binary measurements and a 29-page
PDF. DICOM identity, every header/footer and byte-identical atomic PDF export
were checked; all pages were rendered and visually reviewed. Maximum absolute
posterior-volume difference from the previous same-scan result was 0.000003 cm3.
The 86 focused report/reference/workflow tests passed on the Windows Qt backend.
This exercised the application's service and export functions, not a new live
Eagle Eye button-click session or clean-machine installer acceptance. Private
validation artifacts remain in User Data, not in the distributable payload.

Result interaction and future maintenance are specified in [Brain UI and maintenance](EAGLE_EYE_BRAIN_UI_AND_MAINTENANCE.md). The completion card replaces embedded full-report HTML with clear PDF save/open actions.
