# Eagle Eye spatial diagnosis packet experiment

Date: 2026-09-08. Existing work item: OPT-55.

## Implementation boundary

`tools/eagle_eye_bench/spatial_packet.py` implements an independent benchmark
input builder. It does not change the live application's diagnostic package or
default routing. This is an executed input experiment, not a claim that a vision
language model has acquired a native three-dimensional representation.

Each packet retains every member of its selected immutable acquisition groups.
Sagittal sequence and right/central/left groups remain separate. The target axial
slab stays intact. Ordering and adjacent distances use projection on the physical
plane normal, not filenames, instance order, nominal slice thickness or Z alone.
Missing members, duplicate planes, incompatible normals, excessive image/pixel
budgets and unverified shared frames of reference fail validation. Uneven sampling
is explicitly reported; no interpolation joins separate blocks.

The geometry manifest describes the displayed image, including its crop-adjusted
origin, directions, pixel spacing and dimensions in patient LPS coordinates. Two
auxiliary images show actual plane intersections in both directions: target axial
planes on a central sagittal reference, and sagittal T2 planes on a target axial
reference. Intersections are clipped to both acquired fields of view. The unmarked
diagnostic images remain separate and unchanged. These lines identify acquired
planes, not lesion boundaries or segmentations.

The geometry follows the [DICOM Image Plane Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html).
The use of multiple separate images is consistent with Google's
[Gemini image-understanding interface](https://ai.google.dev/gemini-api/docs/image-understanding).
Neither interface establishes correct clinical spatial reasoning by the model.

## Matched evaluation

The approved private test study is reconstructed from the most recent source-run
series. Current DICOM geometry and every rendered original image are checked
against the previously frozen inputs. No patient identifiers, images, response
text or case-specific reference findings belong in this report or test fixtures.

Two arms use the same Gemini 3.1 Pro company route, temperature 1.0, 12,000 output
token ceiling, diagnostic question and original image bytes/order:

1. Complete ordered groups with group roles and image identities.
2. The same complete groups plus the physical manifest and two plane locators.

Five levels, two arms and two repeats produce 20 requests. Every request includes
11 sagittal T2 images, 11 sagittal T1 images and the entire four- or five-image
target axial slab. Each sequence keeps its original right/central/left groups.
The spatial arm adds two locator images. Source anatomy-gate labels are explicit
priors, not independently established anatomical truth.

Both arms independently assess every level and neural compartment, irrespective
of negative screening decisions. This tests the added spatial manifest/locators
against a matched complete-sequence control. Comparison with the ordinary live
pipeline additionally changes coverage and gating and cannot isolate geometry.
The prompt contains no expected findings, prior model answers or scoring labels.

After reviewing the first comparison, a bounded focused follow-up repeats all
five levels in two arms and two repeats (20 additional requests). It retains only
the complete five-slice central sagittal T2 group and complete target axial slab.
Its control preserves the previous grouped-input clinical prompt; its spatial
arm adds the matching manifest and two locators. The prompt explicitly permits
insufficient foraminal coverage. This follow-up is exploratory, not a preselected
factorial experiment: it changes both sagittal coverage and clinical prompt
relative to the first comparison. Within each comparison, originals and clinical
question remain identical between control and spatial arms. Both use transport
image detail `high`; earlier historical probes may use a different detail value.

Private inputs, hashes, transport outcomes and response files are retained under
the ignored local benchmark directory. Failures must be counted separately from
diagnostic disagreement. Two repeats on one previously investigated case are a
pilot, not a clinical accuracy or stability estimate.

## Verification

Seven synthetic guards pass in `test_eagle_eye_spatial_packet.py` (direct pytest,
exit 0): physical order and complete membership; shared-frame rejection;
separate-group boundaries; bidirectional finite-field intersections; original
pixel preservation; gaps and duplicate planes; and oblique, anisotropic,
crop-adjusted coordinate consistency. The initial six feature guards failed at
import before the new module existed; this was a new-feature baseline, not six
reproductions of a clinical defect.

All ten private locator images have complete intersection audits. The two
critical-level guides were visually inspected before dispatch. Shared DICOM
coordinates alone do not prove absence of motion between acquisitions, correct
anatomical numbering, adequate lesion coverage or diagnostic validity.

Runtime integration and default adoption remain separate from this benchmark.
No installed build, production package, credentials or GPU services are changed.

## Execution outcome

Both comparisons completed: 40 of 40 transport responses finished successfully,
and all 40 parsed with valid target levels, grading enums and supplied evidence
identities. This validates transport and the tested structural fields, not image
reasoning. The pilot did not establish stable diagnostic agreement from adding
geometry and locators. Case-specific findings, repeat disagreements, unscored
compartments, exact-side versus bilateral-inclusive counts and complete outputs
remain only in the private benchmark reports. The current evidence does not
justify making this experimental packet the default diagnostic input.

## Visual handoff correction: paired cards

A subsequent visual review identified two presentation weaknesses in the first
pilot: native axial images were separated from their line locators, and the reverse
locator overlaid many lines on one axial image. Originals were preserved, but that
alone did not ensure an easy visual correspondence. The previous 40 diagnostic
responses used that earlier layout and must not be attributed to this correction.

`render_correspondence_cards` now emits one card for every member of an immutable
target axial group, in physical cranial-to-caudal order. Each card contains a
small sagittal locator with exactly one line, an enlarged unmarked sagittal slab
context, and the corresponding enlarged unmarked axial image. A shared pair ID,
exact source IDs and measured distance from the previous plane sit outside the
image panels. The sagittal crop covers all slab intersections with padding and
retains the full image width; it is not a lesion annotation. Enlargement is
prepared before dispatch and does not require an interactive zoom tool or add
acquired detail. Every native member of the selected sagittal and axial groups
still accompanies the cards as a separate image.

The renderer validates membership and geometry before generating cards and refuses
existing card destinations. Its audit records exact source crops and canvas boxes
for clean-panel pixel comparison. The old locator audit now explicitly states
`locator_pixels_annotated: true`, distinguishing marked guides from unchanged
source pixels. This remains a benchmark utility, not production integration.

Two new guards failed before the paired renderer existed and pass afterward;
the full spatial utility suite now passes nine tests. On the approved private
case, all 22 paired cards passed exact clean-panel pixel equality against the
expected crop/resize of their sources. Representative normal and abnormal target
cards were visually reviewed. A separate five-request company-route probe checks
only whether the model reads pair/source IDs, ordering and overlay placement.
Its outcome is a presentation check, not a new diagnostic result or proof of
spatial reasoning.

The five layout-only requests completed. All 22 source-image/reference pairs and
their order were read correctly, with one locator line and unmarked clean panels
reported for every card. Four pair tags included the visible total-count suffix;
strict short-tag agreement is 18/22, suffix-normalized agreement is 22/22. The
source identity checks remain exact. No revised-layout diagnostic inference was
performed in this follow-up.

## Subsequent paired-layout diagnostic replay

On a subsequent explicit request, the audited paired cards were replayed for
diagnosis through both the existing company Gemini 3.1 Pro and GPT-5.6-Sol routes.
The primary protocol evaluates all five levels, two repeats per model, with
identical messages and image bytes at each target, temperature 1.0, detail high
and a 12,000-token output ceiling. All native selected group members accompany
the cards. No clinical reference findings or prior model answers enter requests.

An initial 20-request run retained a legacy sentence describing representative
middle slices. That inaccurate coverage description was identified before
reviewing diagnostic outcomes. The initial run is preserved separately. The
primary 20-request run replaces that sentence with an explicit complete axial
group and separately supplied five-slice sagittal sequence description; no image
or model setting changes accompany the correction. The runs are not pooled.

All 20 primary responses completed and passed the tested local field and source-ID
contracts. Case-specific agreement and side/severity/level disagreements remain
in the ignored private paired-diagnosis reports. The experiment does not establish
stable clinical performance or a causal layout benefit. No runtime provider
selection, production default or installed build changed.
