# -*- coding: utf-8 -*-
"""Build the MRI region modules from the shared MRI prompt.

EXTRACTED, not invented: the normal-findings lines, the grouping-vocabulary headings
and the sequence lexicon all already exist in `build_report_system_prompt("MRI")`,
written by a radiologist for this project. This script pulls them out and re-shapes
them into the five fixed sections the template wants. The PATHOLOGY half comes from
`turbo_mri_authored.py` and is flagged for review there.

    headings   from GROUPING VOCABULARY (MRI)
    pathology  from turbo_mri_authored.MRI_PATHOLOGY        (needs review)
    normal     from the "RSNA-compliant normal findings per body region" blocks
    terms      the MRI sequence lexicon, plus the always-on Persian terms
    notes      from turbo_mri_authored.MRI_NOTES

Run:  .venv\\Scripts\\python.exe tools\\dev\\gen_turbo_mri_modules.py
"""
import io, os, re, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from modules.EchoMind.session_metadata import REGION_KEYS
from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
from modules.EchoMind.viewer_chat import turbo_regions as tr
from turbo_mri_authored import (MRI_HEADINGS, MRI_NORMAL_EXTRA, MRI_NOTES,
                                MRI_PATHOLOGY, MRI_TERMS)

PROMPT = build_report_system_prompt("MRI", "")
LINES = PROMPT.splitlines()

#: block header -> the canonical keys it feeds. A header may feed several keys, and a
#: key may draw on several headers (extremity takes all five MSK sub-blocks).
BLOCKS = {
    "BRAIN": ["brain"],
    "SPINE": ["spine", "spine_cervical", "spine_thoracic", "spine_lumbar"],
    "KNEE": ["knee", "extremity"],
    "SHOULDER": ["shoulder", "extremity"],
    "HIP": ["hip", "extremity"],
    "ANKLE / FOOT": ["ankle_foot", "extremity"],
    "WRIST / HAND": ["wrist_hand", "extremity"],
    "BREAST": ["breast"],
    "ABDOMEN": ["abdomen"],
    "PELVIS": ["pelvis"],
    "PROSTATE": ["prostate"],
    "HEAD AND NECK": ["head_neck", "thyroid"],
    "ORBIT": ["orbit"],
    "TEMPORAL BONES / INTERNAL AUDITORY CANALS": ["temporal_bone"],
}

#: Present in the prompt and deliberately NOT mapped to a region.
#: `MSK / MUSCULOSKELETAL` is a parent header whose content lives in its five
#: sub-blocks. `PITUITARY / SELLA` is a study SUBTYPE of a brain MRI, not a region -
#: folding it into `brain` would put 219 tokens of sella detail into every brain MRI,
#: which is the mistake `CORONARY CTA` under `chest` would have been on the CT side.
UNMAPPED = ("MSK / MUSCULOSKELETAL", "PITUITARY / SELLA")

TITLES = {
    "brain": "Brain", "spine": "Spine", "spine_cervical": "Cervical spine",
    "spine_thoracic": "Thoracic spine", "spine_lumbar": "Lumbar spine",
    "knee": "Knee", "shoulder": "Shoulder", "hip": "Hip",
    "ankle_foot": "Ankle and foot", "wrist_hand": "Wrist and hand",
    "extremity": "Extremity", "breast": "Breast", "abdomen": "Abdomen",
    "pelvis": "Pelvis", "prostate": "Prostate", "head_neck": "Neck",
    "thyroid": "Neck", "orbit": "Orbit", "temporal_bone": "Temporal bone",
}


def _span(start_pat, stop_pats):
    """Line range from the first match of start_pat to the first following stop."""
    lo = next(i for i, l in enumerate(LINES) if re.search(start_pat, l))
    for j in range(lo + 1, len(LINES)):
        if any(re.search(p, LINES[j]) for p in stop_pats):
            return lo, j
    return lo, len(LINES)


def _content_lines(raw):
    """Body lines of a block, continuations joined, rule scaffolding dropped.

    The SEX-SPECIFIC ANATOMY RULE is cut as a whole SPAN, not bullet by bullet.
    Dropping its bullets individually left their continuation lines behind, and
    they merged into the preceding content line. The rule itself is not lost - it
    lives in the shared RULES_NORMAL slot, stated once.
    """
    out, skipping = [], False
    for ln in raw:
        s = ln.strip()
        if "SEX-SPECIFIC ANATOMY RULE" in s:
            skipping = True
            continue
        if skipping:
            if s.startswith("Female pelvis") or s.startswith("Male pelvis"):
                skipping = False
            else:
                continue
        if not s or s.startswith("──") or s.startswith("═") or s.startswith("━"):
            continue
        if re.match(r"^[•►–—-]", s) or re.match(r"^\[?[A-Z]", s):
            out.append(re.sub(r"^[•►]\s*", "", s))
        elif out:
            out[-1] = out[-1].rstrip() + " " + s
    return [re.sub(r"\s+", " ", x).strip() for x in out if x.strip()]


# ── headings, from GROUPING VOCABULARY (MRI) ─────────────────────────────────
gv_lo, gv_hi = _span(r"GROUPING VOCABULARY \(MRI\)",
                     [r"Only mention specific MRI sequences"])
HEAD_SRC = {}
_cur = None
for ln in LINES[gv_lo:gv_hi]:
    s = ln.strip()
    m = re.match(r"^–\s*([A-Za-z /]+):\s*(.*)$", s)
    if m:
        _cur = m.group(1).strip()
        HEAD_SRC[_cur] = m.group(2).strip()
    elif _cur and s and not s.startswith("*"):
        HEAD_SRC[_cur] = (HEAD_SRC[_cur] + " " + s).strip()
HEAD_SRC = {k: re.sub(r"\s+", " ", v).strip(" ·") for k, v in HEAD_SRC.items()}

HEAD_FOR = {
    "brain": "Brain", "spine": "Spine", "spine_cervical": "Spine",
    "spine_thoracic": "Spine", "spine_lumbar": "Spine",
    "knee": "Knee", "shoulder": "Shoulder",
    "hip": "Hip / Ankle / Wrist", "ankle_foot": "Hip / Ankle / Wrist",
    "wrist_hand": "Hip / Ankle / Wrist", "breast": "Breast",
    "abdomen": "Abdomen / Pelvis", "pelvis": "Abdomen / Pelvis",
    "prostate": "Abdomen / Pelvis",
}

# ── the region blocks ────────────────────────────────────────────────────────
nf_lo, nf_hi = _span(r"RSNA-compliant normal findings per body region",
                     [r"^##\s", r"MRI Example"])
marks = []
for i in range(nf_lo, nf_hi):
    s = LINES[i].strip()
    m = re.match(r"^[–►]\s*([A-Z][A-Z /()0-9-]*?)\s*(?:\(|:)", s)
    if m:
        marks.append((i, m.group(1).strip()))
marks.append((nf_hi, "<end>"))

RAW = {}
for k in range(len(marks) - 1):
    (i, name), (j, _) = marks[k], marks[k + 1]
    RAW[name] = LINES[i + 1:j]

# ABDOMEN / PELVIS arrives as one block and has to be split at the bladder
if "ABDOMEN / PELVIS" in RAW:
    body = RAW.pop("ABDOMEN / PELVIS")
    cut = next((n for n, l in enumerate(body) if l.strip().startswith("Bladder")),
               len(body))
    RAW["ABDOMEN"] = body[:cut]
    RAW["PELVIS"] = body[cut:]

missing = [b for b in BLOCKS if b not in RAW]
if missing:
    raise SystemExit("blocks not found in the MRI prompt: %s\nfound: %s"
                     % (missing, sorted(RAW)))

NORMAL = {}
for block, keys in BLOCKS.items():
    for key in keys:
        NORMAL.setdefault(key, [])
        for line in _content_lines(RAW[block]):
            if line not in NORMAL[key]:
                NORMAL[key].append(line)


def _resolve_spine(key, lines):
    """[Cervical] / [Lumbar] markers: keep the one that applies, drop the other."""
    keep = {"spine_cervical": "[Cervical]", "spine_lumbar": "[Lumbar]"}.get(key)
    out = []
    for l in lines:
        m = re.match(r"^\[(Cervical|Lumbar)\]\s*(.*)$", l)
        if not m:
            out.append(l)
        elif key == "spine":
            out.append(l)                       # the all-levels package keeps both
        elif keep and l.startswith(keep):
            out.append(m.group(2).strip())
    return out


for key in ("spine", "spine_cervical", "spine_thoracic", "spine_lumbar"):
    NORMAL[key] = _resolve_spine(key, NORMAL[key])

for key, extra in MRI_NORMAL_EXTRA.items():
    for line in extra:
        if line not in NORMAL.get(key, []):
            NORMAL.setdefault(key, []).append(line)

# ── terms: the MRI sequence lexicon plus the always-on Persian terms ─────────
seq_lo, seq_hi = _span(r"Recognize MRI sequences from Persian or Finglish",
                       [r"^\s*$", r"═══"])
SEQ = []
for ln in LINES[seq_lo + 1:seq_hi + 2]:
    s = ln.strip().lstrip("–").strip()
    if not s or s.startswith("*") or set(s) <= set("═━─ "):
        continue
    SEQ.extend(x.strip(" .") for x in s.split(",")
               if x.strip(" .") and not set(x.strip()) <= set("═━─"))

#: The CT always-on lexicon is NOT reused: it carries an attenuation term
#: (hyperdense / hypodense) that is wrong on MRI. The MRI list is authored
#: in turbo_mri_authored.py and is flagged for review there.
ALWAYS = list(MRI_TERMS)


SEQ_LINE = "sequences named in dictation: " + ", ".join(SEQ) if SEQ else ""

# ── assemble ─────────────────────────────────────────────────────────────────
modules = {}
for key in sorted(NORMAL, key=lambda k: list(TITLES).index(k)):
    if key not in REGION_KEYS:
        raise SystemExit("%r is not a canonical region key" % key)
    terms = ([SEQ_LINE] if SEQ_LINE else []) + list(ALWAYS)
    modules[key] = {
        "title": TITLES[key],
        "headings": HEAD_SRC.get(HEAD_FOR.get(key, ""), "") or MRI_HEADINGS.get(key, ""),
        "pathology": MRI_PATHOLOGY.get(key, []),
        "normal": NORMAL[key],
        "terms": terms,
        "notes": MRI_NOTES.get(key, []),
    }

print("%d MRI region modules built" % len(modules))
for k, m in modules.items():
    print("  %-18s %-16s head=%-3s path=%2d normal=%2d terms=%2d notes=%d"
          % (k, m["title"], "yes" if m["headings"] else "NO", len(m["pathology"]),
             len(m["normal"]), len(m["terms"]), len(m["notes"])))

nohead = [k for k, m in modules.items() if not m["headings"]]
nopath = [k for k, m in modules.items() if not m["pathology"]]
print("\nno headings:", nohead or "none")
print("no pathology:", nopath or "none")
print("sequence lexicon:", SEQ)

out = io.StringIO()
w = out.write
w('''"""MRI region modules for the Turbo prompt template.

GENERATED by `tools/dev/gen_turbo_mri_modules.py`. Do not hand-edit: re-run it.

The normal-findings lines, the headings and the sequence lexicon are EXTRACTED from the
shared MRI prompt, where a radiologist wrote them for this project. The pathology rules
come from `tools/dev/turbo_mri_authored.py`, are compiled from the published literature,
and are ⚠️ NOT YET CLINICALLY REVIEWED.

    headings   the organ order for this region, one line
    pathology  the descriptors worth preserving here and the systems that apply here
    normal     the normal-findings reference, one line per structure
    terms      the MRI sequence lexicon plus the always-on Persian terms
    notes      region-specific traps

MRI's distinctive requirement: signal has no meaning without the sequence that shows it.
The pathology rules ask that the physician's sequence attribution survive rewriting.

NOT COVERED: cardiac MRI, chest MRI and fetal MRI. The shared MRI prompt has no block
for any of them, and none was invented here. A study gated to one of those regions
falls back to the full shared prompt, which is correct.
"""

from __future__ import annotations

from typing import Dict, List

MRI_MODULES: Dict[str, dict] = {
''')
for r, m in modules.items():
    w("    %r: {\n" % r)
    w("        'title': %r,\n" % m["title"])
    w("        'headings': %r,\n" % m["headings"])
    for sec in ("pathology", "normal"):
        w("        %r: [\n" % sec)
        for line in m[sec]:
            w("            %r,\n" % line)
        w("        ],\n")
    w("        'terms': %r,\n" % m["terms"])
    w("        'notes': %r,\n" % m["notes"])
    w("    },\n")
w("}\n")

dst = os.path.join(ROOT, "modules", "EchoMind", "viewer_chat", "turbo_mri_modules.py")
io.open(dst, "w", encoding="utf-8", newline="\n").write(out.getvalue())
print("\nwrote %s  %d bytes" % (dst, os.path.getsize(dst)))

import importlib
mod = importlib.import_module("modules.EchoMind.viewer_chat.turbo_mri_modules")
importlib.reload(mod)
assert len(mod.MRI_MODULES) == len(modules), "round trip lost a module"
for k, m in modules.items():
    assert mod.MRI_MODULES[k]["normal"] == m["normal"], "round trip changed %s" % k
print("import verified:", len(mod.MRI_MODULES), "modules")
