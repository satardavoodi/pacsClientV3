# -*- coding: utf-8 -*-
"""Ultrasound: region pathology rules, and the OBSTETRIC SUBTYPE packages.

⚠️ CLINICAL REVIEW REQUIRED for everything authored here. Compiled 2026-08-09.

WHAT IS EXTRACTED. The SONOGRAPHY branch is the richest source since CT. It already
carries per-exam normal templates with real thresholds (liver <=15-16 cm, CBD <=6 mm,
spleen <=12 cm, kidneys 9-12 cm, thyroid isthmus <=3-4 mm, testes 3-5 cm, ICA PSV
<125 cm/s, appendix <=6 mm, post-void residual <=50 mL), a gynaecologic block, an
obstetric biometry block and an ISUOG obstetric normal-findings block.
`gen_turbo_us_modules.py` extracts all of it.

WHY SUBTYPES EXIST, AND WHY ULTRASOUND FORCED THEM. Every other modality gates on
region alone. Obstetric ultrasound cannot: a dating scan, an NT scan, an anomaly scan, a
growth scan and a biophysical profile all have region `obstetric` and share almost no
reporting content. This centre books 17 distinct obstetric codes. Gating them all to one
`obstetric` package would send the ISUOG anatomy survey to a viability scan and the
failed-pregnancy criteria to a third-trimester growth scan.

So `US_SUBTYPES` is a second, independent axis, selected by `case.subtype` and rendered
after the region packages. The design note from the CT work applies unchanged: region is
WHERE the study looked, subtype is WHAT KIND of study it is.

A FINDING WORTH ACTING ON. `openai_reporter.py` line 1311 branches on
`modality_lower in ["obstetric ultrasound", "ob ultrasound", ...]` and behind it sits a
complete 10-section ISUOG prompt, about 8,000 tokens, with its own JSON schema. The
modality menu emits only CT, MRI, SONOGRAPHY, RADIOLOGY and MAMOGRAPHY - so nothing the
physician can select reaches it. That prompt has been unreachable. The subtype axis is
the fix that does not require a sixth menu entry: an obstetric study is SONOGRAPHY, with
region `obstetric`, plus a subtype.

WHERE GUIDELINES DIFFER OR A VALUE DEPENDS ON THE CHART, NO NUMBER IS ENCODED:
    EFW percentile      depends entirely on which growth standard was applied
    gestational age     depends on the dating method and on which scan dated it
    AFI vs SDP          different measures with different thresholds; not interchangeable
    NT                  valid only in a CRL window and only on a qualifying image
    Doppler indices     PI, RI and S/D are different indices of the same waveform

SOURCES: ISUOG Practice Guidelines - 11-14 week scan (UOG 2023;61:127), routine
mid-trimester scan (UOG 2022;59:840), third-trimester scan (UOG 2024;63:131), fetal
biometry and growth (UOG 2019;53:715), SGA and FGR (UOG 2020;56:298), Doppler
velocimetry (UOG 2021;58:331), pre-eclampsia screening (UOG 2018), placenta accreta
spectrum, twin pregnancy; AIUM practice parameters; RSNA RadReport.

NOT COVERED: fetal echocardiography (2 codes) and fetal lung maturity (1 code) - both
are their own specialty studies and nothing was written for them.
"""
from __future__ import annotations

from typing import Dict, List

US_PATHOLOGY: Dict[str, List[str]] = {}
US_NOTES: Dict[str, List[str]] = {}
US_TECHNIQUE: Dict[str, List[str]] = {}
US_HEADINGS: Dict[str, str] = {}

#: The second gate axis. Keyed by canonical subtype, each with the same section shape
#: as a region package.
US_SUBTYPES: Dict[str, dict] = {}


US_HEADINGS.update({
    "abdomen": "Liver · Gallbladder and biliary tree · Pancreas · Spleen · Kidneys · Aorta and IVC · Free fluid and nodes",
    "pelvis": "Uterus · Endometrium · Ovaries and adnexa · Cervix · Bladder · Free fluid",
    "head_neck": "Thyroid lobes and isthmus · Cervical nodes · Salivary glands · Carotid and vertebral arteries",
    "thyroid": "Thyroid lobes and isthmus · Nodules · Cervical nodes",
    "breast": "Skin and subcutaneous tissue · Fibroglandular parenchyma · Lesions · Ducts · Axilla",
    "scrotum": "Testes · Epididymes · Tunica and hydrocele · Pampiniform plexus · Vascularity",
    "extremity": "Skin and subcutaneous tissue · Muscles and tendons · Joints and bursae · Vessels · Collections",
    "hip": "Femoral head coverage · Acetabular morphology · Stability on stress · Alpha and beta angles",
    "brain": "Ventricles · Periventricular parenchyma · Midline and cavum · Posterior fossa · Extra-axial spaces",
    "orbit": "Globe and lens · Vitreous · Retina and choroid · Optic nerve sheath · Extraocular muscles",
    "chest": "Pleural spaces · Lung sliding and B-lines · Diaphragm · Chest wall",
    "obstetric": "Fetal number and presentation · Cardiac activity · Biometry · Anatomy · Placenta · Amniotic fluid · Cervix · Doppler",
})

US_TECHNIQUE["_shared"] = [
    "Ultrasound is operator- and window-dependent. Preserve any statement he made about "
    "a limited acoustic window, bowel gas, body habitus or patient cooperation - it is "
    "what qualifies every finding after it.",
    "Preserve the approach he used - transabdominal, transvaginal, transrectal, "
    "high-frequency linear, endocavitary - because the same structure is assessed "
    "differently by each and a negative on one is not a negative on another.",
    "Preserve which structures he said were not visualised. On ultrasound, "
    "not-visualised and normal are different statements, and only he can say which "
    "applies.",
]

US_PATHOLOGY["abdomen"] = [
    "Preserve every measurement with the organ and the plane he measured it in, and the "
    "reference he compared it to if he named one.",
    "Focal lesion - preserve the organ, the segment or location, the size in three "
    "planes if he gave them, the echogenicity term he used, and any vascularity he "
    "described on Doppler.",
    "Preserve echotexture terms exactly - hyperechoic, hypoechoic, anechoic, "
    "heterogeneous, coarse. They are not interchangeable and they are his observation.",
    "Biliary - preserve duct calibre with the duct, and, where dilated, the level and "
    "cause he named. Preserve calculi with their number, size and whether they were "
    "mobile and shadowing.",
    "Preserve any hepatic steatosis or fibrosis grading he assigned, with the system, "
    "and any elastography value with its unit and technique.",
    "Preserve free fluid with its location and character, and lymphadenopathy with the "
    "station and short-axis size.",
    "Appendix - preserve the maximal outer diameter, compressibility, wall thickness, "
    "periappendiceal changes and whether he could visualise it at all.",
]

US_PATHOLOGY["pelvis"] = [
    "Uterus - preserve the size in three dimensions, the position, the myometrial "
    "description and every fibroid with its FIGO type if he assigned one, its location "
    "and its size.",
    "Endometrium - preserve the thickness with the plane, and the menstrual phase or "
    "menopausal status he referenced it against. A thickness without that context "
    "cannot be interpreted.",
    "Ovaries - preserve the side, the volume or dimensions, the follicle description, "
    "and any lesion with its locularity, solid components and vascularity. Preserve an "
    "O-RADS score only if he assigned one.",
    "Preserve free fluid with its volume estimate and character, and any adnexal "
    "tenderness or ovarian mobility he described on the probe.",
    "Preserve any Doppler finding with the vessel and the index, and preserve whether "
    "he described flow as present, absent or of a particular waveform.",
]

US_PATHOLOGY["head_neck"] = [
    "Thyroid nodule - preserve the lobe and position, the size in three dimensions, "
    "composition, echogenicity, shape, margin and echogenic foci as he described them, "
    "and any TI-RADS category with the system version he used.",
    "Preserve gland size and echotexture separately from any nodule, and preserve "
    "vascularity as he described it.",
    "Cervical node - preserve the level, the short-axis size, the hilum, the shape and "
    "any cystic change, calcification or peripheral vascularity.",
    "Carotid - preserve the peak systolic and end-diastolic velocities with the vessel "
    "and segment, the intima-media thickness, and any plaque with its location, "
    "surface and echogenicity. Preserve the stenosis grade only with the criteria set "
    "he applied - velocity thresholds differ between published criteria.",
    "Preserve salivary gland and any duct dilatation or calculus with the side.",
]

US_PATHOLOGY["breast"] = [
    "Preserve the side, the clock position, the distance from the nipple and the depth "
    "for every lesion. A breast finding without its location cannot be biopsied.",
    "Preserve shape, orientation, margin, echo pattern and posterior features as he "
    "described them - that is the BI-RADS ultrasound lexicon and each term is a "
    "separate observation.",
    "Preserve the BI-RADS category he assigned and never derive one he did not state.",
    "Preserve elastography and Doppler findings as separate observations, and preserve "
    "axillary nodes with cortical thickness and hilum.",
]

US_PATHOLOGY["scrotum"] = [
    "Preserve the side for every finding. A scrotal report without laterality is not "
    "actionable.",
    "Testicular lesion - preserve the side, size, echogenicity and vascularity, and "
    "preserve whether he called it intratesticular or extratesticular. That distinction "
    "drives management.",
    "Torsion - preserve exactly what he said about flow: present, reduced, absent, and "
    "compared to the other side. Never soften an absent-flow statement.",
    "Varicocele - preserve the vein calibre, the side, and whether reflux was present "
    "and on what manoeuvre.",
    "Preserve hydrocele, epididymal findings and any wall thickening with the side.",
]

US_PATHOLOGY["extremity"] = [
    "Preserve the exact site he scanned and the side. A soft-tissue ultrasound is only "
    "as useful as its localisation.",
    "Collection - preserve the dimensions, the depth, the contents he described, and "
    "whether it was compressible or had internal vascularity.",
    "Tendon - preserve the tendon by name, whether he called the tear partial or "
    "full-thickness, and any dynamic finding he obtained on movement.",
    "Deep vein - preserve which veins were assessed, compressibility segment by "
    "segment, and the presence, extent and age of any thrombus. Preserve the veins he "
    "could not assess.",
    "Arterial - preserve the waveform he described (triphasic, biphasic, monophasic), "
    "the velocities and the site.",
]

US_PATHOLOGY["hip"] = [
    "Infant hip - preserve the alpha and beta angles with the side, and any Graf type "
    "he assigned. Preserve the femoral head coverage he measured.",
    "Preserve stability as he described it on the dynamic manoeuvre - stable, "
    "subluxatable, dislocatable, dislocated - and never infer it from a static image.",
    "Preserve the infant's age. Hip ultrasound findings are age-dependent and a "
    "measurement without an age cannot be interpreted.",
    "Adult hip - preserve any effusion with its depth, and any bursal or tendon finding "
    "with the side.",
]

US_PATHOLOGY["brain"] = [
    "Neonatal head - preserve the ventricular measurements with the side and the plane, "
    "and any index he used with its name.",
    "Haemorrhage - preserve the grade he assigned with the system, the side and the "
    "location. Never assign a grade he did not state.",
    "Preserve periventricular echogenicity and any cystic change with the side, and "
    "preserve the fontanelle window he used.",
    "Preserve midline structures, the cavum and the posterior fossa separately.",
]

US_PATHOLOGY["orbit"] = [
    "Preserve the side and whether the finding was intraocular or orbital.",
    "Preserve retinal or choroidal detachment as he characterised it, including "
    "mobility on kinetic scanning, and preserve any vitreous finding separately.",
    "Preserve the optic nerve sheath diameter with the distance behind the globe at "
    "which it was measured. Published thresholds differ, so carry his figure.",
    "Preserve any foreign body with its composition and position.",
]

US_PATHOLOGY["chest"] = [
    "Preserve the side and the zones he scanned. A lung ultrasound is reported by zone.",
    "Preserve pleural effusion with its estimated volume, echogenicity and any septation.",
    "Preserve lung sliding, B-lines and consolidation exactly as he described them, "
    "including their absence, and preserve any lung point he identified.",
    "Preserve diaphragmatic excursion with the side and the manoeuvre.",
]

US_NOTES.update({
    "scrotum": ["Every finding carries a side."],
    "breast": ["Every lesion carries side, clock position, distance from nipple and "
               "depth."],
    "hip": ["An infant hip measurement without the infant's age cannot be read."],
    "abdomen": ["Preserve any statement that the acoustic window was limited."],
})

#: Ultrasound dictation terms. ⚠️ Authored - check the Persian against what the
#: transcription service actually emits.
US_TERMS = [
    "سونوگرافی → ultrasound",
    "اکوژنیسیته → echogenicity",
    "هایپراکو → hyperechoic",
    "هایپواکو → hypoechoic",
    "انکو → anechoic",
    "داپلر → Doppler",
    "ترانس واژینال → transvaginal",
    "ترانس ابدومینال → transabdominal",
    "کیست → cyst",
    "سنگ → calculus",
    "هیدرونفروز → hydronephrosis",
    "آسیت → ascites",
    "جنین → fetus",
    "جفت → placenta",
    "مایع آمنیوتیک → amniotic fluid",
    "ضربان قلب جنین → fetal heart rate",
    "سن بارداری → gestational age",
]


# ═══════════════════════════════════════════════════════════════════════════
# THE OBSTETRIC SUBTYPE PACKAGES
# ═══════════════════════════════════════════════════════════════════════════

US_SUBTYPES["ob_first_trimester"] = {
    "title": "First trimester — dating and viability",
    "technique": [
        "Preserve the route he used. A transvaginal scan answers questions a "
        "transabdominal scan cannot, and the criteria for a failed pregnancy differ by "
        "route: on the transabdominal route ISUOG asks for a repeat a minimum of 14 "
        "days later before concluding.",
    ],
    "must_report": [
        "Preserve the number of gestational sacs, and for each: the presence of a yolk "
        "sac, the presence of a fetal pole, and cardiac activity present or absent.",
        "Preserve the measurement he dated by - crown-rump length or mean sac diameter "
        "- with its value, and the gestational age he assigned from it.",
        "Preserve the location of the pregnancy as he described it, intrauterine or "
        "otherwise, and any adnexal finding or free fluid.",
    ],
    "pathology": [
        "Preserve his conclusion about viability exactly as he stated it, including any "
        "hedge. 'Cannot be excluded' and 'no cardiac activity' are different reports "
        "with different consequences, and a suggested interval scan must survive.",
        "Never conclude a failed pregnancy from measurements he reported without saying "
        "so. The criteria are specific and they are his to apply.",
        "Preserve subchorionic haemorrhage with its size and relation to the sac.",
        "Preserve any statement that the findings are inconclusive and a repeat scan is "
        "advised - that is a recommendation and it must not be dropped.",
    ],
}

US_SUBTYPES["ob_ectopic"] = {
    "title": "Ectopic pregnancy search",
    "technique": ["Preserve the route. This question is usually answered transvaginally "
                  "and a transabdominal negative does not close it."],
    "must_report": [
        "Preserve whether an intrauterine gestational sac was seen, and preserve the "
        "endometrial appearance and thickness.",
        "Preserve every adnexal finding with the side, the size and what he called it - "
        "a tubal ring, a complex mass, or a corpus luteum.",
        "Preserve free fluid with its volume estimate and echogenicity. Echogenic free "
        "fluid is a different finding from anechoic and must not be generalised.",
    ],
    "pathology": [
        "Preserve his terminology exactly. Pregnancy of unknown location, suspected "
        "ectopic and confirmed ectopic are three different reports.",
        "Preserve any beta-hCG value or clinical correlation he referenced, and any "
        "recommendation for interval scanning or clinical review.",
        "Preserve any statement about haemodynamic concern or a large volume of "
        "haemoperitoneum without softening it.",
    ],
}

US_SUBTYPES["ob_nt"] = {
    "title": "Nuchal translucency and nasal bone",
    "technique": [
        "Preserve the crown-rump length. Nuchal translucency is valid only within a CRL "
        "window, and a measurement outside it is not an NT.",
        "Preserve any statement he made about image quality or the number of attempts - "
        "the measurement depends on a qualifying midsagittal image with the fetus "
        "neutral and the calipers correctly placed.",
    ],
    "must_report": [
        "Preserve the CRL, the gestational age, the NT measurement in millimetres, and "
        "the nasal bone as present, absent or not assessable.",
        "Preserve cardiac activity and the fetal number, and for multiples preserve "
        "which fetus each measurement belongs to.",
        "Preserve any additional first-trimester anatomy he surveyed.",
    ],
    "pathology": [
        "Preserve the NT value as he measured it. Never convert it into a risk, a "
        "centile or a screen-positive result - the risk calculation combines maternal "
        "age, biochemistry and the software's own reference and is not yours to derive.",
        "Preserve ductus venosus and tricuspid flow findings if he assessed them, each "
        "as a separate observation.",
        "Preserve any statement that the measurement was not obtainable, and any "
        "recommendation to repeat.",
    ],
}

US_SUBTYPES["ob_anomaly"] = {
    "title": "Mid-trimester anomaly scan",
    "technique": ["Preserve any structure he recorded as not adequately visualised, and "
                  "any recommendation to re-scan for it. On an anomaly scan, a "
                  "not-seen structure is a reportable outcome, not an omission."],
    "must_report": [
        "The ISUOG minimum survey, by system: head — intact cranium, head shape, cavum "
        "septi pellucidi, choroid plexus, midline falx, thalami, lateral ventricles, "
        "cerebellum, cisterna magna. Face — both orbits, midsagittal profile, nasal "
        "bone, upper lip intact. Neck — no mass.",
        "Chest and heart — chest and lungs normal in shape and size, cardiac activity, "
        "four-chamber view with the left chambers on the left, aortic and pulmonary "
        "outflow tracts. Abdomen — stomach on the left, bowel not dilated, gallbladder "
        "on the right, both kidneys present, no pyelectasis, cord insertion at the "
        "abdominal wall, bladder present.",
        "Skeletal — no spinal defect on transverse and sagittal views, arms and hands "
        "present with normal joint position, legs and feet present with normal joint "
        "position. Placenta — position and relation to the cervix, no mass. Cord — "
        "three vessels, normal placental insertion. Genitalia, and cervical length "
        "where assessed.",
        "Preserve biometry as he measured it and the estimated fetal weight with the "
        "formula or chart he used.",
    ],
    "pathology": [
        "Preserve every anomaly with the system, the side and the exact descriptors he "
        "used. Preserve any measurement he made of it.",
        "Preserve soft markers exactly as he characterised them, and preserve his "
        "statement of significance if he made one. Never upgrade a soft marker to an "
        "anomaly.",
        "Preserve any recommendation for fetal echocardiography, MRI, karyotyping or "
        "referral - these are the recommendations that most matter and they must "
        "survive intact.",
    ],
}

US_SUBTYPES["ob_growth"] = {
    "title": "Growth and fetal growth restriction",
    "technique": ["Preserve the interval since the previous scan and the previous "
                  "measurements he compared against. A growth scan is a comparison, "
                  "and without the prior it is a single biometry."],
    "must_report": [
        "Preserve each biometric measurement he took - biparietal diameter, head "
        "circumference, abdominal circumference, femur length, and humerus length where "
        "measured - with its value.",
        "Preserve the estimated fetal weight with the formula he used and the centile "
        "with the growth chart it came from. A centile without its reference chart "
        "cannot be interpreted and must never be restated against a different one.",
        "Preserve the amniotic fluid assessment with the method - amniotic fluid index "
        "or single deepest pocket. They are different measures with different "
        "thresholds and are not interchangeable.",
        "Preserve placental location and appearance, and fetal presentation.",
    ],
    "pathology": [
        "Preserve his classification exactly - small for gestational age and fetal "
        "growth restriction are different conclusions, and early and late FGR are "
        "defined differently. Never derive one from the numbers he reported.",
        "Preserve any Doppler index he obtained as part of the assessment, with the "
        "vessel and the index name.",
        "Preserve growth velocity or any drop across centiles as he described it, and "
        "any recommendation for interval scanning or delivery planning.",
    ],
}

US_SUBTYPES["ob_doppler"] = {
    "title": "Obstetric Doppler",
    "technique": [
        "Preserve the insonation conditions he described - the angle, the absence of "
        "fetal breathing or movement, the segment of the vessel sampled. A Doppler "
        "index is only as good as the waveform it came from.",
    ],
    "must_report": [
        "Preserve every index with its vessel and its name. Pulsatility index, "
        "resistance index and the systolic-diastolic ratio are different indices of the "
        "same waveform and are not interchangeable.",
        "Preserve umbilical artery findings including absent or reversed end-diastolic "
        "flow, exactly as he stated them. That distinction is the whole point of the "
        "study.",
        "Preserve middle cerebral artery indices, and any cerebroplacental ratio or "
        "umbilicocerebral ratio with which one he calculated - they are inverses of "
        "each other.",
        "Preserve uterine artery indices with the side and whether he described a "
        "notch, and preserve ductus venosus waveform including the a-wave.",
    ],
    "pathology": [
        "Preserve any centile he quoted with the reference it came from.",
        "Never convert a raw index into a centile, or a centile into a clinical "
        "category. Both depend on the reference range in use.",
        "Preserve brain-sparing, redistribution or deterioration only if he used those "
        "words, and preserve any recommendation for surveillance interval or delivery.",
    ],
}

US_SUBTYPES["ob_bpp"] = {
    "title": "Biophysical profile",
    "technique": ["Preserve the observation period. Each component requires the fetus "
                  "to be watched for a defined time before it can be scored zero."],
    "must_report": [
        "Preserve each of the five components as he scored it - fetal breathing "
        "movements, gross body movement, fetal tone, amniotic fluid volume, and the "
        "non-stress test where performed - and preserve the total.",
        "Preserve the amniotic fluid measurement with the method he used.",
    ],
    "pathology": [
        "Never compute the total from components he reported, and never infer a "
        "component score he did not state. A biophysical profile score is a clinical "
        "decision instrument.",
        "Preserve any recommendation for repeat testing or delivery exactly as given.",
    ],
}

US_SUBTYPES["ob_placenta"] = {
    "title": "Placenta and placenta accreta spectrum",
    "technique": ["Preserve the bladder filling state and the route. The uterovesical "
                  "interface is assessed with a partly filled bladder and the "
                  "transvaginal route adds to the transabdominal for the lower segment."],
    "must_report": [
        "Preserve the placental location and its relationship to the internal cervical "
        "os as he described it, with the distance in millimetres if he measured one. "
        "The current terminology is low-lying versus praevia; preserve his term.",
        "Preserve any prior caesarean or uterine surgery he referenced, since the "
        "accreta assessment is read against it.",
    ],
    "pathology": [
        "Preserve each accreta spectrum descriptor he named, individually: loss of the "
        "clear zone, myometrial thinning, abnormal placental lacunae, bladder wall "
        "interruption, placental bulge, focal exophytic mass, uterovesical "
        "hypervascularity, subplacental hypervascularity, bridging vessels, lacunae "
        "feeder vessels. Do not summarise them into a single impression he did not make.",
        "Preserve whether he called the involvement focal or diffuse, and any grade he "
        "assigned. Never assign a grade from the descriptors yourself.",
        "Preserve placental abruption, succenturiate lobe, vasa praevia and velamentous "
        "cord insertion as distinct findings, each with its location.",
    ],
}

US_SUBTYPES["ob_multiple"] = {
    "title": "Multiple pregnancy",
    "technique": ["Preserve the gestational age at which chorionicity was determined. "
                  "It is reliable only in an early window, and a later assessment "
                  "carries less weight - which is why the first determination is the "
                  "one that must survive."],
    "must_report": [
        "Preserve chorionicity and amnionicity as he determined them, and the features "
        "he based them on - the intertwin septum, the lambda or T sign, the number of "
        "placental masses.",
        "Preserve his twin labelling strategy exactly as he recorded it. Relabelling "
        "twins between scans is a serious error, and the labels are only meaningful "
        "with the convention he used.",
        "Preserve per-fetus biometry, estimated weight, amniotic fluid and Doppler, "
        "each attributed to the correct twin.",
    ],
    "pathology": [
        "Preserve the estimated weight discordance as he calculated it, and any "
        "selective growth restriction classification with the criteria set he applied - "
        "the criteria differ between dichorionic and monochorionic pregnancies.",
        "Preserve twin-to-twin transfusion findings and any staging he assigned, never "
        "derived.",
        "Preserve amniotic fluid separately for each sac.",
    ],
}


#: The SONOGRAPHY prompt has an exam template for twelve studies but none for the
#: infant hip, the neonatal head, the orbit or the chest. ⚠️ Authored, feature-register.
US_NORMAL_EXTRA = {
    "hip": [
        "Femoral heads are well seated within the acetabula bilaterally, with normal "
        "bony coverage.",
        "Acetabular roofs are normally angled with a well-formed bony rim and a normal "
        "cartilaginous labrum.",
        "Alpha and beta angles are within the expected range for the infant's age.",
        "Hips remain located and stable throughout the dynamic manoeuvre; no "
        "subluxation and no dislocation.",
        "Cartilaginous femoral heads are symmetric in size and echotexture.",
        "No joint effusion; the anterior synovial recess is not distended.",
        "Ossific nuclei, where present, are symmetric.",
        "Surrounding soft tissues are unremarkable.",
    ],
    "brain": [
        "Lateral ventricles are normal in size and symmetric, with no dilatation.",
        "Third and fourth ventricles are normal in size and position.",
        "Germinal matrix and periventricular white matter show normal echogenicity, "
        "with no haemorrhage and no cystic change.",
        "Choroid plexuses are smooth and symmetric.",
        "Cavum septi pellucidi is present and the midline structures are normal.",
        "Corpus callosum is present and normally formed on the midline sagittal view.",
        "Posterior fossa structures, including the cerebellum and cisterna magna, are "
        "normal.",
        "Extra-axial spaces are not widened and there is no extra-axial collection.",
        "Cerebral parenchyma shows normal echogenicity with normal sulcation for "
        "gestational age.",
    ],
    "orbit": [
        "Globe is normal in size and contour with an intact wall.",
        "Anterior chamber is clear and the lens is normally positioned and anechoic.",
        "Vitreous is anechoic, without haemorrhage, opacity or membrane.",
        "Retina and choroid are apposed to the wall throughout, with no detachment.",
        "Optic nerve sheath is normal in calibre at the measured distance behind the "
        "globe.",
        "Extraocular muscles are symmetric in thickness.",
        "Retrobulbar fat is homogeneous, with no mass or collection.",
        "No intraocular or intraorbital foreign body.",
    ],
    "chest": [
        "Pleural spaces are clear bilaterally, with no effusion.",
        "Lung sliding is present throughout the zones examined.",
        "A-lines are the predominant pattern; no pathological B-lines.",
        "No subpleural consolidation and no air bronchograms.",
        "No lung point identified; no evidence of pneumothorax.",
        "Diaphragms move normally and symmetrically with respiration.",
        "Chest wall soft tissues are unremarkable, with no collection.",
        "No pericardial effusion in the views obtained.",
    ],
}


US_PATHOLOGY["thyroid"] = list(US_PATHOLOGY["head_neck"])

US_PATHOLOGY["obstetric"] = [
    "Preserve the gestational age with the method it came from, and preserve which "
    "scan established the dating. A gestational age re-derived from today's biometry "
    "is a different number from the established one and must not replace it.",
    "Preserve fetal number, presentation and cardiac activity exactly as stated, "
    "including a heart rate if he gave one.",
    "Preserve every biometric measurement with its abbreviation, and any estimated "
    "fetal weight with the formula and the growth chart he used. A centile without its "
    "chart cannot be interpreted.",
    "Preserve the amniotic fluid assessment with the method - amniotic fluid index or "
    "single deepest pocket. They are different measures with different thresholds.",
    "Preserve the placental location and its relation to the internal os, with the "
    "distance if he measured one.",
    "Preserve every Doppler index with its vessel and index name, and preserve absent "
    "or reversed end-diastolic flow exactly as stated.",
    "Preserve any recommendation for interval scanning, referral or further imaging. "
    "In obstetrics these are the part of the report that changes what happens next.",
]

US_NORMAL_EXTRA["breast"] = [
    "Both breasts show a normal fibroglandular pattern for age, with no architectural "
    "distortion.",
    "No solid or complex cystic mass identified in either breast.",
    "No ductal dilatation and no intraductal lesion.",
    "Skin and subcutaneous tissues are of normal thickness, without oedema or "
    "retraction.",
    "No abnormal vascularity on colour Doppler within the areas examined.",
    "Axillae show no node of abnormal cortical thickness or lost fatty hilum.",
]
US_NORMAL_EXTRA["scrotum"] = [
    "Both testes are normal in size, symmetric and homogeneous in echotexture, without "
    "focal lesion or microlithiasis.",
    "Both epididymal heads, bodies and tails are normal in size and echogenicity.",
    "Symmetric intratesticular vascularity is demonstrated bilaterally on colour and "
    "spectral Doppler.",
    "No hydrocele, haematocele or pyocele.",
    "Pampiniform plexus veins are of normal calibre with no reflux on Valsalva.",
    "Tunica albuginea is intact bilaterally and the scrotal wall is of normal "
    "thickness.",
]
US_NORMAL_EXTRA["head_neck"] = [
    "Both thyroid lobes and the isthmus are normal in size and homogeneous in "
    "echotexture, with no nodule.",
    "Normal thyroid vascularity on colour Doppler.",
    "No cervical lymphadenopathy; visualised nodes retain a fatty hilum and normal "
    "cortical thickness.",
    "Submandibular and parotid glands are normal in size and echotexture, with no duct "
    "dilatation or calculus.",
    "Carotid and vertebral arteries are patent bilaterally with normal antegrade flow "
    "and no haemodynamically significant stenosis.",
    "Internal jugular veins are patent and compressible bilaterally.",
]
US_NORMAL_EXTRA["thyroid"] = list(US_NORMAL_EXTRA["head_neck"])
