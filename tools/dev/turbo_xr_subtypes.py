# -*- coding: utf-8 -*-
"""Radiography STUDY TYPES — the second gate axis, for X-ray.

⚠️ CLINICAL REVIEW REQUIRED. Compiled 2026-08-09. Not read by a radiologist.

WHY THESE ARE SUBTYPES AND NOT REGIONS. A hysterosalpingogram, a barium enema and a
colon transit study are all performed on the abdomen and pelvis, and share nothing else.
A bone age, a skeletal survey and a standing alignment film are all skeletal, and share
nothing else. Region is WHERE the study looked; subtype is WHAT KIND of study it is.
The axis was built for obstetric ultrasound and applies here unchanged.

Two of the requested categories are NOT subtypes and were handled as regions instead:
paranasal sinus radiography already has a region module, strengthened here with the
named projections; and pelvic bone radiography is the existing `pelvis` region.

WHERE PUBLISHED VALUES DISAGREE, NO NUMBER IS ENCODED. Lower-limb alignment is the worst
case in the whole project so far — the mechanical axis deviation normal is given as
4 ± 2 mm medial (EFORT), 8 ± 7 mm medial (Paley) and 3 mm either side (Gupta), and the
joint-angle normals are published both as mean ± 3° and as asymmetric ranges. Colon
transit has at least four protocols with different marker counts, film days and
thresholds, and the numbers are not transferable between them. Every rule below asks for
the physician's value together with the method or protocol it came from.

SOURCES: ACR Extremity Radiography (DocId=12); EFORT Open Reviews 2021 lower-limb
alignment (PMC8246117); Gupta J Clin Orthop Trauma 2020 (PMC7026560); boneaxis.org;
LSUHSC knee alignment; Hinton/Sitzmarks day-5 protocol; Metcalf (PMID 3023168); Arhan
(PMID 7318630); Chaussade/Abrahamsson via the NASPGHAN Southwell review; J Neurogastro
Motil marker studies (PMC5051174); Parks perianal fistula classification; RSNA
RadReport; StatPearls.

NOT COVERED: interventional and vascular fluoroscopy, which is a different report shape.
"""
from __future__ import annotations

from typing import Dict, List

XR_SUBTYPES: Dict[str, dict] = {}


def _s(key, title, technique, must, path):
    XR_SUBTYPES[key] = {"title": title, "technique": technique,
                        "must_report": must, "pathology": path}


# ═══════════════ contrast and fluoroscopic studies ═══════════════

_s("xr_hsg", "Hysterosalpingography",
   ["Preserve the phase of the cycle and any statement about pregnancy exclusion.",
    "Preserve the contrast agent, the volume used, and whether he described the "
    "injection as difficult, refluxing or painful - each qualifies the images."],
   ["Preserve the uterine cavity contour as he described it - size, shape, any filling "
    "defect, synechiae or septum - and any uterine anomaly classification he named, "
    "with the system.",
    "Preserve each tube separately by side: whether it filled, its course and calibre, "
    "and whether free peritoneal spill was seen. A tube that did not fill and a tube "
    "that is occluded are different statements.",
    "Preserve the spill as he described it - free, loculated, or absent - and the side.",
    "Preserve any intravasation of contrast into the myometrium or venous channels."],
   ["Never conclude tubal occlusion from a tube that failed to fill on one attempt. "
    "Preserve his wording, including any note of spasm or a repeat injection.",
    "Preserve any recommendation for laparoscopy, repeat study or antibiotic cover."])

_s("xr_rug", "Retrograde urethrography and voiding cystourethrography",
   ["Preserve which study was performed - retrograde, voiding, or both - and the "
    "catheter or technique used. A retrograde study shows the anterior urethra and a "
    "voiding study the posterior urethra and bladder neck; they answer different "
    "questions and one does not substitute for the other.",
    "Preserve the obliquity used. A urethra assessed on a straight AP is foreshortened."],
   ["Preserve each urethral segment by name - penile, bulbar, membranous, prostatic - "
    "and the calibre and appearance of each.",
    "Stricture - preserve the segment, the length in centimetres, the residual calibre, "
    "and whether he described it as single or multiple.",
    "Preserve bladder capacity, contour and any diverticulum or trabeculation.",
    "Preserve vesicoureteric reflux by side and by the grade he assigned, with the "
    "grading system named. Never assign a grade he did not state.",
    "Preserve any extravasation, false passage, fistula or contrast in the periurethral "
    "tissues."],
   ["Preserve post-void residual if he reported one, with how it was assessed.",
    "Preserve any statement that a segment was not distended or not assessed."])

_s("xr_ivp", "Intravenous pyelography / urography",
   ["Preserve the contrast agent, the dose and every timed film he described. The "
    "phases - nephrogram, pyelogram, delayed - answer different questions and a finding "
    "belongs to the phase it was seen in.",
    "Preserve any preliminary control film and what it showed. A calculus visible only "
    "on the control film is obscured once contrast is given.",
    "Preserve any compression, prone or post-void film, and any delayed film with its "
    "timing.",
    "Preserve any statement about renal function or non-excretion - a kidney that did "
    "not excrete is the central finding of the study, not an omission."],
   ["Preserve each kidney separately: position, axis, size, contour and the timing and "
    "symmetry of its nephrogram.",
    "Preserve the pelvicalyceal system on each side - calyceal architecture, any "
    "blunting, clubbing or dilatation - and the level of any obstruction.",
    "Preserve ureteric course, calibre and any filling defect or deviation, by side and "
    "by segment.",
    "Preserve the bladder outline, any filling defect, and the post-void appearance."],
   ["Preserve any filling defect exactly as characterised, and never convert a filling "
    "defect into a diagnosis he did not give.",
    "Preserve the study's stated limitation. Urography assesses the collecting system "
    "and excretion, not renal parenchymal lesions, and any such caveat he made must "
    "survive."])

_s("xr_barium_swallow", "Barium swallow and oesophagram",
   ["Preserve the contrast used and whether the study was single- or double-contrast. "
    "Double contrast shows mucosal detail; single contrast shows distensibility, "
    "strictures and motility better. Preserve which was performed.",
    "Preserve the positions and phases he screened - erect, prone oblique, supine, "
    "Trendelenburg - and any water-siphon or provocative manoeuvre.",
    "Preserve any use of a barium tablet or marshmallow for a suspected stricture."],
   ["Preserve the swallowing phases he assessed, and any penetration or aspiration with "
    "the consistency it occurred on and any scale he applied.",
    "Preserve pharyngeal findings separately from oesophageal ones - pooling, residue, "
    "cricopharyngeal bar, pouch.",
    "Preserve oesophageal motility as he described it - primary and secondary "
    "peristalsis, tertiary contractions - since motility is only assessable "
    "fluoroscopically.",
    "Preserve any stricture with its level, length and calibre, and any mucosal "
    "abnormality, ulcer, ring or web.",
    "Preserve hiatus hernia with its type and size, and reflux with the manoeuvre that "
    "provoked it."],
   ["Preserve his wording on aspiration exactly. Silent aspiration and aspiration with "
    "cough are different findings, and any recommendation for a speech and language "
    "assessment must survive.",
    "Preserve any suspected perforation or leak and the contrast agent used, since a "
    "suspected perforation changes which agent is safe."])

_s("xr_barium_meal", "Barium meal and upper gastrointestinal study",
   ["Preserve whether the study was single- or double-contrast and whether an "
    "effervescent agent and a hypotonic drug were given. Mucosal relief depends on both.",
    "Preserve the fasting state and the positions screened."],
   ["Preserve the oesophagus, stomach and duodenum as separate sections.",
    "Preserve gastric distensibility, rugal pattern, and any ulcer with its site, size "
    "and whether he called it benign or malignant in appearance.",
    "Preserve any filling defect, mass or rigid segment with its location.",
    "Preserve the duodenal cap and loop, and any deformity, diverticulum or "
    "extrinsic impression.",
    "Preserve gastric emptying and any delay he observed."],
   ["Preserve his characterisation of an ulcer exactly. Benign and malignant features "
    "are his call from the fluoroscopic appearance and must not be softened or upgraded.",
    "Preserve any recommendation for endoscopy."])

_s("xr_sbft", "Small-bowel follow-through and enteroclysis",
   ["Preserve whether this was a follow-through or an enteroclysis via a nasojejunal "
    "tube - they have different sensitivity and different distension.",
    "Preserve the timing of each film and the total transit time to the caecum.",
    "Preserve any compression or spot views of the terminal ileum, which is the segment "
    "the study most often exists to answer."],
   ["Preserve small-bowel calibre, fold pattern and distribution as he described them, "
    "by segment.",
    "Preserve the terminal ileum specifically - calibre, fold thickening, ulceration, "
    "stricture, separation of loops.",
    "Preserve any stricture with its length and the degree of narrowing, and any "
    "proximal dilatation.",
    "Preserve fistula, sinus tract or abscess cavity with its course.",
    "Preserve transit time and any statement of delay."],
   ["Preserve his distinction between a fixed narrowing and a transient contraction - "
    "only the fluoroscopist can make it, and it is lost if the wording is generalised.",
    "Preserve any recommendation for cross-sectional enterography."])

_s("xr_barium_enema", "Barium enema",
   ["Preserve whether the study was single- or double-contrast. Double contrast shows "
    "mucosal detail and small polyps; single contrast is better for obstruction, "
    "fistula and in the frail or unprepared patient. Preserve which was performed and "
    "why if he said.",
    "Preserve the bowel preparation and its adequacy. Residual faecal material limits "
    "the study and any such statement qualifies everything after it.",
    "Preserve any water-soluble agent used instead of barium, and the reason - "
    "suspected perforation or a planned surgery changes the agent.",
    "Preserve whether the caecum was reached and refluxed into the terminal ileum."],
   ["Preserve each colonic segment by name - rectum, sigmoid, descending, splenic "
    "flexure, transverse, hepatic flexure, ascending, caecum.",
    "Preserve any filling defect with its segment, size and morphology, and whether he "
    "called it sessile or pedunculated.",
    "Preserve strictures with segment, length and shoulder morphology, and any "
    "proximal dilatation.",
    "Preserve diverticular disease with its distribution and severity.",
    "Preserve mucosal abnormality, haustral loss and any fistula or extravasation."],
   ["Preserve his statement about segments that were not adequately distended or "
    "coated. On an enema, a poorly seen segment is a reported limitation.",
    "Preserve any recommendation for colonoscopy or CT colonography."])

_s("xr_fistulography", "Fistulography",
   ["Preserve the external opening he catheterised, its site, and the contrast volume "
    "and injection pressure he described.",
    "Preserve the projections used and any statement that the tract was not fully "
    "opacified - an unopacified branch is not an absent branch."],
   ["Preserve the tract's course, length and calibre, and every branch or secondary "
    "tract he demonstrated.",
    "Preserve the internal opening if he identified one, with its position, and say so "
    "if he did not.",
    "Preserve the relationship of the tract to any named structure - for a perianal "
    "fistula, to the internal and external sphincters, the levator plate and the "
    "ischiorectal fossa.",
    "Preserve any Parks classification he assigned, with the type. Never assign a type "
    "he did not state - Parks is defined by the relationship to the sphincter complex "
    "and a fistulogram may not show it.",
    "Preserve any abscess cavity, communication with bowel, bladder or skin, and any "
    "extravasation."],
   ["Preserve the anatomical region. Fistulography is performed at many sites and a "
    "tract described without its region is not actionable.",
    "Preserve any recommendation for MRI, which resolves the sphincter relationship "
    "that a fistulogram often cannot."])


_s("xr_colon_transit", "Colon transit time with radiopaque markers",
   ["Preserve the protocol by name and its parameters: how many markers, how many "
    "capsules, on which days, and on which day the film was taken. At least four "
    "protocols are in use - single-capsule day 5, Metcalf, Arhan, Chaussade - with "
    "different marker counts, different film days and different thresholds. A marker "
    "count means nothing without the protocol it belongs to and must never be read "
    "against a different one.",
    "Preserve any laxative, enema or medication he recorded as withheld or taken during "
    "the study period."],
   ["Preserve the total number of markers retained, and the number in each colonic "
    "segment - right colon, left colon, rectosigmoid - as he counted them.",
    "Preserve the segmental landmarks he used, if he stated them. The segments are "
    "defined by lines drawn on the film and different sources draw them differently.",
    "Preserve any transit time in hours he calculated, together with the formula or "
    "protocol it came from.",
    "Preserve the distribution pattern as he described it - scattered throughout the "
    "colon, or accumulated in the rectosigmoid. That pattern is the interpretation, "
    "not the count.",
    "Preserve the number and dates of all films if the study ran over several days."],
   ["Never convert a retained-marker count into a diagnosis. Slow-transit constipation "
    "and a defecation disorder are distinguished by the distribution and by thresholds "
    "that are protocol-specific, and the published cut-offs disagree.",
    "Preserve his conclusion in his words - normal transit, slow transit, outlet "
    "obstruction, or inconclusive - and any recommendation for anorectal manometry, a "
    "defecography or a repeat study at a longer interval."])

# ═══════════════ musculoskeletal and spine study types ═══════════════

_s("xr_limb_alignment", "Standing lower-limb alignment (long-leg film)",
   ["Preserve that the film was weight-bearing and full-length from hip to ankle, and "
    "preserve the patellar position - the patellae must face forward, because limb "
    "rotation alters the measured angles substantially.",
    "Preserve whether a calibration marker or ruler was in the field. Every length in "
    "millimetres is magnification-dependent without one; the angles are not.",
    "Preserve any statement of fixed flexion at the knee, which invalidates the "
    "coronal measurement.",
    "Preserve what the film cannot answer - it is a coronal study and says nothing "
    "about sagittal deformity or torsion."],
   ["Preserve each angle he measured, by its abbreviation, with its value and side: "
    "hip-knee-ankle angle, mechanical axis deviation, mechanical lateral distal femoral "
    "angle, medial proximal tibial angle, lateral distal tibial angle, joint line "
    "convergence angle, medial proximal femoral angle.",
    "Preserve whether he reported the mechanical or the anatomical tibiofemoral angle, "
    "and any anatomical-mechanical offset he applied. They differ by several degrees "
    "and are not interchangeable.",
    "Preserve the mechanical axis deviation with its direction, medial or lateral, and "
    "in millimetres.",
    "Preserve femoral and tibial segment lengths and any limb-length discrepancy, with "
    "the side that is shorter and the calibration method.",
    "Preserve his statement of where the deformity is - femoral, tibial, both, or "
    "intra-articular - since that is what the joint angles exist to localise."],
   ["Preserve every value as his. Published normals for these angles disagree between "
    "sources - mechanical axis deviation alone is given as 4 plus or minus 2 mm medial, "
    "as 8 plus or minus 7 mm medial, and as 3 mm either side - and the joint angles are "
    "published both as a mean with a tolerance and as asymmetric ranges. Never restate "
    "his figure against a different reference or convert it into a verdict.",
    "Preserve his terms for the deformity - genu varum, genu valgum - only where he "
    "used them, and never derive one from an angle he reported.",
    "Preserve any planned correction, osteotomy level or surgical recommendation."])

_s("xr_spine_alignment", "Total spine and alignment views",
   ["Preserve that the film was upright and full-length, and preserve whether it was "
    "taken PA or AP, since the projection changes both dose and apparent rotation.",
    "Preserve any statement that a curve was measured on a supine film. A curve is "
    "called major only from an upright radiograph.",
    "Preserve whether the study included the femoral heads, which the sagittal "
    "parameters depend on."],
   ["Preserve every Cobb angle with the end vertebrae he selected, the direction of "
    "convexity and the region of the curve. A Cobb angle without its end vertebrae "
    "cannot be reproduced on the next study.",
    "Preserve the apex of each curve and whether he called a curve structural or "
    "compensatory.",
    "Preserve coronal and sagittal balance measurements with the plumb line he used.",
    "Preserve sagittal parameters by name where he gave them - thoracic kyphosis, "
    "lumbar lordosis, pelvic incidence, pelvic tilt, sacral slope - with the levels.",
    "Preserve vertebral rotation and any method he named for grading it, and shoulder "
    "or pelvic obliquity.",
    "Preserve skeletal maturity if he assessed it, with the index used."],
   ["Preserve any comparison with a prior study, including the interval and the prior "
    "values. On an alignment film, progression is the finding.",
    "Preserve any Lenke or King classification only if he assigned one."])

_s("xr_spine_flexion_extension", "Flexion and extension views",
   ["Preserve that both a flexion and an extension film were obtained, and preserve any "
    "statement that the range achieved was limited by pain or guarding - an inadequate "
    "excursion cannot exclude instability and that caveat must survive.",
    "Preserve whether the films were upright or supine and whether they were "
    "physician-supervised."],
   ["Preserve translation in millimetres and angulation in degrees at each level, "
    "measured between the two films, and the method he used.",
    "Preserve which level or levels he assessed, and preserve any level he could not "
    "assess.",
    "Preserve the position of any listhesis on each film separately - a slip that "
    "reduces on extension is a different finding from a fixed one.",
    "Preserve any hardware and its position on both films."],
   ["Preserve his conclusion about instability in his words. Published millimetre and "
    "degree criteria vary and this study exists to answer that question, so never "
    "derive the conclusion from the measurements yourself.",
    "Preserve any statement that the study was non-diagnostic."])

_s("xr_spine_oblique", "Oblique spine views",
   ["Preserve that oblique views were obtained and the side of each, since the oblique "
    "shows the pars and the facets on the side towards or away from the film depending "
    "on the projection.",
    "Preserve the region examined."],
   ["Preserve the pars interarticularis on each side at each level examined, and any "
    "defect with its level and side.",
    "Preserve the facet joints and the neural foramina as he described them, by level "
    "and side.",
    "Preserve any statement that a level was obscured or not adequately profiled."],
   ["Preserve his wording about a suspected pars defect. Preserve any recommendation "
    "for CT or SPECT, which is what resolves an equivocal oblique."])

_s("xr_bone_age", "Bone age",
   ["Preserve which hand was radiographed - the left is conventional - and the "
    "projection.",
    "Preserve the method he used by name. Greulich-Pyle reads the film against an atlas "
    "of standards; Tanner-Whitehouse scores individual bones and sums them. They "
    "produce different numbers from the same film and are not interchangeable, so a "
    "bone age without its method cannot be compared with a previous one."],
   ["Preserve the chronological age, with the date of birth or the age in years and "
    "months as he gave it.",
    "Preserve the assessed skeletal age with the method, and any standard deviation or "
    "range he quoted with it.",
    "Preserve his comparison between the two - advanced, delayed, or concordant - and "
    "the magnitude of any difference.",
    "Preserve the specific epiphyses and carpal ossification centres he based the "
    "assessment on, if he named them.",
    "Preserve the sex used for the reference standard. The atlas standards are "
    "sex-specific and a bone age read against the wrong standard is wrong."],
   ["Never compute a skeletal age, a percentile or a predicted adult height from the "
    "findings. Each depends on the method and its reference population.",
    "Preserve any incidental skeletal finding on the hand film separately.",
    "Preserve any recommendation for endocrine referral or interval reassessment."])

_s("xr_skeletal_survey", "Skeletal survey / bone survey",
   ["Preserve the indication, because the projection list differs by indication - "
    "myeloma, metastatic disease, suspected physical abuse in a child, and skeletal "
    "dysplasia are four different protocols.",
    "Preserve the complete list of projections actually obtained, and any region that "
    "was not imaged. A survey is defined by its coverage, and an unimaged region is a "
    "reported limitation, not a normal one.",
    "Preserve any statement he made about the sensitivity of radiography for the "
    "indication, and any recommendation for whole-body low-dose CT, MRI or bone "
    "scintigraphy - for myeloma in particular, current guidance has moved away from "
    "the radiographic survey as first-line."],
   ["Preserve findings region by region, in the order he surveyed - skull, spine, "
    "thorax and ribs, pelvis, and each long bone by side.",
    "Preserve every lesion with its bone, its position within the bone, its size, and "
    "whether he called it lytic, sclerotic or mixed.",
    "Preserve any pathological fracture, cortical breach, periosteal reaction or soft "
    "tissue component.",
    "Preserve the overall bone mineralisation and any diffuse abnormality.",
    "Preserve explicitly that a region was normal where he said so - on a survey, a "
    "normal region is a positive statement of coverage."],
   ["In a suspected-abuse survey, preserve every fracture with its age or stage of "
    "healing exactly as he described it, and preserve any statement about the number of "
    "fractures and whether they are of different ages. Never estimate or harmonise "
    "fracture ages.",
    "Preserve any recommendation for a follow-up survey at an interval, which is part "
    "of the standard protocol in suspected abuse.",
    "Preserve any comparison with a prior survey, including which lesions are new."])

# ═══════════════ specialised projections ═══════════════

_s("xr_nasal_bone", "Nasal bone radiography",
   ["Preserve the projections obtained - a lateral soft-tissue nasal view and, where "
    "taken, an occipitomental or a superoinferior axial. A nasal fracture is often "
    "visible on only one.",
    "Preserve any statement that the study does not exclude a nasal fracture and that "
    "the diagnosis is clinical. That caveat is the most important sentence in this "
    "report and must not be dropped.",
    "Preserve any soft-tissue swelling that limited the assessment."],
   ["Preserve the nasal bones and the frontal process of the maxilla as separate "
    "structures.",
    "Preserve any fracture with its side, whether he called it displaced or "
    "undisplaced, and the direction of any displacement.",
    "Preserve the nasal septum and any deviation or fracture.",
    "Preserve the anterior nasal spine and the visualised frontal sinuses.",
    "Preserve any radiolucent line he explicitly identified as a normal suture or "
    "vascular groove rather than a fracture. That distinction is the whole difficulty "
    "of this study."],
   ["Preserve his wording on displacement, since it determines whether reduction is "
    "offered.",
    "Preserve any suspicion of a wider facial injury and any recommendation for CT."])

_s("xr_shoulder_special", "Specialised shoulder projections",
   ["Preserve every projection by name - axillary, Grashey or true AP, scapular-Y, "
    "Stryker notch, West Point, Garth, outlet - because each exists to answer one "
    "question and a finding must be attributed to the view that shows it.",
    "An AP alone cannot establish the direction of a dislocation. Preserve his "
    "statement of which view demonstrated it.",
    "Preserve any view that was attempted and not obtained because of pain."],
   ["Preserve the glenohumeral relationship as seen on the axillary or scapular-Y, and "
    "the true joint space as seen on the Grashey view.",
    "Preserve any Hill-Sachs or bony Bankart lesion with the view it was seen on.",
    "Preserve the acromial morphology and the subacromial space where an outlet view "
    "was taken.",
    "Preserve the acromioclavicular joint and any comparison with the opposite side."],
   ["Preserve the direction of any dislocation and the view that established it.",
    "Preserve any recommendation for CT or MR arthrography for bone loss quantification."])

_s("xr_mastoid", "Mastoid and petrous temporal projections",
   ["Preserve every projection by name - Schuller, Law, Stenvers, Towne - and the side. "
    "Each profiles a different part of the temporal bone and a finding belongs to the "
    "view that showed it.",
    "Preserve any statement that plain films do not exclude temporal bone pathology and "
    "that CT is the modality of choice. Preserve any recommendation that follows."],
   ["Preserve the degree of mastoid pneumatisation on each side and any comparison "
    "between them.",
    "Preserve the clarity of the air cells, any loss of trabeculation, and any "
    "sclerosis or coalescence.",
    "Preserve the sinodural angle and the sigmoid sinus plate where he described them.",
    "Preserve the internal auditory canal and petrous apex where a Stenvers or Towne "
    "view was taken."],
   ["Preserve the side with every finding.",
    "Preserve his distinction between under-pneumatisation and opacification - they are "
    "different findings with different meanings."])
