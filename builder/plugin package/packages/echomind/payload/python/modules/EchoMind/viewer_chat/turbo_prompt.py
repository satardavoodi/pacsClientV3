"""Turbo's own report prompt builder.

WHY A SEPARATE BUILDER (owner decision, 2026-08-08).
`build_report_system_prompt` has TWO consumers:

    openai_reporter.reporter          the company GapGPT path
    openai_parallel_backend.reporter  the user's own-OpenAI-key path

and `_ai_module()` routes BOTH the Turbo button and the Send button through them
depending on the Settings backend. They deliberately share one prompt — `_prompt_parity_
enabled()` exists so a radiologist gets the same report whichever backend is selected.

Turbo is now going to diverge: region-gated context composed per study. That divergence
must not reach Send. Since `openai_reporter.reporter` serves Send too whenever the
backend is `company` (the default), the split CANNOT live inside that function — it has
to be made at the Turbo CALL SITE, which is the only place that knows it is Turbo.

So: this module builds Turbo's prompt, the Turbo call site passes it as
`system_prompt_override`, and every other caller keeps the shared builder untouched by
passing nothing.

WHAT IT DOES

WITHOUT a profile it returns output **byte-identical** to the shared builder. Not one
character changes. A test pins that for every modality, with and without a normal
template, and it is the baseline everything else is measured against.

WITH a profile carrying regions, and only for CT so far, it REPLACES the
`RSNA-compliant normal findings per CT body region` span with just the blocks those
regions need. Everything outside that span — source fidelity, report organisation, the
normal-findings method, the output contract — is untouched, byte for byte. Measured on
study 53516 (chest + abdomen + pelvis): 12,184 → 8,806 tokens, keeping 4 of 19 blocks.

THE SAFETY POSTURE, which matters more than the saving

Every uncertainty resolves to "send the full prompt", never to "send less":
no profile · no regions · unrecognised regions · a modality not yet decomposed ·
markers not found · any exception. And a SELF-CHECK compares the live span against the
extracted library on every call — if the prompt and `turbo_regions.py` have drifted
apart, narrowing would ship stale clinical text, so it refuses and sends everything.

The one thing it must never do is narrow to nothing. An empty region section would
delete every region's reporting rules and still look like a successful call.

NEXT, HERE AND NOWHERE ELSE
MRI's six region blocks sit inside a span mislabelled `PATHOLOGICAL FINDINGS RULES`;
extracting them is the same procedure and the same tests. Send keeps today's prompt
throughout.

KILL SWITCH
``AIPACS_TURBO_PROMPT=0`` makes this return None, and the call site then falls back to
the shared builder — the same field-revertible pattern as `_prompt_parity_enabled`.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_ENV_TURBO_PROMPT = "AIPACS_TURBO_PROMPT"

#: The CT region section, located by its own markers rather than by line number so an
#: unrelated edit above it cannot silently shift the span.
_CT_SECTION_START = "* RSNA-compliant normal findings per CT body region:"
_CT_SECTION_END = "OUTPUT FORMAT (STRICT)"


def _locate_ct_section(prompt: str):
    """(start, end) of the region section, or None if the markers are not where we
    expect. Returning None means "do not narrow" — never "narrow to nothing"."""
    i = prompt.find(_CT_SECTION_START)
    if i < 0:
        return None
    j = prompt.find(_CT_SECTION_END, i)
    if j <= i:
        return None
    # back up to the rule line that opens the OUTPUT FORMAT banner
    k = prompt.rfind("\n", i, j)
    while k > i and not prompt[k + 1:j].lstrip().startswith("━"):
        k2 = prompt.rfind("\n", i, k)
        if k2 <= i:
            break
        k = k2
    return (i, k + 1)


def _select_ct_blocks(profile: dict):
    """Block names for this profile, or None meaning "keep the whole section".

    THE SAFETY RULE: this returns None far more readily than it returns a short list.
    No regions, unrecognised regions, or anything it cannot account for all mean the
    physician gets the full section — exactly today's behaviour. The one thing it must
    never do is return an empty selection, because that would delete every region's
    reporting rules and still look like a successful narrowing.
    """
    try:
        from .turbo_regions import AXIS_BLOCKS, COMBO_BLOCKS, REGION_TO_BLOCKS
        from .turbo_regions_extra import EXTRA_REGION_TO_BLOCKS
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-prompt] region library unavailable: %s", exc)
        return None

    regions = [str(r).strip().lower() for r in (profile.get("regions") or []) if r]
    if not regions:
        return None

    names = []

    def add(bs):
        for b in bs:
            if b not in names:
                names.append(b)

    for r in regions:
        add(REGION_TO_BLOCKS.get(r, []))
        add(EXTRA_REGION_TO_BLOCKS.get(r, []))
    for combo, blocks in COMBO_BLOCKS.items():
        if set(combo) <= set(regions):
            add(blocks)
    procedure = str(profile.get("procedure") or "").strip().lower()
    if procedure in ("angio", "angiography", "cta", "vascular"):
        add(AXIS_BLOCKS.get("vascular", []))
    subtype = str(profile.get("subtype") or "").strip().lower()
    if subtype in ("urography", "kub", "ct_kub"):
        add(AXIS_BLOCKS.get("urography", []))
    if subtype in ("coronary", "coronary_cta", "cardiac"):
        add(AXIS_BLOCKS.get("coronary", []))

    if not names:
        logger.info("[Turbo-prompt] regions %s map to no block; keeping the full "
                    "section", regions)
        return None

    # Contrast refines brain, which is the one region with a with/without pair. Only a
    # DEFINITE 'none' drops the contrast block; unknown keeps both, because the prompt
    # already knows how to stay neutral and guessing here would suppress real guidance.
    if str(profile.get("contrast") or "").strip().lower() in ("none", "non-contrast",
                                                              "without"):
        names = [n for n in names if n != "BRAIN CT WITH CONTRAST"] or names
    return names


def _tr():
    from . import turbo_regions
    return turbo_regions


def _tx():
    from . import turbo_regions_extra
    return turbo_regions_extra


def _narrow_span(prompt, start, end, *, tr_full, tr_for, regions,
                 extra_map=None, extra_text=None, label=""):
    """Replace one region-specific span, or leave the prompt exactly as it is.

    Same self-check as the region blocks: if the live span is not what the extracted
    library says it should be, the two have drifted and this does not touch it.

    THE TRAILING-WHITESPACE DETAIL, which is not cosmetic. Each span ends with the
    indentation of the line that follows it — the last grouping entry carries the 24
    spaces that put `• Exclude any anatomical region…` at the right level. Drop that
    entry and the next line lands at column 0, which reads as a different level of the
    prompt's outline. So the original span's trailing whitespace is carried over.
    """
    try:
        i = prompt.find(start)
        if i < 0:
            return prompt
        j = prompt.find(end, i + 1)
        if j <= i:
            return prompt
        orig = prompt[i:j]
        if orig != tr_full():
            logger.warning("[Turbo-prompt] %s has drifted from turbo_regions.py; "
                           "leaving it whole", label)
            return prompt
        new = tr_for(regions)
        for r in regions:
            for name in (extra_map or {}).get(r, []):
                if extra_text:
                    new += extra_text(name)
        if not new.strip():
            return prompt
        tail_old = orig[len(orig.rstrip()):]
        tail_new = new[len(new.rstrip()):]
        if tail_old != tail_new:
            new = new.rstrip() + tail_old
        return prompt[:i] + new + prompt[j:]
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-prompt] could not narrow %s: %s", label, exc)
        return prompt


def _render_template(modality: str, profile: dict):
    """The template-composed prompt, or None to fall through to narrowing.

    Modality-keyed since MRI landed: the library is chosen by `turbo_modules`, not
    assumed. A region with no module in that modality's library means the template
    would render a REPORTING CONTEXT with nothing in it — worse than the narrowed or
    the full prompt, so it declines rather than degrades.
    """
    try:
        from .turbo_modules import modules_for, subtypes_for
        from .turbo_template import render
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-prompt] template unavailable: %s", exc)
        return None
    regions = [str(r).strip().lower() for r in (profile.get("regions") or []) if r]
    mods = modules_for(modality, regions)
    if not mods:
        logger.info("[Turbo-prompt] no %s region module for %s; using the narrowed "
                    "prompt", modality, regions)
        return None
    _contrast = str(profile.get("contrast") or "").strip().lower()
    facts = [
        ("Patient", profile.get("patient"), profile.get("patient_source") or "DICOM"),
        ("Modality", str(modality or "").strip().upper(), "DICOM"),
        ("Regions", ", ".join(r.replace("_", " ") for r in regions),
         profile.get("regions_source") or "auto-detected"),
        # Spelled out for the model: "without" alone reads as a truncated field, and
        # this row is what RULES — NORMAL FINDINGS step 1 sends it to look for.
        ("Contrast", _CONTRAST_LABEL.get(_contrast, profile.get("contrast")),
         profile.get("contrast_source") or ""),
        ("Service", profile.get("service"), "reception booking"),
        ("Protocol", profile.get("protocol"), "DICOM"),
    ]
    raw_sub = profile.get("subtype") or []
    if isinstance(raw_sub, str):
        raw_sub = [raw_sub]
    subs = subtypes_for(modality, [str(s).strip().lower() for s in raw_sub if s])
    return render(modality=modality, study_facts=facts, modules=mods,
                  study_notes=profile.get("notes") or [], subtypes=subs,
                  contrast=_contrast)


TURBO_CORRECTION_FRAME = """\
# TASK — EDIT, DO NOT GENERATE

Edit the existing radiology report strictly according to the physician's
correction request. The existing report is the authoritative base document.

Apply only the requested correction and preserve all unrelated content.

- Do not generate a new report from scratch.
- Do not regenerate Normal Findings.
- Do not introduce a pathological finding the request did not ask for.
- Do not remove a finding unless removal is what was requested.
- Do not change a measurement, laterality, anatomical location, diagnosis,
  Impression or Recommendation unless the correction request requires it.
- Keep the existing structure, section order and formatting.

Make the minimal grammatical and structural adjustments needed to keep the
report medically coherent after the change - and no more than those.

Return the COMPLETE corrected report, not a diff and not only the changed
section, in the output format specified below.
"""


def build_turbo_correction_prefix() -> Optional[str]:
    """The editing frame Turbo prepends to the shared correction prompt.

    A PREFIX, not an override. A correction response is parsed, so a prompt that
    replaced the shared one and forgot a key would return a report the app cannot
    read - and the shared correction prompt already carries a hard-won contract
    (mammography has eleven keys, not five). Everything it says still follows this.

    Returns None when the Turbo prompt is disabled, so the caller sends the shared
    correction prompt exactly as it is today.
    """
    if not turbo_prompt_enabled():
        logger.info("[Turbo-correction] disabled by %s; shared prompt only",
                    _ENV_TURBO_PROMPT)
        return None
    return TURBO_CORRECTION_FRAME


def build_mammography_prefix(profile: Optional[dict] = None) -> Optional[str]:
    """The breast reporting context, prepended to the shared mammography prompt.

    A PREFIX, never a replacement. The mammography prompt opens with a REGEX-LOCKED
    schema and returns a different shape from every other modality — no `Impression`
    and no `Recommendations` key at all. Rendering the nine-slot template here would
    emit the five-key contract and the regex would reject it.

    So mammography is the one modality that gains coverage without gaining brevity: the
    prompt is slightly LONGER than before. That was the trade to make; a shorter prompt
    that fails to parse is worth nothing.

    Returns None when the Turbo prompt is disabled, so the caller sends the shared
    mammography prompt exactly as it is today.
    """
    if not turbo_prompt_enabled():
        return None
    try:
        from .turbo_mammo_modules import MAMMO_CONTEXT, MAMMO_SUBTYPE_PACKAGES
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-mammo] context unavailable: %s", exc)
        return None

    c = MAMMO_CONTEXT
    out = ["# REPORTING CONTEXT — BREAST (MAMMOGRAPHY)", "",
           "Guidance for coverage, order and vocabulary. Everything below this block —",
           "including the JSON schema and its regex lock — still governs the output.", "",
           "  Headings, in this order", "    " + str(c["headings"]),
           "", "  Technique and what it limits"]
    out += ["    - " + x for x in c["technique"]]
    out += ["", "  Pathological findings, when he dictates them"]
    out += ["    - " + x for x in c["pathology"]]
    out += ["", "  Dictation terms you may encounter",
            "    " + " \u00b7 ".join(c["terms"])]
    out += ["", "  Notes"]
    out += ["    - " + x for x in c["notes"]]

    raw = (profile or {}).get("subtype") or []
    if isinstance(raw, str):
        raw = [raw]
    seen = set()
    for s in raw:
        p = MAMMO_SUBTYPE_PACKAGES.get(str(s).strip().lower())
        if not p or p["title"] in seen:
            continue
        seen.add(p["title"])
        out += ["", "## " + p["title"]]
        for label, key in (("Technique", "technique"),
                           ("This study must report", "must_report"),
                           ("Pathological findings, when he dictates them", "pathology")):
            rows = [x for x in p.get(key, []) if str(x).strip()]
            if rows:
                out += ["", "  " + label] + ["    - " + x for x in rows]
    return "\n".join(out) + "\n"


def turbo_prompt_enabled() -> bool:
    """Default ON. ``=0`` reverts Turbo to the shared builder without a rebuild."""
    raw = os.environ.get(_ENV_TURBO_PROMPT)
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


#: How the Contrast row reads in STUDY CONTEXT. `session_metadata.detect_contrast`
#: emits the canonical short forms; the v1 narrowing path below matches on those too.
_CONTRAST_LABEL = {
    "with": "with contrast (IV contrast administered)",
    "without": "without contrast (non-contrast study)",
}


def build_turbo_system_prompt(
    modality: Optional[str] = "",
    normal_template: Optional[str] = "",
    *,
    profile: Optional[dict] = None,
) -> Optional[str]:
    """The system prompt for a Turbo report, or None to defer to the shared builder.

    Returning None — rather than raising or returning a half-built prompt — is the
    contract that makes this safe to land: the call site treats None as "use what you
    used yesterday", so a failure here costs the physician nothing.

    ``profile`` is reserved for the resolved study profile in phase 2. It is accepted
    now so that wiring the gate is a change to THIS file only.
    """
    if not turbo_prompt_enabled():
        logger.info("[Turbo-prompt] disabled by %s; using the shared builder",
                    _ENV_TURBO_PROMPT)
        return None
    try:
        # The import is local so a circular-import problem in openai_reporter can never
        # break the Turbo button — it degrades to the shared builder instead.
        from .openai_reporter import build_report_system_prompt
        base = build_report_system_prompt(modality or "", normal_template or "")
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-prompt] build failed, falling back to the shared "
                       "builder: %s", exc)
        return None

    # No profile, or a modality with no region-module library: byte-identical to the
    # shared prompt. CT and MRI have libraries; ultrasound, X-ray and mammography do
    # not yet, and for those this returns exactly what the shared builder produced.
    # Mammography is gated by PREFIX, not by template: its schema is regex-locked
    # and the template's OUTPUT slot would emit the wrong shape.
    if str(modality or "").strip().upper() in ("MAMOGRAPHY", "MAMMOGRAPHY",
                                                "MAMMOGRAM", "MAMOGRAM"):
        if not isinstance(profile, dict):
            return base
        try:
            pre = build_mammography_prefix(profile)
        except Exception as exc:                  # pragma: no cover - defensive
            logger.warning("[Turbo-mammo] prefix failed: %s", exc)
            return base
        if not pre:
            return base
        logger.info("[Turbo-mammo] prefix %d chars + shared prompt", len(pre))
        return pre + "\n" + base

    from .turbo_modules import normalise_modality, supported_modalities
    mod = normalise_modality(modality)
    if not isinstance(profile, dict) or mod not in supported_modalities():
        return base

    # The TEMPLATE path (opt-in, AIPACS_TURBO_PROMPT_V2=1). It replaces the whole
    # prompt rather than narrowing spans inside it, so it is a behaviour change and
    # defaults off until it has been evaluated against real transcripts.
    try:
        from .turbo_template import template_v2_enabled
        if template_v2_enabled():
            v2 = _render_template(modality, profile)
            if v2:
                logger.info("[Turbo-prompt] TEMPLATE v2: %d chars (narrowing would be "
                            "a different prompt)", len(v2))
                return v2
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-prompt] template failed, narrowing instead: %s", exc)

    # NARROWING is CT-only, and stays that way: the three spans it rewrites were
    # extracted from the CT branch of the shared prompt and the drift self-check is
    # against that extraction. MRI reaches the gate through the template path only,
    # so with v2 off an MRI report is byte-identical to today.
    if mod != "CT":
        return base

    try:
        names = _select_ct_blocks(profile)
        if not names:
            return base
        regions = [str(r).strip().lower() for r in (profile.get("regions") or []) if r]

        span = _locate_ct_section(base)
        if span is None:
            logger.warning("[Turbo-prompt] region section markers not found; "
                           "sending the full prompt")
            return base

        # SELF-CHECK. The extraction in turbo_regions was lifted from this prompt. If
        # someone edits the prompt and not the library — or the reverse — the two have
        # drifted, and narrowing would silently ship stale clinical text. Compare, and
        # refuse to narrow on any mismatch.
        from .turbo_regions import full_section, section_for
        a, b = span
        if base[a:b] != full_section():
            logger.warning("[Turbo-prompt] the region section has DRIFTED from "
                           "turbo_regions.py; sending the full prompt. Re-run "
                           "tools/dev/regen_turbo_regions.py")
            return base

        # Generated blocks keep their original order; authored ones are appended.
        # `section_for` only knows the generated library, so the extras are spliced
        # here — which is also why regenerating turbo_regions.py can never lose them.
        from .turbo_regions_extra import extra_block_text
        section = section_for(names)
        for _n in names:
            section += extra_block_text(_n)
        narrowed = base[:a] + section + base[b:]

        # The region blocks are not the only region-specific span. The GROUPING
        # VOCABULARY names headings for eight regions, and the prompt tells the model
        # to use "the groupings the MODALITY RULES already name for this study"; the
        # Persian lexicon carries sixteen dictation terms. Both are sent whole today,
        # so a knee CT is offered chest headings and an appendicitis mapping.
        narrowed = _narrow_span(
            narrowed, "• GROUPING VOCABULARY (CT)", "• Exclude any anatomical",
            tr_full=_tr().gv_full, tr_for=_tr().gv_for, regions=regions,
            extra_map=_tx().EXTRA_GV_REGION_MAP, extra_text=_tx().extra_gv_text,
            label="grouping vocabulary")
        narrowed = _narrow_span(
            narrowed, "* Recognise Persian", "━",
            tr_full=_tr().lex_full, tr_for=_tr().lex_for, regions=regions,
            label="persian lexicon")

        logger.info("[Turbo-prompt] regions=%s blocks=%d prompt %d -> %d chars",
                    profile.get("regions"), len(names), len(base), len(narrowed))
        return narrowed
    except Exception as exc:                      # pragma: no cover - defensive
        logger.warning("[Turbo-prompt] narrowing failed, sending the full prompt: %s",
                       exc)
        return base
