"""Fill the prompt template's REGION slot for every canonical CT region.

GENERATED from content that already exists — the grouping vocabulary supplies the
headings, the RSNA normal-findings blocks supply the reference lines, and the Persian
lexicon supplies the dictation terms. Nothing clinical is invented here: this is a
re-shaping of text a radiologist wrote into the four fixed sections the template wants.

    headings   one line, the organ order for this region
    pathology  the region's pathological-findings rules and the classification
               systems that apply here - and only here
    normal     the normal-findings reference, one line per structure
    terms      the dictation terms that belong to this region
    notes      region-specific traps; authored, and empty for most

Run:  .venv\\Scripts\\python.exe tools\\dev\\gen_turbo_modules.py
"""
import io, os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.EchoMind.viewer_chat import turbo_regions as tr
from modules.EchoMind.viewer_chat import turbo_regions_extra as tx
from modules.EchoMind.session_metadata import REGION_KEYS
from turbo_region_authored import NORMAL_EXTRA, PATHOLOGY_RESEARCHED

BLOCKS = dict(tr.CT_BLOCKS)
BLOCKS.update({n: t for n, t in tx.CT_EXTRA_BLOCKS})
GV = dict(tr.GV_ITEMS)
GV.update({n: t for n, t in tx.EXTRA_GV_ITEMS})

REGION_TO_BLOCKS = dict(tr.REGION_TO_BLOCKS)
for k, v in tx.EXTRA_REGION_TO_BLOCKS.items():
    REGION_TO_BLOCKS.setdefault(k, []).extend(v)

GV_FOR_REGION = {}
for entry, regions in tr.GV_REGION_MAP.items():
    for r in regions:
        GV_FOR_REGION.setdefault(r, []).append(entry)
for region, entries in tx.EXTRA_GV_REGION_MAP.items():
    GV_FOR_REGION.setdefault(region, []).extend(entries)

#: display title per canonical region
TITLES = {
    "brain": "Brain", "chest": "Chest", "head_neck": "Neck", "thyroid": "Neck",
    "paranasal_sinuses": "Paranasal sinuses", "abdomen": "Abdomen",
    "pelvis": "Pelvis", "prostate": "Pelvis",
    "spine_cervical": "Cervical spine", "spine_thoracic": "Thoracic spine",
    "spine_lumbar": "Lumbar spine", "spine": "Spine",
    "shoulder": "Shoulder", "hip": "Hip", "knee": "Knee",
    "ankle_foot": "Ankle and foot", "wrist_hand": "Wrist and hand",
    "extremity": "Extremity", "temporal_bone": "Temporal bone", "orbit": "Orbit",
    "dental_maxillofacial": "Maxillofacial",
}

#: authored region traps. Deliberately sparse — a note earns its place by describing a
#: mistake that has actually been made, not by restating the anatomy above it.
NOTES = {
    "pelvis": ["The inguinal region belongs to the pelvic section, not the abdomen."],
    "abdomen": ["An abdominal study that names the kidneys and urinary tract in its "
                "booking must give them explicit coverage even when normal."],
    "chest": ["Report the visualised upper abdominal organs only if the study covered "
              "them."],
    "spine": ["State the levels examined. A spine report that does not say which "
              "levels were covered cannot be acted on."],
    "temporal_bone": ["Say which side. A temporal bone study is almost never bilateral "
                      "in its indication."],
    "brain": ["Do not describe enhancement on a non-contrast study, even to deny it."],
}

#: Region-specific pathological-findings rules, gated in with the region.
#:
#: SOURCE. Every line below is a re-assignment of a bullet the shared prompt already
#: sends to every CT study - the 15 CT-SPECIFIC MEASUREMENT AND CLASSIFICATION RULES
#: and the STANDARDIZED SYSTEMS list. Nothing clinical is invented.
#:
#: REGISTER. The source bullets are imperatives to PRODUCE: "Brain haemorrhage: specify
#: type, location, volume (ABC/2 method or mL), density (HU)...". The physician dictates;
#: he cannot dictate an ABC/2 volume he did not measure, and source fidelity forbids the
#: model inventing one. So each bullet is recast as what it can only safely have meant:
#: preserve these descriptors when he gives them. Same protection, no contradiction.
#:
#: EMPTY IS CORRECT. A region with no entry contributes nothing - which is strictly
#: better than today, where a knee CT receives all 15 bullets and 0 of them apply.
#: The MSK regions have real classification systems (Salter-Harris, Gustilo,
#: Kellgren-Lawrence, Outerbridge) that no radiologist has written into this project
#: yet; they stay empty rather than being invented here.
PATHOLOGY = {
    "brain": [
        "Intracranial haemorrhage - preserve the type he named (EDH, SDH, SAH, IPH), "
        "the location, and any volume, attenuation, mass effect or midline shift he gave.",
        "Infarction - preserve the territory he named (MCA, ACA, PCA) and the side, plus "
        "any ASPECTS score he dictated. Loss of grey-white differentiation and sulcal "
        "effacement are his observations to keep, never yours to add.",
    ],
    "chest": [
        "Pulmonary nodule - preserve size (longest dimension, mm), lobe and segment, "
        "density (solid, part-solid, ground-glass, calcified) and margin (smooth, "
        "irregular, spiculated) as dictated.",
        "Fleischner and Lung-RADS are the systems for pulmonary nodules. Use their "
        "wording only when what he dictated meets the criteria, and never assign a "
        "category he did not state.",
        "Pleural effusion - preserve laterality, his size estimate, loculation, and any "
        "associated atelectasis.",
        "Pulmonary embolism - preserve the vessel level he named (main, lobar, "
        "segmental, subsegmental) and any RV:LV ratio or right-heart strain sign.",
        "Thoracic aorta - preserve the maximal diameter and the level he measured it at "
        "(sinus, ascending, arch, descending), with mural thrombus, intramural "
        "haematoma, or a dissection flap and its Stanford class if he gave one.",
        "Lymph node - preserve short-axis diameter, location, necrosis and "
        "calcification. Mediastinal and hilar nodes are reported against a 1 cm "
        "short-axis threshold.",
    ],
    "abdomen": [
        "Liver lesion - preserve the segment (I-VIII), the dimensions, the enhancement "
        "pattern he described (arterial enhancement, wash-out, peripheral rim) and any "
        "satellite lesions.",
        "LI-RADS applies to a liver observation in a patient at risk for HCC, and "
        "Bosniak to a renal cyst. Use either only when the dictated findings meet its "
        "criteria; never assign a category he did not state.",
        "Biliary tree - preserve the duct calibre he gave and, if dilated, the level of "
        "obstruction he named.",
        "Pancreatitis - preserve any Revised Atlanta severity, Balthazar grade, necrosis "
        "percentage or duct calibre he dictated.",
        "Appendix - preserve diameter, wall thickness, periappendiceal fat stranding, "
        "and any abscess or sign of perforation he described.",
        "Bowel obstruction - preserve which segment is dilated, the transition point, "
        "the degree he stated (partial or complete), and any closed-loop sign.",
        "Urinary calculus - preserve size, location along the tract (calyx, pelvis, "
        "proximal / mid / distal ureter, VUJ), attenuation, and the grade of "
        "hydronephrosis he gave.",
        "Abdominal aorta - preserve the maximal diameter, mural thrombus, and any "
        "dissection flap with its Stanford class as dictated.",
        "Lymph node - preserve short-axis diameter, location, necrosis and calcification "
        "as dictated.",
    ],
    "pelvis": [
        "Urinary calculus at the vesicoureteric junction - preserve size, side, "
        "attenuation, and the grade of hydronephrosis he gave.",
        "Lymph node - preserve short-axis diameter, location, necrosis and calcification "
        "as dictated.",
        "O-RADS applies to an adnexal lesion and PI-RADS to prostate MRI. Neither is "
        "assigned on a CT unless he names it.",
    ],
    "head_neck": [
        "TI-RADS applies to a thyroid nodule. Use it only when the dictated features "
        "meet its criteria; never assign a category he did not state.",
        "Cervical lymph node - preserve short-axis diameter, the level he named, and any "
        "necrosis or extranodal extension.",
    ],
    "spine": [
        "Vertebral fracture - preserve the level, any AO/Magerl class he gave, the height "
        "loss, burst versus compression as he characterised it, canal compromise and "
        "retropulsion.",
        "Disc herniation - preserve the level, the direction he named (central, "
        "paracentral, foraminal, far lateral), the size, and the nerve root or thecal "
        "sac he said was compressed.",
        "Use accepted ACR/NASS nomenclature for disc disease - bulge, protrusion, "
        "extrusion, sequestration - to standardise his wording, never to reclassify what "
        "he described.",
    ],
}
PATHOLOGY["prostate"] = PATHOLOGY["pelvis"]
PATHOLOGY["thyroid"] = PATHOLOGY["head_neck"]
#: the researched regions - separate file, separate provenance, needs review
for _r, _v in PATHOLOGY_RESEARCHED.items():
    if PATHOLOGY.get(_r):
        raise SystemExit("researched content would overwrite authored: %s" % _r)
    PATHOLOGY[_r] = _v
for _lvl in ("spine_cervical", "spine_thoracic", "spine_lumbar"):
    PATHOLOGY[_lvl] = PATHOLOGY["spine"]


def strip_bullets(block_text):
    """The block's bullets, de-indented, as plain sentences."""
    out = []
    for ln in block_text.split("\n"):
        s = ln.strip()
        if not s.startswith("•"):
            continue
        s = s.lstrip("• ").strip()
        # drop a nested sub-rule heading such as the sex-specific banner
        if s.startswith("──") or s.endswith("──"):
            continue
        out.append(s)
    return out


def heading_line(entries):
    """The grouping entry, collapsed to one line of organ names."""
    parts = []
    for e in entries:
        raw = GV.get(e, "")
        body = raw.split(":", 1)[1] if ":" in raw else raw
        body = " ".join(x.strip() for x in body.split("\n") if x.strip())
        body = re.sub(r"\s+", " ", body).strip()
        if body and body not in parts:
            parts.append(body)
    return " · ".join(parts)


def terms_for(region):
    out = []
    for name, text in tr.LEX_ITEMS:
        regions = tr.LEX_REGION_MAP.get(name)
        if name in tr.LEX_ALWAYS or (regions and region in regions):
            m = re.search(r"–\s*\"(.+?)\"\s*→\s*(.+?)\s*$", text.strip())
            if m:
                fa = m.group(1).split("/")[0].strip()
                out.append(f"{fa} → {m.group(2).strip().lower()}")
    return out


modules = {}
for region in REGION_KEYS:
    blocks = REGION_TO_BLOCKS.get(region) or []
    if not blocks:
        continue
    normal = []
    for b in blocks:
        for line in strip_bullets(BLOCKS.get(b, "")):
            if line not in normal:
                normal.append(line)
    for line in NORMAL_EXTRA.get(region, []):
        if line not in normal:
            normal.append(line)
    if not normal:
        continue
    modules[region] = {
        "title": TITLES.get(region, region.replace("_", " ").title()),
        "headings": heading_line(GV_FOR_REGION.get(region, [])),
        "pathology": PATHOLOGY.get(region, []),
        "normal": normal,
        "terms": terms_for(region),
        "notes": NOTES.get(region, []),
    }

print(f"{len(modules)} region modules built")
for r, m in modules.items():
    print(f"  {r:22} {m['title']:18} headings={'yes' if m['headings'] else 'NO':3} "
          f"path={len(m['pathology']):2} normal={len(m['normal']):2} "
          f"terms={len(m['terms']):2} notes={len(m['notes'])}")

missing_head = [r for r, m in modules.items() if not m["headings"]]
print("\nregions with no grouping headings:", missing_head or "none")

out = io.StringIO()
w = out.write
w('''"""Region modules for the Turbo prompt template — the REGION slot, filled.

GENERATED by `tools/dev/gen_turbo_modules.py`. Do not hand-edit: re-run the generator.
The clinical text comes from the blocks a radiologist wrote, re-shaped into the four
fixed sections the template expects.

    headings   the organ order for this region, one line
    pathology  the pathological-findings rules and classification systems that
               apply to this region - a brain CT is not told about Fleischner
    normal     the normal-findings reference, one line per structure
    terms      the dictation terms that belong to this region, plus the always-on ones
    notes      region-specific traps

A module is selected by canonical region key — the same vocabulary the gate emits, so
what the physician sees on the metadata card is what selects the content.
"""

from __future__ import annotations

from typing import Dict, List

REGION_MODULES: Dict[str, dict] = {
''')
for r, m in modules.items():
    w(f"    {r!r}: {{\n")
    w(f"        'title': {m['title']!r},\n")
    w(f"        'headings': {m['headings']!r},\n")
    w("        'pathology': [\n")
    for line in m["pathology"]:
        w(f"            {line!r},\n")
    w("        ],\n")
    w("        'normal': [\n")
    for line in m["normal"]:
        w(f"            {line!r},\n")
    w("        ],\n")
    w(f"        'terms': {m['terms']!r},\n")
    w(f"        'notes': {m['notes']!r},\n")
    w("    },\n")
w("}\n\n\n")
w('''def module_for(region: str):
    """The module for a canonical region key, or None."""
    return REGION_MODULES.get(str(region or "").strip().lower())


def modules_for(regions) -> List[dict]:
    """Modules for these regions, de-duplicated by title so `pelvis` and `prostate`
    do not both emit the pelvis package."""
    out, seen = [], set()
    for r in regions or []:
        m = module_for(r)
        if m and m["title"] not in seen:
            seen.add(m["title"])
            out.append(m)
    return out
''')

dst = os.path.join(ROOT, "modules", "EchoMind", "viewer_chat", "turbo_region_modules.py")
io.open(dst, "w", encoding="utf-8", newline="\n").write(out.getvalue())
print(f"\nwrote {dst}  {os.path.getsize(dst)} bytes")

import importlib
m = importlib.import_module("modules.EchoMind.viewer_chat.turbo_region_modules")
importlib.reload(m)
assert len(m.REGION_MODULES) == len(modules)
print("import verified:", len(m.REGION_MODULES), "modules")
