# Eagle Eye MRI: Canonical Pipeline and Card Architecture

Status: **official primary MRI architecture**
Effective date: 2026-09-05
Current lumbar implementation: pipeline 8.5.0, atomic contract 2.6.0, anatomy-card schema 1.10.0, screening schema 3.4.0, screening-atlas schema 1.6.0
Clinical status: engineering-verified; radiologist-adjudicated multi-case validation remains required

## Physical side and compartment coverage update (2026-09-05)

Axial radiological display is explicit: patient right is viewer left, patient left
is viewer right. The atomic atlas rejects unverified/noncanonical source orientation
before dispatch. DICOM LPS X corrects sagittal side labels while preserving the
selected midline, source membership and all axial level identities.

Every diagnostic level requires independent central-canal, bilateral lateral-recess,
bilateral nerve-root and bilateral neural-foramen observations. Recesses are part
of the canal assessment; central patency cannot substitute for their inspection.
Foraminal assessment remains a separate specialist request and joins the same
seven-compartment audit. Abnormal observations require corresponding diagnostic
candidates; not_assessable requires review. No central stenosis grade is inferred
from recess or foraminal disease. See
[`EAGLE_EYE_NEURAL_COVERAGE_2026-09-05.md`](../reports/EAGLE_EYE_NEURAL_COVERAGE_2026-09-05.md)
for validation, evidence binding and live acceptance.

## 1. Authority and scope

This document is the architectural source of truth for Eagle Eye MRI analysis.
All new MRI body-part implementations and all changes to the lumbar pipeline must
preserve this sequence:

```text
1. Geometry Processing
        ↓
2. Anatomical Localization / Site Recognition
        ↓
3. Screening Card Generation and Normal-vs-Abnormal Screening
        ↓
4. Diagnostic Card Generation
        ↓
5. Pathology Diagnosis / Classification
```

Body-part configuration may adapt approximately 10–20% of sequence selection,
anatomical targets, card layout, and diagnostic vocabulary. It must not replace
the five-stage architecture. A defect is corrected in the stage that owns it:

| Observed problem | Owning correction |
|---|---|
| Wrong image or side | Geometry processing or anatomical localization |
| Wrong level or anatomical target | Anatomical localization contract |
| Missed abnormal target | Screening evidence, prompt, or validation |
| Crowded or ambiguous card | Card template and renderer |
| Wrong pathology class or grade | Diagnosis evidence, prompt, or rubric |

The central card registry is implemented at
`modules/ai_imaging/eagle_eye/card_templates.py`. Body-part adapters consume the
registry; the registry never imports a viewer, VTK, Qt, DICOM decoder, or a
body-part pipeline.

## 2. Non-negotiable architecture rules

**Extended anatomical coverage (2026-09-05).** Acquisition coverage and diagnostic
scope are separate. Every neutral axial group is still mapped and validated exactly
once. Recognized thoracic disc levels and S1-S2 outside the T12-L1 through L5-S1
diagnostic scope are retained in `context_axial_levels`, with full source-tile and
group membership records. Source atlas images remain intact. Lumbar screening cards
use only `axial_levels`; context-only groups cannot become lumbar pathology or normal
findings. The stored coverage notice identifies levels not assessed and requires
review. Unknown, duplicate, mismatched, or uncertain labels still fail the gate; no
position-based relabeling is permitted. Existing 1.8.0 mapping responses can be
revalidated without editing the original response. See
[`EAGLE_EYE_EXTENDED_COVERAGE_2026-09-05.md`](../reports/EAGLE_EYE_EXTENDED_COVERAGE_2026-09-05.md).

1. Geometry precedes anatomical naming, and both precede pathology assessment.
2. DICOM patient coordinates are the authority for orientation, side, slice
   position, ordering, cross-series spatial correspondence, and membership in
   a geometry-derived acquisition group.
3. DICOM geometry alone does not name a lumbar level, pedicle, foramen, or true
   anatomical midline. Those labels require validated landmarks or bounded
   model-assisted anatomical recognition.
4. Screening answers normal versus abnormal. It does not classify morphology,
   stenosis, neural effect, Modic type, or another diagnosis.
5. Diagnosis is triggered only by a screening-positive target and receives a
   task-specific diagnostic card.
6. A card identity is `Task + Anatomical Target + Geometry + Relevant Sequences`.
   A level name alone is never a card template.
7. The workstation must not guess semantic anatomy when it knows only geometry.
   High-confidence sequence metadata may be supplied as a semantic label;
   otherwise the series keeps a neutral identifier.
8. The anatomy mapper may assign sequence and level semantics, but model output
   cannot overwrite source identity, geometry, patient side, spatial order,
   geometry-group membership, card identity, or allowed structure group.
9. Invalid gates stop visibly. The runtime does not silently invoke a historical
   monolithic path.
10. Every model-facing image and structured handoff remains saved and auditable.
11. No architecture version is promoted on a favorable single-patient run.
12. Geometry groups must remain visually intelligible without color. Physical
    whitespace and separate rows or blocks are the primary grouping signal,
    section headers are secondary, and color is tertiary.
13. A geometry group is immutable after Stage 1. Later stages may label the
    whole group or select a focused subset, but they may not split, merge,
    reorder, or move members between groups.
14. Every focused diagnostic subset records its persistent parent group ID,
    the complete original membership, and the selected membership. A mismatch
    is a gate failure, not a model-correctable uncertainty.

## 3. Shared cross-stage contract

Every stage emits an immutable, versioned artifact. A downstream stage consumes
only validated upstream output and source references contained by the active
session.

```text
DICOM instances
  → neutral GeometryMap and grouped cards
  → AnatomicalMap
  → ScreeningCard + ScreeningDecision
  → DiagnosticCard
  → DiagnosticDecision
  → deterministic reviewed report
```

Each artifact must include:

- `schema_version` and producing pipeline version;
- stable session-local source identities rather than filenames or screen order;
- body part, modality, task, anatomical target, and level when applicable;
- patient-space geometry provenance and authority;
- included and deliberately excluded sequences;
- confidence or assessability without converting uncertainty into a positive;
- warnings, validation results, and explicit failure reason;
- references to the exact image and JSON artifacts used by the next stage.

### Immutable group handoff

Gate 1-to-2 screening cards carry every member of each included geometry group.
Representative slices may be highlighted in metadata, but representation may
not redefine membership. Gate 2-to-3 diagnostic cards may reduce pixels by
selecting task-specific members only after screening. Each selected tile must
retain `parent_group_id`, `parent_group_members`, and its original source member
identity. The deterministic validator compares these values against the Stage 1
contract before rendering or sending a diagnostic card. Any changed identity,
missing authoritative parent, or member outside its parent produces
`geometry_group_integrity_error` and stops that card.

Clinical context is a bounded side input to diagnosis, not a geometry or
screening authority. It may inform differential diagnosis and assessability but
cannot create, move, or erase an image-grounded target.

## 4. Stage 1 — Geometry Processing

### Objective

Convert source DICOM metadata into deterministic patient-space relationships
before an LLM sees an anatomical or pathological question.

### Input

- selected DICOM series and instances, including classifier confidence and
  whether assignment was automatic or operator-confirmed;
- `ImageOrientationPatient`, `ImagePositionPatient`, pixel spacing, slice
  spacing, dimensions, and `FrameOfReferenceUID`;
- immutable study/series/instance identities;
- protocol-specific series-role classification as confidence-bearing metadata,
  not an unconditional semantic truth.

### Output

A versioned `GeometryMap` containing neutral series identity, acquisition plane,
slice normal, patient-space position, patient right/left and superior/inferior
order, neutral sagittal and axial group identity and bounds, cross-series intersections,
nearest corresponding slices, optional high-confidence semantic sequence label,
and validation state.

### Available Tools

- pydicom metadata;
- local DICOM geometry utilities;
- SimpleITK/VTK transforms in their existing isolated execution domains;
- the Fast Viewer synchronization geometry service when a read-only immutable
  geometry result is sufficient;
- session artifact and manifest writers.

### DICOM Workstation Capabilities

The workstation can determine plane, ordering, patient side, physical distance,
line/plane intersection, and nearest cross-series slice when coordinate frames
are compatible. It splits an axial acquisition into internally contiguous
groups using physical slice gaps. It also partitions sagittal planes into
persistent patient-space lateral/central regions while keeping those regions
semantically unnamed. It can state that frames or planes belong together, but
that fact alone does not identify a vertebral level, foramen, paracentral plane,
or sequence.

### LLM Role

None for deterministic geometry. An LLM may not redefine patient side, reorder
instances, or invent a spatial correspondence.

### Deterministic Processing

- normalize orientation vectors and reject invalid direction cosines;
- order slices by projection onto the slice normal, not filename or instance
  number;
- preserve raw and canonical order in the audit;
- assign stable neutral identifiers such as `sagittal-series-a`,
  `sagittal-group-02`, and `axial-group-03` before semantic anatomy is known;
- derive sagittal-group membership from projection onto the DICOM slice normal,
  never from filenames, instance numbers, or a presumed T1/T2 label;
- split axial groups from measured physical gaps without assigning level names;
- expose a semantic sequence label only for operator-confirmed or
  high-confidence classification; otherwise expose `semantic_label: null`;
- require compatible frame-of-reference and bounded separation for a claimed
  cross-series correspondence;
- record all transforms and tolerances.
- render each geometry group as an independent block and paginate only at group
  boundaries; an axial or sagittal group is never visually merged into the
  next group merely to fill a page.

### Fallback Logic

Missing or inconsistent geometry produces `not_assessable` or stops the gate.
Screen order, file order, guessed sequence names, and guessed level names are not
geometry fallbacks.

### Known Limitations

DICOM geometry does not identify named vertebral levels, a true anatomical
midline, foraminal boundaries, pedicles, or pathology. Different frames of
reference may require registration rather than nearest-slice projection.

### Optimization Opportunities

- reusable immutable geometry maps keyed by series identity;
- validated registration for incompatible frames of reference;
- landmark-assisted anatomical axes;
- deterministic quality scores for spacing, obliquity, and correspondence.

### Validation Method

Synthetic orientation/ordering tests, pixel-to-patient round trips, known
intersection cases, duplicate/sparse-stack rejection, and saved-manifest review.

## 5. Stage 2 — Anatomical Localization / Site Recognition

### Objective

Assign stable anatomical names and site roles to geometry-validated source
images without assessing normality or pathology.

### Input

- validated `GeometryMap`;
- task-neutral correlated source atlas with neutral series plus sagittal- and
  axial-group IDs;
- body-part anatomical configuration and expected sites.

### Output

A versioned `AnatomicalMap` with explicit neutral-series-to-sequence assignment,
neutral-sagittal-group-to-regional-role assignment,
neutral-axial-group-to-level assignment, exact source tile identity, named site,
side, plane/position role, correspondence links, authority, confidence, and
validation outcome.

### Available Tools

- local DICOM geometry and cross-series sync;
- protocol configuration and measured slab boundaries;
- optional locally validated anatomical landmark or segmentation services;
- bounded Gemini anatomy-only mapping when deterministic landmarks are absent.

### DICOM Workstation Capabilities

The workstation supplies correct patient-space order and validates whether a
model-selected source belongs to the claimed neutral series and immutable
sagittal or axial group. After the model assigns sequence semantics, it can pair T1/T2 planes by
physical distance and constrain candidate axial images without reassigning their
anatomical roles from Z order.

### LLM Role

Assign unresolved T1/T2 sequence roles, assign every neutral sagittal group to
`right_lateral`, `central`, or `left_lateral`, assign each neutral axial group
to a lumbar level, and select anatomical slice roles where local landmarks
cannot yet do so. The prompt forbids normality, pathology, severity, or
diagnostic language.

### Deterministic Processing

- validate exact tile, neutral series identity, and neutral group membership;
- reject duplicate sequence assignments, duplicate levels, duplicate groups,
  cross-series references, and tiles moved across measured group boundaries;
- use DICOM LPS X to correct right/left sagittal labels without moving source
  members or the selected midline; reject ambiguous side or T1/T2 group conflicts;
- record superior-to-inferior axial order without inferring levels or slice roles;
- enforce T1/T2 pair-distance and axial-slab bounds;
- retain model-assigned axial anatomical roles while recording their physical
  superior-to-inferior order separately;
- sort completed cards by named level only after the anatomy map is validated.
- render the Gate 1-to-2 card from immutable group membership. Every meaningful
  sagittal region and every axial acquisition group receives its own row or
  block with at least 32 pixels of whitespace before the next group.
- persist the block bounding boxes, tile identities, geometry-group IDs, and
  grouping-signal hierarchy in the card JSON sidecar.

### Fallback Logic

An incomplete or contradictory anatomical map stops the analysis. The system
does not fall back to independent level counting in later stages.

### Known Limitations

Lumbar level and low-confidence sequence naming remain model-assisted unless a
validated landmark or metadata method establishes them. Geometry-group identity
does not prove level identity. Axial sample roles are bounded within a measured
group but are not inferred from Z order and remain dependent on anatomical
recognition.

### Optimization Opportunities

- local sacrum/vertebra landmark validation;
- anatomical midline from posterior vertebral body and spinous-process
  landmarks;
- confidence-calibrated landmark fusion;
- operator correction of one landmark with deterministic propagation.

### Validation Method

Exact source-identity guards, DICOM-LPS canonicalization tests, physical-gap
grouping tests, pair-distance tests, arbitrary group-to-level permutation tests,
sequence-confidence tests, and radiologist review of saved maps.

## 6. Standard geometry and anatomical output

The schema evolves by version. Geometry and semantics remain separate. A
simplified geometry-first example is:

```json
{
  "schema_version": "1.4.0",
  "modality": "mri",
  "body_part": "lumbar_spine",
  "series_contract": {
    "sagittal-series-a": {
      "plane": "sagittal",
      "semantic_label": null,
      "semantic_confidence": "low"
    }
  },
  "geometry_groups": {
    "sagittal": [
      {
        "group_id": "sagittal-group-01",
        "meaning": "geometry_only_unlabelled_sagittal_region",
        "series_members": {
          "sagittal-series-a": {"source_slices": [1, 2, 3]}
        }
      }
    ],
    "axial": [
      {"group_id": "axial-group-01", "axial_frames": [1, 4]},
      {"group_id": "axial-group-02", "axial_frames": [5, 8]}
    ]
  }
}
```

The anatomy mapper then produces a separate validated semantic assignment:

```json
{
  "schema_version": "1.5.0",
  "sequence_assignments": {
    "sagittal_t2": {
      "series_id": "sagittal-series-a",
      "confidence": "high"
    }
  },
  "sagittal_group_assignments": [
    {
      "group_id": "sagittal-group-01",
      "anatomical_role": "right_lateral",
      "confidence": "high"
    }
  ],
  "axial_levels": [
    {
      "axial_group_id": "axial-group-02",
      "level": "L4-L5",
      "axial_frames": [5, 8]
    }
  ]
}
```

No patient name, external path, or transport credential belongs in this
contract.

## 7. Stage 3 — Screening Cards and Normal-vs-Abnormal Screening

### Objective

Determine whether each bound anatomical target is normal or abnormal with high
sensitivity, without diagnosing the abnormality.

### Input

- validated `AnatomicalMap`;
- one registry-selected task-specific screening card;
- exact source-image and geometry sidecar.

### Output

For each allowed structure: assessment, confidence, visual salience,
adjacent-slice persistence, and exact evidence locations. A normal target is not
forwarded to diagnosis. An abnormal target becomes a diagnosis-card request.

### Available Tools

- central Card Template Registry;
- anatomy-card renderer and JSON sidecars;
- Gemini through the shared GapGPT bridge;
- local schema, source-identity, and domain validators;
- parallel bounded request orchestration.

### DICOM Workstation Capabilities

Local code chooses only sequences and positions declared by the template,
renders patient-side/level labels from validated anatomy, and preserves source
identity. It does not ask Gemini to reconstruct geometry. The card remains
self-explanatory in grayscale because physical blocks, not border color, carry
group membership.

### LLM Role

Normal/abnormal assessment only. The model reports location and persistence but
does not name disc morphology, stenosis, neural effect, Modic type, or grade.

### Deterministic Processing

- one card and one request per template;
- temperature 0 for the current lumbar screening stages;
- allowlisted structures and output keys;
- no cross-domain rows;
- exact request/card/anatomy identity validation;
- physical group separation as the primary visual contract, section headers as
  the secondary contract, and color only as a tertiary cue;
- local merge preserves provenance and never promotes invalid output.

### Fallback Logic

An unstructured, truncated, cross-domain, or identity-invalid response fails
that gate and stops the analysis. It is not interpreted as a normal screen and
does not invoke the historical monolithic screen.

### Known Limitations

A false-negative screen prevents diagnosis-card generation. Very small signal
abnormalities may remain sampling-limited. Anatomy-map error can still bind the
wrong level even if the screening decision is visually reasonable.

### Optimization Opportunities

- radiologist-adjudicated sensitivity calibration by target;
- deterministic minimum coverage for critical targets;
- image-resolution and sequence additions controlled by template version;
- repeated frozen-input evaluation of model variance;
- local segmentation or quantitative candidate generation where validated.

### Validation Method

Contract tests, exact image/JSON audit, frozen-card repeated runs, per-target
recall/false-positive scoring, failed-request rate, latency, tokens, and
multi-case radiologist adjudication.

## 8. Stage 4 — Diagnostic Card Generation

### Objective

Build the smallest complete evidence package that can classify one
screening-positive anatomical target.

### Input

- one validated abnormal screening attention record;
- `GeometryMap` and `AnatomicalMap`;
- matching diagnosis template;
- source DICOM-derived evidence.

### Output

One immutable diagnosis PNG and one matching JSON sidecar containing card ID,
template ID, task, target, level/side, exact source images, sequence and geometry
roles, attention IDs, sampling, crop bounds, and limitations.

### Available Tools

- Card Template Registry;
- focus planner, crop renderer, and evidence budget validator;
- DICOM patient-space projection and correspondence;
- session-local atomic artifact writer.

### DICOM Workstation Capabilities

The workstation binds the card to one level/target, selects/crops source images
using validated geometry, pairs corresponding sequences, and annotates identity
outside diagnostic anatomy.

### LLM Role

None in deterministic card construction. Model-proposed screening attention may
select a candidate, but local code owns the actual source binding and rendering.

### Deterministic Processing

- exact registry lookup; no nearest-template substitution;
- task-specific sequence and position allowlist;
- bounded resolution, pixel, byte, and image budgets;
- stable layout and patient-side labels;
- one sidecar immediately bound to one image;
- normal targets are excluded.

### Fallback Logic

Missing required evidence or an invalid identity makes the target
`not_assessable` or stops card construction. The renderer does not replace a
required sequence with unrelated images.

### Known Limitations

Tight crops can hide migration or wider context, while wide crops can cause
level bleed. The template must preserve both defining morphology and sufficient
context. A sequence absent from the acquisition cannot be synthesized.

### Optimization Opportunities

- task-specific tight-plus-context layouts;
- anatomy-aware adaptive crops;
- quantitative measurements with validated local tools;
- salience-aware evidence budgets without dropping critical coverage;
- direct use of validated landmarks rather than model-selected anchors.

### Validation Method

Pixel/source identity checks, geometry round trips, crop/sampling manifests,
budget tests, visual card QA, and frozen-card diagnostic experiments.

## 9. Stage 5 — Pathology Diagnosis / Classification

### Objective

Confirm or reject abnormality and classify one bound target with high
specificity and positive predictive value.

### Input

- exactly one diagnosis card and its immediately bound JSON sidecar;
- one structure-group diagnostic rubric;
- bounded clinical context when relevant.

### Output

Card-bound diagnosis, morphology, signal abnormality, laterality, anatomical
effect, severity, limitations, not-assessable fields, evidence citations, and a
status such as confirmed, refined, reclassified, rejected, or indeterminate.

### Available Tools

- GPT-5.6 Sol through the shared GapGPT bridge;
- registry-derived structure profile;
- local identity/schema validator;
- deterministic report merger and review gate.

### DICOM Workstation Capabilities

The workstation supplies authoritative identity and geometry, enforces allowed
structures, and merges only validated decisions. It does not let prose move a
finding to another level or side.

### LLM Role

Challenge the screening-positive target, consider normal as a differential,
classify pathology and morphology, determine effects and severity, and cite the
provided evidence. It does not perform a second whole-study screen.

### Deterministic Processing

- one card per request with bounded parallelism;
- exact card/level/group/attention validation;
- invalid or omitted identity becomes indeterminate;
- deterministic level-ordered report assembly;
- review-required state for failed or conflicting decisions.

### Fallback Logic

One failed card may be retained as indeterminate when sibling cards completed.
If no diagnostic card completes, the analysis fails visibly. The historical
single-request verifier is not called.

### Known Limitations

General vision-language models remain variable on subtle MRI morphology and
grading. A correct diagnosis card does not guarantee a correct classification.
Clinical performance is not established from prompt or contract tests.

### Optimization Opportunities

- frozen-card repeated experiments;
- concise structure-specific rubrics;
- calibrated quantitative measurements;
- targeted expert models or segmentation/classification tools;
- ensemble or adjudication only after measured benefit.

### Validation Method

Radiologist-adjudicated multi-case evaluation of level, side, morphology,
signal, compartment, root relationship, severity, false positives,
not-assessable decisions, variance, failures, latency, and cost.

## 10. Central Card Template Registry

The current registry hierarchy is:

```text
MRI
└── Lumbar Spine
    ├── Screening
    │   ├── Disc
    │   ├── Canal / Neural
    │   ├── Neural Foramen
    │   ├── Bone Marrow / Endplate
    │   └── Facet / Posterior Elements
    └── Diagnosis
        ├── Disc
        ├── Canal / Nerve Root
        ├── Neural Foramen
        ├── Bone Marrow / Endplate
        └── Facet / Posterior Elements
```

Registry records are frozen and have a unique identity such as
`mri.lumbar_spine.screening.disc`. Exact lookup fails closed; there is no
automatic substitution between families, targets, modalities, or body parts.

Every template declares:

- family and decision question;
- anatomical targets;
- required sequence roles;
- sagittal and axial geometry roles;
- allowed output fields;
- model-specific task instruction;
- stable presentation layout parameters.

## 11. Lumbar screening templates

| Template | Required evidence | Screening question |
|---|---|---|
| Disc | The complete central sagittal T2 geometry group; every complete anatomy-confirmed axial T2 geometry group in a separate row | Is the bound disc normal or abnormal? |
| Canal / Neural | The complete central sagittal T2 geometry group; every complete anatomy-confirmed axial T2 geometry group in a separate row; up to two optional identity-checked MR-myelography overview images | Are canal, recess, or neural structures normal or abnormal, assessed independently? |
| Neural Foramen | Complete right- and left-lateral sagittal geometry groups for T2 and again for T1; every complete axial T2 geometry group in a separate row | Is either bound foramen normal or abnormal? |
| Bone Marrow / Endplate | Complete central sagittal T1 and T2 geometry groups, interleaved by source order where correspondence is available | Are marrow, vertebral body, or endplates normal or abnormal? |
| Facet / Posterior Elements | For each of T2 and T1: complete right-lateral, central, and left-lateral geometry groups; every complete axial T2 geometry group in a separate row | Are facets, ligament, posterior elements, alignment, or paraspinal tissues normal or abnormal? |

These five cards are separate model requests. Foramen and posterior elements are
not combined, because their strongest sequences, visual questions, and failure
modes differ. Pipeline 8.2.0 changes group transport integrity only: screening
cards expose complete immutable groups, while task-specific diagnostic cards
record selected subsets against their complete parent contracts. It does not
change the five-gate order, normal/abnormal screening semantics, model ownership,
or diagnostic classification responsibility.

## 12. Lumbar diagnosis templates

| Template | Primary classification responsibility |
|---|---|
| Disc | Bulge, protrusion, extrusion, migration, annular fissure, signal, zone/laterality, and disc contribution |
| Canal / Nerve Root | Central canal, lateral recess, root contact, deviation, compression, and relevant severity |
| Neural Foramen | Foraminal caliber, perineural fat, exiting root, side, and contributing structures |
| Bone Marrow / Endplate | T1/T2 signal, endplate surface and morphology, Modic pattern, fracture/infection/replacement differentials |
| Facet / Posterior Elements | Facet degeneration/hypertrophy/effusion, ligamentum flavum, posterior osseous structures, alignment, and soft tissues |

Diagnosis templates are created only for positive screening targets. Their
source evidence may overlap, but their question, identity, output schema, and
model request remain independent.

## 13. Body-part configuration contract

A future MRI body-part package supplies configuration rather than a replacement
pipeline:

```text
BodyPartMRIConfig
  series-role rules
  geometry tolerances
  expected anatomical sites
  anatomical-map schema extension
  screening templates
  diagnosis templates
  grading and terminology rubrics
  evidence budgets
  validation cohort and acceptance thresholds
```

Brain, cervical spine, knee, shoulder, and other MRI protocols should register
their templates under the same modality/family hierarchy and use the same five
gates.

## 14. Versioning and change control

- Geometry/anatomy schema, card template, screening, diagnosis, and pipeline
  versions are independent and recorded in artifacts.
- A layout, required-sequence, target, or output-contract change requires a
  template or schema version change and a structural guard.
- Prompt-only changes require frozen-input repeated evaluation.
- Geometry changes require deterministic geometry tests before any model call.
- A favorable case may establish a hypothesis, never promotion.
- Promotion requires a locked radiologist-adjudicated multi-case cohort and no
  material regression in critical-finding recall, identity, or review-gate
  behavior.

## 15. Historical document status

The following documents remain as implementation evidence, not current
architectural authority:

| Document | Status |
|---|---|
| `docs/plans/EAGLE_EYE_LUMBAR_CURRENT_STATE_2026-09-02.md` | Historical snapshot of the pre-registry lumbar implementation |
| `docs/plans/EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE_2026-09-02.md` | Historical implementation record for pipeline 7.7.0 |
| `docs/plans/EAGLE_EYE_FOCUSED_V3_MORPHOLOGY_RESEARCH_PLAN_2026-08-31.md` | Historical experiment/research plan |
| `docs/plans/EAGLE_EYE_LLM_PROMPT_DRAFT_2026-08-26.md` | Deprecated prompt draft |
| `docs/plans/EAGLE_EYE_LLM_STAGE2_2026-08-26.md` | Historical stage design |
| `docs/plans/EAGLE_EYE_LUMBAR_STAGE1_2026-08-26.md` | Historical stage design |

They must not be used to restore monolithic screening, level-only cards,
model-owned DICOM geometry, or automatic historical fallback.

## 16. Current engineering conclusion

Pipeline 8.2.0 implements geometry-first neutral grouping before semantic
anatomical mapping. Persistent sagittal and axial group identities are rendered
on the anatomy atlas, validated in the anatomy-only response, and reused in the
screening and diagnosis card JSON and labels. Gate 1 atlas pages and Gate 1-to-2
cards now carry complete immutable group membership and communicate grouping
through separate rows/blocks and physical whitespace even when color is removed.
Diagnostic cards may use a bounded subset, but every selected member carries its
parent group ID and full original membership and is rejected if it moved across
a boundary. Disc and canal separate every axial group; foramen separates
bilateral T2 and T1 lateral groups; posterior elements separate right-lateral,
central, and left-lateral groups for both sequences. It keeps the five registry-derived
screening tasks and the atomic diagnosis path while preventing group order,
low-confidence sequence classification, or physical-order shortcuts from
becoming false anatomical truth. This is an architecture and auditability
improvement, not proof of diagnostic accuracy. The next clinical step is a
restarted source-build run followed by a frozen, repeated,
radiologist-adjudicated multi-case comparison.

## 17. Central-canal specificity and MR-myelography context (pipeline 8.3.0)

The live 8.2.0 canal screen emitted an L4-L5 `central_canal` abnormality and a
separate bilateral `lateral_recess` abnormality from the correct immutable
axial group. Its raw response cited two axial tiles and one sagittal tile but
stored no visual basis, caliber assessment, or CSF observation. Geometry and
card membership were intact; the contract could neither explain nor prevent a
minor ventral contour impression from becoming a generic central-canal positive.

Pipeline 8.3.0 changes only this screening boundary. The response contains one
`central_canal_observations` row for every mapped axial group, including exact
group identity, same-group axial evidence, caliber, CSF visibility, bounded
visual basis, optional myelographic correlation, and a short source-grounded
reason. Local validation rejects a central-canal positive when the observation
says preserved caliber or minor impression only. Lateral recess, foramen, root,
and disc decisions remain independent. Preserved CSF is not an unconditional
veto when there is reproducible caliber reduction or a directly visible non-
stenotic intracanal abnormality.

The worker may discover at most two series explicitly identified as MR
myelography. It validates study, series, modality, pixel bounds, and burned-in
annotation status before decoding one overview per series. These images occupy
a visibly separate card section and have `localization_allowed=false`. They
support level-to-level CSF-column comparison but cannot name a level, change an
axial group, or override level-bound axial T2 evidence. Absence is not a
protocol deficiency. This follows the qualitative distinction in Lee et al.
(DOI `10.1007/s00256-011-1102-x`) and "Using Magnetic Resonance Myelography to
Improve Interobserver Agreement in the Evaluation of Lumbar Spinal Canal
Stenosis and Root Compression" (PMC5401833).

Exact myelography source files, series/instance identities, and frame indices
are retained only in `canal_context_sources.local.json` beside the card. The
model-facing metadata contains neutral source keys and frame indices, not local
paths or DICOM identities.
