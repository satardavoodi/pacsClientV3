# 2 · Prompt architecture

**Scope:** how the prompt is decomposed into reusable components, which components are
shared, which are selected by the gate, and how the final message is assembled.

---

## 2.1 Two prompt paths exist at once

| | v1 — narrowing | v2 — template |
|---|---|---|
| What it does | takes the shared prompt and **replaces** three region-keyed spans with the gated subset | builds the prompt from **named slots**, nothing inherited |
| Default | fallback only | **on** since 2026-08-09 (`AIPACS_TURBO_PROMPT_V2=0` reverts) |
| CT chest+abdomen | ~7,749 tok | ~2,322 tok |
| Any CT, ungated | ~12,184 tok | — |
| Risk | low: everything outside the three spans is byte-identical | it IS the behaviour now; evaluation against real transcripts is verification, not a gate |

Both live in `turbo_prompt.py`. `build_turbo_system_prompt()` picks: the mammography
prefix if the modality is mammography, else v2 if every prerequisite holds, else v1
narrowing (CT only), else the shared prompt unchanged.

### The section shape differs by modality

A region package is not the same shape everywhere, because the modalities do not fail
the same way:

| Section | CT | MRI | X-ray | US |
|---|---|---|---|---|
| `headings` · `pathology` · `normal` · `terms` · `notes` | ✓ | ✓ | ✓ | ✓ |
| `projection` — what the performed view can and cannot assess | | | **✓** | |
| `technique` — window, route, and what was not visualised | | | | **✓** |

A radiograph acquires one view and a view cannot assess what it does not show. An
ultrasound is operator- and window-dependent, and "not visualised" is not "normal".
CT and MRI acquire a volume and need neither. Tests pin that neither section leaks.

### Mammography is gated by prefix, not by template

Its shared prompt opens with `SECTION 0 — REGEX-LOCKED JSON SCHEMA (HARD ENFORCEMENT)`
and returns `Breast Composition`, `Normal Findings {Right Breast, Left Breast}`,
`Axillary Evaluation`, `BI-RADS Category {Right Breast, Left Breast}` — with **no
`Impression` and no `Recommendations` keys**. The template's `OUTPUT` slot defines the
five-key contract and would emit the wrong shape. So the gate contributes a prefix and
the shared prompt follows untouched.

The consequence is stated because it looks like a regression otherwise: **mammography
gains coverage and loses brevity**, 9,714 → 10,916 tok. A shorter prompt that fails to
parse is worth nothing.

### 2.9 The correction frame

Turbo in the Correction tab prepends `build_turbo_correction_prefix()` to the shared
correction prompt: *edit, do not generate*; do not regenerate Normal Findings; do not
introduce or remove findings; do not change a measurement, laterality, anatomical
location, diagnosis, Impression or Recommendation unless the request requires it;
return the COMPLETE corrected report.

A prefix again, and for the same reason: the correction response is parsed, and the
shared correction prompt carries a contract that was hard to get right — a mammography
report has eleven keys, not five.

---

## 2.2 The component decomposition

The v2 template (`turbo_template.py`) defines **nine slots** in a fixed order. This is the
canonical decomposition; mobile implementations should reproduce these names.

| # | Slot | Owner | Contents | ~tok |
|---|---|---|---|---|
| 1 | `ROLE` | shared | who the model is, what it returns, output language | 74 |
| 2 | `PRECEDENCE` | shared | what wins when two instructions conflict | 77 |
| 3 | `TWO_HALVES` | shared | transcription vs generation — the central idea | 56 |
| 4 | `RULES_PATHOLOGICAL` | shared | source fidelity; one bullet per observed failure | 412 |
| 5 | `RULES_NORMAL` | shared | the 5-step generation method, register, contrast, sex | 560 |
| 6 | `MODALITY` | per modality | how to describe findings in this modality | 16-48 |
| 7 | `STUDY_CONTEXT` | per study | structured facts, each with provenance | ~90 |
| 8 | `REPORTING_CONTEXT` | **per region, gated** | one self-contained package per selected region | ~400 each |
| 9 | `OUTPUT` | shared | the JSON contract and text layout | 146 |

Shared total: **1,325 tokens**, identical for every study. Measured, not estimated:
`ROLE 74 + PRECEDENCE 77 + TWO_HALVES 56 + RULES_PATHOLOGICAL 412 + RULES_NORMAL 560
+ OUTPUT 146`. The modality note adds 16 (mammography) to 48 (CT).

**The order is deliberate.** Role and task first — the prompt this replaced opened on a
formatting constraint and never stated the task at all. Facts before guidance, so the
guidance can refer to them. Output contract last, for recency.

### Mapping to the components you asked about

| Component | Where it lives |
|---|---|
| Shared / core instructions | `ROLE`, `PRECEDENCE`, `TWO_HALVES` |
| Pathological Findings — shared rules | `RULES_PATHOLOGICAL` |
| Pathological Findings — region-specific | `REPORTING_CONTEXT` → each module's `pathology` |
| Normal Findings — generation rules | `RULES_NORMAL` |
| Normal Findings — region-specific context | `REPORTING_CONTEXT` → each module's `headings` + `normal` |
| Output / JSON / parsing | `OUTPUT` |
| Impression rules | last bullet of `RULES_PATHOLOGICAL` |
| Recommendation rules | same bullet — they are one rule, stated once |
| Physician transcript | the **user** message, never the system message |

---

## 2.3 What is gated and what is not

```
ALWAYS SENT                                     1,341-1,373 tok
  ROLE · PRECEDENCE · TWO_HALVES
  RULES_PATHOLOGICAL · RULES_NORMAL
  MODALITY note
  OUTPUT

PER STUDY                                              ~90 tok
  STUDY_CONTEXT — patient, modality, regions, contrast, service, protocol

SELECTED BY THE GATE                              ~400 tok each
  REPORTING_CONTEXT — one block per region:
      Headings, in this order
      Pathological findings, when he dictates them
      Normal-findings reference
      Dictation terms you may encounter
      Notes
```

A one-region study lands near **1,800–2,000 tok**; measured range across all 21 regions is
**1,790 (thyroid) to 2,335 (extremity)**, median 2,053.

### Impression and Recommendations are shared, not gated

They are a *presence* rule, not region knowledge: appear only if he dictated one; if he
did, preserve it intact; if he did not, omit the key. That is true of a knee CT and a
mammogram equally, so it stays in the shared slot and is stated once.

### Classification systems ARE gated

This is the part that used to be shared and should not have been. The shared prompt sends
every study the same nine-system list — a brain CT is told about BI-RADS, PI-RADS, O-RADS,
LI-RADS, TI-RADS and Lung-RADS; a mammogram is told about Fleischner and Bosniak. Systems
now belong to the region that uses them:

```
Fleischner · Lung-RADS      → Chest
Bosniak · LI-RADS · Balthazar → Abdomen
ASPECTS                     → Brain
TI-RADS                     → Neck
O-RADS · PI-RADS            → Pelvis
AO/Magerl                   → the four spine gates
Neer · Ideberg · Walch · Goutallier → Shoulder
Judet-Letournel · Pipkin    → Hip
Schatzker · Dejour          → Knee
Sanders · Hawkins · Lauge-Hansen · Myerson → Ankle and foot
Herbert · Frykman           → Wrist and hand
Lund-Mackay · Keros         → Paranasal sinuses
Le Fort · Zingg · Markowitz-Manson → Maxillofacial
BI-RADS · CAD-RADS          → no CT region — correctly absent
```

The shared bullet keeps only the safety rule — *never invent a category he did not give* —
and points forward: *"The systems that apply to this study … are named in REPORTING CONTEXT."*

`test_a_region_never_sees_another_regions_classification_system` fails the build if a
region shows a system it does not own.

---

## 2.4 Rules that are load-bearing and must survive any rewrite

Each of these exists because of an observed failure. Nine are verified present by literal
probe in `test_turbo_template.py`; do not paraphrase them away.

| Rule | The failure it encodes |
|---|---|
| `"The liver is normal."` is not acceptable | verdict-register output that told the clinician nothing |
| `کد طبیعی` · `کد نرمال` · `تمپلیت نرمال` · `نرمال بیاد` · `بقیه طبیعی` · `مابقی طبیعی` | the normal-template request, in dictation |
| `دگنش` | a real STT corruption of `دیگه‌اش`; judge by intent, not spelling |
| `"No pathological findings are identified."` | empty Pathological Findings threw away a valid normal report, twice |
| `"may represent"` must not become `"represents"` | models normalise language toward confidence |
| `"Right occipital lobe"` stays the right occipital lobe | laterality drift → wrong-side report |
| `"never invent one"` | measurement / grade / category fabrication |
| `Never infer the patient's sex` | sex-specific organs in the wrong report |
| `no code fences` | JSON parse failures |

---

## 2.5 Assembly, step by step

```python
# turbo_template.render()
parts = [ROLE, PRECEDENCE, TWO_HALVES, RULES_PATHOLOGICAL, RULES_NORMAL]
if MODALITY_NOTES.get(modality):    parts.append("# MODALITY — …")
if render_study_context(facts):     parts.append(…)      # only non-empty facts render
if render_region_context(modules):  parts.append(…)      # region-major, gate order
parts.append(OUTPUT)
return "\n".join(p.rstrip() + "\n" for p in parts)
```

`render_region_context` is **region-major**: one self-contained block per region, in gate
order, each carrying its own headings, pathology rules, normal reference, terms and notes.
Adding a region adds exactly one block.

An earlier draft merged section-wise, guarding against "two competing reporting orders".
That failure belonged to the old prompt, where each region fragment carried its own
`REPORT ORGANIZATION` rule. A module carries a heading **list**, not an ordering rule — the
rule lives once, in `OUTPUT` — so blocks in gate order state exactly one order.

Dictation terms de-duplicate first-wins across regions, so the always-on Persian lexicon
reaches the model once rather than once per region.

### The two mentions of "regions" are not duplication

`STUDY_CONTEXT` carries `Regions  chest, abdomen  (auto-detected)`. `REPORTING_CONTEXT`
carries the packages. They are different things at different precedence levels:

- the row is the gate's **conclusion**, a fact with provenance, at precedence 3
- the context is **guidance**, at precedence 4, explicitly not a limit on what may be reported

They also legitimately differ. `_render_template` proceeds when *some* region has a module,
so a detected region with no package appears in the row and not in the slot; `pelvis` +
`prostate` contribute two names and one block. When they differ, the model should see it.

---

## 2.6 The v1 narrowing path

For completeness, since it is what runs today. `build_turbo_system_prompt` calls the shared
`build_report_system_prompt`, then narrows three region-keyed spans in place:

| Span | What it is | Gated by |
|---|---|---|
| `GROUPING VOCABULARY (CT)` | organ order per region | `turbo_regions.section_for()` |
| `CT-SPECIFIC MEASUREMENT AND CLASSIFICATION RULES` | 15 bullets | region map |
| `RSNA normal findings per CT body region` | 19 region blocks, 4,823 tok | `turbo_regions.CT_BLOCKS` |

Each narrowing carries a **drift self-check** against the extracted library: if the span in
the live prompt no longer matches what was extracted, the narrowing declines rather than
cutting the wrong text. `_select_ct_blocks` returns `None`, never `[]`, so "no match" can
never be mistaken for "match nothing".

**v1 has the problem v2 was built to fix:** region content appears in three places that
have to agree. On study 53516, chest and abdomen content is in the grouping vocabulary, in
the measurement rules and in the RSNA block.

---

## 2.7 Authoring rules

Written into the module docstring so they are enforced where the editing happens, and
three of them are enforced by tests directly on the shared slots.

1. State the desired behaviour. Reserve prohibitions for the safety boundary.
2. Say it **once**. If it needs saying twice, the first place was wrong.
3. No emphasis markers. Precedence is declared in `PRECEDENCE`, not by shouting.
4. Prefer one good example over a paragraph of description.
5. Facts go in `STUDY_CONTEXT`, instructions go in `RULES`. A conditional reading
   *"if the sex is unknown…"* usually means a fact belongs in the context block.

For reference, the prompt this replaced carried 23 emphasis markers (one every 17 lines),
stated `RSNA` nine times and the nodal threshold three times, and was 13% leading
whitespace.

---

## 2.8 Known open issues

- **The worked example in `RULES_PATHOLOGICAL` is a liver lesion**, shown to every study
  including a brain CT. Moving examples into the region packages is a separate change.
- **Contrast is not used as a filter.** Four regions carry normal lines that only make
  sense with contrast — brain 5 of 18, paranasal sinuses 3 of 9, temporal bone 2 of 13,
  abdomen 1 of 12 — while `RULES_NORMAL` says to say nothing about enhancement without
  contrast. The fix is the same idea as region gating applied to a second axis the content
  already varies on: split `normal` into unconditional and contrast-only lines and include
  the second list only when the study had contrast.
- **v2 has not been evaluated against real transcripts.** The 81% reduction is arithmetic;
  that it produces equal or better reports is a hypothesis.
