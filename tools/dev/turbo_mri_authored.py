# -*- coding: utf-8 -*-
"""MRI pathology rules per region - compiled from the published literature.

⚠️ CLINICAL REVIEW REQUIRED. Compiled 2026-08-09. Not read by a radiologist.

WHAT IS EXTRACTED VS WHAT IS HERE
    extracted   the MRI normal-findings blocks, the MRI grouping vocabulary and the
                sequence lexicon all already exist in the shared MRI prompt, written
                for this project. `gen_turbo_mri_modules.py` pulls them out verbatim.
    here        the PATHOLOGY half. The MRI prompt has no per-region pathology rules
                at all - its PATHOLOGICAL FINDINGS RULES block is generic
                appearance-then-conclusion guidance, which already lives in the
                shared template slot. So every line below is new.

THE REGISTER, same as CT: preserve what he dictated, never instruct the model to
produce a measurement or assign a category. Enforced by
`test_pathology_rules_preserve_rather_than_produce`.

THE MRI-SPECIFIC ADDITION: signal has no meaning without the sequence that shows it.
"T2-hyperintense" is a finding; "hyperintense" is not. Each region's rules name the
sequences its findings are pinned to, and ask that the physician's sequence attribution
survive.

WHERE PUBLISHED DEFINITIONS DISAGREE OR A VERSION MATTERS, NO VALUE IS ENCODED:
    Pfirrmann        TWO different systems share the name - disc degeneration 1-5 and
                     nerve-root compromise. "Pfirrmann grade 3" is ambiguous.
    Fardon v2.0      focal <25% vs broad-based 25-50% vs bulge >50% unresolved between
                     secondary sources; primary text unreachable
    Outerbridge      grade 2/3 split at 1/2 inch (original) vs 1.5 cm (restatement)
    ARCO             1993 vs 2019 revision are different systems
    PI-RADS          v2 vs v2.1 differ in the TZ upgrade rule
    NI-RADS          the sourced values are the CT/PET version; an MRI v2025 exists
    Fazekas          single 0-3 impression vs the original separate PVH and DWMH scores

SOURCES: RSNA RadReport via api3.rsna.org (MR Brain 45, MR Right Knee 303, MR Hip 55,
MR Ankle 41, MR Wrist 73, MR Lumbar Spine 50592, MR Thoracic Spine 50594, MR Orbits 65,
MR IAC Screening 50655, mpMRI prostate 50205); ACR BI-RADS 5th ed. atlas; PI-RADS v2.1
(Dartmouth mirror of the ACR PDF); Bosniak v2019 and LI-RADS v2018 via Radiology
Assistant; O-RADS MRI v1 (Radiology 10.1148/radiol.204371); #Enzian 2021; Lumbar Disc
Nomenclature v2.0; Schizas (PLoS One), Lee (AJR 10.2214/AJR.09.2772); Meyerding
(StatPearls NBK430767); Goutallier, Patte, Ellman, ISAKOS, Snyder SLAP
(musculoskeletalkey, PMC10899560, StatPearls NBK538284); Tonnis; ARCO 2019
(PMC8216992); Palmer TFCC (PMC7384326); Hepple/Berndt-Harty/Anderson (jassm.org,
jbsr.be); Fazekas/MTA/GCA/Koedam (Radiology Assistant); ASPECTS (Frontiers in
Neurology); RANO 2.0; NI-RADS (AJNR 38:1193); Koos (otoscape).

NOT COVERED, and not invented: cardiac MRI (6 service codes at this centre), chest MRI
(3 codes), fetal MRI (1 code). The shared MRI prompt has no block for any of them.
"""
from __future__ import annotations

from typing import Dict, List

MRI_PATHOLOGY: Dict[str, List[str]] = {}
MRI_NOTES: Dict[str, List[str]] = {}

_SPINE = [
    "Disc herniation - preserve the level, the contour term he used (bulge, protrusion, "
    "extrusion, sequestration, migration), the axial zone (central, subarticular, "
    "foraminal, extraforaminal), containment, and the nerve root or thecal sac he said "
    "was contacted, displaced or compressed. Do not substitute one contour term for "
    "another: protrusion and extrusion are different findings.",
    "Preserve the degree of canal or foraminal compromise exactly as he graded it, "
    "whether in thirds, in millimetres, or as mild / moderate / severe. Published "
    "circumference thresholds for focal, broad-based and bulge disagree between "
    "sources, so never restate his term in a different scale.",
    "Pfirrmann - preserve the grade and, critically, which Pfirrmann he means. Two "
    "different systems carry the name: disc degeneration 1 to 5, and nerve root "
    "compromise. If he did not say which, carry the grade without interpreting it.",
    "Modic - preserve the type he gave (1, 2, 3, or mixed) and the level. Modic is "
    "defined on T1 and T2 together, so preserve both signal statements if he gave them.",
    "Preserve any Schizas (A1-A4, B, C, D), Lee canal or foraminal grade (0-3), or "
    "Meyerding slip grade (I-V) he stated, with the level it applies to.",
    "Spondylolisthesis - preserve the level, the direction, the grade, and the Wiltse "
    "type if he named one.",
    "Cord signal - preserve the sequence he saw it on (T2, STIR, T1 post-contrast) and "
    "the segment. Myelomalacia, oedema and cord expansion are separate findings; keep "
    "the one he described.",
    "Preserve the numbering statement verbatim if he made one - which disc space he is "
    "calling L5-S1, or how he handled a transitional segment. Renumbering his levels "
    "changes every finding in the report.",
    "Preserve marrow signal changes with their sequences (T1, STIR or T2 fat-saturated) "
    "and, where he gave one, the vertebral level and the pattern.",
]
MRI_PATHOLOGY["spine"] = list(_SPINE)
MRI_PATHOLOGY["spine_cervical"] = list(_SPINE)
MRI_PATHOLOGY["spine_thoracic"] = list(_SPINE)
MRI_PATHOLOGY["spine_lumbar"] = list(_SPINE)

MRI_NOTES["spine"] = ["State the levels examined. A spine report that does not say "
                      "which levels were covered cannot be acted on."]

MRI_PATHOLOGY["brain"] = [
    "Preserve the sequence every signal abnormality was described on - T1, T2, FLAIR, "
    "DWI with ADC, SWI or GRE, post-contrast T1. A signal statement without its "
    "sequence is not a finding.",
    "Restricted diffusion - preserve it exactly as he paired it: high signal on DWI "
    "with corresponding low ADC. Never call something restricted diffusion on DWI "
    "signal alone, and never add an ADC statement he did not make.",
    "Preserve any Fazekas score he gave, and whether he scored it as one overall value "
    "or as separate periventricular and deep white matter scores. The original scale "
    "and the common single-value form are both in use.",
    "Preserve any MTA or Scheltens medial temporal atrophy score, GCA global cortical "
    "atrophy score, or Koedam posterior atrophy score, with the plane he rated it in.",
    "Infarction - preserve the territory and side he named, the age he assigned "
    "(acute, subacute, chronic), and any ASPECTS value. ASPECTS applies to the anterior "
    "circulation; do not extend it to a posterior circulation infarct he described.",
    "Mass lesion - preserve the location, the size, the signal on each sequence he "
    "named, the enhancement pattern, and any mass effect, midline shift or herniation "
    "he described. Preserve a RANO category only if he stated one.",
    "Haemorrhage and microbleeds - preserve the sequence (usually SWI or GRE), the "
    "distribution he described, and the stage if he assigned one.",
    "Enhancement - describe it only when contrast was given. Preserve the pattern he "
    "named (ring, nodular, leptomeningeal, dural, patchy) rather than generalising it.",
]

MRI_PATHOLOGY["knee"] = [
    "Meniscal tear - preserve which meniscus, the horn or segment (anterior horn, body, "
    "posterior horn, root), the tear pattern he named (horizontal, vertical or "
    "longitudinal, radial, oblique or flap, complex, bucket-handle), which articular "
    "surface he said it reaches, and any displaced fragment and its location.",
    "Preserve a meniscal signal grade (1, 2 or 3) as he stated it. Grades 1 and 2 are "
    "intrasubstance degeneration and are not tears; never promote a grade 1 or 2 to a "
    "tear in the wording.",
    "Cartilage - preserve the grade and the system he named. Outerbridge and ICRS are "
    "different scales, and the published size thresholds for Outerbridge grades 2 and 3 "
    "differ between sources, so carry his grade rather than converting it.",
    "Cruciate and collateral ligaments - preserve which ligament, whether he called the "
    "tear partial or complete, and the sequence the abnormal signal was seen on.",
    "Bone marrow oedema - preserve the compartment and the sequence (STIR or "
    "fat-saturated T2). Preserve any subchondral fracture, insufficiency fracture or "
    "osteochondral lesion he described as a separate finding.",
    "Preserve effusion, Baker cyst and any bursitis he described, with the size term he "
    "used.",
]

MRI_PATHOLOGY["shoulder"] = [
    "Rotator cuff tear - preserve which tendon, whether he called it partial- or "
    "full-thickness, and for a partial tear the surface he named (articular, bursal, "
    "interstitial). Preserve the size or footprint measurement he gave.",
    "Preserve any Goutallier fatty infiltration grade (0-4), Patte retraction stage "
    "(1-3), Ellman partial-thickness grade, or ISAKOS axis value he stated, with the "
    "muscle or tendon it applies to.",
    "Labral tear - preserve the location by clock position or named region, and any "
    "Snyder SLAP type he assigned. Bankart, reverse Bankart and SLAP are different "
    "lesions; keep the one he named.",
    "Preserve biceps long head findings separately - tendinosis, partial tear, complete "
    "tear, subluxation or dislocation from the bicipital groove.",
    "Preserve the sequence for every signal abnormality, and note that fatty "
    "infiltration is assessed on parasagittal T1.",
    "Preserve joint effusion, subacromial-subdeltoid bursitis and any paralabral or "
    "spinoglenoid notch cyst as he described them.",
]

MRI_PATHOLOGY["hip"] = [
    "Avascular necrosis - preserve the side, the low-signal band he described and the "
    "sequence it was seen on, any subchondral fracture or articular collapse, and the "
    "staging system with its version. ARCO 1993 and the 2019 revision are different "
    "systems, so preserve the version he named rather than assuming one.",
    "Labral tear - preserve the location by clock position, whether he called it a "
    "substance tear or a detachment at the osseolabral junction, and any Czerny or Lage "
    "category he assigned.",
    "Femoroacetabular impingement - preserve the morphology he named (cam, pincer or "
    "mixed) and any alpha angle, centre-edge angle or head-neck offset he measured, "
    "with the method. Published thresholds for these angles differ, so carry his number.",
    "Preserve any Tonnis osteoarthritis grade he stated, and keep it separate from the "
    "cartilage description.",
    "Preserve marrow oedema, stress or insufficiency fracture, transient osteoporosis "
    "and joint effusion as distinct findings, each with the sequence he used.",
    "Preserve tendon and muscle findings by name - iliopsoas, abductors, hamstring "
    "origin - along with any bursitis and the side.",
]

MRI_PATHOLOGY["ankle_foot"] = [
    "Osteochondral lesion of the talus - preserve the location on the dome, the "
    "staging system he named and its value. Hepple, Berndt-Harty, Anderson and Ferkel "
    "are different systems with different criteria; never convert between them.",
    "Preserve whether he described marrow oedema around the lesion or its absence - "
    "that distinction is what separates stages in more than one of these systems.",
    "Tendon findings - preserve the tendon by name (Achilles, posterior tibial, "
    "peroneus longus or brevis, flexor hallucis longus, tibialis anterior), and whether "
    "he called it tendinosis, a partial tear, a complete tear, subluxation or "
    "dislocation.",
    "Ligament findings - preserve which ligament (ATFL, CFL, PTFL, deltoid complex, "
    "spring ligament, syndesmotic AITFL or PITFL) and the grade or completeness he gave.",
    "Preserve plantar fascia thickness and signal, sinus tarsi contents, and tarsal "
    "tunnel findings as he described them, each with its sequence.",
    "Preserve stress and insufficiency fractures with the bone, and keep marrow oedema "
    "without a fracture line as a separate finding from one with.",
]

MRI_PATHOLOGY["wrist_hand"] = [
    "TFCC - preserve the Palmer class and subtype he gave (1A to 1D traumatic, 2A to 2E "
    "degenerative) and the part of the complex he named. A central perforation and a "
    "peripheral foveal avulsion are different injuries.",
    "Intrinsic ligaments - preserve which ligament (scapholunate, lunotriquetral), "
    "whether he called the tear partial or complete, and which portion (volar, dorsal, "
    "membranous).",
    "Carpal alignment - preserve any DISI or VISI he named, the ulnar variance with its "
    "sign, and any distal radioulnar joint incongruence.",
    "Avascular necrosis - preserve the bone (scaphoid proximal pole, lunate) and the "
    "signal change on each sequence he named. Preserve a staging value only if he gave "
    "one.",
    "Preserve tendon findings by compartment and by name, with the severity term he "
    "used, and preserve median nerve signal and calibre separately from the carpal "
    "tunnel description.",
    "Preserve marrow oedema, occult fracture and any ganglion with its location.",
]

MRI_PATHOLOGY["extremity"] = [
    "Preserve the joint or segment he examined and report within it - an extremity "
    "study is only as specific as the anatomy he named.",
    "Soft tissue lesion - preserve the compartment, the size, the signal on every "
    "sequence he named, the enhancement pattern, and any relationship to neurovascular "
    "structures he described.",
    "Preserve marrow signal abnormality with its sequence and its distribution, and "
    "keep oedema, infiltration and fracture as separate findings.",
    "Muscle - preserve the muscle by name and whether he described oedema, atrophy, "
    "fatty replacement or a tear, with the grade if he gave one.",
    "Preserve any fracture with the bone, the part, and whether he called it acute, "
    "stress, insufficiency or healed.",
]

MRI_PATHOLOGY["breast"] = [
    "Preserve the BI-RADS assessment category exactly as he gave it, including a 4A, 4B "
    "or 4C subdivision. Never assign a category he did not state and never collapse a "
    "subdivision.",
    "Preserve the fibroglandular tissue category (a to d) and the background parenchymal "
    "enhancement level (minimal, mild, moderate, marked) with its symmetry, as separate "
    "statements.",
    "A mass - preserve shape, margin and internal enhancement as he described them. "
    "Non-mass enhancement - preserve distribution and internal pattern. These are two "
    "different lexicons; do not describe a mass with NME terms or the reverse.",
    "Preserve the kinetic curve as he stated it: the initial phase (slow, medium, fast) "
    "and the delayed phase (persistent, plateau, washout).",
    "Preserve the location of every finding as he gave it - side, clock position or "
    "quadrant, depth, and distance from the nipple.",
    "Preserve associated features by name - nipple or skin retraction, skin thickening, "
    "axillary adenopathy, architectural distortion, pectoralis or chest wall invasion.",
    "Diffusion is not part of the BI-RADS MRI lexicon. Preserve any ADC value he "
    "dictated, but never derive a category from it.",
]

MRI_PATHOLOGY["prostate"] = [
    "Preserve the PI-RADS category and the version he scored under. v2 and v2.1 differ "
    "in the transition-zone rules, so a category without its version cannot be "
    "re-derived.",
    "Preserve the component scores separately as he gave them: T2W, DWI with ADC, and "
    "whether DCE was positive or negative. Never compute an overall category from "
    "components he did not score.",
    "Preserve each lesion's sector-map location, its zone (peripheral, transition, "
    "central, anterior fibromuscular stroma), and its size in mm.",
    "Preserve extraprostatic extension, seminal vesicle invasion and neurovascular "
    "bundle involvement exactly as he characterised them, including any hedge.",
    "Preserve prostate volume and any PSA density he stated, with their units.",
    "Preserve nodal and osseous findings separately from the prostate assessment.",
]

MRI_PATHOLOGY["abdomen"] = [
    "Liver observation - preserve the segment, the size, and each major feature he "
    "described: arterial phase hyperenhancement, washout, enhancing capsule, threshold "
    "growth. Preserve a LI-RADS category only when he assigned one, and preserve it "
    "verbatim including LR-M and LR-TIV.",
    "Preserve the phase every enhancement statement belongs to - arterial, portal "
    "venous, delayed, or hepatobiliary. An enhancement claim without its phase is not a "
    "finding.",
    "Renal cyst or mass - preserve the Bosniak class he assigned and the features he "
    "based it on: septa and their number and thickness, wall thickness, enhancing "
    "nodule. Bosniak has a distinct 2019 MRI formulation, so preserve his version.",
    "Preserve in-phase and opposed-phase signal drop as he described it, and any "
    "quantitative fat fraction or iron measurement with its units. Never convert a "
    "qualitative statement into a grade.",
    "Biliary - preserve duct calibre with the duct he measured, and, where dilated, the "
    "level and cause of obstruction he named.",
    "Preserve diffusion restriction as the DWI and ADC pair he described, and any focal "
    "lesion's signal on T1, T2 and fat-suppressed sequences.",
    "Preserve bowel findings by segment with wall thickness, enhancement and any "
    "stricture, fistula or abscess he described.",
]

MRI_PATHOLOGY["pelvis"] = [
    "Adnexal lesion - preserve the side, the size, whether he called it unilocular, "
    "multilocular or solid, the presence of enhancing solid tissue, and the O-RADS MRI "
    "score if he gave one. Preserve the time-intensity curve type or his comparison to "
    "myometrial enhancement as he stated it.",
    "Endometriosis - preserve the compartments he named and any Enzian value. The 2021 "
    "#Enzian revision adds compartments the original does not have, so preserve which "
    "he used rather than normalising.",
    "Preserve T2 shading and T1 fat-saturated hyperintensity as the paired finding he "
    "described - together they are what characterise an endometrioma.",
    "Leiomyoma - preserve the FIGO subclassification number when he gives one, the "
    "location, the size, and any degeneration he described.",
    "Preserve a FIGO stage only when he stated it, with the malignancy it applies to. "
    "Never derive a stage from the findings.",
    "Rectal or pelvic malignancy - preserve the T and N categories, the mesorectal "
    "fascia or circumferential margin distance, and extramural vascular invasion "
    "exactly as he characterised them.",
    "Preserve pelvic sidewall, ureteric and nodal findings separately from the primary "
    "lesion.",
]

MRI_PATHOLOGY["head_neck"] = [
    "Preserve the anatomic space or nodal level he named. A neck finding without its "
    "space or level is not actionable.",
    "Preserve perineural spread exactly as he described it - the nerve, the foramen, "
    "and the fat-plane effacement or enhancement he based it on. This is the finding "
    "most often lost in rewriting and it changes management.",
    "Preserve any NI-RADS category, and preserve the primary site and the neck nodes as "
    "separate categories. The published categories differ between the CT/PET version "
    "and the MRI algorithm, so carry the version he used.",
    "Preserve the signal on each sequence he named, the enhancement pattern, and any "
    "diffusion restriction as a DWI and ADC pair.",
    "Preserve bone marrow replacement and skull base involvement as distinct findings, "
    "with the structure named.",
    "Preserve nodal findings with side, level, short-axis size, necrosis and any "
    "extranodal extension he described.",
]

MRI_PATHOLOGY["orbit"] = [
    "Preserve the side and the compartment he named - intraconal, extraconal, "
    "preseptal, orbital apex, lacrimal fossa. An orbital finding without its "
    "compartment cannot be planned around.",
    "Preserve optic nerve and sheath findings separately from each other, with the "
    "sequence, and preserve any enhancement he described only when contrast was given.",
    "Extraocular muscle - preserve which muscles, whether he described tendon "
    "involvement or sparing, and any measurement he gave. Published normal thicknesses "
    "differ between series, so carry his number rather than a verdict.",
    "Preserve globe findings by name - contour, lens position, retinal or choroidal "
    "detachment, vitreous signal - and any foreign body with the composition he "
    "attributed to it.",
    "Preserve orbital apex and optic canal involvement exactly as he stated it. Apex "
    "involvement with visual loss is an emergency and must not be softened.",
    "Preserve lacrimal gland and nasolacrimal findings separately, with the side.",
]

MRI_PATHOLOGY["temporal_bone"] = [
    "Preserve the side. A temporal bone study is almost never bilateral in its "
    "indication, and a side-less finding is not actionable.",
    "Vestibular schwannoma or IAC mass - preserve the size, whether he described it as "
    "intracanalicular or extending into the cerebellopontine angle, its relation to the "
    "brainstem, and any Koos grade he assigned.",
    "Preserve which cranial nerve he named - facial (VII) or vestibulocochlear (VIII) - "
    "and the segment. These run together in the IAC and must not be merged.",
    "Preserve labyrinthine signal and enhancement as he described them, with the "
    "sequence. High-resolution heavily T2-weighted imaging and post-contrast T1 answer "
    "different questions; keep his attribution.",
    "Cholesteatoma - preserve the location, the non-echo-planar diffusion finding if he "
    "cited one, and every eroded structure he named (scutum, ossicles, lateral "
    "semicircular canal, tegmen, facial nerve canal).",
    "Preserve middle ear and mastoid opacification separately from the labyrinth, and "
    "preserve any facial nerve canal involvement by segment.",
]

MRI_NOTES["temporal_bone"] = ["Say which side, in every finding."]
MRI_NOTES["breast"] = ["Report per breast. A finding without a side is not reportable."]
MRI_NOTES["prostate"] = ["Name the PI-RADS version. A category without it cannot be "
                         "re-derived by the next reader."]
MRI_NOTES["brain"] = ["Describe enhancement only when contrast was given, even to deny "
                      "it."]


MRI_PATHOLOGY["thyroid"] = list(MRI_PATHOLOGY["head_neck"])

#: Headings for the five regions the MRI GROUPING VOCABULARY does not cover.
#: Every structure named here is taken from that region's own normal-findings block in
#: the shared MRI prompt - this is an ordering line over content a radiologist wrote,
#: not new anatomy.
MRI_HEADINGS = {
    "extremity": "Bones and marrow · Joints and cartilage · Ligaments and tendons · "
                 "Muscles · Soft tissues · Neurovascular structures",
    "head_neck": "Mucosal surfaces · Deep spaces · Salivary glands · Thyroid · "
                 "Lymph node levels · Vessels · Skull base and marrow",
    "thyroid":   "Mucosal surfaces · Deep spaces · Salivary glands · Thyroid · "
                 "Lymph node levels · Vessels · Skull base and marrow",
    "orbit":     "Globes · Optic nerves and sheaths · Extraocular muscles · Intraconal "
                 "and extraconal fat · Lacrimal apparatus · Orbital walls · Orbital apex",
    "temporal_bone": "External auditory canal · Middle ear and ossicles · Labyrinth · "
                     "Internal auditory canal and CN VII/VIII · Mastoid air cells · "
                     "Cerebellopontine angle",
}

#: Normal-findings lines added where the extracted block is too thin to be a reference.
#: ⚠️ Authored, feature-register, needs review.
MRI_NORMAL_EXTRA = {
    "pelvis": [
        "Pelvic sidewalls and obturator spaces are clear; no lymphadenopathy by "
        "short-axis size.",
        "No free pelvic fluid beyond a physiological volume.",
        "Rectum and sigmoid show normal wall thickness and signal; the mesorectal "
        "fascia is intact and not thickened.",
        "Pelvic floor and perineal soft tissues are unremarkable.",
        "Sacrum, sacroiliac joints and femoral heads show normal marrow signal.",
    ],
    "shoulder": [
        "Bony glenoid and humeral head contours are preserved; no Hill-Sachs or bony "
        "Bankart defect.",
        "Rotator cuff muscle bulk is symmetric on the parasagittal images, without "
        "fatty replacement.",
    ],
    "hip": [
        "Hip joints are congruent and concentrically located; no subluxation.",
        "Muscles and tendons about the hip are symmetric, without oedema, atrophy or "
        "fatty replacement.",
    ],
    "wrist_hand": [
        "Distal radioulnar joint is congruent and ulnar variance is neutral.",
        "Extensor and flexor tendon compartments show normal signal and no tenosynovial "
        "fluid.",
    ],
}

#: The MRI dictation lexicon. The CT always-on list is NOT reused wholesale: it carries
#: هایپردنس → hyperdense/hypodense, which is an attenuation term and wrong on MRI.
#: ⚠️ Authored, needs review - particularly the Persian spellings, which should match
#: what the transcription service actually produces rather than correct orthography.
MRI_TERMS = [
    "هایپراینتنس → hyperintense",
    "هایپواینتنس → hypointense",
    "انانسمنت → enhancement",
    "رستریکشن → restricted diffusion",
    "ادم → oedema",
    "دیسک → intervertebral disc",
    "پروتروژن → disc protrusion",
    "اکستروژن → disc extrusion",
    "استنوز → stenosis",
    "لنفادنوپاتی → lymphadenopathy",
    "ماده حاجب → contrast medium",
]
