# Eagle Eye Focused V3: Localization-First Screening and Independent Multiplanar Diagnosis

**Research review and implementation proposal | 2026-08-31**

**Status:** Research proposal with bounded axial coverage repair, scoped root-negation scoring repair (scorer 1.1.0), and an opt-in additive bilateral sagittal experiment implemented and verified offline on 2026-08-31 (see section 16). The remaining phases are proposals. Clinical system prompts, models, GapGPT routing, default mode, and clinical references are unchanged. Experimental evidence captions/header explain the added images. No new paid model evaluation was performed.

**Review amendment:** Follow-up verification reproduced an axial focus-window coverage defect. A bounded coverage repair now precedes benchmark refactoring. Sections 2.4, 5.2, 15, and 16 distinguish focus coverage from overview coverage and document the revised order.

**Scope:** The existing Eagle Eye lumbar pipeline, `gemini-3.1-pro-preview` screening and parallel context extraction, `gpt-5.6-sol` diagnostic verification, and the existing GapGPT transport. This is not a recommendation to replace the models or bypass GapGPT.

**Evidence convention:** *Verified* means observed in the current working-tree code or saved local artifacts. *Documented upstream* means supported by provider documentation, not necessarily by GapGPT. *Research-supported* describes a published method, not validation of this application. *Proposed* and *hypothesis* identify work that still requires testing.

Patient identifiers, source images, private paths, and verbatim clinical reports are intentionally excluded. The radiologist reference remains in the existing private benchmark store. All examples below are synthetic.

## Executive conclusion

The best next experiment is not a stronger instruction to call more extrusions. It is a cleaner separation between **finding an abnormal region** and **identifying what that region represents**, together with a more reliable connection between the region and its original images.

Focused V3 is worth retaining: it allocates more image pixels to the spine and preserves a useful, bounded, headless evidence-building path. However, it does not yet implement the proposed separation of model responsibilities. The screening model still supplies diagnostic labels, the evidence planner depends on those labels, sagittal screening anchors are not retained by that planner, and the diagnostic prompt contains competing acceptance rules. The benchmark also treats morphology as an ordered severity scale.

The recommended order is:

1. Repair the reproducible axial focus-window clipping defect, with deterministic coverage guards and manifest verification; no model call is needed to establish the software correction.
   Before E1/E2, separately test bilateral sagittal focus coverage while preserving the complete V3 base package; this opt-in implementation is now available, with clinical benefit still unverified.
2. Correct and freeze the benchmark contracts before judging diagnostic improvement, including clinician adjudication of reference negatives.
3. Preserve V3 rendering while testing a diagnosis-neutral attention handoff and independent diagnostic contract.
4. Retain both sagittal and axial anchors, with explicit source identity and coverage accounting.
5. Add validated image-coordinate localization and app-rendered markers as a separate experiment.
6. Consider bounded additional evidence requests and clinician-assisted measurements only after the simpler path is evaluated.

This is a testable architectural recommendation, not a claim that the current models can achieve a specified sensitivity, specificity, or positive predictive value. OpenAI explicitly cautions against interpreting specialized medical images with its general vision models. These experiments therefore require clinician-supervised research evaluation; better prompting is not clinical validation. [OpenAI vision limitations](https://developers.openai.com/api/docs/guides/images-vision)

## 1. The clinical intent to preserve

The requested division of work is coherent, provided it is represented in the data contracts and scoring, not just in introductory prompt language.

| Component | Primary question | Appropriate output | What it should not establish |
|---|---|---|---|
| Gemini image screening | Is there a potentially abnormal region, and where is it? | Suspicious foci, anatomical structure, image references, candidate points/boxes, coverage and uncertainty | Final morphology, final stenosis grade, or a diagnosis the next reader must defend |
| Parallel Gemini context | What historical, clinical, and protocol context should guide inspection? | Sourced history, broad and focal attention, available/missing sequences, provisional context | Proof that a historical diagnosis is present on the current images |
| Local evidence service | Which original pixels best expose the requested regions? | Validated, bounded, identity-linked clean images and locator information | Invented anatomy, an unverified level map, or a clinical diagnosis |
| GPT-5.6 Sol diagnostic reader | What do signal and morphology actually support? | Independent diagnosis or normal/indeterminate disposition, localization, consequences, evidence references | Automatic agreement with screening or automatic escalation of severity |

The diagnostic differential must include normal appearance, artifact, an alternative pathology, and insufficient evidence. A positive screening focus is an instruction to inspect, not an obligation to find disease.

Conversely, specificity must not be implemented as blanket deletion of mild abnormalities. A real mild finding and a normal variant are different outcomes. Imaging presence, clinical significance, and likely symptom causation should be separate concepts. Likewise, age and history may influence interpretation without becoming rules that erase visible findings.

The main distinctions requested by the clinician are:

- Signal characteristics and shape are separate evidence channels. A disc displacement can be morphologically abnormal without requiring a particular degree of desiccation.
- Protrusion versus extrusion is a morphology decision, not simply a move from mild to severe.
- A generalized bulge and a focal herniation can coexist at the same level; the output must not force a single mutually exclusive label for the entire disc.
- Side, compartment, stenosis severity, and nerve-root effect require their own evidence. Changing the morphology label must not automatically change all consequences.
- Patient laterality comes from verified orientation and source geometry, not a blanket instruction to mirror every image.
- Adjacent slices and the corresponding second plane should be presented as related observations of the same focus, not as unrelated pictures.

## 2. What focused V3 actually changes

### 2.1 As-built flow

```text
Immutable captured study and available source metadata
        |
        +--> Gemini screening ---------------------+
        |                                          |
        +--> Gemini clinical/protocol context -----+
                                                   |
                                  Local focused-V3 evidence builder
                                                   |
                                  GPT-5.6 Sol through GapGPT
                                                   |
                                  Structured audit + free-text report
```

The two Gemini requests run in parallel. Focused V3 is a verification-evidence profile, not a new clinical reasoning pipeline. The inspected V3 run still used pipeline version `4.6.1`. Its three stage prompts matched the compared V2 run, while the screening outputs and resulting selections differed.

The source default remains `layout`. `AIPACS_EAGLE_EYE_EVIDENCE_MODE=focused-v3` selects V3. A successful source experiment therefore does not mean that V3 is already the build default.

### 2.2 Verified code boundaries

Paths below are repository-relative; symbols are preferable to line numbers because the working tree is actively changing.

| Location | Verified behavior | Implication |
|---|---|---|
| `modules/ai_imaging/eagle_eye_lumbar/analysis_prompt.py` | Screening asks for likely morphology and candidate labels; its schema includes grade fields | Screening is not localization-only |
| `eagle_eye_lumbar/llm_backend.py::_candidate_context` | Forwards parsed candidates, or raw screening text if parsing fails | Removing one diagnostic field would not reliably eliminate label anchoring |
| `eagle_eye_lumbar/evidence_request.py::EvidenceFocus` | Stores `key_axial_frames`, but not sagittal anchors | A decisive sagittal frame can be lost between screening and evidence construction |
| `evidence_request.py::build_evidence_plan` | Derives `family` from candidate wording, groups by level, caps focus count | Neutral screening requires planner changes, not only a prompt edit |
| `eagle_eye_lumbar/focus_evidence.py::_focus_image` | Projects the selected axial image center into sagittal space | The projected point is not a model-localized lesion center |
| `focus_evidence.py::_same_slab_neighbors` | Finds the acquisition slab, then clips an anchor-centered radius without backfilling at the opposite boundary | A five-slice slab can supply only three or four focus slices despite available capacity |
| `focus_evidence.py::_axial_roi` | Uses a physical crop with a fixed posterior bias | This is geometric cropping, not canal or lesion segmentation |
| `eagle_eye_lumbar/capture_controller.py::_viewport_bounds` | Records viewer-widget rectangles inside a capture | These are useful pane boundaries, not complete anatomy-pixel-to-DICOM transforms |
| `modules/ai_imaging/evidence_core/volume.py` | Provides patient-space projection and per-slice geometry helpers | A suitable reusable foundation already exists |
| `modules/EchoMind/viewer_chat/openai_reporter.py::build_eagle_eye_user_content` | Sends captions followed by base64 image bytes with shared `detail="high"` | Inspect the real transport; a local PNG alone is not proof of upstream processing |
| `tools/eagle_eye_bench/scoring.py` | Uses an ordered morphology list and prose parsing | Current scores can conceal clinically important subtype or detection errors |
| `tools/eagle_eye_bench/bench.py::cmd_run` | Repeats the complete three-call pipeline | Existing repeats cannot isolate a change to diagnostic evidence alone |

In the shortened `eagle_eye_lumbar/...` paths, the prefix is `modules/ai_imaging/`.

### 2.3 What the saved V3 result supports

The inspected completed run used 36 screening images and five diagnostic composite images: two overview sheets and three focus sheets. Five uploaded composites do not mean five source slices. The focus sheets contain multiple related views.

V3 increased focus tiles from 256 to 384 pixels and cropped before fitting. Its declared physical crop sizes include approximately 96 by 104 mm axially and 100 by 100 mm for sagittal focus views. The inspected manifest recorded approximately 0.313 mm/pixel axial and 0.391 mm/pixel sagittal focus sampling. These are local rendered-image properties, not a guarantee about the provider's internal visual representation.

The recorded run used approximately 90,471 total tokens and took approximately 148 seconds. It completed without a focused-evidence warning. Nevertheless, the radiologist comparison still showed a focal herniation subtype error, underestimation of its neural consequence, and omissions of smaller true findings. Improved localization did not establish complete diagnostic correctness.

These observations support retaining V3 as a baseline worth testing. They do **not** establish that:

- the rendering change caused the apparent improvement;
- all decisive morphology was included in the focused crops;
- the remaining problem is only excessive conservatism;
- an extrusion label would automatically correct recess grading or root assessment;
- one successful answer would place a new version outside the variability of prior runs.

The benchmark README describes repeated variation, but its narrative is not a controlled comparative study. Historical test totals in the supplied follow-on note were not rerun here. The root-cause document named by that note was not found at its referenced repository location and was not read in this review. Follow-up feedback places it in the Claude project attached to the workspace. That is an access/provenance limitation, not a reason to consider an externally stored document unverifiable: its claims can be checked once the actual artifact is available. They must not be represented as independently reviewed before then.

### 2.4 Follow-up finding: focus-window clipping loses high-detail coverage

The reviewer identified a real gap in the initial audit. `_focus_image` selects an axial anchor, `_same_slab_neighbors` identifies the corresponding contiguous acquisition slab, and `focus_slice_indices` returns a radius-clipped window within it. There is no opposite-end backfill when that window meets a slab boundary.

An isolated execution of the existing helper confirms the behavior without importing the application or calling a model:

| Synthetic five-slice slab | Current selected local indices, padding 2 | Available bounded coverage |
|---|---|---|
| Anchor at index 0 | 0, 1, 2 | 0, 1, 2, 3, 4 |
| Anchor at index 1 | 0, 1, 2, 3 | 0, 1, 2, 3, 4 |
| Anchor at index 2 | 0, 1, 2, 3, 4 | 0, 1, 2, 3, 4 |
| Anchor at index 3 | 1, 2, 3, 4 | 0, 1, 2, 3, 4 |
| Anchor at index 4 | 2, 3, 4 | 0, 1, 2, 3, 4 |

The saved V3 manifest confirms two focus windows with four axial slices where a fifth same-slab slice was available. This defect is shared by the selection policy; it is not a V3-only rule. Changing the screening anchor between runs changes how much coverage is lost, even with identical prompt fingerprints and unchanged selection code.

An important qualification to the reviewer's feedback: the two omitted terminal frames were still present in the diagnostic axial overview. Its manifest lists all 25 axial capture frames, including those terminal frames, at approximately 0.407 mm/pixel. They were absent from their corresponding larger focus rows, whose axial sampling was approximately 0.313 mm/pixel. Thus the verified defect is **incomplete high-detail focus coverage**, not complete absence of those frames from the diagnostic request. Its contribution to the diagnostic error remains unmeasured.

The 1536-pixel focus-sheet width is consistent with four 384-pixel columns. However, `_draw_sheet` chooses the maximum tile count across rows, so width alone is not an authoritative axial-frame count. The manifest establishes which frames were actually included. A four-slice acquisition slab can also legitimately produce four tiles; target count must be derived from available same-slab coverage, not hardcoded to five in every case.

The repair should retain the selected anchor and shift the bounded window only as far as necessary to fill available slots within the same slab. For a valid local anchor `c`, slab depth `n > 0`, and radius `p >= 0`, the proposed selection is:

```text
count = min(n, 2*p + 1)
start = min(max(c - p, 0), n - count)
selected = start through start + count - 1
```

This includes the complete slab when its depth is at most the target count. For larger slabs, it preserves anchor locality. Do not blindly recenter on the entire slab: that can exclude an edge anchor in a long acquisition. Keep the original anchor as the sagittal-projection reference; filling the axial window does not itself justify changing the patient-space projection point.

Scope the change to focused axial selection, through `_same_slab_neighbors` or a dedicated bounded-window policy at that seam. Do not globally redefine the shared `focus_slice_indices` helper without auditing its sagittal and other consumers. Preserve plane/gap boundaries, no-duplicate behavior, cancellation, and image budgets.

This repair need not wait for a scoring refactor. It can be proven by synthetic guards and an offline replay to a new derived-artifact directory, leaving the original session untouched. Proving corrected coverage does not prove improved clinical diagnosis; that still requires the later controlled evaluation.

## 3. Why two planes are necessary but not sufficient

Two cross-sections generally do not uniquely specify a three-dimensional object. A reader must establish that the sections intersect the same structure, understand their orientations and positions, and distinguish an actual connection from partial-volume appearance or a missed slice.

The useful near-term representation is therefore **geometry-linked 2.5D evidence**: selected original slices, their neighbors, explicit sequence and orientation labels, and a shared anatomical focus. It is not a claim that a general image model reconstructs a diagnostic 3D volume internally.

Three different problems need separate solutions:

1. **Addressing:** Which exact source image and region is under discussion?
2. **Correspondence:** Does the second-plane region belong to the same lesion?
3. **Classification:** What does the combined evidence support?

A correct answer to addressing does not prove correspondence. A DICOM coordinate projected onto another acquisition is a geometric starting point, not proof that motion, slice thickness, or acquisition differences have preserved perfect anatomical correspondence.

The BLINK benchmark investigated visual correspondence and multi-view perception and found substantial limitations in the models it tested. Those were earlier models; its scores must not be attributed to GPT-5.6 Sol or Gemini 3.1. Its relevant lesson is methodological: multi-image input capability and reliable spatial perception are different properties. [BLINK, ECCV 2024](https://arxiv.org/abs/2404.12390)

For this application, the design should:

- retain original axial acquisition slabs and their per-slice geometry;
- order neighbors physically within a slab while preserving original capture identifiers;
- retain both midline and relevant parasagittal observations;
- show the relationship between a selected axial slice and the sagittal locator;
- reject or flag inconsistent geometry rather than making a visually plausible reconstruction;
- avoid treating thick, gapped, or differently angled acquisitions as an isotropic volume;
- record cross-sequence correspondence uncertainty, even when a shared frame of reference exists.

Additional multiplanar reconstructions can be useful when the source acquisition supports them, but interpolation cannot recover morphology absent from the acquisition. A volume rendering is not a substitute for source-slice inspection of a small disc base or nerve root.

## 4. The clinical morphology contract

The nomenclature should be defined once and then referenced consistently by prompts, structured outputs, and the benchmark.

Under the 2014 lumbar disc nomenclature consensus, extrusion can be established when a dimension of displaced material exceeds its attachment-base dimension **in the same plane**, or when continuity with the parent disc is absent. Complete separation is further described as sequestration. When qualifying protrusion and extrusion appearances coexist, the disc is classified as extruded. This does not require sagittal priority as a general rule: it requires a reliable defining observation of the same lesion in at least one plane. [Fardon et al., Lumbar Disc Nomenclature 2.0](https://radiology.queensu.ca/source/Lumbar_Disc_Nomenclature.pdf)

For implementation, the diagnostic record should separate:

| Dimension | Examples of independent values |
|---|---|
| Assessment state | Normal, abnormal, indeterminate, not assessable |
| Signal observation | Preserved central T2 signal, reduced signal, focal annular signal abnormality, uncertain |
| Background contour | No generalized bulge, generalized bulge, uncertain |
| Focal displacement | Absent, present, uncertain |
| Herniation subtype | Protrusion, extrusion, extrusion with sequestration, subtype indeterminate |
| Position | Level hypothesis, confirmed level if supported, side, zone |
| Neural consequence | Canal/recess/foraminal assessment and root contact, displacement, compression, or uncertainty |
| Evidence | Defining view, supporting views, contradictory views, missing views |

This representation prevents a one-dimensional severity ladder from determining unrelated findings.

The hydration concern also needs a precise boundary. A bright central nucleus on an appropriate sagittal T2 image should make the model scrutinize a desiccation claim; it should not become a rule that excludes every other disc abnormality. Avoid judging hydration from the normally darker peripheral annulus or from unmatched window settings. Standard MRI disc-degeneration grading evaluates more than a single brightness comparison. [Pfirrmann et al., original grading study](https://pubmed.ncbi.nlm.nih.gov/11568697/)

Sequence-dependent evaluation and structured separation of disc, endplate, and neural findings are consistent with the BACPAC working group's imaging-evaluation approach. That provides a useful clinical checklist foundation, not a validation of an LLM reader. [BACPAC acquisition and evaluation recommendations](https://pmc.ncbi.nlm.nih.gov/articles/PMC10403314/)

## 5. What the selected models can actually provide

### 5.1 Capability versus clinical performance

| Question | Evidence-backed answer | Boundary for Eagle Eye |
|---|---|---|
| Can GPT-5.6 Sol receive images? | Its official model documentation lists image input, text output, structured outputs, and function calling; video input is not supported | Keep explicit image evidence; do not assume a movie can replace the image request |
| Can Gemini 3.1 Pro Preview return a newly marked image? | Its model card lists text output and no image generation, while image/video input and structured outputs are supported | Request coordinates or identifiers; have the application draw the marks |
| Can Gemini propose bounding boxes? | Google's image-understanding guide documents normalized boxes | Capability must be tested on the exact model and GapGPT route; general object detection is not MRI lesion validation |
| Does official API support prove GapGPT support? | No | Probe parameter acceptance and semantic behavior through the existing bridge |

Sources: [GPT-5.6 Sol model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Gemini 3.1 Pro Preview model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview), and [Google image understanding](https://ai.google.dev/gemini-api/docs/image-understanding).

### 5.2 Local sampling gains fit the documented upstream image budget

The actual five saved V3 PNGs had these dimensions:

| Image class | Count | Dimensions | 32-pixel patch count per image |
|---|---:|---:|---:|
| Axial overview | 1 | 1280 x 1440 | 1800 |
| Focus composite | 3 | 1536 x 856 | 1296 |
| Sagittal overview | 1 | 1440 x 1112 | 1575 |

OpenAI documents a 2048-pixel dimension limit and a 2,500-patch budget for GPT-5.6 `high` detail. All five images fit those limits. Consequently, the documented upstream resizing rules would preserve their dimensions: V3's local sampling gains are not canceled by that particular preprocessing step. GapGPT-specific processing remains unverified. [OpenAI image sizing rules](https://developers.openai.com/api/docs/guides/images-vision)

This supports the rationale for improving local sampling. It does not prove end-to-end pixel preservation through the bridge, reliable model perception, or a causal diagnostic improvement. The earlier framing against switching to `original` was an audit-side hypothesis, not a proposal made by the V3 author, and is not the main conclusion here.

Filling a clipped four-column focus row to five columns would produce a 1920 x 856 sheet under the current renderer, or 1620 patches. That predicted size also fits the documented `high` limits. Recheck actual dimensions, compressed bytes, and total-package budgets after the repair rather than assuming that every future expansion fits.

For future larger composites, compare image detail settings in a patient-free capability test and then a controlled clinical experiment. Apply any change per stage; the current transport constant is shared with Gemini.

### 5.3 Reasoning and prompt length

The saved diagnostic prompt was approximately 36,509 characters, before adding the candidate/context content. Length alone does not diagnose the failure. Contradictory requirements, duplicated rules, diagnostic anchoring, and omitted evidence are more specific hypotheses.

OpenAI's GPT-5.6 guidance recommends simplifying repeated instructions and evaluating changes incrementally, and supports intentionally chosen reasoning effort. Its reported prompt-simplification benefits come from other workloads, not lumbar MRI. Start by eliminating contradictions and preserving the required clinical output, then test reasoning settings separately. [GPT-5.6 prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6)

The current Eagle Eye request does not explicitly set reasoning effort or a strict response schema. Do not silently assume provider defaults, or add unsupported fields to GapGPT requests. Do not equate additional reasoning tokens with recovered image detail.

## 6. Gemini localization: points and boxes, not a preliminary diagnosis

### 6.1 Proposed screening contract

Replace the clinical-candidate handoff with an **attention contract**. Each focus should identify:

- an immutable focus ID;
- the anatomical structure, without requiring a disease subtype;
- `suspected_abnormality`, `indeterminate`, or an explicit assessed-normal coverage state;
- a level hint with independent uncertainty;
- the exact presented image and pane/tile IDs;
- ranked axial and sagittal source anchors;
- optional point or bounding box, in a declared coordinate system;
- a brief observable reason, such as focal contour change or focal signal difference;
- missing coverage or image-quality limitations.

Do not require screening to decide bulge versus protrusion versus extrusion, assign a final stenosis grade, or establish root compression. It still needs enough anatomical description to direct acquisition of useful evidence.

Example of one synthetic attention focus, not a complete production schema:

```json
{
  "schema_version": "attention-proposal-1",
  "focus_id": "focus-01",
  "assessment": "suspected_abnormality",
  "anatomical_structure": "disc_region",
  "level_hint": null,
  "level_confidence": "unknown",
  "observation_tags": ["focal_contour_change"],
  "views": [
    {
      "image_ref": "synthetic-sag-t2-004",
      "pane_ref": "sagittal_t2",
      "anchor_rank": 1,
      "coordinate_space": "presented_image_0_1000",
      "box_ymin_xmin_ymax_xmax": [420, 360, 650, 610],
      "point_y_x": [530, 490]
    },
    {
      "image_ref": "synthetic-ax-t2-017",
      "pane_ref": "axial_t2",
      "anchor_rank": 1,
      "coordinate_space": "presented_image_0_1000",
      "box_ymin_xmin_ymax_xmax": [380, 410, 570, 630],
      "point_y_x": [480, 520]
    }
  ],
  "localization_confidence": "moderate",
  "coverage_limitations": []
}
```

Google documents bounding-box ordering as `[ymin, xmin, ymax, xmax]` normalized to 0-1000. Preserve that convention explicitly rather than mixing it with drawing libraries' x/y order. The current guide's examples use a different model; they do not establish lesion-localization accuracy for the exact deployed Gemini version. [Google bounding-box documentation](https://ai.google.dev/gemini-api/docs/image-understanding)

An empty focus list must be accompanied by coverage and assessability, not interpreted automatically as a normal study. Foci with uncertain vertebral numbering must remain inspectable through valid image references.

### 6.2 Who draws the marks?

Gemini returns coordinates. A deterministic application renderer draws an attention marker on a **derived locator copy**. The diagnostic reader receives clean evidence plus the locator or a compact identity legend. It must be told that markers identify requests for inspection, not confirmed disease boundaries.

Use small IDs and leader lines that do not obscure the disc attachment, displaced component, root, or CSF interface. Do not generate or repaint anatomical pixels. Maintain the unmarked source and the transform manifest. If marks reduce visibility or create anchoring, prefer IDs in the margin and a separate locator.

Set-of-Mark prompting demonstrated that explicit visual region identifiers can improve grounding for GPT-4V on nonclinical tasks. It supports testing region addressing, not assuming that markings improve lumbar diagnosis or accurately outline disease. [Set-of-Mark prompting](https://arxiv.org/abs/2310.11441)

Two different marking experiments should remain distinct:

1. Model-proposed suspicious points/boxes: tests **detection plus localization**.
2. Clinician-approved points/boxes without diagnostic labels: tests **downstream evidence delivery and interpretation**.

If the second works and the first fails, the bottleneck is not resolved by lengthening the diagnostic prompt.

## 7. Coordinate correctness is the central engineering requirement

### 7.1 One coordinate must name one actual image

A box is meaningless without its source image identity. It must refer to the exact image presented to Gemini, not an earlier screenshot, a differently resized pane, or the current live viewer state.

The transformation chain is:

```text
Presented image coordinates
  -> exact pane/tile coordinates
  -> original image pixel coordinates
  -> patient LPS coordinates and source slice plane
  -> target acquisition coordinates
  -> diagnostic crop coordinates
  -> composite tile coordinates
```

For zero-based column index `i` and row index `j`, DICOM patient coordinates follow:

```text
P(i,j) = IPP
       + i * PixelSpacing[1] * IOP[0:3]
       + j * PixelSpacing[0] * IOP[3:6]
```

Here `IPP` is the center of the first transmitted pixel, and the direction vectors come from `ImageOrientationPatient`. Pixel-edge box coordinates and pixel-center indices require an explicit half-pixel convention. Per-frame geometry must be used where applicable. [DICOM Image Plane Module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html)

Normalized points and box edges also need separate definitions: a point can map to a pixel-center index range, while a box edge maps to the image boundary range. Tests must prevent a silent width-versus-width-minus-one mismatch.

### 7.2 Why the existing widget bounds are insufficient

The current capture records pane rectangles. It does not, by itself, encode all image letterboxing, viewport scaling, zoom, pan, flip, rotation, or device-pixel transformations. Multiplying a Gemini coordinate by DICOM dimensions would therefore be unsafe.

Two implementation choices are possible:

- **Preferred for a new localization experiment:** generate deterministic screening image panes directly from immutable source images and retain their exact rendering transforms. This changes screening evidence and must be benchmarked separately from a prompt-only change.
- **Compatibility path:** use existing captured panes only when the full capture-time image transform can be recovered and validated. Otherwise accept frame-level anchors but reject pixel-coordinate projection.

The local renderer should own rotation, padding, crop bounds, scale, and source references. It should also distinguish acquired images from resampled images.

A point on one slice identifies a point on that plane. A two-dimensional box does not define a unique three-dimensional lesion volume. Neighbor selection needs a bounded search slab and uncertainty margin, not an invented 3D extent.

### 7.3 Level, laterality, and lesion identity

Do not make the model's level label the primary identity key. Use stable focus/source references; attach the level as a separately checked interpretation. Transitional anatomy, incomplete coverage, and uncertain counting should produce uncertainty rather than a forced standard level.

Similarly, patient-right should be derived from DICOM orientation and validated displayed markers. Screen-right is not a universal patient-left rule. A deterministic label can still be wrong if the underlying transform is wrong, so both need tests.

Before combining views, check sequence, slab, plane position, nearest-slice distance, and relevant anatomy. Shared coordinates should aid the reader, not claim a level of registration accuracy that was never measured.

## 8. Evidence packaging that preserves shape without excessive uploads

Keep the overview-plus-focus pattern, but choose focused evidence around **the same requested anatomy**, not only around the image center or a level-range midpoint.

For a disc-region focus, a candidate package is:

- one shared sagittal overview spanning the clinically relevant lumbar region;
- the selected sagittal T2 anchor and nearby slices, including a relevant parasagittal view when available;
- the selected axial T2 anchor and nearby slices within the same acquisition slab;
- a corresponding sagittal T1 observation when it answers a signal/endplate question;
- clear frame IDs, sequence identity, patient orientation, and a locator relationship.

The exact number of neighbors should follow coverage and budget rather than an unconditional per-disc quota. The current limit of up to five axial neighbors and three sagittal neighbors is a reasonable experimental starting point, not a clinically validated optimum.

Merge overlapping requested windows. Several adjacent disc foci can share a sagittal strip and T1 context. Preserve a separate focus ID for each suspicious region even when the images are shared. Do not merge distinct abnormalities solely because they share a disc level.

Use structure-specific templates: a foraminal question may require lateral sagittal coverage; a marrow question may need additional available signal sequences; a postoperative question may remain limited by artifact. A central disc crop is not a universal template for every lumbar abnormality. Missing relevant sequences should remain an explicit limitation.

| Representation | Main benefit | Main risk | Recommendation |
|---|---|---|---|
| Full workstation capture | Preserves current layout and localizer context | Anatomy competes with interface pixels | Retain as baseline and immutable fallback |
| Ordered clean image panes | Clear anatomy and simple coordinate mapping | More image items | Candidate screening representation |
| Paired overview and focus composites | Bounded upload with explicit local context | Dense sheets can shrink or confuse small structures | Retain V3 baseline; validate every tile |
| Separate defining-plane tiles | Makes subtle morphology larger and easier to reference | More items and repeated context | Controlled alternative to a dense focus sheet |
| Cine/video | Expresses slice order naturally for a human | Unsupported by selected GPT model; conversion/selection changes evidence | Not the first shared-pipeline solution |
| Raw DICOM files | Preserve acquisition data for local tools | Not the current provider image-input contract | Decode and project locally, not raw-upload as vision images |
| Specialist 3D model or segmentation | Can provide explicit spatial structures | Training, licensing, validation, and integration costs | Later research branch, not a V3 hotfix |

A caption saying that frames are sequential does not prove that a model reasons over them like a human scrolling a film. The model receives a finite set of image inputs. Correct ordering, visible adjacent changes, and explicit correspondence are testable properties; inferred continuous-volume understanding is not.

## 9. Independent diagnosis: compact instructions and an observable evidence record

### 9.1 Remove the actual contradictions

The current prompt already contains useful multiplanar morphology language. However, elsewhere it tells the verifier to remove findings not confirmed on an orthogonal plane and applies broad all-conditions acceptance gates. These can conflict with a reliable defining observation in one plane or with true mild abnormalities.

The proposed correction is not unrestricted acceptance of one-slice findings. It is **finding-specific evidence sufficiency**: assess whether the defining feature is actually resolved, whether the compared views represent the same focus, and whether another view is contradictory or merely nondiagnostic.

The current example of changing a bulge candidate to extrusion with `change_direction: "upgraded"` should be retired for morphology. Use `reclassified` for a different subtype, while grading changes remain attached to their own structure and scale.

### 9.2 Proposed diagnostic task text

The following is a design draft, not a replacement applied to the runtime:

```text
Evaluate the supplied lumbar MRI evidence as an independent diagnostic reader.
Attention targets identify regions to inspect, not established diagnoses.
Clinical context contains sourced priors, not proof of current image findings.

For each focus, inspect the clean source-linked images and their neighbors.
Establish patient orientation, anatomical correspondence, and image adequacy.
Record the relevant signal and contour observations before assigning a label.
Use the single supplied clinical-definition block; do not substitute severity
for morphology or let a nondiagnostic view veto a reliable defining view.

Return normal, abnormal, or indeterminate assessment for each focus. Compare
the plausible alternatives, including normal appearance and artifact, using
brief image-grounded reasons and explicit evidence references. Diagnose neural
consequences independently. Preserve true mild findings and report limitations.

Inspect the overview for important unflagged abnormalities. Return added foci
with source references when justified. Never treat missing coverage as normal.
Do not invent measurements, slice correspondence, or missing sequence findings.
```

The output should be an **observable evidence record**, not a request for hidden chain-of-thought. Require short clinical observations, source IDs, the selected diagnosis, material alternatives, and uncertainty. Listing every conceivable differential would add noise; record alternatives relevant to the actual focus.

In one call, place observations before diagnosis in the output schema. This is a behavioral hypothesis, not a guarantee of internal reasoning order. If it does not improve performance, a separate image-only observation pass can be tested later with its extra latency and cost explicitly measured.

### 9.3 Keep diagnostic axes separate

Suggested records include `signal_observations`, `contour_observations`, `background_bulge`, `focal_herniation`, `morphology_subtype`, `defining_evidence`, `level_assessment`, `patient_side`, `zone`, and separate `neural_findings`.

Each clinical field needs an assessability state. The following are not interchangeable:

- explicitly absent on adequate evidence;
- not mentioned in the report;
- not imaged adequately;
- uncertain despite adequate imaging;
- positive but not confidently subtyped.

The final report should be rendered from validated structured findings, with a consistency check that every accepted reportable finding appears and that prose does not contradict the audit. The present audit/free-text split leaves room for correct intermediate observations to disappear from the final report.

Normal alternatives should remain in the audit when they explain rejection; the concise clinical report need not print a long differential for every normal structure.

## 10. Context is useful, but label leakage can return through it

Keep the parallel reception/history/prior-report pathway and paired sagittal T1/T2 context. Preserve the distinction among:

1. reception or historical records;
2. current-study inventory and protocol facts;
3. provisional image-derived broad or regional context;
4. current diagnostic findings, which remain the diagnostic reader's responsibility.

A neutral screening handoff is insufficient if the context prompt supplies the same specific current diagnosis through a free-text hypothesis. Use provenance-aware context fields and separate historical diagnoses from current visual attention.

Do not delete meaningful historical reports merely to achieve blindness. For the anchoring experiment, create an explicitly labeled image-only or history-excluded experimental arm, while the intended clinical workflow retains sourced history. Benchmark reference labels must never enter either input.

The attention set should include the union of valid screening and context foci, with deduplication based on source/anatomical correspondence. Keep a broad overview so a context or screening miss does not make the region invisible to the diagnostic reader.

## 11. Use the existing orchestration, not another unrestricted agent

The required bridge is primarily deterministic:

```text
Model attention JSON
  -> schema and source-reference validation
  -> bounded evidence plan
  -> headless source-image rendering
  -> coverage/quality manifest
  -> diagnostic request
```

The existing `evidence_request.py`, `focus_evidence.py`, and `evidence_core` already supply the right service boundaries. MCP can expose that service later, but MCP is a transport/interface mechanism, not a morphology algorithm.

Do not let model output contain executable commands, arbitrary file paths, live viewer scroll instructions, or unconstrained crop sizes. Resolve opaque source references locally. The model proposes attention; the application decides what operations are valid.

The default path should remain three model calls: two parallel Gemini calls and one GPT call. After validation, an optional bounded follow-up could allow GPT to request one additional evidence bundle when a named feature is not visible, with at most one additional diagnostic call. The response should request missing evidence, not request an image that proves a predetermined diagnosis.

All decode, crop, upload, and model work stays off the GUI thread. Use immutable session-bound sources, atomic artifact writes, cancellation checks, and late-result identity guards. Never read pixels from a newly scrolled live viewer to satisfy an old request.

Keep current hard limits as an initial guardrail: eight evidence images, four focused regions, 12,000,000 pixels, and 12 MiB of encoded images. These are engineering budgets, not proof of clinical completeness. Every excluded focus needs an explicit `not_evaluated_due_to_budget` disposition or approved fallback; a fifth focus must not silently become normal.

Quality checks must cover uniform/black images, clipping, orientation, source correspondence, and anatomical coverage. A nonblack image can still be the wrong slice or a crop that excludes the defining feature.

## 12. GapGPT capability checks before transport changes

Extend the existing patient-free capability harness rather than creating a direct OpenAI or Google client. Keep the company-managed GapGPT authentication and routing.

Proposed probes, each isolated from the clinical benchmark:

- verify requested versus returned model identifiers where exposed;
- verify image ordering and caption-to-image association;
- test supported strict JSON output and malformed-output handling;
- test point/box coordinates on synthetic shapes with known positions;
- compare `high` and `original` on a synthetic fine-detail chart;
- test explicit reasoning parameters only for the intended model/endpoint;
- test whether Gemini media-resolution controls are accepted and effective through this bridge.

Google documents media-resolution controls for allocating visual processing to images and frames, with a detail/latency tradeoff. That does not prove the OpenAI-compatible GapGPT route exposes the same control. [Google media-resolution guidance](https://ai.google.dev/gemini-api/docs/image-understanding)

A successful HTTP response proves acceptance, not semantic fidelity. Record actual payload fields, returned identifiers, output behavior, usage, and latency. If the provider omits its served-model identity, record that limitation rather than treating the requested string as proof.

Do not change temperature, reasoning effort, image detail, evidence layout, and prompt simultaneously. The current screening/context/diagnostic temperatures are different; the review has not demonstrated that any one of them caused the clinical errors.

## 13. Other approaches worth considering

### 13.1 Specialist vertebral localization

SpineNetV2 separates vertebral detection/labelling from radiological grading across spinal MRI. This is a relevant architectural precedent for a local anatomical locator upstream of a general diagnostic model. It is not proof of reliable extrusion classification in this application. Evaluate licensing, acquisition compatibility, transitional anatomy, and out-of-distribution performance before adoption. [SpineNetV2 technical report](https://arxiv.org/abs/2205.01683)

An appropriate comparison would be Gemini localization versus specialist localization versus clinician-approved localization, all feeding the same diagnostic evidence contract. A specialist is attractive if it reduces localization error without requiring more LLM calls.

### 13.2 Prompted medical segmentation

MedSAM demonstrates medical-image segmentation using a medical foundation model. A useful future role is helping outline an already identified region, with clinician correction and task-specific validation. A segmentation mask is not itself a disc-morphology diagnosis or a validated measurement of its attachment base. [MedSAM, Nature Communications 2024 / author manuscript](https://arxiv.org/abs/2304.12306)

For narrow structures, an apparently smooth mask can erase the very neck or interface that matters. Evaluate boundary accuracy at clinically defining features, not only whole-region overlap.

### 13.3 Dedicated 3D medical models

M3D introduces a dedicated 3D medical dataset, model, and benchmark. This supports a longer-term alternative using explicitly volumetric representations rather than hoping a general image endpoint reconstructs a volume. It does not establish compatibility with this lumbar MRI workflow or justify replacing the current models without new validation. [M3D research paper](https://arxiv.org/abs/2404.00578)

### 13.4 Public lumbar datasets

RSNA LumbarDISC provides multi-institution lumbar MRI annotations for canal, subarticular, and foraminal stenosis. It is useful for coverage and localization research but does not replace a reference set specifically annotated for extrusion morphology, annular fissures, and the requested independent findings. Its stated noncommercial terms require review before product use. [RSNA LumbarDISC dataset paper](https://pubs.rsna.org/doi/full/10.1148/ryai.250480)

### 13.5 Clinician-assisted measurements with 3D Slicer

The repository has a Slicer launcher and background launch worker. Full Slicer prewarming is explicitly disabled because it opens a window. Do not make Slicer startup part of the default three-call analysis path.

Slicer Markups supports points, lines, and measurement workflows. A later opt-in tool could record clinician-approved base and displaced-component landmarks on the same plane, retaining their image identities and uncertainty. The application can then calculate distances; the LLM should not invent millimetres from screenshots. [Slicer Markups](https://slicer.readthedocs.io/en/5.10/developer_guide/script_repository/markups.html)

Keep coordinate conventions explicit: Slicer uses RAS internally, whereas DICOM patient coordinates commonly use LPS; the first two axes change sign in that conversion. Import/export must retain the declared convention and relevant transforms. [Slicer coordinate systems](https://slicer.readthedocs.io/en/5.10/user_guide/coordinate_systems.html)

Measurements are supporting evidence, not an automatic severity engine. A ratio near a decision boundary needs uncertainty handling, especially with thick slices or uncertain attachment landmarks. No Slicer measurement integration is claimed to exist in the current lumbar path.

## 14. Repair the benchmark before optimizing against it

### 14.1 Specific current defects

The existing harness is a useful start, but its scoring contract is not yet appropriate for this research question.

| Verified issue | Why it matters | Proposed replacement |
|---|---|---|
| `MORPHOLOGY_ORDER` orders none, bulge, protrusion, extrusion, sequestration | Different shapes become severity steps; none versus bulge can receive partial credit | Separate presence detection from subtype classification |
| Generic `herniat` maps to protrusion | An unspecified herniation is assigned a subtype it never claimed | Preserve herniation with indeterminate subtype |
| One morphology value is retained per level | Background bulge plus focal herniation can be lost | Multi-component disc record |
| Missing/normal/unassessable states are incompletely distinguished | Omission can be mistaken for a negative diagnostic decision | Explicit states and missing-field penalties |
| False-positive accounting focuses on selected structures and includes soft-normal handling | A low count does not establish general specificity | Separate adjudicated negatives, unlabelled structures, and exploratory alerts |
| Root effect and side evaluation are coupled in parts of scoring | One error can hide another | Score root identity, side, and effect separately |
| Scoring without a session filter pools historical outputs | Different versions can be mixed into one rate | Group by full immutable experiment configuration |
| Failed reruns are skipped from the successful-score aggregate | A fragile system can look better by failing to produce reports | Count all attempted runs and show coverage/failure denominators |

Level-map monotonicity is a useful consistency check, not anatomical proof. Sorting direction alone cannot establish correct numbering or slice-to-disc correspondence.

Correct the clinical reference policy as well: an unmentioned structure is **unlabelled**, not normal. Do not add normal upper levels, normal central canals, or absolute foraminal normality merely to fill a schema when the clinician did not assert them. Have the radiologist adjudicate those fields before using them as negatives. This document does not edit the reference.

### 14.2 Measure each task independently

For screening, measure lesion/region sensitivity, important-focus miss rate, false attention targets, and coverage. For localization, measure reference-region inclusion, point distance in millimetres where calibrated, level/side correctness, and inclusion of defining features. Box overlap alone is insufficient if the disc base is outside the crop.

For diagnosis, measure:

- normal-versus-abnormal discrimination on adequately assessed regions;
- subtype confusion, with indeterminate subtype preserved;
- laterality, zone, and level errors separately;
- missed annular, signal, and mild focal abnormalities;
- compartment-specific severity and root consequences separately;
- unsupported positive findings in adjudicated normal structures;
- structured-audit versus final-report omissions and contradictions;
- abstention rate, performance among answered cases, and unresolved clinically important cases.

Sensitivity and positive predictive value need denominators from an appropriate patient spectrum. Repeating one abnormal case estimates run-to-run variability for that case; it does not establish clinical PPV. Do not treat repeated runs as independent patients.

### 14.3 Reference and study design

Use a radiologist reference created from full source imaging, not model-generated text. Where feasible, obtain independent second-reader adjudication, especially for morphology boundaries and root effects. Store uncertainty or disagreement rather than silently choosing the answer most favorable to a model.

Maintain patient-disjoint development and locked evaluation sets, with an external/site-held-out set when available. Include normal examinations, mild disease, multiple levels, mixed bulge and herniation, different sides, difficult numbering, postoperative changes, artifacts, and nondegenerative pathology. Include examples where a suspected extrusion is genuinely not an extrusion.

Use the repeatedly discussed local case as a development sentinel, not as the sole definition of success. Do not insert its expected findings, coordinates, or labels into reusable prompts.

For comparisons, randomize or interleave configurations, repeat within cases to expose variability, and report uncertainty using the patient as the independent sampling unit. Predefine primary outcomes and noninferiority margins with the clinical/statistical reviewer before inspecting held-out results. Five repeats can be a smoke experiment, not clinical validation.

## 15. A controlled experiment sequence

Version these dimensions independently: evidence profile, screening contract, context contract, diagnostic contract, schema, transport parameters, reference, and scoring implementation. These are proposed experiment-manifest fields, not newly implemented configuration variables.

| Experiment | Held fixed | Changed | Question answered |
|---|---|---|---|
| EC: deterministic coverage repair | Saved screening/context outputs, source images, windows, V3 render profile, model settings | Clipped axial window versus anchor-preserving bounded backfill | Does the derived manifest include every available target slice within the slab and budget? No model call is required. |
| E0: frozen baseline | Existing saved inputs, V3 artifacts, current contracts | Nothing | Can we reproduce and score the current system consistently? |
| E1: handoff ablation | Exact diagnostic image bytes, context, diagnostic model/settings | Candidate labels versus neutral source-linked attention | Does the first-pass diagnostic label bias the final interpretation? |
| E2: diagnostic-contract ablation | Same images and neutral attention | Current acceptance rules versus compact, noncontradictory contract | Does the diagnostic instruction change help on unchanged evidence? |
| E3: anchor preservation | Frozen screening/context responses and diagnostic contract | Current projection selection versus retained anchors in both planes | Are defining slices missing because of selection? |
| E4: localization comparison | Diagnostic reader and evaluation cases | Automatic versus clinician-approved label-free ROIs | Is the bottleneck localization/cropping or diagnosis? |
| E5: presentation/settings | Same clinically relevant source slices | Composite versus separate defining tiles; then supported detail/reasoning settings one at a time | Is presentation or processing limiting perception? |
| E6: end-to-end validation | Frozen reference, scoring, and chosen configuration | Complete repeated pipeline versus frozen baseline | Does the integrated change improve relevant outcomes without unacceptable losses? |

E1 may require a compatibility adapter because the present diagnostic contract expects candidates. Record that adapter as part of the changed condition; do not claim a pure one-word intervention. A small factorial test of handoff and diagnostic contract can distinguish their interaction if budget permits.

The present CLI does not implement frozen-stage replay. Add replay modes explicitly before running the model experiments; using its existing full-pipeline rerun is not equivalent. A narrowly scoped offline renderer replay is sufficient for EC and need not wait for the benchmark refactor. Preserve both the original V3 artifacts and a separately versioned coverage-corrected baseline. For subsequent prompt comparisons, preserve exact evidence bytes; for renderer comparisons, preserve exact model outputs.

A useful diagnostic decision tree is:

```text
Incorrect final result
  |
  +-- Is the reference independently adjudicated?
  +-- Does the transmitted evidence contain the defining feature at useful scale?
  +-- Are identity, orientation, sequence, and cross-view correspondence correct?
  +-- Does a label-free clinician-selected evidence package improve the answer?
  +-- Does removing prior model labels improve the answer on identical pixels?
  +-- Does the compact diagnostic contract improve the answer?
  +-- If these fail, is a specialist method or mandatory human assessment needed?
```

This avoids interpreting every error as a prompt problem or every improvement as proof of better morphology perception.

## 16. Phased implementation plan

### Coverage preflight: bounded axial-window repair

**Implementation status (2026-08-31, OPT-55): fixed and automatically/offline verified; live clinical verification pending.** The defect descriptions elsewhere in this review describe the original saved baseline. Keep that baseline immutable rather than replacing it with corrected evidence under the same experiment label.

**Deliverables:** a regression guard reproducing boundary underfill, a minimal focused-axial selection correction, and new manifest fields or checks for available slab depth, expected count, selected count, and boundary adjustment. Preserve the screening anchor and existing sagittal projection point.

**Files:** `focus_evidence.py` at the same-slab selection seam, focused V2/V3 guards, and the regression catalog. Keep the generic radius-clipping helper unchanged unless a separate consumer audit justifies expanding the scope.

**Gate:** test anchors at both boundaries and in the interior, short and long slabs, gaps, differing orientations, reversed capture/source ordering, and unchanged behavior when a full window already fits. Verify the actual rendered manifest and budget in an offline replay using a separate output directory. Do not overwrite source captures, old reports, or original evidence manifests. No paid model call is necessary for this gate.

**Order:** this small coverage correction precedes Phase 0. Benchmark repair remains mandatory before claiming diagnostic superiority, but is not a prerequisite for fixing deterministic loss of available focus coverage. Because V2 and V3 share this selection seam, explicitly verify both and version the policy change for reproducible comparisons.

**Implemented contract:** `_same_slab_neighbors` fills `min(slab_depth, 2 * padding + 1)` contiguous capture-ordered slices inside the already detected acquisition slab. It shifts the window at a boundary, not the original anchor. Short slabs remain short; long slabs stay near the anchor rather than moving to the slab midpoint. Gap/orientation boundary detection, capture-to-source identity, shared sagittal selection, geometry projection, rendering profiles, existing budgets, worker execution, and layout fallback are unchanged.

The evidence manifest is now schema **1.3.0**. Each focus has an `axial_window` record with policy `same-slab-backfill-v1`, anchor capture frame, available slab depth and capture-frame bounds, requested/expected/selected counts, and a boundary-adjustment flag. This versions the evidence-selection change independently of the unchanged model prompts. The correction applies to both focused V2 and V3; it does not switch the default evidence mode from `layout`.

**Verification record:**

- Before the runtime edit, 41 new synthetic regression cases produced **20 failures and 21 passes**, exit code 1; both render-mode integration cases failed on four selected slices instead of five.
- After the correction and updating two older expectations that pinned clipped coverage, the V2/V3 suite passed **63 tests**, exit code 0. Guards cover every anchor in short/long slabs, both boundaries, interior windows, gaps, differing orientations, reversed source ordinals, unchanged sagittal selection, original capture bytes, manifest coverage, and budget limits.
- Complete AI Imaging: **643 passed, 8 existing xfailed**, exit code 0; default-build inclusion: **3 passed**, exit code 0; plugin mirror verification: **458 pairs matched**. The changed lumbar file belongs to the core AI Imaging package and has no plugin payload mirror. No build was produced or deployed.
- A fresh private offline replay used the saved screening/context `data` payloads, original captures, and local DICOM provenance. It rendered in **3.03 seconds** on this machine with outbound socket connections denied. This is one local timing, not a performance benchmark. All **57 original session files** retained identical hashes; both overview PNGs were byte-identical, and all original anchors, sagittal slices, and sagittal crop/sampling records were unchanged.

| Replay coverage/budget | Original evidence | Corrected evidence |
|---|---:|---:|
| First five-slice slab focus | 4 slices | 5 slices |
| Second five-slice slab focus | 4 slices | 5 slices |
| Four-slice slab focus | 4 slices | 4 slices |
| Two affected focus-sheet dimensions | 1536 x 856 each | 1920 x 856 each |
| Total image count | 5 | 5 |
| Total pixels (limit 12,000,000) | 7,388,928 | 8,046,336 |
| Total encoded bytes (limit 12,582,912) | 4,364,552 | 4,546,578 |

The previously omitted slices were missing from the high-detail focuses, **not** from the overview. This replay proves restored focused coverage; it does not prove improved extrusion recognition, specificity, or PPV. A new clinician-supervised source-build evaluation remains necessary. Phase 0 reference/scorer repair and E1/E2 are still pending; no patient-specific diagnosis or morphology rule was added.

**Rollback:** the existing `AIPACS_EAGLE_EYE_EVIDENCE_MODE=layout` path bypasses focused composition. To reproduce pre-fix focused evidence, use the preserved original artifacts; do not overwrite them or present a new-policy run as the old baseline.

### Additional coverage preflight: additive bilateral sagittal experiment

**Implemented, opt-in, offline verified (2026-08-31; OPT-55).** Select
`focused-v3-parasagittal` through the existing evidence-mode environment
variable or benchmark CLI. The normal V3 renderer is unchanged. All its PNGs
and captions are retained before optional sagittal T2 supplements are appended.
This makes an evidence comparison possible without simultaneously changing
screening, clinical context, diagnostic system prompts, or provider settings.

**Correction to the later saved-run interpretation:** the approximately 9.6 mm
right-sided sagittal plane was present in the overview but absent from the
three-slice focused row. The approximately 14.4 mm plane was outside both.
InstanceNumber and decoded-volume order are reversed in that acquisition;
they cannot be treated as the same numbering system. The overview's five
source-volume slices were independently re-rendered and matched to the saved
PNG pixels. Therefore the appropriate hypothesis is inadequate focused
coverage/emphasis, not complete absence of the 9.6 mm plane. The diagnostic
model's prose does not establish which tile determined its morphology call.

The experiment samples targets at 0, +/-5, +/-10, and +/-15 mm in patient LPS
x from the unchanged axial-center projection. It keeps the geometric reference
and both sides regardless of screening laterality; the reference is explicitly
not a verified anatomical midline. These offsets are a bounded engineering
choice, not a clinical localization rule. Up to seven distinct sagittal T2
slices are cropped at V3 scale and arranged right-to-left. Source-volume slice
numbers and actual offsets accompany each tile; sampling may be noncontiguous.

Manifest **1.4.0**, policy `bilateral-lps-supplement-v1`, audits included,
unavailable, budget-excluded, and partial supplements. Original V3 retains
schema 1.3.0. Supplements cannot evict baseline images or raise the existing
8-image/12-million-pixel/12-MiB caps. A supplement failure preserves baseline
evidence; a failure constructing the baseline retains the existing layout
fallback. Focus priority, broad overviews, and headless worker execution are
unchanged. This is not lesion-coordinate localization or proof of complete
anatomical coverage.

**Verification:** initial new-mode guards failed in 11 cases before the
implementation; the final parasagittal file passes 18 tests, including reversed
order, obliquity, invalid geometry, partial/short coverage, all three budget
caps, exact baseline pixels/captions, side-label independence, no-focus
overviews, and mocked pipeline dispatch/failure. Complete AI Imaging passes
675 tests with 8 existing xfails; default-build inclusion passes 3 tests;
458 plugin mirror pairs match. All exit codes are 0.

In a private network-disabled replay, the four baseline images remained
byte-identical and two supplements were added. Total evidence was 6 images,
9,361,152 pixels, and 4,897,937 bytes within unchanged caps. Both supplements
contained seven planes spanning approximately +/-14.4 mm. All 57 original
session files retained their hashes. Rendering took 2.551 s in one local trial;
this is not a latency benchmark. No model run, build, or clinical validation
was performed. See [implementation section 30](EAGLE_EYE_LLM_STAGE2_2026-08-26.md#30-v3-bilateral-sagittal-experiment-and-scoped-root-scoring-2026-08-31)
for the budget comparison, packaging applicability, and trial/rollback steps.

### Phase 0: trustworthy baseline and scoring

**Partial implementation:** scorer 1.1.0 now scopes negation to root effects
instead of suppressing a root mention because a different attribute was
negated nearby. Root-negation guards reproduced 6 failures before the fix;
the scorer file now passes 25 tests. A saved report rescored as contact
(`under` against compression), not missing root involvement. Individual score
JSON records the scorer version and effect assertions. This does not repair
the remaining morphology, multi-component, root-identity/effect independence,
failed-attempt denominator, or reference-adjudication issues below.

**Deliverables:** independent morphology/presence scoring, explicit unknown states, reference-negative adjudication, configuration grouping, attempted-run accounting, and immutable baseline manifests.

**Files:** `tools/eagle_eye_bench/{reference,scoring,bench}.py` and `tests/code/ai_imaging/test_eagle_eye_bench_scoring.py`.

**Gate:** synthetic cases prove correct distinctions; existing saved sessions are rescored without changing their reports. No accuracy claim is made from the old aggregate alone.

### Phase 1: neutral attention contract without changing image rendering

**Deliverables:** versioned attention schema, diagnosis-neutral diagnostic adapter, explicit source references, both-plane anchor retention in the contract, unknown-level focus support, and coverage/budget dispositions. Initially keep the existing V3 evidence selection for the handoff comparison.

**Files:** `analysis_prompt.py`, `evidence_request.py`, `llm_backend.py`, and focused service tests. Add a small schema/adapter module inside `eagle_eye_lumbar` if that keeps the backend simpler.

**Gate:** no candidate diagnosis can leak through notes, raw parse-failure fallback, or unsourced current-context hypotheses. Historical diagnoses remain clearly sourced history. Malformed output produces an explicit degraded state, not a fabricated normal result.

### Phase 2: independent diagnostic contract and consistent report

**Deliverables:** one clinical-definition block, observation-oriented structured output, independent morphology/consequence fields, finding-specific sufficiency, a normal differential, and report/audit consistency validation.

**Files:** `analysis_prompt.py`, `llm_backend.py`, report/schema helpers in the lumbar service package, and `test_eagle_eye_llm_analysis.py`.

**Gate:** E1/E2 results are assessed together with misses and false positives. Existing tests that pin conflicting prose or the morphology-upgrade example are replaced with requirement-based guards; preserving those exact strings is not the goal.

### Phase 3: source-grounded localization and evidence selection

**Deliverables:** calibrated screening coordinates, exact rendering transforms, retained sagittal/axial anchors, lesion-region rather than image-center projection, clean/locator separation, merged overlapping crops, and coverage checks.

**Files:** `capture_controller.py` only for metadata capture where needed; otherwise `evidence_bundle.py`, `evidence_request.py`, `focus_evidence.py`, and reusable `evidence_core` helpers.

**Gate:** geometry round-trip and clinical coverage tests pass; E3/E4 demonstrate that the selected package contains the defining anatomy. No live viewer manipulation is needed after capture. Existing layout fallback remains available.

### Phase 4: optional bounded retrieval and measurement research

**Deliverables:** one bounded additional-evidence request if justified; optional clinician markups/measurements; specialist localization comparison only if earlier experiments identify a localization ceiling.

**Gate:** a measured benefit justifies added cost and latency. No automatic Slicer launch, unrestricted agent, or new default model layer is introduced.

### Promotion and rollback

Keep the known baseline available throughout. Promote only after the locked evaluation shows the predefined benefit without unacceptable loss of sensitivity, excess false positives, or new critical errors. A zero-new-critical-regression gate on the locked set is useful, but cannot guarantee safety on every future case.

Use an explicit source-build trial with the human launching and logging in once. Runtime changes, mirrors, configuration defaults, installer/profile handling, and builder parity must follow the repository packaging checklist before any build-default promotion. Do not infer that an environment-variable trial changed shipped defaults.

No database schema change or new external service is required for Phases 0-3. Any later stability/performance change must be recorded in the canonical optimization master plan under the relevant existing item, or a new item there if no matching concern exists; this research proposal is not a replacement stability tracker.

## 17. Regression guards required by the future implementation

| Guard | Required property |
|---|---|
| Neutral handoff | Diagnoses and grades are absent from the attention interface, including malformed-output paths |
| Source identity | Coordinates cannot resolve against another session, image, pane, or frame |
| Both-plane anchors | Ranked sagittal and axial anchors survive normalization and selection |
| Full bounded axial window | Select `min(slab_depth, 2*padding+1)` unique same-slab slices, retain the anchor, and backfill only within the slab |
| Unknown numbering | A valid focus is not dropped merely because its level is uncertain |
| Geometry round trip | Correct results with anisotropic spacing, reversed order, oblique slabs, rotation, flip, zoom, padding, and high-DPI captures |
| Coordinate convention | Explicit x/y, row/column, normalized point, box-edge, and pixel-center handling |
| Crop coverage | Defining region and required context remain inside the crop; nonblack alone is insufficient |
| Budget accounting | Every truncated focus has a visible disposition; omitted coverage is not normal |
| Multiplanar classification | A reliable defining observation is not mechanically vetoed by a nondiagnostic orthogonal view |
| Independent consequences | Morphology changes do not automatically alter stenosis or root effects |
| Multi-component disc | Background bulge and focal herniation can coexist in output and scoring |
| Clinical state distinctions | Absent, omitted, indeterminate, and unassessable remain distinct |
| Report consistency | Accepted reportable findings survive into the final report without contradictions |
| Benchmark integrity | Failed attempts remain in denominators; versions and reference revisions are not silently mixed |
| Worker lifecycle | Cancellation, stale callbacks, teardown, and fallback preserve session identity and GUI responsiveness |

Use synthetic phantoms and fictional clinical records in committed fixtures. Geometry and schema tests prove software behavior, not LLM diagnostic accuracy. Clinical evaluation needs separate approved data and radiologist review.

Each eventual bug fix needs its fail-before/pass-after guard, the relevant regression-catalog row, focused direct test results, and mirror parity where applicable. Documentation-only work does not claim those implementation gates have been completed.

## 18. Final recommendation and unresolved questions

Retain V3's headless physical-crop approach. Replace diagnostic candidate inheritance with a source-linked attention contract, preserve both-plane anchors, and ask the diagnostic reader to classify observations independently. Make the benchmark recognize detection, morphology, localization, and neural consequences as different tasks.

The strongest unresolved hypotheses are:

1. First-pass labels and context wording bias the diagnostic reader.
2. Current selection omits or underemphasizes the defining sagittal observation.
3. The confirmed axial focus-window clipping defect reduces clinically useful emphasis or detail, despite terminal frames remaining in the overview; its diagnostic effect is not yet established.
4. Conflicting acceptance rules suppress correct findings or force a less specific label.
5. Composites remain perceptually difficult despite adequate local sampling.
6. The general models have a clinically important perception limitation that prompting cannot reliably overcome.

Only controlled experiments can rank these explanations. The same model name in a chat interface and an application does not imply identical images, instructions, preprocessing, reasoning settings, or conversation context. A convincing answer in one chat is also not proof of reliable clinical performance.

Persistent cross-patient conversational memory is not the missing foundation. The useful memory is an **immutable, per-study evidence manifest**: what was presented, where it came from, what was selected, what remains unassessed, and which observation supports each conclusion. Keep benchmark truth out of that inference manifest.

The axial coverage repair, opt-in bilateral sagittal supplement experiment, and narrow root-negation correction are now implemented and verified offline. The next gates are clinician-supervised comparison of the evidence conditions, completion of Phase 0 with adjudication of reference negatives, and controlled E1/E2. Do not simultaneously replace prompts, rendering, model settings, and orchestration. If a properly localized, adequately resolved, label-free evidence package still fails reliably, investigate a specialist method or require human assessment rather than adding instructions that force the expected diagnosis.

## Repository reading map

These links are relative to this file in `docs/plans/`, not relative to the repository root or an external copy in `docs/eagle_eye/`. All eight targets were checked again after the follow-up feedback and resolve in this working tree. Copying the article to another folder requires rebasing its relative links; the current repository links do not need relocation.

- [Existing stage-two implementation history](EAGLE_EYE_LLM_STAGE2_2026-08-26.md)
- [Capture and series-resolution plan](EAGLE_EYE_LUMBAR_STAGE1_2026-08-26.md)
- [Prompt-design history](EAGLE_EYE_LLM_PROMPT_DRAFT_2026-08-26.md)
- [Current benchmark README](../../tools/eagle_eye_bench/README.md)
- [Verified subsystem and execution-domain map](../architecture/PRE_DEVELOPMENT_SYSTEM_MAP_2026-08-27.md)
- [Repository readiness and verification limitations](../reports/CODEX_REPOSITORY_READINESS_2026-08-27.md)
- [Canonical optimization/stability plan](../OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md)
- [Regression catalog](architecture/REGRESSION_CATALOG.md)

Public references are linked beside the claims they support. Provider documentation was checked on 2026-08-31; preview models and API behavior remain subject to change. No public source reviewed here establishes diagnostic performance for this exact model pair, GapGPT route, evidence package, and clinical population.
