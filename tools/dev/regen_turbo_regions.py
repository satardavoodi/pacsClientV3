"""Generate turbo_regions.py by lifting the CT region blocks out of the LIVE prompt.

Verbatim, and generated rather than retyped: a hand copy of 19 clinical blocks is a
transcription error waiting to happen, and the whole point of this step is that it is
provably lossless.
"""
import ast, io, os, re, sys, typing
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
#: this script lives in tools/dev/, so the project root is two levels up
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", ".."))
REPORTER = os.path.join(ROOT, "modules", "EchoMind", "viewer_chat", "openai_reporter.py")

src = io.open(REPORTER, encoding="utf-8").read()
lines = src.split("\n")
node = next(n for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name == "build_report_system_prompt")
ns = {"_to_str": lambda x: "" if x is None else str(x),
      "Optional": typing.Optional, "Dict": dict, "Any": object}
exec(compile("\n".join(lines[node.lineno - 1:node.end_lineno]), REPORTER, "exec"), ns)
P = ns["build_report_system_prompt"]("CT", "")

START = "* RSNA-compliant normal findings per CT body region:"
i = P.find(START)
assert i >= 0, "region section start marker not found"
j = P.find("OUTPUT FORMAT (STRICT)", i)
assert j > i, "region section end marker not found"
# back up to the start of the ━ rule that precedes OUTPUT FORMAT
k = P.rfind("\n", i, j)
while k > i and not P[k + 1:j].lstrip().startswith("━"):
    k2 = P.rfind("\n", i, k)
    if k2 <= i:
        break
    k = k2
SECTION = P[i:k + 1]
print(f"section span: {len(SECTION)} chars, lines {P[:i].count(chr(10))+1}"
      f"-{P[:k].count(chr(10))+1}")

# split on the "– NAME:" block heads, keeping everything verbatim
heads = list(re.finditer(r"^[ \t]*–[ \t]+([A-Z][A-Z0-9 /()\-]{3,}?)[ \t]*:", SECTION, re.M))
assert heads, "no region blocks found"
PREFIX = SECTION[:heads[0].start()]
blocks = []
for a, b in zip(heads, heads[1:] + [None]):
    name = re.sub(r"\s+", " ", a.group(1)).strip()
    text = SECTION[a.start(): (b.start() if b else len(SECTION))]
    blocks.append((name, text))
SUFFIX = ""
assert PREFIX + "".join(t for _n, t in blocks) + SUFFIX == SECTION, "reassembly mismatch"
print(f"{len(blocks)} blocks, reassembly verified")

#: canonical region key -> the CT block names that serve it
#: Keys MUST come from session_metadata.REGION_KEYS — that is the vocabulary the gate
#: emits, and a key that is not in it can never be selected. `heart` and `neck` were
#: wrong here on the first pass; the canonical spellings are below.
MAP = {
    "brain": ["BRAIN CT (NON-CONTRAST)", "BRAIN CT WITH CONTRAST"],
    "chest": ["CHEST CT AND HRCT"],
    "head_neck": ["NECK CT"],
    "thyroid": ["NECK CT"],
    "paranasal_sinuses": ["PARANASAL SINUS CT"],
    "abdomen": ["ABDOMEN CT"],
    "pelvis": ["PELVIS CT"],
    "prostate": ["PELVIS CT"],
    "spine_cervical": ["CERVICAL SPINE CT"],
    "spine_thoracic": ["THORACIC SPINE CT"],
    "spine_lumbar": ["LUMBAR SPINE CT"],
    # A bare `spine` is the conservative PARENT: send all three levels rather than
    # guess which one, because guessing deletes the level that was actually imaged.
    "spine": ["CERVICAL SPINE CT", "THORACIC SPINE CT", "LUMBAR SPINE CT"],
    "shoulder": ["MSK CT SHOULDER"],
    "hip": ["MSK CT HIP"],
    "knee": ["MSK CT KNEE"],
    "ankle_foot": ["MSK CT ANKLE AND FOOT"],
    "wrist_hand": ["MSK CT WRIST AND HAND"],
    "extremity": ["MSK CT SHOULDER", "MSK CT HIP", "MSK CT KNEE",
                  "MSK CT ANKLE AND FOOT", "MSK CT WRIST AND HAND"],
}
#: blocks that answer to a COMBINATION rather than one region
COMBO = {("abdomen", "pelvis"): ["ABDOMINOPELVIC CT"]}
#: Blocks selected by an axis OTHER than region. A coronary CTA is a study type, not a
#: property of the chest — riding it on every chest CT would put 310 tokens of coronary
#: reporting rules into a routine chest study.
AXIS = {
    "vascular": ["CT ANGIOGRAPHY AORTA"],
    "urography": ["CT UROGRAPHY AND CT KUB"],
    "coronary": ["CORONARY CTA"],
}

names = [n for n, _t in blocks]
unmapped = [n for n in names
            if n not in {x for v in MAP.values() for x in v}
            and n not in {x for v in COMBO.values() for x in v}
            and n not in {x for v in AXIS.values() for x in v}]
print("unmapped blocks:", unmapped or "none")

# ═══ the OTHER two region-specific spans in the CT prompt ═══════════════════
#
# GROUPING VOCABULARY — eight region heading-sets, and the prompt tells the model to
# use "the organ/region groupings the MODALITY RULES below already name for this
# study". On a knee CT it names chest, abdomen, pelvis, brain and sinuses too.
#
# PERSIAN LEXICON — sixteen dictation terms. "Appendicitis" and "Hydronephrosis" are
# not useful on a temporal bone CT, and "Concha bullosa" is not useful on a knee.

GV_START = "• GROUPING VOCABULARY (CT)"
GV_END = "• Exclude any anatomical"
gi, gj = P.find(GV_START), P.find(GV_END)
assert gi >= 0 and gj > gi, "grouping vocabulary markers not found"
GV = P[gi:gj]
gheads = list(re.finditer(r"^\s*–\s+([A-Z][A-Za-z ]+?):", GV, re.M))
GV_PREFIX = GV[:gheads[0].start()]
gv_items = []
for a, b in zip(gheads, gheads[1:] + [None]):
    gv_items.append((a.group(1).strip(),
                     GV[a.start():(b.start() if b else len(GV))]))
assert GV_PREFIX + "".join(x for _n, x in gv_items) == GV, "GV reassembly mismatch"
print(f"grouping vocabulary: {len(gv_items)} entries, reassembly verified")

LEX_START = "* Recognise Persian"
li = P.find(LEX_START)
lj = P.find("━", li)
assert li >= 0 and lj > li, "lexicon markers not found"
LEX = P[li:lj]
lheads = list(re.finditer(r"^\s*–\s+\".*$", LEX, re.M))
LEX_PREFIX = LEX[:lheads[0].start()] if lheads else LEX
lex_items = []
for a, b in zip(lheads, lheads[1:] + [None]):
    seg = LEX[a.start():(b.start() if b else len(LEX))]
    eng = seg.split("→")[-1].strip().split("\n")[0].strip()
    lex_items.append((eng, seg))
assert LEX_PREFIX + "".join(x for _n, x in lex_items) == LEX, "lexicon reassembly mismatch"
print(f"persian lexicon: {len(lex_items)} terms, reassembly verified")

#: grouping-vocabulary entry -> canonical regions it serves
GV_MAP = {
    "Chest": ["chest"],
    "Abdomen": ["abdomen"],
    "Pelvis": ["pelvis", "prostate"],
    "Brain": ["brain"],
    "Paranasal sinuses": ["paranasal_sinuses"],
    "Neck": ["head_neck", "thyroid"],
    "Spine": ["spine", "spine_cervical", "spine_thoracic", "spine_lumbar"],
    "MSK": ["shoulder", "hip", "knee", "ankle_foot", "wrist_hand", "extremity",
            "temporal_bone", "dental_maxillofacial"],
}
#: lexicon term -> regions. ALWAYS means "keep it whatever the region is": these two
#: are general CT vocabulary, not anatomy-specific.
LEX_ALWAYS = ["Hyperdense / Hypodense", "Lymphadenopathy"]
LEX_MAP = {
    "Bronchiectasis": ["chest"],
    "Ground-glass opacity (GGO)": ["chest"],
    "Emphysema": ["chest"],
    "Pneumothorax": ["chest"],
    "Pleural effusion": ["chest"],
    "Concha bullosa": ["paranasal_sinuses"],
    "Diverticulitis": ["abdomen", "pelvis"],
    "Fat stranding": ["abdomen", "pelvis"],
    "Appendicitis": ["abdomen"],
    "Pneumoperitoneum": ["abdomen", "pelvis"],
    "Hydronephrosis": ["abdomen", "pelvis"],
    "Nephrolithiasis": ["abdomen", "pelvis"],
    "Tenosynovitis": ["shoulder", "hip", "knee", "ankle_foot", "wrist_hand",
                      "extremity"],
    "Osteophytosis": ["shoulder", "hip", "knee", "ankle_foot", "wrist_hand",
                      "extremity", "spine", "spine_cervical", "spine_thoracic",
                      "spine_lumbar"],
}
unmapped_lex = [n for n, _s in lex_items if n not in LEX_MAP and n not in LEX_ALWAYS]
print("unmapped lexicon terms:", unmapped_lex or "none")
unmapped_gv = [n for n, _s in gv_items if n not in GV_MAP]
print("unmapped grouping entries:", unmapped_gv or "none")


def lit(s):
    return '"""' + s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"') + '"""'

out = io.StringIO()
w = out.write
w('''"""CT region blocks, lifted VERBATIM out of the monolithic report prompt.

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
SECTION_PREFIX: str = ''')
w(lit(PREFIX) + "\n\n")
w("#: (block name, verbatim text) in the order they appear in the live prompt.\n")
w("CT_BLOCKS: List[Tuple[str, str]] = [\n")
for n, t in blocks:
    w(f"    ({n!r},\n     {lit(t)}),\n")
w("]\n\n")

w("#: The GROUPING VOCABULARY entries — the headings the prompt tells the model to\n"
  "#: use. Sent whole today, so a knee CT is offered chest and abdomen headings.\n")
w("GV_PREFIX: str = " + lit(GV_PREFIX) + "\n\n")
w("GV_ITEMS: List[Tuple[str, str]] = [\n")
for n, s in gv_items:
    w(f"    ({n!r},\n     {lit(s)}),\n")
w("]\n\n")
w(f"GV_REGION_MAP: Dict[str, List[str]] = {GV_MAP!r}\n\n")

w("#: The Persian / Finglish dictation lexicon, term by term.\n")
w("LEX_PREFIX: str = " + lit(LEX_PREFIX) + "\n\n")
w("LEX_ITEMS: List[Tuple[str, str]] = [\n")
for n, s in lex_items:
    w(f"    ({n!r},\n     {lit(s)}),\n")
w("]\n\n")
w(f"LEX_ALWAYS: List[str] = {LEX_ALWAYS!r}\n\n")
w(f"LEX_REGION_MAP: Dict[str, List[str]] = {LEX_MAP!r}\n\n")

w("#: canonical region key -> block names. A region may need more than one block, and\n"
  "#: brain needs two because the contrast state changes what may be said.\n")
w("REGION_TO_BLOCKS: Dict[str, List[str]] = {\n")
for k, v in MAP.items():
    w(f"    {k!r}: {v!r},\n")
w("}\n\n")
w("#: blocks that answer to a COMBINATION of regions rather than any single one.\n")
w("COMBO_BLOCKS: Dict[Tuple[str, ...], List[str]] = {\n")
for k, v in COMBO.items():
    w(f"    {tuple(sorted(k))!r}: {v!r},\n")
w("}\n\n")
w("#: blocks selected by an axis other than region (procedure, subtype).\n")
w(f"AXIS_BLOCKS: Dict[str, List[str]] = {AXIS!r}\n\n")
w('''
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
''')

dst = os.path.join(ROOT, "modules", "EchoMind", "viewer_chat", "turbo_regions.py")
io.open(dst, "w", encoding="utf-8", newline="\n").write(out.getvalue())
print("wrote", dst, os.path.getsize(dst), "bytes")

# prove it round-trips before anyone trusts it
sys.path.insert(0, ROOT)
import importlib
m = importlib.import_module("modules.EchoMind.viewer_chat.turbo_regions")
assert m.full_section() == SECTION, "GENERATED FILE DOES NOT REPRODUCE THE SECTION"
assert m.gv_full() == GV, "GENERATED FILE DOES NOT REPRODUCE THE GROUPING VOCABULARY"
assert m.lex_full() == LEX, "GENERATED FILE DOES NOT REPRODUCE THE LEXICON"
print("round-trip verified: all three spans reproduce byte for byte")
print("blocks:", len(m.CT_BLOCKS), "regions mapped:", len(m.REGION_TO_BLOCKS))
