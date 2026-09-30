"""CT region blocks that the monolithic prompt never had.

WRITTEN, NOT GENERATED — and kept in a separate module for exactly that reason.
`turbo_regions.py` is produced by `tools/dev/regen_turbo_regions.py` and must never be
hand-edited, or the byte-for-byte reassembly proof stops meaning anything. Authored
content lives here so regeneration can never clobber it and the proof stays intact.

WHY THESE THREE. Measured against the 1405 tariff, they are the CT regions with real
bookable volume and no coverage at all in the prompt:

    temporal bone / inner ear       11 service codes
    orbit                            9 service codes
    maxillofacial / dental / TMJ     8 service codes

Until now a temporal bone CT was sent nineteen region blocks, none of which described a
temporal bone. The model had to invent the structure list — which is precisely the
"generate the normal findings" task the prompt asks of it, with no guidance for the
anatomy actually imaged.

⚠️ CLINICAL REVIEW REQUIRED. These follow the form, depth and vocabulary of the
nineteen blocks a radiologist already wrote, and the structure lists are conventional
for each examination — but they have NOT been reviewed by a radiologist yet. They are
the format-correct first draft that review should start from, not finished content.

FORMAT IS LOAD-BEARING. 24 spaces before the `–` heading, 28 before each `•`, one blank
line at the end. The composer splices these into the same section as the generated
blocks, and a test asserts the shapes match — a block with the wrong indentation reads
as a different level of the prompt's outline.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

_H = " " * 24
_B = " " * 28


def _block(title: str, bullets: List[str]) -> str:
    return (f"{_H}– {title}:\n"
            + "".join(f"{_B}• {b}\n" for b in bullets)
            + "\n")


CT_EXTRA_BLOCKS: List[Tuple[str, str]] = [
    ("TEMPORAL BONE CT", _block("TEMPORAL BONE CT", [
        "External auditory canal: patent bilaterally; no stenosis, exostosis, or soft tissue lesion.",
        "Tympanic membrane and middle ear cavity: normally aerated; no soft tissue density or effusion.",
        "Ossicular chain: malleus, incus, and stapes are intact and normally articulated; no erosion, dislocation, or fixation.",
        "Scutum and Prussak space: intact; no blunting or erosion to suggest cholesteatoma.",
        "Mastoid air cells: normally pneumatised and clear bilaterally; no opacification or septal erosion.",
        "Facial nerve canal: normal course and calibre in its labyrinthine, tympanic, and mastoid segments; no dehiscence.",
        "Inner ear: cochlea, vestibule, and all three semicircular canals are normally formed and patent; no malformation, ossification, or dehiscence of the superior semicircular canal.",
        "Vestibular aqueduct: normal in calibre; not enlarged.",
        "Internal auditory canal: normal in width and symmetric bilaterally; no widening or erosion.",
        "Petrous apex: normally aerated or marrow-containing; no expansile lesion or opacification.",
        "Jugular foramen and carotid canal: normal in size and cortical margins; no dehiscence.",
        "Temporomandibular joint (visualised): normal osseous contours.",
        "No fracture, and no lytic or sclerotic osseous lesion of the temporal bone.",
    ])),

    ("ORBIT CT", _block("ORBIT CT", [
        "Globes: normal in size, shape, and position bilaterally; no rupture, luxation, or intraocular foreign body.",
        "Anterior and posterior chambers: normal in configuration; no haemorrhage or lens dislocation.",
        "Optic nerve–sheath complexes: normal in calibre and course bilaterally; no thickening, tortuosity, or perineural fluid.",
        "Extraocular muscles: normal in bulk and attenuation bilaterally; no enlargement of the muscle bellies and no tendinous involvement.",
        "Intraconal fat: normal attenuation; no mass, stranding, or collection.",
        "Extraconal spaces: unremarkable bilaterally; no subperiosteal collection or mass.",
        "Lacrimal glands: normal in size and symmetric; no enlargement or mass.",
        "Orbital walls: intact; no fracture, no blow-out defect, and no bony erosion or hyperostosis.",
        "Orbital apex and superior orbital fissure: patent; no soft tissue lesion.",
        "Visualised paranasal sinuses: clear, with no sinus disease extending into the orbit.",
        "Preseptal soft tissues: normal thickness; no cellulitis or collection.",
        "No orbital emphysema and no retrobulbar haemorrhage.",
    ])),

    ("MAXILLOFACIAL AND DENTAL CT", _block("MAXILLOFACIAL AND DENTAL CT", [
        "Facial buttresses: nasomaxillary, zygomaticomaxillary, and pterygomaxillary buttresses are intact; no Le Fort pattern fracture.",
        "Maxilla: normal cortical margins and alveolar ridge; no fracture, cyst, or lytic lesion.",
        "Mandible: normal in contour and cortical integrity throughout the symphysis, body, angle, ramus, and condyles; no fracture or lytic lesion.",
        "Zygomatic arches and orbital rims: intact and symmetric bilaterally.",
        "Nasal bones and nasal septum: intact; septum midline without deviation or fracture.",
        "Temporomandibular joints: condyles normally positioned within the glenoid fossae bilaterally; joint spaces preserved; no erosion, flattening, sclerosis, or osteophyte.",
        "Dentition: no periapical lucency, no retained root, and no impacted tooth requiring comment on this examination.",
        "Alveolar bone: normal height and trabecular pattern; no periodontal bone loss beyond that expected for age.",
        "Maxillary sinuses (visualised): clear, with no odontogenic mucosal disease or oro-antral communication.",
        "Facial soft tissues: normal; no swelling, collection, or radio-opaque foreign body.",
        "No osseous lesion, sequestrum, or periosteal reaction to suggest osteomyelitis.",
    ])),
]

#: canonical region key -> extra block names. Kept here beside the content so adding a
#: region is one edit in one file.
EXTRA_REGION_TO_BLOCKS: Dict[str, List[str]] = {
    "temporal_bone": ["TEMPORAL BONE CT"],
    "orbit": ["ORBIT CT"],
    "dental_maxillofacial": ["MAXILLOFACIAL AND DENTAL CT"],
}


# ── grouping-vocabulary headings for the same three regions ──────────────────
#
# An inconsistency introduced when the three normal-findings blocks were added and the
# GROUPING VOCABULARY was not: the prompt tells the model to "use the organ/region
# groupings the MODALITY RULES below already name for this study — do not invent a
# different vocabulary", and for a temporal bone CT it named none. So the model was
# handed a structure list and simultaneously told to head it with vocabulary that did
# not cover it.
#
# 26 spaces before the `–`, 28 for a continuation line, matching the eight generated
# entries exactly.

_GH = " " * 26

EXTRA_GV_ITEMS: List[Tuple[str, str]] = [
    ("Temporal bone",
     f"{_GH}– Temporal bone: External auditory canal · Middle ear and ossicles · "
     f"Mastoid air cells ·\n{_GH}  Inner ear and IAC · Facial nerve canal · "
     f"Petrous apex\n"),
    ("Orbit",
     f"{_GH}– Orbit: Globes · Optic nerve–sheath complexes · Extraocular muscles ·\n"
     f"{_GH}  Intraconal and extraconal fat · Lacrimal glands · Orbital walls\n"),
    ("Maxillofacial",
     f"{_GH}– Maxillofacial: Facial buttresses · Maxilla · Mandible · "
     f"Zygomatic arches ·\n{_GH}  Temporomandibular joints · Dentition · "
     f"Facial soft tissues\n"),
]

#: canonical region key -> extra grouping entries
EXTRA_GV_REGION_MAP: Dict[str, List[str]] = {
    "temporal_bone": ["Temporal bone"],
    "orbit": ["Orbit"],
    "dental_maxillofacial": ["Maxillofacial"],
}


def extra_gv_text(name: str) -> str:
    """Verbatim text for an authored grouping entry, or "" when it is not one of ours."""
    for n, t in EXTRA_GV_ITEMS:
        if n == name:
            return t
    return ""


def extra_block_text(name: str) -> str:
    """Verbatim text for an authored block, or "" when it is not one of ours."""
    for n, t in CT_EXTRA_BLOCKS:
        if n == name:
            return t
    return ""
