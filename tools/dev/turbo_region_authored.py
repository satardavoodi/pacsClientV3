# -*- coding: utf-8 -*-
"""Region content compiled from the published literature - NOT from this project.

⚠️ CLINICAL REVIEW REQUIRED. Everything in this file was compiled on 2026-08-09 from
RSNA RadReport templates, RadioGraphics, Radiopaedia, StatPearls and primary journal
sources. It has NOT been read by a radiologist. The content in the generator itself
(NOTES, PATHOLOGY) came from prompts a radiologist wrote for this project; this file
did not. The split is deliberate - provenance should be visible in the file layout.

WHY IT EXISTS. Ten of the 21 CT regions had no pathology rules at all, because the
shared prompt this project grew from never wrote any for them: the MSK group, the
paranasal sinuses, temporal bone, orbit and maxillofacial. Those studies were receiving
15 measurement bullets of which none applied.

THE ONE RULE THAT GOVERNED THE WRITING. Where published normal ranges disagree, no
number is encoded. The research surfaced several genuinely contested thresholds:

    Gissane angle          130-145 deg (StatPearls) vs 100-130 / 120-145 (LITFL)
    Insall-Salvati         patella alta at >1.3 vs >1.5
    Tibiofibular clear sp. <6 mm radiographic vs ~2.0-2.4 mm on axial CT
    Vestibular aqueduct    Valvassori >1.5 mm vs Cincinnati >=1.0 mm midpoint vs
                           0.8 mm borderline in the 45-degree oblique plane
    Extraocular muscle     Ozgen 1998 medial rectus 3.3-5.0 mm vs Zhang 2013 3.1+/-0.5
    Globe position         9.4 mm behind the interzygomatic line, plane-dependent
    Optic nerve sheath     5.28 mm at 3 mm behind the globe on CT; no agreed cut-off
    Alpha angle (hip)      50.5 / 55 / 57 degrees all published
    Lateral centre-edge    normal >25 vs >20 degrees

Encoding one side of a disagreement silently would produce confidently wrong reports.
So instead the pathology line names the measurement, asks that the physician's value and
its measurement plane or method be preserved, and states that the interpretation is his.
That is both safer and truer to how the rest of the prompt works.

SOURCES, by region group:
  MSK      RSNA RadReport RPT50819 (shoulder CT), RPT50833 (knee CT), RPT50797
           (wrist/hand CT), RPT50814 (ankle/foot); RadioGraphics 10.1148/rg.2020200008,
           rg.2021200106, rg.352140098, rg.342125215, rg.322115017; StatPearls
           NBK430861 / NBK430688 / NBK470346; LITFL Schatzker, Lauge-Hansen, Hawkins,
           Pipkin, Bohler, Gissane; OTA distal radius curriculum; Radsource DDH and
           trochlear dysplasia; Hand Surgery Resource (Herbert).
           NOTE: RadReport has NO CT template for hip, ankle or foot.
  Head/neck RSNA RadReport 181, 182, 229, 50613, 50616, 50670, 50200, 50844;
           RadioGraphics 10.1148/rg.2020190023 (temporal bone), rg.331125080 and
           PMID 16702454 (facial); Radiology 2016;281:10-21 (CLOSE checklist);
           Little & Kesser PMID 17178939; Radiopaedia Lund-Mackay, Keros, Le Fort,
           NOE, mandibular fracture; Zingg via ijashnb.org and theplasticsfella.com.

Regenerate with:  .venv\\Scripts\\python.exe tools\\dev\\gen_turbo_modules.py
"""
from __future__ import annotations

from typing import Dict, List

#: Pathological-findings rules for the regions the project had none for.
#: Preserve-register, same as the generator's own PATHOLOGY dict.
PATHOLOGY_RESEARCHED: Dict[str, List[str]] = {}

#: Normal-findings lines added to the reference a region already had.
#: Feature-register: what was assessed, not a verdict.
NORMAL_EXTRA: Dict[str, List[str]] = {}

PATHOLOGY_RESEARCHED["shoulder"] = [
    "Proximal humeral fracture - preserve the parts he named (greater tuberosity, lesser "
    "tuberosity, articular surface, shaft) and any Neer part count. The 1 cm / 45 degree "
    "displacement criterion is his to apply, never yours.",
    "Glenoid fossa fracture - preserve the Ideberg type when he gives one, the rim he "
    "named, and whether he said the fracture exits the scapula.",
    "Glenoid morphology - preserve the modified Walch type (A1, A2, B1, B2, B3, C, D) "
    "when he states it, and the version in degrees with its sign, anteversion or "
    "retroversion.",
    "Glenoid bone loss - preserve the value and the location he gave (anterior, mid, "
    "posterior). Never convert between a percentage and a millimetre figure.",
    "Instability - preserve on-track or off-track when he says it, with the Hill-Sachs "
    "interval and glenoid track values he measured.",
    "Rotator cuff - preserve the Goutallier grade (0 to 4) of fatty infiltration when he "
    "states it, and the tendon he named.",
]
NORMAL_EXTRA["shoulder"] = [
    "Glenohumeral joint is congruent and concentrically located; the glenoid articular "
    "surface is single-concave, without posterior erosion or biconcavity.",
    "Acromion is normal in shape and position, with no subacromial spur and no os "
    "acromiale.",
    "Acromioclavicular joint is normally aligned, without marginal osteophyte or "
    "capsular hypertrophy.",
    "No glenoid or humeral head bone loss; no Hill-Sachs defect and no bony Bankart "
    "lesion.",
    "Rotator cuff muscle bulk is symmetric, without fatty replacement.",
]

PATHOLOGY_RESEARCHED["hip"] = [
    "Acetabular fracture - preserve the Judet-Letournel pattern he named, elementary "
    "(anterior wall, posterior wall, anterior column, posterior column, transverse) or "
    "associated, and which wall or column he said was involved.",
    "Weight-bearing dome - preserve his statement of dome involvement together with any "
    "roof-arc or subchondral-arc measurement he made.",
    "Femoral head fracture - preserve the Pipkin type (I to IV) when he gives it, and its "
    "relation to the fovea as he described it.",
    "Version - preserve the femoral or acetabular version in degrees together with the "
    "slice level and the measurement method he named. Version changes with both, so a "
    "version figure carried without its method cannot be interpreted.",
    "Coverage angles - preserve any lateral centre-edge, Tonnis, alpha or head-neck "
    "offset value he dictated. These have more than one published normal range; carry "
    "his number, and an interpretation only if he gave one.",
    "Preserve intra-articular fragments, dislocation and its direction, comminution, and "
    "displacement in mm, as he described them.",
]
NORMAL_EXTRA["hip"] = [
    "Femoral heads are spherical and concentrically seated within the acetabula.",
    "Acetabular roof and both columns are intact; anterior and posterior walls are "
    "continuous.",
    "No fracture line, no subchondral collapse and no intra-articular fragment.",
    "Joint spaces are preserved and symmetric; no acetabular protrusion.",
    "Sacroiliac joints and pubic symphysis are aligned and symmetric.",
]

PATHOLOGY_RESEARCHED["knee"] = [
    "Tibial plateau fracture - preserve the columns he named (anteromedial, "
    "anterolateral, posterolateral, posteromedial) and any three-column count.",
    "Preserve the Schatzker type (I to VI) or the AO/OTA class when he states one.",
    "Preserve articular depression and step-off in mm, fragment displacement, "
    "angulation, and whether he called the fracture open.",
    "Preserve lipohaemarthrosis and the effusion size he described. Lipohaemarthrosis is "
    "a fracture sign and must never be dropped from the report.",
    "Patellofemoral measurements - preserve the TT-TG distance, trochlear depth, sulcus "
    "angle, patellar tilt and Insall-Salvati ratio he gave, with their units. Published "
    "normal bands differ between sources, so carry his value rather than a verdict.",
    "Trochlear dysplasia - preserve the Dejour type (A to D) when he states it.",
]
NORMAL_EXTRA["knee"] = [
    "Femorotibial and patellofemoral alignment is normal; the patella is centred within "
    "the trochlear groove.",
    "Articular surfaces of the femoral condyles, tibial plateaux and patella are smooth "
    "and congruent, without depression or step-off.",
    "No fracture line and no lipohaemarthrosis.",
    "No joint effusion and no popliteal cyst.",
    "Extensor mechanism is intact; patellar and quadriceps tendon insertions are "
    "unremarkable.",
]

PATHOLOGY_RESEARCHED["ankle_foot"] = [
    "Calcaneal fracture - preserve the Sanders type (I to IV, with the A, B, C subtypes) "
    "and the posterior facet fragment count he gave.",
    "Preserve any Bohler or Gissane angle he measured, as his number. Both angles have "
    "more than one published normal range, so never convert his figure into a verdict he "
    "did not state.",
    "Talar neck fracture - preserve the Hawkins type (I to IV) and the joints he said "
    "were dislocated.",
    "Malleolar fracture - preserve the Weber level (A, B, C) or the Lauge-Hansen stage he "
    "named, and whether he called the syndesmosis disrupted.",
    "Midfoot - preserve the Lisfranc or Myerson pattern he named, the first cuneiform to "
    "second metatarsal distance in mm, and any intercuneiform widening he measured.",
    "Physeal injury - preserve the Salter-Harris grade (I to V) when he states it.",
    "Preserve fracture orientation, comminution, intra-articular extension, fragment "
    "distraction in mm, and the dislocation he named (tibiotalar, subtalar, midtarsal, "
    "tarsometatarsal).",
]
NORMAL_EXTRA["ankle_foot"] = [
    "Ankle mortise is congruent; the talar dome is centred beneath the tibial plafond.",
    "Distal tibiofibular syndesmosis is intact.",
    "Subtalar, talonavicular and calcaneocuboid joints are congruent.",
    "Tarsometatarsal alignment is preserved, with the medial border of the second "
    "metatarsal aligned to the medial border of the intermediate cuneiform and no "
    "diastasis.",
    "No soft tissue swelling and no radiopaque foreign body.",
]

PATHOLOGY_RESEARCHED["wrist_hand"] = [
    "Scaphoid fracture - preserve the Herbert type when he gives one, the pole he named, "
    "and any displacement in mm or humpback deformity he described.",
    "Distal radius fracture - preserve the system he used by name (Frykman, Melone, "
    "Fernandez, AO) and the figures he measured: radial inclination in degrees, radial "
    "height in mm, volar or dorsal tilt in degrees, ulnar variance in mm, and articular "
    "step-off or gap in mm.",
    "Carpal alignment - preserve the scapholunate interval, scapholunate angle, "
    "capitolunate angle and radiolunate angle he gave, in the units he used.",
    "Preserve comminution, orientation, fragment rotation, intra-articular extension, "
    "articular surface involvement and fragment distraction in mm as he stated them.",
    "Preserve the fracture acuity he stated - acute, subacute, chronic or age "
    "indeterminate - and never upgrade an indeterminate one to acute.",
    "Avulsion - preserve the tendon he named and the retraction distance he measured.",
]
NORMAL_EXTRA["wrist_hand"] = [
    "Carpal alignment is normal; the radius, lunate and capitate maintain a colinear "
    "axis on the sagittal reformat.",
    "Proximal and distal carpal rows maintain normal contour, with uniform intercarpal "
    "spaces; scapholunate and lunotriquetral intervals are not widened.",
    "Distal radius and ulna are intact, with a congruent distal radioulnar joint and "
    "neutral ulnar variance.",
    "Distal radial articular surface is smooth, without step-off or gap.",
    "Metacarpals and phalanges are intact and normally aligned.",
    "No soft tissue swelling and no radiopaque foreign body.",
]

PATHOLOGY_RESEARCHED["extremity"] = [
    "Fracture - preserve the bone and the part he named, the orientation he described "
    "(transverse, oblique, longitudinal, spiral), comminution, displacement in mm, "
    "angulation in degrees, rotation, intra-articular extension, and whether he called "
    "it open.",
    "Preserve the fracture acuity he stated - acute, subacute, chronic or age "
    "indeterminate - along with any healing, callus or non-union he described.",
    "Physeal injury - preserve the Salter-Harris grade (I to V) when he gives it.",
    "Preserve dislocation and its direction, and any joint effusion or lipohaemarthrosis "
    "he described.",
    "Hardware - preserve the device he named and the specific complication he stated "
    "(loosening, periprosthetic fracture, hardware failure, malposition).",
]

PATHOLOGY_RESEARCHED["paranasal_sinuses"] = [
    "Preserve the Lund-Mackay score when he gives one, with the per-sinus grade he "
    "assigned (0 clear, 1 partial, 2 complete) and the side. The ostiomeatal complex "
    "scores 0 or 2 only, never 1.",
    "Preserve the drainage pathway state he described for each involved sinus - "
    "maxillary ostium, infundibulum, middle meatus, frontal drainage pathway, sphenoid "
    "ostium.",
    "Preserve the pattern he named: mucosal thickening, air-fluid level, complete "
    "opacification, retention cyst, polyp, or hyperdense inspissated or fungal content.",
    "Preserve the surgically relevant variants he identified by name - Keros type of the "
    "olfactory fossa, Onodi (sphenoethmoidal) cell, Haller (infraorbital) cell, concha "
    "bullosa, lamina papyracea dehiscence, a dehiscent carotid or optic canal, and a "
    "sphenoid septum inserting on the carotid canal. These change the operation and must "
    "survive intact.",
    "Preserve bone changes he described - osteitic thickening, expansion, erosion or "
    "dehiscence - and the wall he attributed them to.",
]
NORMAL_EXTRA["paranasal_sinuses"] = [
    "Cribriform plates and olfactory fossae are symmetric; the lateral lamellae are of "
    "even depth.",
    "Lamina papyracea is intact bilaterally.",
    "Carotid and optic canals are covered by bone and not dehiscent; the sphenoid septum "
    "does not insert onto the carotid canal.",
    "Anterior ethmoidal canals run within the skull base and do not traverse the ethmoid "
    "air cells.",
]

PATHOLOGY_RESEARCHED["temporal_bone"] = [
    "Fracture - preserve the axis he named (longitudinal, transverse, mixed) and, more "
    "importantly, whether he called it otic-capsule-sparing or otic-capsule-violating. "
    "That distinction carries the prognosis and must never be softened or dropped.",
    "Preserve every structure he said was involved: the ossicular chain and which joint "
    "(incudomalleolar, incudostapedial, stapediovestibular), the facial nerve canal and "
    "which segment (labyrinthine, geniculate, tympanic, mastoid), tegmen tympani or "
    "mastoideum, carotid canal, sigmoid plate or jugular bulb, and the external auditory "
    "canal.",
    "Preserve pneumolabyrinth, haemotympanum and any CSF leak he described.",
    "Cholesteatoma - preserve the location and the erosion he named (scutum, ossicles, "
    "lateral semicircular canal, tegmen, facial nerve canal).",
    "Preserve any vestibular aqueduct measurement together with the plane it was made "
    "in. Midpoint and operculum criteria differ between published series and between the "
    "axial and 45-degree oblique planes, so a figure without its plane cannot be read.",
    "Preserve the side. A temporal bone study is almost never bilateral in its "
    "indication, and a side-less finding is not actionable.",
]
NORMAL_EXTRA["temporal_bone"] = [
    "Ossicular chain is intact, with a normal incudomalleolar configuration on the axial "
    "images.",
    "Facial nerve canal is intact through its labyrinthine, tympanic and mastoid "
    "segments.",
    "Tegmen tympani and tegmen mastoideum are intact.",
    "Sigmoid plate and carotid canal are preserved.",
    "Oval and round windows are patent; the otic capsule is normally mineralised.",
]

PATHOLOGY_RESEARCHED["orbit"] = [
    "Orbital wall fracture - preserve which wall he named (floor, medial, lateral, roof), "
    "whether he called it pure or impure, and the defect size he gave.",
    "Preserve what he said about the inferior and medial rectus - herniation, and the "
    "muscle's position and shape, since rounding or kinking is the entrapment sign. In a "
    "child, preserve any statement of a trapdoor configuration.",
    "Preserve an enophthalmos or proptosis measurement together with the reference plane "
    "he used. Interzygomatic-line values shift with gantry angulation and cannot be "
    "interpreted without it.",
    "Preserve retrobulbar haematoma, orbital emphysema, globe rupture or deformity, lens "
    "dislocation, and any intraorbital or intraocular foreign body with the composition "
    "he attributed to it.",
    "Preserve anything he said about the orbital apex and the optic canal. An apex "
    "fracture with visual loss is a surgical emergency and must not be softened.",
    "Preserve the zygomaticosphenoid suture and any orbital volume change he described.",
]
NORMAL_EXTRA["orbit"] = [
    "Globes are symmetric in size and position, with intact contours and normally seated "
    "lenses.",
    "Extraocular muscles are symmetric in thickness, with normal tendinous insertions.",
    "Optic nerves are symmetric in calibre and normally coursing; retrobulbar fat is "
    "clear.",
    "Orbital floor, medial wall, lateral wall and roof are intact and continuous.",
    "Superior orbital fissures and optic canals are symmetric; no intraorbital gas, "
    "haematoma or radiopaque foreign body.",
]

PATHOLOGY_RESEARCHED["dental_maxillofacial"] = [
    "Preserve the Le Fort level he named (I, II, III). All three require pterygoid plate "
    "involvement, the levels can differ between sides, and more than one can co-exist - "
    "so preserve each side as he described it rather than collapsing them into one.",
    "Zygomaticomaxillary complex fracture - preserve the Zingg type (A1, A2, A3, B, C) "
    "when he gives it, and which of the four articulations he said were involved.",
    "Nasoorbitoethmoid fracture - preserve the Markowitz-Manson type (I, II, III) and "
    "what he said about the medial canthal tendon insertion, telecanthus and the "
    "nasolacrimal apparatus.",
    "Preserve fractures by the named buttress or subunit he used rather than as an "
    "undifferentiated list, with displacement in mm and direction, rotation, angulation "
    "and comminution as he gave them.",
    "Mandibular fracture - preserve the site he named (condyle, ramus, angle, body, "
    "parasymphysis, symphysis, coronoid, alveolus), whether he called it unifocal or "
    "multifocal, condylar dislocation, and any tooth lying in the fracture line.",
    "Preserve anything he said about dental occlusion, even where he called the "
    "misalignment minimal.",
    "Preserve involvement of the frontal sinus anterior and posterior tables, the "
    "nasofrontal outflow tract, the cribriform plate, and the V2 or V3 canals.",
]
NORMAL_EXTRA["dental_maxillofacial"] = [
    "Frontal sinus anterior and posterior tables are intact.",
    "Pterygoid plates are intact bilaterally.",
    "Zygomatic arches and the zygomaticomaxillary buttresses are continuous.",
    "Mandibular condyles are seated within the glenoid fossae; the mandible is intact "
    "and dental occlusion is preserved.",
    "Nasal bones and nasal septum are intact; no pneumocephalus and no soft tissue "
    "emphysema.",
]
