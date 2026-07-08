# EchoMind — Exported Prompts (for manual review/edit)

**Exported:** 2026-06-28 · **Source:** `modules/EchoMind/viewer_chat/openai_reporter.py`
**Status:** VERBATIM extraction. **No prompt or source code was modified.**

These JSON files contain the prompts EchoMind sends for the client-side (Turbo / direct-to-GapGPT)
report flows. Each was captured by **running the real `openai_reporter.py` code with the network
call stubbed**, so each `system_prompt` is byte-for-byte what the app would send (not a hand copy).

| File | Group | Source function | What it is |
|------|-------|-----------------|------------|
| `turbo_mri.json` | Turbo Report | `reporter(modality="MRI")` | MRI report system prompt |
| `turbo_ct.json` | Turbo Report | `reporter(modality="CT")` | CT report system prompt |
| `turbo_xray.json` | Turbo Report | `reporter(modality="Radiology")` | X-ray / Radiography report system prompt |
| `turbo_ultrasound.json` | Turbo Report | `reporter(modality="Ultrasound")` | Ultrasound / OB-GYN report system prompt |
| `turbo_mammography.json` | Turbo Report | `reporter(modality="Mammography")` | Mammography (BI-RADS, regex-locked) system prompt |
| `standardization.json` | Standardize | `standardize()` | Standard / Standardize button prompt |
| `correction.json` | Correction | `correction()` | Correct / Correction prompt |
| `translation.json` | Translation | `translate_report()` + `translate_text_to_persian()` | Report translation (primary) + free-text translation |

## Each file contains

- `system_prompt` — the verbatim system message (for `translation.json`, see `variants.*.system_prompt`).
- `user_message_template` — the user-message scaffold, with input slots shown as `__PLACEHOLDER__`.
- Metadata: `source_function`, `input_variables`, `destination`, `assembly`, and notes.

## Important caveats before you edit/reload

1. **These are the default `company` (GapGPT-direct) prompts.** When `llm_backend == "openai"`,
   EchoMind instead uses the *short* twin prompts in `openai_parallel_backend.py` (override-driven).
   Editing these files affects the **default** path only.

2. **Turbo `system_prompt` is the no-template case.** It is assembled as
   `header + template_logic + user_normal_template + (base_modality_logic + modality_specific_instructions)`.
   When a user supplies a **Normal Template**, the `user_normal_template` slot is filled and the
   template-logic branch changes (see `assembly` in each file).

3. **X-ray matches on the exact value `radiology`.** The branch fires only when
   `modality.lower() == "radiology"`. If the modality button stores `"X-ray"` / `"XRAY"`, this
   prompt is **not** used (it falls back to a generic prompt). Confirm what `_current_modality`
   holds before relying on edits here.

4. **`<|end|>` sentinel.** Several report prompts require the model to end output with `<|end|>`;
   downstream parsing depends on it. Keep it unless you also change the parser.

5. These files are **not yet wired** into a loader. They are exported for review/edit; the reload
   mechanism is a follow-up step.
