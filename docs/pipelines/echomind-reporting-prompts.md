# EchoMind Reporting Prompts — Architecture & Physician-Content Preservation (as-built)

**Last updated:** 2026-07-09 · **partly superseded 2026-08-09**

> Read [`docs/echomind/README.md`](../echomind/README.md) first. This document is still
> correct about the per-modality prompt bodies, the preservation rule and the validator.
> Its claim that the prompt is selected **by modality only** no longer holds for Turbo on
> CT, where a region gate selects the region-specific content - see
> [`docs/echomind/02-prompt-architecture.md`](../echomind/02-prompt-architecture.md).
**Owner module:** `modules/EchoMind/viewer_chat/`
**Purpose of this doc:** single reference so future developers/agents never have to re-discover
where the report prompts live, which prompt serves each modality, how a prompt flows through the
pipeline, which steps can modify a finished report, and what has/has not been reviewed for the
**physician-provided Impression / Recommendation / Suggestion preservation** requirement.

> **Golden rule enforced across all prompts:** The model must **never independently generate** a
> new impression, recommendation, suggestion, follow-up, or clinical/laboratory/pathologic
> correlation. But it must **always preserve** any such content the **physician explicitly
> dictated** — never delete, omit, weaken, or soften it. See "Preservation rule" below.

---

## 1. Where the prompts live (files & format)

| What | Location | Format | Authoritative? |
|------|----------|--------|----------------|
| **Report generation prompts (default / company path = GapGPT-direct)** | `modules/EchoMind/viewer_chat/openai_reporter.py` → `reporter()` (starts line **244**) | **Python** (f-strings + triple-quoted literals assembled at call time) | ✅ **YES** — this is what the app sends on the default backend |
| **Report generation prompt (OpenAI backend)** | `modules/EchoMind/viewer_chat/openai_parallel_backend.py` → `reporter()` (line **77**) | Python (short "twin" prompt, override-driven) | ✅ YES — used only when `llm_backend == "openai"` |
| **Standardize / Correction / Translate (default path)** | `openai_reporter.py` → `standardize()` (2833), `correction()` (~3041), `translate_report()` (2531), `translate_text_to_persian()` (2462) | Python | ✅ YES |
| **Standardize / Correction / Translate (OpenAI backend)** | `openai_parallel_backend.py` (`standardize` 214, `correction` 232, `translate_report` 178) | Python | ✅ YES |
| **Prompt exports (review copies)** | `modules/EchoMind/viewer_chat/prompts/*.json` | JSON | ❌ **NO** — verbatim *snapshots* exported 2026-06-28; **not wired to any loader**, do **not** drive runtime, and are now **stale** vs the Python source. Treat as documentation only. |

**Key fact:** prompts are **Python, not config/JSON**. The `prompts/*.json` files are a read-only
export for manual review and are not loaded by the app. Edit the Python source to change behavior.

---

## 2. Backend selection (which prompt module runs)

`ai_chat_pages.py` ~line **2921**:

```python
reporter_fn = openai_direct.reporter if backend == "openai" else reporter
```

- **Default / "company"** backend → `openai_reporter.py` (GapGPT-direct, rich per-modality prompts).
- **`openai`** backend → `openai_parallel_backend.py` (short twin prompts; settings-driven).

Both backends were reviewed and both now carry the preservation rule.

---

## 3. Modality → Body Part → Prompt Location → Purpose → Status

The report prompt is selected **by MODALITY only**, inside `reporter()` via
`modality_lower = modality.lower()`. **Body part is NOT a separate prompt** — each modality prompt
handles all its body regions internally (embedded RSNA/ACR per-region "Normal Findings" blocks and
region-aware Report-Title rules). This is by design: one carefully-tuned prompt per modality, with
body-part logic inside it. There is **no per-body-part prompt file/branch.**

| Modality (menu value) | `modality_lower` match | Branch (openai_reporter.py) | Body-part handling | Output schema | Preservation rule | Status |
|---|---|---|---|---|---|---|
| **CT** | `ct` | line **283** | RSNA CT regions embedded (head/chest/abdomen-pelvis/spine/MSK/angio) | `Report Title, Pathological Findings, Normal Findings, Impression?, Recommendations?` | Presence-lock **+ new CT PRESERVE clause** | ✅ Reviewed & fixed |
| **MRI** ⭐ confirmed problem area | `mri` | line **619** | RSNA MRI regions embedded (brain/spine/MSK/breast/abdomen-pelvis) | same as CT | Presence-lock **+ new MRI PRESERVE clause** + broadened triggers | ✅ Reviewed & fixed |
| **Ultrasound** (menu "SONOGRAPHY") | `sonography` / `ultrasound` | line **1199** | General US + OB/GYN regions embedded | same as CT | Presence-lock **+ new ULTRASOUND PRESERVE clause** | ✅ Reviewed & fixed |
| **Mammography** (menu "MAMOGRAPHY") | `mammography` / `mamography` / `mammogram` / `mamogram` | line **1422** | Breast (regex-locked BI-RADS schema) | `Report Title, Breast Composition, Pathological Findings, Normal Findings{R,L}, Axillary Evaluation, BI-RADS Category{R,L}` — **no Impression/Recommendations keys** | **New SCHEMA-SAFE PRESERVE clause (SECTION 0b)** — keep dictated impression/rec inside Pathological Findings / BI-RADS; never add keys | ✅ Reviewed & fixed |
| **Radiology / X-ray** (menu "RADIOLOGY") | `radiology` | line **1769** | X-ray/DEXA/bone-age/barium regions embedded | same as CT | Presence-lock **+ new RADIOLOGY PRESERVE clause**; also **fixed a contradicting "Absolutely no suggestions/recommendations" block** to exempt physician content | ✅ Reviewed & fixed |
| **Obstetric Ultrasound** | `obstetric ultrasound` / `ob ultrasound` / `pregnancy ultrasound` / `fetal ultrasound` | line **996** | ISUOG structured OB schema | `... Impression, Recommendations (OMIT if routine)` | SECTION 9 lock **+ preserve distinction added**; softened "OMIT if routine" to keep dictated recs | ✅ Reviewed & fixed — ⚠ **but see §6: not reachable from the standard modality menu** |
| **Generic fallback** (unknown modality string) | `else` | ~line **2065** | inferred | inferred | **New PRESERVE bullet added** | ✅ Reviewed & fixed |
| **No modality provided** | outer `else` | ~line **2072** | inferred | inferred | **New PRESERVE bullet added** | ✅ Reviewed & fixed |

Menu source: `ai_chat_pages.py` line **1258** → `["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]`.

---

## 4. Prompt processing flow (end to end)

```
User dictation (composer)
   │  (optional) "Standardize" button → standardize()  → cleaned Persian/English + dictated
   │                                                      impression/recommendation arrays
   ▼
_send_with_mode(text, "Report", modality=<menu value>)   [ai_chat_pages.py]
   ▼
reporter_fn = openai_direct.reporter (openai)  |  reporter (default/company)   [~line 2921]
   ▼
reporter(user_msg, modality, normal_template, ...)        [openai_reporter.py:244]
   ├─ template_logic     (user normal-template override vs RSNA auto)
   ├─ modality_logic     = base + PER-MODALITY specific_instructions  ← the per-modality prompt
   ├─ system_prompt      = English-only header + template_logic + normal_template + modality_logic
   └─ POST to GapGPT (or chat_completion for openai backend)
   ▼
raw JSON report  → _validate_report_json() (mri/ct only: ensures keys, nulls empties — never drops
                    a non-empty Impression/Recommendations)
   ▼
_normalize_report_like_payload() → render bubble
   │
   ├─ (optional) "Correct" → correction()      — editor; preserves unaffected sections
   └─ (optional) "Persian" → translate_report() — preserves keys/structure & all clinical info
```

**Post-processing steps that could modify a finished report** and their preservation status:

| Step | Function | Can it drop physician content? | Notes |
|------|----------|-------------------------------|-------|
| Standardize | `standardize()` (2833) | No | Upstream of report; extracts impression/recommendation **only if explicitly dictated** and "preserves original wording"; keeps content in `cleaned_sentences` regardless. |
| Correction | `correction()` (~3041) | No | Pure editor: only edits sections named in the correction note; "all other sections must remain EXACTLY unchanged"; forbids *inventing* new content. |
| Translate | `translate_report()` (2531) | No | "Do not add, remove, or modify any clinical information"; preserves keys/structure. |
| Validate (mri/ct) | `_validate_report_json()` (197) | No | Only nulls **empty** optionals and inserts missing keys as null; never removes a non-empty Impression/Recommendations. |

---

## 5. The preservation rule (what was added to each prompt)

Every report prompt now states the same **distinction** (tailored in wording per prompt, **not** a
single shared/central block — see §7):

- **FORBIDDEN:** do NOT independently generate/invent/infer/expand a NEW impression, conclusion,
  differential, suggestion, follow-up advice, clinical/laboratory/pathologic correlation, biopsy
  recommendation, further-imaging recommendation, or management recommendation the physician did
  **not** provide.
- **MANDATORY:** ANY impression / conclusion / suggestion / recommendation / follow-up /
  clinical-laboratory-pathologic correlation the physician **explicitly dictated** is SOURCE
  CONTENT and MUST be preserved (meaning & intent intact) — e.g. *"the above findings are
  suggestive of ..."*, *"clinical correlation is recommended"*, *"correlation with laboratory
  findings is recommended"*, *"further evaluation is recommended"*, *"biopsy is recommended"*.
- The "do not generate" rules apply **only** to content the physician did not provide; they
  **never** authorize deleting/omitting/weakening/softening physician-dictated content.
- **Placement:** put preserved content in the report's `Impression`/`Recommendations` fields when
  the modality schema has them; for the **regex-locked mammography** schema (no such fields), keep
  it inside `Pathological Findings` / `BI-RADS Category` and **never add keys**.

The four modality prompts that already had a "PRESENCE-LOCK" (CT, MRI, Ultrasound, Radiology) kept
it and had their recommendation trigger lists **broadened** to explicitly name *clinical /
laboratory / pathologic correlation, further evaluation, further imaging*.

---

## 6. Findings discovered during review (important)

1. **Mammography menu spelling bug (fixed).** The menu emits `"MAMOGRAPHY"` (one `m` →
   `"mamography"`), but the branch matched only `"mammography"`, so mammography dictations fell
   through to the **generic fallback** and never used the BI-RADS mammography prompt. The branch
   now accepts `("mammography", "mamography", "mammogram", "mamogram")`. *(Consider also adding
   `"mamography"` to `_VALIDATED_MODALITIES` if you want the mammography temperature/token tuning to
   apply — currently only mri/ct are post-validated, so not required for correctness.)*
2. **Obstetric-Ultrasound branch is currently unreachable from the standard menu.** The menu sends
   `SONOGRAPHY` → the general `["sonography","ultrasound"]` branch (1199), not the
   `obstetric ultrasound` branch (996). The OB branch only runs if a caller passes literally
   `"obstetric ultrasound"` (etc.). It was still reviewed/fixed, but confirm the intended
   entrypoint if OB reports should use the ISUOG prompt.
3. **Radiology had a self-contradiction (fixed).** Its prompt contained both a preserve rule and an
   older *"4. Absolutely no: Suggestions … recommendations"* block (which even banned the word
   "suggestion"). That block now explicitly applies only to **self-generated** content and exempts
   physician-dictated content.
4. **JSON exports are stale.** `prompts/*.json` no longer match the Python source. Regenerate them
   (or delete) in a follow-up; do not rely on them.

---

## 7. Architecture decision: per-prompt rules, NOT one central rule

A first attempt added a single shared preservation block to the assembled `system_prompt`. This was
**reverted** per the maintainer directive: prompts must stay **independently customized per
modality** so each can be optimized for its own report quality, and a central block does not fit a
fixed/regex-locked schema (mammography) cleanly. The rule now lives **inside each modality branch**,
tailored to that prompt's structure. The guard test enforces that each branch carries its **own**
modality-named preservation header.

---

## 7b. Sex-specific anatomy handling (2026-07-09)

**Problem:** the auto-generated RSNA "Normal Findings" blocks listed BOTH male and female pelvic
organs with a weak `(if applicable)` marker, so a pelvic/abdomino-pelvic report could contain
*"Prostate is unremarkable"* **and** *"Uterus/ovaries unremarkable"* at once, and could invent a
sex the physician never stated.

**Rule now enforced (per-prompt, independently):** Do NOT infer/assume the patient's sex. Include a
sex-specific organ (prostate, uterus, ovaries, seminal vesicles, cervix, vagina, testes) ONLY IF the
physician explicitly mentioned it (or gave a finding that requires it); otherwise OMIT it entirely —
never emit a normal/"unremarkable" statement for it — and NEVER output both male and female organs in
the same report.

**Where it was fixed (each edited individually, not one global rule):**

| Location | Change |
|----------|--------|
| CT branch → `– PELVIS CT:` normal-findings | Added SEX-SPECIFIC ANATOMY RULE block; uterus/ovaries/prostate/seminal vesicles changed from `(if applicable)` → "INCLUDE ONLY IF the physician explicitly mentioned … (Otherwise OMIT entirely.)" |
| MRI branch → `– ABDOMEN / PELVIS:` normal-findings | Added SEX-SPECIFIC ANATOMY RULE; "Female pelvis"/"Male pelvis" changed from `(if applicable)` → explicit-mention-only + "never both" |
| Ultrasound branch | Prostate line + GYNECOLOGIC section (uterus/ovaries/cervix) gated to explicit-mention-only; added SEX-SPECIFIC ANATOMY RULE header |
| `template_logic` (both branches) | Sex caveat added: auto path enforces the rule; user-template override path must NOT auto-complete unmentioned sex organs even if the template lists them |
| `openai_parallel_backend.reporter()` | One-line sex rule added |

**Not a source of the bug:** OB/obstetric ultrasound (inherently female/pregnancy), mammography
(breast-only), and `standardize()`/`correction()`/`translate()` (no organ insertion). The
`normal_template` is a **user-authored per-session file** (`<sid>-normal_template.json`), not a shipped
default — there is no built-in template that ships both sexes.

---

## 7c. Non-obstetric ultrasound — exam-specific normal templates (2026-07-09)

**Problem:** the non-OB ultrasound prompt had a single thin "RSNA NORMAL FINDINGS — GENERAL
ULTRASOUND" list (liver/GB/pancreas/kidneys/spleen/bladder/prostate/soft-tissue, no measurements),
so normal reports were only a few generic lines and not exam-specific.

**Change:** replaced that flat list with an **exam-specific normal-template library** inside the
`["sonography","ultrasound"]` branch. The model is instructed to detect the ONE exam type and build
Normal Findings from only that template, organ-by-organ, with standard terminology and normal
**reference** measurements (stated as normal thresholds, not fabricated patient values). Templates
provided: Complete Abdominal, Hepatobiliary/RUQ, Renal-Urinary (KUB), Pelvic-Male, Thyroid/Neck,
Breast, Scrotal/Testicular, Carotid/Vertebral Doppler, Extremity Venous (DVT), Extremity Arterial,
Appendix/RIF, Soft-tissue/Superficial/MSK. The **Gynecologic / female-pelvic** block was expanded
with uterine dimensions, endometrial thickness by phase, and ovarian volume.

**Untouched (by request):** the obstetric (ISUOG) template — it already follows protocol. The
sex-specific anatomy rule (§7b) and physician-content preservation rule (§5) inside the ultrasound
branch are retained. Guard: `test_non_ob_ultrasound_has_exam_specific_normal_templates`.

---

## 7d. Correction workflow — final targeted-revision (PATCH) step (2026-07-09)

**What it is:** the last revision stage. The physician selects a previously generated report and
writes a correction note; the model must apply ONLY that change and return the complete report.
UI entry points: `_send_report_correction` (Report mode) and `_send_correction` (ChatGPT mode) in
`ai_chat_pages.py`; both call `correction()` (company path = `openai_reporter.py`, OpenAI path =
`openai_parallel_backend.py`).

**Problems found & fixed:**

| Problem | Fix |
|---------|-----|
| Company/GapGPT path hard-coded the **weak** `gpt-4.1-mini` for correction | Both UI callers now use `_ai_model("correction", "gpt-5.4", backend)`; `correction()` default model raised to `gpt-5.4`. On the OpenAI backend the `correction` feature maps to `report_model` (default `gpt-5.4`), configurable in Settings — set a stronger model there (e.g. `gpt-5.5`) if/when available. |
| **No temperature** set → API default (~1.0) encouraged rewriting unrelated content | `temperature: 0` pinned on both backends (surgical patch, deterministic). `max_tokens: 3000` on the company path. |
| Payload was a loose `ORIGINAL_REPORT:… CORRECTION_NOTE:…` string | Restructured into clearly-delimited `===== ORIGINAL_REPORT =====` / `===== CORRECTION_NOTE =====` blocks with an explicit instruction to change only what the note requires and return the complete report. |
| No channel for the **exact section/sentence/line/finding** to change | Added optional `target_section` param → a separate `===== TARGET_LOCATION =====` block (present only when supplied; the model otherwise locates the target from the note). Prompt gains a "LOCATE the target, then patch" step. The UI can pass a highlighted selection here in future; the field is wired end-to-end. |
| OpenAI-backend correction used a 1-line system prompt | Replaced with the full PATCH/preserve system prompt (change only the target; keep everything else byte-identical; don't add findings; don't delete valid info; preserve terminology/structure; return all 5 keys). |

The strong company-path PATCH system prompt (PATCH-not-regenerate, preserve-all, minimal-edit,
literal-dependency-only propagation) was already present and is retained. Response processing
(strip `<|end|>`, parse JSON, re-register for further corrections) is unchanged and adequate.

Guards: `test_correction_is_deterministic_and_structured`,
`test_correction_target_location_block_is_conditional`,
`test_correction_backend_uses_correction_feature_and_temp0`.

---

## 8. Tests

- **Guard test:** `tests/code/echomind/test_report_prompt_preservation.py`
  - Assembles each modality's real `system_prompt` (network stubbed) and asserts the preservation
    rule + `clinical correlation` + `biopsy` appear in **every** modality prompt.
  - Asserts the `MAMOGRAPHY` alias routes to the regex-locked mammography prompt.
  - Asserts each modality branch has its **own** preservation header (no reliance on a central rule).
  - **Sex-specific anatomy:** asserts CT/MRI/Ultrasound prompts carry the sex rule (do-not-infer +
    include-only-if-mentioned + never-both), that no weak `(if applicable)` sex-organ conditional
    remains in source, and that the template-override path has the sex caveat.
  - Run: `python -m pytest tests/code/echomind/test_report_prompt_preservation.py -p no:debugging -q`
- **Backend twin:** `openai_parallel_backend.reporter()` preservation wording verified present.

---

## 9. Review status

| Prompt | Reviewed | Changed | Notes |
|--------|:---:|:---:|-------|
| MRI (openai_reporter) | ✅ | ✅ | Confirmed problem area; PRESERVE clause + broadened triggers |
| CT (openai_reporter) | ✅ | ✅ | PRESERVE clause + broadened triggers |
| Ultrasound (openai_reporter) | ✅ | ✅ | PRESERVE clause + broadened triggers |
| Radiology (openai_reporter) | ✅ | ✅ | PRESERVE clause + fixed contradicting "Absolutely no" block |
| Mammography (openai_reporter) | ✅ | ✅ | Schema-safe SECTION 0b clause + spelling alias |
| Obstetric US (openai_reporter) | ✅ | ✅ | SECTION 9 preserve distinction; verify entrypoint (§6.2) |
| Generic / no-modality fallback | ✅ | ✅ | PRESERVE bullet |
| `openai_parallel_backend.reporter()` | ✅ | ✅ | PRESERVE wording (prev. session) |
| standardize / correction / translate (both backends) | ✅ | ⬜ | Already preserve-safe; no change needed |
| **Live source-build clinical verification** | ⬜ | — | **PENDING** — dictate MRI (+ CT, mammography) with an impression + a recommendation; confirm both survive into the rendered report |

**Pending / follow-ups:** live clinical-lane verification (above); regenerate or delete stale
`prompts/*.json`; decide OB-US entrypoint; optional `_VALIDATED_MODALITIES` mammography alias.
