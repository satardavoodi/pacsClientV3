# -*- coding: utf-8 -*-
"""RADIOGRAPHY (X-ray) region content.

⚠️ CLINICAL REVIEW REQUIRED. Compiled 2026-08-09. Not read by a radiologist.

WHY THIS FILE IS MOSTLY AUTHORED, WHERE CT AND MRI WERE MOSTLY EXTRACTED
The RADIOLOGY branch of the shared prompt has almost nothing to extract. Its whole
normal-findings content is four study-family blocks totalling about twenty lines:
GENERAL X-RAY (chest 5 lines, abdomen 3, extremities 3, spine 2), BONE DENSITY 3,
BONE AGE 3, BARIUM 4. There is no per-region reference the way CT has 19 RSNA blocks
and MRI has 10. So the extraction supplies the skeleton and this file supplies the body.
That also means the review burden here is larger than it was for MRI.

THE X-RAY-SPECIFIC SECTION: `projection`
CT and MRI acquire a volume; a radiograph acquires one view, and a view cannot assess
what it does not show. The shared prompt already states the rule - "A projection cannot
assess what it does not show - never add a heading for a structure the projection cannot
support" - but states it once and generically. Each region here carries the specifics:
which views were taken, what each can answer, and what must not be claimed without them.
This is the highest-value content in the X-ray library and it has no CT or MRI analogue.

THE GLOBAL CAVEAT: MAGNIFICATION
Any linear (mm) radiographic measurement is magnification-dependent unless a calibration
marker is in the field (PMID 31695262). Ratios and angles are not. Where a published
normal exists only as a linear measurement, the rule says to preserve his number and not
to derive a verdict from it.

WHERE PUBLISHED VALUES DISAGREE, NO NUMBER IS ENCODED:
    carrying angle        six different published normals, collated in PMC3355210
    Baumann angle         64-81 vs 64-82/69-81 vs 75-80 degrees
    LCEA                  <25 vs <20 degrees; borderline 20-25 vs 18-25
    prevertebral soft tissue   sources disagree and all have poor sensitivity
    small bowel calibre   >2.5 cm vs >3 cm (the familiar 3/6/9 rule uses 3)
    mediastinal width     >8 cm vs >6-8 cm
    Torg ratio            the 0.8 cut-off is unsourced and the ratio is unreliable
    Genant vs eSQ         different scales, overlapping grade numbers

SOURCES: ACR practice parameters via gravitas.acr.org (Extremity radiography DocId=12,
Spine radiography DocId=152, Scoliosis DocId=44, Chest DocId=129, DXA DocId=48);
RSNA RadReport via api3.rsna.org (knee 152, ankle 142, foot 148, wrist 157,
shoulder 154/50023, pelvis 224, lumbar spine 156, forearm 250, chest 144, 50798, 50814);
ISCD 2023 Adult and Paediatric Official Positions; ILO 2022; StatPearls (NBK482427,
NBK470593, NBK493188, NBK441919, NBK470346, NBK537347, NBK448083, NBK542228, NBK560933,
NBK448140, NBK519563, NBK430767, NBK563157, NBK537051, NBK448079); PMC6440422 (Kellgren-
Lawrence verbatim), PMC9983115 (hip angles), PMC3355210 (elbow normals), PMC11493813 and
PMC7186643 (Genant SQ), PMC8292005 and PMC5404618 (bowel calibre), AJNR 28:1819 (CCJ
measurements, radiograph vs CT).

NOT COVERED: interventional and vascular fluoroscopy - 35 of this centre's 93
fluoroscopy codes. Angiography is a different report shape and nothing was invented for
it. Bone age and barium/contrast studies are carried as SUBTYPES, not regions: a barium
swallow is a study type performed on the neck and chest, and a bone age is a study type
performed on the left hand.
"""
from __future__ import annotations

from typing import Dict, List

XR_PROJECTION: Dict[str, List[str]] = {}
XR_PATHOLOGY: Dict[str, List[str]] = {}
XR_NORMAL: Dict[str, List[str]] = {}
XR_NOTES: Dict[str, List[str]] = {}
XR_HEADINGS: Dict[str, str] = {}


XR_HEADINGS.update({
    "chest": "Lungs · Pleura · Heart and mediastinum · Diaphragm · Bones · Soft tissues · Lines and tubes",
    "abdomen": "Bowel gas pattern · Free intraperitoneal air · Organ outlines · Calcifications · Bones",
    "knee": "Bones · Joint spaces and alignment · Patellofemoral joint · Soft tissues",
    "shoulder": "Bones · Glenohumeral joint · Acromioclavicular joint · Soft tissues",
    "hip": "Bones · Hip joints and alignment · Pelvic ring · Soft tissues",
    "pelvis": "Pelvic ring · Acetabula and hip joints · Sacrum and sacroiliac joints · Soft tissues",
    "elbow": "Bones · Joint and alignment · Fat pads · Soft tissues",
    "wrist_hand": "Bones · Carpal alignment and intervals · Joint spaces · Soft tissues",
    "ankle_foot": "Bones · Ankle mortise and hindfoot alignment · Joint spaces · Soft tissues",
    "extremity": "Bones · Joint and alignment · Soft tissues · Hardware",
    "spine": "Alignment · Vertebral bodies · Disc spaces · Posterior elements · Soft tissues",
    "spine_cervical": "Alignment · Vertebral bodies · Disc spaces · Posterior elements · Prevertebral soft tissues · Craniocervical junction",
    "spine_thoracic": "Alignment · Vertebral bodies · Disc spaces · Posterior elements · Paraspinal soft tissues",
    "spine_lumbar": "Alignment · Vertebral bodies · Disc spaces · Posterior elements · Sacrum and sacroiliac joints",
    "brain": "Calvarium · Sutures and vascular grooves · Skull base · Sella · Facial bones",
    "paranasal_sinuses": "Frontal sinuses · Maxillary sinuses · Ethmoid and sphenoid · Nasal septum and turbinates · Orbital rims",
    "dental_maxillofacial": "Dentition · Mandible · Maxilla and alveolar ridges · Temporomandibular joints · Maxillary sinuses · Facial buttresses",
    "head_neck": "Airway and soft tissues · Cervical spine alignment · Bony structures · Calcifications",
    "bone_density": "Lumbar spine · Total hip and femoral neck · Forearm when indicated · Vertebral fracture assessment",
})

XR_PROJECTION["chest"] = [
    "PA erect at full inspiration is the standard. Say so, and say when the study was "
    "AP, supine or portable instead - heart size cannot be assessed on an AP or supine "
    "film, and a pneumothorax and an effusion both change appearance.",
    "Lateral adds the retrocardiac and retrosternal spaces and the posterior "
    "costophrenic recesses. Without it, do not claim a clear retrocardiac lung.",
    "A lateral decubitus distinguishes free from loculated pleural fluid. Do not call "
    "an effusion free-flowing from a frontal film alone.",
    "Expiratory films are for small pneumothorax and air trapping. Judge inspiration "
    "before calling lung volumes low.",
]
XR_PATHOLOGY["chest"] = [
    "Preserve the projection he named with every finding that depends on it, "
    "particularly heart size, mediastinal width and pneumothorax.",
    "Cardiomegaly - preserve his cardiothoracic ratio or his qualitative call. The "
    "ratio is defined on a PA film, so never carry it forward from an AP or supine "
    "study he described as such.",
    "Mediastinal widening - preserve his measurement. Published thresholds run from "
    "6 to 8 cm depending on source, so carry his number rather than a verdict.",
    "Preserve the lobe or zone he localised a consolidation, nodule or opacity to, and "
    "the silhouette sign if he used it.",
    "Pleural findings - preserve laterality, whether he called the fluid free or "
    "loculated, and any pneumothorax with its size estimate and the view it was seen on.",
    "Lines and tubes - preserve the device he named and the tip position he described, "
    "exactly. This is the finding most often acted on within minutes.",
    "Preserve any ILO pneumoconiosis classification he gave, with its profusion "
    "category and shape and size codes.",
]

XR_PROJECTION["abdomen"] = [
    "Supine KUB is the baseline. Free intraperitoneal air needs an erect chest or a "
    "left lateral decubitus - never exclude free air from a supine film alone.",
    "An erect abdomen shows air-fluid levels. Their absence on a supine-only study "
    "means nothing.",
    "Say which views were performed. Obstruction, perforation and ileus are each "
    "distinguished by findings that only some projections can show.",
]
XR_PATHOLOGY["abdomen"] = [
    "Bowel dilatation - preserve the segment he named and the calibre he measured. "
    "Published thresholds differ (small bowel >2.5 cm or >3 cm; the familiar rule uses "
    "3 cm for small bowel, 6 cm for colon, 9 cm for caecum), so carry his figure.",
    "Obstruction - preserve his description of proximal dilatation with distal "
    "decompression, and any transition point he identified. Do not upgrade dilated "
    "loops to obstruction he did not call.",
    "Free air - preserve the view it was seen on. This is the finding where projection "
    "and conclusion are inseparable.",
    "Preserve calcifications by location and by what he attributed them to, and "
    "preserve any calculus with its side and position along the urinary tract.",
    "Preserve organ outlines and any mass effect or displaced gas pattern he described.",
    "Preserve foreign bodies and surgical hardware with their position, and any device "
    "tip he localised.",
]


XR_PROJECTION["knee"] = [
    "AP and lateral are the minimum. The patellofemoral joint is not assessable on "
    "them - a congruence angle or a lateral patellofemoral angle needs a skyline, "
    "Merchant or sunrise view.",
    "Joint-space narrowing is underestimated on a non-weight-bearing AP. A flexion "
    "weight-bearing (Rosenberg) or tunnel view detects more, so do not grade "
    "tibiofemoral osteoarthritis confidently from a supine AP.",
    "A cross-table lateral is what shows lipohaemarthrosis in trauma.",
    "A negative radiograph does not exclude a Segond fracture: only 82% were visible "
    "on plain films in one ACL cohort.",
]
XR_PATHOLOGY["knee"] = [
    "Preserve any Kellgren-Lawrence grade (0 to 4) with the compartment and the view "
    "it was graded on.",
    "Tibial plateau fracture - preserve the Schatzker type he assigned and note it is "
    "provisional on radiographs; preserve the depression and widening in mm as he "
    "measured them.",
    "Patellar height - preserve the ratio he used by name (Insall-Salvati, "
    "Blackburne-Peel, Caton-Deschamps) with its value. They have different normal "
    "bands, so a bare number without the method cannot be read.",
    "Preserve effusion and lipohaemarthrosis as separate findings. Lipohaemarthrosis "
    "implies an intra-articular fracture and must never be dropped.",
    "Preserve any Salter-Harris grade he gave, with the physis.",
]

XR_PROJECTION["shoulder"] = [
    "AP alone cannot tell an anterior from a posterior dislocation. An axillary or "
    "scapular-Y view is what establishes direction - Rockwood types IV and VI in "
    "particular are not determinable from AP.",
    "Say which views were performed before describing the direction of any "
    "displacement.",
]
XR_PATHOLOGY["shoulder"] = [
    "Proximal humeral fracture - preserve the parts he named and any Neer count. The "
    "displacement criterion is more than 1 cm or more than 45 degrees; it is his to "
    "apply, never yours.",
    "Acromioclavicular injury - preserve the Rockwood type. Its thresholds are a "
    "percentage change against the contralateral side, not an absolute measurement, so "
    "preserve the comparison he made.",
    "Dislocation - preserve the direction and the view that showed it, plus any "
    "Hill-Sachs or bony Bankart lesion he described.",
    "Preserve any AO/OTA code exactly as he gave it, with its version if he named one.",
]

XR_PROJECTION["hip"] = [
    "An AP pelvis is what the coverage and version angles are defined on; a single "
    "hip AP does not allow comparison with the other side.",
    "A lateral or cross-table view is needed for femoral neck displacement and for "
    "posterior wall assessment.",
    "Say whether the film was weight-bearing. Joint-space assessment depends on it.",
]
XR_PATHOLOGY["hip"] = [
    "Femoral neck fracture - preserve the Garden grade (I to IV) and any Pauwels type, "
    "with the displacement he described.",
    "Preserve any Tonnis osteoarthritis grade or Kellgren-Lawrence grade he assigned, "
    "and keep the system he named.",
    "Coverage angles - preserve the lateral centre-edge, Tonnis or Sharp angle he "
    "measured. Published normals disagree (LCEA normal is given as above 25 and as "
    "above 20 degrees, borderline as 20-25 or 18-25), so carry his number.",
    "Preserve Shenton's line as he described it - unbroken, or broken and on which "
    "side.",
    "Paediatric hip - preserve the acetabular index with the child's age, and preserve "
    "his statements about the Hilgenreiner and Perkin lines and the ossific nucleus.",
    "Never assign a Gustilo-Anderson grade from a radiograph. It classifies the wound "
    "at examination, not the film.",
]
XR_PATHOLOGY["pelvis"] = list(XR_PATHOLOGY["hip"])
XR_PROJECTION["pelvis"] = list(XR_PROJECTION["hip"])

XR_PROJECTION["elbow"] = [
    "A true lateral in 90 degrees of flexion is what the fat pads and the anterior "
    "humeral line depend on. An oblique or rotated lateral makes both unreadable.",
    "The AP carries the Baumann and carrying angles; the lateral carries the anterior "
    "humeral and radiocapitellar lines. Do not report a line from the view that cannot "
    "show it.",
]
XR_PATHOLOGY["elbow"] = [
    "A posterior fat pad is never normal. Preserve it exactly as he described it - in "
    "an adult it implies a radial head fracture, in a child a supracondylar fracture, "
    "and it is often the only sign on the film.",
    "Preserve his statement about the anterior humeral line and the radiocapitellar "
    "line - whether each bisects the capitellum, and which third.",
    "Radial head fracture - preserve any Mason type, and note whether he used the "
    "Hotchkiss modification, whose types 2 and 3 embed a functional judgement rather "
    "than a radiographic one.",
    "Supracondylar fracture - preserve the modified Gartland type. Type IV is defined "
    "by instability under fluoroscopy and cannot be assigned from a static film.",
    "Angles - preserve the Baumann or carrying angle he measured. Published normals "
    "differ widely between series, so carry his value and not a verdict.",
    "Preserve any Salter-Harris grade with the physis he named.",
]


XR_PROJECTION["wrist_hand"] = [
    "PA and lateral are the minimum; carpal intervals are measured on the PA and "
    "carpal alignment on a true lateral. A scaphoid view is a separate request.",
    "A normal radiograph does not exclude a scaphoid fracture. Say what was performed "
    "rather than implying the question is closed.",
]
XR_PATHOLOGY["wrist_hand"] = [
    "Distal radius fracture - preserve the figures he measured: radial inclination and "
    "volar or dorsal tilt in degrees, radial height and ulnar variance in mm, and any "
    "articular step-off or gap. Linear measurements are magnification-dependent on a "
    "radiograph unless a marker was in the field, so carry his number as his.",
    "Carpal alignment - preserve the scapholunate interval he measured and any DISI or "
    "VISI he named.",
    "Scaphoid - preserve the pole he named, the displacement, and whether he called "
    "the study normal or the fracture not excluded.",
    "Preserve any Salter-Harris grade with the physis, and the fracture acuity he "
    "stated.",
    "Preserve comminution, angulation, rotation, intra-articular extension and "
    "dislocation exactly as he described them.",
]

XR_PROJECTION["ankle_foot"] = [
    "The mortise view is what shows the medial clear space and talar tilt; an AP alone "
    "does not. Say which of AP, mortise and lateral were taken.",
    "Weight-bearing changes syndesmotic and Lisfranc assessment. A supine film can miss "
    "an unstable injury that a standing film shows.",
    "Calcaneal angles are measured on the lateral; Sanders typing needs CT and cannot "
    "be assigned from a radiograph.",
]
XR_PATHOLOGY["ankle_foot"] = [
    "Malleolar fracture - preserve the Weber level (A, B, C) or the Lauge-Hansen stage "
    "he named, and whether he called the syndesmosis or the mortise disrupted.",
    "Preserve any Bohler or Gissane angle he measured as his number. Both have more "
    "than one published normal range.",
    "Midfoot - preserve the Lisfranc alignment he described and any diastasis he "
    "measured, with whether the film was weight-bearing.",
    "Preserve any Salter-Harris grade with the physis he named.",
    "Preserve talar dome lesions as he described them, and do not assign an MRI or CT "
    "staging system from a radiograph.",
]

XR_PROJECTION["extremity"] = [
    "Two orthogonal views are the minimum for any fracture assessment. A single view "
    "cannot establish displacement, angulation or rotation.",
    "Say which views were performed, and include the joint above and below when he "
    "described them.",
]
XR_PATHOLOGY["extremity"] = [
    "Fracture - preserve the bone and part he named, the orientation, comminution, "
    "displacement, angulation, rotation, intra-articular extension, and whether he "
    "called it open.",
    "Preserve the fracture acuity he stated and any healing, callus or non-union.",
    "Preserve any Salter-Harris grade, and any AO/OTA code with its version.",
    "Preserve dislocation and its direction, and the view that showed it.",
    "Hardware - preserve the device and the specific complication he named.",
    "Linear measurements on a radiograph are magnification-dependent unless a "
    "calibration marker was in the field. Preserve his figure; do not convert it.",
]

_SPINE_PROJ = [
    "State the levels the film actually covered. A cervical study must show the "
    "craniocervical junction to at least the superior endplate of T1; if it did not, "
    "say so.",
    "Flexion and extension views are what establish instability, and side-bending "
    "films are what distinguish a structural from a non-structural curve. Neither can "
    "be inferred from a neutral film.",
    "A curve is called major from an upright radiograph. Do not call one major from a "
    "supine study.",
]
_SPINE_PATH = [
    "Vertebral fracture - preserve the level and any Genant semiquantitative grade "
    "(0, 0.5, 1, 2, 3) he assigned. The extended eSQ scale uses overlapping numbers "
    "with different meanings, so preserve which scale he used.",
    "Preserve the percentage height loss he measured and the endplate he attributed it "
    "to, and never convert his percentage into a different grade.",
    "Spondylolisthesis - preserve the level, the direction, the Meyerding grade (I to "
    "V) and any Wiltse type he named.",
    "Scoliosis - preserve the Cobb angle with the end vertebrae he used and whether "
    "the film was upright or supine. Preserve any Lenke or King classification he gave.",
    "Preserve alignment, disc-space heights and posterior element findings by level as "
    "he described them.",
    "Do not assign SLIC or AO Spine from a plain film - they are CT and MRI driven.",
]
for _k in ("spine", "spine_cervical", "spine_thoracic", "spine_lumbar"):
    XR_PROJECTION[_k] = list(_SPINE_PROJ)
    XR_PATHOLOGY[_k] = list(_SPINE_PATH)

XR_PATHOLOGY["spine_cervical"] = _SPINE_PATH + [
    "Prevertebral soft tissue - preserve his measurement and the level. Published "
    "thresholds disagree and all have poor sensitivity, so carry his number.",
    "Craniocervical junction - preserve the atlanto-dental interval, basion-dens "
    "interval or Powers ratio he measured. Radiographic and CT normals differ for the "
    "first two (ADI 3 mm and BDI 12 mm are radiographic figures), so preserve the "
    "modality he measured on.",
]


XR_PROJECTION["brain"] = [
    "Skull radiographs answer a narrow question. They do not exclude intracranial "
    "injury, and a normal film must not be worded as though they did.",
    "Say which projections were taken. A fracture line is often visible on only one.",
]
XR_PATHOLOGY["brain"] = [
    "Fracture - preserve the bone he named, whether he called it linear, depressed or "
    "diastatic, and the projection it was seen on.",
    "Preserve his distinction between a fracture line, a vascular groove and a suture. "
    "That distinction is the whole difficulty of the study and must survive rewriting.",
    "Preserve any intracranial calcification, sellar change or radiopaque foreign body "
    "with its position.",
    "Preserve his statement that a radiograph does not exclude intracranial injury if "
    "he made one.",
]

XR_PROJECTION["paranasal_sinuses"] = [
    "Name every projection taken. Each sinus view profiles different sinuses and a "
    "finding belongs to the view that showed it: occipitomental (Water's) for the "
    "maxillary antra and the orbital floors, occipitofrontal (Caldwell) for the "
    "frontal and ethmoid sinuses, lateral for the sphenoid and the posterior wall of "
    "the frontal sinus and the nasopharyngeal airway, submentovertex for the sphenoid "
    "and the posterior ethmoids.",
    "An air-fluid level requires an ERECT film. A supine study cannot show one, and "
    "its absence on a supine film means nothing.",
    "The ethmoid and sphenoid sinuses are poorly assessed on plain films at all. "
    "Preserve any statement he made to that effect and any recommendation for CT.",
]
XR_PATHOLOGY["paranasal_sinuses"] = [
    "Preserve which sinus, which side, and whether he described mucosal thickening, an "
    "air-fluid level or complete opacification. These are different findings.",
    "Preserve the projection with any air-fluid level, and whether the film was erect.",
    "Preserve nasal septal deviation and turbinate hypertrophy as he described them.",
    "Preserve any fracture of the orbital rim, nasal bones or sinus wall with the side.",
]

XR_PROJECTION["dental_maxillofacial"] = [
    "A panoramic view surveys the dentition and mandible but distorts and superimposes; "
    "it cannot substitute for a periapical or an occlusal view for a single tooth.",
    "Facial trauma needs at least an occipitomental and a lateral. Say which were taken.",
]
XR_PATHOLOGY["dental_maxillofacial"] = [
    "Preserve tooth identity exactly as he gave it, in the notation he used. Renumbering "
    "a tooth changes which one gets treated.",
    "Preserve periapical, periodontal and caries findings by tooth, and any impaction "
    "with the angulation he described.",
    "Mandibular fracture - preserve the site he named (condyle, ramus, angle, body, "
    "parasymphysis, symphysis, coronoid, alveolus), whether unifocal or multifocal, and "
    "any tooth in the fracture line. Mandibular fractures are frequently bilateral - "
    "preserve both sides if he described both.",
    "Preserve temporomandibular joint position and any condylar dislocation.",
    "Preserve anything he said about dental occlusion, even where he called the "
    "misalignment minimal.",
]

XR_PROJECTION["head_neck"] = [
    "A lateral soft-tissue neck is taken in inspiration with the neck extended. A "
    "flexed or expiratory film exaggerates the prevertebral soft tissues and the "
    "retropharyngeal space, and must not be read as though it did not.",
]
XR_PATHOLOGY["head_neck"] = [
    "Preserve airway calibre and any narrowing he described, with the level.",
    "Preserve prevertebral and retropharyngeal soft tissue thickness as his "
    "measurement, with the level and the phase of respiration if he gave it.",
    "Preserve any radiopaque foreign body with its position and orientation, and "
    "whether he localised it to the airway or the oesophagus.",
    "Preserve calcifications and any tracheal deviation with its direction.",
]

XR_PROJECTION["bone_density"] = [
    "State the sites scanned and the regions of interest. The diagnosis is assigned "
    "from the lowest T-score across lumbar spine, total hip, femoral neck or 33% "
    "radius - not per site.",
    "State the instrument manufacturer and model. Values are not comparable across "
    "machines, and a follow-up study on a different scanner cannot be compared to the "
    "prior.",
    "State any vertebra excluded and why. A vertebra may be excluded if it is clearly "
    "abnormal, or if it differs by more than 1.0 T-score from its neighbours.",
    "For bilateral hips, diagnosis uses the lowest of the four femoral neck and total "
    "hip values, never the mean. Monitoring uses the mean bilateral total hip.",
]
XR_PATHOLOGY["bone_density"] = [
    "Preserve every BMD value in g/cm² with its site, and every T-score and Z-score "
    "with the site it belongs to.",
    "Preserve the diagnostic category he assigned and never derive one he did not "
    "state. One category is assigned per patient, from the lowest T-score.",
    "Preserve whether he reported T-scores or Z-scores. Z-scores are what apply before "
    "menopause, in men under 50, and in children - and in children a T-score must not "
    "appear at all, nor the words osteopenia or osteoporosis.",
    "Preserve any fracture-risk calculation with the tool he named and the inputs he "
    "listed.",
    "Preserve any vertebral fracture assessment finding with its level and grade, and "
    "any prior-study comparison with the least significant change he applied.",
    "Preserve his statement when a non-central device was used - the WHO classification "
    "does not apply to those T-scores, and that caveat must not be dropped.",
]

XR_NOTES.update({
    "chest": ["Name the projection. Heart size and mediastinal width mean different "
              "things on PA, AP and supine films."],
    "abdomen": ["Free intraperitoneal air cannot be excluded from a supine film."],
    "elbow": ["A posterior fat pad is never a normal finding."],
    "bone_density": ["One diagnostic category per patient, from the lowest T-score - "
                     "not one per site."],
    "spine": ["State the levels the film covered."],
    "extremity": ["Two orthogonal views are the minimum for any fracture assessment."],
})

#: Radiography dictation terms. ⚠️ Authored - check the Persian spellings against what
#: the transcription service actually produces.
XR_TERMS = [
    "رادیوگرافی → radiograph",
    "گرافی → radiograph",
    "نمای رخ → frontal (AP/PA) projection",
    "نمای نیمرخ → lateral projection",
    "ایستاده → erect",
    "خوابیده → supine",
    "شکستگی → fracture",
    "دررفتگی → dislocation",
    "استئوپروز → osteoporosis",
    "اسکولیوز → scoliosis",
    "افیوژن → effusion",
    "کنسولیداسیون → consolidation",
    "باریم → barium",
    "ماده حاجب → contrast medium",
]


#: Normal-findings references. The four extracted blocks supply 2-5 lines per family;
#: these bring each region up to a usable reference. ⚠️ Authored, feature-register.
XR_NORMAL.update({
    "chest": [
        "Both apices and costophrenic sulci are included; inspiration is adequate.",
        "Lungs are clear, without consolidation, collapse or interstitial opacity.",
        "Pulmonary vascular markings are normal in distribution and calibre.",
        "No pleural effusion, pleural thickening or pneumothorax.",
        "Cardiac silhouette is normal in size, with a cardiothoracic ratio under 50% on "
        "this PA projection.",
        "Mediastinal contours are normal and the mediastinum is not widened; the trachea "
        "is central.",
        "Both hemidiaphragms are smoothly outlined and normally positioned; no free "
        "subdiaphragmatic gas on this erect film.",
        "Bony thorax is intact; visualised ribs, clavicles and shoulder girdles show no "
        "fracture or lytic lesion.",
        "Soft tissues are unremarkable; no surgical emphysema.",
    ],
    "abdomen": [
        "Bowel gas pattern is normal, with no dilated small-bowel or colonic loops.",
        "Small-bowel calibre is within normal limits and the colon is normally "
        "distended; caecal calibre is normal.",
        "No air-fluid levels to suggest obstruction on the erect projection.",
        "No free intraperitoneal gas on the erect chest or decubitus projection.",
        "No abnormal soft-tissue mass or displaced bowel to suggest mass effect.",
        "Visualised renal, hepatic and splenic outlines are within normal limits.",
        "No abnormal calcification along the renal tracts, in the gallbladder fossa or "
        "in the pelvis.",
        "Visualised lower thoracic and lumbar vertebrae, pelvis and hips show no acute "
        "bony abnormality.",
        "Soft tissues and flank stripes are unremarkable.",
    ],
    "knee": [
        "No fracture, and no focal lytic or sclerotic lesion.",
        "Bone mineralisation is normal for age.",
        "Medial and lateral tibiofemoral joint spaces are preserved.",
        "No marginal osteophyte, subchondral sclerosis or subchondral cyst.",
        "Patella is normally positioned with a normal patellar height ratio on the "
        "lateral projection.",
        "Patellofemoral joint space is preserved on the axial projection.",
        "Alignment is anatomical; no subluxation.",
        "No joint effusion and no lipohaemarthrosis.",
        "Soft tissues are unremarkable; no radiopaque foreign body.",
    ],
    "shoulder": [
        "No fracture of the proximal humerus, clavicle or scapula.",
        "Glenohumeral joint is congruent and normally located.",
        "Acromioclavicular joint is normally aligned and the coracoclavicular "
        "relationship is symmetric with the opposite side.",
        "Subacromial space is preserved; no high-riding humeral head.",
        "No Hill-Sachs defect and no bony Bankart lesion.",
        "No calcific deposit in the rotator cuff.",
        "Bone mineralisation is normal and no focal bone lesion is seen.",
        "Visualised lung apex and ribs are unremarkable.",
        "Soft tissues are unremarkable.",
    ],
    "hip": [
        "No fracture of the femoral neck, intertrochanteric region or pelvic ring.",
        "Femoral heads are spherical and concentrically located within the acetabula.",
        "Shenton's line is unbroken bilaterally.",
        "Hip joint spaces are preserved and symmetric.",
        "No marginal osteophyte, subchondral sclerosis or subchondral cyst.",
        "Femoral head coverage is normal; no acetabular protrusion or dysplastic "
        "configuration.",
        "Sacroiliac joints and pubic symphysis are aligned and symmetric.",
        "Bone mineralisation is normal for age.",
        "Soft tissues are unremarkable.",
    ],
    "elbow": [
        "No fracture of the distal humerus, radial head, neck or olecranon.",
        "Anterior humeral line bisects the middle third of the capitellum on the "
        "lateral projection.",
        "Radiocapitellar line intersects the central capitellum in every projection.",
        "Anterior fat pad is a normal thin lucency; no posterior fat pad is visible.",
        "Elbow joint is congruent; radial head, capitellum and ulnohumeral articulation "
        "are normally aligned.",
        "Joint spaces are preserved; no marginal osteophyte or loose body.",
        "Physes, where open, are normal in width and configuration.",
        "Bone mineralisation is normal for age.",
        "Soft tissues are unremarkable.",
    ],
    "wrist_hand": [
        "No fracture of the distal radius, ulna, carpus, metacarpals or phalanges.",
        "Radial inclination, volar tilt and radial height are within normal limits and "
        "ulnar variance is neutral.",
        "Carpal arcs are smooth and uninterrupted; carpal alignment is normal on the "
        "lateral projection.",
        "Scapholunate and lunotriquetral intervals are uniform and not widened.",
        "Distal radioulnar joint is congruent.",
        "Radiocarpal and intercarpal joint spaces are preserved.",
        "No erosion, periarticular osteopenia or chondrocalcinosis.",
        "Physes, where open, are normal in width and configuration.",
        "Soft tissues are unremarkable; no radiopaque foreign body.",
    ],
    "ankle_foot": [
        "No fracture of the malleoli, talus, calcaneus, midfoot or forefoot.",
        "Ankle mortise is congruent and symmetric, with a normal medial clear space and "
        "an intact syndesmosis.",
        "Talar dome is smooth, without an osteochondral defect.",
        "Bohler's angle is within normal limits on the lateral projection.",
        "Subtalar, talonavicular and calcaneocuboid joints are congruent.",
        "Tarsometatarsal alignment is preserved, without diastasis.",
        "Joint spaces are preserved; no erosion or marginal osteophyte.",
        "Physes, where open, are normal in width and configuration.",
        "Soft tissues are unremarkable; no radiopaque foreign body.",
    ],
    "brain": [
        "Calvarium is intact, with no fracture line, depression or diastasis.",
        "Cranial sutures are normal for age and not diastatic.",
        "Vascular grooves and diploic channels follow their expected courses.",
        "Skull base and petrous temporal bones are unremarkable on the projections "
        "obtained.",
        "Sella turcica is normal in size and configuration.",
        "No abnormal intracranial calcification.",
        "No radiopaque foreign body.",
        "Visualised facial bones and paranasal sinuses are unremarkable.",
        "Soft tissues of the scalp are unremarkable.",
    ],
    "paranasal_sinuses": [
        "Frontal sinuses are aerated and symmetric.",
        "Maxillary antra are aerated, with no mucosal thickening and no air-fluid level "
        "on this erect projection.",
        "Visualised ethmoid air cells are clear.",
        "Sphenoid sinus is aerated as far as this projection allows.",
        "Nasal septum is midline and the turbinates are normal in size.",
        "Orbital rims and floors are intact.",
        "Zygomatic arches and the visualised facial buttresses are continuous.",
        "No radiopaque foreign body.",
        "Soft tissues are unremarkable.",
    ],
    "dental_maxillofacial": [
        "Dentition is complete for age, with normal crown and root morphology.",
        "No carious lesion, periapical lucency or retained root.",
        "Alveolar bone height is normal, with no periodontal bone loss.",
        "Mandible is intact throughout, including both condyles, rami, angles, body and "
        "symphysis.",
        "Maxilla and alveolar ridges are intact.",
        "Temporomandibular joints are normally located, with condyles seated in the "
        "glenoid fossae.",
        "Visualised maxillary antra are aerated.",
        "No impacted or supernumerary tooth.",
        "No radiopaque foreign body and no soft-tissue calcification.",
    ],
    "head_neck": [
        "Airway is patent and normal in calibre throughout.",
        "Prevertebral and retropharyngeal soft tissues are normal in thickness on this "
        "extended inspiratory lateral projection.",
        "Epiglottis and aryepiglottic folds are normal in contour.",
        "Trachea is central and normal in calibre.",
        "Visualised cervical vertebrae show normal alignment and preserved disc spaces.",
        "No radiopaque foreign body in the airway or the cervical oesophagus.",
        "No soft-tissue calcification and no free gas in the soft tissues.",
        "Visualised lung apices are clear.",
    ],
    "bone_density": [
        "Lumbar spine L1 to L4: bone mineral density and T-score within the expected "
        "range for the reference population.",
        "Total hip and femoral neck: bone mineral density and T-score within the "
        "expected range.",
        "Diagnostic category assigned from the lowest T-score across the sites measured.",
        "All vertebrae assessable; none excluded for structural abnormality or for a "
        "T-score differing by more than 1.0 from its neighbours.",
        "No focal skeletal abnormality within the regions of interest.",
        "Trabecular and cortical pattern are normal.",
        "Instrument manufacturer and model recorded; positioning and analysis "
        "satisfactory.",
        "No prior study available for comparison, or change within the least "
        "significant change for this instrument.",
    ],
})

_XR_SPINE_NORMAL = [
    "Vertebral alignment is normal, with preserved physiological curvature.",
    "Vertebral body heights are maintained; no compression or wedge deformity.",
    "Intervertebral disc spaces are preserved.",
    "Endplates are smooth and well corticated; no erosion or sclerosis.",
    "Pedicles, laminae, spinous and transverse processes are intact.",
    "Facet joints are normally aligned.",
    "No spondylolisthesis or pars defect.",
    "Bone mineralisation is normal for age.",
    "Paraspinal soft tissues are unremarkable.",
]
XR_NORMAL["spine"] = list(_XR_SPINE_NORMAL)
XR_NORMAL["spine_thoracic"] = _XR_SPINE_NORMAL + [
    "Thoracic kyphosis is within the normal range; no scoliotic curvature.",
    "Visualised lung fields and costophrenic angles are clear.",
]
XR_NORMAL["spine_lumbar"] = _XR_SPINE_NORMAL + [
    "Lumbosacral junction is normally formed; no transitional segment.",
    "Sacroiliac joints are symmetric and unremarkable.",
]
XR_NORMAL["spine_cervical"] = _XR_SPINE_NORMAL + [
    "The study covers the craniocervical junction to the superior endplate of T1.",
    "Prevertebral soft tissues are normal in thickness at each level.",
    "Atlanto-dental interval is within normal limits and the craniocervical junction is "
    "normally aligned.",
]
XR_NORMAL["extremity"] = [
    "No fracture, and no focal lytic or sclerotic lesion.",
    "Bone mineralisation is normal for age.",
    "Cortices are intact and periosteum is smooth, without reaction.",
    "Alignment is anatomical; no subluxation or dislocation.",
    "Joint spaces are preserved.",
    "Physes, where open, are normal in width and configuration.",
    "No joint effusion.",
    "Soft tissues are unremarkable; no swelling, calcification or radiopaque foreign "
    "body.",
]
XR_NORMAL["pelvis"] = list(XR_NORMAL["hip"])
