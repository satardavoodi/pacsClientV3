# Eagle Eye Lumbar Atomic Structure Pipeline

Date: 2026-09-02
Status: **historical 7.7.0 implementation record; superseded for architecture**
Current authority: `docs/pipelines/eagle-eye-mri.md`
Pipeline: `lumbar_pathology` 7.7.0
Atomic contract: 1.8.0
Anatomy map/card schema: 1.2.0
Screening atlas manifest: 1.2.0
Atomic screening schema: 3.2.0
Atomic diagnosis schema: 1.2.0
Evidence mode: `focused-v5-level-cards`

## Decision

The diagnostic unit is no longer “one lumbar level containing every visible
structure.” It is one anatomical question at one bound level. The pipeline uses
one anatomy-only Gemini mapping request followed by four bounded Gemini
screening requests, constructs one structure-specific
card for each positive focus, sends each card in an independent GPT-5.6 Sol
request, and merges only identity-valid structured decisions in local code.

This is a deliberate architecture experiment, not a clinical-accuracy claim.
The previous 23-run single-patient history showed that adding prompt length and
level-card complexity did not produce stable diagnostic convergence. Version
7.7.0 therefore separates anatomical identity, abnormality screening, and
diagnostic classification rather
than asking one model call to solve every lumbar compartment simultaneously.

## Runtime flow

1. The correlated DICOM atlas is built once from sagittal T2, sagittal T1, and
   axial T2 source series.
2. One temperature-0 Gemini request receives the complete atlas and performs
   anatomy mapping only. It selects five distinct sagittal source planes in T1
   and T2 and binds all six measured axial slabs to T12-L1 through L5-S1, with
   disc-level, subarticular, and infrapedicular samples inside each slab. It is
   forbidden to assess normality or pathology.
3. Local code validates exact atlas identity and DICOM geometry. DICOM LPS X,
   not the model or screen position, sorts the selected sagittal set and assigns
   patient-right foraminal, right paracentral, midline, left paracentral, and
   left foraminal roles. DICOM LPS Z independently sorts each model-selected
   axial triplet from superior to inferior and assigns disc-level,
   subarticular, and infrapedicular roles. The audit retains both proposed and
   canonical sagittal and axial bindings.
   Local code rejects an unknown or wrong-sequence tile, duplicate plane, T1/T2
   pair separated by more than 8 mm, changed measured slab, or axial sample
   outside its slab.
4. Four immutable Gate 1-to-2 PNG cards and JSON sidecars are rendered:

   | Anatomy card | Sagittal content | Axial content |
   |---|---|---|
   | Disc | right paracentral, midline, left paracentral T2 | all six levels, each with disc-level, subarticular, and infrapedicular T2 |
   | Canal/neural | right paracentral, midline, left paracentral T2 | all six levels, each with disc-level, subarticular, and infrapedicular T2 |
   | Endplate/marrow | matched right paracentral, midline, left paracentral T1/T2 | deliberately excluded |
   | Foraminal plus posterior elements | matched right foraminal, right paracentral, left paracentral, left foraminal T1/T2 | all six levels, each with three anatomical T2 samples |

5. Four Gemini pathology-screening requests run concurrently. Each receives
   exactly one matching anatomy card and its validated `ANATOMY_MAP_JSON`, uses
   temperature 0, and has a bounded 24000-token JSON-only response contract.
   The anatomy map is the sole level and plane authority; screening decides only
   abnormality presence, anatomical structure, level, visual magnitude,
   persistence, and cross-plane correspondence. It may not recount levels or
   return another level map. It may not classify disc morphology or zone, name
   stenosis, describe space effacement, or label neural contact, displacement,
   or compression. Disc, canal, recess, root, foramen, facet, endplate, and
   marrow abnormalities are independent rows rather than companion attributes.
6. Local normalization rejects cross-domain rows, remaps each request-local
   image identity to the stored anatomy-card identity, validates tile geometry,
   and produces one shared diagnosis-free attention contract.
7. The evidence planner groups by `(level, structure_group)`. A disc focus and
   facet focus at L5-S1 therefore become two cards rather than one mixed card.
8. The diagnostic renderer uses an anatomy-specific profile:

   | Card | Sagittal evidence | Axial evidence |
   |---|---|---|
   | Disc | right paracentral, midline, left paracentral T2 | disc-level, maximum-abnormality, caudal-extent T2 |
   | Endplate/marrow | matched T2/T1 at right paracentral, midline, left paracentral | maximum-abnormality T2 |
   | Canal/neural | matched T2/T1 at right paracentral, midline, left paracentral | three same-slab T2 samples |
   | Foraminal | matched T2/T1 at right and left foraminal planes | three same-slab T2 correlation samples |
   | Posterior elements | matched T2/T1 at right and left paracentral planes | three same-slab T2 samples |

9. GPT-5.6 Sol receives exactly one image and its immediately preceding
   `CARD_METADATA_JSON`. The atomic diagnostic prompt is restricted to that
   card's structure group and subject level. It receives the sanitized clinical
   prior but not the whole screening-attention list, because the card already
   carries its own bound attention IDs.
   Each atomic diagnostic request has a 12000-token response allowance. The
   higher ceiling is headroom for reasoning and structured completion, not a
   request for verbose output.
   The output structure must be one of the exact structures allowed for that
   card. A disc card classifies the disc only. Canal, lateral-recess, and
   nerve-root diagnosis occurs only on independently screened canal/neural
   cards, preventing a disc task from becoming a second multi-structure screen.
10. Up to three diagnostic card requests run concurrently. Local code then
   validates card ID, subject level, structure group, attention ID, and status.
   A conflicting or omitted identity becomes `INDETERMINATE`; it cannot enter
   the report as a positive finding.
11. The final report is assembled deterministically by level. Existing level-map,
   evidence-coverage, and cross-card citation guards remain active.

## Image transport settings

- The live GapGPT bridge uses the OpenAI-compatible Chat Completions image
  object and explicitly sends `detail="high"` for every Eagle Eye PNG. This is
  shared by Gemini screening and GPT-5.6 Sol diagnosis.
- OpenAI documents `low`, `high`, `original`, and `auto` for GPT-5.6 Sol.
  `high` preserves images within 2048 x 2048 pixels and 2500 32-pixel patches.
  The largest current diagnostic card is 1600 x 1050 pixels, or 1650 patches,
  so OpenAI's documented `high` preprocessing does not resize that card.
  Changing it to `original` would therefore not add source pixels to the
  current card layout.
- Google's native Gemini 3 API exposes per-image `media_resolution`, with
  `high` recommended for detailed image analysis and `ultra_high` available
  for selected per-item tasks. The current application does not call the
  native Gemini API: it sends an OpenAI-compatible `detail="high"` field through
  GapGPT. The bridge's mapping from that field to Gemini `media_resolution` is
  not documented or capability-verified, so the application must not claim a
  native Gemini resolution level from the outbound payload alone.
- The added anatomy-map request consumes the six-page atlas once. Each of the
  four screening calls then receives one purpose-built card instead of two or
  three raw atlas pages. This reduces screening image count and cognitive scope,
  but the additional request means lower total cost is not assumed.
  Live evaluation must record input/image, reasoning, output, latency, and
  fallback usage per request before making a cost claim.

Technical references: [OpenAI images and vision](https://developers.openai.com/api/docs/guides/images-vision),
[Google Gemini media resolution](https://ai.google.dev/gemini-api/docs/media-resolution).

Evidence-selection references: the
[ACR lumbar MRI accreditation parameters](https://accreditationsupport.acr.org/support/solutions/articles/11000061020-mri-exam-specific-parameters-spine-module-revised-5-10-2022-)
specify sagittal dark-fluid, sagittal bright-fluid, and axial fluid-sensitive
coverage for a complete lumbar examination. It does not prescribe VLM payload
selection; the narrower task-level allowlists are therefore an engineering
hypothesis to be tested, not an ACR recommendation. Foraminal grading literature uses
sagittal T1 as the main method because loss of perineural fat is a core feature,
with T2 as complementary evidence
([Jeong et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC5544375/)). Vertebral
endplate marrow recommendations treat T1 and T2 as foundational matched
sequences and fat-suppressed/STIR imaging as complementary
([ISSLS recommendations](https://pmc.ncbi.nlm.nih.gov/articles/PMC7205555/)).
The current atlas does not provide sagittal STIR, so 7.6.0 does not claim that
the T1/T2-only marrow screen is equivalent to a dedicated marrow protocol.

## Failure policy

- Atomic analysis is default-on. The V5 runtime has one path: anatomy gate,
  anatomy cards, pathology-screening gate, diagnostic cards, and diagnosis gate.
  `AIPACS_EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE=0` is an explicit operator kill
  switch that selects the historical route before analysis; it is not an
  automatic fallback.
- A truncated or unstructured Gemini request group is a failed request; it is
  never merged as an empty screen.
- An unstructured or geometrically invalid anatomy map produces no anatomy
  cards and stops the analysis. The historical monolithic screen is not called.
- If any grouped pathology-screening request fails, the analysis stops and the
  exact failed request artifacts remain available for review. The historical
  monolithic screen is not called.
- Failure to construct valid diagnostic cards stops the analysis. If every
  diagnostic card request fails, the historical verifier is not called.
- One failed or unstructured diagnostic card becomes a card-bound
  `INDETERMINATE` decision only when at least one sibling card completed, so a
  partial atomic report cannot silently omit the failed card.
- No model may move a card to another level or structure during merge.

## Live failure that led to 7.4.0

The first 7.3.0 source run successfully built a six-page correlated atlas, but
the anatomy mapper repeated the prompt's illustrative sagittal tile numbers.
For that acquisition, DICOM LPS X proved that the returned list was ordered in
the opposite patient-right-to-left direction. The validator correctly rejected
the map, but 7.3.0 then invoked the historical monolithic screen. That fallback
again exchanged the dominant L5-S1 lesion with the L4-L5 level and prevented the
new three-gate architecture from being tested.

Version 7.4.0 removed both causes. The prompt contains no concrete source tile
IDs, and local geometry canonicalizes the five selected sagittal planes. Any
remaining Gate 1, Gate 2, card-construction, or all-card Gate 3 failure is now a
visible failed analysis rather than a different pipeline producing a report.

## Live 7.5.0 regression and 7.6.0 correction

The first clinically useful three-gate output retained the dominant disc
morphology but omitted its right lateral-recess and right S1 consequences,
duplicated an imprecisely anchored endplate signal finding, and overcalled mild
ligamentum flavum prominence. The saved artifacts showed that these were
contract defects, not missing source pixels: Gate 2 stopped after the disc row,
Gate 3 was prohibited from creating an unproposed companion finding, endplate
rows lacked vertebral-surface identity, and the posterior-element threshold was
qualitative.

Pipeline 7.5.0 added neural companion attributes to every abnormal disc row and
five candidate-independent companion decisions to every disc diagnostic card.
A live run used the same source slots as the preceding run but changed the disc
morphology decision. The saved Gate 2 output also became internally
inconsistent: it encoded a neural relationship inside the disc row while the
companion structures were normal. This is evidence of task and semantic
competition, not evidence that the pixels regressed.

Pipeline 7.6.0 keeps every input image, crop, card dimension, evidence role,
output ceiling, temperature, and concurrency limit unchanged. It removes
diagnostic attributes and companion checklists from Gate 2 and strips
laterality, feature interpretation, and within-study priority from the compact
Sol handoff. The retained handoff is structure, level-bound attention identity,
normal/abnormal assessment, confidence, visual abnormality magnitude,
persistence, and source evidence. Gate 3 receives one bound structure question
and independently decides diagnosis, morphology, zone, side, severity, and
effects. Endplate identity and objective posterior-element thresholds remain.

## Live 7.6.0 instability and 7.7.0 correction

Three consecutive runs used byte-identical atlas pages, the same anatomy prompt,
the same Gemini preview model, and temperature 0. The 7.6.0 anatomy reply still
cyclically reassigned the same selected axial tiles among disc-level,
subarticular, and infrapedicular roles at every level. The local validator
proved only that each tile belonged to the measured slab, so model-owned role
order changed the intermediate anatomy card despite unchanged source pixels.

The same run's combined disc/canal/neural screen returned several disc findings
but no central-canal, lateral-recess, or nerve-root finding. Because positive
screening attention is the sole card-creation trigger, Gate 3 could not evaluate
the omitted neural consequences. Separately, an effectively pixel-identical
L5-S1 disc diagnostic card changed morphology between runs. That remaining Sol
variance is not attributed to image selection and must be tested with a frozen
card/prompt repetition experiment rather than another crop change.

Pipeline 7.7.0 corrects only the two deterministic upstream defects. DICOM LPS
Z now canonicalizes each model-selected axial triplet from superior to inferior,
with proposed and canonical bindings retained in the manifest. Disc and
canal/neural screening are separate one-card Gemini requests. Diagnostic card
pixels and the Sol prompt are unchanged so the later frozen-card experiment
remains interpretable.

## Audit artifacts

The aggregate stage files remain at `llm_stage<N>_*`. Every actual atomic model
request is also stored under:

```text
.atomic_analysis/
  stage1/anatomy_mapping_request.json
  stage1/anatomy_mapping_response.txt
  stage1/anatomy_mapping_structured.json
  stage1/screening_<request-group>_request.json
  stage1/screening_<request-group>_response.txt
  stage1/screening_<request-group>_structured.json
  stage3/card_<index>_<structure>_request.json
  stage3/card_<index>_<structure>_response.txt
  stage3/card_<index>_<structure>_structured.json
```

The four Gate 1-to-2 PNGs and JSON sidecars are stored under
`.evidence/anatomy-gate-v1/` with `anatomy_manifest.json`. Every grouped
screening request must reference exactly one of those cards.

The aggregate request records that it was not sent as one request, the domain or
card count, parallelism limit, failures, and artifact directory. Each card still
has its PNG, `.card.json`, manifest binding, crop/sampling audit, and source frame
identity.

The result panel includes `View stage images`. Its independent read-only gallery
shows the anatomy-mapping atlas and validated map, all four intermediate
anatomy cards, each grouped screening request's exact one-card input and
parse/truncation state, session-local context images,
every gated structure card with level/group/frame metadata, and the diagnostic
request image set. The gallery resolves only files contained by the selected
session; it does not open source DICOM paths, external attachment paths, or live
viewer widgets. The authoritative axial level ranges are also preserved as the
aggregate stage-one JSON `level_map`, instead of existing only in report prose.

## Verification completed

- `test_eagle_eye_anatomy_gate.py` failed at collection before the anatomy-card
  module existed. It now guards the diagnosis-free mapper, exact four-card
  contract, one-card screening boundary, saved manifest, cross-role rejection,
  and DICOM-Z-owned axial role order.
- The atomic regression file failed before the structure grouping existed and now
  covers request/domain boundaries, compact JSON prompts, truncation rejection,
  page renumbering, card profiles, card splitting, independent diagnostic
  prompts, identity rejection, and deterministic report merge.
- A headless orchestrator test verifies one anatomy-map call, four one-card
  Gemini screening calls, two independent
  one-image Sol calls, per-call artifacts, and deterministic merged output.
- Separate integration guards prove that an invalid anatomy map and a
  23996/24000 truncated grouped reply both stop without invoking the monolithic
  screening or verification stages.
- The 7.6 contract guards fail against the 7.5 implementation because the old
  prompt and schema still expose diagnostic fields and mandatory companions.
  The screening/card pair passes 39 tests; the adjacent
  screening/orchestration/anatomy/grading selection passes 153. Complete AI
  Imaging passes 889 tests with 8 pre-existing xfails and 3 existing SWIG
  warnings. Python compilation passes, builder package checks pass 4 with 4
  deselected, and all 462 plugin mirror pairs match.
- The 7.7 axial-order and four-request guards fail against 7.6. The initial
  two-file run produced 6 failures and 20 passes; after correction those files
  pass 27. The anatomy/atomic/LLM/audit boundary passes 136. Complete AI Imaging
  passes 900 tests with 8 pre-existing xfails and 3 existing SWIG warnings,
  default-build inclusion passes 3, and all 462 plugin mirror pairs match.

The live 7.1.0 session is fail-before evidence for the exhausted response
allowance. A new 7.7.0 source run remains required. No sensitivity or specificity
claim follows from this architecture correction.

## Required clinical experiment

Do not promote this architecture as more accurate from one favorable run. Freeze
version 7.7.0 and compare it against frozen historical outputs only as offline
baselines on a radiologist-adjudicated multi-case set. Each case must score abnormality recall,
level, side, morphology, compartment, root relationship, severity, false
positive structures, not-assessable decisions, latency, token use, failed-card
rate, and review-required rate. The known reference case is a regression seed,
not the validation cohort.
