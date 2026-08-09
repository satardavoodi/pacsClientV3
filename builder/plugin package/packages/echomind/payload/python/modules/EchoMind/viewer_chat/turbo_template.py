"""The Turbo prompt TEMPLATE — named slots, filled per study.

WHY A TEMPLATE. The prompt this replaces grew by accretion: every failure added a
paragraph, usually near a related one, occasionally restating a rule already present.
Measured on the CT branch — 23 emphasis markers, the same rule stated 2–3×, 13% of the
bytes leading whitespace, and no statement anywhere of what job the model is doing.
A template fixes the SHAPE first, so a future failure adds a line to a named slot
instead of another paragraph wherever it seemed to fit.

THE SLOTS, and who owns each one:

    ROLE                shared    who the model is, what it returns, language
    PRECEDENCE          shared    what wins when two instructions conflict
    TWO_HALVES          shared    transcription vs generation — the central idea
    RULES_PATHOLOGICAL  shared    source fidelity; one bullet per observed failure
    RULES_NORMAL        shared    the generation method, register, contrast, sex
    MODALITY            per-modality
    STUDY_CONTEXT       per-study    structured facts, each with provenance
    REPORTING_CONTEXT   per-region   gated; one self-contained package per region,
                                     sourced from the gate and nowhere else, and
                                     carrying BOTH halves - pathology rules and
                                     normal-findings reference
    OUTPUT              shared    the JSON contract and text layout

ONE REGION LAYER. The gate produces the region list, the region list produces this
slot, and nothing else in the prompt carries region content. That is the whole point
of the slot: the prompt it replaces spread chest and abdomen content across a
grouping vocabulary, a measurement block and an RSNA normal-findings block, three
places that had to agree and did not. `REGION_MODULES` in `turbo_region_modules` is
the LIBRARY; `REPORTING_CONTEXT` is the slot it fills.

The short `Regions` row in STUDY_CONTEXT is not a second copy. It is the gate's
conclusion stated as a fact with provenance, at precedence 3, where this slot is
guidance at precedence 4 — and the two legitimately differ: a detected region with
no module contributes to the row and not to the slot, and two regions sharing one
package (pelvis + prostate) contribute two names and one block. When they differ,
the model should be able to see that they differ.

ORDER IS DELIBERATE. Role and task first, because the prompt it replaces opened on a
formatting constraint and never stated the task at all. Output contract last, because
recency helps a machine-readable contract. Facts before guidance, so the guidance can
refer to them.

WHAT THIS IS NOT DOING YET. Default OFF. `AIPACS_TURBO_PROMPT_V2=1` opts in. The
current narrowing path is untouched until this has been evaluated against real
transcripts — a 71% token reduction is arithmetic; that it produces equal or better
reports is a hypothesis, and the cases to watch are the ones the removed text was
protecting: a normal-template request, a multi-region study, a hedged dictation, and
one carrying a measurement.

AUTHORING RULES for anything added here:
  1. State the desired behaviour. Reserve prohibitions for the safety boundary.
  2. Say it ONCE. If it needs saying twice, the first place was wrong.
  3. No emphasis markers. Precedence is declared in PRECEDENCE, not by shouting.
  4. Prefer one good example over a paragraph of description.
  5. Facts go in STUDY_CONTEXT, instructions go in RULES. A conditional that reads
     "if the sex is unknown…" usually means a fact belongs in the context block.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_ENV_V2 = "AIPACS_TURBO_PROMPT_V2"


def template_v2_enabled() -> bool:
    """Default ON since 2026-08-09, by owner decision. `AIPACS_TURBO_PROMPT_V2=0`
    reverts every modality to the previous prompt without a rebuild.

    It shipped OFF while the four libraries were being built, on the argument that a
    token reduction is arithmetic and "it produces equal or better reports" is a
    hypothesis. The owner - who is the radiologist these prompts serve and the person
    who can judge the output - decided to run it live. The kill switch is what makes
    that reversible: one environment variable, effective on the next report.
    """
    raw = os.environ.get(_ENV_V2)
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


# ═══════════════════════════════════════════════════════════════════════════
# SHARED SLOTS
# ═══════════════════════════════════════════════════════════════════════════

ROLE = """\
# ROLE

You are a radiologist writing the formal report for one imaging study. You are given
the reporting physician's dictated transcript and structured facts about the study.
You produce a complete, formal radiology report as JSON.

Write in English only, whatever language the transcript is in.
"""

PRECEDENCE = """\
# PRECEDENCE — when two things conflict, the higher number wins

1. The physician's transcript. Nothing overrides it.
2. The RULES in this message.
3. THE EXAMINATION THAT WAS ACTUALLY PERFORMED — the STUDY TYPE block, the Service
   booking, the modality. This decides which structures belong in the report at all.
4. STUDY CONTEXT — what the booking and the scanner recorded.
5. REPORTING CONTEXT — ADVISORY. Structures worth attending to, and the vocabulary to
   use, for a region this study touched. It is neither a limit on what you may report
   nor a checklist you must complete.
"""

TWO_HALVES = """\
# THE TWO HALVES OF THE REPORT

Pathological Findings is TRANSCRIPTION: the physician's findings, formalised.
Normal Findings is GENERATION: the structures he did not mention, written by you.
Never let one become the other.
"""

RULES_PATHOLOGICAL = """\
# RULES — PATHOLOGICAL FINDINGS

The transcript is the only source of pathology. You may fix grammar, apply correct
radiological terminology, repair transcription errors, and reorder findings into
anatomical sequence. You may not change what was found.

- Do not add a finding, diagnosis or location the physician did not state, however
  typical it would be for this study.
- Keep anatomy and laterality exactly as dictated. "Right occipital lobe" stays the
  right occipital lobe.
- A stated negative stays negative. "No hemorrhage" is not a hemorrhage.
- Preserve certainty exactly. A hedge is a clinical claim: "may represent" must not
  become "represents"; "suspicious for" must not become "consistent with";
  "cannot be excluded" stays uncertain.
- Preserve every measurement, grade, score and classification the physician dictated,
  and never invent one — no attenuation value, no volume, no staging or risk
  category unless he gave it, or the finding he described plainly meets that
  system's stated criteria. The systems that apply to this study, and the
  descriptors worth preserving in each region, are named in REPORTING CONTEXT.
- Describe the imaging appearance, then the conclusion:
  "A 2.4 cm hypodense lesion in hepatic segment VI with peripheral rim enhancement,
  consistent with an abscess." — not "Hepatic abscess."
- If you are unsure he said something, leave it out. A shorter faithful report is
  correct; a fuller invented one is a clinical error.
- Impression and Recommendations appear only if he dictated one. If he did, it must
  survive with its meaning intact. If he did not, omit the key — never invent either.
"""

RULES_NORMAL = """\
# RULES — NORMAL FINDINGS

Build them in this order:

1. Identify the EXAMINATION that was actually performed — from the transcript, the
   STUDY TYPE block and the Service booking, not from the region alone.
2. List the structures a standard report of THAT examination covers, using
   established radiology reporting practice for it.
3. Consult REPORTING CONTEXT and take from it what applies: the structures it names
   that this examination genuinely assesses, its terminology, its measurements. Leave
   out what it lists that this examination does not show, and add what it omits that
   this examination does show.
4. For each structure, write its relevant normal imaging features for this modality
   and for the contrast state in STUDY CONTEXT: modality, regions, contrast.
5. Subtract: remove or narrow anything touching a structure the pathology already
   involves or calls into question. The same structure must never appear as both
   normal and abnormal.
6. Group under the REPORTING CONTEXT headings where they fit the examination, and
   otherwise under the headings a standard report of this examination would use. One
   line per organ or group.

Report features, not verdicts. "The liver is normal." is not acceptable — it tells the
referring clinician nothing about what was assessed. Write instead: "Liver is normal in
size, contour and attenuation, enhancing homogeneously, with no focal lesion and no
intrahepatic biliary ductal dilatation."

One line per organ or tightly-related pair. Never one sentence enumerating eleven
organs.

Default to a qualified register — "No gross abnormality is identified in …" — qualified
once at the top of the block rather than on every line. But when the physician asks for
the normal report, switch to definitive normals: he asked for a finished report, not
hedged text he has to rewrite. Recognise the request through bad transcription, in
either language: کد طبیعی · کد نرمال · تمپلیت نرمال · نرمال بیاد · بقیه طبیعی ·
مابقی طبیعی · "the rest is normal" · "normal template". Judge by intent, not spelling —
"دگنش هم کد طبیعی بیاد" is a corrupted "دیگه‌اش هم کد طبیعی بیاد" and is the request.

THE REGIONAL CONTEXT IS GUIDANCE, NOT A SKELETON. A region gate is coarse by design: a
hysterosalpingogram, a retrograde urethrogram, a double-contrast barium study and a
plain abdominal film can all gate to the same region and share almost nothing. Writing
a normal bowel gas pattern, normal renal outlines and no free intraperitoneal air on a
hysterosalpingogram — because the abdominal block happens to list them — is a WRONG
report, not a thorough one. Report what the examination actually shows: for that study,
the uterine cavity, the tubes and the peritoneal spill.

Some examinations are routine enough that nearly every item in the block applies, and
there you should cover nearly all of them. Others need judgement. Decide by what the
examination can actually demonstrate, never by what the block happens to contain.

When the supplied context does not describe the examination you were given, fall back
to established radiology reporting practice for it — conventional RSNA-style section
order and headings for that study — rather than filling in the template you were
handed. A structure the examination cannot assess must not appear as a normal finding.

Contrast governs what you may say. With contrast you may describe enhancement. Without
it, say nothing about enhancement — that is a fabricated observation.

Never infer the patient's sex. Include a sex-specific organ only if STUDY CONTEXT
states the sex or the physician mentioned the organ, and never both male and female
organs in one report.

Completeness is measured against the anatomy this study covered, never a word count.
Never pad a small study; never compress a large one. A completely normal study is a
valid and common report: if nothing abnormal was dictated, Pathological Findings must
say so in words — "No pathological findings are identified." — never empty, never null.
"""

OUTPUT = """\
# OUTPUT

Return one JSON object and nothing else — no prose, no markdown, no code fences.

{
  "Report Title":           string,
  "Pathological Findings":  string,
  "Normal Findings":        string,
  "Impression":             string | null,
  "Recommendations":        string | null
}

"Report Title" names the examination that was performed: the modality, the technique
he named if he named one, and the region. Take the region from the PHYSICIAN. «ام آر آی
از ناحیه شکم به صورت تری فازیک» is a triphasic MRI of the abdomen, and stays one even
when the scanner recorded a wider acquisition. If he named no region, use the Service
booking, then STUDY CONTEXT. Never widen the title to a region he did not name — the
title is the first claim the report makes about what was examined.

Inside the string values: group under the headings above, heading on its own line
ending in a colon, findings on the lines beneath it. Number multiple pathological
findings. Emit a heading only when it has content — a heading is a claim that the
region was examined.

Start with { and end with }.
"""

#: Per-modality note. Region content lives in the region modules, not here.
MODALITY_NOTES: Dict[str, str] = {
    "CT": "Use attenuation, not density, for parenchymal description. Give sizes in mm\n"
          "and name the plane of measurement. Mention a contrast phase only when the\n"
          "transcript or STUDY CONTEXT establishes one.",
    "MRI": "Describe signal on the sequence that shows it (T1, T2, STIR, DWI/ADC, post-\n"
           "contrast). Give sizes in mm and name the plane.",
    "SONOGRAPHY": "Describe echogenicity and echotexture. Give measurements in mm with\n"
                  "the plane. Note the transducer approach when it matters.",
    "RADIOLOGY": "Describe radiodensity and alignment. Name the projection when it\n"
                 "affects what can be assessed.",
    "MAMOGRAPHY": "Follow the BI-RADS lexicon for composition, findings and category.",
}


# ═══════════════════════════════════════════════════════════════════════════
# RENDERING
# ═══════════════════════════════════════════════════════════════════════════

def render_study_context(facts: Iterable) -> str:
    """STUDY CONTEXT from (label, value, provenance) triples.

    Provenance travels with every fact because "the scanner recorded it", "the booking
    says so" and "the physician set it" carry different weight — and the last of those
    is not a hint at all.
    """
    rows = [(str(a), str(b), str(c or "")) for a, b, c in facts if str(b or "").strip()]
    if not rows:
        return ""
    w = max(len(a) for a, _b, _c in rows)
    out = ["# STUDY CONTEXT", ""]
    for label, value, prov in rows:
        line = f"  {label.ljust(w)}   {value}"
        if prov:
            line += f"   ({prov})"
        out.append(line)
    return "\n".join(out) + "\n"


#: A normal-findings line that can only be written when contrast was given. Matching on
#: the two stems rather than a curated list means a region added later is covered the
#: day it lands, instead of the day somebody remembers to tag it.
_CONTRAST_DEPENDENT = re.compile(r"enhanc|contrast", re.IGNORECASE)

#: Only these say "contrast was definitely NOT given". Unknown must never filter.
_CONTRAST_ABSENT = ("without", "none", "non-contrast", "noncontrast", "unenhanced")


def render_region_context(modules: Iterable[dict], notes: Optional[List[str]] = None,
                          *, contrast: str = "") -> str:
    """REPORTING CONTEXT — one self-contained package per gated region.

    Region-major, in gate order: each region contributes its own block carrying its
    headings, its pathological-findings rules, its normal-findings reference, its
    dictation terms and its notes. Adding a region to the library adds exactly one
    block here and changes nothing else.

    A radiography package carries one more section, `projection`, rendered first
    because it constrains everything after it: a view cannot assess what it does not
    show. CT and MRI packages have no such key and render nothing for it.

    `contrast` gates the normal-findings reference (2026-08-09). A brain CT booked
    «بدون تزریق» used to receive five lines describing enhancement — "No abnormal
    parenchymal, leptomeningeal, or dural enhancement", "Choroid plexuses enhance
    symmetrically" — alongside a prose rule forbidding exactly that. The model resolved
    it correctly by reading the Persian booking text, but the same prompt showed
    REPORTING CONTEXT winning over RULES on attenuation-vs-density, so relying on that
    precedence holding for a fabrication safeguard is not a decision worth making.
    Filtering applies ONLY when contrast is positively known absent; unknown changes
    nothing, because guessing here would delete real guidance.

    BOTH HALVES ARE GATED, not just the normal half. The pathology rules a region
    carries are the descriptors worth preserving there and the classification systems
    that apply there: a brain CT is not told about Fleischner, an abdominal CT is not
    told about BI-RADS, and the shared rules keep only what is true of every study.

    An earlier draft merged section-wise, out of a worry about "two competing reporting
    orders". That failure belonged to the old prompt, where each region fragment
    carried its own REPORT ORGANIZATION rule. A module carries a heading LIST, not an
    ordering rule — the rule lives once, in OUTPUT — so blocks in gate order state
    exactly one order, and the merge was solving a problem the module contract had
    already removed.

    Dictation terms are de-duplicated first-wins across regions: the always-on terms
    reach the model once rather than once per region.
    """
    mods = [m for m in modules if m]
    if not mods:
        return ""
    drop_enhancement = str(contrast or "").strip().lower() in _CONTRAST_ABSENT
    out = ["# REPORTING CONTEXT", "",
           "ADVISORY — one block per region this study was gated to. Structures worth",
           "attending to and the vocabulary to use, NOT a checklist and NOT a report",
           "skeleton. Use the parts that apply to the examination actually performed;",
           "leave out the parts that do not. If the transcript describes anatomy",
           "outside it, report that finding normally and place it correctly."]

    seen: set = set()
    for m in mods:
        out += ["", f"## {m['title']}", "",
                "  Headings, in this order",
                f"    {m['headings']}"]
        technique = [p for p in m.get("technique", []) if str(p).strip()]
        if technique:
            out += ["", "  Technique and what it limits"]
            for line in technique:
                out.append(f"    - {line}")
        projection = [p for p in m.get("projection", []) if str(p).strip()]
        if projection:
            out += ["", "  What the performed projection can and cannot assess"]
            for line in projection:
                out.append(f"    - {line}")
        pathology = [p for p in m.get("pathology", []) if str(p).strip()]
        if pathology:
            out += ["", "  Pathological findings, when he dictates them"]
            for line in pathology:
                out.append(f"    - {line}")
        normal = list(m["normal"])
        if drop_enhancement:
            kept = [ln for ln in normal if not _CONTRAST_DEPENDENT.search(str(ln))]
            # Never empty a region's reference. A block carrying a contradiction the
            # model has to resolve is bad; a block with no normal guidance at all is
            # worse, and would be a silent, total loss of coverage for that region.
            if kept and len(kept) != len(normal):
                logger.info("[Turbo-prompt] %s: dropped %d contrast-dependent normal "
                            "line(s) — study is non-contrast",
                            m.get("title"), len(normal) - len(kept))
                normal = kept
            elif not kept:
                logger.warning("[Turbo-prompt] %s: every normal line is contrast-"
                               "dependent; keeping all of them", m.get("title"))
        out += ["", "  Normal-findings reference — use the items this examination "
                    "actually assesses"]
        for line in normal:
            out.append(f"    - {line}")
        fresh = [t for t in m.get("terms", []) if t not in seen]
        seen.update(fresh)
        if fresh:
            out += ["", "  Dictation terms you may encounter",
                    "    " + " \u00b7 ".join(fresh)]
        region_notes = [n for n in m.get("notes", []) if str(n).strip()]
        if region_notes:
            out += ["", "  Notes"]
            for n in region_notes:
                out.append(f"    - {n}")

    study_notes = [n for n in (notes or []) if str(n).strip()]
    if study_notes:
        out += ["", "## Notes for this study", ""]
        for n in study_notes:
            out.append(f"    - {n}")
    return "\n".join(out) + "\n"


def render_subtype_context(packages: Iterable[dict]) -> str:
    """STUDY TYPE — the second gate axis, selected by `case.subtype`.

    Region is WHERE the study looked; subtype is WHAT KIND of study it is.
    Obstetric ultrasound is the case that forced the distinction: a dating scan,
    an NT scan, an anomaly scan, a growth scan and a biophysical profile all have
    region `obstetric` and share almost no reporting content. Gating them to one
    package would send the anatomy survey to a viability scan.

    Rendered AFTER the region context because it narrows within it, and it may be
    empty — most studies have no subtype and render nothing here.
    """
    pkgs = [p for p in packages if p]
    if not pkgs:
        return ""
    out = ["# STUDY TYPE", "",
           "THE EXAMINATION THAT WAS PERFORMED. This defines the report: what it must",
           "cover, and which parts of the region block above are relevant to it. Where",
           "the two disagree, this wins."]
    for p in pkgs:
        out += ["", f"## {p['title']}"]
        for label, key in (("Technique", "technique"),
                           ("This study must report", "must_report"),
                           ("Pathological findings, when he dictates them",
                            "pathology")):
            rows = [x for x in p.get(key, []) if str(x).strip()]
            if rows:
                out += ["", f"  {label}"]
                out += [f"    - {x}" for x in rows]
    return "\n".join(out) + "\n"


def render(*, modality: str, study_facts: Iterable, modules: Iterable[dict],
           study_notes: Optional[List[str]] = None,
           subtypes: Optional[Iterable[dict]] = None,
           contrast: str = "") -> str:
    """Assemble the whole system prompt from the slots, in the fixed order.

    `contrast` is passed straight through to the region renderer, which drops the
    enhancement normal-lines when the study is known to be non-contrast. Defaulting to
    "" keeps every existing caller (and the unknown-contrast case) byte-identical.
    """
    parts = [ROLE, PRECEDENCE, TWO_HALVES, RULES_PATHOLOGICAL, RULES_NORMAL]
    note = MODALITY_NOTES.get(str(modality or "").strip().upper())
    if note:
        parts.append(f"# MODALITY — {str(modality).strip().upper()}\n\n{note}\n")
    ctx = render_study_context(study_facts)
    if ctx:
        parts.append(ctx)
    reg = render_region_context(modules, study_notes, contrast=contrast)
    if reg:
        parts.append(reg)
    sub = render_subtype_context(subtypes or [])
    if sub:
        parts.append(sub)
    parts.append(OUTPUT)
    return "\n".join(p.rstrip() + "\n" for p in parts)
