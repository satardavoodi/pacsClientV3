# -*- coding: utf-8 -*-
"""Build the ultrasound region modules and the obstetric subtype packages.

The SONOGRAPHY branch is the richest source since CT: per-exam normal templates marked
with a U+258C bar, a gynaecologic block, an obstetric biometry block and an ISUOG
obstetric normal-findings block. All of it is extracted. The pathology half, the
technique guidance and every obstetric subtype come from `turbo_us_authored.py`.

Run:  .venv\\Scripts\\python.exe tools\\dev\\gen_turbo_us_modules.py
"""
import io, os, re, sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)

from modules.EchoMind.session_metadata import REGION_KEYS
from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
from turbo_us_authored import (US_HEADINGS, US_NORMAL_EXTRA, US_NOTES, US_PATHOLOGY,
                               US_SUBTYPES, US_TECHNIQUE, US_TERMS)

LINES = build_report_system_prompt("SONOGRAPHY", "").splitlines()
BAR = "▌"

BLOCK_TO_REGIONS = {
    "COMPLETE ABDOMINAL ULTRASOUND": ["abdomen"],
    "HEPATOBILIARY / RIGHT-UPPER-QUADRANT (focused)": ["abdomen"],
    "RENAL / URINARY-TRACT (KUB) ULTRASOUND": ["abdomen"],
    "PELVIC ULTRASOUND — MALE (bladder / prostate)": ["pelvis"],
    "THYROID / NECK ULTRASOUND": ["head_neck", "thyroid"],
    "BREAST ULTRASOUND (bilateral / targeted)": ["breast"],
    "SCROTAL / TESTICULAR ULTRASOUND": ["scrotum"],
    # `thyroid` and `head_neck` share the title "Neck", so `modules_for`
    # de-duplicates them to one block. They must therefore carry the SAME
    # content, or which key the gate emitted first would silently decide
    # whether the carotids were covered.
    "CAROTID / VERTEBRAL DOPPLER": ["head_neck", "thyroid"],
    "EXTREMITY VENOUS DOPPLER (DVT study)": ["extremity"],
    "EXTREMITY ARTERIAL DOPPLER": ["extremity"],
    "APPENDIX / RIGHT-ILIAC-FOSSA ULTRASOUND": ["abdomen"],
    "SOFT-TISSUE / SUPERFICIAL / MUSCULOSKELETAL ULTRASOUND": ["extremity"],
}
TITLES = {
    "abdomen": "Abdomen", "pelvis": "Pelvis", "head_neck": "Neck", "thyroid": "Neck",
    "breast": "Breast", "scrotum": "Scrotum", "extremity": "Extremity and soft tissue",
    "hip": "Hip", "brain": "Neonatal head", "orbit": "Orbit", "chest": "Chest",
    "obstetric": "Obstetric",
}


def _bullets(rows):
    out = []
    for ln in rows:
        s = ln.strip()
        if s.startswith("•") or s.startswith("–"):
            out.append(re.sub(r"\s+", " ", s.lstrip("•– ").strip()))
        elif out and s and not s.startswith(BAR) and not s.endswith(":"):
            out[-1] = (out[-1] + " " + re.sub(r"\s+", " ", s)).strip()
    return [x for x in out if x and "DO NOT infer" not in x
            and "Include a sex-specific organ" not in x
            and "NEVER include BOTH" not in x and not x.startswith("ONE set")]


# ── the barred exam templates ────────────────────────────────────────────────
marks = [(i, LINES[i].strip().lstrip(BAR).strip())
         for i in range(len(LINES)) if LINES[i].strip().startswith(BAR)]
if len(marks) < 10:
    raise SystemExit("only %d barred exam templates found — the block moved" % len(marks))
marks.append((len(LINES), "<end>"))

NORMAL = {}
for k in range(len(marks) - 1):
    (i, name), (j, _) = marks[k], marks[k + 1]
    for region in BLOCK_TO_REGIONS.get(name, []):
        for line in _bullets(LINES[i + 1:j]):
            NORMAL.setdefault(region, []).append(line)

# ── the gynaecologic block feeds pelvis; the ISUOG block feeds obstetric ─────
def _span(start_pat, stop_pats):
    lo = next(i for i, l in enumerate(LINES) if re.search(start_pat, l))
    for j in range(lo + 1, len(LINES)):
        if any(re.search(p, LINES[j]) for p in stop_pats):
            return lo, j
    return lo, len(LINES)


g_lo, g_hi = _span(r"ISUOG NORMAL FINDINGS — GYNECOLOGIC", [r"All ultrasound terminology"])
for line in _bullets(LINES[g_lo + 1:g_hi]):
    if line not in NORMAL.get("pelvis", []):
        NORMAL.setdefault("pelvis", []).append(line)

o_lo, o_hi = _span(r"ISUOG NORMAL FINDINGS — OBSTETRIC", [r"ISUOG NORMAL FINDINGS — GYN"])
NORMAL["obstetric"] = _bullets(LINES[o_lo + 1:o_hi])
b_lo, b_hi = _span(r"BPD, HC, AC, FL", [r"NON-OBSTETRIC ULTRASOUND"])
BIOMETRY = _bullets(LINES[b_lo:b_hi])
for line in BIOMETRY:
    if line not in NORMAL["obstetric"]:
        NORMAL["obstetric"].append(line)

for key, extra in US_NORMAL_EXTRA.items():
    for line in extra:
        if line not in NORMAL.get(key, []):
            NORMAL.setdefault(key, []).append(line)

modules = {}
for key in TITLES:
    if key not in REGION_KEYS:
        raise SystemExit("%r is not a canonical region key" % key)
    modules[key] = {
        "title": TITLES[key],
        "headings": US_HEADINGS.get(key, ""),
        "technique": list(US_TECHNIQUE["_shared"]),
        "pathology": US_PATHOLOGY.get(key, []),
        "normal": NORMAL.get(key, []),
        "terms": list(US_TERMS),
        "notes": US_NOTES.get(key, []),
    }

print("%d ultrasound region modules built (%d extracted exam templates)"
      % (len(modules), len(marks) - 1))
for k, m in modules.items():
    print("  %-12s %-26s head=%-3s tech=%d path=%2d normal=%2d notes=%d"
          % (k, m["title"], "yes" if m["headings"] else "NO", len(m["technique"]),
             len(m["pathology"]), len(m["normal"]), len(m["notes"])))
thin = {k: len(m["normal"]) for k, m in modules.items() if len(m["normal"]) < 8}
print("\nnormal references under 8 lines:", thin or "none")
print("obstetric subtypes:", len(US_SUBTYPES))


out = io.StringIO()
w = out.write
w('''"""Ultrasound region modules and obstetric subtype packages.

GENERATED by `tools/dev/gen_turbo_us_modules.py`. Do not hand-edit: re-run it.

The normal-findings references are EXTRACTED from the SONOGRAPHY branch of the shared
prompt, where a radiologist wrote per-exam templates with real thresholds. The pathology
rules, the technique guidance and every obstetric subtype come from
`tools/dev/turbo_us_authored.py` and are ⚠️ NOT YET CLINICALLY REVIEWED.

    headings    the organ order for this region
    technique   window, route and what was not visualised     ← ultrasound only
    pathology   descriptors worth preserving and the systems that apply here
    normal      the normal-findings reference
    terms       ultrasound dictation terms
    notes       region-specific traps

WHY `technique`. Ultrasound is operator- and window-dependent in a way CT and MRI are
not. "Not visualised" and "normal" are different statements, a transabdominal negative
is not a transvaginal negative, and a limited acoustic window qualifies everything after
it. That is the same class of section as radiography's `projection`.

WHY SUBTYPES. Obstetric ultrasound is the one place where region is not enough. A dating
scan, an NT scan, an anomaly scan, a growth scan and a biophysical profile all have
region `obstetric` and share almost no reporting content — this centre books 17 distinct
obstetric codes. `US_SUBTYPES` is a second axis selected by `case.subtype`.

NOT COVERED: fetal echocardiography and fetal lung maturity.
"""

from __future__ import annotations

from typing import Dict, List

US_MODULES: Dict[str, dict] = {
''')
for r, m in modules.items():
    w("    %r: {\n" % r)
    w("        'title': %r,\n" % m["title"])
    w("        'headings': %r,\n" % m["headings"])
    for sec in ("technique", "pathology", "normal"):
        w("        %r: [\n" % sec)
        for line in m[sec]:
            w("            %r,\n" % line)
        w("        ],\n")
    w("        'terms': %r,\n" % m["terms"])
    w("        'notes': %r,\n" % m["notes"])
    w("    },\n")
w("}\n\n\n")
w("#: The second gate axis: selected by `case.subtype`, rendered after the regions.\n")
w("US_SUBTYPE_PACKAGES: Dict[str, dict] = {\n")
for s, m in US_SUBTYPES.items():
    w("    %r: {\n" % s)
    w("        'title': %r,\n" % m["title"])
    for sec in ("technique", "must_report", "pathology"):
        w("        %r: [\n" % sec)
        for line in m.get(sec, []):
            w("            %r,\n" % line)
        w("        ],\n")
    w("    },\n")
w("}\n")

dst = os.path.join(ROOT, "modules", "EchoMind", "viewer_chat", "turbo_us_modules.py")
io.open(dst, "w", encoding="utf-8", newline="\n").write(out.getvalue())
print("\nwrote %s  %d bytes" % (dst, os.path.getsize(dst)))

import importlib
mod = importlib.import_module("modules.EchoMind.viewer_chat.turbo_us_modules")
importlib.reload(mod)
assert len(mod.US_MODULES) == len(modules), "round trip lost a module"
assert len(mod.US_SUBTYPE_PACKAGES) == len(US_SUBTYPES), "round trip lost a subtype"
for k, m in modules.items():
    assert mod.US_MODULES[k]["normal"] == m["normal"], "round trip changed %s" % k
print("import verified:", len(mod.US_MODULES), "modules,",
      len(mod.US_SUBTYPE_PACKAGES), "subtypes")
