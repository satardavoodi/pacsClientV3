# Eagle Eye Lumbar — Current State and Decision Record

Date: 2026-09-02
Status: **historical implementation snapshot; superseded for architecture**
Current authority: `docs/pipelines/eagle-eye-mri.md`
Authority at time of writing: measured historical conclusions and next gates
Current runtime: pipeline 7.7.0, atomic contract 1.8.0
Anatomy map/card schema: 1.2.0; screening atlas manifest: 1.2.0
Atomic screening schema: 3.2.0; atomic diagnosis schema: 1.2.0
Clinical status: experimental; no diagnostic-accuracy claim

## Read this first

This document records the pre-registry pipeline 7.7.0 state. It remains useful
as implementation and experiment evidence, but it is not the current
architectural source of truth. Do not use it to restore four combined screening
cards or another historical transport path.

The current implementation is documented in
`EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE_2026-09-02.md`. New design decisions should
update this decision record before adding another pipeline version.

## Current runtime in one page

1. One correlated DICOM atlas is prepared from sagittal T2, sagittal T1, and
   axial T2 sources.
2. One normality-free and diagnosis-free Gemini request selects five distinct
   sagittal source planes in T1/T2 and maps all six measured axial slabs. Local
   code validates every proposed tile, then uses DICOM LPS X to assign the five
   patient-right-to-left sagittal roles and DICOM LPS Z to assign the selected
   axial samples in superior-to-inferior order. The model never owns sagittal
   laterality or axial role order.
3. Local code saves four anatomy cards and JSON sidecars: disc, canal/neural,
   endplate/marrow, and foraminal plus posterior elements.
4. Four compact diagnosis-free Gemini requests run concurrently at temperature
   0. Each receives
   exactly one matching anatomy card, not the raw atlas. Gate 1 owns level and
   plane identity; Gate 2 owns only abnormality presence, anatomical structure,
   level, visual magnitude, persistence, and correspondence. It cannot classify
   morphology or zone, name stenosis, describe space effacement, or label
   neural contact, displacement, or compression. Five anatomical domains
   remain separate after validation.
5. Local code validates card identities and geometry, removes cross-domain
   output, and groups positive attention by `(level, structure_group)`.
6. The renderer creates one diagnostic anatomy-specific card per positive group. It does
   not send a universal thirteen-tile level card.
7. GPT-5.6 Sol receives exactly one card, its JSON, and a sanitized clinical
   prior per request. It does not receive the global screening list. The compact
   screening handoff contains no diagnostic descriptors, and a disc card
   classifies only the disc. Canal, recess, and root diagnosis requires its own
   independently raised canal/neural card.
8. Up to three card decisions run concurrently. Local code rejects a mismatched
   card ID, level, structure group, attention ID, duplicate, missing positive
   finding, or invalid status before merge.
9. Accepted decisions are merged deterministically. Missing or conflicting work
   is `INDETERMINATE` and review-required, never silently moved to another card.
10. The result window exposes a non-modal `View stage images` audit gallery. It
   reads immutable session artifacts and shows the source atlas used for anatomy
   mapping, all four intermediate anatomy cards, the exact one-card input sent
   to each screening branch, session-local context images, every
   gated diagnostic card, and the diagnostic request image set.
   The authoritative axial level ranges are retained in the aggregate stage-one
   JSON, so the first tab can show the mapped frames beside the source atlas.

Default evidence mode remains `focused-v5-level-cards`. Atomic dispatch is
default-on and has no automatic fallback to monolithic screening or
verification. `AIPACS_EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE=0` is an explicit
operator kill switch that selects the historical route before analysis.

## What the previous runs established

The comparative historical data are useful for failure analysis, not for
estimating a population accuracy rate. Twenty-three scored runs used one
reference case across thirteen evolving pipeline versions. Multiple variables
often changed together, the scorer had known parsing defects, and several
negative reference labels were not independently adjudicated. The subsequent
7.0.0 and 7.1.0 live runs are recorded as operational truncation/fallback
evidence, not as additional diagnostic-accuracy samples.

Within those limits, the following conclusions are strong enough to guide work:

### Stable engineering gains

- Physical ROI cropping increased axial and sagittal sampling materially. The
  model's stated morphology reasoning changed when the defining parasagittal
  plane became visible.
- Same-slab window backfill fixed a real coverage defect that had dropped an
  inferior slice.
- DICOM geometry, volume order, sagittal offsets, atlas tile identity, and
  source-frame audit removed several silent identity assumptions.
- The level/card review gate is valuable independently of diagnostic accuracy;
  it prevented a broken level assignment from being presented as verified.
- Explicit card JSON, crop/sampling manifests, and per-request artifacts made
  failures reproducible rather than anecdotal.

These mechanisms should be retained unless a replacement proves the same
coverage and identity properties.

### Results that did not demonstrate convergence

- No historical run matched all four adjudicated attributes of the principal
  disc finding: side, morphology, root effect, and severity.
- The best observed runs reached two of four attributes, in different
  combinations.
- Across the fifteen focused-V3-or-later runs, hand-checked report prose called
  the reference side in 10/15, extrusion in 3/15, and compression in 4/15.
  Severe narrowing was never reproduced. These are case-specific stability
  counts, not sensitivity or specificity estimates.
- A favorable pipeline-5.3 run simultaneously corrected level, side, morphology,
  and migration, but still undercalled neural effect and missed quieter sagittal
  findings. Later versions did not preserve the combination reliably.
- Increasing prompt length, card complexity, and the number of jointly reviewed
  structures did not produce monotonic improvement. The last combined level-card
  runs introduced new level assignment, laterality, false-positive posterior
  element, and missing-level-map failures.
- The first live 7.0.0 run did not test atomic diagnosis: four of five Gemini
  screens reached 5996/6000 completion tokens, returned truncated JSON, and
  produced no diagnostic cards. The only parseable request was an empty
  foraminal screen. The review gate correctly blocked the resulting empty
  overview report, but the run exposed an output-budget and fallback defect.
- Live pipeline 7.1.0 session `20260902T074642Z` repeated the failure after
  grouping and evidence allowlisting: all three focused screens reached
  5996/6000 completion tokens and stopped while emitting incomplete JSON. Two
  visible responses contained only the opening level map and no finding row.
  The bounded monolithic fallback completed, created eight cards, and sent all
  eight to the legacy verifier. The run therefore did not exercise atomic
  one-card diagnosis and must not be used as evidence for or against it.

### Hypotheses not yet proven

- Clinical context may improve differential prioritization, but its independent
  contribution was never isolated while pixels, prompts, and evidence modes were
  changing.
- Temperature was not compared on a frozen atlas with repeated samples.
- More images are not automatically harmful; irrelevant or ambiguously bound
  images are harmful. The new architecture tests this distinction by reducing
  each request to one anatomical decision.
- Anatomy-specific atomic requests may reduce anchoring and cognitive load, but
  no multi-case benchmark has yet shown that they improve clinical accuracy.

## What was cleaned up in pipeline 7.0

- The unused fixed five-pair level-card renderer was removed. The current
  renderer is structure-specific and dynamically sized.
- Atomic screening no longer produces or requires Gemini-owned card templates;
  local geometry owns card assembly. The old requirement remains only in the
  monolithic fallback contract.
- Card JSON checklists contain only the card's permitted anatomical structures.
  A disc card no longer carries normal/unknown facet, foraminal, endplate, or
  canal checklist entries.
- Aggregate stage request files no longer duplicate unsent monolithic prompts,
  images, or context. They explicitly identify themselves as local merge records
  and point to the exact `.atomic_analysis` subrequests.
- Historical evidence modes and long prompts remain only because benchmark
  reproduction and bounded rollback still require them. They are not ordinary
  runtime choices and should not receive new features.
- Pipeline 7.1.0 replaces the five screening calls with three focused,
  temperature-0.2, JSON-only requests while retaining the established
  6000-token safety ceiling for each request. The design targets lower expected
  output and less multitask competition, not a smaller maximum allowance. A truncated or unstructured
  request group is now a failed request, not an empty result. The complete
  bounded monolithic screening path is used as a fallback and all discarded
  atomic usage remains in the cost audit.
- Pipeline 7.2.0 / atomic contract 1.3.0 kept the same prompts, temperatures,
  image allowlists, image budget, and failure policy. It raises focused Gemini
  output headroom from 6000 to 24000 tokens because provider reasoning and
  visible JSON share that allowance, and raises each one-card diagnostic
  allowance from 6000 to 12000. This is bounded transport headroom, not a request
  for longer prose. It also adds a read-only stage-image gallery; no image is
  recaptured or newly sent when the gallery opens. The aggregate atomic result
  now retains the machine-readable axial `level_map` used by the handoff.
- Pipeline 7.3.0 / atomic contract 1.4.0 introduced the missing anatomy gate. The
  full atlas goes only to a normality-free anatomy mapper. Local code validates
  its source-tile and DICOM-geometry assignments, saves three anatomy cards and
  JSON sidecars, and sends exactly one matching card to each pathology screen.
- The first live 7.3.0 run exposed two defects: concrete example IDs in the
  mapping prompt were repeated by Gemini, and rejection of the resulting
  patient-right-to-left order conflict automatically invoked the historical
  monolithic pipeline. The run therefore did not test the requested three-gate
  route and again exchanged the dominant L5-S1 lesion with L4-L5.
- Pipeline 7.4.0 / atomic contract 1.5.0 removes numeric source-ID examples,
  makes DICOM LPS geometry the sole sagittal right/left ordering authority, and
  records proposed versus canonical bindings. Gate 1 or Gate 2 failure,
  diagnostic-card construction failure, and an all-card Gate 3 failure now stop
  visibly. None invokes the old monolithic screening or verifier.
- Pipeline 7.5.0 / atomic contract 1.6.0 keeps the same anatomy cards, image
  dimensions, sequence selection, and request topology. Both pathology
  screening and diagnosis use temperature 0. The disc screen must explicitly
  clear the central canal, both lateral recesses, and both traversing roots for
  every abnormal disc level; abnormal companion observations require separate
  location-bound screening rows. A disc diagnostic card independently accepts
  or rejects those five companion questions even when screening supplied no
  positive candidate. Endplate findings require an exact vertebra and
  superior/inferior surface, with Modic II requiring matched T1/T2 fatty-marrow
  evidence. Ligamentum flavum hypertrophy requires reproducibility on adjacent
  axial slices plus objective thickening or a canal/recess effect; isolated
  prominence or buckling is rejected or left indeterminate.
- The live 7.5.0 run showed why that companion contract was wrong for this
  architecture. With unchanged source slots, Gate 2 embedded disc zone and
  neural-effect interpretation in the screening row, produced a contradictory
  disc/companion combination, and the final morphology changed. The failure
  was semantic task competition rather than missing evidence.
- Pipeline 7.6.0 / atomic contract 1.7.0 / screening schema 3.2.0 / diagnosis
  schema 1.2.0 removes the 7.5 companion experiment. Gemini outputs only the
  abnormal structure, immutable level, confidence, visual abnormality
  magnitude, persistence, and evidence locations. Disc and central-canal rows
  use `laterality=not_applicable`; paired structures may use laterality only as
  anatomical identity. Local validation rejects diagnostic fields. Compact
  card metadata omits screening laterality, interpreted features, priority, and
  companion questions. Sol receives one exact structure task and independently
  assigns diagnosis, morphology, zone, side, severity, and effects.
- The live 7.6.0 comparison used byte-identical atlas pages across three runs,
  yet the anatomy mapper cyclically reassigned the same axial samples among
  disc-level, subarticular, and infrapedicular roles. The combined disc/canal
  screen then emitted disc abnormalities but no canal, lateral-recess, or root
  abnormality. An essentially identical L5-S1 disc diagnostic card also changed
  from extrusion to protrusion, proving that this morphology variance was not
  caused by recapture or missing pixels.
- Pipeline 7.7.0 / atomic contract 1.8.0 / anatomy schema 1.2.0 corrects the two
  deterministic upstream defects without changing diagnostic crops or the Sol
  prompt. Local DICOM patient-Z geometry canonicalizes the model-selected axial
  samples into superior-to-inferior disc-level, subarticular, and
  infrapedicular roles. Disc and canal/neural screening now use separate cards
  and independent Gemini requests, so a disc-positive response cannot consume
  the canal/recess/root screening task. Proposed and canonical axial bindings
  remain in the audit manifest.

## Decision rules from now on

1. Freeze pipeline 7.7.0 after the requested live verification. Do not create
   another clinical prompt version from one favorable or unfavorable run.
2. A change must state whether it targets screening recall, localization,
   geometry, diagnostic classification, grading, or report assembly. Do not
   move several layers in one experiment.
3. Compare frozen inputs. Repeated live recapture is not an A/B test because UI
   state and captured pixels may change.
4. Score per attribute, not one morphology label per level. Disc bulge and focal
   herniation can coexist. Root side, contact, deviation, and compression are
   separate fields.
5. Failed requests and review-required results remain in the denominator.
6. No normal label counts as a benchmark negative until a radiologist explicitly
   adjudicates it.
7. Promote only a measured multi-case improvement with no material regression in
   critical-findings recall, level identity, or review-gate behavior.

## Next experiment

Use at least three radiologist-adjudicated lumbar studies initially, then expand
before a clinical claim. Include one simple focal disc case, one multilevel
degenerative/scoliotic case, and one non-disc or postoperative/oncologic case.
Freeze the source atlas and compare:

- pipeline 7.7.0 anatomy mapping, four one-card screens, and atomic diagnostic cards;
- frozen historical outputs from 5.3.0 and 4.6.1 as offline baselines only.

Run repeated samples per candidate with fixed model IDs and temperature. Measure
screening abnormality recall, localization, level, side, morphology, compartment,
root relationship, grading, false positives, not-assessable decisions,
review-required rate, failed-request rate, latency, image count, and token cost.

Until that experiment is complete, the correct conclusion is: pipeline 7.7.0 is
a cleaner and more auditable hypothesis, not a proven diagnostic improvement.
