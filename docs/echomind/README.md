# EchoMind — architecture documentation

**Last updated:** 2026-08-09 · **Owner modules:** `modules/EchoMind/`, `modules/EchoMind/viewer_chat/`

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
                    ┌─────────────── DICOM (local DB + file header)
   chat created ────┤
                    ├─────────────── reception booking (cached, prefetched during dictation)
                    └─────────────── the modality the physician picked

                                   ↓  build_auto_from_context()

              ┌──────────────────────────────────────────────┐
              │  CHAT METADATA   ai_session_meta(sid)         │
              │    auto   what detection produced             │
              │    user   only what the physician edited      │
              │    effective = deep_merge(auto, user)         │
              └──────────────────────────────────────────────┘
                       │                          │
        shown as the first card in the chat       │  _build_gate_profile()
        (editable — an edit writes `user`)        ▼
                                          ┌───────────────┐
                                          │  REGION GATE  │  case.regions → modules
                                          └───────────────┘
                                                  ▼
                                      selected region packages
                                   (pathology + normal + terms + notes)
                                                  ▼
                                          PROMPT ASSEMBLY
                                    shared slots + study facts + gated context
                                                  ▼
                                                 LLM
```

**One sentence per layer.** Metadata is a record of what the case *is*. The gate turns that
record into a list of region packages. Prompt assembly puts the shared rules, the study
facts and those packages into a fixed slot order. The LLM sees only what the gate selected.

---

## The invariants

These are the things that break the system if you change them without reading the
document that owns them.

1. **The gate reads only `effective` metadata** — the same record shown on the card. What
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
   not Turbo — including the correction path.
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
| Regions with modules | CT 21 · MRI 19 · X-ray 19 · US 12 |
| Study-type packages | X-ray 18 · ultrasound 9 · mammography 5 (the second gate axis) |
| Clinical review | the 10 literature-sourced CT regions, all 19 MRI pathology sets and **nearly all of the X-ray library** are not yet reviewed — see doc 6 |

---

## Superseded documents

- [`docs/pipelines/echomind-reporting-prompts.md`](../pipelines/echomind-reporting-prompts.md)
  (2026-07-09) is still correct about the per-modality prompt bodies, the preservation
  rule and the validator. Its statement that the prompt is selected *by modality only* is
  no longer true for Turbo on CT — see doc 2.
- `modules/EchoMind/viewer_chat/prompts/*.json` are stale snapshots. Not loaded, not
  authoritative. Prompts are Python.
