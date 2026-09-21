# Eagle Eye lumbar saved company model profile

Status: persisted source/build candidate; fresh-source GUI and installer acceptance pending.
Owner: OPT-55. Pipeline provenance version: 8.7.0. No product release version changed.

The owner requested that the best available experimental configuration survive a
future build. This saves the Astra screening/diagnosis candidate with independent
Gemini anatomy and clinical context. It does not promote the unsuccessful mixed
Sol neural experiment, nor establish clinical accuracy or a universally best model.

## Saved routing

| Step | Company model | Evidence/behavior |
|---|---|---|
| Geometry and card construction | Local existing code | Existing source identity and group validation |
| Atomic anatomy mapping | `gemini-3.1-pro-preview` | Independently resolved, recorded in atomic request and aggregate dispatch |
| Five screening domains | `gpt-6-astra` | Existing anatomy cards and screening contracts |
| Clinical context | `gemini-3.1-pro-preview` | Existing bounded context reader |
| All standard diagnostic cards | `gpt-6-astra` | Existing card-bound diagnoses and validators |

For company requests whose exact model ID is `gpt-6-astra` or
`openai/gpt-6-astra`, the reporter sends `detail=original`,
`reasoning_effort=medium`, and the stage budget as `max_completion_tokens`.
It omits `temperature` and legacy `max_tokens`. Other company models retain their
existing transport settings. Stage/card output budgets are unchanged.

This is an Astra diagnostic baseline, not the last research mixture: Sol's
complete-group five-compartment audit was not integrated. Gemini's non-disc
diagnostic branches from that mixture are not the saved default either. The
selected standard Astra diagnostic path had previously been exercised privately;
the latest mixed run provided additional support for disc morphology, but showed
that neural grading remained unreliable. These are selected-pilot observations,
not independent multi-case validation. The new default route has not yet completed
a fresh source-GUI clinical acceptance run.

## Override and provider boundaries

- Explicit `run_analysis(model=...)` pins every model, including anatomy.
- `AIPACS_EAGLE_EYE_MODEL` remains the global environment override.
- `AIPACS_EAGLE_EYE_SCREENING_MODEL`, `AIPACS_EAGLE_EYE_CLINICAL_CONTEXT_MODEL`
  and `AIPACS_EAGLE_EYE_VERIFICATION_MODEL` affect their named stages.
- `AIPACS_EAGLE_EYE_ANATOMY_MAPPING_MODEL` independently overrides anatomy.
  A screening-only pin no longer changes anatomy; use the global pin to change all.
- Direct-provider mode still requires the user's explicit provider settings and
  model slots. Company model defaults do not create a direct OpenAI connection.
- Existing environment or explicit user overrides outrank these saved defaults.
  No machine-local settings, keys, endpoint URLs or installer credentials changed.

Rollback without rebuilding: set `AIPACS_EAGLE_EYE_MODEL=gemini-3.1-pro-preview`
for the source/installed process. Remove that override to restore this candidate.
No environment variable was set on the user's machine by this change.

## Source and packaging authority

- `modules/ai_imaging/eagle_eye_lumbar/analysis_prompt.py`: stage defaults and version.
- `modules/ai_imaging/eagle_eye_lumbar/atomic_pipeline.py`: independent anatomy default.
- `modules/ai_imaging/eagle_eye_lumbar/llm_backend.py`: anatomy resolution and provenance.
- `modules/EchoMind/viewer_chat/openai_reporter.py`: company Astra wire settings.
- The EchoMind reporter's existing plugin payload mirror is synchronized.
- AI Imaging is included by the existing PyInstaller module collection and both
  Nuitka full-core inclusion paths; it has no separate lumbar plugin mirror here.

No private images, reports, results, prompts, identifiers or credentials were copied
into source or installer payloads. Private experiments remain outside distribution.
No installer was built, installed, published or released by this task. A future
build must use `RELEASE.md` and `BUILD.md` and the source changes must be included
in that build's reviewed snapshot.

## Verification

- New guard before implementation: 5 failures / 1 pass, exit 1. Failures reproduced
  unsaved defaults, missing independent anatomy resolution and wrong Astra wire keys.
- Final focused profile, orchestration, atomic/card, explicit-provider and builder
  selection: 164 passed, exit 0; existing SWIG deprecation warnings only.
- Plugin mirror verification: all 468 pairs match, exit 0.
- Synthetic-only real GapGPT call through the actual runtime reporter: passed with
  the saved Astra default. No patient data used. This checks transport, not diagnosis.
- Existing source Test Control Server: `ping` and `list_actions` succeeded. The
  already-running process predates these edits; it was not restarted or hot-patched.
  Fresh-source affected-workflow GUI acceptance and final installer acceptance are
  pending and must not be described as passed.

## Remaining limitations

Neural severity and root-effect reliability, subtle finding recall, the existing
eight-card coverage limit and strict output-contract failures remain open under
OPT-55. This change preserves a reproducible candidate, not a fix for those issues.
Do not hardcode reference diagnoses, choose the most severe response, or replace
failed/missing cards with normal findings.
