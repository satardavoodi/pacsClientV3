# MedGemma grouped lumbar diagnosis: input and prompt design

Date: 2026-09-07. Work item: OPT-55.
Status: investigation and proposed experiment; no runtime/server change or new inference.
Architecture authority: `docs/pipelines/eagle-eye-mri.md`.

## Recommendation

Keep screening and candidate selection in place. For each selected
`(level, structure_group)`, build one multi-image diagnosis request from immutable
source groups. Send separate native slice images, organized into explicit
sequence/plane/anatomical blocks, with a compact spatial manifest. Preserve the
existing montage for review and as an experimental control.

Use the locally hosted MedGemma 1.5 4B through a bounded multi-image adapter.
Do not upload DICOM ZIPs to the existing single-image endpoint or stitch separate
lumbar acquisition slabs into a synthetic continuous volume. This recommendation
chooses the next experiment; it does not establish superior lumbar accuracy.

## Verified external capabilities

MedGemma processes volumes as sequences of 2D RGB axial images, not native 3D voxel
tensors. The technical report used up to 85 slices during training/evaluation,
with consistent thickness within eligible volumes and at least five slices.
MRI used per-volume min-max normalization with equal RGB channels. Its reported
MRI dataset covers brain, knee and abdomen, not a lumbar extrusion benchmark.
Evaluated volume prompts are focused condition questions, not comprehensive
multi-level reports. These training details are not an API limit or a requirement
to pad a short client request to five slices.
[Technical report](https://arxiv.org/html/2604.05081v1).

The official CT notebook places individual images and slice labels into one user
message, then uses `processor.apply_chat_template` and `model.generate` with
sampling disabled. Its GIF is for display, not inference. Its example sorting by
InstanceNumber and uniform sampling must be replaced by our geometry/membership
contracts. Its CT color-window mapping must not be copied into MRI preprocessing.
[Official notebook](https://github.com/google-health/medgemma/blob/main/notebooks/high_dimensional_ct_hugging_face.ipynb).

The model card documents 896 x 896 processing, 256 tokens per image, a 128K input
context and text output. Actual image expansion, resizing and memory use must be
measured with the deployed processor. Server-side preprocessing deployments linked
there are not automatically features of our custom endpoint.
[Model card](https://developers.google.com/health-ai-developer-foundations/medgemma/model-card).

## Official geometry audit: ordered images versus physical coordinates

The following findings are from Google's public repository at commit
`a60a66024f6153496dfa9490dba12d4f1fbd092e`, inspected on 2026-09-07.
They describe the published serving path, not undocumented training internals or
the configuration of our running server.

**What the model receives.** The serving predictor expands a DICOM CT/MRI
acquisition into individual images and inserts `SLICE 1`, `SLICE 2`, etc. when
there are multiple slices. It passes encoded images and the resulting text to
inference. This assembly does not automatically pass ImagePositionPatient,
ImageOrientationPatient, millimeter spacing, an affine, or cross-plane
intersections to the model. Numbering restarts per acquisition. Ordinary image
entries take a different branch without this automatic volume numbering.
Consequently, our image-list adapter must provide its own labels and group IDs.
[Published model-input assembly](https://github.com/google-health/medgemma/blob/a60a66024f6153496dfa9490dba12d4f1fbd092e/python/serving/predictor.py#L540).

**What the transport accepts.** The published request schema accepts a DICOM
instance URI, a series URI, or an ordered list of instance URIs. It explicitly
assigns significance to list order. Its optional patch coordinates describe
rectangular image ROIs, not physical 3D coordinates. A generic extensions field
does not establish a geometry-conditioning capability.
[DICOM request schema](https://github.com/google-health/medgemma/blob/a60a66024f6153496dfa9490dba12d4f1fbd092e/python/serving/vertex_schemata/request.yaml#L598).
The explicit-instance download path constructs its selected metadata list in
caller-supplied URI order.
[Instance-list handling](https://github.com/google-health/medgemma/blob/a60a66024f6153496dfa9490dba12d4f1fbd092e/python/data_accessors/dicom_generic/data_accessor.py#L209).
This published schema supplements the unfinished serving documentation page;
it does not add those inputs to our existing `/AnalyzeImage` endpoint.

**An ordering concern in the convenience path.** At this pinned revision,
`_sort_by_slice_position` names its index as a Z coordinate but sets it to zero,
then indexes ImagePositionPatient. That selects patient X. The series-selection
helper uses this key. For ideal axial images with constant X, this cannot establish
superior/inferior order; for oblique images, X alone is not a general slice-order
rule. This is a source-level concern, not evidence of a failure in our current
PNG endpoint or a reproduced error on clinical data. Prefer our validated ordering
and an explicit image/instance list over relying on that series convenience path.
[Series selection and sort](https://github.com/google-health/medgemma/blob/a60a66024f6153496dfa9490dba12d4f1fbd092e/python/data_accessors/utils/dicom_source_utils.py#L207).

### Geometry responsibilities for this workstation

DICOM defines image origins and row/column directions in patient coordinates,
with PixelSpacing supplying in-plane scale.
[DICOM Image Plane Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html).
Our proposed implementation should calculate a common slice normal from compatible
orientation vectors and sort each immutable acquisition group by the projection
of its image origin onto that normal. Differences in these projections give plane
separation; SliceThickness alone does not. Validate frame compatibility and motion
before cross-sequence correspondence. Determine anatomical eligibility separately.

The model can infer relationships from ordered visual evidence, but an ordinal
does not specify metric separation or the intersection of an axial and sagittal
plane. The compact physical manifest proposed in this report is **our engineering
addition**, not a documented special MedGemma geometry input. Supplying numbers
in prose does not demonstrate that the model uses them correctly.

For the next comparison, retain a baseline using ordered axial images with slice
labels, closest to the published volumetric input. Add sagittal evidence as
separate verified sequence/anatomical blocks, never as continuation of the axial
stack. Keep block boundaries, member identities and missing coverage explicit.
With identical pixels, test a further arm containing verified relative positions
and cross-plane correspondences. A locator image showing calculated intersections
can be a separate subsequent experiment; preserve an unmarked diagnostic image
and validate every overlay after crop/resize. Neither metadata nor overlays are
assumed to improve accuracy before evaluation.

### What independent volumetric work establishes

The NeuroVFM study uses standardized voxel spacing and a volume encoder with 3D
patches and positional information. Its MedGemma comparator instead receives 2D
slices; that experiment used reduced-resolution, subsampled neuroimaging inputs.
This illustrates an architectural route to spatial representations, not a
MedGemma prompt feature or validation for lumbar extrusion. Its comparator
results also cannot isolate the effect of geometry from preprocessing and training.
[Nature Medicine methods](https://www.nature.com/articles/s41591-026-04497-1).

The evidence supports an ordered-slice experiment with geometry calculated by our
software. It does not establish a best-performing lumbar recipe or justify a
claim that a prompt alone turns MedGemma into a metric 3D reconstruction model.

## Specialist models as evidence providers for MedGemma

Follow-up source audit, 2026-09-07. Ranking below reflects task coverage and
integration evidence, not a head-to-head clinical accuracy comparison. No weights
were loaded and no patient inference was performed.

### Candidate selection

| Candidate | Documented or inspected outputs | Useful handoff | Main limitation | Decision |
|---|---|---|---|---|
| lhwcv RSNA 2024 solution | Localization points; five condition families at five levels, each with three severity probabilities | Target coordinates, traceable crops, canal/left-right foraminal/left-right subarticular predictions | Competition ensemble; requires preprocessing, coordinate and batching audit; no herniation subtype or root-compression head | First candidate for a bounded grading experiment |
| Oxford Park et al. multi-view model | Five stenosis condition heads per IVD and an auxiliary level head | Joint evidence for canal, foramina and subarticular spaces at the selected level | Public paper promises code/weights; matching release not located during this audit | Architectural reference; executable candidate when release is verified |
| M-SCAN | Localization probability maps and five level-wise canal severity outputs | Independent canal assessment and candidate ROIs | Narrower label scope and concrete notebook batch-layout concerns | Defer until code/weights agreement is resolved |
| SPINEPS, complementary segmentation | Anatomical masks, centroids, optional uncertainty and review snapshots | Anatomical contours and spatial anchors alongside original images | Sagittal segmentation is not axial-sagittal diagnostic fusion; no dedicated extruded-fragment or S1-root label | Separate geometry/segmentation experiment |

The Oxford architecture aggregates slice embeddings from multiple views at one
IVD, adding order, view and level encodings. Its five condition heads distinguish
canal, left/right foraminal and left/right subarticular stenosis. Its severity
classes combine normal and mild. The author's inspected public repository list
did not expose a matching release; AutoLabelClassifier is a different report-text
project. Do not substitute it for this imaging model.
[Oxford paper](https://www.robots.ox.ac.uk/~vgg/publications/2025/Park25/park25.pdf).

### RSNA implementation evidence and constraints

Inspected commit: `f466285646a2ca4047cf794c4be6fe34afd9ecbf`.
The repository documents trained-model links and carries an MIT source license;
weight download and artifact-specific reuse terms remain unverified.
[Repository](https://github.com/lhwcv/solution-rsna-2024-lumbar-spine/tree/f466285646a2ca4047cf794c4be6fe34afd9ecbf).

`HybridModel_V2` combines sagittal and axial embeddings and produces condition,
level and severity logits. Final inference combines branches and applies softmax,
yielding five conditions by five levels by three classes per study. The keypoint
inference path separately exports points and source-series associations.
[Fusion model](https://github.com/lhwcv/solution-rsna-2024-lumbar-spine/blob/f466285646a2ca4047cf794c4be6fe34afd9ecbf/infer_scripts/v2/models.py#L103),
[final probabilities](https://github.com/lhwcv/solution-rsna-2024-lumbar-spine/blob/f466285646a2ca4047cf794c4be6fe34afd9ecbf/infer_scripts/final_infer_cond.py#L1268),
[keypoints](https://github.com/lhwcv/solution-rsna-2024-lumbar-spine/blob/f466285646a2ca4047cf794c4be6fe34afd9ecbf/infer_scripts/final_infer_keypoints.py#L83).

These points are model/preprocessing coordinates, not automatically patient-space
millimeters. Reverse scaling, cropping, sorting and resampling before using them
as source-image annotations. Exported candidates cannot override our immutable
group memberships. The supplied DICOM helper sorts using one patient-coordinate
component. Some axial transformer paths also pass batch-first features to layers
constructed with the sequence-first default. Audit the exact selected path and
checkpoint; do not copy the entire repository into runtime as a validated package.
[DICOM helper](https://github.com/lhwcv/solution-rsna-2024-lumbar-spine/blob/f466285646a2ca4047cf794c4be6fe34afd9ecbf/src/utils/dicom.py#L41),
[axial model](https://github.com/lhwcv/solution-rsna-2024-lumbar-spine/blob/f466285646a2ca4047cf794c4be6fe34afd9ecbf/train_scripts/v24/axial_model.py#L73).

### Why M-SCAN is not the first integration choice

Inspected commit: `d1af1aaa35fcc4bb6ed65f6d6b5bae9120a76ea7`.
The final notebook produces 15 logits for five canal grades. It constructs
MultiheadAttention without `batch_first=True` but supplies `(batch, sequence,
feature)` tensors without transposing. Its flattened axial slicing also omits
the batch offset and broadcasts a selected result across the batch. These are
static source concerns requiring batch-independence tests and checkpoint
re-evaluation, not a reproduction of the published clinical results. Running
with batch size one would not establish intended sequence attention.
[Final notebook](https://github.com/Deep-learning-exp/M-SCAN/blob/d1af1aaa35fcc4bb6ed65f6d6b5bae9120a76ea7/spinal_canal_stenosis_FINAL.ipynb),
[attention input convention](https://docs.pytorch.org/docs/stable/generated/torch.nn.MultiheadAttention.html).

The U-Net's six channels are level-localization classes plus background, not a
herniation segmentation mask. A separate PointNet file is a placeholder, so its
presence is not evidence of a working 3D point service.
[U-Net](https://github.com/Deep-learning-exp/M-SCAN/blob/d1af1aaa35fcc4bb6ed65f6d6b5bae9120a76ea7/UNET/model.py#L100),
[PointNet](https://github.com/Deep-learning-exp/M-SCAN/blob/d1af1aaa35fcc4bb6ed65f6d6b5bae9120a76ea7/UNET/point_model.py#L18).
The README links weights, but download was not verified. No explicit license file
was present in the inspected tree. These unresolved items limit readiness.

### Segmentation provides a different kind of evidence

SPINEPS documents disc, canal and vertebral masks, centroids, optional uncertainty,
and optional VERIDAH anatomical labeling. It offers a Python interface and model
download workflow. These outputs could support overlays and geometry-derived
measurements after validation. Anatomical disc segmentation is not a validated
extrusion-boundary mask, and a canal mask is not a nerve-root segmentation.
Assess severe pathology and lower lumbar coverage before deriving measurements.
[SPINEPS](https://github.com/Hendrik-code/spineps),
[pipeline](https://spineps.readthedocs.io/en/latest/modules/pipeline/).

### Proposed handoff and comparison

Provide MedGemma with original ordered images plus an explicitly attributed
specialist-evidence block: target/group IDs, mapped frame IDs, localization
coordinates, complete class-probability vectors, model/checkpoint version,
preprocessing provenance, coverage and assessability. Optional overlays remain
separate from unmarked images. Raw latent vectors are not directly interoperable
with MedGemma's vision embeddings; consuming those would require a trained
connector and a different model experiment.

Never translate `normal_mild` into definitely normal, softmax into calibrated
clinical confidence, severe stenosis into extrusion, or subarticular narrowing
into proven S1 compression. None of the three grading models documents direct
heads for extrusion, sequestration, annular fissure or individual root compression.
Keep unsupported fields unknown and preserve disagreement for review.

RSNA and M-SCAN paths expect multi-level context. Run their documented study input
once in an isolated worker and bind only the relevant outputs to selected diagnosis
units; do not pretend an arbitrarily reduced single-disc input is equivalent.
Record this broader input context in evaluation. Keep screening/grouping authority
in place. Existing seams are `atomic_pipeline.py::verification_package_for` and
`focus_evidence.py::_diagnostic_group_integrity`; any evidence-block extension must
preserve their level, structure and parent-membership scope.

Compare on identical LLM images: images alone; images plus validated locations;
then images plus locations and specialist grades. Evaluate segmentation overlays
separately. Assess all supported levels/conditions, not only faults. Measure severe
misses, side/level errors, false positives and changes in morphology accuracy,
with radiologist references withheld from prompts. A better stenosis score does
not by itself establish improved extrusion recognition. No reported AUROC across
these different evaluations is treated as a direct model ranking.

## Current local boundary and source findings

The client guide identifies MedGemma 1.5 4B on an A100 40GB host. The live API schema
inspected during this investigation sequence exposes `POST /AnalyzeImage` with one
`file`, `prompt` and `max_new_tokens`. The guide describes Pillow RGB loading;
neither the guide nor that schema provides image-list, DICOM or NIfTI ingestion.

| Source seam | Verified behavior | Implication |
|---|---|---|
| `screening_evidence.py::_axial_group_contract` | Retains measured slab memberships under neutral IDs | Reuse the exact parent group; do not regroup all lumbar slices during diagnosis |
| `screening_evidence.py::_sagittal_group_contract` | Sorts by common DICOM slice-normal projection, then partitions up to three outer planes per side and all intervening planes centrally | Geometry order is verified; foraminal visibility is not established by this partition |
| `anatomy_cards.py::normalize_anatomy_map` | Validates group membership and corrects sagittal side using LPS X | Preserve this check, but do not equate correct side with correct foraminal anatomy |
| `focus_evidence.py::_sagittal_contract_indices` | Uses lateral-group middle members and central-group first/middle/last members as fallback | A group-preserving sample can still miss the target |
| `focus_evidence.py::_distinct_axial_fallback` | Selects three neighboring same-slab samples, repeating samples if too few exist | Sequence experiments should retain complete usable groups without duplicate padding |
| `focus_evidence.py::_diagnostic_group_integrity` | Validates selected members and parent identities | Reuse these guards at export and server receipt |
| `atomic_pipeline.py::verification_package_for` | Sends one montage for each independent diagnosis | Add a multi-image representation of the same diagnostic unit |

**The positional outer-three partition still exists in the source.** It follows
DICOM sorting rather than filename order, but cannot prove that each outer member
shows a foramen. This identifies a limitation of the guarantee, not proof that a
particular patient's selected slice is wrong. No source change was made here.

## Input routes

| Route | Actual model input | Decision |
|---|---|---|
| Existing montage through `/AnalyzeImage` | One composite image | Baseline and operator preview |
| Separate PNGs and manifest through a local multi-image adapter | Independent image items in one user message | Recommended |
| In-process Hugging Face with PIL images | Same multi-image representation without HTTP | Isolated implementation probe, outside the GUI thread |
| DICOM/NIfTI through a preprocessing adapter | Decoded images after geometry validation | Later transport convenience; not native voxel inference |
| Hosted Google preprocessing/container | Deployment-specific conversion | Alternative infrastructure, unnecessary initially; its linked serving API page currently says Coming soon |
| GIF/video or rendered 3D surface | A different, potentially lossy representation | Not the main input demonstrated by the official volumetric notebook |

Axial/sagittal/coronal are image roles, not separate model endpoints. Mixed-plane
input is technically packageable, but the published volumetric recipe is axial.
Mixed-plane lumbar input is an explicit experiment. Coronal reformats are a later
option only when real acquisition resolution and validated transforms support them;
they cannot recover anatomy absent from the acquisition.

## Immutable groups versus anatomical eligibility

Keep four layers separate:

1. Source image/frame identity and original DICOM transform.
2. Neutral geometry parent group and its complete original member set.
3. Anatomical eligibility for a target/side/level/ROI, with verification authority.
4. The selected members transmitted for this diagnosis.

A sagittal plane spans multiple levels and can depict several structures. Its
target eligibility is an annotation, not permission to move it into another
parent group. Keep `sequence_role` (T1/T2), `plane`, `anatomical_role` and
`target_level` distinct.

For a foraminal packet, establish target-level anatomy using the validated map and
sagittal/axial relationship. Operator-confirmed anchors are appropriate for the
initial controlled experiment. A future landmark method needs separate validation.
DICOM geometry provides side and intersections, not recognition of the pedicle,
true anatomical midline or foraminal boundary.

Never move a central member into a lateral group to satisfy a requested slot. If
an immutable group cannot support its assigned anatomical role, record an
eligibility conflict and return that target for anatomy review. A corrected group
definition must be a versioned upstream correction with provenance, not a silent
diagnosis-side mutation. This adds a handoff check without rerunning screening.

For axial slices, similar Z is insufficient. Use orientation, projection onto the
acquisition normal, existing slab identity and validated level mapping. Preserve
angulated groups. Compatible FrameOfReferenceUID enables coordinate comparison
but does not exclude inter-sequence motion. An invalid lesion correspondence must
not become a purported lesion-centered crop using the image's geometric center.

## Task-specific packets

Counts are data-dependent, never fixed three-slice rules.

| Task | Primary evidence | Complementary evidence | Boundary |
|---|---|---|---|
| Disc | Complete usable axial T2 parent slab | Eligible central/paracentral sagittal T2 group covering attachment and extent | Disc morphology only |
| Canal/recess/root | Complete usable axial T2 slab and available caudal/subarticular coverage | Eligible central/paracentral sagittal T2; other sequences only under the existing template or an explicit experimental arm | Separate central canal, each recess and each neural structure |
| Right foramen | Anatomically verified right foraminal sagittal T2 and matched T1 | Same-level axial T2; optional separately labelled left comparison group | Right conclusions require right-side eligible evidence |
| Left foramen | Anatomically verified left foraminal sagittal T2 and matched T1 | Same-level axial T2; separate right comparison if included | Mirror of right-side contract |
| Endplate/marrow | Matched eligible sagittal T1/T2 | Existing task-specific axial context | Preserve vertebra and endplate surface |
| Posterior elements | Existing template's eligible sagittal T1/T2 and same-level axial groups | Appropriate side-specific context | Preserve target, side and parent membership |

A bilateral foraminal candidate can use one request with distinct right/left
blocks and separate assessments. Pair T1/T2 by validated physical correspondence,
not equal list indices.

“Good axial images” means interpretable native members of the correct group, not
only those with the strongest model-predicted abnormality. Initially include all
usable members of the bounded group. Record corrupt, duplicate or non-diagnostic
members as exclusions with reasons. Exclusion does not change the parent list or
authorize borrowing from another level. If the visible lesion reaches the acquired
boundary, report `extent_not_covered`. Any later additional context retains its own
parent group/level and context designation; never stitch groups into a fake stack.

## Pixels, geometry and request serialization

Use a stable physical ROI across members of each series, preserving attachment and
neighboring anatomical boundaries. Independently recentering each slice on an LLM
box can create artificial movement. Keep crop-to-source transforms locally. Avoid
a lesion-only crop that removes its parent structure.

Preserve current intensity mapping in the initial representation comparison.
Compare official per-volume normalization separately, rather than changing pixels
and transport simultaneously. Do not apply independent auto-contrast to every
slice. Preserve aspect ratio through the actual processor and inspect its processed
inputs. Keep diagnostic pixels clean; image IDs belong outside tissue. Locator
overlays may be separate context, not an obscuring line over the target.

Proposed private manifest:

```text
packet_id, schema_version, source_contract_version, target_level, structure_group
groups[]:
  group_id, sequence_role, plane, anatomical_role, role_verification
  parent_member_ids, included_member_ids, excluded_members_with_reasons
  physical_order, spacing_summary, coverage_status
images[]:
  image_id, group_id, parent_member_id, content_hash, target_eligibility
  order_in_group, relative_position_mm, orientation_labels, crop_transform
correspondences[]:
  image_ids, validation_status, local_transform_reference
```

Use packet-local opaque IDs in model-visible metadata. Keep identifiers, source
paths, DICOM UIDs and full transforms in the private session store. Server-side
validation checks image count/hashes, group order and target membership before
inference. Hash both pixels and manifest to establish request identity.

Example serialization, using ordinary text labels rather than special model tokens:

```text
USER: bounded task and compact packet header
GROUP: axial-target / T2 / selected level / superior-to-inferior order
IMAGE: ax-01
TEXT: image_id=ax-01; group=axial-target; ordinal=1; relative_position_mm=...
IMAGE: ax-02
TEXT: image_id=ax-02; group=axial-target; ordinal=2; relative_position_mm=...
END_GROUP
GROUP: sagittal-central / T2 / patient-right-to-left order
... separate images and labels ...
END_GROUP
GROUP: sagittal-right-foraminal / T1 / only if relevant and verified
... separate images and labels ...
END_GROUP
TEXT: task-specific question and response contract
```

Different planes and sequences are complementary blocks, not one continuous
sequence. Adjacency exists only inside a group. Do not alternate T1/T2/axial items
and imply that neighboring message items are neighboring slices.

## Prompt proposal

Use a single bounded user message, without assuming system-role support or
multi-turn memory. Keep history out of the first representation comparison and
the reference diagnosis out of all inference requests. Candidate identity supplies
a target, not a required positive answer. Do not ask the 4B model for a full lumbar
report, repeated manifest or long reasoning essay.

Common instruction, followed by the image blocks and one task-specific addendum:

```text
Evaluate the supplied target at the bound spinal level using these grouped MRI
images. The groups are complementary views of the target, not separate cases.

Keep image IDs, parent groups, level and patient-side labels unchanged. Adjacency
applies only within each group. Different sequences and planes are not a continuous
stack. Use only correspondences marked valid in the manifest. In axial images,
patient right is viewer left and patient left is viewer right.

Follow the target through adjacent slices and complementary views. Identify its
parent structure, attachment, visible extent and relevant neighboring boundaries.
Do not classify panels independently or vote across panels.

Screening selection does not establish disease, morphology or severity. Normal,
abnormal and indeterminate are allowed. Missing coverage is not normality. If
anatomical eligibility or correspondence is insufficient for a claim, identify
that limitation without moving an image or inventing a measurement.

Return compact JSON containing packet_id, target_level, structure_group,
assessment, spatial_observations, diagnosis, evidence_image_ids and limitations.
Each observation must cite supplied image IDs. Do not repeat the manifest.
```

Disc addendum:

```text
Assess only the bound disc. Describe the displaced contour, attachment to its
parent disc and visible cranial/caudal extent. Compare the extra-discal component
with its base within the SAME image plane, citing that evidence. Distinguish
generalized bulging from localized herniation before assigning protrusion or
extrusion. Migration and continuity are separate observations; absence of migration
alone does not exclude extrusion. Return indeterminate when required boundaries
are not visible. Do not invent millimeter measurements.
```

Terminology must remain aligned with the established
[NASS/ASSR/ASNR nomenclature](https://radiology.queensu.ca/source/Lumbar_Disc_Nomenclature.pdf).
This is a proposed task instruction, not a validated Google lumbar prompt.

Canal/recess/root addendum:

```text
Assess central canal, right and left lateral recesses, and right and left neural
structures separately. Trace each assessable structure through the available
group. Record normal, abnormal or indeterminate, visible change and supporting
image IDs for each. Central canal patency does not establish recess/root normality.
Describe neural relationship separately from disc morphology and central canal
severity. Apply the supplied grading contract only when its features are assessable.
```

Foraminal addendum:

```text
Assess each requested foramen using its verified patient-side sagittal group and
valid same-level axial correspondence. Record perineural fat and root appearance
for each requested side with supporting image IDs. Opposite-side images are
comparison context and cannot establish an ipsilateral finding. A lateral sagittal
position alone does not prove foraminal visibility. Return indeterminate when
target-side coverage is insufficient.
```

Keep each spatial observation compact: `feature`, `value`, `image_ids`. Prefer
bounded values and `indeterminate` over unsupported numeric precision. Map only
validated responses into the existing card-bound diagnosis contract. Malformed or
truncated JSON, omitted targets, foreign IDs and side contradictions are invalid
responses, not negative findings. Do not automatically repair clinical content.

## Implementation and resource boundaries

Proposed workstation seam: a worker-side exporter alongside `focus_evidence.py`,
consuming the evidence plan and authoritative anatomy/group contracts. No decode
or network work on the Qt GUI thread; no mutable VTK sharing between viewer domains.

Proposed server seam: a separately tested image-list adapter around the loaded
processor/model, with a documented manifest and multi-file contract. Endpoint name
is not committed. Keep `/AnalyzeImage` compatible. No direct OpenAI fallback or
company-provider setting change is needed.

Initially serialize local GPU inference; do not inherit three-way external-model
concurrency without measuring memory. Pin model, processor, dependencies and decode
settings. Start with `do_sample=False` and a proposed 2,048-token response budget;
greedy decoding is not proof of clinical stability. Record actual input tokens,
latency, GPU peak memory, truncation and cancellation. Over-budget packets return
an explicit size/coverage error rather than silently dropping members. No remote
inference or patient export is part of this documentation-only investigation.

## Controlled evaluation

Freeze target identities, group memberships and reference adjudication. Evaluate
all selected diagnosis families, not only a successful disc example. Include
expert-bound negative controls offline without adding all-level production diagnosis.

| Arm | Input | Prompt | Variable isolated |
|---|---|---|---|
| A | Existing montage | Short bounded diagnosis task | Baseline |
| B | Exactly the same source crops as separate images | Same task | Representation |
| C | Complete eligible parent groups as separate blocks | Same task | Contiguous coverage |
| D | Same images/manifest as C | Spatial-observation addendum | Prompt |

Keep shared pixels, contrast and preprocessing constant; keep transport labels as
comparable as possible. Fix three initial repeats per target/arm and record all
responses, including invalids. Expand only to resolve a concrete ambiguity. After
choosing the input form, compare on identical eligible evidence with the existing
company-routed models, recording provider-specific resizing. Do not select the
most favorable response or interpret repeated greedy answers as generalization.

Score binding, morphology, compartment findings, negative-control false positives,
assessability, citation correctness and repeat agreement separately. Report exact
denominators, invalid-output rate and runtime. Schema compliance is not clinical
accuracy. Clinical acceptance is adjudicated by the radiologist; engineering
acceptance tolerates no group/side/level reassignment.

This measures diagnosis conditional on a selected target. An omitted screening
candidate still has no production diagnosis request. Manually binding an offline
benchmark target isolates diagnosis without concealing that upstream limitation.

## Required guards for the implementation

- Reverse storage order without changing physical order or patient side.
- Vary sagittal coverage; outer-three position cannot establish foraminal eligibility.
- Reject a central member falsely assigned to a lateral/foraminal group.
- Reject adjacent-level borrowing, changed parent identity and duplicate padding.
- Retain full parent membership and explicit exclusions/missing extent.
- Pair unequal T1/T2 sampling geometrically rather than by ordinal.
- Reject invalid orientation/correspondence and incompatible coordinate frames.
- Verify image order/IDs through transport and actual processor preprocessing.
- Reject omitted targets, foreign citations, malformed output and truncation.
- Preserve normal, indeterminate and review-required outcomes as distinct.
- Keep installed processes, provider configuration and live databases outside tests.

No runtime tests were run for this report because application code was not changed.
Next implementation begins with synthetic membership/transport guards and the local
multi-image adapter, followed by the bounded diagnosis comparison on approved
private inputs. No new diagnostic performance result is claimed here.
