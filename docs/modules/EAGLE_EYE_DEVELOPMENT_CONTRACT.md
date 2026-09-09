# Eagle Eye development contract

Updated 2026-09-07. Applies to Brain, Lumbar and future anatomy features.

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
