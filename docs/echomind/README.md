# EchoMind â€” architecture documentation

## Fresh restart and native input staging (2026-09-11)

[Verified restart and complete MONAI input loading](ECHOMIND_RESTART_AND_INPUT_STAGING_2026-09-11.md):
EchoMind restored in 47 seconds; all 1,885 staged candidate inputs loaded through
the Linux worker. Clinical image-reference labels remain pending.

## EchoMind runtime and isolated training environment (2026-09-11)

[Verified endpoint repair, isolated environment and stop/test/restore](ECHOMIND_RUNTIME_AND_TRAINING_ENV_2026-09-11.md):
health/status ok, chat closure repaired, training dependencies isolated and synthetic
full-backbone optimizer/checkpoint checks passed. Reviewed patient labels remain pending.

Operational reference: [A100 stop/start, MONAI capacity test and verified
restoration (2026-09-10)](ECHOMIND_GPU_MAINTENANCE_2026-09-10.md).
This covers the separate Linux service on port 8082 and its external control
tools; it does not change the workstation prompt architecture below.

**Last updated:** 2026-08-09 آ· **Owner modules:** `modules/EchoMind/`, `modules/EchoMind/viewer_chat/`

This set exists so that the prompt system, the region gate and the chat metadata record
can be reproduced on Android and iOS without re-deriving them from Windows source, and
so that a new modality or region can be added without touching anything unrelated.

| # | Document | Read it when |
|---|---|---|
| 1 | [Architecture and workflows](01-architecture.md) | You need the module map, the three backends, or what each button actually does |
| 2 | [Prompt architecture](02-prompt-architecture.md) | You are changing prompt text, or need to know what is shared vs gated |
| 3 | [Region gating](03-region-gating.md) | You are changing gate selection, or adding a region |
| 4 | [Chat metadata](04-chat-metadata.md) | You need where a field comes from, when it is written, or how edits work |
| 5 | [Mobile parity contract](05-mobile-parity.md) | You are implementing EchoMind on Android or iOS |
| 6 | [Extending the system](06-extending.md) | You are adding a modality, region, subtype, lexicon or rule |

---

## The one-page mental model

```
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ DICOM (local DB + file header)
   chat created â”€â”€â”€â”€â”¤
                    â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ reception booking (cached, prefetched during dictation)
                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ the modality the physician picked

                                   â†“  build_auto_from_context()

              â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
              â”‚  CHAT METADATA   ai_session_meta(sid)         â”‚
              â”‚    auto   what detection produced             â”‚
              â”‚    user   only what the physician edited      â”‚
              â”‚    effective = deep_merge(auto, user)         â”‚
              â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
                       â”‚                          â”‚
        shown as the first card in the chat       â”‚  _build_gate_profile()
        (editable â€” an edit writes `user`)        â–¼
                                          â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”گ
                                          â”‚  REGION GATE  â”‚  case.regions â†’ modules
                                          â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”ک
                                                  â–¼
                                      selected region packages
                                   (pathology + normal + terms + notes)
                                                  â–¼
                                          PROMPT ASSEMBLY
                                    shared slots + study facts + gated context
                                                  â–¼
                                                 LLM
```

**One sentence per layer.** Metadata is a record of what the case *is*. The gate turns that
record into a list of region packages. Prompt assembly puts the shared rules, the study
facts and those packages into a fixed slot order. The LLM sees only what the gate selected.

---

## The invariants

These are the things that break the system if you change them without reading the
document that owns them.

1. **The gate reads only `effective` metadata** â€” the same record shown on the card. What
   the gate acts on is exactly what the physician was shown and could have corrected.
   (doc 3)
2. **There is one region layer.** The gate is the sole source of region content in the
   prompt. Nothing else in the prompt is region-specific. (doc 2)
3. **`user` is sparse and never overwritten by detection.** Re-detection refreshes `auto`
   only. (doc 4)
4. **The library is modality-keyed.** `turbo_modules.modules_for(modality, regions)`
   is the only lookup. Never import a library directly and assume the modality.
5. **Region content is Python, never data files.** `AIPacs.spec` needs an explicit
   `datas.append(...)` for every non-`.py` file; storing prompts as `.md` or `.json`
   silently ships an app whose prompts are missing. (doc 6)
6. **Turbo is pinned to the company backend.** The `llm_backend` setting switches Send,
   not Turbo â€” including the correction path.
8. **A gated prompt is never NARROWER than the shared one on failure.** Every degraded
   path sends more, not less. (doc 3)
9. **Mammography is gated by prefix, never by template.** Its schema is regex-locked.
   (doc 2) (doc 1)
7. **A prompt builder that cannot do its job returns `None`**, and the caller falls back
   to the previous behaviour. Never a half-built prompt. (doc 2)

---

## Status of the region-gated prompt

| | |
|---|---|
| Region gate (span narrowing) | **on** by default; `AIPACS_TURBO_PROMPT=0` reverts |
| Template v2 (whole-prompt) | **on** by default since 2026-08-09; `AIPACS_TURBO_PROMPT_V2=0` reverts |
| Modalities with region modules | **All five.** CT, MRI, radiography and ultrasound by template; mammography by prefix (its schema is regex-locked) |
| Regions with modules | CT 21 آ· MRI 19 آ· X-ray 19 آ· US 12 |
| Study-type packages | X-ray 18 آ· ultrasound 9 آ· mammography 5 (the second gate axis) |
| Clinical review | the 10 literature-sourced CT regions, all 19 MRI pathology sets and **nearly all of the X-ray library** are not yet reviewed â€” see doc 6 |

---

## Superseded documents

- [`docs/pipelines/echomind-reporting-prompts.md`](../pipelines/echomind-reporting-prompts.md)
  (2026-07-09) is still correct about the per-modality prompt bodies, the preservation
  rule and the validator. Its statement that the prompt is selected *by modality only* is
  no longer true for Turbo on CT â€” see doc 2.
- `modules/EchoMind/viewer_chat/prompts/*.json` are stale snapshots. Not loaded, not
  authoritative. Prompts are Python.
