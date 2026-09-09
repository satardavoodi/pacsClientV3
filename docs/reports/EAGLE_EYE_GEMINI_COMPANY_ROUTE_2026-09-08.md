# Eagle Eye lumbar: Gemini throughout the company route

Date: 2026-09-08. Status: source change and patient-free provider checks completed; restarted source-app and clinical validation pending. Extends OPT-55. No installed binary, server, credential, clinical image or grading rule was changed.

## Decision and scope

Use `gemini-3.1-pro-preview` for all default lumbar LLM stages: anatomy mapping, every structure screening request, clinical context, individual diagnostic cards and legacy verification fallback. Atomic report assembly remains deterministic local code. Sol is no longer a shipped lumbar default; explicit comparison overrides remain possible and auditable.

This follows the owner's request and prior private within-case evidence, not a claim that Pro outperforms every Flash version. The new sampling profile has not been clinically evaluated. Brain, mammography and general EchoMind reporting are outside this lumbar change.

## Live GapGPT availability

The existing EchoMind credential, endpoint and HTTP authorities queried `/models`. Two catalog reads returned 24 Gemini IDs, including non-diagnostic image, audio and embedding endpoints.

| Family | Listed text/image assessment IDs | Decision |
|---|---|---|
| Pro | `gemini-3.1-pro-preview`, `gemini-3-pro-preview`, `gemini-2.5-pro` | Select the tested 3.1 Pro ID rather than a floating alias. |
| Flash | `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3-flash-preview`, `gemini-2.5-flash` | 3.6 passed synthetic multi-image delivery; not clinically compared here. |
| Flash-Lite | `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.1-flash-lite-preview`, `gemini-2.5-flash-lite`, `gemini-2.0-flash-lite`, `gemini-flash-lite-latest` | No silent smaller-model substitution in diagnosis. |

Google's current model directory lists Flash 3.7 and 3.8. Neither appeared in the live GapGPT catalog. Absence is not a direct inference rejection, and presence alone does not guarantee capability. Tested endpoints returned the requested IDs prefixed with `google/`; these strings do not independently authenticate underlying weights.

## Ten patient-free transport probes

All probes returned HTTP 200; semantic outcomes were evaluated separately.

| Probe | Endpoints | Outcome |
|---|---|---|
| Three separate images, ordered labels, `detail=high` | 3.1 Pro, 3.6 Flash, 2.5 Pro | 3/3 correct. Tests delivery/order, not medical spatial reasoning. |
| Strict schema with required fields and enum values | Same three | 0/3 matched the required object. |
| Explicit `reasoning_effort=high`, three images | 3.1 Pro | Accepted and labels correct; enforcement of the setting is not established. |
| Exact JSON requested in prompt without response-format parameter | 3.1 Pro | Passed. |
| Same prompt with `response_format=json_object` | 3.1 Pro | Passed. |
| Same explicit prompt with the original strict schema | 3.1 Pro | Failed again, returning an empty object. |

The runtime therefore retains prompt-defined structured contracts, JSON extraction and local validation. Provider-enforced strict schema was not enabled. This failure concerns the tested required/enum schema, not every possible schema. Responses, native Google Files/Interactions, caching, video and volumetric DICOM routes were not assumed to work through GapGPT.

Private probe code, catalog IDs, reduced responses and before-edit snapshots remain under `user_data/ai/eagle_eye/_bench/gemini_route_20260908/`. No patient data was used.

## Capabilities and settings

Google documents image/video/audio/PDF input, text output, thinking and structured output for 3.1 Pro, with 1,048,576 input tokens and 65,536 output tokens. These are upstream specifications, not verified GapGPT allowances. Multi-image input does not make this a native DICOM-volume reader: workstation geometry, immutable grouping and anatomical eligibility remain essential.

Google recommends temperature 1.0 for Gemini 3 and warns that lower values can degrade reasoning or induce loops. Context and verification now use 1.0, matching screening. Atomic factories inherit the base temperature rather than silently forcing zero, preserving explicitly selected comparison settings and accurate request provenance.

The transport already sends high-detail image requests. Native `media_resolution` has not been verified through GapGPT and was not added. Reasoning remains the model/provider default: one accepted high-effort request does not prove proxy enforcement. Existing ceilings remain: 24,000 anatomy/screening, 12,000 atomic diagnosis, 6,000 context and 24,000 legacy verification. Clinical optimality of these settings is not claimed.

## Implementation

- `analysis_prompt.py`: Gemini verification default and temperature 1.0 for context/verification. Pipeline 8.6.0, context 2.3.0, verification 5.2.0.
- `atomic_pipeline.py`: version 2.7.0; inherit sampling for anatomy, screening and diagnosis. Geometry, schemas, image selection and grading text unchanged.
- `llm_backend.py`: Gemini fallback; global environment pins resolve at call time instead of returning an import-time cached value. Stage pins retain precedence.
- Actual current source-process resolution returned `company` and Gemini for all base stages without environment pins.
- Explicit direct-provider access remains governed by Settings. No implicit direct OpenAI or Google path was introduced.

## Verification and activation

All five new guards failed before correction, covering mixed dispatch defaults, stale runtime pins and three sampling factories. The final combined selection passes **189 tests**, exit code 0: routing, atomic stages, anatomy, grading, neural coverage, stage audit and explicit-provider selection. Only existing SWIG deprecation warnings were observed. A prompt-only fixture lacking a temperature field also remains supported through a 1.0 default. Source-byte compilation and a before/after comparison confirm all three base prompt texts are unchanged.

Mirror dry-run found zero drift; all 462 pairs match. These three lumbar files have no existing plugin-payload mirrors to update. No installer build or application restart was performed.

The next human-launched source run should record pipeline 8.6.0, atomic 2.7.0, Gemini at every LLM stage and temperature 1.0. Review severe findings and normal-level false positives. Earlier temperature-zero experiments do not validate this profile. Rollback should reverse only scoped model/sampling changes, preserving unrelated work and the call-time override fix.

## Official sources checked

- [Google model directory](https://ai.google.dev/gemini-api/docs/models)
- [Gemini 3.1 Pro specifications](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview)
- [Gemini 3 guide: temperature and migration](https://ai.google.dev/gemini-api/docs/gemini-3)
- [Compatibility API: reasoning controls](https://ai.google.dev/gemini-api/docs/openai)
- [GapGPT](https://gapgpt.app/): availability above comes from authenticated catalog/probes, not public marketing text.
