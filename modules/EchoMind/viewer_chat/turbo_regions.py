"""CT region blocks, lifted VERBATIM out of the monolithic report prompt.

GENERATED, NOT WRITTEN. Produced by extracting the `RSNA-compliant normal findings per
CT body region` section from the live output of `build_report_system_prompt("CT", "")`.
A hand copy of nineteen clinical blocks is a transcription error waiting to happen, and
the point of this step is that it is provably lossless: `test_turbo_regions.py` asserts
that PREFIX + every block, concatenated in order, reproduces that section byte for byte.

WHY PYTHON AND NOT MARKDOWN FILES. `AIPacs.spec` requires an explicit `datas.append(...)`
for every non-`.py` resource, and the Nuitka build has its own include list. A `.md`
region library would work in development and vanish in the frozen build — the worst
possible failure mode for clinical content. A module is compiled, mirrored to the plugin
payload by the existing sync, and still reviewable in a diff.

EDITING. These strings are the real prompt content. Changing one changes what the model
is told about that region — and only that region, only on Turbo. The reassembly test
will fail the moment a block is edited, which is intended: re-run
`tools/dev/regen_turbo_regions.py` to re-baseline once the change is deliberate.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

#: The text that opens the region section, before the first block.
SECTION_PREFIX: str = """* RSNA-compliant normal findings per CT body region:

"""

#: (block name, verbatim text) in the order they appear in the live prompt.
CT_BLOCKS: List[Tuple[str, str]] = [
    ('BRAIN CT (NON-CONTRAST)',
     """                        – BRAIN CT (NON-CONTRAST):
                            • No acute territorial infarction; grey-white matter differentiation is preserved bilaterally.
                            • No intracranial haemorrhage (parenchymal, subdural, epidural, or subarachnoid).
                            • No abnormal intraparenchymal hyperdensity or hypodensity.
                            • Ventricular system is normal in size and configuration; no hydrocephalus.
                            • No midline shift or significant mass effect.
                            • Basal cisterns are patent and symmetric; no effacement.
                            • No extra-axial fluid collection.
                            • Cerebral sulci and gyri are appropriate for patient age; no asymmetric sulcal effacement.
                            • The cerebellum and brainstem show no focal hypodense or hyperdense lesion.
                            • Posterior fossa structures are unremarkable; fourth ventricle is in normal position.
                            • Osseous calvarium: no fracture, lytic, or sclerotic lesion.
                            • Visualised paranasal sinuses and mastoid air cells are clear.
                            • The orbits are normal in appearance; globes are symmetric.

"""),
    ('BRAIN CT WITH CONTRAST',
     """                        – BRAIN CT WITH CONTRAST:
                            • No abnormal parenchymal, leptomeningeal, or dural enhancement.
                            • No ring-enhancing or nodular-enhancing lesion.
                            • Major intracranial vessels demonstrate normal enhancement without filling defect or cutoff.
                            • No abnormal enhancement in the posterior fossa or brainstem.
                            • Choroid plexuses enhance symmetrically; no abnormal ependymal enhancement.

"""),
    ('CHEST CT AND HRCT',
     """                        – CHEST CT AND HRCT:
                            • Lung parenchyma: clear lung fields bilaterally; no focal consolidation, mass, or suspicious nodule.
                            • No ground-glass opacity, interstitial thickening, or honeycombing.
                            • Airways: trachea and central bronchi are patent and normally calibred; no bronchiectasis or bronchial wall thickening.
                            • Pleura: no pleural effusion, pleural thickening, or pneumothorax bilaterally.
                            • Mediastinum: no mediastinal widening or mass; no pathologic lymphadenopathy (no node greater than 1 cm short axis).
                            • Heart: normal in size; no pericardial effusion or thickening.
                            • Thoracic aorta and pulmonary vasculature are normal in calibre and course.
                            • Oesophagus: not dilated; no wall thickening.
                            • Chest wall and osseous structures: no rib fracture, no lytic or sclerotic bony lesion.
                            • Thyroid gland (visualised): symmetric; no nodule detected on this limited view.
                            • Visualised upper abdominal organs are unremarkable.

"""),
    ('NECK CT',
     """                        – NECK CT:
                            • Larynx: normal configuration and symmetry; no mucosal irregularity or subglottic narrowing.
                            • Epiglottis and supraglottic structures: unremarkable.
                            • Hypopharynx and oropharynx: no asymmetric soft tissue thickening.
                            • Thyroid gland: normal in size, morphology, and attenuation; no nodule or calcification.
                            • Parathyroid glands: not enlarged.
                            • Salivary glands: parotid and submandibular glands are symmetric and normal in attenuation.
                            • No pathologic cervical lymphadenopathy (no node greater than 1 cm short axis); no necrotic node.
                            • Carotid arteries and internal jugular veins: patent bilaterally; no vascular abnormality.
                            • Prevertebral soft tissues: not thickened.
                            • Cervical spine (limited view): normal alignment; no fracture or subluxation.

"""),
    ('PARANASAL SINUS CT',
     """                        – PARANASAL SINUS CT:
                            • Frontal sinuses: clear bilaterally; no mucosal thickening, polyp, or air-fluid level.
                            • Maxillary sinuses: clear bilaterally; no mucosal thickening, polyp, or opacification.
                            • Ethmoid air cells: clear bilaterally; no opacification or cell wall erosion.
                            • Sphenoid sinus: clear; no opacification or lateral recess involvement.
                            • Nasal cavity: patent bilaterally; nasal septum midline without perforation; inferior and middle turbinates are of normal size.
                            • Ostiomeatal complexes: patent bilaterally; no obstructing polyp or mucosal disease.
                            • No concha bullosa; no paradoxical middle turbinate.
                            • Orbits (limited view): no periorbital extension of sinus disease; optic nerves unremarkable.
                            • Dentition (limited view): no periapical lucency or dental abscess on this limited view.

"""),
    ('ABDOMEN CT',
     """                        – ABDOMEN CT:
                            • Liver: normal in size, morphology, and attenuation; no focal hepatic lesion; smooth hepatic contour.
                            • Gallbladder: normal wall thickness and luminal content; no cholelithiasis or polyp.
                            • Bile ducts: common bile duct not dilated (less than 6 mm); no intrahepatic biliary ductal dilatation.
                            • Spleen: normal in size and attenuation; no focal splenic lesion.
                            • Pancreas: normal in size, contour, and attenuation; pancreatic duct not dilated (less than 3 mm); no peripancreatic fat stranding.
                            • Adrenal glands: normal size and morphology bilaterally; no adrenal mass.
                            • Kidneys: normal in size, cortical thickness, and enhancement bilaterally; no nephrolithiasis or hydronephrosis; no perinephric fat stranding.
                            • Bowel: no small or large bowel obstruction; no bowel wall thickening or pneumatosis; appendix visualised and normal (less than 6 mm).
                            • No pneumoperitoneum or intraperitoneal free fluid.
                            • Abdominal aorta: normal calibre (less than 3 cm); no aneurysmal dilatation or mural thrombus.
                            • No enlarged abdominal or retroperitoneal lymph nodes (no node greater than 1 cm short axis).
                            • Abdominal wall: no hernia or abnormal soft tissue mass.

"""),
    ('PELVIS CT',
     """                        – PELVIS CT:
                            ── SEX-SPECIFIC ANATOMY RULE (STRICT — applies to prostate, uterus, ovaries, seminal vesicles, cervix, vagina, testes) ──
                            • DO NOT infer or assume the patient's sex. If the physician did not state the sex and it cannot be
                              reliably determined from the physician-provided content, do NOT assume it.
                            • Include a sex-specific organ ONLY IF the physician EXPLICITLY mentioned that organ (or provided a
                              finding that clearly requires it). If the physician gave no information about a sex-specific organ,
                              OMIT that organ entirely — do NOT emit a normal/"unremarkable" statement for it.
                            • NEVER include BOTH male and female organs in the same report. A report must never list, e.g., the
                              prostate AND the uterus/ovaries together just because this template mentions both.
                            • Urinary bladder: normal wall thickness; no intraluminal filling defect, calculus, or mural mass.
                            • Distal ureters: not dilated; no ureteric calculus at the ureterovesical junction.
                            • Uterus — INCLUDE ONLY IF the physician explicitly mentioned it: normal in size and attenuation; no intraluminal mass or myometrial lesion. (Otherwise OMIT entirely.)
                            • Ovaries — INCLUDE ONLY IF the physician explicitly mentioned them: normal in size; no ovarian mass or complex cyst. (Otherwise OMIT entirely.)
                            • Prostate — INCLUDE ONLY IF the physician explicitly mentioned it: normal in size; no hypodense lesion. (Otherwise OMIT entirely.)
                            • Seminal vesicles — INCLUDE ONLY IF the physician explicitly mentioned them: symmetric and unremarkable. (Otherwise OMIT entirely.)
                            • Rectum and sigmoid colon: normal wall thickness; no pericolonic fat stranding.
                            • No pelvic lymphadenopathy; no free pelvic fluid.
                            • Pelvic floor musculature: symmetric and unremarkable.
                            • Osseous structures of the pelvis: no lytic, sclerotic, or erosive changes; sacroiliac joints symmetric; femoral heads spherical with preserved joint space.

"""),
    ('ABDOMINOPELVIC CT',
     """                        – ABDOMINOPELVIC CT:
                            • Full survey of abdominal and pelvic organs as described above with no focal abnormality identified.
                            • No pneumoperitoneum or free intraperitoneal fluid.
                            • Abdominal aorta and iliac vessels: normal in calibre; no aneurysm.
                            • No significant abdominal or pelvic lymphadenopathy.

"""),
    ('CERVICAL SPINE CT',
     """                        – CERVICAL SPINE CT:
                            • Vertebral alignment: normal cervical lordosis maintained; no anterolisthesis or retrolisthesis at any level.
                            • Vertebral bodies: normal height, cortical margins, and bone density at C1 through C7.
                            • Intervertebral disc spaces: maintained at all cervical levels; no disc calcification.
                            • Spinal canal: adequate AP diameter at all levels; no significant central stenosis.
                            • Neural foramina: patent bilaterally at all cervical levels.
                            • Facet joints: normal articular surfaces; no hypertrophic change or erosion.
                            • Atlantoaxial joint: normal alignment; odontoid process intact and normally positioned; C1-C2 interval preserved.
                            • Prevertebral soft tissues: not thickened.
                            • Posterior elements (pedicles, laminae, spinous processes): intact at all levels.
                            • No fracture, dislocation, lytic, or sclerotic bony lesion.

"""),
    ('THORACIC SPINE CT',
     """                        – THORACIC SPINE CT:
                            • Vertebral alignment: normal thoracic kyphosis; no spondylolisthesis at any level.
                            • Vertebral bodies: normal height, cortical integrity, and bone density from T1 to T12; no compression deformity.
                            • Intervertebral disc spaces: maintained throughout.
                            • Spinal canal: patent at all thoracic levels; no significant stenosis.
                            • Posterior elements: pedicles, laminae, transverse processes, and spinous processes intact.
                            • Costovertebral articulations: normal bilaterally; no rib head erosion or subluxation.
                            • Paravertebral soft tissues: no paravertebral mass or abscess.
                            • No lytic, sclerotic, or destructive bony lesion throughout the thoracic spine.

"""),
    ('LUMBAR SPINE CT',
     """                        – LUMBAR SPINE CT:
                            • Vertebral alignment: normal lumbar lordosis; no spondylolisthesis at L1 through S1.
                            • Vertebral bodies: normal height and bone density at all lumbar levels; no compression or wedge deformity.
                            • Intervertebral disc spaces: maintained at all levels; no significant disc height loss or calcification.
                            • Spinal canal: adequate AP diameter and cross-sectional area at all lumbar levels.
                            • Thecal sac: not compressed at any level.
                            • Neural foramina: patent bilaterally at all lumbar levels; no significant foraminal narrowing.
                            • Facet joints: normal articular surfaces bilaterally; no significant joint space narrowing or vacuum phenomenon.
                            • Sacroiliac joints: symmetric and unremarkable; no erosion or sclerosis.
                            • Paraspinal musculature: normal bulk and attenuation bilaterally.
                            • No fracture, lytic, or sclerotic lesion at L1 through S1 or the sacrum.

"""),
    ('MSK CT SHOULDER',
     """                        – MSK CT SHOULDER:
                            • Glenohumeral joint: normal articular surfaces; preserved joint space; no effusion.
                            • Humeral head: normal sphericity and cortical integrity; no Hill-Sachs defect.
                            • Glenoid: normal morphology; no Bankart osseous lesion or glenoid rim fracture.
                            • Acromioclavicular joint: normal; no superior migration of the humeral head.
                            • Acromion: no os acromiale; subacromial space not critically narrowed.
                            • Clavicle and scapula: intact; no fracture or lytic lesion.
                            • Soft tissues (visualised): no abnormal calcification or soft tissue mass.

"""),
    ('MSK CT HIP',
     """                        – MSK CT HIP:
                            • Femoral head: normal sphericity; no subchondral collapse, cyst, or osteonecrosis.
                            • Acetabulum: normal morphology; no fracture, labral ossification, or protrusio.
                            • Hip joint space: preserved bilaterally; no joint effusion.
                            • No cam or pincer deformity.
                            • Femoral neck: normal neck-shaft angle; no stress fracture or cortical defect.
                            • Pelvis and proximal femora: no lytic, sclerotic, or permeative bony lesion.
                            • Soft tissues: no iliopsoas or trochanteric bursitis; no calcific tendinopathy.

"""),
    ('MSK CT KNEE',
     """                        – MSK CT KNEE:
                            • Tibial plateau: no fracture, depression, or cortical disruption.
                            • Femoral condyles: intact articular surfaces; no osteochondral defect.
                            • Patellofemoral joint: normal alignment; no tilt or subluxation; no patellar fracture.
                            • Joint space: preserved in all three compartments.
                            • No intra-articular loose body.
                            • Proximal fibula: intact.
                            • Soft tissues: no soft tissue calcification.

"""),
    ('MSK CT ANKLE AND FOOT',
     """                        – MSK CT ANKLE AND FOOT:
                            • Tibiotalar joint: normal alignment and joint space; no fracture.
                            • Talus: intact; no osteochondral lesion of the talar dome; no avascular necrosis.
                            • Calcaneus: normal morphology; no fracture.
                            • Subtalar, talonavicular, and calcaneocuboid joints: normal alignment; no coalition.
                            • Metatarsals and phalanges: intact; no stress fracture or lytic lesion.
                            • No tarsal coalition.
                            • Soft tissues: no abnormal calcification.

"""),
    ('MSK CT WRIST AND HAND',
     """                        – MSK CT WRIST AND HAND:
                            • Distal radius and ulna: intact articular surfaces; normal ulnar variance; no fracture.
                            • Carpal bones: normal alignment and osseous integrity; no scaphoid fracture; no carpal coalition.
                            • Intercarpal joints: normally aligned; no dissociation.
                            • Metacarpals and phalanges: intact; no cortical disruption or periosteal reaction.
                            • Soft tissues: no calcification; no erosive joint disease.

"""),
    ('CORONARY CTA',
     """                        – CORONARY CTA:
                            • Coronary artery origin and course: all three vessels arise normally from the aortic root; no anomalous origin.
                            • Left main coronary artery (LMCA): patent throughout; no significant stenosis or calcified plaque.
                            • Left anterior descending artery (LAD): patent; no significant stenosis; no obstructive calcification.
                            • Left circumflex artery (LCx): patent; no significant stenosis.
                            • Right coronary artery (RCA): patent; right-dominant circulation; no significant stenosis.
                            • Cardiac chambers: no chamber dilatation; left ventricular wall thickness within normal limits.
                            • Myocardium: no perfusion defect or focal myocardial thinning.
                            • Pericardium: no pericardial effusion or constrictive thickening.
                            • Aortic root and ascending aorta: normal in calibre; no dilatation.
                            • Pulmonary vasculature: no pulmonary embolism or filling defect.
                            • Incidental extracardiac findings: none significant.

"""),
    ('CT ANGIOGRAPHY AORTA',
     """                        – CT ANGIOGRAPHY AORTA:
                            • Aortic root and ascending aorta: normal calibre; no aneurysm, intramural haematoma, or penetrating ulcer.
                            • Aortic arch: normal origin of branch vessels; no arch aneurysm.
                            • Descending thoracic aorta: normal calibre and smooth wall; no dissection flap.
                            • Abdominal aorta: normal calibre (less than 3 cm); no aneurysmal dilatation or mural thrombus.
                            • Major visceral branches (celiac, SMA, renal arteries): patent and normally arising with no stenosis.
                            • Iliac arteries: normal in calibre and course bilaterally; no aneurysm.
                            • No arteriovenous fistula or vascular anomaly.

"""),
    ('CT UROGRAPHY AND CT KUB',
     """                        – CT UROGRAPHY AND CT KUB:
                            • Kidneys: normal in size, cortical thickness, and corticomedullary differentiation bilaterally; normal parenchymal enhancement.
                            • Collecting systems: no caliceal dilatation or hydronephrosis bilaterally.
                            • No nephrolithiasis; no cortical scar or nephrocalcinosis.
                            • Ureters: course normally throughout their length; no ureteral calculus, stricture, or dilatation.
                            • Urinary bladder: normal wall thickness and morphology; no intraluminal filling defect, calculus, or mural lesion.
                            • No perinephric fat stranding or retroperitoneal mass.
                            • Adrenal glands: normal size and morphology bilaterally.


"""),
]

#: The GROUPING VOCABULARY entries — the headings the prompt tells the model to
#: use. Sent whole today, so a knee CT is offered chest and abdomen headings.
GV_PREFIX: str = """• GROUPING VOCABULARY (CT) — headings to use in BOTH findings sections, chosen from
                          the regions/organs this study actually covered (never a heading without content):
"""

GV_ITEMS: List[Tuple[str, str]] = [
    ('Chest',
     """                          – Chest: Lungs · Pleura · Mediastinum and hila · Heart and great vessels ·
                            Chest wall and bones
"""),
    ('Abdomen',
     """                          – Abdomen: Liver · Gallbladder and biliary tree · Pancreas · Spleen · Adrenal glands ·
                            Kidneys and ureters · Bowel · Peritoneum and free fluid · Vessels · Lymph nodes
"""),
    ('Pelvis',
     """                          – Pelvis: Urinary bladder · Pelvic organs (uterus and adnexa, or prostate and seminal
                            vesicles) · Rectosigmoid · Pelvic lymph nodes
"""),
    ('Brain',
     """                          – Brain: Cerebral parenchyma · Ventricular system and midline · Extra-axial spaces ·
                            Posterior fossa · Skull base and calvarium · Paranasal sinuses and mastoids · Orbits
"""),
    ('Paranasal sinuses',
     """                          – Paranasal sinuses: Maxillary sinuses · Ethmoid air cells · Frontal sinuses ·
                            Sphenoid sinus · Ostiomeatal complexes · Nasal cavity and turbinates ·
                            Nasal septum · Orbits · Skull base · Dentition
"""),
    ('Neck',
     """                          – Neck: Pharynx and larynx · Salivary glands · Thyroid · Cervical lymph nodes · Vessels
"""),
    ('Spine',
     """                          – Spine: Alignment · Vertebral bodies · Intervertebral discs · Spinal canal and foramina ·
                            Facet joints · Paraspinal soft tissues
"""),
    ('MSK',
     """                          – MSK: Bones · Joint and cartilage · Ligaments and tendons · Soft tissues
                          – A 'Musculoskeletal' or 'Soft tissues' heading may close any body-region study.
                        """),
]

GV_REGION_MAP: Dict[str, List[str]] = {'Chest': ['chest'], 'Abdomen': ['abdomen'], 'Pelvis': ['pelvis', 'prostate'], 'Brain': ['brain'], 'Paranasal sinuses': ['paranasal_sinuses'], 'Neck': ['head_neck', 'thyroid'], 'Spine': ['spine', 'spine_cervical', 'spine_thoracic', 'spine_lumbar'], 'MSK': ['shoulder', 'hip', 'knee', 'ankle_foot', 'wrist_hand', 'extremity', 'temporal_bone', 'dental_maxillofacial']}

#: The Persian / Finglish dictation lexicon, term by term.
LEX_PREFIX: str = """* Recognise Persian / Finglish CT terminology and map to correct radiologic English:
"""

LEX_ITEMS: List[Tuple[str, str]] = [
    ('Bronchiectasis',
     """                        – "برونشکتازی / bronshiektazi" → Bronchiectasis
"""),
    ('Ground-glass opacity (GGO)',
     """                        – "گراند گلس / grand glass" → Ground-glass opacity (GGO)
"""),
    ('Emphysema',
     """                        – "آمفیزم / amfizem" → Emphysema
"""),
    ('Concha bullosa',
     """                        – "کونکا بولوزا / concha boloza" → Concha bullosa
"""),
    ('Diverticulitis',
     """                        – "دیورتیکولایتیس / diverticolitis" → Diverticulitis
"""),
    ('Fat stranding',
     """                        – "استرندینگ چربی" → Fat stranding
"""),
    ('Hyperdense / Hypodense',
     """                        – "هایپردنس / هایپودنس" → Hyperdense / Hypodense
"""),
    ('Lymphadenopathy',
     """                        – "لنفادنوپاتی / lemfnodopaty" → Lymphadenopathy
"""),
    ('Pneumothorax',
     """                        – "پنوموتوراکس / pnomotoraks" → Pneumothorax
"""),
    ('Pleural effusion',
     """                        – "پلورال افیوژن / ploralafijon" → Pleural effusion
"""),
    ('Hydronephrosis',
     """                        – "هیدرونفروز / hidronefros" → Hydronephrosis
"""),
    ('Nephrolithiasis',
     """                        – "نفرولیتیازیس / sange kolyeh" → Nephrolithiasis
"""),
    ('Appendicitis',
     """                        – "آپاندیسیت / apandisit" → Appendicitis
"""),
    ('Pneumoperitoneum',
     """                        – "پنوموپریتونئوم" → Pneumoperitoneum
"""),
    ('Tenosynovitis',
     """                        – "تنوسینوویت" → Tenosynovitis
"""),
    ('Osteophytosis',
     """                        – "اکیپشوس" → Osteophytosis

                        """),
]

LEX_ALWAYS: List[str] = ['Hyperdense / Hypodense', 'Lymphadenopathy']

LEX_REGION_MAP: Dict[str, List[str]] = {'Bronchiectasis': ['chest'], 'Ground-glass opacity (GGO)': ['chest'], 'Emphysema': ['chest'], 'Pneumothorax': ['chest'], 'Pleural effusion': ['chest'], 'Concha bullosa': ['paranasal_sinuses'], 'Diverticulitis': ['abdomen', 'pelvis'], 'Fat stranding': ['abdomen', 'pelvis'], 'Appendicitis': ['abdomen'], 'Pneumoperitoneum': ['abdomen', 'pelvis'], 'Hydronephrosis': ['abdomen', 'pelvis'], 'Nephrolithiasis': ['abdomen', 'pelvis'], 'Tenosynovitis': ['shoulder', 'hip', 'knee', 'ankle_foot', 'wrist_hand', 'extremity'], 'Osteophytosis': ['shoulder', 'hip', 'knee', 'ankle_foot', 'wrist_hand', 'extremity', 'spine', 'spine_cervical', 'spine_thoracic', 'spine_lumbar']}

#: canonical region key -> block names. A region may need more than one block, and
#: brain needs two because the contrast state changes what may be said.
REGION_TO_BLOCKS: Dict[str, List[str]] = {
    'brain': ['BRAIN CT (NON-CONTRAST)', 'BRAIN CT WITH CONTRAST'],
    'chest': ['CHEST CT AND HRCT'],
    'head_neck': ['NECK CT'],
    'thyroid': ['NECK CT'],
    'paranasal_sinuses': ['PARANASAL SINUS CT'],
    'abdomen': ['ABDOMEN CT'],
    'pelvis': ['PELVIS CT'],
    'prostate': ['PELVIS CT'],
    'spine_cervical': ['CERVICAL SPINE CT'],
    'spine_thoracic': ['THORACIC SPINE CT'],
    'spine_lumbar': ['LUMBAR SPINE CT'],
    'spine': ['CERVICAL SPINE CT', 'THORACIC SPINE CT', 'LUMBAR SPINE CT'],
    'shoulder': ['MSK CT SHOULDER'],
    'hip': ['MSK CT HIP'],
    'knee': ['MSK CT KNEE'],
    'ankle_foot': ['MSK CT ANKLE AND FOOT'],
    'wrist_hand': ['MSK CT WRIST AND HAND'],
    'extremity': ['MSK CT SHOULDER', 'MSK CT HIP', 'MSK CT KNEE', 'MSK CT ANKLE AND FOOT', 'MSK CT WRIST AND HAND'],
}

#: blocks that answer to a COMBINATION of regions rather than any single one.
COMBO_BLOCKS: Dict[Tuple[str, ...], List[str]] = {
    ('abdomen', 'pelvis'): ['ABDOMINOPELVIC CT'],
}

#: blocks selected by an axis other than region (procedure, subtype).
AXIS_BLOCKS: Dict[str, List[str]] = {'vascular': ['CT ANGIOGRAPHY AORTA'], 'urography': ['CT UROGRAPHY AND CT KUB'], 'coronary': ['CORONARY CTA']}


def section_for(block_names) -> str:
    """The region section containing exactly these blocks, in the original order."""
    wanted = list(block_names or [])
    kept = [t for n, t in CT_BLOCKS if n in wanted]
    return SECTION_PREFIX + "".join(kept)


def full_section() -> str:
    """Every block — byte-identical to what the monolithic prompt carries today."""
    return SECTION_PREFIX + "".join(t for _n, t in CT_BLOCKS)


def _pick(items, prefix, regions, always=()):
    keep = [t for n, t in items if n in always or n in regions]
    return prefix + "".join(keep)


def gv_full() -> str:
    return GV_PREFIX + "".join(t for _n, t in GV_ITEMS)


def gv_for(regions) -> str:
    """Grouping headings for these regions. Empty selection -> everything, because a
    model told to use headings and given none would invent its own."""
    want = {n for n, rs in GV_REGION_MAP.items() if set(rs) & set(regions or [])}
    if not want:
        return gv_full()
    return _pick(GV_ITEMS, GV_PREFIX, want)


def lex_full() -> str:
    return LEX_PREFIX + "".join(t for _n, t in LEX_ITEMS)


def lex_for(regions) -> str:
    """Dictation terms for these regions, plus the always-relevant ones."""
    want = {n for n, rs in LEX_REGION_MAP.items() if set(rs) & set(regions or [])}
    if not want:
        return lex_full()
    return _pick(LEX_ITEMS, LEX_PREFIX, want, always=LEX_ALWAYS)
