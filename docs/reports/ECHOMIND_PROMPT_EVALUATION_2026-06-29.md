# EchoMind Prompt Evaluation Report
**Date:** 2026-06-29  
**Files reviewed:**  
- `modules/EchoMind/viewer_chat/openai_reporter.py` (all 2556 lines)  
- `modules/EchoMind/viewer_chat/prompts/*.json` (8 exported prompt files)

---

## Executive Summary

The EchoMind prompt system is structurally sound for its core goal (Persian-dictation → structured English JSON radiology report), with strong RSNA/ACR/BI-RADS vocabulary and well-designed examples. However, there are **2 critical safety/correctness issues**, **4 high issues**, and several medium/low issues that should be addressed before any production expansion.

The most urgent item is a legacy "extreme exaggeration" instruction that was never removed from the CT and X-ray prompts — it directly instructs the model to use "vivid, dramatic phrasing" in a clinical reporting context.

---

## Critical Issues — Must Fix Immediately

### C1. "Extreme Exaggeration" Legacy Instruction in CT and X-ray Prompts

**Files:** `openai_reporter.py` — CT branch (~line 314) and X-ray/Radiology branch (~line 1219)  
**Exported:** `turbo_ct.json`, `turbo_xray.json`

Both the CT and X-ray `specific_instructions` strings end with a concatenated legacy block that was never cleaned up. The legacy block explicitly instructs:

```
"3. Language & Tone:\n"
" • ANSWER MUST STRICTLY IN ENGLISH.\n"
" • Use *extreme exaggeration*—vivid, dramatic phrasing.\n"
```

This instruction directly contradicts every other rule in those prompts, which require:
- "Interpret strictly based on user input with zero speculation"
- "Do not generate any diagnosis, differential diagnosis, or recommendations unless explicitly provided"
- "Ensure no additional implications or speculative thinking are added"

**Risk:** A model following "extreme exaggeration — vivid, dramatic phrasing" in a CT or X-ray report could produce non-clinical, sensationalist, or misleading output. This is a clinical safety issue — radiology reports are used for patient care decisions.

**Fix:** Delete the entire legacy block from both branches (lines ~314–362 in CT, lines ~1195–1244 in X-ray). The clean RSNA sections above those blocks are complete and correct on their own.

---

### C2. Schema Conflict: Correction Always Forces 5 Keys; Turbo Uses Conditional Keys

**Files:** `openai_reporter.py` — `correction()` function (~line 2357), all Turbo `reporter()` branches  
**Exported:** `correction.json`

The Turbo report prompts (MRI, CT, Ultrasound, X-ray) state:
> "If Impression/Recommendations do NOT exist in input, OMIT those keys entirely."

The `correction()` function states the exact opposite:
> "You MUST ALWAYS output a corrected report as a SINGLE JSON object with EXACTLY these 5 keys (NO MORE, NO LESS): ... Impression ... Recommendations"

And the REPORT SECTION LOGIC says:
> "• Impression (always present)  
> • Recommendations (always present)"

**Impact:** A physician generates a Turbo report with no dictated Impression/Recommendations → JSON has 3 keys. If they then request a correction, `correction()` returns 5 keys with invented/empty Impression and Recommendations fields. The downstream parser (which expects the Turbo 3-key schema) will fail or silently accept fabricated empty fields into the report.

The correction function also says "Never create new medical content to populate empty/unknown fields" — which directly contradicts forcing a non-empty "Impression" key when none existed.

**Fix:** Add a conditional schema rule to `correction()`: if the incoming `ORIGINAL_REPORT` JSON does not contain "Impression" and/or "Recommendations" keys, do NOT add them to the corrected output. Mirror the Turbo presence-lock semantics.

---

## High Issues — Should Fix Before Next Release

### H1. X-ray Modality String Match Is Fatally Narrow

**File:** `openai_reporter.py` line 1048: `elif modality_lower == "radiology":`

The X-ray/Radiology branch activates only on the exact lowercase string `"radiology"`. Every other spelling silently falls to the generic `else` branch and gets a 2-line generic prompt:

| Input `modality=` | Route |
|---|---|
| `"Radiology"` | ✅ X-ray branch |
| `"X-ray"` | ❌ generic fallback |
| `"xray"` | ❌ generic fallback |
| `"Radiography"` | ❌ generic fallback |
| `"Chest X-ray"` | ❌ generic fallback |
| `"Plain Film"` | ❌ generic fallback |

This is documented in `turbo_xray.json` as `"modality_match": "radiology"` — technically correct, but the constraint is invisible to the calling code and very easy to trigger accidentally.

**Fix:** Expand the match condition:
```python
elif any(k in modality_lower for k in ("radiology", "xray", "x-ray", "radiograph", "plain film", "dexa", "barium", "bone age", "bone density")):
```

---

### H2. Four Different Output Formats, One Downstream Parser

The four main endpoints return inconsistent output structures:

| Function | Output format |
|---|---|
| `reporter()` Turbo | Raw JSON + `<|end|>` appended (no fences) |
| `correction()` | ` ```json\n...\n``` ` + `<|end|>` (with markdown fences) |
| `translate_report()` | ` ```json\n...\n``` ` + `<|end|>` (with markdown fences) |
| `standardize()` | Raw JSON only (no `<|end|>`, no fences) |

The downstream parser must handle all four variants. If any parsing code assumes raw-JSON + `<|end|>`, it will fail on correction output. If any code strips code fences universally, it may corrupt raw Turbo output.

**Fix:** Pick one output contract and enforce it consistently across all functions. Recommended: raw JSON + `<|end|>` (no markdown fences) everywhere.

---

### H3. `translate_report()`: Plain-Text Format Instruction Contradicts JSON Example

**File:** `openai_reporter.py` `translate_report()` function (~line 1821)

The system prompt first instructs:
```
Output Format
Return the translation in the following format:
Translated Radiology Report (EN → FA)
[Pathological Findings]
... Persian translation ...
[Normal Findings]
... Persian translation ...
```

Then immediately the FORMAT-MATCHING RULES section requires:
```
"The JSON OUTPUT MUST strictly follow the same structural pattern as the English base report JSON"
"The keys must remain exactly the same (e.g., 'Report Title', 'Pathological Findings', 'Normal Findings')"
```

And the example shows a JSON object. The model is given two mutually exclusive output formats in the same prompt. The JSON example at the end likely wins (examples override instructions in most models), but the behavior may be inconsistent across calls.

**Fix:** Remove the plain-text "Output Format" block. Keep only the JSON STRICT FORMAT-MATCHING section and the example.

---

### H4. `reporter()` Has No Temperature or `max_tokens` Control

**File:** `openai_reporter.py` `reporter()` function (~line 1269)

The Turbo report payload:
```python
payload = {
    "model": ...,
    "messages": [...],
}
```

No `temperature`, no `max_tokens`. Compare to `ImageQualityAnalyzer()` which correctly uses `temperature=0.2, max_tokens=2000`.

- **Temperature default** on most providers is 1.0. For clinical reporting this is far too high — it increases hallucination probability.
- **No max_tokens** means the model can generate arbitrarily long outputs, increasing cost and latency. For a structured 5-key JSON the output should be bounded (~1500–3000 tokens is ample).

Same issue affects `standardize()`, `chat()`, and `translate_report()`.

**Fix:** Add `"temperature": 0.1, "max_tokens": 2500` to `reporter()`, `"temperature": 0.1, "max_tokens": 1500` to `standardize()`.

---

## Medium Issues — Important Quality / Maintenance

### M1. 35-Line IMPRESSION/RECOMMENDATIONS Block Duplicated 4 Times

**Files:** CT, MRI, Ultrasound, X-ray branches in `reporter()`

The verbatim "CRITICAL: IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK (HARD RULE)" block (35 lines) is copy-pasted identically into all four modality branches. Any future change to the trigger phrases or hard constraints must be applied in 4 places; a missed copy diverges silently.

**Fix:** Extract to a module-level constant `_IMPRESSION_LOCK_INSTRUCTIONS = """..."""` and interpolate it: `f"{_IMPRESSION_LOCK_INSTRUCTIONS}"` in each branch.

---

### M2. Impression Trigger List Is Inconsistent Between `standardize()` and Turbo Prompts

`standardize()` uses these impression indicators:
```
"یافته ها به نفع" / "یافته ها به ضرر" / "جمع بندی" / "نتیجه گیری" / "Impression"
```

Turbo prompts use a superset:
```
"در مجموع", "مطرح‌کننده", "suggestive of", "compatible with", "به احتمال زیاد", etc.
```

The standardize step runs BEFORE turbo generation. If a physician dictates `"در مجموع..."` (which Turbo would treat as an impression trigger), `standardize()` would NOT extract it as impression. The Turbo prompt would then see it embedded in `cleaned_sentences` and extract it. The pipeline produces correct output, but the standardized intermediate representation is semantically inconsistent.

**Fix:** Align the impression trigger phrase lists between `standardize()` and the Turbo prompts, or document clearly that standardize does not guarantee complete impression extraction.

---

### M3. X-ray Legacy Block: Literal Typo `.n` Instead of `.\n`

**File:** `openai_reporter.py` line 1202

```python
"...and contrast fluoroscopic studies where relevant.n"
```

The `\n` newline escape is missing the backslash — `".n"` will appear literally in the assembled prompt as `.n`. This is a minor rendering issue but shows the legacy block is untested.

---

### M4. `correction()` REPORT SECTION LOGIC Claims Impression Is "Always Present"

**File:** `openai_reporter.py` correction() ~line 2406

```
REPORT SECTION LOGIC:
- Reports contain:
  • Impression (always present)
  • Recommendations (always present)
```

This is factually wrong per the Turbo contract. See C2 above. This documentation comment should be corrected to match reality.

---

### M5. `standard_assist_search()` Has a Stray `print()` Call

**File:** `openai_reporter.py` line 2097

```python
_log_usage_safe(m, center, model, prompt_tokens, completion_tokens, user_msg)
print()   # ← prints an empty line to stdout on every call
```

This is a debug artifact. Remove it.

---

## Low Issues — Code Quality

### L1. `chat()` and `correction()` Overlap in Purpose

Both `chat()` (line 1319) and `correction()` (line 2344) serve as report editors. `chat()` has its own system message:
> "You are a medical report editor. You will receive (1) USER_REPORT then (2) CORRECTION_NOTE."

This is the same role as `correction()`, but `chat()` lacks the strict 5-key schema enforcement and proper parameter separation. If `chat()` is a legacy precursor to `correction()`, it should either be removed or its docstring should clarify when to use which.

---

### L2. `reporter()` English-Only Header Is Placed Before the Persian Lexicon

The assembled system prompt starts with:
```
"IMPORTANT: You MUST respond ONLY in English. This rule is ABSOLUTE and applies regardless of the user's input language. Do NOT include any non-English text."
```

Immediately followed by the Persian/Finglish term tables (e.g., `"ارتولیز / آرتروز → osteoarthritis"`). The English-only rule is correct (it applies to OUTPUT), but a model reading "do NOT include any non-English text" might be confused about why the system prompt itself contains Persian text.

**Fix:** Clarify to: `"You MUST respond ONLY in English. The user's input may be in Persian/Finglish/English. Your OUTPUT must always be in English only."`

---

### L3. Standardize No-Comma Rule May Degrade Downstream Quality

`standardize()` forbids commas:
> "NEVER use commas. Use only '.' to end sentences."

Radiology reports require commas for precise description (sizes, bilateral findings, anatomical pairs: "A 2×3 cm, well-defined, hypodense lesion at the liver S7..."). When the comma-free standardized text is fed to the Turbo reporter as input, the reporter must reconstruct natural medical prose. In practice this works, but the atomic-sentence constraint may occasionally force grammatically awkward English translations.

This is a design trade-off, not a bug. It should be documented.

---

### L4. `BreastExpertAssistant` Prompt Is an Unformatted Wall of Text

**File:** `openai_reporter.py` line 1551

The `BreastExpertAssistant` prompt is assigned as one giant single-quoted string on a single logical line, with no triple-quote formatting. This is a maintenance and readability issue only.

---

## Per-Function Summary

| Function | Severity | Issues |
|---|---|---|
| `reporter()` CT branch | 🔴 Critical | C1 (extreme exaggeration), M1 (dup block), H4 (no temp) |
| `reporter()` X-ray branch | 🔴 Critical | C1 (extreme exaggeration), H1 (modality match), M3 (typo), M1 (dup block), H4 (no temp) |
| `reporter()` MRI branch | 🟡 Medium | M1 (dup block), H4 (no temp) |
| `reporter()` Ultrasound branch | 🟡 Medium | M1 (dup block), H4 (no temp) |
| `reporter()` Mammography branch | 🟢 Good | No critical issues |
| `correction()` | 🔴 Critical | C2 (schema conflict), H2 (output format) |
| `standardize()` | 🟡 Medium | M2 (trigger list), H2 (output format), L3 (no-comma) |
| `translate_report()` | 🟠 High | H3 (contradictory format), H2 (output format) |
| `translate_text_to_persian()` | 🟢 Good | No issues found |
| `chat()` | 🟡 Medium | L1 (overlap with correction) |
| `ImageQualityAnalyzer()` | 🟢 Good | No issues found |
| `BreastExpertAssistant()` | 🟢 Good | L4 (code style) |
| `standard_assist_search()` | 🟢 Good | M5 (stray print) |

---

## Recommended Fix Priority

1. **C1** — Delete the legacy "extreme exaggeration" block from CT and X-ray branches. 5-minute fix, high clinical safety impact.
2. **C2** — Make `correction()` conditional on incoming key presence for Impression/Recommendations.
3. **H4** — Add `temperature=0.1, max_tokens=2500` to `reporter()`, `temperature=0.1, max_tokens=1500` to `standardize()`.
4. **H1** — Expand X-ray modality match beyond `"radiology"`.
5. **H2** — Standardize output format: raw JSON + `<|end|>` everywhere, no markdown fences.
6. **H3** — Remove plain-text output format instruction from `translate_report()`.
7. **M1** — Extract the duplicated IMPRESSION/RECOMMENDATIONS block into a constant.
8. **M5** — Remove stray `print()` in `standard_assist_search()`.
