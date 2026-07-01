# Android EchoMind Synchronization Specification

**Document type:** Technical specification for a second AI Agent  
**Status:** Draft — 2026-07-01  
**Author:** Analysis of Windows DICOM Workstation (canonical) vs Android EchoMind app  
**Security note:** GapGPT bearer tokens and center credentials referenced in
`modules/EchoMind/viewer_chat/api_manager.py` (Windows) and `EchoMindCenters.kt` (Android)
are internal credentials. This document describes their *structure and resolution logic*
but does **not** include actual token values.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Repository Analysis — Windows Workstation (Canonical)](#2-repository-analysis--windows-workstation-canonical)
3. [Repository Analysis — Android App](#3-repository-analysis--android-app)
4. [Gap Analysis](#4-gap-analysis)
5. [Prompt System Documentation](#5-prompt-system-documentation)
6. [AI Workflow Documentation](#6-ai-workflow-documentation)
7. [Backend Communication Documentation](#7-backend-communication-documentation)
8. [Configuration Documentation](#8-configuration-documentation)
9. [Architecture Recommendations](#9-architecture-recommendations)
10. [Phased Migration Plan](#10-phased-migration-plan)
11. [Validation Checklist](#11-validation-checklist)

---

## 1. Executive Summary

EchoMind is an AI-powered radiology dictation and report generation module embedded in both
the AI-PACS Windows DICOM workstation and an Android companion app. The two implementations
share the same backend infrastructure (GapGPT / AI_BASE) but have diverged significantly in
prompt quality, feature coverage, and language support.

**The Windows workstation is the canonical implementation.** It contains:
- Fully developed bilingual (Persian–English) standardization
- Five modality-specific turbo report-generation prompts (CT, MRI, Ultrasound, X-ray,
  Mammography) with RSNA-compliant structure, Persian/Finglish terminology mappings, and
  IMPRESSION/RECOMMENDATIONS presence-lock rules
- A surgical-patch `correction()` function for post-approval edits
- A translation function
- A Normal Template system for radiologist-supplied default phrasing
- Full proxy support (direct / SOCKS5)

**The Android app** has the same UI flow (record → transcribe → standardize → generate →
send to reception) but uses generic English-only prompts hardcoded as Kotlin constants,
lacks `correction()` entirely, and has only one center key (`RAZI`) in its center registry.

This specification gives the implementing agent a complete, actionable roadmap to bring the
Android implementation to parity with Windows across six phases.

---

## 2. Repository Analysis — Windows Workstation (Canonical)

### 2.1 File Layout

| Path | Role |
|------|------|
| `modules/EchoMind/viewer_chat/openai_reporter.py` | **Core AI backend.** Contains `standardize()`, `correction()`, `reporter()` (turbo), `chat()`, and `translate()`. ~3 000 lines. |
| `modules/EchoMind/viewer_chat/api_manager.py` | **Credentials & center key resolution.** Maps center keys to GapGPT `sk-` bearer tokens. Internal — do not expose. |
| `modules/EchoMind/viewer_chat/llm_client.py` | HTTP client wrapper for both GapGPT and OpenAI endpoints. |
| `modules/EchoMind/viewer_chat/openai_parallel_backend.py` | Simpler parallel backend for bulk operations. Has its own lightweight `standardize()` (2-line system prompt). |
| `modules/EchoMind/viewer_chat/ai_chat_config.py` | Runtime config loader. Reads `echomind_settings.json`. |
| `modules/EchoMind/viewer_chat/prompts/` | **8 exported prompt JSON files** (see §5). |
| `modules/EchoMind/secretary/` | Secretary agent subsystem (command/router pipeline). Separate feature; not in Android scope. |
| `builder/plugin package/packages/echomind/payload/python/modules/EchoMind/viewer_chat/openai_reporter.py` | **Plugin mirror** — must stay byte-identical to source after every edit. |

### 2.2 Function Inventory

| Function | Entry point | Output format |
|----------|------------|---------------|
| `standardize(text, CENTER_Key, model)` | Bilingual Persian–English normalizer | 6-field JSON object (raw, no markdown) |
| `reporter(user_msg, modality, normal_template, CENTER_Key, model)` | Turbo report generation | 5-key JSON in ` ```json … ``` <\|end\|>` |
| `correction(user_report, correction_note, CENTER_Key, model)` | Patch-style report editor | 5-key JSON in ` ```json … ``` <\|end\|>` |
| `chat(messages, CENTER_Key, model)` | Free-form chat | Plain text / streamed |
| `translate(text, target_lang, CENTER_Key, model)` | Text translation | Plain text |

### 2.3 Standardize — Output Schema

```json
{
  "cleaned_sentences_persian": ["sentence 1.", "sentence 2."],
  "impression_persian": ["explicit impression."],
  "recommendation_persian": ["explicit recommendation."],
  "cleaned_sentences_english": ["sentence 1.", "sentence 2."],
  "impression_english": ["explicit impression."],
  "recommendation_english": ["explicit recommendation."]
}
```

Rules enforced by the prompt:
- NEVER use commas (Windows canonical version — `standardization.json` export).
  *Note: The redesigned `token_instructions` in `openai_reporter.py` (applied 2026-07-01)
  relaxes this to "commas are permitted where grammatically appropriate in Persian." The
  exported `standardization.json` snapshot still reflects the old rule. Android must target
  the **live in-code prompt**, not the snapshot.*
- Mandatory splitting at every "و" / "یا" / "که" connector (old rule).
  *Redesigned prompt: splitting is now selective — "و" alone is NOT a reason to split.*
- Input: raw Persian STT dictation. Fillers (خب / مرسی / آها) are stripped.
- Impression and recommendation are extracted only when explicitly dictated (not inferred).

### 2.4 Reporter (Turbo) — Output Schema

```json
{
  "Report Title":          "CT of the Chest with Contrast",
  "Pathological Findings": "...",
  "Normal Findings":       "...",
  "Impression":            "...",
  "Recommendations":       "..."
}
```

Wrapped in ` ```json\n...\n``` <|end|>`.

Rules enforced by the prompt:
- English-only output regardless of input language.
- RSNA-structured Normal Findings, modality-aware.
- Impression and Recommendations: REQUIRED if present in transcript, EMPTY STRING if absent.
- Persian/Finglish medical terminology is recognized and mapped to correct English terms.
- If user provided a `normal_template`, it replaces auto-generated Normal Findings.

### 2.5 Correction — Output Schema

Same 5-key JSON as Reporter. Wrapped in ` ```json\n...\n``` <|end|>`.

Key rules:
- PATCH semantics: every word not changed by `CORRECTION_NOTE` is preserved verbatim.
- Input may be JSON (canonical) or HTML (rendered report). HTML is converted first.
- If `CORRECTION_NOTE` is ambiguous, ask rather than guess.

### 2.6 Backend Routing — Windows

```
reporter(turbo=True, backend=company)  →  GapGPT  /chat/completions
reporter(turbo=False, backend=company) →  AI_BASE  /generate_report
reporter(backend=openai)               →  OpenAI   /chat/completions

standardize(backend=company)           →  GapGPT  /chat/completions
standardize(backend=openai)            →  OpenAI  /chat/completions

transcribe(backend=company)            →  AI_BASE  /generate_transcript
transcribe(backend=openai)             →  OpenAI   /audio/transcriptions

correction(backend=company)            →  GapGPT  /chat/completions
correction(backend=openai)             →  OpenAI  /chat/completions
```

### 2.7 Center Key Resolution — Windows

`api_manager.py` maps a human-readable center key (e.g. `"Ai-pacs/razi245608"`) to a GapGPT
`sk-` bearer token via a hardcoded registry. The mapping is done at call time; the raw center
key is never sent to GapGPT. **This registry is internal; its values must not be published.**

### 2.8 Proxy Configuration — Windows

`_get_requests_proxies(connection_type, proxy_port)`:
- `"direct"` → returns `{}` (explicit empty dict — disables system proxies).
- `"socks5"` → returns `{"http": "socks5://127.0.0.1:<port>", "https": "..."}`.

`proxies={}` vs `proxies=None` is critical: `None` inherits system proxy; `{}` bypasses it.

### 2.9 Models

| Context | Windows canonical model |
|---------|------------------------|
| Company turbo report | `gpt-4.1-mini` |
| Company standardize | `gpt-4.1-mini` |
| Company correction | `gpt-4.1-mini` |
| OpenAI report | Configurable via `openai_report_model` (e.g. `gpt-4o`) |

---

## 3. Repository Analysis — Android App

### 3.1 File Layout

| Path (under `app/src/main/`) | Role |
|-----------------------------|------|
| `java/com/aipacs/mobile/network/EchoMindBackendClient.kt` | **Core AI network layer.** All HTTP calls. Contains hardcoded prompt constants. |
| `java/com/aipacs/mobile/data/EchoMindRepositoryImpl.kt` | Repository wrapper. Calls `EchoMindBackendClient` + `ReceptionApiClient`. |
| `java/com/aipacs/mobile/ui/echomind/EchoMindViewModel.kt` | ViewModel. State management + orchestration. |
| `java/com/aipacs/mobile/ui/echomind/EchoMindScreen.kt` | Compose UI. Standardize / Generate / Turbo buttons; modality picker dialog. |
| `java/com/aipacs/mobile/config/EchoMindSettings.kt` | Config data class. |
| `java/com/aipacs/mobile/config/EchoMindCenters.kt` | Center key → GapGPT bearer resolver (RAZI only). |
| `java/com/aipacs/mobile/config/EchoMindCaseStore.kt` | Per-study draft persistence. |
| `java/com/aipacs/mobile/data/local/LocalLibrary.kt` | Voice/report/draft local file library. |
| `java/com/aipacs/mobile/report/ReportFormat.kt` | Report text parser + renderer. |
| `assets/echomind_prompts.json` | Exported prompt JSON (not currently loaded at runtime). |

### 3.2 Function Inventory

| Function | Entry point | Status |
|----------|------------|--------|
| `generateReport(transcript, modality, turbo)` | Report generation | ✓ Implemented |
| `standardize(text)` | Text standardization | ✓ Implemented (English-only) |
| `chat(messages)` | Free-form chat | ✓ Implemented |
| `transcribe(audioFile, turbo)` | STT transcription | ✓ Implemented |
| `sendToReception(patientId, content, status)` | Reception submit | ✓ Implemented |
| `correction(report, note)` | Patch editor | ✗ **Missing** |
| `translate(text, targetLang)` | Translation | ✗ **Missing** |

### 3.3 Current Prompt Constants (hardcoded in `EchoMindBackendClient.kt`)

**REPORT_SYSTEM_PROMPT_PREFIX** (used for normal/non-turbo route via AI_BASE):
> Generic English-only instruction to produce a structured radiology report with fields:
> Report Title, Technique, Pathological Findings, Normal Findings, Impression, Recommendations.
> No modality-specific language, no RSNA rules, no Persian terminology mapping.

**STANDARDIZE_SYSTEM_PROMPT**:
> Short English-only instruction to clean and rewrite the transcription as structured sentences.
> No bilingual output, no Persian sentence pairs, no 6-field JSON schema.

**CHAT_SYSTEM_PROMPT**:
> General-purpose radiology assistant prompt.

### 3.4 Backend Routing — Android

```
generateReport(turbo=false, backend=company)  →  AI_BASE  /generate_report
generateReport(turbo=true,  backend=company)  →  GapGPT   /chat/completions
generateReport(backend=openai)                →  OpenAI   /chat/completions

standardize(backend=company)                  →  GapGPT   /chat/completions
standardize(backend=openai)                   →  OpenAI   /chat/completions

transcribe(backend=company)                   →  AI_BASE  /generate_transcript
transcribe(backend=openai)                    →  OpenAI   /audio/transcriptions
```

### 3.5 Models — Android

| Context | Android current model |
|---------|----------------------|
| Company turbo | `gpt-4o` |
| Company normal | `gpt-4o-mini` |

*(Windows uses `gpt-4.1-mini` for company backend. This is a drift point — see Gap G-7.)*

### 3.6 `echomind_prompts.json` Asset

This file exists at `assets/echomind_prompts.json` (~145 KB). The first key is `reporter_ct`
containing the full CT turbo prompt (matching the Windows `turbo_ct.json` export). The file
appears to have been exported from the Windows workstation but is **not currently loaded at
runtime** — the app uses the hardcoded Kotlin constants instead. The asset is effectively dead
code today and represents an incomplete past migration attempt.

### 3.7 Center Key Resolution — Android

`EchoMindCenters.kt` implements `resolveCompanyKey(entered: String)`:
- If `entered` matches a known center key (case-insensitive), returns the mapped GapGPT bearer.
- Otherwise returns `entered` unchanged (allows pasting a raw `sk-` key directly).
- Only the **RAZI** center is currently included. Windows has a larger registry in
  `api_manager.py` — additional centers must be added manually to `EchoMindCenters.kt`
  from the Windows registry when deploying to other facilities.

### 3.8 `ReportFormat` — Android

`ReportFormat.kt` parses the 5-key JSON report into structured `Line` objects with kinds:
`TITLE`, `SECTION`, `SUBHEAD`, `BULLET`, `BODY`, `BLANK`. Colors are driven by
`NAVY`/`BROWN`/`GREEN`/`RED`/`ORANGE` constants mirroring the Windows workstation palette.
`toServerHtml()` produces the HTML sent to the reception server.

The parser reads the **normal 5-key JSON** (`Report Title`, `Pathological Findings`,
`Normal Findings`, `Impression`, `Recommendations`). If the Android backend receives AI_BASE
format (fields: `Report Title`, `Technique`, `Pathological Findings`, `Normal Findings`,
`Impression`, `Recommendations`) from the non-turbo route, the `Technique` field is silently
dropped — the parser ignores unknown sections.

---

## 4. Gap Analysis

### 4.1 Summary Table

| ID | Area | Windows (Canonical) | Android (Current) | Severity |
|----|------|--------------------|--------------------|----------|
| G-1 | Standardize language | Bilingual Persian–English; 6-field JSON with `cleaned_sentences_persian`, `impression_persian`, etc. | English-only; schema unknown/undocumented; no Persian fields | **Critical** |
| G-2 | Standardize prompt quality | Full CRITICAL NON-EXPANSION rule + HARD SENTENCE SPLITTING + conditional impression extraction | Generic 2-sentence instruction | **Critical** |
| G-3 | Modality-specific prompts | 5 prompts: CT, MRI, Ultrasound, X-ray, Mammography — each with RSNA rules, terminology maps, IMPRESSION presence-lock | Single generic REPORT_SYSTEM_PROMPT_PREFIX for all modalities | **Critical** |
| G-4 | Correction function | `correction(report, note)` — surgical patch editor with 5-key JSON output | **Not implemented** | **Critical** |
| G-5 | Persian/Finglish terminology | Explicit mapping table per modality (e.g. "برونشکتازی" → Bronchiectasis for CT; "گراند گلس" → GGO) | None | High |
| G-6 | Normal Template system | User-supplied template replaces auto-generated Normal Findings | Not implemented | High |
| G-7 | Model name | `gpt-4.1-mini` for company turbo/standardize/correction | `gpt-4o` (turbo) / `gpt-4o-mini` (normal) | High |
| G-8 | Translation function | `translate(text, target_lang)` function exists | Not implemented | Medium |
| G-9 | Proxy support | Full SOCKS5 + direct with `proxies={}` explicit bypass | `proxyPort` config field exists; HTTP proxy plumbing unclear | Medium |
| G-10 | `echomind_prompts.json` usage | N/A (Windows uses live in-code prompts) | Asset exists but is dead code — not loaded at runtime | Medium |
| G-11 | Center registry completeness | Full registry in `api_manager.py` covering multiple facilities | Only RAZI center in `EchoMindCenters.kt` | Medium |
| G-12 | Parallel backend | `openai_parallel_backend.py` for bulk operations | Not present | Low |
| G-13 | Standardize output parsing | Caller parses 6 named fields and renders them separately | Caller treats result as opaque text string | **Blocks G-1** |
| G-14 | IMPRESSION/RECOMMENDATION handling | Presence-lock: empty string when absent, non-empty string required when present in transcript | No enforcement | High |
| G-15 | Standardize redesign propagation | New `token_instructions` (2026-07-01): commas permitted, selective splitting, UNCERTAINTY RULE | Not propagated | High |

### 4.2 Critical Gap Detail

#### G-1 / G-2: Standardization Pipeline

The Windows `standardize()` function is a **bilingual pipeline**, not a cleanup function.
The Android implementation treats `standardize()` as a simple "clean my text" operation
returning a single string. The full Windows behavior:

1. Input: raw Persian STT dictation
2. Process: normalize, deduplicate, split into short sentences, strip fillers
3. Output: 6-field JSON containing both Persian and English sentence arrays, plus separate
   impression and recommendation arrays in both languages

The Android `EchoMindViewModel.standardize()` passes the result directly to `composerText`
as a String. For bilingual output to work, the ViewModel must be updated to parse the 6-field
JSON and decide what to render (e.g. Persian sentences → composerText, English → separate
display, or merged formatted text).

#### G-3: Modality-Specific Turbo Prompts

The Windows turbo prompt for each modality is large (~4–16 KB) and contains:
- English-only enforcement header
- Template logic (normal template vs auto-generate)
- Modality logic block with RSNA rules tailored to the modality
- Persian/Finglish → English terminology map (15–30 terms per modality)
- IMPRESSION/RECOMMENDATIONS PRESENCE-LOCK (hard rule)
- Report structure output rules with 5-key JSON schema and ` ```json…``` <|end|>` wrapping

The Android `generateReport()` currently sends `REPORT_SYSTEM_PROMPT_PREFIX` regardless of
modality. The AI_BASE route (`/generate_report`) has its own server-side prompt so normal
(non-turbo) generation is partially handled there, but turbo generation using GapGPT
`/chat/completions` uses no modality context.

#### G-4: Correction Function

The `correction()` function has no Android equivalent. In the Windows workstation workflow:
1. Physician generates a report
2. Physician reviews, presses **Correct** button, types a correction note
3. `correction()` is called — it applies the note as a patch to the original report JSON
4. Result replaces the report in the viewer

This is a post-approval editing feature. On Android, the `ReportCard` component has an
Edit button that drops to a raw `OutlinedTextField`. Adding `correction()` on Android would
allow the same structured AI-powered correction workflow instead of manual text editing.

---

## 5. Prompt System Documentation

### 5.1 Windows Prompt File Registry

All 8 prompt files live at `modules/EchoMind/viewer_chat/prompts/`. Each is a JSON export
with metadata about the prompt's origin.

| File | `id` | Purpose | Approximate size |
|------|------|---------|-----------------|
| `turbo_ct.json` | `turbo_ct` | Turbo report — CT | ~16 KB system_prompt |
| `turbo_mri.json` | `turbo_mri` | Turbo report — MRI | ~12 KB system_prompt |
| `turbo_ultrasound.json` | `turbo_ultrasound` | Turbo report — Ultrasound | ~10 KB system_prompt |
| `turbo_xray.json` | `turbo_xray` | Turbo report — X-ray | ~8 KB system_prompt |
| `turbo_mammography.json` | `turbo_mammography` | Turbo report — Mammography | ~8 KB system_prompt |
| `correction.json` | `correction` | Surgical patch editor | ~4.5 KB system_prompt |
| `standardization.json` | `standardization` | Bilingual normalizer | ~8.4 KB system_prompt |
| `translation.json` | `translation` | Text translation | ~2 KB system_prompt |

**Important:** The `.json` files are snapshots exported 2026-06-28. The live prompts are
assembled dynamically in `openai_reporter.py` — the `reporter()` function stitches together
a `system_prompt` from: `english_only_header` + `template_logic` + `user_normal_template`
(if provided) + `base_modality_logic` + `modality_specific_instructions`. The exported JSON
reflects the "no normal template" case. **Android must implement this same dynamic assembly.**

### 5.2 Standardization Prompt (Canonical — Live Version in `openai_reporter.py`)

The redesigned standard prompt (`token_instructions`, applied 2026-07-01) enforces:

```
ROLE: conservative bilingual (Persian-English) medical text normalizer
Input: raw Persian STT dictation

OUTPUT RULES (NEVER BREAK):
1) Single valid raw JSON object (no markdown, no code fences)
2) First char = "{", last char = "}"
3) Python json.loads()-parseable; double quotes only; no trailing commas
4) No newline characters inside any JSON string
5) Empty arrays if input is empty or meaningless

CORE PRINCIPLE: MINIMAL INTERVENTION
- Make the minimum edits necessary
- When in doubt, keep the original word

PERMITTED TRANSFORMATIONS:
1) STT error correction (only obvious, unambiguous errors)
   UNCERTAINTY RULE: if not certain → keep original word verbatim
2) Readability splitting (selective, NOT mandatory)
   "و" alone is NOT a reason to split
   Natural compounds stay intact: "کلیه راست و چپ", "با و بدون تزریق"
3) Formatting: remove fillers (مرسی / خب / اِ / آها / ببخشید)
   Commas are permitted where grammatically appropriate in Persian
4) Dictation command normalization (strictly limited):
   "[organ] طبیعی بزن" → "[organ] نمای طبیعی دارد."
```

**Note for Android:** The old exported `standardization.json` has stricter rules (NEVER use
commas, HARD SENTENCE SPLITTING at every connector). Android should implement the **new live
version** rules described above, not the JSON snapshot.

### 5.3 Turbo Report Prompt Assembly (for Implementing Agent)

The turbo report system prompt is assembled as follows:

```
[BLOCK 1: english_only_header]
"IMPORTANT: You MUST respond ONLY in English. This rule is ABSOLUTE..."

[BLOCK 2: template_logic]
IF normal_template provided:
  "A 'normal_template' was provided. Use it to populate 'Normal Findings'."
ELSE:
  "No 'normal_template' provided. Construct 'Normal Findings' automatically
   using META-driven RSNA structure. Exclude organs in Pathological Findings."

[BLOCK 3: user_normal_template]
(empty string if not provided; verbatim text if provided)

[BLOCK 4: base_modality_logic]
"The imaging modality is '{modality}'. Customize 'Report Title' to include modality.
Tailor 'Normal Findings' structure and terminology to the modality."

[BLOCK 5: modality_specific_instructions]
(full per-modality block — see §5.4)
```

The user message is the raw transcript string.

### 5.4 Modality-Specific Instruction Summary

Each modality block contains:

**CT** — RSNA CT structured reporting; contrast phase recognition; anatomical grouping;
Persian/Finglish CT terms (برونشکتازی→Bronchiectasis, گراند گلس→GGO, هایپردنس→Hyperdense,
پنوموتوراکس→Pneumothorax, پلورال افیوژن→Pleural effusion, هیدرونفروز→Hydronephrosis, etc.);
IMPRESSION/RECOMMENDATIONS presence-lock.

**MRI** — RSNA MRI reporting; sequence-conditional mention (DWI/SWI only if in transcript);
body-region-specific grouped normal findings; same presence-lock.

**Ultrasound** — RSNA US reporting; grayscale/color/elastography conditional; echogenicity
terminology; sonographic measurement standards; Persian US terms (اکوژنیسیته→Echogenicity,
کیستیک→Cystic, هیپواکو→Hypoechoic, etc.); same presence-lock.

**X-ray** — RSNA CXR/plain film reporting; view-conditional (AP/PA/lateral); bone
vs soft tissue findings; lung zone organization; same presence-lock.

**Mammography** — BI-RADS terminology; density categories; lesion descriptor standards
(shape/margin/density for masses; morphology/distribution for calcifications);
same presence-lock.

**All modalities share:**
```
IMPRESSION/RECOMMENDATIONS PRESENCE-LOCK (HARD RULE):
- If Impression EXISTS in input → output "Impression" MUST be non-empty
- If Recommendations EXISTS in input → output "Recommendations" MUST be non-empty
- If either is absent → output MUST be empty string (not null, not missing)

EXISTS = any explicit indicator phrase:
  Impression: "impression", "جمع‌بندی", "نتیجه", "مطرح‌کننده", "suggestive of",
              "compatible with", "به نفع", "به احتمال زیاد"
  Recommendations: "recommend", "توصیه", "follow-up", "biopsy", "نمونه‌برداری",
                   "بررسی بیشتر", "فالو آپ"
```

### 5.5 Correction Prompt Structure

```
ROLE: high-precision medical report editor performing a PATCH operation
Task: output = ORIGINAL_REPORT + minimum_edits_from_CORRECTION_NOTE

INPUT:
1) ORIGINAL_REPORT — approved report (JSON canonical or HTML rendered)
2) CORRECTION_NOTE — physician instruction describing what to change

OUTPUT FORMAT (NEVER BREAK):
- Single JSON in code block: ```json\n{...}\n```
- Terminated with: <|end|>
- Exactly 5 keys: "Report Title", "Pathological Findings", "Normal Findings",
  "Impression", "Recommendations"

CORE PRINCIPLE: PATCH, NOT REGENERATE
- Every word NOT required to change → preserved verbatim ("byte-identical")
- Example: "change right to left" only alters laterality, preserves all other content

PROCESS:
1) Parse ORIGINAL_REPORT (JSON directly, or convert HTML→JSON)
2) Read CORRECTION_NOTE
3) Identify minimum required edits
4) Apply ONLY those edits
5) Verify every other field is byte-identical to ORIGINAL_REPORT
6) Output the patched 5-key JSON

HTML→JSON RULE:
- Only map content explicitly present; leave unmappable fields as ""
- NEVER output HTML — always output JSON
```

---

## 6. AI Workflow Documentation

### 6.1 Windows Workstation Full Workflow

```
PHYSICIAN OPENS PATIENT TAB
         │
         ▼
   [OPTIONAL] Load draft if prior session
         │
         ▼
   RECORD voice (AudioRecorder → .wav file)
         │
         ▼
   TRANSCRIBE  →  AI_BASE /generate_transcript  (company)
               OR OpenAI /audio/transcriptions   (openai)
         │
         ▼
   [Display transcription in text area]
         │
         ├─── STANDARDIZE  →  GapGPT /chat/completions
         │                    Input:  raw Persian transcript
         │                    Prompt: bilingual normalizer (redesigned 2026-07-01)
         │                    Output: 6-field JSON
         │                    Android gap: English-only, wrong schema (G-1, G-2, G-13)
         │
         ├─── GENERATE (Normal)
         │         │
         │         ▼
         │    AI_BASE /generate_report
         │         Input:  {transcript, modality, ...}
         │         Output: 6-field server format → ReportFormat parses
         │
         ├─── GENERATE (Turbo)  →  GapGPT /chat/completions
         │         Input:  transcript as user message
         │         Prompt: modality-specific system prompt (5-block assembly)
         │         Output: 5-key JSON in ```json...``` <|end|>
         │         Android gap: generic prompt (G-3), wrong model (G-7)
         │
         └─── CORRECT (post-approval edit)
                   Input:  {ORIGINAL_REPORT, CORRECTION_NOTE}
                   Prompt: correction system prompt
                   Output: 5-key JSON in ```json...``` <|end|>
                   Android gap: NOT IMPLEMENTED (G-4)
         │
         ▼
   [Report card displayed — editable]
         │
         ▼
   SEND TO RECEPTION  →  server /report endpoint (HTML via ReportFormat.toServerHtml())
```

### 6.2 Android Current Workflow

```
RECORD voice  →  auto-transcribe on stop
      │
      ▼
TRANSCRIBE  →  AI_BASE /generate_transcript (company) OR OpenAI /audio/transcriptions
      │
      ▼
STANDARDIZE  →  GapGPT /chat/completions
      │          Prompt: STANDARDIZE_SYSTEM_PROMPT (English-only generic)
      │          Output: treated as plain text string
      │
GENERATE (dialog: Standard or Turbo, modality picker)
      │
      ├── Normal  →  AI_BASE /generate_report
      │              formatStructuredReport() parses server JSON
      │
      └── Turbo   →  GapGPT /chat/completions
                     REPORT_SYSTEM_PROMPT_PREFIX (generic, no modality context)
                     Output: formatStructuredReport() parses 5-key JSON
      │
SEND TO RECEPTION  →  ReceptionApiClient
```

### 6.3 `formatStructuredReport()` on Android

This function parses two distinct JSON formats that the backend may return:

**AI_BASE format** (6-key, from `/generate_report`):
```json
{
  "Report Title":          "...",
  "Technique":             "...",   ← unique to AI_BASE, dropped in parser
  "Pathological Findings": "...",
  "Normal Findings":       "...",
  "Impression":            "...",
  "Recommendations":       "..."
}
```

**GapGPT turbo format** (5-key, from `/chat/completions`):
```json
{
  "Report Title":          "...",
  "Pathological Findings": "...",
  "Normal Findings":       "...",
  "Impression":            "...",
  "Recommendations":       "..."
}
```

The parser uses `ReportFormat.parse(text)` which handles the ` ```json…``` <|end|>` wrapping.
It extracts JSON from the code block, then maps fields to `Line` objects.

### 6.4 Transcription Request Format

**Company backend (`AI_BASE /generate_transcript`):**
```json
{
  "audio_files":   ["<base64-encoded-audio>"],
  "quality_mode":  "standard"
}
```
Response: `{"transcript": "..."}`

**OpenAI (`/audio/transcriptions`):**
- Multipart form: `file=<audio>`, `model=whisper-1`
- Response: `{"text": "..."}`

---

## 7. Backend Communication Documentation

### 7.1 Endpoints Reference

| Backend | Base URL | Endpoint | Used for |
|---------|----------|----------|---------|
| GapGPT (company) | `https://api.gapgpt.app/v1` | `/chat/completions` | Turbo report, standardize, correction, chat |
| AI_BASE (company) | `http://81.16.117.196:8082` | `/generate_report` | Normal (non-turbo) report generation |
| AI_BASE (company) | `http://81.16.117.196:8082` | `/generate_transcript` | Voice transcription |
| OpenAI | Configurable base URL | `/chat/completions` | Report, standardize, correction, chat |
| OpenAI | Configurable base URL | `/audio/transcriptions` | Voice transcription |

### 7.2 GapGPT Chat Completions Request

```json
POST /v1/chat/completions
Authorization: Bearer <resolved_gapgpt_key>
Content-Type: application/json

{
  "model":    "gpt-4.1-mini",
  "messages": [
    {"role": "system", "content": "<system_prompt>"},
    {"role": "user",   "content": "<user_message>"}
  ],
  "temperature": 0.3,
  "max_tokens":  2048
}
```

Temperature and max_tokens are tuned per operation:
- Standardize: lower temperature (conservative output)
- Turbo report: moderate temperature
- Correction: lowest temperature (patch fidelity)

### 7.3 AI_BASE Generate Report Request

```json
POST /generate_report
Content-Type: application/json

{
  "transcript":  "<text>",
  "modality":    "<modality>",
  "center_key":  "<center_key>"
}
```

Response schema:
```json
{
  "Report Title":          "...",
  "Technique":             "...",
  "Pathological Findings": "...",
  "Normal Findings":       "...",
  "Impression":            "...",
  "Recommendations":       "..."
}
```

### 7.4 Authentication

**Company backend:** Bearer token resolved from center key via `EchoMindCenters.resolveCompanyKey()`.
- If entered key matches a known center key → returns the mapped GapGPT `sk-` bearer.
- If entered key is already an `sk-` key → returned unchanged.
- **Never log the resolved bearer token.**

**OpenAI backend:** Bearer token from `EchoMindSettings.openaiApiKey`.

### 7.5 Error Handling

Windows `openai_reporter.py` pattern:
- Network errors → return structured `{"error": "...", "message": "..."}` dict, never raise to UI
- Parse failures (malformed JSON from AI) → retry once, then return error
- Model overloaded (HTTP 429) → exponential backoff (2 attempts)
- Connection refused → surface error immediately, no retry

Android `EchoMindRepositoryImpl` pattern:
- All backend calls return `AppResult<T>` (sealed class: `Success(data)` / `Failure(message)`)
- Audio is preserved on transcription failure for retry
- `generateReport` failure → `_state.update { it.copy(generating=false, message=r.message) }`

### 7.6 Reception Submit

```
Android: EchoMindRepositoryImpl.sendToReception(patientId, content, status)
  → content = reportText (plain text from ReportCard)
  → ReportFormat.toServerHtml(content) converts to HTML
  → ReceptionApiClient.updateReport(patientId, html, status)

Windows: similar HTML conversion before server POST
```

---

## 8. Configuration Documentation

### 8.1 Windows Config (`echomind_settings.json`)

```json
{
  "llm_backend":         "company",
  "center_key":          "Ai-pacs/razi245608",
  "connection_type":     "direct",
  "proxy_port":          1080,
  "openai_api_key":      "",
  "openai_base_url":     "https://api.openai.com/v1",
  "openai_report_model": "gpt-4o",
  "openai_chat_model":   "gpt-4o-mini",
  "stt_provider":        "company"
}
```

### 8.2 Android Config (`EchoMindSettings.kt`)

```kotlin
data class EchoMindSettings(
    val llmBackend:             String = "company",
    val apiKey:                 String = "Ai-pacs/razi245608",  // center key
    val openaiApiKey:           String = "",
    val openaiBaseUrl:          String = "https://api.openai.com/v1",
    val openaiReportModel:      String = "gpt-4o",
    val openaiChatModel:        String = "gpt-4o-mini",
    val connectionType:         String = "direct",
    val proxyPort:              Int    = 1080,
    val secretarySttProvider:   String = "company",
)
```

### 8.3 Config Differences

| Field | Windows | Android | Note |
|-------|---------|---------|------|
| Default backend | `"company"` | `"company"` | ✓ Matching |
| Default center key | `"Ai-pacs/razi245608"` | `"Ai-pacs/razi245608"` | ✓ Matching |
| Company turbo model | Resolved to `gpt-4.1-mini` by `api_manager.py` | Hardcoded `gpt-4o` | ✗ Drift (G-7) |
| Company normal model | Resolved to `gpt-4.1-mini` | Hardcoded `gpt-4o-mini` | ✗ Drift (G-7) |
| Proxy handling | `proxies={}` explicit bypass | `proxyPort` field only | Verify implementation |

### 8.4 Modality Normalization — Android

`EchoMindViewModel.normalizeModality(raw: String)` maps reception-worklist labels:

| Input keywords | Normalized value |
|----------------|-----------------|
| "son" / "ultra" / "us" | `"Ultrasound"` |
| "mri" / "mr" | `"MRI"` |
| "ct" | `"CT"` |
| "mammo" / "mg" | `"Mammography"` |
| "rad" / "x-ray" / "xray" / "dx" / "cr" / "xr" | `"X-ray"` |

`EchoMindViewModel.MODALITIES = ["CT", "MRI", "Ultrasound", "X-ray", "Mammography", "Other"]`

---

## 9. Architecture Recommendations

### 9.1 Prompt Loading Strategy

**Recommended:** Load prompts from `assets/echomind_prompts.json` at runtime, not from
hardcoded Kotlin constants.

Rationale:
- The asset file already exists and contains CT prompt matching Windows.
- Prompts can be updated via app-level update without a full APK rebuild.
- Enables the same dynamic assembly pattern as Windows.

Implementation sketch:
```kotlin
// PromptRepository.kt
class EchoMindPromptRepository(context: Context) {
    private val prompts: Map<String, String> by lazy {
        val json = context.assets.open("echomind_prompts.json")
            .bufferedReader().readText()
        JSONObject(json).let { obj ->
            obj.keys().asSequence().associateWith { key -> obj.getString(key) }
        }
    }

    fun getReporterPrompt(modality: String): String =
        prompts["reporter_${modality.lowercase()}"]
            ?: prompts["reporter_ct"]  // fallback
            ?: DEFAULT_REPORT_PROMPT

    fun getStandardizePrompt(): String =
        prompts["standardization"] ?: DEFAULT_STANDARDIZE_PROMPT

    fun getCorrectionPrompt(): String =
        prompts["correction"] ?: DEFAULT_CORRECTION_PROMPT
}
```

### 9.2 Standardize Response Parsing

The Android ViewModel must be updated to parse the 6-field bilingual JSON instead of
treating the result as a plain string:

```kotlin
// EchoMindStandardizeResult.kt
data class StandardizeResult(
    val cleanedPersian:      List<String>,
    val impressionPersian:   List<String>,
    val recommendationPersian: List<String>,
    val cleanedEnglish:      List<String>,
    val impressionEnglish:   List<String>,
    val recommendationEnglish: List<String>
) {
    /** Formatted Persian text for composerText (the working draft). */
    fun toPersianComposer(): String =
        (cleanedPersian + impressionPersian + recommendationPersian)
            .joinToString("\n")

    /** Formatted English text for display bubble. */
    fun toEnglishDisplay(): String =
        (cleanedEnglish + impressionEnglish + recommendationEnglish)
            .joinToString("\n")
}
```

The `EchoMindUiState` should gain an optional `standardizeResult: StandardizeResult?` field.
The ViewModel places Persian in `composerText` (for generate input) and English in a
`STANDARDIZED` message bubble.

### 9.3 Correction Integration

The correction feature requires minimal Android-side additions:

1. **Backend:** Add `suspend fun correct(report: String, note: String): AppResult<String>` to
   `EchoMindBackendClient.kt`. Routes to GapGPT `/chat/completions` with correction prompt.
   Parser identical to turbo report (extracts JSON from ` ```json…``` <|end|>` wrapper).

2. **Repository:** Expose `correction(report, note)` in `EchoMindRepository` interface and
   `EchoMindRepositoryImpl`.

3. **ViewModel:** Add `fun correct(note: String)` calling `echoMind.correction(reportText, note)`.

4. **UI:** Replace the raw `OutlinedTextField` Edit mode in `ReportCard` with a two-field
   dialog: original report (read-only) + correction note (editable). On submit → `vm.correct(note)`.

### 9.4 Modality Prompt Injection for Turbo

The turbo route (`GapGPT /chat/completions`) must pass a modality-aware system prompt.
Current gap: `REPORT_SYSTEM_PROMPT_PREFIX` is sent regardless of modality.

Minimal fix (load from asset):
```kotlin
fun buildTurboSystemPrompt(modality: String, normalTemplate: String? = null): String {
    val base = promptRepository.getReporterPrompt(modality)
    return if (normalTemplate.isNullOrBlank()) {
        base  // already includes "no normal template" logic
    } else {
        // Inject template into the template_logic slot
        base.replace("__NORMAL_TEMPLATE_PLACEHOLDER__", normalTemplate)
    }
}
```

### 9.5 Model Configuration

Recommend adding a `companyTurboModel` and `companyNormalModel` field to `EchoMindSettings`:
```kotlin
val companyTurboModel:  String = "gpt-4.1-mini",
val companyNormalModel: String = "gpt-4.1-mini",
```

These should be resolved from the backend at runtime or read from config, matching the
Windows `api_manager.py` behavior where model names are resolved per-center.

### 9.6 Separation of Concerns

The current `EchoMindBackendClient.kt` mixes network logic, prompt constants, and routing
decisions. Recommended layering:

```
EchoMindPromptRepository  ← prompts (from assets/echomind_prompts.json)
EchoMindModelConfig       ← model name resolution (center-aware)
EchoMindBackendClient     ← HTTP only (no business logic, no prompts)
EchoMindRepositoryImpl    ← orchestration (prompt injection + routing + error handling)
EchoMindViewModel         ← state + UI events only
```

---

## 10. Phased Migration Plan

### Phase 1 — Load Prompts from Asset (Low risk, no API change)

**Goal:** Replace hardcoded Kotlin prompt constants with runtime loading from
`assets/echomind_prompts.json`.

**Steps:**
1. Add all missing prompt keys to `echomind_prompts.json`:
   - `standardization` — the canonical bilingual prompt (new live version from `openai_reporter.py`)
   - `reporter_mri`, `reporter_ultrasound`, `reporter_xray`, `reporter_mammography`
     (export from Windows `turbo_*.json` files)
   - `correction` — from Windows `correction.json`
   - `translation` — from Windows `translation.json`
2. Implement `EchoMindPromptRepository` (see §9.1).
3. Wire `EchoMindBackendClient.kt` to read from repository instead of constants.
4. Validate: turbo CT generation matches Windows output quality.

**Validation:** Unit test that `getReporterPrompt("ct")` returns a string containing
"IMPRESSION / RECOMMENDATIONS PRESENCE-LOCK".

**Risk:** None. The app behavior improves immediately. No schema change.

---

### Phase 2 — Fix Model Names (Low risk, one-line change)

**Goal:** Align Android model names with Windows canonical (`gpt-4.1-mini`).

**Steps:**
1. Update `EchoMindSettings.kt` defaults:
   - `companyTurboModel  = "gpt-4.1-mini"`
   - `companyNormalModel = "gpt-4.1-mini"`
2. Update `EchoMindBackendClient.kt` to use these fields.
3. Keep `gpt-4o` / `gpt-4o-mini` as the OpenAI backend defaults (those are correct — OpenAI
   backend is separate).

**Validation:** GapGPT request body logs show `"model": "gpt-4.1-mini"`.

**Risk:** Negligible. Model upgrade.

---

### Phase 3 — Full Bilingual Standardization (Medium complexity, schema change)

**Goal:** Make Android `standardize()` output match Windows 6-field bilingual JSON schema.

**Steps:**
1. From Phase 1, `echomind_prompts.json` already contains the canonical bilingual prompt.
   The `standardize()` call in `EchoMindBackendClient` is already routed to GapGPT — so the
   only change is the system prompt (Phase 1 covers this).
2. Add `StandardizeResult` data class (see §9.2).
3. Update `EchoMindRepositoryImpl.standardize()` to parse the 6-field JSON response.
4. Update `EchoMindViewModel.standardize()`:
   - Place `toPersianComposer()` in `composerText` (for use as generate input).
   - Place English display in a `STANDARDIZED` message bubble.
   - Preserve `preStandardize` for undo.
5. Update `EchoMindUiState` to optionally carry `StandardizeResult`.
6. Update `EchoMindCaseStore` serialization to persist the new result shape.

**Validation:**
- Input: `"كبد طبیعی هست لطفاً"` → Output must contain `cleaned_sentences_persian` and
  `cleaned_sentences_english` arrays.
- Impression extraction: `"جمع‌بندی: احتمال کولانژیت"` → `impression_persian` non-empty.
- Undo (undoStandardize) restores original Persian text.

**Risk:** Medium. Schema change requires updating ViewModel, UI state, and persistence.
Existing plain-text `standardize()` consumers must be migrated.

---

### Phase 4 — Modality-Specific Turbo Prompts (Medium complexity)

**Goal:** Pass modality-specific system prompts for turbo generation (Phase 1 already loads
the prompts; this phase wires them to the turbo route).

**Steps:**
1. Update `EchoMindBackendClient.generateReport(turbo=true)` to accept `systemPrompt: String`
   parameter instead of using `REPORT_SYSTEM_PROMPT_PREFIX`.
2. Update `EchoMindRepositoryImpl.generateReport()` to call
   `promptRepository.getReporterPrompt(modality)` and pass it to the backend.
3. Add Normal Template support:
   - Add `normalTemplate: String?` to `EchoMindSettings`.
   - Inject into prompt assembly when non-null (replace placeholder token in the system prompt).
4. Update `EchoMindCaseStore` / `EchoMindCase` to optionally persist the normal template.

**Validation:**
- Turbo CT report: output must contain "Report Title" including "CT".
- Turbo MRI: Normal Findings must not mention CT-specific terms.
- Persian input with "احتمالاً" in the transcript → Impression must be non-empty (presence-lock).
- Persian input with no impression indicator → Impression must be empty string.

**Risk:** Medium. Prompt assembly logic must be tested per modality.

---

### Phase 5 — Correction Function (Medium complexity, new feature)

**Goal:** Implement the surgical patch correction workflow on Android.

**Steps:**
1. Add `correction` prompt to `echomind_prompts.json` (from Windows `correction.json`).
2. Add `suspend fun correct(report: String, note: String): AppResult<String>` to
   `EchoMindBackendClient.kt`. Route: GapGPT `/chat/completions` with correction system prompt.
   Response parser: extract JSON from ` ```json…``` <|end|>` (same parser as turbo report).
3. Expose `correction()` in `EchoMindRepository` interface and `EchoMindRepositoryImpl`.
4. Add `fun correct(note: String)` to `EchoMindViewModel`.
5. Replace raw text edit in `ReportCard` with correction-note UI:
   - "Edit" button opens a dialog: note text field + "Apply AI correction" + "Edit manually".
   - "Apply AI correction" → `vm.correct(note)`.
   - "Edit manually" → existing `OutlinedTextField` path.
6. Add `correcting: Boolean` state to `EchoMindUiState`.

**Validation:**
- Correction note `"change right kidney to left kidney"` applied to a report with
  "right kidney" → output must have "left kidney"; all other text identical.
- HTML input: submit HTML-rendered report + correction note → output is 5-key JSON, no HTML.
- Empty correction note → shows validation error, no API call.

**Risk:** Medium-low. Net-new feature; no regression risk on existing paths.

---

### Phase 6 — Translation, Center Registry, and Hardening (Low complexity)

**Goal:** Close remaining gaps and harden the implementation.

**Steps:**
1. **Translation:** Add `translate(text, targetLang)` to backend client and repository.
   Route: GapGPT `/chat/completions` with `translation` system prompt from asset.
2. **Center registry:** Sync `EchoMindCenters.kt` from Windows `api_manager.py` when deploying
   to facilities beyond RAZI. Each center entry must be added manually; do not automate
   registry export (credentials are internal).
3. **Proxy hardening:** Verify Android `OkHttpClient` proxy configuration:
   - `"direct"` → create client with `Proxy.NO_PROXY` (explicit, same semantics as `proxies={}`)
   - `"socks5"` → create client with `Proxy(Type.SOCKS, InetSocketAddress("127.0.0.1", port))`
4. **`echomind_prompts.json` versioning:** Add a `_version` key to the JSON; app reads it at
   startup and logs if the asset version is behind the Windows canonical version.
5. **Error handling alignment:** Ensure all `EchoMindBackendClient` failures return structured
   `AppResult.Failure` with human-readable Persian or English error message.
6. **Correction output parsing robustness:** Add fallback for AI output that omits the
   ` ```json…``` <|end|>` wrapper (direct JSON fallback) — same defense Windows uses.

**Validation:** See §11 master checklist.

---

## 11. Validation Checklist

### Pre-Phase Checks

- [ ] `assets/echomind_prompts.json` contains keys: `reporter_ct`, `reporter_mri`,
  `reporter_ultrasound`, `reporter_xray`, `reporter_mammography`, `standardization`,
  `correction`, `translation`
- [ ] `EchoMindPromptRepository` unit test: all 8 keys load without exception
- [ ] `EchoMindCenters.resolveCompanyKey("Ai-pacs/razi245608")` returns a non-empty string
  starting with `"sk-"`
- [ ] GapGPT request log shows `"model": "gpt-4.1-mini"` for company backend calls

### Standardization (Phase 3)

- [ ] English-only input → `cleaned_sentences_english` non-empty, `cleaned_sentences_persian`
  may be empty or mirrors input
- [ ] Persian input without impression → `impression_persian` = `[]`, `impression_english` = `[]`
- [ ] Persian input with `"جمع‌بندی:"` → `impression_persian` non-empty
- [ ] Filler words (`خب`, `مرسی`, `آها`) stripped from output
- [ ] Natural compound `"کلیه راست و چپ"` stays intact (not split at و)
- [ ] `composerText` receives Persian text after standardize
- [ ] `STANDARDIZED` message bubble receives English text
- [ ] Undo restores `preStandardize` (pre-standardize text)
- [ ] 6-field JSON persists correctly in `EchoMindCaseStore` across app restarts

### Turbo Report Generation (Phase 4)

- [ ] CT report contains RSNA CT terminology (not generic)
- [ ] MRI report does NOT contain CT-specific terms
- [ ] Ultrasound report uses echogenicity terminology
- [ ] Report Title includes modality name (e.g. "CT of the Chest")
- [ ] Input transcript with "impression" keyword → Impression field non-empty
- [ ] Input transcript with no impression keyword → Impression field is `""` (empty string)
- [ ] Input transcript with no recommendation → Recommendations field is `""` (empty string)
- [ ] Persian/Finglish CT term "گراند گلس" → English output "ground-glass opacity" or "GGO"
- [ ] Persian/Finglish CT term "پلورال افیوژن" → English output "pleural effusion"
- [ ] Normal template provided → Normal Findings mirrors template content, not auto-generated
- [ ] ` ```json…``` <|end|>` wrapper parsed correctly; result rendered in ReportCard

### Correction (Phase 5)

- [ ] "change right to left" applied to report with "right kidney" → output has "left kidney"
- [ ] All other fields in corrected output are byte-identical to original
- [ ] HTML original report → output is JSON (not HTML)
- [ ] JSON original report → output is JSON
- [ ] Empty correction note → UI validation error, no API call
- [ ] Correction applied to sent report → `sent` flag resets to `false` (requires re-send)
- [ ] Network failure during correction → error message shown, original report unchanged
- [ ] Corrected report persists in `EchoMindCaseStore`

### Backend Communication

- [ ] GapGPT base URL is `https://api.gapgpt.app/v1` (not `http://`)
- [ ] AI_BASE URL is `http://81.16.117.196:8082`
- [ ] Authentication header is `Authorization: Bearer <resolved_key>` (never `Basic`)
- [ ] Resolved GapGPT bearer token is **never logged** at any log level
- [ ] `"direct"` connection type → no system proxy used (`Proxy.NO_PROXY`)
- [ ] `"socks5"` connection type → SOCKS5 proxy at `127.0.0.1:<proxyPort>`
- [ ] HTTP 429 (rate limit) → retry with exponential backoff (≥ 2 attempts)
- [ ] Network timeout → `AppResult.Failure` with readable message, no crash

### Configuration

- [ ] Default `llmBackend` = `"company"`
- [ ] Default `apiKey` = `"Ai-pacs/razi245608"`
- [ ] Settings persist across app restart (Jetpack DataStore or equivalent)
- [ ] Switching backend from `"company"` to `"openai"` routes all calls correctly
- [ ] `EchoMindSettings` fields round-trip through serialization without data loss

### UI / UX Alignment with Windows

- [ ] Standardize button active only when `composerText.isNotBlank()` and `!busy`
- [ ] Generate button opens modality picker dialog (Standard / Turbo radio, modality dropdown)
- [ ] Modality list: `["CT", "MRI", "Ultrasound", "X-ray", "Mammography", "Other"]`
- [ ] Recording auto-transcribes on stop (same as Windows auto-transcribe behavior)
- [ ] ReportCard "Send to Reception" submits HTML (not raw JSON) to reception server
- [ ] Report status chip updates after successful send
- [ ] Draft auto-saved to `EchoMindCaseStore` on every state change (`persist()`)
- [ ] Draft survives app background/kill and resumes correctly on re-open

### Security

- [ ] No GapGPT `sk-` keys are present in any log output (Logcat or file)
- [ ] No center keys or bearer tokens appear in network request logs
- [ ] `EchoMindCenters.kt` does not export its key list via any public API surface
- [ ] `EchoMindSettings` does not persist `openaiApiKey` to unencrypted storage
- [ ] Audio files are stored under app-private directory, not external storage

---

*End of specification. This document is the complete implementation brief for the Android
EchoMind synchronization agent. Begin with Phase 1 (asset loading) — it is the prerequisite
for all subsequent phases and carries zero regression risk.*
