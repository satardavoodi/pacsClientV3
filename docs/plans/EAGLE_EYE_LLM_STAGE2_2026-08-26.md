# Eagle Eye — Stage 2: sending a capture session to the LLM

> **HISTORICAL IMPLEMENTATION LOG.** This long document preserves the sequence
> of experiments and implementation decisions. For current behavior and
> conclusions, start with `docs/pipelines/eagle-eye-mri.md`. The 2026-09-02
> current-state and atomic-pipeline documents are also historical snapshots.

**Date:** 2026-08-26 · **Current status (2026-09-02):** pipeline 7.0.2,
three focused Gemini screening request groups, each retaining the established
6000-token safety ceiling, in parallel with the clinical-
context branch, followed by independent one-card GPT-5.6 Sol diagnostic requests
through GapGPT. The canonical evidence mode remains `focused-v5-level-cards`,
but positive attention is now grouped by level and anatomical structure. Each
model-facing card contains only the sequences and planes required for that
decision and carries one exact card-local JSON payload. Retired evidence
profiles, including V4, are engineering-only rollback paths, not normal runtime
configuration. Clinical benchmark validation remains open.
**Scope:** captured session → ordered image package → EchoMind OpenAI path → pathology-only
result, stored with the session and reopenable.
**Consumes** the session produced by stage 1 (`EAGLE_EYE_LUMBAR_STAGE1_2026-08-26.md`)
and changes nothing in it.

---

## 1. The pipeline

```
Eagle Eye capture finishes  (capture stage, unchanged)
        ↓  session.json + 2 manifests + N screenshots on disk
llm_package.build_package()      ordered images + captions + PID-0 request doc
        ↓
llm_backend.run_analysis()       ┬─ Gemini MRI screening → attention map
        │                        └─ Gemini paired sagittal T2/T1 + multi-source
        │                           context → global prior + attention foci
        ↓                          (the two branches run concurrently)
GPT-5.6 Sol verification         attention + prior + level cards → final report
        ↓                        (llm_runner puts this on an ApiWorker thread)
analysis_store                   per-stage artifacts + llm_result.txt + the state
        ↓
EagleEyeResultPanel              non-modal, closeable, reopenable
```

### 1a. Why two passes (v2.0.0, 2026-08-26)

Screening and verification want **opposite dispositions**. A single prompt asked
to be both thorough and conservative resolves that tension somewhere in the
middle and does neither: it misses the quiet osseous findings *and* keeps the
over-called disc ones. The first live v1 report was almost entirely discs.

So the pipeline runs two passes with opposite briefs:

| | pass 1 — screening | pass 2 — verification |
|---|---|---|
| disposition | inclusive; preserve every plausible abnormal focus | high-specificity adjudication; resolve each focus and select the best-supported diagnosis |
| output | candidate list (structured) | audit + the report the user sees |
| cost of error | cheap — pass 2 removes it | expensive — it reaches the report |

Pass 2 does **not** "look again". It receives pass 1's candidates as
**hypotheses** and must return CONFIRMED / REFINED / DOWNGRADED / REJECTED /
INDETERMINATE for each, deciding on the plane and sequence where that
abnormality is actually settled — axial T2 for canal, recess and disc
morphology; sagittal T1 for foraminal fat; sagittal for alignment; T1+T2 at the
same position for marrow.

**The user-facing report is always the final stage's.** Guarded by
`test_the_user_sees_stage_TWO_not_the_screening_list`.

### 1b. Carried context rides on the HEADER, not the prompt

The candidate list is per-run data; the stage prompt is a fixed, fingerprinted
contract. Mixing them would make the fingerprint a lie — two runs would share a
prompt fingerprint while having sent materially different instructions. So the
candidates go into the user-message header, and `sent.context` in the stage-2
request document records exactly what was carried.

Capture and analysis are **separate stages on purpose**. When a request fails the
captures are already written and validated, so the cost is a retry, never a
recapture. `test_a_failed_request_keeps_every_captured_frame_and_offers_retry`
pins that.

---

## 2. New files

| File | Role |
|---|---|
| `modules/ai_imaging/eagle_eye_lumbar/analysis_prompt.py` | versioned + **fingerprinted** prompts; the lumbar prompt text |
| `modules/ai_imaging/eagle_eye_lumbar/llm_package.py` | session → ordered, captioned images + request document |
| `modules/ai_imaging/eagle_eye_lumbar/llm_backend.py` | backend/model resolution + the whole headless run |
| `modules/ai_imaging/eagle_eye_lumbar/llm_runner.py` | the Qt/QThread wrapper, and nothing else |
| `modules/ai_imaging/eagle_eye_lumbar/analysis_store.py` | state, request and result on disk |
| `modules/ai_imaging/ai_module_ui/service_tab/eagle_eye_result_panel.py` | the non-modal result window |

Touched: `protocols.py` (`Protocol.analysis`, `.analysable`), `constants.py`
(three filenames), `imaging_tab.py` (trigger, state, `closeEvent`),
`EchoMind/settings_store.py` (`eagle_eye` feature → model),
`EchoMind/viewer_chat/openai_reporter.py` and `openai_parallel_backend.py`
(the multi-image call). The last three are **plugin-mirrored**; 456/456 pairs match.

Everything except `llm_runner.py` and the panel is pure python and runs headless.

---

## 2b. What is kept, per run (§15)

```
llm_stage1_request.json     what pass 1 was asked, incl. the full prompt text
llm_stage1_response.txt     pass 1's raw answer
llm_stage1_structured.json  its candidate block, with `parsed: true|false`
llm_stage2_request.json     …same for pass 2, plus `sent.context` = the candidates
llm_stage2_response.txt
llm_stage2_structured.json  the verification audit (status per candidate)
llm_result.txt              THE REPORT — pass 2's, what the user sees
llm_result.json             state, model, pipeline id/version/fingerprint,
                            per-stage fingerprints, image count, summed usage
```

`parsed: false` is written explicitly rather than the file being absent, so an
evaluation can tell "the model produced nothing structured" apart from "nobody
looked".

**Usage is summed across passes.** A two-pass run costs two requests; reporting
only the last would understate what the study spent. The per-stage breakdown is
kept under `usage.stages`.

**Cost roughly doubles**: both passes send all the images. At the measured
~1,400 tokens/image a 31-frame study goes from ≈49K to ≈100K input tokens —
about **$0.15 → $0.30** on `gpt-5.6-sol`.

---

## 3. The prompt is protocol data

`Protocol.analysis` holds an `AnalysisPipeline` — ordered `AnalysisStage`s —
exactly the way `Protocol.sessions` holds the sweeps. The packaging and request
code contains no body-part knowledge; adding Brain MRI analysis is a pipeline
entry plus one reference. The engine loops over `pipeline.stages` and does not
know how many there are: a third pass would be configuration, not code.

Both lumbar stages compose a **shared package preamble** (what the sessions are,
the clean-pane rule, the metadata-trust rules, the windowing trap) with their own
body, written once so the two passes cannot come to disagree about what they are
looking at. `test_both_stages_carry_the_shared_package_rules` pins it.

`Protocol.analysable` is deliberately separate from `implemented`: a protocol
whose sweeps work is still useful without a prompt, and offering an analysis it
cannot perform would fail *after* the whole study had been captured.

### Why a fingerprint as well as a version

§17 of the request asks to store the prompt version so revisions can be compared
objectively. A hand-maintained version answers that only while everyone remembers
to bump it — edit the text and forget, and two different prompts share a version,
and every comparison after that is silently meaningless.

`AnalysisStage.fingerprint` is the SHA-256 of the text actually sent, and
`AnalysisPipeline.fingerprint` chains **every** stage's in order. A pipeline is
only the same pipeline when BOTH passes are unchanged — comparing runs on stage
1's fingerprint alone would silently mix results produced by two different
verification prompts. `test_the_pipeline_fingerprint_covers_EVERY_stage` pins it.

---

## 4. What the model receives

Not a bag of screenshots. The header states the layout and, per sweep, which panes
are evaluated and which are localisers. Then each image is preceded by its caption:

```
[lumbar_sagittal] frame 1 of 11; sweep direction right_to_left;
Sagittal T2 slice #0 (EVALUATE - no reference line) |
Sagittal T1 slice #0 (EVALUATE - no reference line, position-matched to 0.00 mm) |
Axial T2 slice #12 (localiser - reference line drawn);
slice position 7.8 mm right of the midline - GEOMETRY ESTIMATE of where the SLICE
lies, not a zone assignment for any finding;
axial z = 124.5 mm (88.3 mm below the top of the axial stack)
```

### 4a. The rule the two-session design rests on

> **Read diagnostically from the panes with no reference line.**

It is not a second convention invented for the prompt — it is
`capture_order.reference_lines_hidden_on`, already in the manifest, already the
thing v1.1.0 suppresses lines by. Sagittal sweep → read the sagittals, axial pane
localises. Axial sweep → the reverse. One rule, derived from data, in place of two
session-specific rules that could drift apart.

This **inverts** the old single-screenshot prompt's rule 8 ("do not interpret the
axial panel as a diagnostic series"), which was right when one screenshot was one
sagittal slice and is wrong half the time now.

### 4b. Geometry labels are demoted, on purpose

`spatial_context.region` emits `paracentral_lateral_recess`, `foraminal`,
`extraforaminal` — computed from fixed millimetre bands (≤5 mm, ≤22 mm) around an
**estimated** midline. Handed over bare, `"region": "left_foraminal"` reads as a
zone assignment and invites a foraminal finding to match it.

Every caption therefore says the label describes **where the slice was taken**,
never where a finding is, and the raw band string never travels on its own
(`test_a_slice_position_label_is_marked_as_an_estimate_not_a_zone`).

The zone of a finding comes from the axial images. No vertebral level is supplied
at all — `geometry.axial_context` deliberately does not infer one — so the prompt
requires the model to **declare its level map before reporting anything**, which
turns a wrong-level finding into something visible instead of silent.

### 4c. An incomplete session is refused

`build_package` compares each manifest's `capture_count` against the captures it
lists *and* against the files on disk, and raises on either mismatch. Same lesson
as the capture side: a partial sweep is made of individually valid frames, so
nothing but the count reveals it — and a partial study analysed as whole produces
a confident report about anatomy nobody looked at.

---

## 5. Integration: reuse, not a second path

Eagle Eye adds **no** authentication, endpoint, proxy, retry or key handling.

* backend: `settings_store.get_llm_backend()` — the user's own EchoMind selection
* model: `get_openai_model_for_feature("eagle_eye")`, a new entry in the existing
  feature→model table, defaulting to `gpt-5.6-sol`
* transport: each backend's own `EagleEyeImageAnalysis`, beside `reporter` and
  `correction`, on `echomind_http.post` like every other outbound call
* thread: `ai_chat_api.ApiWorker`, the workstation's existing AI worker

`test_the_backend_selection_follows_the_users_echomind_setting` fails if
`api_key`, `Authorization`, `https://` or `requests.` ever appear in the bridge.

### 5a. Three things the existing single-image path got wrong for this use

| | before | now |
|---|---|---|
| images per call | exactly 1 | the whole session, in capture order |
| MIME | hardcoded `image/jpeg` for any file | derived from the suffix — Eagle Eye writes **PNG** |
| detail | unset | `high` — the anatomy is a few hundred px of a downscaled pane |
| max_tokens | 2000 | 6000; a level-by-level report truncates at 2000 |

Both backends call **one** shared `build_eagle_eye_user_content`, so image order,
MIME and detail cannot drift between them — the same rule the report prompts
already follow.

### 5b. The model id is overridable without a rebuild

`AIPACS_EAGLE_EYE_MODEL`, mirroring `AIPACS_ECHOMIND_PRIMARY_MODEL`. A provider
can rename or retire an id at any time and a wrong id fails only at request time,
**after** the whole study has been captured.

`gpt-5.6-sol` was **confirmed by the owner** (2026-08-26) against a working
GapGPT snippet using `base_url="https://api.gapgpt.app/v1"` — which is exactly
`GAPGPT_API_URL` minus `/chat/completions`, i.e. the company backend this
defaults to.

### 5c. The key: one source, and it only exists inside the running app

The GapGPT key is **not** a static secret in a config file. It is derived at
runtime per center: `Manage.get_center_and_gapgpt_key()` →
`ensure_detected()` → `get_irannobat_key()`, which raises *"No validated
IRANNOBAT API key"* unless `APIKeyManager` has been validated **in this
process**. Eagle Eye obtains it exactly the way every other GapGPT call does.

Two consequences:

* `EagleEyeImageAnalysis` accepts `CENTER_Key` for signature parity with the
  OpenAI twin and **deliberately ignores it** — an override would be a way to
  route Eagle Eye through a different key than the rest of EchoMind.
  `test_the_gapgpt_call_uses_the_SAME_center_key_as_every_other_call` pins that
  the only source is `m.get_center_and_gapgpt_key()`.
* A standalone connectivity probe is **impossible by design** — a bare python
  process has no validated key. The live proof of auth + model + payload shape
  is the first in-app Eagle Eye run. An unvalidated key surfaces as the
  ValueError above, caught by `run_analysis` and shown verbatim in the result
  panel, so the failure names itself.

---

## 6. State: one authority, and no state you cannot leave

`llm_result.json` holds the state — `not_analyzed` / `analyzing` / `complete` /
`failed`. It is deliberately **not** mirrored into `session.json`: two files
claiming to know whether an analysis finished is two files that can disagree, and
the wrong one is always the one someone reads.

Two ordering rules:

* `mark_complete` writes `llm_result.txt` **first** and flips the pointer last, so
  a reader that sees `complete` always finds something to show. If the text is
  missing anyway, `read_record` degrades to a retryable failure rather than
  opening an empty window.
* A 200 carrying an empty body is a **failure**, not a study with no findings.

### 6a. Stale `analyzing`

A crash or a close during a request leaves `analyzing` with nothing left to finish
it, and a state that can never be left blocks retry forever. The record carries
`pid` and `started_at`; a reader in a different process — or after 30 minutes —
reports it as *interrupted* and offers retry.

---

## 7. UI

Non-modal by construction: a top-level `QDialog`, `setModal(False)`, `show()` and
never `exec()` (which spins a nested loop and blocks every other window).
`WA_DeleteOnClose` is deliberately not set — the panel is reused, and closing it
destroys nothing, because the result lives on disk. Reopening re-reads it.

`View Eagle Eye Result` sits beside the capture status and appears only once a
session actually has something behind it. Re-analyze sends the same images again;
it never recaptures.

`ImagingToolsTab.closeEvent` detaches an in-flight run. The worker is a QThread
parented into the tab, and destroying a running QThread aborts the **process**
with "QThread: Destroyed while thread is still running" — no traceback, the log
just stops. Detach, never wait: the HTTP request can take minutes.

---

## 7b. UI: which pass is running

The two passes take comparable time, so one undifferentiated "Analyzing…" for the
whole run reads as a stall halfway through. `run_analysis` takes a
`progress(number, total, name)` callback; the runner turns it into a
`stage(int, int, str)` **signal emitted from the worker thread**, which Qt queues
so the slot still runs on the GUI thread. Status shows
*"Eagle Eye is analyzing the lumbar MRI — Stage 1/2…"* then *"…verifying the
findings — Stage 2/2…"*.

The callback is best-effort: a raising progress handler must never take down an
analysis that is otherwise fine
(`test_progress_is_reported_once_per_stage_and_cannot_break_the_run`).

The internal candidate list and the audit trail are **not** shown — they are on
disk for evaluation. The panel shows only the final report.

---

## 8. Tests

`tests/code/ai_imaging/test_eagle_eye_llm_analysis.py` — 49 guards, headless,
transport injected (stage-aware: each pass answers in its own contract).
Suites: `tests/code/ai_imaging` **475 passed / 8 xfailed**; `tests/code/echomind`
**2310 passed / 12 skipped / 4 xfailed**; `tests/code/viewer` **2288 passed**;
mirrors **456/456**. `analysis_prompt.py` has **no plugin mirror** — one copy,
nothing to sync.

Two guards are worth naming because they cover failure modes that would be
invisible in a green run:

* `test_an_unparseable_candidate_block_degrades_instead_of_failing` — if pass 1's
  JSON will not parse, its **prose** is carried to pass 2 instead. Losing the
  candidates entirely would silently reduce a two-pass run to a lone
  conservative read.
* `test_a_verification_answer_without_the_marker_still_yields_a_report` — the
  report is what the user sees, so a missing `FINAL REPORT` marker must not blank
  it; the answer minus its fenced JSON is used.

One pre-existing guard was bumped rather than loosened:
`test_pipeline_scoping` counts outbound calls in `openai_reporter.py` and went
10 → 11. It caught a real drift first — the new call had been written with
`echomind_http.post(GAPGPT_API_URL, ...)` instead of the pinned
`url = GAPGPT_API_URL` / `post(url, ...)` shape. The code was conformed; the
count is now a named constant with a note that it rises **once per added call**.

---

## 9. Open after the first live run

1. ~~The model id~~ — confirmed: `gpt-5.6-sol` on GapGPT, same key, same URL.
2. **PHI** — the screenshots still carry the burned-in overlay (name, ID, date);
   the owner decided that is acceptable for this test. Only the *structured*
   metadata is anonymised (`PID 0`). Cropping the panes would remove the overlay,
   drop ~15% sidebar chrome and raise effective resolution at the same token cost.
3. **41 images per study** is a large request; trim afterwards using the level map
   the model declares, not before.
4. `session.json` demographics are still empty (`build_study_context` reads fields
   `AIPatientWidget` does not populate). Harmless here — stage 2 sends `PID 0`.

---

## 10. Specificity calibration — pipeline 3.0.0 (2026-08-26, later same day)

The first live two-pass run confirmed the mechanics but not the calibration:
stage 2 verified the candidates and then kept almost all of them. Verification
that never removes anything is a re-read with extra steps, and the report was
long enough that the findings that mattered were buried among borderline ones.

### 10a. What changed, and where

Everything below lives in `_LUMBAR_VERIFICATION_BODY` **only**:

| Block | Answers |
| --- | --- |
| `USE A HIGH-SPECIFICITY REPORTING THRESHOLD` | pass 1 asks *could this be abnormal?*, pass 2 asks *does this deserve a place in the report?* |
| `THRESHOLDS FOR THE COMMONLY OVERCALLED FINDINGS` | disc contour; disc desiccation (~10% insufficient / ~20% may support); facet, flavum and osteophytic change |
| `A CALIBRATION FOR "IS THIS OUTSIDE NORMAL?"` | central ~60% normal · ~20% either side borderline · beyond that pathologic |
| `THE CLINICAL SIGNIFICANCE TEST` | canal / recess / foramen / root / alignment / vertebral-body consequence, or it does not earn a line |
| `REMOVE THESE` | seven explicit removal criteria |
| `THE DECISION THRESHOLD` | six questions, all yes, before CONFIRMED or REFINED |

Stage 1 gained the **opposite** instruction (one short paragraph): pass 2 culls
hard by design, that is not a reason to pre-filter, stay inclusive.

### 10b. The percentages are calibration language, not measurements

`~10%`, `~20%`, `~60%` describe **how large a difference has to look** before it
is worth calling. The prompt says so in the same breath as each number, and adds
*"do not measure signal intensity"*, *"report no numeric percentage"*,
*"compute nothing and report no percentiles"* — otherwise a model handed a
number tends to start producing numbers it cannot measure from a
few-hundred-pixel screenshot.
`test_the_calibration_numbers_are_labelled_as_NOT_measurements` pins that each
number keeps its disclaimer.

### 10c. Why the asymmetry is a guarded invariant

Two passes only beat one prompt while their dispositions stay **opposite**.
Copying the threshold language into screening collapses them back into a single
middling reader that both misses quiet osseous findings *and* keeps overcalled
disc ones — precisely the failure the split exists to avoid. It is an easy edit
to make by accident (the language reads like good radiology advice anywhere), so
`test_the_specificity_CALIBRATION_STAYS_OUT_of_stage_one` asserts each block is
**absent** from stage 1 and that stage 1 still carries its inclusive brief.

### 10d. Versions

| | before | after |
| --- | --- | --- |
| `lumbar_screening` | 1.0.0 | **1.1.0** (brief unchanged; told what pass 2 does) |
| `lumbar_verification` | 1.0.0 | **2.0.0** (changes *which* findings reach the user) |
| `lumbar_pathology` | 2.0.0 | **3.0.0** |

`test_a_successful_run_stores_the_text_and_the_provenance` pins `3.0.0`
deliberately rather than reading it from the pipeline: a stored result must be
traceable to a named revision, so a bump stays an explicit edit.

Sizes (`tools/analysis/oneoff/eagle_eye_prompt_sizes_2026_08_26.py`):

```
lumbar_screening     v1.1.0    7239 chars
lumbar_verification  v2.0.0   13987 chars   (was 8817)
pipeline lumbar_pathology v3.0.0
```

Cost impact is negligible: +5.2 KB of prompt is ~1.3k tokens against ~49k of
image tokens, roughly +2.6% on the input side of one pass.

### 10e. The honest risk

**A filter this aggressive can remove real findings.** That is the trade the
owner asked for — *"prefer missing a very minor borderline change rather than
converting every subtle variation into pathology"* — but it is a trade, not a
free win, and it should be measured rather than assumed.

The counterweight already exists on disk: `llm_stage2_structured.json` records
every REJECTED and DOWNGRADED candidate **with its reason**. Read a handful of
runs' rejection lists against the images. If findings the owner would have
reported are being rejected, the calibration is too tight and the numbers in
10a are the dial to turn — not the two-pass architecture.

Two specific things to watch in the first calibrated runs:

1. **Over-culling at a single level.** A level whose only finding was
   DOWNGRADED to nothing disappears from the report entirely; the audit block is
   the only trace.
2. **Question 5 of the decision threshold** (*does it have a consequence worth
   reporting?*) is the strictest of the six. A genuine early degenerative change
   with no canal or foraminal consequence will now be dropped by design. If the
   owner wants those retained as context, that question is the one to relax.

---

## 11. Per-stage models — Gemini on the screening pass (2026-08-26)

Owner's call: run pass 1 on `gemini-3.1-pro-preview` (GapGPT, same key, same
endpoint) while pass 2 stays on `gpt-5.6-sol`. Detection over ~31 frames and
adjudication against a strict threshold are different jobs; this is the cheapest
honest way to find out whether a different model reads the osseous and
posterior-element categories better.

### 11a. The model became per-STAGE, not per-pipeline

`AnalysisStage` already carried `model_feature`; it now also carries
`model_default`, and `llm_backend.resolve_model(backend, stage)` takes the stage.
`run_analysis` resolves **once per stage**, inside the loop.

| | feature slot | default |
| --- | --- | --- |
| `lumbar_screening` | `eagle_eye_screening` | `gemini-3.1-pro-preview` |
| `lumbar_verification` | `eagle_eye` | `gpt-5.6-sol` |

Precedence, most specific first:

1. `AIPACS_EAGLE_EYE_SCREENING_MODEL` / `AIPACS_EAGLE_EYE_VERIFICATION_MODEL` —
   swap **one** pass in the field
2. `AIPACS_EAGLE_EYE_MODEL` — pin the **whole** pipeline to one model. It
   deliberately outranks a stage default: it is the one-line way to call off an
   experiment on a machine in clinical use, without a rebuild
3. the stage's Settings slot (OpenAI-direct path only) → its `model_default`

### 11b. The trap this could have hit

`get_openai_model_for_feature` does **not** raise on an unknown feature name —
it silently falls back to `text_model`. A new stage naming a slot nobody added
to the map would have sent a *chat* model 31 screenshots, and failed only at
request time, after the study was captured. Both slots were added to
`settings_store` (defaults, `get_openai_settings`, the feature map, and the save
path), and `test_every_stage_feature_IS_MAPPED_in_the_settings_authority` pins
it for every stage, present and future.

The `settings_store.py` plugin mirror was re-synced — 456/456 pairs match.

### 11c. Provenance had to stop being one string

`llm_result.json` carried a single `model`. For a mixed run that field can only
lie about one pass. Now:

* `model` — the run-level summary. Identical stages collapse to the one name; a
  mixed run reads `"gemini-3.1-pro-preview -> gpt-5.6-sol"`.
* `stage_models` — the per-pass truth, in order. **This is what a comparison
  should read.** Empty on records written before this change.
* each `llm_stage{N}_request.json` records the model *that* stage was sent with.
* each entry in the merged `usage.stages` gained `stage_model`, so per-pass spend
  stays attributable when the passes cost different amounts.

### 11d. Nothing about the prompts or the transport changed

Both stage fingerprints are unchanged (`4cacceb8…` / `a168e14e…`, pipeline
`caf4adfe…`), which is the point: the only variable in this A/B is the model on
pass 1. The GapGPT payload is a plain OpenAI-compatible `chat/completions` body —
model name, messages, temperature, `max_tokens` — so nothing was model-gated and
the transport was not touched.

### 11e. What is NOT yet known — verify on the first live run

1. **Whether GapGPT's Gemini route accepts 31 `image_url` parts in one request.**
   Untested. A failure here costs the request, not the captures — Retry is
   offered — but it is the most likely way this falls over.
2. **Whether `"detail": "high"` is honored or ignored** on the Gemini route. If
   ignored, pass 1 may be reading downscaled panes, which would show up as a
   thinner, vaguer candidate list rather than an error.
3. **Cost.** `gemini-3.1-pro-preview` pricing on GapGPT was not checked; the
   ~$0.30/study figure in §1 assumes `gpt-5.6-sol` on both passes and no longer
   holds. Read `usage.stages[].stage_model` after the first run.
4. **JSON discipline.** Pass 1 must emit a fenced `CANDIDATE FINDINGS` block. If
   it does not parse, the run degrades to carrying pass 1's prose instead
   (guarded, §8) — quietly. Check `llm_stage1_structured.json` for
   `"parsed": false` before judging the experiment on the report alone.

### 11f. How to read the result honestly

Compare against the `gpt-5.6-sol` baseline on the **candidate list**, not the
final report — pass 2 is unchanged, so a difference in the report is downstream
of a difference in what pass 1 raised. `llm_stage1_structured.json` is the
comparison; `llm_stage2_structured.json` says what pass 2 did with it. Two
questions worth asking: did Gemini raise more *osseous and posterior-element*
candidates (the category that motivated the two-pass split), and did it raise
more that pass 2 then rejected (sensitivity bought with noise)?

To call it off: `set AIPACS_EAGLE_EYE_MODEL=gpt-5.6-sol` — no rebuild, both
passes back on the known model.

---

## 12. POSTMORTEM — the per-stage model was dead code in the app

Session `20260826T191537Z` ran with pipeline 3.0.0 and reported
`model gpt-5.6-sol`. Both passes used gpt-5.6-sol. The Gemini experiment never
happened, and **nothing failed**.

### 12a. Root cause: a second resolver one layer up

`run_analysis` resolved per stage correctly. `llm_runner.start()` — the only
real-world caller — claims the session on the GUI thread before the worker
exists, and it did:

```python
model = llm_backend.resolve_model(backend)          # no stage → DEFAULT_MODEL
mark_analyzing(..., model=model, ...)               # no models= → stage_models []
run_analysis(..., model=model, started=started_doc) # ← pins EVERY stage
```

`run_analysis` reads `model=` as *the caller named a model*, which is correct
behaviour, so it applied it to both passes. The per-stage defaults became dead
code in the one path that matters.

This is the same class of miss as the entitlement bug in §5: the layer being
edited was read, the layer above it was not.

### 12b. Why the tests passed and the UI looked right

* Every test calls `run_analysis` **directly**, with no `model=`. The runner was
  never in the loop.
* The stored `stages` metadata still advertised
  `"model_default": "gemini-3.1-pro-preview"` — because that is prompt
  configuration, not what was sent.
* The header showed `gpt-5.6-sol`, which is what a run with two identical stages
  is *supposed* to show.

Only two fields gave it away: `"stage_models": []` (the runner passed no
per-stage list) and `usage.stages[0].stage_model == "gpt-5.6-sol"`. **Those two
together are the signature of an affected run.**

### 12c. Fix

One authority, called by both: `llm_backend.resolve_stage_models(pipeline,
backend, model="")` and `summarize_models(stage_models)`. The runner now calls
them for what it has to write and passes **no** `model=` down;
`run_analysis` resolves for itself through the same function, so the two cannot
disagree.

Guards: `test_the_Qt_RUNNER_does_not_pin_the_model_for_every_stage` reads the
runner's `run_analysis(...)` call and fails if `model=` reappears in it (a
source guard — instantiating the runner needs Qt, ApiWorker and a real thread);
`test_the_two_resolvers_cannot_disagree` pins that both paths get the same
answer from the same function. `ai_imaging` + `echomind` **2793 passed**.

### 12d. What the run DID tell us — the calibration works as a filter

Same session, on the calibrated 3.0.0 prompts, both passes on gpt-5.6-sol:

* Stage 1 raised **19 candidates** across L3-L4, L4-L5 and L5-S1.
* Stage 2 kept **8** (all L4-L5) and rejected **11**.

That is the first evidence that stage 2 is behaving as a filter rather than a
re-read — before the calibration it kept nearly everything.

### 12e. ...and where it over-culled

**L5-S1 disc desiccation was REJECTED.** Stage 1 rated it `high` confidence —
*"markedly reduced T2 disc signal"* — and stage 2's reason was:

> "Although T2 signal is reduced, the isolated change has no convincing stenotic
> or neural consequence and does not meet the concise-report threshold."

That is §10's clinical-significance test (question 5) doing exactly what it was
written to do, applied to a finding that was never borderline. **Convincing disc
desiccation is reportable pathology in its own right**, whether or not it
narrows anything — and the same reasoning also dropped L5-S1 disc height loss.

The rule is too broad as written: it should gate *borderline* findings, not
findings that are convincingly visible. Proposed narrowing — the consequence
test applies only when the finding's own visibility is borderline; a finding
that is clearly and reproducibly demonstrated stands on its own, with its
absence of canal/recess/foraminal effect stated rather than used to delete it.

The L3-L4 rejections look correct: stage 1 rated those `low` confidence and
stage 2's reasons match (preserved thecal sac, no recess effacement).

### 12f. Fix — pipeline 3.1.0, the consequence test gates borderline findings only

`lumbar_verification` 2.0.0 → **2.1.0**, pipeline 3.0.0 → **3.1.0**. Three edits,
all in `_LUMBAR_VERIFICATION_BODY`:

1. `THE CLINICAL SIGNIFICANCE TEST` became
   **`… - FOR BORDERLINE FINDINGS ONLY`** and now branches first on how
   *convincing* the finding is. Clearly and reproducibly demonstrated findings
   stand on their own — convincing desiccation, definite height loss, a definite
   protrusion, a vertebral deformity, unambiguous spondylosis — and the absence
   of a canal/recess/foraminal consequence is **stated as part of the finding**,
   never used to delete it. Only borderline findings must earn their line.
   > "The distinction is HOW CONVINCING the finding is, not how severe it is. A
   > mild but unmistakable finding is reportable; a possible but
   > severe-sounding one is not."
2. `REMOVE THESE` split in two. Four criteria still remove outright (one slice,
   not confirmed on the orthogonal plane, plausible normal variation, could be
   windowing). The three consequence-flavoured ones — minimal anatomical effect,
   no canal/recess/foraminal/root consequence, common at this age — now apply
   **only when the finding is borderline**.
3. The decision gate lost question 5 (six questions → five). It would otherwise
   re-apply the consequence test to everything through the back door. The prompt
   says so explicitly, so a later edit does not "helpfully" put it back.

Guard: `test_the_consequence_test_gates_BORDERLINE_findings_only` pins the
scoping *and* asserts the gate has exactly five questions.

Verification prompt 13,987 → 15,514 chars; fingerprints
`4cacceb8…` (screening, unchanged) / `2a4b4f43…` (verification) / `098ac100…`
(pipeline). `ai_imaging` + `echomind` **2794 passed**, mirrors 456/456.

Expected effect on the same study: L5-S1 desiccation and disc height loss return;
the L3-L4 rejections (all `low` confidence, preserved thecal sac) stay rejected.
That is the check to run first.

---

## 13. Session `20260826T202150Z` — the combination ran, and the run was degraded

First run with `gemini-3.1-pro-preview -> gpt-5.6-sol` on pipeline 3.1.0. Same
study as §12 (patient 55930), 41 images, 123,617 tokens, 1 min 50 s.

### 13a. The plumbing is confirmed

```
"model": "gemini-3.1-pro-preview -> gpt-5.6-sol"
"stage_models": ["gemini-3.1-pro-preview", "gpt-5.6-sol"]
usage.stages[0].stage_model == "gemini-3.1-pro-preview"
usage.stages[1].stage_model == "gpt-5.6-sol"
```

The §12 runner fix works, and GapGPT's Gemini route accepted all 41 `image_url`
parts — unknown #1 from §11e is answered.

### 13b. But the report is not the product of that combination

`llm_stage1_structured.json` → **`"parsed": false`**. Stage 1's answer is cut off
mid-string, inside the second field of the first finding:

```
CANDIDATE FINDINGS
```json
{ "findings": [ { "level": "L1-L2", "candidate": "schmorl_node", ...
      "evidence": [ "sagittal_t2        ← ends here
```

So the degradation path fired (correctly, §8): pass 1's **prose** was carried
forward instead of its candidates. `llm_stage2_structured.json` shows stage 2
received exactly **one** candidate, rejected it, and then wrote the entire report
itself as two `ADDED` findings.

**This was a single-pass gpt-5.6-sol read wearing a two-pass costume.** Gemini
contributed one rejected Schmorl node.

### 13c. Root cause: the screening output ceiling, not the model

| run | screening model | completion tokens | ceiling | outcome |
| --- | --- | --- | --- | --- |
| `…191537Z` | gpt-5.6-sol | 3993 | 4000 | parsed — at 99.8% of the cap |
| `…202150Z` | gemini-3.1-pro-preview | 3996 | 4000 | **truncated** |

`max_output_tokens=4000` on the screening stage was never a margin; gpt-5.6-sol
fit by luck. This stage is the verbose one by design — every candidate at every
level as pretty-printed JSON — so a model that formats generously overruns first.

Fixed: **both stages raised to 12,000**. A ceiling costs nothing unless it is
used. Guard: `test_no_stage_ceiling_is_close_to_what_a_model_actually_produces`
requires every stage to sit at ≥2× the largest answer ever measured.

### 13d. Truncation is now visible instead of inferred

`parsed: false` alone cannot distinguish *"this model cannot emit JSON"* from
*"this model ran out of room"* — opposite fixes. `llm_stage{N}_structured.json`
now also records `model`, `completion_tokens`, `max_output_tokens` and
`truncated`, and the loop logs a WARNING naming the stage, model and the
token count when a pass lands on its ceiling. Guards:
`test_a_truncated_pass_is_RECORDED_not_just_silently_degraded`,
`test_a_normal_answer_is_not_flagged_as_truncated`.

### 13e. Gemini's level map is geometrically wrong

`tools/analysis/oneoff/eagle_eye_axial_slabs_2026_08_26.py` on this session's
own manifest — objective, from the DICOM z-positions:

```
30 axial frames, 7 slabs by the large z-gaps:
  1-4 | 5-8 | 9-12 | 13-16 | 17-20 | 21-26 | 27-30
  (gaps 9.5, 13.0, 23.8, 27.9, 27.9, 41.6 mm; within-slab 4.3-5.3 mm)
```

| | frames | boundaries | top level |
| --- | --- | --- | --- |
| geometry | 30 | 4/5 · 8/9 · 12/13 · 16/17 · 20/21 · 26/27 | — |
| **gpt-5.6-sol** | 30 | **exact match, all 6** | T11-T12 |
| gemini-3.1-pro-preview | 26 | 5/6 · 11/12 · 16/17 · 21/22 (**1 of 4 correct**) | L1-L2 |

Gemini dropped four frames and put its top slab at L1-L2 where the geometry and
gpt-5.6-sol both say T11-T12 — a **two-level shift** across the whole study.
gpt-5.6-sol has now matched all seven physical slabs exactly, on two separate
runs. This did not reach the report only because the truncation meant stage 2
rebuilt the map itself.

### 13f. What actually improved the report

The §12f calibration fix, exactly as predicted: **L5-S1 disc desiccation is back**
("without significant canal, lateral recess, or foraminal narrowing" — the
consequence stated, not used to delete). That is 3.1.0 working, and it would have
happened on gpt-5.6-sol alone.

### 13g. ⚠ The severity call swung on identical images

| | `…191537Z` (3.0.0, gpt/gpt, 19 candidates) | `…202150Z` (3.1.0, gemini/gpt, 1 candidate) |
| --- | --- | --- |
| L4-L5 canal | **severe** central canal stenosis | **mild** central canal narrowing |
| L4-L5 recess | severe bilateral lateral recess stenosis | mild bilateral |
| cauda equina | crowding reported | absent |
| facet arthropathy / hypertrophy | reported | absent |
| ligamentum flavum | thickening reported | absent |

Same patient, same frames, opposite severity. The shorter report is not
necessarily the better one — it is the one produced without a candidate list to
adjudicate. **Neither run is yet a fair test of the combination.** Re-run at
3.1.0 with the 12,000-token ceiling before drawing any conclusion; that is the
first run where pass 1 will actually reach pass 2.

---

## 14. Session `20260826T205136Z` — the first honest two-pass run

Same study, pipeline 3.1.0, `gemini-3.1-pro-preview -> gpt-5.6-sol`, 41 images,
126,759 tokens, 2 min 14 s.

### 14a. The pipeline is healthy

```
stage 1  gemini-3.1-pro-preview   4743 / 12000 tokens   parsed: true   truncated: false
stage 2  gpt-5.6-sol              3777 / 12000 tokens   parsed: true   truncated: false
```

**4743 > 4000**: this run would have been truncated again at the old ceiling, and
also at 4500. §13c was the right diagnosis.

13 candidates in, 13 verified out — every one accounted for exactly once, no
`ADDED`, no degradation. **6 survived, 7 rejected.** This is the first run where
stage 2 actually adjudicated a list rather than writing its own report.

| level | candidate | status |
| --- | --- | --- |
| L2-L3 | desiccation, bulge | REJECTED ×2 |
| L3-L4 | desiccation | CONFIRMED |
| L3-L4 | bulge | REFINED → mild, mild canal narrowing |
| L3-L4 | facet, flavum | REJECTED ×2 |
| L4-L5 | desiccation | CONFIRMED |
| L4-L5 | bulge | REFINED → moderate canal + bilateral recess |
| L4-L5 | facet, flavum | CONFIRMED ×2 |
| L5-S1 | desiccation | CONFIRMED |
| L5-S1 | bulge, facet | REJECTED ×2 |

The L4-L5 stenotic combination (bulge + facet + flavum) is back — it had vanished
in the degraded run — and L5-S1 desiccation survives on its own, which is 3.1.0.
Severity landed at **moderate**, between 3.0.0's *severe* and the degraded run's
*mild*.

### 14b. ⚠ THE TWO STAGES DISAGREE ABOUT THE LEVEL MAP BY ONE LEVEL

Geometry is not in doubt. From the DICOM z-gaps, 1-based caption frames:

```
slabs:  1-4 | 5-8 | 9-12 | 13-16 | 17-20 | 21-26 | 27-30      (7 slabs)
```

| | slab boundaries | top slab | 21-26 slab | bottom slab |
| --- | --- | --- | --- | --- |
| geometry | 4/5 · 8/9 · 12/13 · 16/17 · 20/21 · 26/27 | — | — | — |
| gpt-5.6-sol (stage 2) | **all 6 exact** | T11-T12 | **L4-L5** | L5-S1 |
| gemini (stage 1) | 4 of 6 (3/4 and 7/8 wrong) | T12-L1 | **L5-S1** | Sacrum |

Gemini improved sharply on §13e (was 26 frames and 1/4 boundaries; now 30 frames
and 4/6), but its **labels sit one level lower than gpt's on every slab**.

The candidates carry Gemini's labels. Stage 2 verified them, kept those labels in
`refined_finding`, and then printed **its own** level map above the report. So:

> The report says `L4-L5: … moderate central canal and bilateral lateral recess
> narrowing`, above a map where L4-L5 = frames 20-25. But that finding was raised
> at Gemini's L4-L5 = frames 17-20, which the same map calls **L3-L4**.

Every reported level may be one off, and nothing in the output shows it. This is
the single most important open issue in the pipeline — a level error is worse
than a missed finding.

### 14c. ⚠ gpt-5.6-sol changed its frame-numbering base between runs

Captions number axial frames **1..30** (`frame 29 of 30`; the DICOM index inside
the caption is separately `slice #28`, 0-based). Stage 2's map this run reads
`T11-T12: axial frames 0-3 … L5-S1: 26-29` — the 0-based slice index, not the
caption frame number. Earlier runs used `1-4 … 27-30`. The **grouping is
identical and exactly matches all 7 slabs both times**; only the base moved. A
reader tracing "frames 20-25" back to the images lands one frame early.

### 14d. Where this leaves the combination

Gemini's screening list is clean, well-formed, and well-distributed across
levels — 13 candidates spanning four levels including the osseous and posterior-
element categories the split exists to surface. Stage 2 culled 7 of them with
specific, checkable reasons. That part is working as designed.

The level map is the problem, and it is a *geometry* problem the models should
not be solving by eye at all: the slab boundaries are already computable exactly
from the z-positions (`tools/analysis/oneoff/eagle_eye_axial_slabs_2026_08_26.py`
derives all 6 without a model). Handing both stages the slab structure would
remove Gemini's 2 boundary errors outright and reduce the remaining question to a
single anatomical anchor — which slab is L5-S1 — instead of seven independent
guesses that two models answer differently.

### 14e. Fix — pipeline 3.2.0, the slab grouping is measured and handed over

Owner's call: help the model rather than replace it. The boundaries stop being a
visual judgement; only the level names remain one.

**`llm_package._axial_slabs(captures)`** groups the axial frames from the
`axial_context.z_lps` already in every capture: a boundary is a z-gap wider than
`1.5 x` the median step. On the live study that separates cleanly — 4.3-5.3 mm
inside a slab against 9.5-41.6 mm between — and reproduces all seven slabs.

It refuses rather than guesses:

* fewer than 4 frames, any capture missing its z → `[]`
* a uniformly spaced stack (no gaps above threshold) → `[]`, because one group
  is not a structure and "1 slab" would read as "the whole study is one level"
* the **sagittal** sweep parks its axial pane, so every capture carries the same
  z and it correctly finds nothing there

When there is a structure, `_slab_lines` puts it in the package header — the
same header both stages receive. Verified on the real session with
`tools/analysis/oneoff/eagle_eye_header_peek.py`:

```
  AXIAL SLAB STRUCTURE (measured from the DICOM slice positions):
    7 slabs, by frame number as used in the captions below:
    1-4 | 5-8 | 9-12 | 13-16 | 17-20 | 21-26 | 27-30
    These boundaries are MEASURED, not estimated. Use them as given and
    do not re-derive them by eye. … Assigning the LEVEL NAMES
    is still yours; the grouping is not.
```

Prompt changes, in the SHARED preamble so the two stages cannot diverge:
use the block as given, do not re-derive it, assign names only, and — for §14c —
*"Report frame numbers using the caption numbering… Never renumber from zero and
never use the DICOM slice index in a level map."*

Stage 2 additionally gained **THE LEVEL IS PART OF THE FINDING**: build your map
first, check each candidate against it, and mark any level you move as REFINED
with the change stated (`"L3-L4 (first pass called this L4-L5): …"`). Silently
keeping pass 1's label under pass 2's map is the exact failure in §14b.

Versions: screening **1.2.0**, verification **2.2.0**, pipeline **3.2.0** (the
shared preamble changed, so both fingerprints move: `a92800e1…` / `bcaf619e…` /
pipeline `c6ec6c14…`).

Guards — 8 new, including the live z-positions verbatim rather than a synthetic
stack, because what makes this hard is that the smallest real between-slab jump
is only ~1.9× the typical step:
`test_the_slab_boundaries_are_MEASURED_not_read_off_the_screenshots`,
`test_a_uniformly_spaced_stack_claims_NO_structure`,
`test_the_PARKED_sagittal_sweep_yields_no_slabs`,
`test_a_capture_missing_its_z_disables_the_block_entirely`,
`test_the_slab_block_reaches_the_package_header`,
`test_BOTH_stages_are_told_to_use_the_measured_grouping`,
`test_stage_two_must_FLAG_a_level_it_moves`.
The session fixture was made slabbed — a uniform one exercised only the "no
structure" path and the block would never have appeared in anything built from
it. `ai_imaging` + `echomind` **2805 passed**, mirrors 456/456.

**Still open:** which slab is L5-S1. Geometry cannot answer that and neither
model should be trusted to, having disagreed. The next run will show whether a
fixed grouping is enough to make the two agree on names.

---

## 15. Session `20260826T211657Z` — the level maps agree

First run on pipeline **3.2.0**, same study, `gemini-3.1-pro-preview -> gpt-5.6-sol`,
41 images, 131,832 tokens, 2 min 5 s.

### 15a. The disagreement is gone

Both stages printed the **same** map, and it is the measured geometry exactly:

```
T11-T12: 1-4   T12-L1: 5-8   L1-L2: 9-12   L2-L3: 13-16
L3-L4: 17-20   L4-L5: 21-26  L5-S1: 27-30
```

* All 7 slabs, all 6 boundaries, **1-based** — §14c's numbering drift is gone too.
* Gemini, which produced `L1-L2 … L5-S1` over 26 frames in §13e and
  `T12-L1 … Sacrum` in §14b, now matches. Handing it the grouping settled the
  labels as well: with the boundaries fixed, both models independently anchor the
  21-26 slab at **L4-L5**.

That is agreement, not proof — but the two models converging from opposite
starting answers is the strongest evidence available short of a reader.

### 15b. Health

```
stage1  gemini-3.1-pro-preview   parsed=True  truncated=False  8848/12000  headroom 1.36x
stage2  gpt-5.6-sol              parsed=True  truncated=False  3364/12000  headroom 3.57x
```

**20 candidates in, 20 verified out**; 7 CONFIRMED, 1 REFINED, 12 REJECTED, no
`ADDED`, no degradation. Gemini raised 20 rather than 13 and reached further into
the under-reported categories — facet joint effusion, foraminal narrowing, nerve
root contact, Modic change, disc height loss — which is exactly what pass 1 is
for. Pass 2 rejected 12 of them with specific reasons.

### 15c. ⚠ The ceiling was already too close again

8848 tokens against 12000 is **1.36x**. The 12000 was sized against a 4743-token
run; once the slab block stopped Gemini spending output on boundary guesses it
spent it on findings instead, and the margin quietly evaporated. Same failure
mode as §13c, one revision later.

Both stages raised to **24,000** (~2.7x the largest answer measured). The guard's
`largest_observed` constant went 4122 → **8848** with a note in its docstring
that a stale constant makes the guard pass while the real headroom disappears —
that is the only way this check keeps working.

### 15d. Cost

131,832 tokens: 119,620 in @ $2.50/M + 12,212 out @ $15/M ≈ **$0.48/study**, up
from ~$0.30. Gemini is the verbose half (8848 of the 12,212 output tokens). The
ceiling itself costs nothing — only what is used is billed.

### 15e. ⚠ Stenosis severity is still not stable

Same patient, same frames, four runs:

| run | pipeline | L4-L5 canal |
| --- | --- | --- |
| `…191537Z` | 3.0.0, gpt/gpt | **severe** |
| `…202150Z` | 3.1.0, degraded | mild |
| `…205136Z` | 3.1.0, gemini/gpt | moderate |
| `…211657Z` | 3.2.0, gemini/gpt | **mild** |

The findings themselves are now stable — desiccation, bulge, facet, flavum at
L4-L5 plus L5-S1 disc disease, run after run. The **grading** is not, and it
swings across the whole scale. It is also the part a clinician acts on. Nothing
in the prompt currently defines what mild / moderate / severe mean for canal
calibre, recess height or foraminal fat, so each run re-invents the scale.
That is the next thing worth fixing, and unlike the level map it cannot be
computed — it needs the owner's own criteria.

## 16. First accuracy-improvement slice — pipeline 3.3.0 (2026-08-27)

The owner approved the staged implementation rather than a one-shot rewrite.
The first guarded slice changes grading semantics and sampling provenance only;
capture layout, evidence selection, candidate routing, and report rendering are
unchanged so the effect remains attributable.

### 16a. One domain catalog, consumed by both readers

`modules/ai_imaging/eagle_eye_lumbar/grading.py` is now the single immutable,
versioned authority for:

* `lee_central_canal` — axial T2, grades 0–3 from anterior CSF obliteration and
  cauda-equina rootlet separation;
* `lee_neural_foramen` — sagittal T1, grades 0–3 from perineural fat loss and
  nerve-root morphology;
* `bartynski_lateral_recess` — axial T2, grades 0–3 from narrowing/contact,
  deviation, and compression.

The catalog explicitly forbids deriving a grade from measurements alone. When
the primary sequence or defining morphology is not visible, grading fields stay
null, verification uses `INDETERMINATE`, and the limitation is rendered under
the final report's `NOT ASSESSABLE` section. Both prompts render the same
catalog. Their dispositions remain intentionally different: screening is
inclusive; verification is conservative.

Screening candidates now carry `grade_system` and ordinal `grade` for the three
stenosis targets. Verification must return the same fields for an assessable
stenosis decision. Non-stenosis findings use null for both fields.

### 16b. Sampling belongs to the stage, not the shared transport

`AnalysisStage` now records `temperature` in the prompt/request provenance and
the real dispatcher forwards it to both EchoMind backends:

* Gemini 3.1 Pro Preview screening: `1.0`;
* GPT-5.6-sol verification: `0.2`.

This removes the accidental shared `0.2` policy that was optimized for neither
provider as a pair. It does not assert that the GapGPT upstream honors every
provider-native media option; that remains a separate capability-probe phase.

Versions: screening **1.3.0**, verification **2.3.0**, pipeline **3.3.0**.

### 16c. Guard evidence

Five new guards failed before implementation: missing grading module, missing
rubric in both prompts, missing sampling metadata, missing request provenance,
and missing transport forwarding. After the implementation:

```text
tests/code/ai_imaging/test_eagle_eye_llm_analysis.py  73 passed
tests/code/ai_imaging                               499 passed, 8 xfailed
```

The next isolated slice is evidence bundles: diagnostic crops and adjacent
slices as primary inputs, with localizer context separated from the diagnostic
image rather than painted over it.

## 17. Patient-free GapGPT capability probe (2026-08-27)

The capability question was tested through the production provider bridge, not
against OpenAI directly. The adapter reuses `GAPGPT_API_URL`,
`echomind_http.post`, `company_entitlement_error()` and
`Manage.get_center_and_gapgpt_key()`. It contains no endpoint override, separate
credential, capture-session reader or DICOM input.

The pure contract is
`modules/ai_imaging/eagle_eye_lumbar/gapgpt_capability.py`; the opt-in live
adapter is
`tools/analysis/oneoff/eagle_eye_gapgpt_capability_probe.py`. Every image is a
metadata-free PNG tile generated in memory. The safe latest-result artifact is
`generated-files/gapgpt/eagle_eye_capability.json` and declares its data class
as `synthetic_non_patient`.

### 17a. Measured matrix

Five small requests were sent sequentially to each current pipeline model:

| Capability | Gemini 3.1 Pro Preview | GPT-5.6 Sol |
| --- | --- | --- |
| Chat Completions text | passed | passed |
| One synthetic image with `detail=high` | passed | passed |
| Three synthetic images, request order preserved | passed | passed |
| Chat Completions strict JSON schema | **failed semantically** | passed |
| GapGPT `/v1/responses` text request | passed | passed |

The Gemini strict-schema request returned HTTP 200 but the content was an empty
JSON object rather than the required `{status, count}` object. That is not a
transport failure; it is evidence that this GapGPT route cannot currently be
trusted to enforce the supplied schema. GPT-5.6 Sol returned the exact strict
object.

GapGPT reports canonical served names with provider namespaces
(`google/<model>` and `openai/<model>`). These are the requested models, not
substitutions. The evaluator normalizes that namespace but continues to flag a
genuinely different suffix.

### 17b. What this proves, and what it does not

This proves that both configured routes accept the current stage temperatures,
inline PNG vision payloads, `detail=high`, multiple images in order, and the
Responses endpoint. It does **not** prove that `detail=high` is honored as a
higher-resolution decode rather than merely accepted, and it does not establish
diagnostic accuracy. That requires a paired low/high or whole-pane/crop
experiment on the same de-identified evidence set.

The production pipeline therefore stays on Chat Completions for 3.3.0. A later
verification-only slice may use strict Structured Outputs for GPT, but only
after the mixed JSON-plus-report response is redesigned as one schema and the
human-readable report is rendered deterministically. The Gemini screening pass
must keep tolerant parsing plus explicit semantic validation; sending the
current strict schema to it would create false confidence.

### 17c. Verification

```text
tests/code/ai_imaging/test_eagle_eye_gapgpt_capability.py  5 passed
tests/code/ai_imaging                                      504 passed, 8 xfailed
GapGPT/EchoMind cross-boundary selection                    94 passed
plugin mirror parity                                       456 / 456
```

All five capability guards failed before the contract and adapter existed. A
sixth behavior, provider-namespace normalization, failed during hostile review
before the evaluator fix and is pinned inside the semantic-evaluation guard.

## 18. Focused evidence bundle V1 (2026-08-28)

The first evidence-selection experiment is implemented as a reversible A/B
layer, not as a replacement for the source capture. The capture manifest is now
version **1.2.0** and records the normalized rectangle of every actual VTK image
viewport plus the source PNG dimensions. Geometry is measured from the Qt
widgets at capture time. It is never reconstructed later by splitting a screen
into thirds, because the sidebar, group-box chrome, display scaling and panel
width are variable.

At this historical V1 phase, the default was:

```text
AIPACS_EAGLE_EYE_EVIDENCE_MODE=layout
```

This path returns the original package object and performs no additional image
I/O. Reproducing the opt-in experiment in the current runtime additionally
requires the engineering rollback gate:

```text
AIPACS_EAGLE_EYE_ALLOW_LEGACY_EVIDENCE=1
AIPACS_EAGLE_EYE_EVIDENCE_MODE=focused-v1
```

For each source frame, `focused-v1` creates one deterministic evidence sheet:

* the panes whose reference lines were hidden for evaluation occupy 78% of the
  usable canvas when a localizer is present;
* every localizer pane remains visible in a context column, including its
  reference line;
* UI/sidebar chrome outside the measured VTK viewports is absent;
* the output is bounded to 2048 x 1280 pixels;
* image count, pass order, frame order and source captions are preserved;
* previous/next source-frame indices are stated explicitly in each caption;
* every stored request records `evidence_mode` and `source_file` provenance.

> **Live status:** `focused-v1` is implemented but is **not approved for
> promotion**. Its first full 41-frame run exceeded the GapGPT read-time budget
> because the fixed canvas increased the aggregate pixel workload. The default
> must remain `layout` until the correction in §18e is implemented and retested.

The derivative is materialized under `.evidence/focused-v1` only after
`run_analysis` enters the existing EchoMind `ApiWorker`, before the existing
GapGPT dispatch. No crop, resize or composition runs on the GUI thread. Source
captures are never overwritten. A legacy session without measured viewport
bounds is refused in focused mode rather than processed using guessed crops;
it remains fully usable in the default layout mode.

### 18a. Why one sheet per source frame

Sending one diagnostic crop plus two localizers as three separate images would
roughly triple a 30-frame request and change both cost and ordering pressure at
the same time as pixel allocation. The standardized sheet changes the fraction
of useful pixels while holding image count constant, so a paired result is
attributable. Consecutive sheets are the adjacent-slice evidence; no slice is
dropped or sampled in V1.

### 18b. Evaluation protocol

Do not enable this globally from a single case. Use the same de-identified,
reader-labelled case set for both arms:

1. Create two evaluator-local copies of the same de-identified source session,
   because a normal re-analysis overwrites that session's prior result files.
   Run one copy as `layout` and one as `focused-v1`, with identical models,
   prompt fingerprint and stage temperatures.
2. Run each arm at least twice because screening is intentionally sampled at
   temperature 1.0.
3. Score per-finding sensitivity, false positives, level/laterality accuracy,
   Lee/Bartynski grade agreement, `INDETERMINATE` rate and inter-run stability.
4. Record prompt/input/output tokens, request duration and failure rate.
5. Promote only if focused evidence improves the predeclared primary metric
   without worsening false positives, level assignment or verification loss.

No provider connection changed: both arms continue through the existing
EchoMind-to-GapGPT bridge and the current Gemini-screening / GPT-verification
model routing.

### 18c. Guard evidence

Ten focused-evidence guards failed before implementation (the module did not
exist). They now cover: default no-op behavior, measured-bound crop composition,
retention of diagnostic and localizer pixels, chrome exclusion, count/order and
adjacency invariants, strict legacy-session refusal, the environment switch,
clipped normalized geometry, real controller geometry measurement, manifest
persistence of bounds and source dimensions, and worker-side preparation before
GapGPT dispatch.

The final domain gate is **514 passed, 8 pre-existing xfailed**. EchoMind
pipeline scoping is **16 passed**, plugin mirror parity is **456/456**, and
Python compilation of the Eagle Eye lumbar package succeeds. A synthetic
31-frame composition run completed in **2.381 seconds** and produced exactly 31
outputs; this is a bounded implementation check, not a clinical-workstation
latency claim. Visual QA caught undersized pane labels before delivery; the
labels were enlarged and the evidence guard was rerun afterward.

### 18d. First live result — focused timeout, layout control success

The first real 41-frame `focused-v1` run validated the implementation boundary
but failed the transport-performance gate:

```text
package built                         41 source images
focused derivatives prepared         41 images in 18.75 s
stage 1 model                         gemini-3.1-pro-preview
GapGPT route                          /v1/chat/completions through EchoMind
outcome                               read timeout after 180.991 s
stage 2                               not started
```

This was not an authentication, routing, model-selection, capture, manifest or
evidence-generation failure. The focused package was generated successfully,
the correct Gemini screening model was selected, and GapGPT accepted the HTTP
request. The client then waited for a response until the existing 180-second
read timeout expired.

The reason the synthetic benchmark did not predict this is measurable in the
real package:

| Input arm | Frames | Dimensions per frame | Aggregate pixels | PNG bytes |
| --- | ---: | ---: | ---: | ---: |
| source `layout` | 41 | 1692 x 678 | 47.03 MP | 20.49 MB |
| `focused-v1` | 41 | 2048 x 1280 | 107.48 MP | 30.34 MB |

Although image count stayed constant, the fixed focused canvas increased the
aggregate pixel workload to **2.285x** and encoded bytes to **1.481x**. The
focused compositor also upscaled source pane pixels rather than only
reallocating the existing pixel budget. That makes the first implementation an
invalid controlled A/B input: it changes both diagnostic-pixel allocation and
total model workload.

A subsequent `layout` control used a newly captured session and completed:

```text
stage 1  gemini-3.1-pro-preview   HTTP 200   67.237 s   parsed=True   truncated=False
stage 2  gpt-5.6-sol              HTTP 200   69.048 s   parsed=True   truncated=False
total analysis time                          about 137 s
pipeline                                     3.3.0
images                                       41
```

Pipeline health was clean:

* screening prompt 1.3.0 returned 16 candidates, 7,993 / 24,000 completion
  tokens;
* verification prompt 2.3.0 returned 16 decisions — 4 `CONFIRMED`, 2 `REFINED`
  and 10 `REJECTED` — with 4,370 / 24,000 completion tokens;
* all 16 screening candidates received a verification decision;
* three graded screening findings retained graded verification decisions;
* total usage was 133,087 tokens: 120,724 prompt and 12,363 completion;
* the final report artifact was written successfully;
* there was no Eagle Eye/GapGPT warning or error after dispatch began, no retry,
  and no native-fault event during the analysis.

The control was a **new capture session**, not a retry of the failed focused
session. It therefore confirms that the current model routing, prompts,
structured parsing, report storage and GapGPT path are healthy in `layout`
mode. It does **not** establish a diagnostic-accuracy difference between the
two evidence modes; that comparison still requires two evaluator-local copies
of the same de-identified source session as specified in §18b. No patient
identity, DICOM identifiers, captured images or report text are reproduced in
this document.

### 18e. Required correction before the next focused live run

Do not solve the timeout by raising the HTTP read limit first. That would hide
the uncontrolled workload increase and still leave the experiment
non-attributable. The next evidence revision must:

1. derive its canvas budget from the source frame rather than always emitting
   2048 x 1280;
2. never upscale a viewport crop above its source pixel dimensions;
3. keep aggregate derived pixels at or below the source package pixel count;
4. record source and derived pixel/byte totals in safe request provenance and
   logs, without patient or DICOM identifiers;
5. fail before GapGPT dispatch if the configured evidence mode exceeds its
   declared pixel budget;
6. add regression guards for the pixel-budget invariant and worker-only image
   processing;
7. rerun `layout` and the corrected focused arm from two copies of the same
   de-identified source session before any accuracy conclusion or default-mode
   change.

At that phase, `AIPACS_EAGLE_EYE_EVIDENCE_MODE=layout` was the only
live-approved setting. Section 38 supersedes this historical policy.

---

## 19. Parallel clinical-context branch — pipeline 4.0.0 (2026-08-28)

### 19a. Execution graph

The pipeline now has three versioned stages but only two sequential latency
windows when a supported document exists:

```text
                         ┌─ stage 1: Gemini MRI screening ─────┐
capture package ─────────┤                                     ├─ join
study attachment folder ─└─ stage 2: Gemini context extraction ┘
                                                               ↓
                         stage 3: GPT-5.6 Sol MRI verification/fusion
                                                               ↓
                                                        final report
```

Stages 1 and 2 run concurrently in a two-worker executor inside the existing
Eagle Eye analysis worker. Stage 3 does not start until the MRI candidate list
and either a clinical prior or an explicit unavailable-context marker exist.
No network, credential, endpoint, retry, or API-key path was added: every live
request still uses the shared EchoMind-to-GapGPT bridge.

### 19b. Input boundary

`clinical_context.py` reads only root-level image attachments for the current
study. It accepts PNG, JPEG, and WebP, validates image content, rejects empty or
oversized files, caps the request at eight images, excludes known generated
viewport-capture prefixes, and rejects unsafe study identifiers. It does not
copy attachments into the Eagle Eye session.

The request artifact and model captions contain ordinal position and MIME type,
not local paths or filenames. Gemini must classify document versus non-document
content from the pixels because phone-photo filenames are not reliable. The
current implementation does not render PDF or Word attachments; photographed
or scanned pages must be stored as supported images.

### 19c. Extraction contract

The Gemini context reader extracts only explicitly documented material:

* age, unit, and confidence;
* traumatic, degenerative, discogenic, neoplastic, postoperative,
  inflammatory/infectious, congenital, nonspecific-pain, other, or unknown
  clinical scenarios;
* presenting history, symptoms, and duration;
* prior imaging availability and lumbar-relevant prior-report summaries;
* prior spine surgery, documented red flags, contradictions, and uncertainty.

Document text is untrusted data, not instructions. The final fusion adapter
allowlists the expected schema, bounds list and text lengths, rejects unknown
fields, and passes no identity fields into the verification context.

### 19d. Diagnostic boundary and degradation

Clinical context is a prior that may direct attention or alter plausibility. It
is never evidence of a current MRI abnormality. The GPT verification prompt is
explicitly prohibited from confirming, adding, grading, or localizing a finding
solely from the history sheet or a prior report, and must re-check historical
claims against the MRI.

If no supported image exists, the pipeline persists a deterministic
`no_clinical_document` stage without spending a Gemini request. If context
extraction fails, MRI screening and GPT verification continue; the final stage
receives an unavailable-context marker and the result record retains a
`clinical_context_failed` warning. MRI-screening or final-verification failure
still fails the analysis normally. An unparseable context response is preserved
for evaluation but its raw text is not forwarded into the final prompt; GPT
continues without that prior.

### 19e. Stored artifacts and verification result

The stage numbering in pipeline 4.0.0 is:

```text
llm_stage1_*   Gemini MRI screening
llm_stage2_*   Gemini clinical-context extraction or no-document marker
llm_stage3_*   GPT-5.6 Sol verification and final-report source
llm_result.*   final pathology-only report and aggregate provenance
```

The four new regression guards failed before this feature existed and now pin
the versioned Gemini stage/fusion contract, bounded redacted document packaging,
true parallel execution before verification, and graceful missing/failed-
context behavior. Current verification:

```text
tests/code/ai_imaging/test_eagle_eye_llm_analysis.py   77 passed
tests/code/ai_imaging                                  522 passed, 8 xfailed
```

This proves execution, routing, persistence, fallbacks, and prompt boundaries;
it does not prove improved diagnostic accuracy. Promotion requires a labelled,
de-identified paired evaluation comparing pipeline 3.3.0 with 4.0.0, including
finding sensitivity, false positives, level/laterality accuracy, severity-grade
agreement, report-changing context errors, latency, tokens, and failure rate.
No live clinical-context result is claimed in this revision.

---

## 20. Multi-source context expansion — pipeline 4.1.0 (2026-08-28)

Pipeline 4.1.0 supersedes the attachment-only input boundary in section 19
without adding a new provider, endpoint, credential path, or UI-owned feature
logic. Gemini context collection now starts inside the parallel executor after
the Gemini MRI-screening future is submitted. Reception, PACS, DICOM decoding,
and derived-image work therefore remain off the Qt GUI thread and overlap the
screening request rather than delaying it.

### 20a. Source contract

`clinical_context.py` builds one bounded, provenance-preserving package from:

1. The canonical reception REST authority
   (`modules.network.reception_api_config.fetch_patient_record`) for age,
   referring specialty, requested services, and clinical history.
2. Existing reception-history, patient-status, report-normalization, and local
   report authorities for a maximum of six previous reports. Only report date,
   modality, and bounded clinical text enter the request.
3. A sanitized series-catalogue snapshot captured from
   `patient_widget.lst_thumbnails_data`. `series_context.py` retains series
   number, modality, description, protocol, body part, inferred plane, slice
   count, contrast evidence, and document/imaging kind; it never retains series
   UIDs, local paths, or identity.
4. Clinical document DICOM series number `100000`. Pixel data is decoded in the
   context worker and written only as a derived PNG under
   `<session>/.context/documents`; source DICOM files are never modified.
5. At most four evenly sampled images from the already prepared MRI capture
   package. These are labelled `MRI OVERVIEW` and may establish only broad
   degenerative, postoperative, or atypical context—not a focal diagnosis.

Root-level PNG/JPEG/WebP clinical attachments remain supported. All image
sources share the existing EchoMind/GapGPT multimodal transport. Model-request
provenance contains source kind, ordinal position, and MIME type, never local
paths, filenames, patient names, referrer names, or patient IDs.

### 20b. Inventory scope and absence claims

The catalogue has an explicit trust scope:

- `pacs_series_catalog` means the thumbnail catalogue represented the complete
  study known to PACS. Only this scope may support a claim that a material
  sequence, region, or postcontrast acquisition is absent.
- `locally_available_series_only` means only selected/local series were known.
  It may describe what is present but can never prove what is absent.
- `unknown` carries neither presence nor absence authority beyond explicit
  facts.

Both the Gemini prompt and the deterministic GPT-fusion normalizer enforce this
rule. The normalizer overwrites Gemini's echoed scope and source status with the
trusted values from the locally built context package. If Gemini returns
missing-input or protocol-limitation claims from a limited inventory, the
normalizer removes them and resets
`contrast_documented_without_postcontrast_series` to `unknown`. The final GPT
may add `TECHNIQUE / PROTOCOL LIMITATIONS` only for a material limitation
established from `pacs_series_catalog`; otherwise that section is omitted.

### 20c. Structured fusion contract

The context JSON now adds source status, `referrer_specialty`, `study_scope`,
`protocol_context`, and `global_imaging_context` to the original age, history,
scenario, prior imaging, prior surgery, red-flag, contradiction, and uncertainty
fields. It distinguishes routine noncontrast, contrast-enhanced, mixed, and
unknown protocols; lumbar, total-spine, brain, mixed, and unknown scope; and
ordered contrast from an actually present postcontrast series.

The final GPT still receives the complete MRI package and remains the only
report-producing stage. Clinical facts and prior reports are priors, series
inventory is protocol metadata, and MRI overview is explicitly incomplete.
None can independently establish, grade, or localize a current MRI finding.

### 20d. Verification result and remaining clinical work

The new guards failed before implementation and cover source-aware prompt
contracts, reception/catalog/document/overview packaging, exact DICOM document
rendering, real collection-vs-screening concurrency, full-catalogue snapshot,
and suppression of absence claims from partial inventories. Current result:

```text
tests/code/ai_imaging/test_eagle_eye_llm_analysis.py                83 passed
tests/code/ai_imaging/test_eagle_eye_lumbar_pipeline.py            139 passed
both focused files                                                  222 passed
tests/code/ai_imaging                                               529 passed, 8 xfailed
EchoMind scoping + patient-free GapGPT capability                    21 passed
plugin mirror verification                                          456 matched
```

This proves implementation boundaries, concurrency, safety degradation,
storage, and transport reuse. It does not prove improved diagnostic accuracy.
Before clinical promotion, run a labelled paired evaluation that stratifies
routine, contrast, postoperative, tumor/infection, trauma, total-spine/mixed,
and missing-sequence cases and measures finding sensitivity, false positives,
level/laterality accuracy, grading agreement, context-induced report changes,
protocol-limitation precision, latency, tokens, and branch failure rate. No live
multi-source context result is claimed in this revision.

---

## 21. Original-tab context handoff repair (2026-08-29)

The first live pipeline 4.1.0 run completed all three model stages through the
shared GapGPT bridge, but its context provenance exposed two application-side
gaps: `patient_id` was empty, and the inventory scope was
`locally_available_series_only` with three selected series even though the
local study contained six series. Reception history and previous-report lookup
were therefore unavailable, and the protocol inventory could not support
absence claims.

The cause was the UI boundary, not the context collector or either model. The
original patient tab owns the reception identity, while preflight has the
header-probed catalogue for every readable series in the selected study. Eagle
Eye opens a separate reduced patient widget containing only the selected
diagnostic series, and that widget is constructed without a patient ID. The
existing one-shot, TTL-bound `session_request` handoff carried only the
validated study/protocol/series mapping, so the required context was lost
before capture built `session.json`.

The handoff now adds one bounded `study_context` snapshot while the original
tab is still available:

- patient ID resolved from the canonical widget field or supported metadata
  aliases;
- a sanitized maximum-512-entry series inventory, choosing the more complete
  of the original thumbnail catalogue and the header-probed preflight
  candidates, and retaining descriptive protocol fields only;
- no patient name, series UID, local path, filename, or image bytes.

The workflow coordinator passes that snapshot to the feature-owned capture
context builder. A missing local patient ID is filled from the handoff. A full
handoff catalogue replaces a reduced local catalogue only when it is at least
as complete; it cannot overwrite a larger full local catalogue. The receiving
side re-sanitizes the inventory before persistence. The oversized imaging tab
remains unchanged and no new constructor parameter, network route, credential
path, model request, or prompt version was added.

Three regression guards failed before the repair and pass afterward. They
protect original-tab identity/catalogue snapshotting, reduced-widget context
recovery, and end-to-end use of the existing one-shot handoff. Verification:

```text
focused lumbar pipeline + UI boundary                              146 passed
tests/code/ai_imaging                                      546 passed, 8 xfailed
plugin mirror verification                                          456 matched
```

### 21a. Default build inclusion

The repair is unconditional in the source runtime and the mirrored Viewer
payload; no environment variable or feature flag enables the handoff. The
PyInstaller specification already collects every non-optional `modules`
submodule. Both Nuitka paths now explicitly force-include
`modules.ai_imaging`: `AIPacs_nuitka.spec.py` covers the monolithic builder,
and the `full_core` profile in `build_nuitka_release.py` covers the staged
builder. This closes the lazy-import gap without moving AI Imaging into an
optional package.

`test_eagle_eye_default_build_inclusion.py` pins all three build paths, the
unconditional runtime call, and exact canonical-to-Viewer-payload parity. Its
Nuitka inclusion guard failed before the build configuration change and all
three tests now pass, including generated staged-command verification.
Module/plugin readiness, cross-build coherence, Python syntax,
and all 456 plugin mirrors pass. A full builder run is deliberately not claimed:
the broader builder baseline still has six unrelated pre-existing Nuitka ARM64
parity failures, one stale staged-config failure for
`patient_table_sort.json`, and the source-freshness gate timed out during its
network `git fetch`. A new x64/default build must regenerate the stale stage
before live testing.

This proves the application data path and packaging parity. A new human-run
default-build session is still required for live confirmation. The expected
provenance is a non-empty reception lookup key and
`study_series_inventory_scope = pacs_series_catalog`, with the complete study
series count rather than only the three selected capture series.

---

## 22. Disc-hydration specificity and product-only model metadata (2026-08-30)

A user-supplied screen capture and the locally stored, privacy-filtered session
artifacts showed a completed pipeline 4.1.0 run with four screening candidates
for disc desiccation. Verification rejected two but confirmed two, so the issue
was not transport, parsing, truncation, or a screening-only false positive. All
three stages parsed successfully with substantial output headroom, and the
matching log entries contained no error or warning. The defect was clinical
prompt calibration at both image-reading stages.

Pipeline 4.2.0 adds one shared false-positive control to screening 1.4.0 and
verification 2.6.0. The primary hydration decision is now the central nucleus
pulposus on mid-sagittal T2, reproduced on adjacent sagittal slices. Convincing
central T2 hyperintensity relative to the surrounding annulus is explicit
negative evidence against desiccation. A normally dark peripheral annulus,
mild inhomogeneity, or a horizontal low-signal band cannot establish
desiccation while central hydration and nucleus-annulus distinction remain
preserved. Desiccation requires convincing loss or reduction of central nuclear
T2 signal, usually with reduced nucleus-annulus distinction. Axial T2 may
support contour and neural-effect assessment but cannot establish hydration
loss by itself.

This is qualitative screenshot interpretation, not a numeric measurement. It
does not convert the earlier conceptual percentage calibration into a signal-
intensity calculation. The rule follows the established T2-weighted
Pfirrmann-style distinction between hyperintense discs with preserved
nucleus-annulus distinction and discs with intermediate or low nuclear signal
and reduced distinction.

Clinical basis: Pfirrmann et al., *Spine* 2001,
doi:10.1097/00007632-200109010-00011; Tertti et al., *Spine* 1991,
doi:10.1097/00007632-199106000-00006.

The result panel now displays `model AI-PACS AI Lumbar Analysis` instead of the
provider/model chain. Session ID, prompt/pipeline version, pass count, image
count, completion time, and total tokens remain visible. Raw per-stage model
provenance remains stored in `llm_result.json` for audit, evaluation, routing,
and cost analysis; only the end-user presentation is provider-neutral.

Two behavioral regression guards failed on the prior implementation and pass
after the change. Automated verification does not establish improved clinical
accuracy. Promotion still requires a radiologist-reviewed paired set that
includes hydrated discs, early inhomogeneous-but-hyperintense discs, true
desiccation, postoperative artifact, and mismatched/limited sagittal coverage.

```text
changed-boundary files                                             90 passed
tests/code/ai_imaging                                  559 passed, 8 xfailed
default-build inclusion guard                                      3 passed
```

---

## 23. Pathology-focus differential adjudication — pipeline 4.3.0 (2026-08-30)

A radiologist-reviewed live pipeline 4.2.0 result localized a genuine abnormal
disc focus but reported only a broad-based bulge where the dominant morphology
was an extrusion. Privacy-filtered artifacts showed that screening produced 17
candidates and correctly raised the affected disc focus, but emitted no
protrusion, extrusion, sequestration, or migration candidate anywhere. The
verifier produced 19 decisions and successfully added two unrelated findings,
proving that its `ADDED` path worked, but it inherited the bulge label and never
performed the required herniation differential. Every stage parsed without
truncation and the matching log contained no error or warning. The defect was
the role and diagnostic contract, not capture, transport, parsing, or token
budget.

### 23a. Preserved separation of responsibilities

Screening 1.5.0 remains sensitivity-oriented. Its primary obligation is to
preserve an abnormal focus for verification. A candidate label is explicitly a
working hypothesis; when displaced disc material is visible but its exact
morphology is uncertain, screening now emits
`disc_displacement_indeterminate` instead of dropping the focus or forcing a
false precision.

Verification 2.7.0 consumes three inputs with separate authorities:

1. Screening candidates define the attention foci and working labels.
2. Clinical/examination context ranks and expands the differential but cannot
   establish a current MRI finding.
3. The complete MRI package alone decides presence, diagnosis, morphology,
   level, side, zone, and severity.

High specificity now applies to the final diagnosis, not to whether a positive
focus is re-examined. For every focus the verifier must decide presence,
diagnostic family, plausible alternatives, characterization, and anatomical
consequences. A wrong screening label is not equivalent to absent pathology:
if the focus remains abnormal but another diagnosis is better supported, the
disposition is `RECLASSIFIED`, never `REJECTED`. Normal anatomy, artifact,
partial volume, and non-pathological variants remain explicit differential
outcomes and may correctly produce `REJECTED`.

### 23b. Disc morphology and output contract

Both image readers now share a disc-displacement morphology contract based on
the NASS/ASSR/ASNR Lumbar Disc Nomenclature 2.0. It distinguishes generalized
bulge from localized herniation, protrusion from extrusion by the displaced
component-to-base relationship in at least one plane, sequestration by absent
continuity, and migration by cranial or caudal displacement. Sagittal T2 may be
decisive for base-to-dome relationship, continuity, and migration; axial T2 may
be decisive for circumference, zone, side, and neural consequence. An axial
slab that misses the maximal dome cannot veto a convincing sagittal extrusion.

The verification audit now requests `focus_present`, `screening_diagnosis`,
`alternatives_considered`, `final_diagnosis`, `status`, and
`change_direction`. Positive statuses are `CONFIRMED`, `RECLASSIFIED`,
`REFINED`, `UPGRADED`, `DOWNGRADED`, and `ADDED`. `REJECTED` requires no
supported alternative pathology at the focus; `INDETERMINATE` records an
unresolvable package limitation. A mandatory final safety sweep independently
rechecks major report-changing findings, including extrusion, sequestration,
migration, high-grade neural compromise, fracture, destructive marrow lesion,
epidural disease, infection, and conus/cauda-equina abnormality.

Clinical basis: Fardon et al., *The Spine Journal* 2014,
doi:10.1016/j.spinee.2014.04.022.

Four new regression guards failed before implementation and pass afterward.
Two older guards were deliberately re-pinned rather than removed: the old
contract required axial confirmation of every disc morphology and described
verification primarily as a deletion filter; both now guard multi-plane
morphology adjudication and focus-preserving reclassification. Automated prompt
tests prove the contract and execution wiring, not diagnostic accuracy. The
radiologist must re-run the known extrusion case and a balanced labelled set
before clinical promotion.

```text
tests/code/ai_imaging/test_eagle_eye_llm_analysis.py                 88 passed
tests/code/ai_imaging                                  563 passed, 8 xfailed
default-build inclusion guard                                      3 passed
```

---

## 24. Paired sagittal context and focal attention — pipeline 4.4.0 (2026-08-30)

The prior context branch sampled the first and last frames of both sagittal and
axial sweeps when given the usual four-image budget. It therefore did not
guarantee a near-midline sagittal view, despite receiving measured sagittal
offsets, and its prompt explicitly restricted MRI input to global context. The
structured contract and allowlist had no field for a regional or level-specific
context hypothesis, so any such model output would be discarded before final
verification.

Pipeline 4.4.0 changes only the context service and the prompt/data contracts:

- the bounded context image selector accepts only captured sagittal frames that
  contain both geometrically matched `sagittal_t2` and `sagittal_t1` panes;
- it ranks frames by absolute measured midline offset, selects the nearest
  frames, and then restores acquisition order; when geometry is unavailable it
  chooses the central contiguous window rather than the sweep endpoints;
- the context prompt uses paired T2/T1 for general examination context and for
  conspicuous regional or level-specific attention hypotheses, while forbidding
  axial side/zone, stenosis grade, neural compression, or a final diagnosis;
- `context_attention_foci` carries bounded scope, anatomy, context type,
  hypothesis, confidence, allowlisted evidence sources, and explicit full-MRI
  verification questions;
- the final verifier audits every regional or level-specific context focus even
  when screening did not raise it, and may confirm an omitted pathology as
  `ADDED`, reject a normal focus, or mark it `INDETERMINATE`;
- an invalid or absent study UID still permits session-local paired sagittal
  context and series inventory, while all external reception, attachment, and
  DICOM-document lookups remain disabled for that unsafe identity.

Context remains an untrusted prior. The complete MRI package remains the only
authority for diagnosis, location, morphology, side, zone, severity, and neural
consequence. No UI, capture, model routing, GapGPT transport, database, or
packaged mirror changed.

Four behavioral guards failed before the fix and pass afterward. They cover
paired near-midline evidence selection, the general/focal prompt contract,
bounded normalization and forwarding, and safe session-local degradation when
the study UID cannot authorize external lookup. Automated tests validate the
evidence and prompt wiring, not clinical accuracy. Live validation requires a
radiologist-reviewed source-build rerun on the known cases.

```text
tests/code/ai_imaging/test_eagle_eye_llm_analysis.py                 92 passed
tests/code/ai_imaging                                  567 passed, 8 xfailed
default-build inclusion guard                                      3 passed
combined changed-boundary gate                                    570 passed
```

---

## 25. Patient laterality and same-lesion multiplanar fusion — pipeline 4.5.0 (2026-08-30)

A privacy-filtered review of the latest complete source-build run found no
transport, parse, or output-ceiling failure. All three stages completed. The
parallel context branch raised an extrusion hypothesis, but the final verifier
downgraded the visible disc focus to protrusion and assigned the display side
as the patient side. The axial screenshot itself carried an `R` marker on the
screen-left edge and an `L` marker on the screen-right edge, so that mapping was
clinically inverted. The sagittal pane also demonstrated the base-to-dome
relationship more directly than the sampled axial section.

Pipeline 4.5.0 changes the two image-reader prompt contracts only:

- patient laterality must come from visible `R/L` orientation markers or
  trusted DICOM patient-coordinate metadata, never from screen-left or
  screen-right;
- standard radiological display mapping is stated explicitly: screen-left
  under `R` is patient-right and screen-right under `L` is patient-left;
- absent, cropped, unreadable, or conflicting orientation evidence produces an
  indeterminate side instead of a guess;
- sagittal and axial findings must first be correlated to the same level and
  the same displaced component before their evidence is combined;
- morphology is the union of defining features across reliable planes, not a
  majority vote between independently assigned plane labels;
- a sagittal dome wider than its neck or base may establish extrusion even when
  an axial slice intersects only a narrower, protrusion-like portion; axial
  remains authoritative for patient-side, zone, and neural consequence.

Screening remains sensitivity-oriented and verification remains the
high-specificity adjudicator. The execution graph, context service, UI,
GapGPT/OpenAI transport, model routing, capture, database, and build packaging
did not change.

Two prompt-contract guards failed before the fix and pass afterward. Automated
tests prove the decision contract and wiring, not diagnostic accuracy. The next
required step is a radiologist-reviewed source-build rerun on the known case.

```text
tests/code/ai_imaging/test_eagle_eye_llm_analysis.py                 94 passed
tests/code/ai_imaging                                  569 passed, 8 xfailed
default-build inclusion guard                                      3 passed
combined changed-boundary gate                                    572 passed
```

---

## 26. Agent-directed Focused Evidence V2 — implementation plan (2026-08-30)

### 26a. Decision

The next evidence revision will not let Gemini manipulate the live viewer or
request arbitrary screenshots. Gemini will produce a bounded, structured
attention plan. A local Eagle Eye orchestrator will validate that plan, resolve
it against immutable DICOM identity and geometry, and ask a worker-side DICOM
evidence service to build the smallest useful multi-planar package for GPT-5.6
Sol.

This design deliberately keeps the current model-call topology for the first
implementation:

```text
captured study snapshot
        |
        +-- Gemini screening -------- candidates + supporting frame references
        |
        +-- Gemini context ---------- global context + attention foci
                    (parallel)
        |
        v
local FocusPlanner + EvidenceRequestValidator
        |
        v
worker-side DICOM EvidenceComposer
        |
        v
one GPT-5.6 Sol verification request
        |
        v
deterministic result normalization and storage
```

The first version therefore remains three model calls: two Gemini calls in
parallel and one GPT verification call. Native tool calling, per-level GPT
calls, and a model-driven repair loop are deferred until the compact evidence
package has been measured. This avoids adding latency and failure modes before
proving that the evidence representation itself improves accuracy.

### 26b. Why the live viewer is not the evidence engine

The current workstation agent can read viewport context, change series, scroll
slices, capture the viewport, and place measurements. `change_layout` is still
explicitly unimplemented. More importantly, these actions mutate clinical UI
state and several execute on the Qt event path. The MCP bridge currently returns
tool results as text JSON and is not an image transport.

The focused verifier path must therefore not depend on a sequence such as
`change_layout -> change_series -> scroll -> wait -> screen grab`. That sequence
would be vulnerable to stale applies, partially rendered OpenGL surfaces,
reference-line repaint races, user interaction, and black or blank captures.

The primary focused path will render directly from the locally stored DICOM
series. The existing Legion Consult evidence implementation already proves the
required primitives in this repository: headless SimpleITK volume loading,
patient-LPS ROI projection, adjacent-slice selection, stable series windowing,
overview contact sheets, focused context/zoom derivatives, and an immutable
manifest. Its reusable geometry and rendering code should be extracted into a
shared `modules.ai_imaging.evidence_core` package without changing Legion
Consult behavior.

MCP remains useful as an optional adapter over the same service. If exposed in
a later phase, it should offer high-level asynchronous operations such as
`build_eagle_eye_focus_pack` and `get_eagle_eye_focus_pack_status`; it must not
carry pixel bytes through CommandBus or run decode/composition on the GUI
thread.

### 26c. Contracts and trust boundaries

Gemini output is untrusted model input. The application, not the model, owns
study identity, series identity, slice order, patient laterality, geometry,
resource budgets, and the final list of executable operations.

The additive `EvidenceRequestV1` contract should contain:

- a stable `focus_id` and references to screening/context candidate IDs;
- semantic anatomy (`level`, `region`, and pathology family), with `unknown`
  permitted instead of guessing;
- supporting captured evidence IDs and an optional normalized 0..1 attention
  rectangle tied to a specific captured pane;
- the clinical question to adjudicate, such as bulge versus protrusion versus
  extrusion, right recess compromise, foraminal stenosis, marrow lesion, or
  postoperative change;
- requested evidence templates selected from an allowlist, never arbitrary
  commands or file paths;
- priority and model confidence, used only for ordering and never as image
  evidence.

The validator will reject unknown IDs, cross-study references, invalid ranges,
unavailable series, excessive focus counts, excessive image/pixel/byte budgets,
and any request that cannot be resolved without guessing. A rejected model plan
degrades to a deterministic plan derived from the normalized screening
candidates; it does not fail the whole study.

Absolute patient-LPS coordinates must be computed locally from the captured
frame geometry. Gemini may identify an approximate region in a named evidence
frame, but it must not invent DICOM coordinates. Laterality is resolved from
DICOM patient coordinates and trusted orientation metadata; screen-left and
screen-right are never accepted as patient side.

### 26d. Compact evidence representation

Focused V2 will package adjacent slices into composite evidence sheets instead
of uploading one crop per disc or one image per slice.

The default package contains:

1. **Sagittal overview sheet.** Five ordered near-midline sagittal T2 slices in
   one sheet, cropped vertically to include the clinically useful lumbar span
   and posterior elements. A matched central T1 tile is included when marrow,
   postoperative, infection, or tumor context requires it.
2. **Axial stack overview.** The complete selected axial stack represented in
   acquisition order as one or, when necessary, two bounded contact sheets.
   This preserves a global safety sweep without sending every axial frame as a
   separate image.
3. **One level-fusion sheet per positive focus.** The upper row contains five
   adjacent axial slices centered on the best-supported slice. The lower row
   contains three adjacent sagittal views cropped around the same level. The
   sheet keeps morphology, continuity, zone, laterality, and neural consequence
   in one visual object.
4. **Optional template-specific sheet.** Added only when the diagnostic question
   requires evidence not represented above: paired parasagittal T1/T2 foraminal
   views, matched T1/T2 marrow views, or available postcontrast/STIR evidence.

Candidates at the same level share one fusion sheet. Adjacent positive levels
may share a two-row level sheet when native tile resolution remains adequate.
For a typical single-level disc herniation case, the target is three to four
images total rather than 30-40 screenshots: sagittal overview, axial overview,
one level-fusion sheet, and at most one optional sheet.

Initial guardrail targets, to be tuned only through measurement, are:

- no more than 8 model-facing images;
- no more than 4 focus levels;
- no more than 12 megapixels across all derived images;
- no more than 12 MiB before base64 encoding;
- no derived tile larger than its source pixels;
- total derived pixels at or below the selected source evidence pixel count.

PNG remains the baseline because small MRI morphology and labels are sensitive
to lossy artifacts. Every sheet receives a short stable evidence ID, ordered
slice indices, plane/weighting labels, source-series identity in the private
local manifest, patient-space provenance, crop bounds, and source/derived
pixel and byte totals. No patient text is burned into the derivative.

### 26e. Non-blocking execution and black-frame prevention

The orchestrator will be a service-level state machine rather than logic added
to the imaging tab:

```text
SNAPSHOTTED
  -> SCREENING_CONTEXT_RUNNING
  -> FOCUS_PLAN_VALIDATED
  -> EVIDENCE_BUILDING
  -> VERIFICATION_RUNNING
  -> AGGREGATING
  -> COMPLETE | DEGRADED | FAILED | CANCELLED
```

Only a small immutable snapshot of study/series/frame identity is taken from
the UI. DICOM indexing, decoding, windowing, crop projection, sheet composition,
PNG encoding, base64 encoding, network calls, and result parsing all remain off
the Qt GUI thread. Jobs are single-flight per study, use a bounded worker queue,
carry cancellation and correlation IDs, and ignore late results after the user
has cancelled or changed study.

Black/blank prevention is primarily architectural: focused evidence does not
screen-grab a newly scrolled or newly laid-out OpenGL viewport. Each DICOM
derivative is validated before dispatch for successful decode, finite pixels,
non-empty projected bounds, plausible percentile spread, non-uniform content,
expected dimensions, and a source-to-output provenance match. A dark MRI image
is not rejected merely for being dark; only uniform/placeholder/failed output is
rejected.

If focused DICOM evidence cannot be built, the run falls back to the already
stored, immutable layout capture package. It must not attempt a live emergency
layout change or fresh viewer capture. The existing source images remain
untouched, so the fallback cannot corrupt or replace the captured session.

### 26f. Orchestrator placement

The implementation should introduce a thin Eagle Eye domain orchestrator and a
shared evidence core, while leaving the UI as a signal/status coordinator:

```text
modules/ai_imaging/evidence_core/
    contracts.py
    dicom_volume.py
    roi_projection.py
    rendering.py
    quality.py
    budget.py

modules/ai_imaging/eagle_eye_lumbar/
    evidence_request.py
    focus_planner.py
    focus_evidence.py
    pipeline_orchestrator.py
    verification_dispatcher.py
    result_aggregator.py
```

The first extraction from Legion Consult must be behavior-preserving and keep
its existing tests green. Eagle Eye then consumes the shared pure functions;
it must not copy them into a second implementation. The existing GapGPT
transport authority remains the only outbound route.

### 26g. Phased implementation

**Phase 0 — contracts and capability gates (approximately 0.5-1 day).** Add the
versioned request/manifest schemas, stable evidence IDs, strict validator,
resource budgets, state machine, and synthetic fixtures. Extend the existing
patient-free GapGPT probe to test image detail modes and function/tool support,
but do not switch the production path based only on provider documentation.

**Phase 1 — shared evidence core and compact composer (approximately 1-2
days).** Extract the proven pure DICOM geometry/rendering primitives from Legion
Consult. Implement sagittal overview, complete axial overview, level-fusion,
quality validation, and budget enforcement. All work runs in a bounded worker.

**Phase 2 — pipeline integration (approximately 1 day).** Merge and deduplicate
screening candidates and context attention foci, build one compact verification
package, and send it through the current single GPT-5.6 Sol request. Add a
`focused-v2` A/B mode while retaining `layout` as the live default and fallback.

**Phase 3 — measured clinical validation (approximately 1 engineering day plus
radiologist review).** Compare identical de-identified session copies using
`layout` and `focused-v2`. Include the known L5-S1 extrusion case, normal discs,
true desiccation, foraminal stenosis, multilevel disease, postoperative metal,
marrow lesions, and limited protocols. Measure diagnostic performance,
stability, latency, failures, image count, pixels, bytes, and tokens.

**Phase 4 — optional bounded agent loop.** Only if Phase 3 demonstrates an
evidence gap, allow GPT to return one `needs_more_evidence` request from an
allowlisted schema. The composer may supply one additional sheet and GPT may be
called once more. Per-level concurrent verification and MCP-exposed job tools
belong here, not in the initial implementation.

A testable focused package should be achievable in roughly two to three
engineering days because the DICOM evidence primitives already exist. A guarded
candidate for default-on promotion is more realistically three to five days,
excluding the time required for a clinically representative reader-labelled
evaluation.

### 26h. Acceptance and rollback gates

Focused V2 is not promotable until all of the following are true:

- no DICOM decode, image composition, base64 conversion, or network request runs
  on the GUI thread;
- changing the live viewer layout, series, or slice is not required;
- every dispatched image passes quality and provenance validation;
- budget overflow fails before network dispatch and falls back to `layout`;
- single-level cases meet the three-to-four-image target and all cases remain
  within the declared image/pixel/byte caps;
- the known extrusion remains localized to the correct level and patient side,
  and multiplanar morphology is not downgraded because one slice misses the
  maximal dome;
- the global overview still detects major findings omitted by screening;
- cancellation, study change, partial DICOM availability, decode failure,
  missing geometry, and GapGPT timeout have deterministic terminal states;
- logs contain only correlation IDs, counts, timings, budgets, stage outcomes,
  and safe error classes, never patient identifiers, images, prompts, reports,
  UIDs, paths, or API keys;
- source captures and the current `layout` path remain byte-for-byte available
  as the rollback path;
- focused regression suites, neighboring Eagle Eye/Legion tests, agent-gateway
  guards, direct pytest exit codes, and required package-mirror checks pass.

Promotion should remain a runtime A/B decision until the paired clinical cohort
shows improved herniation morphology/level/laterality performance without a
material sensitivity loss, false-positive increase, timeout increase, or
inter-run stability regression.

## 27. Focused V2 implementation result (2026-08-30)

At this historical V2 phase, Phases 0-2 of Section 26 were implemented behind
the strict `AIPACS_EAGLE_EYE_EVIDENCE_MODE=focused-v2` A/B switch and `layout`
was the default and automatic fallback. Section 38 supersedes that selection
policy. No UI controller, model credential, API endpoint, or GapGPT transport
was added or changed.

### 27a. Implemented execution path

The production order is now:

```text
immutable captured layout package
  -> Gemini screening ───────────────┐
  -> Gemini context (parallel) ──────┤
                                      v
                          bounded local focus plan
                                      |
                    worker-side DICOM composition
                                      |
                         GPT verification through
                         the existing EchoMind/GapGPT route
```

Screening contract 1.7.0 adds bounded `key_frames` arrays. These are attention
anchors only. `evidence_request.py` accepts no commands, paths, coordinates, or
arbitrary tools from model output; it allowlists lumbar levels, normalizes and
deduplicates findings/context, sanitizes positive frame numbers, prioritizes at
most four levels, and falls back from an invalid key frame to the explicit
screening level map.

At capture time, each selected role's local series path and Series Instance UID
are written to `series_sources.local.json`. This file is separate from
`session.json`, captions, manifests, and the `sent` request document. Existing
sessions without this optional file remain valid; focused-v2 degrades to layout.

`focus_evidence.py` loads sagittal T2 and axial T2 directly with the shared
headless DICOM core. Sagittal T1 is optional. The representative captured axial
frame contributes its stored Image Position Patient. The composer transforms
that LPS point into the raw axial volume instead of assuming that viewer slice
indices and SimpleITK ordering are identical, then projects the same point into
the sagittal volume.

The model-facing package contains:

1. one sagittal sheet with five contiguous near-midline T2 slices and optional
   T1 context;
2. one ordered axial overview with up to 25 samples spanning the whole stack;
3. one level-fusion sheet per resolved focus, containing five adjacent axial T2
   source slices and three geometry-projected sagittal T2 slices, plus one
   sagittal T1 tile when available.

Candidates at the same level share one sheet. A typical single-level case is
therefore three images. Every caption tells the verifier to read the five axial
slices as one short sequence, and verification prompt 3.0.0 states that sheet
labels remain hypotheses rather than diagnoses.

### 27b. Safety, quality, and budgets

The shared `modules/ai_imaging/evidence_core` package now owns immutable volume
geometry, LPS transforms, DICOM loading, robust volume windowing, no-upscale
tile fitting, ROI projection, derived-image quality inspection, and evidence
budgets. Legion Consult imports these primitives rather than retaining a second
copy.

Focused-v2 rejects missing required provenance, absent Series Instance UID,
unavailable local series, UID-specific DICOM indexing failure, non-finite or
effectively uniform source renders, undecodable output, invalid focus geometry,
and request-budget overflow. The initial hard caps are 8 images, 4 focus levels,
12 megapixels, and 12 MiB before base64. Patient-orientation edge labels are
computed from DICOM direction cosines; no screen-side assumption is used.
Legitimately dark MRI is accepted when it retains meaningful intensity
variation. No VTK/Qt/OpenGL object is created,
no viewer is scrolled or relaid out, and no fresh screen grab is attempted.

All composition occurs inside the existing `run_analysis` worker path after the
parallel branches return. Any focused-v2 failure records only a safe error code
and switches GPT verification back to the stored layout package. Screening is
never delayed by DICOM composition and never receives the reduced package.

### 27c. Verification result

Direct pytest exit codes are green:

- focused-v2 plus changed Eagle Eye/Legion boundaries: **262 passed**;
- complete `tests/code/ai_imaging`: **576 passed, 8 pre-existing xfailed**.

The seven focused-v2 regression guards cover plan validation, frame sanitization,
patient-LPS alignment, DICOM-derived patient orientation, adjacent-slice
composition, privacy separation, quality and budget gates, stage-specific
dispatch, and layout fallback. No live model
request or release build was run during implementation.

### 27d. Deliberately deferred work

This implementation does not promote focused-v2 to default, add an MCP tool,
allow arbitrary agentic viewer control, add a second GPT repair call, or create
separate per-level model calls. The axial overview is a bounded ordered sample,
not a claim that every source slice is shown at diagnostic size. Optional STIR,
postcontrast, parasagittal foraminal, and marrow-specific templates remain Phase
3 evidence-gap decisions. The next required step is the paired radiologist
cohort from Section 26g, including the known L5-S1 extrusion case, before any
default-on decision.

---

## 28. Focused V2 capture-frame authority — pipeline 4.6.1 (2026-08-30)

The first focused-v2 live run completed successfully but printed a reversed
level map. The immutable workstation capture and Gemini screening were correct:
axial capture frames were ordered superior-to-inferior and the lower lumbar
attention anchors used the high-numbered frames. The compact verifier package,
however, decoded the source series as one SimpleITK volume. GDCM ordered the raw
files inferior-to-superior, and the composer wrote those raw source ordinals on
the derived tiles. GPT therefore interpreted source slice 1 as capture frame 1
and reversed the final level map.

That series also contained six independently angled acquisition slabs. Loading
all slabs into one regular 3D affine produced a non-uniform-sampling warning and
made a single volume transform an unsafe authority for cross-plane projection.
The captured DICOM position matched the corresponding source Image Position
Patient to sub-millimetre precision, so the reliable seam is a one-to-one
per-slice geometry match rather than an inferred global volume index.

Pipeline 4.6.1 makes the following corrections:

- each axial DICOM object is decoded as an independent scalar slice with its own
  Image Position Patient, Image Orientation Patient, Pixel Spacing, inversion,
  and bounded source ordinal;
- every original axial capture frame is matched one-to-one to the nearest source
  slice within a strict 2 mm tolerance; a missing, duplicate, or mismatched
  identity fails closed to the existing immutable-layout fallback;
- axial overview and level-fusion tiles are emitted in original
  superior-to-inferior capture order and labeled only as `AX frame n/N`;
- raw source ordinals remain local manifest provenance and are explicitly
  forbidden as report or level-map frame numbers;
- neighboring focus slices stop at an orientation or measured-gap slab boundary,
  preventing a five-slice ribbon from crossing into another prescribed level;
- the cross-plane point is the physical center of the selected axial image,
  derived from per-slice orientation and pixel spacing, rather than the DICOM
  top-left origin or a synthetic multi-slab affine;
- verification prompt 3.0.1 names capture frames as the sole level-map numbering
  authority and distinguishes them from composite-sheet indexes.

Four new synthetic guards reproduce reversed source order, independently angled
slab boundaries, physical image-center projection, and the verifier numbering
contract. A read-only probe against the affected local session mapped capture
frame 1 to raw ordinal 25 and capture frame 25 to raw ordinal 1 while preserving
the model-facing 1-to-25 capture order; all tested sagittal projections remained
inside the selected sagittal volume. No patient data or local paths are stored
in tests or documentation. A new source-build model run and radiologist review
remain required before this correction is live-verified.

Automated verification completed with direct exit code 0: the focused-v2 file
passed **11 tests**; the Eagle Eye/Legion changed-boundary set passed **134
tests**; complete `tests/code/ai_imaging` passed **580 tests** with **8
pre-existing xfails**; default-build inclusion passed **3 tests**; and all
**458 plugin mirror pairs** matched.

## 29. Focused V2/V3 axial-window coverage preflight (2026-08-31)

The focused-axial selector previously clipped a radius-two window at a slab
boundary without filling its unused slots. An edge-adjacent anchor could
therefore produce four slices even when five were available in the same slab.
The correction in `focus_evidence.py::_same_slab_neighbors` backfills from the
opposite side without crossing the existing gap/orientation boundary. It does
not move the screening anchor or its sagittal projection point. This applies
to both focused render profiles; shared sagittal selection remains unchanged.

Manifest schema **1.3.0** adds per-focus `axial_window` provenance under policy
`same-slab-backfill-v1`: anchor, available slab depth and frame bounds,
requested/expected/selected counts, and whether clipping required adjustment.
Prompts, model routing through GapGPT, benchmark scoring, reference negatives,
and the default evidence mode are unchanged. No additional GUI-thread work,
network round trip, runtime module, dependency, or feature flag was introduced.

The new guards demonstrated **20 failures and 21 passes before the fix**.
Afterward, focused V2/V3 passed **63 tests**; complete AI Imaging passed **643
tests with 8 existing xfails**; default-build inclusion passed **3 tests**;
and **458 plugin mirror pairs** matched, all with exit code 0. The source is
included in the core AI Imaging package and has no separate payload mirror.

A private replay of saved screening/context and original local image evidence
restored two four-slice focuses to five slices, retained a true four-slice slab,
and kept five total model-facing images. Encoded bytes increased from
4,364,552 to 4,546,578 within the unchanged budget. The original 57 session
files, both overview PNGs, and all sagittal anchors/sampling remained unchanged.
No model call was made. This is deterministic coverage verification, not a
claim that the clinical interpretation has improved.

See the [V3 research plan, section 16](EAGLE_EYE_FOCUSED_V3_MORPHOLOGY_RESEARCH_PLAN_2026-08-31.md#16-phased-implementation-plan)
for the experiment record and pending Phase 0/E1/E2 work; reliability tracking
is **OPT-55**. Live source-build/radiologist verification remains pending.
The historical layout bypass remains reproducible only through the engineering
rollback gate described in Section 38.

## 30. V3 bilateral sagittal experiment and scoped root scoring (2026-08-31)

Two bounded changes are implemented. Neither changes the model selection,
GapGPT transport, clinical system prompts, reference annotations, or default
evidence mode. The ordinary `focused-v3` path remains the comparison baseline.

### Evidence interpretation corrected before implementation

The reviewed saved run already contained five sagittal overview slices, while
each dedicated focus contained three. DICOM InstanceNumber and decoded-volume
index ran in opposite directions. The approximately 9.6 mm right-sided plane
was present in the overview, but not the dedicated focus. The approximately
14.4 mm plane was outside both selections. Thus a claim of complete absence
of the 9.6 mm plane from the diagnostic request is incorrect. The testable
hypothesis is insufficient focused coverage or emphasis, not a proven cause
of the model's morphology decision. A model's written rationale cannot prove
which tile drove its answer.

### Opt-in additive coverage

With the Section 38 engineering rollback gate enabled,
`AIPACS_EAGLE_EYE_EVIDENCE_MODE=focused-v3-parasagittal` builds the complete,
unchanged V3 package first, then appends one bounded sagittal T2 sheet per
resolved focus while the existing image/pixel/byte limits permit. Screening
and clinical-context inputs are unchanged. Evidence headers/captions explain
the extra sheets; clinical system prompts are unchanged.

- The selection is bilateral in patient LPS coordinates, independent of the
  screening side. Sampling targets are -15, -10, -5, 0, 5, 10, and 15 mm from
  the unchanged geometric reference. These are engineering targets, not
  anatomical zone definitions or a claim to have localized the lesion.
- The reference is the axial image-center projection, not verified anatomical
  midline. Seven targets yield at most seven distinct source slices. Missing
  targets and incomplete bilateral coverage are recorded; coarse spacing can
  merge targets, and samples need not be contiguous.
- Tiles retain the V3 100 x 100 mm crop and 384 x 384 no-upscale tile. They are
  ordered patient-right to patient-left, with actual offsets and explicit
  source-volume numbering. Existing axial capture numbering is untouched.
- Manifest **1.4.0** in the new mode adds `parasagittal_supplements`, policy
  `bilateral-lps-supplement-v1`, source slices, offsets, crop/sampling, and
  `included`, `unavailable`, or `budget_excluded` dispositions. Ordinary V3
  stays at manifest 1.3.0. Optional rendering/quality failure retains the base
  package; failure of base composition retains the existing layout fallback.
- Supplements follow existing focus priority within the unchanged caps:
  8 images, 4 focuses, 12,000,000 pixels, and 12,582,912 encoded bytes. This
  does not guarantee a supplement for every focus. No focus means overview
  evidence only, not proof of a normal study.

The implementation remains in the headless lumbar service, called by the
existing analysis worker. No scrolling, viewer mutation, GUI-thread image
work, new agent loop, extra provider request, or Slicer launch is introduced.

### Root-effect scorer correction

Scorer **1.1.0** attaches negation to contact/deviation/compression assertions,
not to an entire nearby root mention. Synthetic example: "Contact, but no
deviation, of the traversing right L4 root" retains contact and separately
records absent deviation. Against a compression reference this is `under`,
not `miss`. The selected root carries additive `effect_assertions` provenance;
individual score JSON includes `scorer_version`.

This is a narrow repair, not completion of Phase 0. The prose parser is still
bounded; multiple-root representation, independent identity/effect scoring,
morphology categories and coexisting components, failed-attempt denominators,
and clinician adjudication of reference negatives remain open. Do not use the
old aggregate or this single replay to claim diagnostic improvement.

### Verification and measured offline result

- Before implementation: root-negation guards **6 failed, 7 passed**; initial
  parasagittal guards **11 failed**. Self-review also reproduced a missing
  partial-coverage warning, then corrected it with a regression test.
- Afterward: scorer **25 passed**, parasagittal **18 passed**, complete AI
  Imaging **675 passed, 8 existing xfailed**, default-build inclusion **3
  passed**. All **458 plugin mirror pairs** matched; process exit codes were 0.
- Offline replay used saved stage outputs and local DICOM with outbound
  connections disabled. All **57 original files** and all **4 base image
  bytes/captions** remained unchanged. Two supplements brought the package
  from **4 to 6 images**, **6,731,520 to 9,361,152 pixels**, and **3,978,659 to
  4,897,937 bytes**. Both sampled seven slices spanning approximately 14.4 mm
  on each side of the geometric reference; no coverage/budget warning arose.
  One local render took **2.551 s** for the experimental package, versus
  **2.852 s** for baseline; cache/order effects prevent a speed comparison.
- Rescoring the saved report correctly retained root contact and returned
  `under` against compression. No report or private reference was overwritten.
- No model call, application launch, build, deployment, or clinical validation
  occurred. The new mode is ready for a clinician-supervised source trial,
  not promoted as more accurate.

Packaging checklist: the modified files belong to the existing core AI Imaging
tree; there is no corresponding plugin payload mirror. No runtime module,
installable feature, dependency, or config family was added. The new value of
an existing environment switch needs no runtime catalog, installer component,
profile writer, or config-family migration. Core inclusion and mirror checks
passed without producing a build.

For a source trial, close the existing instance first and launch once from CMD:

```cmd
set AIPACS_EAGLE_EYE_ALLOW_LEGACY_EVIDENCE=1
set AIPACS_EAGLE_EYE_EVIDENCE_MODE=focused-v3-parasagittal
.\.venv\Scripts\python.exe main.py
```

Set the same variable to `focused-v3` to compare the unchanged base renderer,
or `layout` to bypass focused composition while the gate remains enabled. These
commands are for historical engineering reproduction, not routine app launch.
Setting terminal variables does not alter installed/build defaults. The next research gates remain full
Phase 0 repair and controlled E1/E2 comparisons with frozen evidence.

## 31. Level-assignment integrity, padding headroom, and scorer 1.2.0 (2026-08-31)

This follow-up addresses a completed run whose two readers assigned different
anatomical names to the same acquisition slabs. Both maps were monotonic and
had the same slab count; the names nevertheless differed by one level. A
monotonicity check alone cannot detect that error. The observed diagnosis change
is not an evidence-only causal experiment: screening and clinical-context
outputs also differed between runs, and the later screening already contained
the changed morphology and neural-compromise candidates. Preserve that
confound when interpreting model rationales or comparing scores.

### Report integrity, not automatic anatomical correction

`evidence_request.audit_level_maps` compares explicit stage-one/stage-three
capture-frame assignments, including lower-thoracic rows. It checks malformed,
missing, duplicate, reversed, overlapping, incomplete, and non-monotonic
assignments; disagreements in names/ranges; and agreement with available
geometry-derived slab boundaries from `llm_package`. Bounded-input truncation
and unparsed additional assignment rows cannot produce a clean result.

- Stable identifiers such as `axial:5-6` identify a capture range within the
  current session. They are not globally unique or verified vertebral labels.
- The audit records `consistent`, `conflict`, or `unavailable`, the two names
  per slab, issue codes, and an optional uniform ordinal level offset. Equal
  maps are only consistent: `anatomical_numbering_verified` remains false.
  Acquisition geometry can establish boundaries, not vertebral numbering.
- The lumbar three-stage worker persists `level_assignment_audit`,
  `integrity_guard_version=1.0.0`, `verification_evidence_audit`, warnings,
  `review_required`, and `report_status`. Missing/conflicting assignments or
  evidence-coverage warnings prefix the displayed/copied report with
  `REVIEW REQUIRED - NOT A VERIFIED FINAL REPORT`. The result-panel heading is
  amber and the session label says review is required.
- Execution can still be `complete`: all calls returned. That does not mean
  the report is clinically verified. The raw stage-three response remains
  untouched; the guarded report retains its original prose under the warning.
  No diagnosis, root, side, or level is silently relabeled, and screening is
  not promoted to ground truth. Existing saved sessions are not rewritten.

The guard is active in the existing lumbar three-stage path without a new
feature flag. It detects these conflicts; it does not solve anatomical
numbering, lesion recognition, or laterality. Human source-image confirmation
is still required when an assignment is disputed.

### Padding-only headroom and explicit coverage

The opt-in `focused-v3-parasagittal` manifest is now **1.5.0**, with render policy
`compact-vertical-padding-v1`. Seven samples, source identities, LPS offsets,
crop boxes, windowing, and effective sampling are unchanged. Only surplus
vertical letterboxing is reduced when the original fitted anatomy permits it;
the width stays 384 pixels, and cell height stays large enough to preserve
the old sampling with caption margin. Large crops retain the old cell height.
Ordinary V3 image bytes and captions remain the baseline (manifest 1.3.0).

The existing 8-image, 4-focus, 12,000,000-pixel and 12,582,912-byte caps remain.
Baseline images are composed first and cannot be evicted by supplements.
Supplement failures/exclusions remain visible in the manifest and now also
reach the verification header, persisted result metadata, and review-required
report. Missing evidence must not be interpreted as normal anatomy. Base
composition failure retains the existing layout fallback and its warning.
Capacity advisories (`image_capacity_reached`, pixel/byte headroom below ten
percent) are recorded separately; they are not themselves evidence omissions.

This reduces pixel pressure, not the image-count ceiling. A fourth focus can
still mean fewer supplements fit. No claim is made that all future packages
fit, and no whole-supplement coverage is traded for an unannounced lower
resolution. Further packing or cap changes require a separate controlled test.

### Scoped benchmark corrections

Scorer **1.2.0** recognizes root-effect participles including `contacting`,
`abutting`, `compressing`, and `deviating`, retaining per-effect negation.
Consequence severity and grade are extracted from a structure-local clause,
not the first grade elsewhere in the level. A subarticular disc-location
phrase alone is not a recess consequence and cannot mask a later explicit
recess grade. Lower-thoracic map entries are retained.

Per-run scores now include a separate `level_assignment_audit` against saved
screening output. A uniform shift is diagnostic metadata, not permission to
move findings to other levels or award corrected-level credit. Strict named-
level claim outcomes remain unchanged by this audit. This is still not full
Phase 0: morphology-as-severity, generic herniation, coexisting components,
independent root identity/effect scoring, failed-run denominators, and
reference-negative adjudication remain open. Inspect extraction before using
an aggregate; neither an old score nor this patch proves clinical improvement.

### Verification record

- Initial changed-boundary guards: **22 failed, 43 passed** before the fix.
  Self-review additionally reproduced five malformed/truncated-map failures;
  private replay reproduced the subarticular-location masking problem, then
  two synthetic guards failed before its correction.
- Final focused files: **19 level-integrity, 26 parasagittal, 35 scorer tests**.
  Full AI Imaging plus default-build inclusion: **732 passed, 8 existing
  xfailed**, exit 0 (729 AI Imaging and 3 inclusion tests). No new quarantine.
  **462 plugin mirror pairs** matched; `git diff --check` passed for this scope.
- Network-disabled replay used saved outputs and local DICOM in a fresh private
  output folder. All **60 original files** retained their hashes. All **5 base
  images** were byte-identical and all **21 supplemental anatomical tile
  contents** were pixel-identical. Slice-selection and sampling records matched.
  The supplemented package rendered in **3.735 s** in one observation, not a
  speed benchmark. Visual inspection confirmed readable labels and retained
  anatomy; varied-aspect-ratio synthetic guards also verify exact pixel retention.
- Evidence remained **8 images**. Pixels changed from **11,990,784 to
  11,253,504**, leaving **746,496 pixels (6.22%)** of headroom. Each supplement
  changed from 1536 x 856 to 1536 x 696; cell height changed from 384 to 304.
  Encoded bytes changed only slightly: **5,890,397 to 5,881,762**. Empty PNG
  padding compresses well, so pixel savings must not be called upload savings.
  Image capacity remains full and both capacity advisories were recorded.
- The saved conflicting maps produced `conflict`, offset **-1**, and
  `review_required=true` without altering report prose. The scorer retained all
  six map rows and the separately stated severe recess grade/root compression.

All code remains in the headless lumbar services/scorer, with presentation only
in the small result panel. No GUI-thread decode/network work, viewer scrolling,
new request, Slicer integration, runtime module, dependency, or config family
was added. These existing core AI Imaging files have no plugin payload mirror;
core inclusion and repository mirror parity were checked without a build.
GapGPT routing, model choices, system prompts, reference data, and default
evidence mode are unchanged. No model call, app launch, build, deployment, or
clinical validation was performed. OPT-55 remains partial pending clinical
acceptance. Complete Phase 0 and frozen-stage E1/E2 before promotion.

## 32. Grading correction and fixed-input preparation (2026-08-31)

### Corrected contract, not demonstrated diagnostic improvement

Review of the current catalog and saved image-reader prompts confirmed a named
grading defect: catalog 1.0.0 called root deviation without compression
`bartynski_lateral_recess` grade 2. The original description instead includes
compressive root deformation with residual recess CSF; grade 3 includes severe
compression with recess CSF obliteration. Deviation alone is not the grade-2
criterion. See [Bartynski and Lin, 2003, Table 1 and Figure 2](https://pmc.ncbi.nlm.nih.gov/articles/PMC7973614/).

The separate normal/contact/deviation/compression observations refer to
[Pfirrmann et al., 2004, nerve-root compromise](https://pubmed.ncbi.nlm.nih.gov/14699183/),
not Pfirrmann disc degeneration. Root identity, side and effect remain distinct
observations. Do not convert these effects directly into recess grades or derive
either laterality or a clinical grade from a bright-CSF area split. The original
Bartynski surgical cohort excluded disc-protrusion root impingement; correcting
terminology is not validation of this AI pipeline on disc extrusions.

Implemented in the framework-free `grading.py` catalog, rendered into both
image-reading prompts:

| Contract | Previous | Current |
|---|---|---|
| Stenosis catalog | 1.0.0 | 2.0.0 |
| Separate root-observation contract | absent | 1.0.0 |
| Screening stage | 1.7.0 | 1.8.0 |
| Verification stage | 3.0.1 | 3.1.0 |
| Context stage | 2.1.0 | 2.1.0, unchanged |
| Pipeline | 4.6.1 | 4.7.0 |

Stenosis-only `grade_system`/`grade` fields and existing system IDs are retained;
root effects use the existing finding/reason text, not a second scale in the same
fields. Lee canal and foraminal definitions are unchanged. Stored stage prompt
text, fingerprints and versions distinguish old and new definitions. No historical
record or clinician reference is rewritten, and historical grades must not be
reinterpreted as catalog 2.0.0. This does not finish the independent root-attribute
benchmark schema repair.

### Fixed-input preparation that works offline

The benchmark CLI now provides `freeze` and `check-frozen`, implemented in
`tools/eagle_eye_bench/frozen_input.py`. They copy and hash exactly the saved
stage-three prompt/settings, sent context/header/captions, ordered image entries
and image bytes into a new local snapshot. No model backend is imported or called.
There is no reference-answer input and no copy of a final report. Safe path,
count, size, order, digest and incomplete-write guards prevent silently accepting
a changed package. The [benchmark README](../../tools/eagle_eye_bench/README.md)
contains CMD usage, limits and privacy constraints.

This is **snapshot preparation**, not verification-only model replay. The existing
`run` command still reruns screening, context, evidence construction and verification.
Freezing an old request intentionally keeps the old prompt: it must not silently
replace it with 4.7.0. A future comparison runner must record an explicit prompt
override while keeping the frozen upstream context, images and model settings
fixed. Provider preprocessing or behavior behind an alias is not frozen by local
hashes. Official [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
supports task-specific evaluation and expert review; its generic model guidance
does not establish clinical accuracy or GapGPT transport equivalence.

### Clinician landmark gate: specified, not automatically implemented

Patient orientation from DICOM and anatomical midline are different facts.
[DICOM Image Plane geometry](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html)
provides patient-coordinate mapping, not a validated anatomical centerline.
Conversely, absence of a numeric centerline does not prove that a visual model
used the acquisition center or cannot see anatomical landmarks. The proposed CSF
area comparison has not been independently reproduced from saved masks/thresholds
and is not a ground-truth replacement.

Before another laterality experiment, collect clinician review in a **separate
private annotation artifact** bound to the frozen snapshot ID:

1. Select the decisive axial image and its adjacent slices; preserve source-volume
   index versus capture-frame identity, tile/crop transform and displayed R/L.
2. Mark two distinct, clinician-confirmed points defining the local anatomical
   axis on each assessable slice, for example a posterior vertebral-body midpoint
   and an appropriate posterior midline landmark. One point alone does not define
   a line. Rotation, scoliosis or postoperative anatomy may require abstention.
3. Mark the lesion and the traversing root separately; retain root identity,
   patient side and effect as separately adjudicated observations. An axis is not
   itself a lesion/root label or proof of compression.
4. Record image hash, exact coordinate convention, both points, reviewer, review
   time and assessability. Derive LPS coordinates only using a verified source
   transform, never from a screenshot's guessed scale or a filename-sorted slice
   table. Reject stale hashes, wrong image bindings or unavailable transforms.
5. Resolve disagreements clinically without silently relabeling the reference.
   Keep unannotated originals. Do not use a patient-specific expected answer in
   a general prompt. Automatic midline estimation requires its own validation.

There is **no new landmark-entry UI, annotation validator or auto-relabeler** in
this patch. These clinical decisions cannot be fabricated by software. The
identity-bound snapshot is the implemented prerequisite for the next slice.

### Next controlled sequence

- Complete remaining Phase 0 scoring repairs and clinician adjudication of
  reference negatives; the existing negation/level-audit fixes remain intact.
- Add and validate the clinician annotation entry/check path and a GapGPT-only
  verification replay adapter consuming the frozen input. An annotated-evidence
  arm must remain distinct from an unannotated diagnostic-performance arm.
- Compare corrected grading and label-free handoff as explicitly separate
  conditions; keep model, settings, frozen upstream input and rendering fixed.
  Report detection, morphology, side, root identity/effect and recess grade
  separately, including failed runs. Do not promote on this single case.
- Then evaluate targeted sagittal T1 foraminal coverage and the unflagged-level
  safety review. Existing overview images and screening/context focus union must
  be preserved; do not claim they are currently absent. Equal T1/T2 offsets do
  not by themselves prove foraminal coverage. Recheck all three upload budgets.

### Verification and scope

- Six grading/version guards failed before correction; the affected prompt and
  grading files then passed **97 tests**.
- The initial **15 snapshot guards** failed before the feature existed. Self-review
  reproduced a canonical-JSON size expansion defect, fixed before output creation;
  final snapshot suite has **18 passing tests**, including link rejection and
  incomplete writes. Synthetic tests deny socket connections.
- Direct AI Imaging plus default-build inclusion gate: **753 passed, 8 existing
  xfailed**, exit 0; three existing SWIG deprecation warnings. **462 mirror pairs
  match**. No new quarantine or lint/full-repository pass is claimed.
- Offline freezing of the reviewed saved input produced six byte-preserved images
  with an independently rechecked snapshot digest. All **59 original artifacts**
  retained their hashes. Snapshot content and identity stay in ignored local data,
  not in this document. No new clinical result was generated.

The bug-fix/DICOM/Titan workflows drove fail-before guards, identity separation
and the clinical gate; OpenAI Docs informed keeping model/configuration changes
out of this correction. Runtime changes are two existing core AI Imaging files;
the new helper is benchmark tooling, not an installable module or feature flag.
No catalog/installer/config-family addition or plugin mirror sync is needed for
this scope. Build inclusion and mirror parity were verified without a build.
No UI-thread I/O, viewer/Slicer change, database access, image selection/crop,
default evidence-mode change, new dependency, key change, model call, app launch,
build or deployment was performed. GapGPT routing remains unchanged. OPT-55
remains partial: source correctness is tested, clinical benefit is not established.

## 33. Localization-only screening and independent diagnosis (2026-08-31)

### Requirement and implemented boundary

Gemini screening now answers **whether a visible anatomical focus is plausibly
abnormal and where it is**, not which disease, disc subtype or severity it has.
The parallel Gemini context branch remains unchanged. The diagnostic reader
receives the neutral attention map, independent clinical prior and MRI evidence;
it must decide normal/artifact versus pathology and classify supported pathology
from signal and morphology, including correlated planes and neighboring slices.

The previous boundary contradicted that division of labor in three places:
screening inherited the shared diagnostic morphology/hydration criteria and the
grading rubric, its output example required a diagnostic candidate and grade,
and the backend forwarded the entire parsed candidate (or raw prose after a
parse failure). The focus planner also accepted explicitly normal rows.

The implemented versions are pipeline **5.0.0**, screening **2.0.0**, diagnostic
verification **4.0.0**, and unchanged clinical context **2.1.0**. Diagnostic
grading catalog **2.0.0** and root observations **1.0.0** are unchanged and are
now supplied only to the diagnostic reader. Existing result artifacts are not
rewritten or relabeled.

### Screening contract

`screening_attention.py` defines a bounded, pure-Python normalization boundary:

- Anatomical structures include disc, endplate, bone marrow, vertebral body,
  posterior elements, facet joint, ligamentum flavum, canal, recess, foramen,
  root, conus/cauda equina, epidural/paraspinal tissue and alignment.
- Each row contains `assessment`, `structure`, tentative `level`, optional
  `vertebra`, patient `laterality`, detection `confidence` and `locations`.
- Each location names `session`, original capture `frame`, `pane` and optional
  `box_2d`. Separate T2/T1/axial locations in one row propose a same-focus
  association. The first listed frame is most informative; neighbors follow.
- The normalizer supplies a deterministic `attention_id` and trusted local
  `source_file`, validates frame/pane membership against the actual package,
  derives the existing planner's `key_frames`, and drops unrecognized fields.
  No first-stage diagnosis, grade, differential or diagnostic free text is
  forwarded. Legacy candidate labels can recover anatomy only, with a warning;
  their original text remains exclusively in the raw stage audit.
- Explicit normal rows are excluded from candidates and focus planning. A
  `normal_count` is audit metadata, not proof of a globally normal examination.
  Material `not_assessable` rows remain separate and require diagnostic review.
  Invalid or missing JSON becomes `unavailable`, never raw-label fallback or
  an implicitly normal examination. Invalid locations do not erase the focus.
- Limits are 64 rows and 15 locations per row. Invalid/truncated information is
  surfaced through bounded warning codes in the analysis result. The same
  normalized object is used for focus planning and the diagnostic request and
  is stored as `screening_attention` in the local result for comparison.

The diagnostic audit references `attention_id`; `screening_diagnosis` stays null
and `change_direction` is `none`. Presence, independent classification,
localization and severity are separate decisions. A supported abnormal focus
must not be discarded solely because its subtype is uncertain. Multiple
coexisting components may be retained. Every context focus and screening
assessment gap also requires resolution; the broad overview safety sweep stays.

### Coordinate and evidence limits

The box convention is `[ymin, xmin, ymax, xmax]`, normalized to 0..1000 over the
entire original screenshot, including the pane's offset. This is consistent
with the documented [Gemini image-localization format](https://ai.google.dev/gemini-api/docs/image-understanding),
not evidence that Gemini's medical localization is accurate. Boxes must be finite,
ordered and in range; parked reference panes and unknown frames are rejected.
The older focused-v1 repacked images have no inverse box transform in this
boundary: proposed boxes are discarded with a warning, while valid frame
attention is retained.

These are **model-proposed correspondences**, not geometry-verified anatomy,
midline landmarks, segmentation or measurements. Box bounds and frame membership
do not validate level, laterality, correct pane placement or lesion identity.
Coordinates are never applied directly to a later composite or crop. This patch
does not add box-to-LPS conversion, source-image annotations, automatic landmark
entry or coordinate-driven sagittal selection. The existing DICOM crop geometry,
axial anchor handling, overview coverage, bilateral supplements, capacity checks
and level-map conflict guard remain in place. New detection outputs can change
which foci/anchors are selected, so subsequent runs are not frozen-input trials.

The [OpenAI prompting guidance](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.6)
supports clear roles and representative evaluation; it does not establish
clinical sensitivity, specificity, PPV, or GapGPT provider equivalence. This
change removes contradictory role instructions without changing transport,
model selection, sampling, token ceilings or adding another model call.

### Verification, scope and next live gate

- Seven initial guards failed before implementation: diagnostic instructions,
  label leakage, raw-text fallback, normal-focus selection and the absent
  source-bound localization contract. Final localization suite: **18 passing**
  synthetic guards, plus an injected parallel-pipeline integration guard proving
  identical crop/diagnostic attention and preservation of the raw response.
- Direct AI Imaging plus default-build inclusion: **772 passed, 8 existing
  xfailed**, exit 0; three existing SWIG deprecation warnings. The adjacent
  Legion sequential handoff is explicitly preserved. No new quarantine.
- **462 plugin mirror pairs match**, with no sync drift. These files belong to
  the already included core AI Imaging package, not a new installable module,
  feature flag or plugin payload. No catalog/installer/config-family changes
  are required. No build, lint pass or repository-wide test pass is claimed.
- No app launch, model request, live database access, viewer change, image
  rewrite, deployment, credential change or migration away from GapGPT occurred.

For the next human-launched source run, verify the stored screening prompt is
2.0.0 and the pipeline is 5.0.0. Inspect raw screening adherence separately from
the sanitized map; check coordinates on their actual original images and review
warning codes. Confirm every retained attention ID has a diagnostic disposition,
normal rows are absent from focus selection, and unassessable is not normal.
Compare detection, level, side, morphology, root effect and grading separately
against clinician-adjudicated references, including misses and failed runs.
Do not promote clinical accuracy from unit tests or a single favorable case.

Rollback is a coordinated reversal of this versioned prompt/handoff change,
not a broad worktree reset or a silent edit of historical results. The existing
layout evidence bypass changes rendering only; it does not restore old prompts.
Remaining Phase 0 scorer repair, clinician landmarks and controlled frozen-input
experiments remain tracked under OPT-55 and section 32.

## 34. Anatomy-first diagnostic alignment (2026-08-31)

The user clarified that location means an **anatomical compartment** such as
disc, endplate or facet joint, plus level/vertebra and image references, not
pixel coordinates alone. Section 33 already transported those fields. A
synthetic check confirms three distinct same-level compartments retain separate
attention IDs and their own cross-plane location lists.

This follow-up changes the prompt contract, not the geometry engine:

- Screening **2.0.1** explicitly requires anatomical location in addition to
  image coordinates. Unknown anatomy remains other/unclear; it is not invented
  from a pixel position. The normalized attention schema stays **2.0.0**.
- Diagnostic verification **4.1.0** explicitly receives per-focus attention
  records plus original/focused MRI evidence and the independent clinical prior.
  It resolves anatomical location, then same-focus correspondence, then abnormal
  presence, diagnostic family/differential, characterization and consequences.
  Shared level or a shared composite sheet does not merge distinct lesions.
- The diagnostic JSON example and field contract now distinguish
  `screening_structure` from the reviewed `structure`, with explicit `level`
  and `vertebra`. A corrected compartment retains the original `attention_id`
  in `candidate`; correction is explained in `reason`. These are requested
  model-output fields, not a new automated clinical-adjudication validator.
  `screening_diagnosis` remains null. Normal/artifact and indeterminate outcomes
  remain valid; a structure-specific differential must not default to disc
  morphology for every endplate or facet focus.
- Pipeline **5.1.0** records the change. Context **2.1.0**, grading, models,
  GapGPT transport, temperatures, token ceilings and evidence budgets are intact.

Three new prompt/example guards failed before this refinement. The anatomical
identity guard passed before and after, demonstrating the already implemented
handoff rather than implying a previously missing data field. The existing
injected parallel integration guard now exercises disc, endplate and facet
joint inputs and proves the same anatomy reaches planning, the saved result
and the diagnostic request without leaking a diagnostic label.

Verification: **122** focused tests pass; full AI Imaging/default-build gate
**778 passed, 8 existing xfailed**, exit 0, with three existing SWIG warnings.
**462 mirror pairs match**, no sync drift. Regression catalog, test/subsystem
indexes and OPT-55 are updated. Runtime edits are confined to the existing core
prompt module; no new module, dependency, configuration, UI, viewer or package
payload is introduced. The bug-fix/Titan workflows drove the fail-before
contract checks and separate claims for transport correctness and clinical use.

**Still not implemented:** automatic DICOM validation of proposed same-lesion
correspondence and direct sagittal selection from the proposed T1/T2 locations.
No source pixels, capture-to-crop transform, clinical reference or saved result
was rewritten. No live app/model call or build was performed. This is not a
claim of improved clinical accuracy or of complete geometric correspondence.
For a human-launched source test, verify pipeline 5.1.0 and review each attention
ID's supplied versus reviewed anatomy and final disposition. A rollback of this
refinement must restore its versioned prompt contract together; keep prior
results and the earlier localization-only handoff unchanged.

## 35. Explicit axial-plane locators without replacing clean evidence (2026-09-01)

### Evidence boundary and decision

Local review found an objectively ambiguous presentation boundary: a focused
sagittal crop can contain several neighboring discs while its sheet title names
one attention level. The geometry selected the crop, but the model could not see
where the paired axial planes intersected it. This is a presentation defect;
it is **not proof that it alone caused the clinical classification disagreement**.
No reference diagnosis, patient identifier, patient image or report is stored in
this document or in committed test fixtures.

The correction deliberately preserves the localization-only screening and the
anatomy-first diagnostic contract. It adds no model stage or external call and
does not force a diagnosis, side, severity or level. The diagnostic context now
explicitly explains that a crop title does not label every visible disc.

### Implementation

- `eagle_eye_lumbar/axial_locator.py` computes finite axial/sagittal plane
  intersections from DICOM geometry. It uses row/column spacing in their proper
  order, source pixel-center coordinates, and clips to both image fields of view.
  It never consumes screening boxes or derives anatomy from a filename.
- `evidence_core/volume.py` retains Frame of Reference identity locally, with UID
  fields excluded from object representations. New locators require a nonempty
  matching reference. The sagittal volume affine is checked against **every**
  source plane's position (0.1 mm tolerance), orientation and pixel spacing
  (1e-4 tolerance). Missing metadata, a nonuniform stack or a conflicting
  reference disables the locator, not legacy decoding. No registration is invented.
- `focus_evidence.py` uses the existing spare eighth cell in a seven-sample
  `focused-v3-parasagittal` sheet for a duplicate of the clean REF image. Only
  this **LOCATOR ONLY** cell receives colored axial-plane lines and original AX
  capture-frame labels. Cyan identifies the anchor frame. The seven clean
  diagnostic samples, ordinary V3 base images, crop extents, sampling and
  physical resolution remain unchanged. If there is no spare cell, the locator
  is unavailable rather than growing the sheet or replacing a diagnostic tile.
- The lines show acquisition planes, **not lesion outlines, anatomical disc
  labels, slab thickness or verified same-lesion correspondence**. Shared DICOM
  reference also does not establish a true anatomical midline or exclude motion.
- Manifest **1.6.0** adds `axial_locator` with policy, status, source slice,
  source-pixel and rendered-cell line endpoints, actual AX capture frames,
  missing-plane reasons and explicit false anatomical/lesion-verification flags.
  No raw reference UID is serialized. Unavailable/partial locators generate
  bounded warning codes and retain clean evidence. Existing budget/fallback
  handling remains authoritative.

Pipeline **5.1.0**, all three stage prompt versions, provider routing through
GapGPT, models, token budgets and the 180-second HTTP read timeout are unchanged.
The changed evidence header/captions are saved with the actual diagnostic request;
the new manifest schema distinguishes this evidence revision. No new selectable
plugin, dependency, configuration family, viewer/UI work or GUI-thread work is
introduced. The helper is inside the existing core AI Imaging package and is
covered by the existing whole-package build inclusion.

### Verification and remaining live gate

The first behavioral guard failed before implementation on the absence of an
explicit locator availability record (pytest exit 1). The resulting synthetic
suite covers oblique planes, anisotropic spacing, reversed source order, finite
FOV clipping, missing/conflicting references, invalid/parallel/nonintersecting
geometry, metadata propagation through real synthetic DICOM decoding,
nonuniform/missing source geometry, partial links and clean-pixel retention.

An offline reconstruction of the selected saved input completed in about **4.2 s**,
without any model request or app interaction. All three locators were included.
The package retained **8 images and 11,253,504 pixels**; bytes changed from
**5,880,276 to 6,055,847** (about 3%). Byte/pixel comparisons confirmed unchanged
base images and unchanged pixels outside each formerly empty locator cell.
Every sagittal source plane passed the additional affine check and shared a
reference with every selected axial source slice. The derived preview was saved
only in a separate ignored local diagnostic directory; previous evidence,
requests, captures and reports were not overwritten. Visual inspection confirmed
legible AX labels and an unobstructed clean counterpart.

Automated verification: **32 new guards pass**; direct full AI Imaging plus
default-build inclusion suite: **810 passed, 8 existing xfailed**, exit 0 (three
existing SWIG warnings). **462 mirror pairs match**, sync dry-run reports no
drift. No source changed here has a plugin mirror. No installer build, live
model request, clinical improvement claim or benchmark-score claim was made.

For historical reproduction of this human-launched source test, enable the
Section 38 engineering gate, select
`AIPACS_EAGLE_EYE_EVIDENCE_MODE=focused-v3-parasagittal`, restart the one source
instance and re-analyze. Check manifest 1.6.0, `axial_locator.status`, identical
clean coverage and each diagnostic decision's actual source level. Clinical
benefit requires radiologist adjudication and repeated/frozen-input comparisons;
the existing scorer limitations still apply. Ordinary `focused-v3` bypasses
both supplements and locators; `layout` remains the original evidence bypass.

This change follows the bug-fix, DICOM-compatibility and Titan workflows. Geometry
conventions follow [DICOM PS3.3 C.7.6.2](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.6.2.html)
and the [Frame of Reference module](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_C.7.4.html).
Full validated anatomical landmarks, deformable registration, automatic
same-lesion clinical verification and complete benchmark repair remain open.

## 36. Source-grounded correlated screening and focused V4 (2026-09-01)

The implemented first reader now has exactly three responsibilities: detect a
plausibly abnormal anatomical focus, localize it, and propose which sagittal T2,
sagittal T1, and axial T2 observations represent the same focus. It does not
classify disease, morphology, grade, severity, or consequence.

`focused-v4-correlated` replaces UI-screen coordinates with a bounded atlas
rendered from immutable DICOM sources in the analysis worker. Every tile carries
a session-local identity; a model box is defined against the grayscale content
of that tile. The orchestrator resolves each accepted box to patient LPS and
checks Frame of Reference plus cross-plane separation. Geometry can verify only
spatial compatibility. It cannot verify anatomy, level, side, normality, or
diagnosis, all of which the GPT diagnostic reader must re-derive.

The verified focus medoid is retained in the local attention plan and used to
centre the V4 sagittal and axial evidence. Raw coordinates are removed before
the diagnostic context is serialized. The existing wide overview, tight focus,
parasagittal supplement, locator, capacity limits, measured slab identity, and
report-level conflict guard remain active. Atlas construction and focused
verification have separate layout fallbacks, and no viewer Sync/Scroll/Crop
command is issued after capture.

At pipeline 5.2.0, the source and packaged-build default became
`focused-v4-correlated`. Section 41 supersedes that evidence default with V5.
Explicit
layout, V1, V2, V3, and V3-parasagittal paths are retained only for engineering
rollback and controlled comparison. Synthetic tests validate identity rejection, LPS correlation, and
lesion-centred cropping. They do not validate model localization or clinical
diagnostic accuracy. An initial human-controlled source run has completed; the
locked multi-case benchmark with failures retained in the denominator remains
required.

## 37. Canonical screening-to-diagnosis handoff (2026-09-01)

Pipeline 5.3.0 adds a deterministic contract between the sensitivity reader and
the diagnostic reader. Gemini still returns its immutable raw response for audit,
but raw rows and prose never become diagnostic memory. The local orchestrator
now emits one canonical attention row per supported anatomical focus.

Repeated observations of the same structure and anatomical site are merged;
their valid source-bound locations and axial/sagittal frame lists are unioned.
When patient-space anchors show observations more than 25 mm apart, they remain
separate attention foci instead of being collapsed by a shared level label.
Correlated sagittal and axial observations can therefore become one verified
multiplanar focus while spatially distinct abnormalities remain A and B.

Contradictory normal and abnormal assessments are resolved locally in favor of
abnormal presence, matching the screening sensitivity objective, and confidence
is reduced by one step. `not_assessable` never becomes normal. Left plus right
for the same structure/site becomes bilateral; any other unresolved categorical
side disagreement becomes indeterminate. These rules remove contradictory claims
without converting uncertainty into a negative examination.

The GPT handoff excludes `normal_count`, raw parser warnings, diagnoses, grades,
free text and exact LPS. It contains only canonical findings, material assessment
gaps, source/tile evidence, geometry status and a bounded `handoff_quality`
record. Internal parsing and provenance remain in the saved stage audit. Screening
prompt 2.2.0 requests the same behavior at source; local normalization remains
authoritative when the model violates it. Verification prompt 4.3.0 treats every
canonical `attention_id` as one independent diagnostic task.

Three guards failed before normalization: duplicate same-focus rows survived,
normal/abnormal disagreement retained high confidence, and competing left/right
rows reached diagnosis separately. Two additional guards failed before the
compact public handoff and prompt contract, and the geometry guard failed until
distant same-anatomy anchors were split. Adversarial self-review then caught and
guarded an intermediate error that promoted a focus with no valid geometry from
`unavailable` to `verified_single_plane`. Final verification is 35 focused
screening/correlation/version guards, 134 orchestration/focused-evidence guards,
817 AI Imaging tests passed with 8 existing xfails, three default-build inclusion
tests passed, and 462 plugin mirror pairs matched. No app launch, model call,
clinical accuracy claim, installer build or deployment occurred. A human source
run and locked clinical benchmark remain required.

## 38. Historical V4 runtime and legacy retirement (2026-09-01)

The canonical policy introduced with pipeline 5.3.0 was active in pipeline
5.4.0: `focused-v4-correlated` was the only ordinary Eagle Eye lumbar evidence
configuration. It was selected when no environment variable was
present and when a stale runtime variable requested layout, V1, V2, V3, or
V3-parasagittal. The app logged that the retired request was ignored and continued
with V4. Pipeline 5.6.0 now selects V5 under the same fail-closed policy; see
section 41. An unsupported value remains a configuration error rather than being
silently guessed.

The older composers have not been physically deleted because they remain useful
for reproducing historical benchmarks and for a bounded incident rollback. They
are unreachable through ordinary mode selection. An engineer must set both
`AIPACS_EAGLE_EYE_ALLOW_LEGACY_EVIDENCE=1` and
`AIPACS_EAGLE_EYE_EVIDENCE_MODE=<retired-mode>` in the same process. The benchmark
CLI applies this gate only when a retired `--evidence-mode` is explicitly chosen.
No UI setting or packaged runtime profile enables the gate.

The first human-controlled source run of the canonical 5.3.0 handoff completed
all three model stages through GapGPT without a transport failure or layout
fallback. It preserved the correct level map and identified the principal lower
lumbar extrusion morphology and side. It still undercalled lateral-recess and
root-effect severity and missed quieter abnormalities, so this is initial
runtime acceptance rather than clinical validation or promotion evidence.

Four mode-policy assertions failed before the retirement gate existed. Final
mode-focused verification passed 120 tests; the complete AI Imaging gate passed
819 tests with 8 existing xfails and 3 dependency warnings. The three default
build-inclusion guards passed, and all 462 plugin mirror pairs matched. No
installer build or deployment was performed.

## 39. Submillimetric sagittal screening pages and sampling audit (2026-09-01)

The first canonical V4 source run correctly combined the principal disc
morphology, side, migration and level, but did not raise a quieter upper-level
disc focus. Read-only inspection identified a structural asymmetry in the new
screening request. The axial atlas retained approximately `0.4065 mm/px`, while
the full-column sagittal crop was letterboxed into a fixed square tile and
reached only `148 x 256` diagnostic pixels, approximately
`1.0135-1.0162 mm/px`. Verification sagittal overview and focus sampling were
`0.5208` and `0.3906 mm/px`, respectively.

Page count was not itself the cause: the renderer used a fixed `256 x 256` tile,
so placing fewer slices on a page would only create a narrower canvas. Pipeline
5.4.0 instead keeps axial pages unchanged and gives sagittal T2/T1 a
`320 x 555` no-upscale tile with six slices per page. For a representative
synthetic 11-slice, 0.390625-mm source series, each sagittal role becomes two
pages of 6+5 slices and preserves `0.4688 mm/px`. With four synthetic axial
slices the complete screening request contains five pages; the observed
25-slice axial layout would contain six. The screening and verification image
budgets are separate requests and are therefore audited separately.

Screening manifest schema 1.1.0 records each tile's source spacing, fitted
diagnostic-content size, effective millimetres per pixel and tile size. Its
`screening_sampling` block summarizes sampling ranges and page/tile counts by
role. A separate 8-image/12-MP/12-MiB screening budget is measured against the
rendered files before dispatch, with capacity notes persisted. The compact
sampling/budget summary also reaches `llm_result.json`; private mappings and
per-tile coordinates remain only in the session-local screening manifest.
Quality, render and budget failures use the existing layout fallback contract.
With the current eight-image request ceiling, unusually deep sagittal series
that require more than three pages per sagittal role can exceed capacity and
therefore fail closed to that fallback; adaptive packing is deferred until a
real source case demonstrates that need.

The causal claim remains deliberately narrow. The lower-resolution sagittal
screening path plausibly explains why a small focus never entered the diagnostic
handoff, but one model run does not prove that relationship. A lower-vertebral
bone-marrow focus did enter screening and was rejected by the diagnostic reader,
so its final classification miss is not attributed to screening resolution.
No disease-specific prompt, severity rule or positive-label injection was added.

Eight guards failed before the changes: schema, paging, sampling, budget,
result-audit persistence, quality fallback, render fallback and pipeline
versioning. Final focused screening/orchestration verification passed 135 tests;
the full AI Imaging gate passed 825 with 8 existing xfails and 3 dependency
warnings. Three default-build inclusion guards passed and all 462 plugin mirror
pairs matched. No live model rerun, clinical improvement claim, installer build
or deployment occurred; a human-controlled source rerun is required.

## 40. Salience-aware screening and dominant-focus retention (2026-09-01)

Read-only comparison of two source runs with byte-identical six-page screening
atlases found materially different Gemini candidate counts. The later run still
localized the principal caudal abnormality, but the deterministic evidence
planner selected four cranial levels first because confidence and family tied
and anatomical level order was the final discriminator. The principal focus was
therefore discovered by screening but did not receive dedicated diagnostic
evidence. This is a handoff/retention defect, not proof of a model-detection
failure.

Pipeline 5.5.0 and screening contract 2.3.0 make the first reader explicitly
atlas-aware and retain its diagnosis-free role. The prompt now orders a global
sweep before row emission and requests three bounded routing observations:
`visual_salience`, `within_study_priority`, and `slice_persistence`. A small
allowlist transports directly visible signal, contour, space-effacement and
neural-relationship observations. These fields are not a morphology, grade,
diagnostic severity or clinical urgency, and the GPT handoff explicitly forbids
copying them into those decisions. The prior level-specific positive example was
replaced by a placeholder schema so it cannot anchor the reader to one disc or
level. Uncertainty about cause preserves a directly visible focus; uncertainty
about abnormal presence now requires direct visual support rather than automatic
positive retention.

The local normalizer canonicalizes the new fields, discards unknown keys and
marks an incomplete 2.3.0 routing contract as degraded. Evidence-plan schema
1.2.0 ranks marked/dominant foci before anatomical order, then uses persistence,
validated correspondence, confidence and family as bounded tie-breakers. Level
order is last. If more marked or dominant levels exist than the configured focus
capacity, the plan records a specific capacity warning; the report-level evidence
guard therefore requires review instead of silently treating omitted evidence as
normal. The focus manifest records the routing values that produced each selected
sheet, so a live run can be audited without reinterpreting model prose. Existing
image budgets, DICOM atlas pixels, GapGPT transport, context
branch, verification prompt, model identifiers and then-current focused-V4
default were unchanged by pipeline 5.5.0. Section 41 supersedes that evidence
default.

Six behavioral guards failed before the production changes: the 2.3.0 contract
was absent, the normalizer dropped routing fields, a marked/dominant L5-S1 focus
lost to four high-confidence cranial levels, dominant over-capacity truncation
was silent beyond a generic warning, and an incomplete 2.3.0 contract was not
material to the diagnostic handoff; the focus manifest also omitted the routing
decision. The changed boundary passed 235 tests. The
complete AI Imaging suite passed 830 tests with 8 existing xfails and 3 existing
third-party SWIG warnings, exit code 0.

Screening temperature remains 1.0 in this slice. The identical-input variance is
real evidence for a controlled temperature experiment, but changing the Gemini
3 default without repeated sensitivity measurements could trade variance for a
missed focus. The next live gate is a frozen-atlas repeated comparison at 1.0,
0.2 and 0.0, retaining failures in the denominator and measuring dominant-focus
detection/retention, major-focus set stability and false-focus burden. No model
request, app launch, clinical-accuracy claim, installer build or deployment was
performed here.

## 41. Self-contained diagnostic level cards (2026-09-01)

The remaining level swaps were traced to diagnostic evidence identity rather
than to an absent lesion. Focused V4 could send a sagittal overview, an axial
overview, one wide focus sheet per selected level, and one parasagittal
supplement per focus. For adjacent lower-lumbar levels, the 100-mm sagittal
crops overlapped heavily and used the same sagittal source slices. A conspicuous
L5-S1 abnormality was therefore visible inside the image titled L4-L5. The
diagnostic reader could also cite an axial range belonging to a different focus,
and page-local screening numbering was not explicitly tied to the global upload
number used by the transport. More prompt text could not make this package
unambiguous.

Pipeline 5.6.0 and verification prompt 4.4.0 make
`focused-v5-level-cards` the canonical source and packaged-build mode. The
existing diagnosis-free screening normalizer continues to group attention by
anatomical level. For every selected level, the worker now produces exactly one
self-contained diagnostic card containing:

- one targeted sagittal T2 tile centred through patient geometry;
- one geometrically matched sagittal T1 tile when the source series exists; and
- no more than four contiguous axial T2 frames drawn only from that level's
  measured acquisition slab.

The card title, both row labels, every tile label, the model-facing caption, the
request header and manifest all repeat the subject level. The header binds the
global image number to its `focus_id`, canonical `attention_id` values, subject
level and allowed axial display frames. Positive-focus V5 requests contain no
whole-stack overview or separate parasagittal supplement, so the diagnostic
reader receives one image for one level instead of several partially redundant
views. If screening resolves no usable focus, the established overview fallback
is retained and recorded; missing evidence is never interpreted as normal.

The V5 sagittal card crop is 100 mm anteroposterior by 60 mm craniocaudal. This
retains local migration context while reducing adjacent-level exposure relative
to the prior 100 x 100 mm focus sheet. It remains a geometric crop rather than a
segmentation. The prompt permits diagnosis only from the attention's bound card
and explicitly forbids borrowing a neighboring card for morphology, level,
laterality or grade. All image transports now prefix each caption with
`IMAGE n OF N`, so Gemini and GPT see the same global identity that the request
header and manifest record.

Two further anchoring channels were closed. The clinical-context MRI overview
may still emit bounded global burden and postoperative context, but its
free-form broad patterns are not forwarded as diagnostic claims. A focus derived
only from paired sagittal MRI is forwarded as a neutral level attention request,
not as a named extrusion, root lesion or stenosis. Missing atlas tile identity is
material degradation in the screening handoff rather than silently available
evidence.

Finally, integrity guard 1.1.0 parses axial frame citations in the structured
verification audit and compares them with the card binding. A citation outside
the allowed frame set makes the stored report review-required, identifies the
affected attention and frames, and preserves the unmodified model report below
the notice. The guard does not relabel a level, alter a diagnosis or claim that
geometry establishes anatomy.

The principal guards failed before their production boundaries existed: V4
returned three images for one synthetic focus instead of one card, the shared
GapGPT content builder exposed no global image number, MRI-overview context
retained a level-specific extrusion/root claim, and no audit function rejected a
cross-card axial range. Focused validation passes 173 tests. The complete AI
Imaging gate passes 837 tests with 8 pre-existing xfails and 3 pre-existing SWIG
warnings. Default-build inclusion plus mirror parity passes 4 tests, and all 462
source/plugin mirror pairs match after synchronizing the EchoMind transport.
No live app launch, model request, clinical-accuracy claim, installer build or
deployment was performed. The next acceptance step is a human-controlled source
rerun followed by the locked radiologist-adjudicated multi-case benchmark.

## 42. Fixed anatomical reading template for each diagnostic level card (2026-09-01)

The first V5 card removed cross-level image borrowing but still made the
diagnostic reader infer a reading order from one sagittal T2 tile, one sagittal
T1 tile and a variable-length axial ribbon. That left two avoidable sources of
variation: the same anatomy could occupy a different visual position from one
card to the next, and the screening reader could identify useful source slices
without a structured way to bind them to the diagnostic package.

Pipeline 5.7.0, screening contract 2.4.0, verification prompt 4.5.0,
evidence-plan schema 1.3.0 and V5 manifest 2.1.0 retain the same canonical
`focused-v5-level-cards` mode but make every positive-focus image the same fixed
3 x 3 template:

| Row | Column 1 | Column 2 | Column 3 |
|---|---|---|---|
| Sagittal T2 | patient-right foraminal sampling plane | midline sampling plane | patient-left foraminal sampling plane |
| Sagittal T1 | patient-right foraminal sampling plane | midline sampling plane | patient-left foraminal sampling plane |
| Axial T2 | disc-level plane | maximum-abnormality plane | caudal-extent plane |

Gemini remains a localization-only reader. For each allowlisted abnormal level,
it proposes exact correlated-atlas `image` and `tile_id` identities for the nine
predeclared slots. It must use `null` rather than inventing a tile. The local
normalizer accepts only an inventory-backed tile whose source role matches the
slot. The evidence planner transports only the normalized source slice/capture
identity, and the renderer checks axial membership against the measured subject
slab. A rejected, missing or out-of-range proposal is replaced by a deterministic
local geometry/same-slab fallback whose selection source is explicit in the
manifest. The fallback is not represented as Gemini-verified anatomy.

The diagnostic prompt reads the rows in a fixed sequence. It uses sagittal T2
for signal, contour, continuity and morphology; sagittal T1 for marrow/endplate
anatomy and foraminal fat; and axial T2 for canal, lateral recess, root and focal
disc relationships. Slot names are sampling positions, not findings, diagnoses,
severity labels or proof of a lesion's side. The prompt also separates the
standard axial zones `central`, `subarticular`, `foraminal` and `extraforaminal`
from the craniocaudal `discal`, `suprapedicular`, `pedicular` and
`infrapedicular` levels described by the combined NASS/ASSR/ASNR nomenclature.
Those axes are not interchangeable. See Fardon et al., 2014:
<https://pubmed.ncbi.nlm.nih.gov/24768732/>.

Six principal guards failed before implementation: the normalized handoff had
no level-card template, a sagittal slot accepted an axial tile, reversed LPS
ordering was accepted, rejected-slot degradation was hidden from the public
handoff, the renderer still produced the variable V5 layout, and the two prompts
did not share the slot vocabulary. The changed boundary passes 166 tests. The
complete AI Imaging suite passes 842 tests with 8 pre-existing xfails and 3 pre-existing SWIG
warnings. These guards establish deterministic source identity, layout and
scope; they do not establish anatomical-midline truth, clinical sensitivity or
diagnostic accuracy. A human-controlled source rerun and the locked
radiologist-adjudicated benchmark remain required.

## 43. Geometry-owned card assembly and compact card-local metadata (2026-09-01)

An offline reconstruction of the latest saved lower-lumbar case exposed a
second identity defect inside the new fixed template. The screening record
predated the nine-slot contract and supplied one axial key frame at the edge of
the measured slab. The local fallback consequently assigned the same source
frame to the disc-level, maximum-abnormality and caudal-extent slots. The image
therefore looked structured while carrying only one axial observation under
three different labels. This was a packaging defect, not a model miss.

Pipeline 5.8.0, screening contract 2.5.0, verification prompt 4.6.0,
evidence-plan schema 1.4.0, card-template schema 1.1.0 and V5 manifest 2.2.0
retain `focused-v5-level-cards` as the ordinary default and make the local
orchestrator the final authority for spatial assembly:

- Gemini still identifies abnormal structures and proposes exact atlas tiles.
  Each proposed slot now also carries `abnormality_conspicuity` from 0 to 3 and
  the attention IDs visible in that tile. The score means not visible, subtle,
  definite or marked visibility in that tile. It is explicitly not disease
  severity, morphology, stenosis grade, clinical urgency or diagnostic truth.
- The normalizer accepts only scores in the bounded range and attention IDs
  already assigned to abnormal findings at that level. Unknown IDs, invalid
  scores, wrong-sequence tiles, reversed sagittal order and repeated axial-slot
  frames degrade the handoff instead of silently becoming trusted evidence.
- DICOM patient coordinates determine the patient-right, central and
  patient-left sagittal order. The selected T2 planes are projected into the T1
  volume so both rows sample the same patient-space planes. An independent T1
  tile proposal cannot break cross-series synchronization.
- A complete set of three distinct Gemini axial slots is retained only when all
  three frames belong to the measured subject slab. Otherwise the fallback
  emits three distinct contiguous same-slab context frames whenever slab depth
  permits; it never relabels one frame three times. Its non-Gemini selection
  status remains explicit.
- DICOM plane intersections are rendered as short cyan edge ticks. No full
  reference line crosses diagnostic anatomy. The local manifest preserves the
  intersection coordinates, while the model-facing JSON exposes only locator
  status and the referenced axial frame.

Only levels with abnormal Gemini screening attention receive named level cards.
Clinical context can enrich a screened level but cannot create a diagnostic card
by itself. Abnormal source-bound findings whose level is `unclear` are no longer
dropped: at most one bounded ADDITIONAL FINDINGS card transports those locations
without forcing a lumbar disc interval. The diagnostic reader must preserve the
localization uncertainty unless anatomy inside that card resolves it.

At pipeline 5.8.0, every card caption ended with compact
`CARD_METADATA_JSON`. It bound the card
and attention IDs, subject level or additional-finding scope, diagnosis-free
structure observations, selected source slices/capture frames, per-tile score,
selection provenance, a fixed disc/endplate/marrow/vertebral-body/facet/flavum/
canal/recess/foramen/root checklist, and compact locator status. A checklist
value of `not_raised_by_screening` is not a normal claim and requires independent
diagnostic review. Full geometry remains in the
session-local manifest and is intentionally not repeated to the model. The
ordinary V5 budget permits up to six cards, sufficient for five abnormal disc
intervals plus one additional-findings card while remaining under the existing
eight-image and twelve-megapixel request ceilings.

Six new behavioral boundaries were reproduced before correction: per-tile
metadata was discarded; one axial frame occupied multiple semantic slots; an
unresolved abnormal location was dropped and triggered an overview fallback;
context alone could create a level card; T1 proposals could diverge from the T2
plane; and no edge-only locator contract existed. The changed screening/card
boundary passes 67 tests. The complete AI Imaging suite passes 848 tests with
8 pre-existing xfails and 3 pre-existing SWIG warnings, exit code 0. Builder
inclusion/parity passes 7 tests with 4 intentionally deselected, and all 462
plugin mirror pairs match. The saved-source reconstruction confirms distinct
same-slab axial frames, synchronized sagittal rows and edge-only ticks without a
model request. A fresh human-controlled source run is still required to populate
real per-tile Gemini scores and assess clinical behavior; no diagnostic-accuracy,
installer-build or deployment claim is made.

## 44. Same-plane sagittal pairs and sequence-separated axial reading (2026-09-01)

Card template 1.1.0 synchronized sagittal T1 to the selected sagittal T2 planes
in patient geometry, but the visual layout still placed all T2 tiles in one row
and all T1 tiles in another. The diagnostic reader therefore had to compare a
tile with another tile one complete row away while also retaining the correct
patient-right, midline or patient-left identity. The geometry was correct; the
visual correlation cost was unnecessary.

Pipeline 5.9.0, verification prompt 4.7.0, card-template schema 1.2.0 and V5
manifest 2.3.0 keep the nine source slots and the canonical
`focused-v5-level-cards` mode, but change the diagnostic card into four explicit
visual groups:

| Group | First tile | Matched or subsequent tile | Reading direction |
|---|---|---|---|
| Patient-right sagittal pair | T2 right foraminal sampling plane | geometry-matched T1 plane | top to bottom |
| Midline sagittal pair | T2 midline sampling plane | geometry-matched T1 plane | top to bottom |
| Patient-left sagittal pair | T2 left foraminal sampling plane | geometry-matched T1 plane | top to bottom |
| Level-bound axial sequence | disc-level plane | maximum-abnormality, then caudal-extent planes | left to right |

The three sagittal pairs remain horizontal in patient-space order, but each T2
tile now sits immediately above its matched T1 tile inside one shared column
container. A strong neutral divider separates the sagittal comparison region
from the axial sequence. Cyan, amber and violet borders identify sagittal T2,
sagittal T1 and axial T2 respectively. The legend, request header, caption,
prompt and manifest all state that border color encodes sequence identity only;
it never encodes abnormality, laterality, severity, confidence or diagnosis.

The sagittal crop is physically 100 x 60 mm. It previously occupied a square
384 x 384 cell and spent substantial canvas area on letterboxing. The paired
card uses a 384 x 256 sagittal cell while retaining a 384 x 384 axial cell. The
source crop and fit policy are unchanged, so the sagittal diagnostic content is
not downsampled; only unused padding is reduced. Total pixels per level card
fall from 1,456,128 to 1,283,328, an 11.9 percent reduction. The resulting
1.28-megapixel image is below the configured OpenAI `high`-detail preservation
threshold used by the GapGPT bridge. OpenAI documents that image-detail choice
controls preserved resolution and token use, while Google documents that higher
media resolution improves small-detail recognition at a token/latency cost and
recommends explicit instructions when a model is not drawing from the relevant
part of an image. Neither vendor mandates this clinical layout; the paired-
column design is a local engineering inference that minimizes comparison
distance without increasing image count or shrinking the axial sequence.

The card-local JSON now carries `layout_kind`, pair groups, exact pairwise visual
reading order, role-specific tile sizes and a non-diagnostic sequence-border
legend. Slot provenance, geometry decisions, attention bindings, per-tile
conspicuity and structure checklist semantics are otherwise unchanged. The
diagnostic prompt must finish each same-plane T2/T1 comparison before moving to
the next sagittal plane, then read the axial sequence from left to right.

The card-layout guard failed before implementation at 1264 pixels high, card
template 1.1.0 and row-major slot order; prompt/pipeline version guards also
failed at 4.6.0 and 5.8.0. After correction, the changed prompt/card boundary
passes 172 tests. The complete AI Imaging suite passes 848 tests with 8
pre-existing xfails and 3 pre-existing SWIG warnings. Builder package checks
pass 4 tests with 4 intentionally deselected, and all 462 plugin mirror pairs
match. An offline reconstruction of a saved lower-lumbar source confirms the
three T2/T1 pairs and three distinct axial frames without a model request. A
fresh human-controlled source run and the locked radiologist-adjudicated
benchmark remain required; no diagnostic-accuracy, installer-build or
deployment claim is made.

Primary vendor references:

- OpenAI model and image-input guidance:
  <https://developers.openai.com/api/docs/guides/latest-model>
- Google Gemini image understanding and media-resolution guidance:
  <https://ai.google.dev/gemini-api/docs/image-understanding>
- Google multimodal prompt troubleshooting:
  <https://ai.google.dev/gemini-api/docs/files#prompt-guide>

## 45. Five-plane sagittal coverage in diagnostic level cards (2026-09-01)

The paired V5 card correctly matched T2 to T1, but its sagittal selector began
with a five-slice patient-space window and then retained only the two endpoints
and centre. The right and left paracentral planes were discarded before the
diagnostic request. This made the card structurally unable to show the complete
foraminal-to-foraminal morphology requested by the radiologist, even when the
source series contained nine to eleven sagittal slices.

Pipeline 6.0.0, screening contract 2.6.0, verification prompt 4.8.0,
evidence-plan schema 1.5.0, card-template schema 1.3.0 and V5 manifest 2.4.0
retain `focused-v5-level-cards` as the ordinary default and define one fixed
thirteen-slot card per abnormal level:

| Patient-space column | Upper tile | Lower matched tile |
|---|---|---|
| Right foraminal | sagittal T2 | geometry-matched sagittal T1 |
| Right paracentral | sagittal T2 | geometry-matched sagittal T1 |
| Midline | sagittal T2 | geometry-matched sagittal T1 |
| Left paracentral | sagittal T2 | geometry-matched sagittal T1 |
| Left foraminal | sagittal T2 | geometry-matched sagittal T1 |

The three level-bound axial T2 slots remain disc-level, maximum-abnormality and
caudal-extent planes below a neutral divider. The local selector requires five
distinct sagittal source planes, orders them by DICOM patient LPS rather than
filename or instance order, and rejects incomplete five-plane coverage instead
of duplicating or falsely relabelling a plane. The selected T2 planes remain the
patient-space authority; each T1 tile is projected from its matched T2 plane.
Gemini proposes the same thirteen source-bound slots and the diagnostic prompt
reads them in the identical right-foraminal-to-left-foraminal order.

Five 384-pixel sagittal columns would exceed the existing twelve-megapixel
request ceiling when all six permitted cards are present. The sagittal cell is
therefore 320 x 224 while its physical source crop remains 100 x 60 mm; the
axial cells remain 384 x 384. One card is 1600 x 1050, or 1,680,000 pixels, and
six cards total 10,080,000 pixels, leaving 1,920,000 pixels of headroom. The
saved-source reconstruction produced two cards totalling 3,360,000 pixels and
1,311,545 encoded bytes. Visual review confirmed five T2/T1 columns with source
slices ordered from patient right to patient left and three distinct axial
frames. No model request was spent on this reconstruction.

Three representative guards failed before implementation: the rendered card
was 1152 x 1114, the fallback returned only three of five available sagittal
planes, and normalized screening remained on schema 2.5.0. After correction,
the changed prompt/card boundary passes 173 tests. The complete AI Imaging suite
passes 849 tests with 8 pre-existing xfails and 3 pre-existing SWIG warnings.
Builder package checks pass 4 tests with 4 intentionally deselected, Python
compilation succeeds, and all 462 plugin mirror pairs match. These checks prove
evidence coverage, identity, ordering and request boundedness. A fresh
human-controlled source run and the locked radiologist-adjudicated benchmark
remain required; no diagnostic-accuracy, installer-build or deployment claim
is made.

## 46. Anatomy-first midline and spaced sagittal sampling (2026-09-01)

Card template 1.3.0 retained five sagittal planes but selected five consecutive
source slices around the lateral coordinate of the screening focus. A lateral
disc focus could therefore shift the nominal midline, while the immediately
adjacent paracentral and foraminal columns did not sample the intended anatomy.
The visible labels also said only `slice`, which could be mistaken for DICOM
InstanceNumber even though the card uses source-volume indexes and those orders
may be reversed.

Pipeline 6.1.0, screening contract 2.7.0, verification prompt 4.9.0,
evidence-plan schema 1.6.0, card-template schema 1.4.0 and V5 manifest 2.5.0
retain the thirteen-slot default card but change its sagittal sampling policy to
`anatomical-midline-spaced-v1`:

- Gemini selects anatomical midline from vertebral-body, spinal-canal and
  posterior-element symmetry rather than from the abnormal focus or file count.
- A complete Gemini proposal is accepted only when its five planes remain
  patient-right-to-left, are distinct, keep each paracentral plane two or three
  source intervals from midline, and keep each foraminal plane farther outward.
  The outermost step may be one interval when an asymmetric acquisition or
  boundary makes that plane anatomically preferable.
- An incomplete or invalid proposal uses the acquisition centre, optionally
  refined by a bounded Gemini midline, then selects source offsets
  `-4, -2, 0, +2, +4`. This preserves one intervening source slice between the
  ordinary midline, paracentral and foraminal samples.
- The lateral coordinate of a lesion remains the craniocaudal crop anchor but
  can no longer redefine sagittal midline. T1 is still projected from each
  selected T2 plane through patient geometry.
- On-card `VOL n/N` labels now explicitly mean source-volume index. The request
  header and caption state that this is not DICOM InstanceNumber and that the
  two orders may run in opposite directions.

The saved-source reconstruction produced the expected non-consecutive T2 and
T1 sequence `10, 8, 6, 4, 2` in patient-right-to-left volume order, with three
distinct axial frames. In that acquisition, source-volume order is reversed
relative to DICOM instance order, so the content corresponds to the expected
low-to-high instance progression. The validator also accepts a one-step inward
outer foraminal proposal when Gemini identifies it as the more representative
anatomical plane. Two reconstructed cards remain 3,360,000 pixels and 1,298,569
encoded bytes, with unchanged request headroom. No model request was used.

Six guards failed before the correction: five consecutive planes, a lateral
lesion anchor controlling midline, unchanged card/prompt versions, absent
spacing instructions, and ambiguous volume-index labelling. The changed
prompt/card boundary passes 174 tests. Complete AI Imaging passes 850 tests with
8 pre-existing xfails and 3 pre-existing SWIG warnings. Builder package checks
pass 4 tests with 4 intentionally deselected, Python compilation succeeds, and
all 462 plugin mirror pairs match. These checks establish sampling, identity,
ordering and boundedness; a fresh human-controlled model run and the locked
radiologist-adjudicated benchmark remain required before any diagnostic-
accuracy claim.

## 47. Explicit per-card JSON sidecars and model bindings (2026-09-01)

Pipeline 6.2.0, verification prompt 5.0.0 and V5 manifest 2.6.0 retain the
parallel Gemini architecture and make the diagnostic handoff explicit. The
image-screening and clinical-context branches still execute concurrently.
Only abnormal, source-bound screening attention can create a diagnostic card;
clinical context is sanitized and appended as a global diagnostic prior, but
cannot create a card. Named lumbar levels receive one level card each. A
source-bound abnormality that cannot safely be assigned to a named level uses
the separate additional-findings card with `subject_level: null`.

Each rendered diagnostic card now has exactly one structured payload:

- the PNG and its sibling `.card.json` file share the same basename;
- the payload records its request `image_index`, PNG filename, `card_id`, card
  kind, subject level or unresolved scope, attention IDs, structure checklist,
  source slots, geometry/fallback provenance and non-severity conspicuity;
- the verification manifest binds that sidecar filename and metadata to the
  same global image number;
- the saved stage-three request records the payload both beside its image entry
  and in an ordered `card_payloads` collection;
- the shared EchoMind/GapGPT content builder inserts exactly one compact
  `CARD_METADATA_JSON` block immediately before the corresponding image.

The JSON was removed from the free-form caption itself. This prevents the same
large object from being repeated while preserving the useful human-readable
card instructions. The diagnostic prompt now treats the explicit block, not a
caption suffix, as the machine-readable authority. The model still receives
the card and JSON as one adjacent text/image unit, and the stage-three request
artifact now records the exact combined header actually passed to transport.

Four principal requirements failed before implementation: `PackagedImage`
could not hold a card payload, no `.card.json` file existed, the saved request
had no ordered card-payload collection, and the transport could not emit a
separate JSON block. The latest saved source session was reconstructed locally
without a model call. It produced two cards, two JSON sidecars, two manifest
bindings and two model-facing JSON blocks; every payload matched exactly after
JSON decoding. The synthetic additional-findings guard verifies the same
contract for unresolved anatomy. These checks establish transport identity and
auditability, not diagnostic accuracy. The changed prompt/card/transport
boundary passes 126 tests. Complete AI Imaging passes 852 tests with 8
pre-existing xfails and 3 pre-existing SWIG warnings. Builder package checks
pass 4 tests with 4 intentionally deselected, Python compilation succeeds, and
all 462 plugin mirror pairs match. A fresh human-controlled Gemini/Sol run and
the locked radiologist-adjudicated benchmark remain required.

## 48. Card-first diagnostic prompt alignment (2026-09-01)

Pipeline 6.3.0 and verification prompt 5.1.0 align the GPT-5.6 Sol diagnostic
reader with the V5 transport introduced in section 47. The previous verifier
had accumulated mutually incompatible instructions: it still described two
whole-workstation screenshot sweeps, invited a whole-study level recount,
allowed context-only current-MRI additions, and required a broad safety sweep
even though the canonical request now contains selected positive-attention
cards. Its output example also embedded a specific L4-L5 extrusion. That
case-specific example could anchor a reader toward the wrong level and has been
removed.

The canonical verifier now uses a card-first contract:

- process request images in order and bind each PNG to the immediately
  preceding `CARD_METADATA_JSON` before interpreting it;
- record `card_id`, request image index, card kind and card subject level in
  every verification row;
- issue one independent presence/classification decision for every bound
  `attention_id`, while keeping distinct anatomical structures separate;
- decide presence before diagnosis, then correlate the paired sagittal T2/T1
  planes and ordered axial sequence before morphology, side, extent and
  consequences;
- use context only to rank the differential for an existing card; context
  cannot create a diagnostic card or an unbound current-study diagnosis;
- confine safety additions to anatomy demonstrated inside the current card;
- treat the printed subject level as the card task scope. A focused reader may
  not recount the whole lumbar study or transfer a finding to an adjacent card.
  An incompatible image/binding is `INDETERMINATE`, not a silent relocation;
- use a neutral structured-output template without a seeded level, disease or
  severity.

The legacy screenshot reader is retained only behind an explicit legacy
package declaration. Its panel and slab-naming rules no longer prefix ordinary
V5 requests. This reduces competing instructions while preserving an auditable
engineering fallback.

Four contract boundaries failed before the correction: exact card binding was
not required in the diagnostic output, unmatched context could generate
unbound findings, the output template seeded a level-specific diagnosis, and
the verifier could recount or move a bound card level. The prompt-focused gate
passes 145 tests. Complete AI Imaging passes 855 tests with 8 pre-existing
xfails and 3 pre-existing SWIG warnings. These tests establish prompt/transport
consistency and regression resistance; they do not establish diagnostic
accuracy. A fresh human-controlled source run and the locked
radiologist-adjudicated benchmark remain required.

## 49. Atomic anatomy screening and structure-card diagnosis (2026-09-02)

Pipeline 7.0.0 replaces the single multi-compartment Gemini screen and the
single multi-card Sol request with bounded independent work units. Five Gemini
requests screen disc, endplate/marrow, canal/neural, foraminal, and posterior
element domains concurrently. Local normalization rejects cross-domain output
and the planner now groups positive attention by both level and structure.

The focused V5 renderer uses card template 2.0.0 and manifest 3.0.0. Each card
contains only the sagittal sequences, patient-space planes, and same-slab axial
samples required for its anatomical decision. Sol receives exactly one card,
its `CARD_METADATA_JSON`, and the sanitized clinical prior. It does not receive
the whole screening-attention list. Up to three card requests run concurrently.

Response identity is enforced locally before merge. Card ID, subject level,
structure group, and attention ID must match the request; conflicting or omitted
decisions become `INDETERMINATE` and make the report review-required. Atomic
request/response/structured artifacts are stored under `.atomic_analysis` while
the aggregate stage artifacts remain backward-compatible. The default-on path
can be disabled for bounded rollback with
`AIPACS_EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE=0`.

Implementation details, failure policy, evidence profiles, verification results,
and the required frozen multi-case experiment are recorded in
`EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE_2026-09-02.md`. No clinical-accuracy claim
is made from the implementation tests.
