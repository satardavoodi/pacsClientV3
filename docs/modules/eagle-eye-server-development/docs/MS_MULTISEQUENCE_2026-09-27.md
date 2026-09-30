# Cross-plane MS candidates and T1 contrast review

Date: 2026-09-27. Status: source candidate; not a clinical qualification or Razi activation receipt.

## User workflow

Select MS reporting context and 2D acquisition mode. The study-series picker accepts:
1. T1 anatomical reference, before contrast when contrast review is requested.
2. Primary axial 2D FLAIR.
3. Optional independent sagittal 2D FLAIR.
4. Optional matching original 3D T1 after contrast.

Matching VIBE descriptions and series order can suggest a post-contrast selection. The clinician verifies the roles; order alone is not evidence of injection. Patient/study identity remains mandatory. Different FrameOfReferenceUID values are accepted only in the explicit registration path. Pre/post T1 must have matching TR, TE, flip angle and sequence family; derived subtraction/MPR inputs are rejected. Missing contrast tags do not invent a contrast administration record.

The existing background executor and brain analysis lock are reused. The PACS remains independent of inference. No new test-only feature flag or inference environment is introduced. Standard clients send counted series references; the server resolves inputs and returns the PDF, masks and review images. Optional roles require the `lesion_multisequence_review` capability. Single-FLAIR requests retain compatibility with older servers.

## Computation and reporting

- Run the existing native-2D MindGlide pipeline independently on each FLAIR, including reversible smooth-band review. Preserve native masks and individual measurements.
- Rigidly register the second FLAIR to the primary. Restrict corroboration to actually acquired secondary slice slabs. Interpolation is not evidence in slice gaps.
- Match native secondary component identities after nearest-neighbor resampling, avoiding recounting disconnected resampling fragments as new lesions.
- Retain full primary components with at least 3 overlapping primary-grid voxels, 0.5 mm3 overlap and 10% primary component overlap. These are explicit, unvalidated engineering thresholds.
- Main counts and sampled-slab volumes describe cross-plane-supported primary candidates. Do not average views, add their volumes or call candidates confirmed MS lesions. Preserve primary-only findings in a blue review mask and secondary native findings separately. Secondary counts on the primary grid exclude unavailable coverage.
- Smooth caps, bands and shared artifacts can appear in both planes. Agreement alone does not establish pathology. Strict corroboration can reduce sensitivity; one-plane findings must remain reviewable.
- Register post-T1 to pre-T1, normalize each within common Otsu foreground using 0.5/99.5 percentiles, then subtract. Supply original pre-T1, registered post-T1, subtraction and transforms. Map subtraction to primary FLAIR only for review and candidate measurements.
- Evaluate every primary candidate, including one-plane candidates. Less than 95% foreground/coverage support yields N/A. Global intensity differences can remain; normalized deltas are not enhancement probabilities or a diagnosis. No automatic enhancing/non-enhancing label or validated threshold is applied.
- PDF includes support/disagreement counts, candidate subtraction values, alignment panels, colored FLAIR previews, scientific method references and limitations. The existing native-2D topography remains review-required; this feature does not fabricate McDonald criteria fulfillment.
- Manual edits invalidate earlier cross-plane and enhancement measurements, retaining them only as source history. Report-context regeneration is blocked for these combined results; rerun with the intended context.

## Scientific basis and model choice

- MAGNIMS-CMSC-NAIMS MRI recommendations (2021): https://pubmed.ncbi.nlm.nih.gov/34139157/ . 3D FLAIR is preferred; 2D slice gaps remain a material limitation.
- MindGlide, Nature Communications (2025): https://www.nature.com/articles/s41467-025-58274-8 . This is the existing native-2D segmentation backend, not an enhancement classifier.
- MS lesion interpretation guidelines: https://pmc.ncbi.nlm.nih.gov/articles/PMC6598631/ . Location and morphology require interpretation; shared-plane signal is not sufficient evidence of MS.
- Subtraction-assisted reading: Beyrle et al., European Journal of Radiology (2026), https://doi.org/10.1016/j.ejrad.2025.112576 . The study used brain masking; our Otsu support is different and is not equivalent validation. The observed pilot had residual global intensity differences, so enhancement remains visual review only.
- HD-MS-Lesions: https://github.com/CCI-Bonn/HD-MS-Lesions ; original work https://doi.org/10.1007/s00330-019-06593-y . It accepts T1, contrast T1, T2 and FLAIR and predicts CE and T2 lesions. Legacy Linux/Python3.6/CUDA requirements and training acquisition differences (3T/MPRAGE versus the available 1.5T/VIBE) require a separate qualified worker. No weights were installed and no superiority claim is made.
- Alternative research implementation: https://github.com/sibajigaj/Gad_lesion_segmentation ; https://pmc.ncbi.nlm.nih.gov/articles/PMC8409666/ . Additional PD and tissue-map inputs make this less direct for the current acquisition.

## Verification and deployment boundary

Initial five synthetic tests failed before the feature existed; the explicit frame-registration guard failed before the identity change. Final focused suite: 94 passed, exit 0; adjacent manual/context/study/server-review/build-payload suite: 95 passed, exit 0. Two additional manual-invalidation/artifact guards subsequently passed with the complete 16-test feature file. Total unique affected tests: 191. SimpleITK deprecation and synthetic DICOM VR warnings remain; no lint pass is claimed.

A private authorized local MRI pilot completed both real model runs and registration in about 481 seconds. Final review changes reused hash-verified native inference from that same run and recomputed registrations, matching and PDF in about 40 seconds. This is cached-inference replay, not a second independent model run. The final 15-page PDF was rendered and visually inspected; no identifiers, images or patient result tables are stored here. Registration panels showed aligned gross anatomy with expected thick-slice blur; this does not certify lesion boundaries or enhancement.

Offscreen selector tests passed. Live source GUI acceptance is pending: the existing control client could not connect to the test server. No Razi listener was restarted, no active remote revision was changed, and no installer was produced. Complete fresh source GUI input/run/export acceptance, then a scoped versioned server candidate/API/artifact acceptance before activation. Existing service receipts do not cover this new capability.

Mirror dry-run found no applicable Brain/remote plugin mirrors and no drift. Repository verifier: 473 pairs match. Keep the existing model assets on Eagle Eye Server; this change does not copy them into Standard Client.

## Source map

`modules/ai_imaging/eagle_eye_brain/lesion_multisequence.py`: registration, gap support, matching, subtraction and PDF additions.
`lesion_widget.py`: study-series picker and worker inputs.
`lesions.py`, `lesions_2d.py`, `patient_context.py`: routing, explicit frame registration and identity.
`lesion_report.py`, `lesion_report_2d.py`, `manual_review.py`, `lesion_indication.py`: reporting and revision provenance.
`modules/ai_imaging/eagle_eye_remote/{routing,contracts,adapters,server,artifacts}.py`: reference-only transport, capabilities and derived artifact allowlist.
`tests/code/ai_imaging/test_lesion_multisequence.py`: synthetic geometry, transport, selector and revision guards.

## Same-day picker correction: disabled second 2D FLAIR

The user screenshot showed the picker in inherited 3D mode. The second-plane combo was intentionally disabled, but the modal picker had no local acquisition selector or actionable explanation. Added a local 2D/3D selector; switching to 2D enables the second plane and updates labels. Switching to 3D clears the unsupported second input and requires confirmation again. Accept commits the mode and selected series together; Cancel preserves the parent state. No inference, patient data or server protocol changed.

Two synthetic acceptance/cancellation guards failed before the fix; 64 focused picker, study-workflow and 2D tests passed afterward (exit 0). The source bridge was unreachable, so fresh native GUI acceptance is pending a human source restart/sign-in. Applicable to Standard Client and Eagle Eye UI through canonical source; no installer or active Razi revision changed. Existing package guards are not an artifact receipt. Rollback only this picker-mode change, preserving the earlier multi-sequence worker.

### Mode-specific presentation follow-up

User requested hidden irrelevant inputs rather than disabled controls. The second-plane 2D FLAIR label and combo are now hidden in 3D mode. Large blue section headings identify 2D/3D FLAIR and the optional 3D contrast input. T1 context in 2D mode is not incorrectly labeled as necessarily 3D. A behavioral visibility guard failed before and passed after; 65 related tests passed. Source GUI remains pending; no model or transport changes.

### Numeric series order follow-up

Study selection previously sorted preferred T1 first, then SeriesNumber strings. It now sorts numerically across all sequence types; absent/invalid numbers follow valid numbers, preserving tie order. Preferred metadata remains available without reordering the dropdown. VIBE pair suggestions use the same numeric key. The synthetic ordering guard failed before the fix; 45 affected feature/study tests passed afterward. Live GUI remains pending. This shared Eagle Eye study loader also supplies volumetry and longitudinal selectors; no database or viewer ordering is changed.

## Anatomical location and focal-increase evidence follow-up

The previous report used fixed unclassified enhancement rows and unavailable native-2D topography. New `lesion_characterization.py` computes descriptive native-slab locations from same-source SynthSeg T1 anatomy and performs an exploratory paired-T1 focal-increase screen. It does not install or emulate the published HD-MS-Lesions neural network.

Locations: primary component IDs, left/right/bilateral assignment from anatomical labels, in-plane WM-side ventricular/cortical contact, supratentorial/infratentorial overlap. Never bridge a FLAIR slice gap to establish contact. Overlapping categories are not additive. Corpus callosum remains unavailable if the atlas has no explicit callosal labels. No fabricated lobar allocation or McDonald fulfillment is produced. The multi-sequence worker computes anatomy once after the two native inferences; standalone MS 2D analysis can enrich locations when the accompanying T1 meets the <=2-mm anatomy input path. Thick T1 retains the review-required fallback. This adds server processing time, not GUI-thread work.

Enhancement screen: register post-T1 to pre-T1; map original FLAIR component IDs onto acquired slabs of native T1. Calibrate gain/offset from eroded, non-lesional GM/WM medians at least 5 mm from candidates. Normalize residuals to pre-T1 WM median signal, not the small GM-WM difference of low-contrast VIBE. WM noise excludes cortical vessels. Record whole-brain pre/post correlation, robust WM noise, calibration and threshold. Engineering quality gates: >=500 reference voxels per tissue, positive gain in (0.1,10), brain correlation >=0.8 and relative robust noise <=0.15. These are unvalidated engineering gates, not clinical accuracy estimates.

A candidate increase must exceed max(0.1 WM signal, median+5 robust noise units, WM residual P99.9), with a connected positive region >=3-mm Feret diameter and >=3 mm3. More than half of qualifying positive volume associated with clusters predominantly within 1.5 mm of CSF/cortical boundaries yields an indeterminate boundary-effect flag. Thresholds, volume cutoff and boundary rule are exploratory; Filippi 2019 supports the clinical enhancement concept and >=3-mm imaging definition, not this algorithm. Vessel suppression and clinical validation remain incomplete. Injection delay is unverified and is explicitly reported.

Outcomes are `Possible enhancement; confirm on native T1`, `No focal increase detected by screen`, `Indeterminate: boundary-associated signal increase`, or `Not evaluable` with a concrete reason. No screen-negative row excludes enhancement. Missing candidate IDs or inadequate T1 field/sampling cannot become negative claims. Native T1 review crops use the same window for pre and calibrated post images. Subtraction panels use amber/cyan (positive/negative), distinct from red/blue FLAIR support/disagreement. Primary IDs are shown in FLAIR previews. Manual revisions invalidate all earlier locations and contrast measurements; changing report context requires rerunning these results.

Server artifacts include mapped anatomy, transforms and primary IDs in T1. Internal anatomy reports are excluded from exports. Existing model assets stay server-side. No new runtime flag or package dependency was added. Razi activation and installer acceptance have not been performed.

Verification: initial three tests failed before the new module; six synthetic characterization tests now cover contact gaps, global gain/offset versus focal increase, missing coverage, missing IDs, boundary-associated increase and failed-pair quality. The 145-test affected suite passed (exit 0); the extended manual-history guard subsequently passed. Mirror dry-run has no applicable additions/drift; 473 pairs match. A fresh same-patient T1 anatomical computation completed; hash-verified prior native FLAIR inference was reused while registrations and characterization were recomputed. The 21-page private review PDF was rendered and inspected; the image-paragraph layout was repaired and affected pages re-rendered. No patient data or result tables are stored in this document. Native source GUI and active service acceptance remain separate pending gates.


## Three-color agreement and pre-contrast T1 corroboration

The worker preserves primary and native secondary candidates and writes `labels-cross-plane.nii.gz` for visualization: 1 blue primary-only, 2 magenta secondary-only, 3 green matched component extents. Physical slice normals supply plane names. These are component agreements, not exact voxel intersections. Green takes precedence over blue, then magenta in spatial overlaps. Native secondary findings outside the primary coverage remain in the secondary mask and T1 review table. The display never replaces the native primary volume measurement. Smooth-band review remains separate; color does not encode enhancement.

`lesion_corroboration.py` measures pre-contrast lesion/WM median ratios on registered native T1. The exploratory screen excludes CSF/cortical boundaries within 1.5 mm, requires at least 50% interior tissue and 3 mm3 core, and marks ratios below 0.8 as supportive low signal. These are unvalidated engineering thresholds, not published normative limits. Missing mapped candidates are explicitly not evaluable. Primary IDs use P and unmatched native secondary IDs use S. This does not remove FLAIR candidates, establish chronic black holes, or replace enhancement assessment. Registration, bias field, partial coverage and sequence-dependent contrast require visual review. Scientific context: Frontiers in Neurology 2021, doi:10.3389/fneur.2021.619135; the paper does not validate this algorithm.

Verification: new regression guards failed before implementation (missing module), then focused suite 147 passed. Synthetic checks cover three-class extents, secondary-only preservation, missing T1 candidates, and CSF boundary exclusion. Mirror dry run found no applicable new mirror; 473 existing pairs match. Private report replay uses verified cached native inference plus recomputed registrations, T1 corroboration and PDF; it is not an independent model validation. Running-source GUI acceptance and Razi activation remain pending. No release/build/deployment performed.

Private cached-inference replay completed in 65.2 seconds; final 25-page PDF rendered and visually checked as a complete page montage. Three-color panels and separate T1 tables are present. Test bridge responds to ping, but the already-running process has not loaded the new source; live acceptance remains pending restart/login by the operator.


## Patient-report citations and T1 interpretation refinement
Patient-facing lesion and volumetry reference pages cite journal articles and DOI identifiers instead of repository links or pinned commits. Internal source URL, revision metadata and attribution/license records remain intact. Scientific provenance must not imply that the cited studies validate our experimental thresholds. T1 hypointensity is reported as an additional finding associated, when persistent, with tissue injury and axonal loss; chronicity requires longitudinal confirmation and no direct neuronal-loss measurement is claimed. Added Andermatt et al., Journal of Neuroimaging (2017), doi:10.1111/jon.12439.

Two new report guards failed before the edit; 30 characterization/multisequence and 36 reference/report/build guards passed afterward. Regenerated the existing private 25-page report without rerunning inference; checked the updated rendered page and absence of repository URLs in extracted PDF text. Mirror verification: 473 matching pairs. Source GUI acceptance and remote activation remain pending.


## Shared PDF readability
The shared brain PDF writer now breaks narrative sentences onto separate lines, retaining inline markup and protecting tables, images, DOI/URL and author-citation paragraphs. Qt-native block formatting applies 135% leading and at least 9-point paragraph bottom spacing outside tables/images. Numeric cell alignment, content, clinical calculations and running furniture are unchanged. Explicit sections and Qt continuation pagination remain in use.

`test_brain_report_readability.py` failed before implementation (missing helper); 25 focused readability/reference/patient-report tests passed after. The existing private 25-page lesion report was regenerated from saved measurements, all pages rendered and the complete montage inspected: no observed content overflow or image/footer collision. This is artifact verification, not a fresh-source GUI acceptance or remote deployment. Volumetry uses the same writer; reference/patient-report guards pass, but no real volumetry case was regenerated in this edit.


## Shared report coverage: volumetry, alignment and total spine
Confirmed consumers of the shared readable PDF writer: organized brain volumetry, MS/WM lesions, multi-T1 comparison, manual brain addendum, lower-limb Alignment and Total Spine. The legacy single-section brain writer now also delegates to this writer instead of separate QTextDocument printing. Lumbar result-panel inspection did not reveal a dedicated PDF writer in that module; do not claim unrelated workstation print routes were changed.

Total Spine method content now has Curve geometry, Balance and annotation colors, Interpretation limits and Coronal landmark proposals subsections. Scientific references start on their own page to avoid crowding. A basic synthetic report now has four pages; the five-curve test has eight. No measurements, landmarks or clinical interpretation were changed.

Verification: single-section delegation guard failed before the edit. Final focused report/packaging suite: 53 passed. Generated and visually inspected synthetic volumetry (20 pages), lower-limb alignment (3 pages) and total spine (4 pages), with complete montage review and full-size updated method/reference pages. These examples are synthetic, not patient results or clinical validation. Mirror verification: 486 pairs match, no drift. Fresh-source GUI and remote deployment acceptance remain pending; no release produced.
