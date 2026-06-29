# EchoMind — Prompt & Server-Communication Map (as-built review)

**Date:** 2026-06-28
**Scope:** `modules/EchoMind/` (the module the request calls "EcoMind")
**Type:** Read-only mapping / documentation. **No prompts or code were changed.**
**Purpose:** Establish a clear, shared understanding of how EchoMind builds prompts and
where every request goes, *before* deciding what to modify/optimize/move out of hardcoded logic.

> Note on naming: the module is spelled **EchoMind** in the codebase
> (`modules/EchoMind/`). "EcoMind" in the request maps to this module.

---

## 0. TL;DR (the things that matter most)

1. **There are TWO subsystems** under `modules/EchoMind/`:
   - **`viewer_chat/`** — the AI **report / chat** UI (radiology report generation, standardization, chat, assistant, translation, image-quality, breast assistant).
   - **`secretary/`** — the **voice-command agent** that controls the app ("open patient X", "download this", "show MPR") via a two-phase LLM router/planner.

2. **There are TWO network destinations** (this is the core of questions 5–9):
   - **Company AI-PACS AI backend** — `http://81.16.117.196:8082` (HTTP, plain, no TLS). Endpoints `/chat`, `/generate_report`, `/generate_assistant`, `/generate_transcript`, `/search`. **The prompt is built on the server here — it is NOT visible in the client code.**
   - **GapGPT** — `https://api.gapgpt.app/v1/chat/completions` (OpenAI-compatible proxy). **The prompt is built in the client** (the big hardcoded prompts you see in `openai_reporter.py`). Optionally swappable to **OpenAI** (`https://api.openai.com/v1`) when the user picks the "openai" backend.

3. **The "Normal vs Turbo" report distinction is exactly the two destinations:**
   - **Normal report** → company backend `/generate_report` (server builds the prompt).
   - **Turbo report** ("⚡Turbo Mode" button) → client builds the full modality prompt and calls GapGPT/OpenAI **directly**.

4. **A backend toggle (`llm_backend`: `company` | `openai`)** decides, for the *client-side* flows, whether requests go to **GapGPT (company)** or **the user's own OpenAI key**. Default = `company`.

5. **A per-center registry of secret GapGPT keys is hardcoded in the client** (`api_manager.py`). Center validation is **100% local** — there is no server round-trip to validate a license key. (See §8 — Security observations.)

6. **A configurable prompt-override layer exists** (`prompt_*` fields in `echomind_settings.json`), but it is **only applied when the backend is `openai`**, and it is **prepended** to the hardcoded base prompts. On the default `company` backend these overrides are ignored.

---

## 1. Module structure

```
modules/EchoMind/
├── ai_chat_config.py        ← endpoints (AI_BASE + GapGPT URL), UI tokens   [SHARED CONFIG]
├── settings_store.py        ← echomind_settings.json read/write, backend toggle, model map
├── api_manager.py           ← HARDCODED per-center registry (gapgpt keys + license keys)
├── llm_client.py            ← provider-aware transport (company GapGPT | OpenAI)
├── viewer_chat/             ← AI REPORT / CHAT subsystem
│   ├── ai_chat_pages.py     ← main UI; Send/Turbo/Standardize wiring (~7400 lines)
│   ├── ai_chat_api.py       ← thin HTTP client for /chat
│   ├── openai_reporter.py   ← LEGACY engine: GapGPT-direct + giant hardcoded modality prompts
│   ├── openai_parallel_backend.py ← lean engine: provider-aware (used when backend=openai)
│   ├── ai_chat_helpers.py / ai_chat_widgets.py / ai_chat_viewer.py / ai_chat_app.py
└── secretary/               ← VOICE-COMMAND AGENT subsystem
    ├── config.py            ← secretary model + prompt-file paths + routing-v2 flag
    ├── prompts/             ← system prompts as .txt files (router + planner)
    │   ├── router_phase1_prompt.txt      (legacy Phase-1 router)
    │   ├── router_phase1_prompt_v2.txt   (verb+object routing, DEFAULT-ON)
    │   ├── agent_phase2_prompt.txt       (ACTIVE Phase-2 action planner)
    │   └── secretary_action_prompt.txt   (LEGACY single-phase template, superseded)
    ├── parser_llm.py        ← single-phase LLM parse (legacy/fallback path)
    ├── brain/router.py      ← Phase 1: choose module(s)
    ├── brain/agent.py       ← Phase 2: produce executable action plan
    ├── stt/router.py        ← STT provider selection (native | openai | v2t)
    └── stt/providers/       ← native_irannobat (AI-PACS backend) | openai_transcribe | v2t_google
```

---

## 2. Destinations & endpoints (questions 5, 6, 7)

| # | Destination | URL | Defined in | Prompt built where | Used by |
|---|-------------|-----|-----------|--------------------|---------|
| D1 | **Company AI-PACS AI backend** | `http://81.16.117.196:8082` (`/chat`, `/generate_report`, `/generate_assistant`, `/generate_transcript`, `/search`, `/health`, `/status`, `/sessions`, `/session`, `/export_all`) | `ai_chat_config.py:23-33` (`AI_BASE`, `URL_*`) | **Server-side (opaque)** | `viewer_chat/ai_chat_pages.py` Chat/Report/Assistant/Search; native STT |
| D2 | **GapGPT** (OpenAI-compatible proxy) | `https://api.gapgpt.app/v1/chat/completions` | `ai_chat_config.py:47` (`GAPGPT_API_URL`); also hardcoded inline in `openai_reporter.py` | **Client-side** | `openai_reporter.py` (Turbo/standardize/etc.); `llm_client.chat_completion`/`gapgpt_chat` (company backend); whole `secretary/` brain |
| D3 | **OpenAI** (direct) | `{openai_base_url}/chat/completions`, default `https://api.openai.com/v1` | `llm_client.py:148-156`, `settings_store.py` | **Client-side** | Same client-side flows as D2, but only when `llm_backend == "openai"` |
| D4 | **OpenAI audio** | `{base_url}/audio/transcriptions` | `secretary/stt/providers/openai_transcribe.py:39` | n/a (audio upload) | Secretary STT when route = `openai` |
| D5 | **Google Web Speech** | via `speech_recognition.recognize_google` (`fa-IR`) | `secretary/stt/providers/v2t_google.py:45` | n/a (audio) | Secretary STT when route = `v2t`, and as native fallback |

**How the destination is chosen:**
- For **viewer_chat "Send" modes** (Chat / Report / Assistant / Search) → always **D1 (company backend)**. The server decides what to send to ChatGPT.
- For **viewer_chat Turbo + Standardize + translate + image-quality + breast** → **D2/D3 (direct)**. The client builds the prompt; `llm_backend` picks GapGPT vs OpenAI.
- For the **secretary brain** (router + planner + parser) → **D2/D3 (direct)** via `llm_client`.
- For **STT** → `secretary/stt/router.py` picks D? by the `secretary_stt_provider` setting (`native`=D1, `openai`=D4, `v2t`=D5), with a fallback chain. The viewer-chat voice button uses **D1 `/generate_transcript`** directly.

**Transport mechanics** (`llm_client.py`):
- Same OpenAI chat-completions JSON shape for D2 and D3: `{model, messages, temperature, max_tokens, [reasoning_effort]}`.
- Auth: `Authorization: Bearer <key>`. For D2 the key is the **center's hardcoded `gapgpt_key`**; for D3 it is the **user's OpenAI key**.
- Optional SOCKS5 proxy (`connection_type: socks5`, `proxy_port` 2080/2081/2082) applied to all `requests` calls.
- Response parsing trims a trailing partial sentence **only** when `finish_reason == "length"`.

---

## 3. The backend toggle & model map (question config)

`echomind_settings.json` (roaming config) — current values in repo:

| Key | Value | Meaning |
|-----|-------|---------|
| `llm_backend` | `company` | `company` → GapGPT + hardcoded center key; `openai` → user OpenAI key |
| `api_key` | `Ai-pacs/razi245608` | the **center license key** (maps to RAZI center in `api_manager.py`) |
| `openai_*` | (empty / defaults) | user OpenAI key, base url, org, project |
| `openai_text_model` | `gpt-5-mini` | chat/standardize/search/translate model (openai backend) |
| `openai_report_model` | `gpt-5.4` | report/correction/breast model (openai backend) |
| `openai_vision_model` | `gpt-5.4` | image-quality model |
| `openai_transcription_model` | `gpt-4o-transcribe` | OpenAI STT model |
| `openai_secretary_model` | `gpt-5-mini` | secretary brain model (openai backend) |
| `prompt_report_generation` … `prompt_image_artifact` | "" (empty) | optional prompt overrides (openai backend only) |
| `secretary_stt_provider` | `native` | STT route: native (AI-PACS backend) |
| `connection_type` / `proxy_port` | `direct` / `2080` | optional SOCKS5 proxy |

**Model defaults when `backend == company`:** the secretary brain uses `SECRETARY_LLM_MODEL = "gpt-5.2"` (`secretary/config.py:22`); the llm_client fallback model is `GAPGPT_DEFAULT_MODEL = "gpt-5.2"` (`ai_chat_config.py:48`); the legacy reporter is called with `model="gpt-4.1-mini"` from the Turbo path. (These model names come straight from config — not verified against the live GapGPT catalog.)

Feature→model mapping for the openai backend lives in `settings_store.get_openai_model_for_feature()` (`settings_store.py:125-148`).

---

## 4. PROMPT CATALOG (questions 1–4)

Legend — **Type:** `HARD` = hardcoded string in Python/txt; `DYN` = assembled at runtime from variables; `SERVER` = built on the company backend (not in client code); `OVERRIDE` = optional user-config prefix.

### 4A. viewer_chat — client-side prompts (destination = GapGPT/OpenAI, D2/D3)

These live in **`viewer_chat/openai_reporter.py`** (legacy, GapGPT-direct, the *detailed* prompts) and mirrored as short prompts in **`viewer_chat/openai_parallel_backend.py`** (used when `backend == openai`).

| Prompt / purpose | Where defined | Type | Input variables | Destination | Endpoint | Response handling | Appears in UI |
|---|---|---|---|---|---|---|---|
| **Report generation (Turbo)** — structured radiology report JSON (`Report Title`, `Pathological Findings`, `Normal Findings`, optional `Impression`/`Recommendations`), with per-modality logic | `openai_reporter.py:131-1315` (`reporter()`); short twin `openai_parallel_backend.py:77-104` | HARD (giant, per-modality) + DYN (modality, template) + OVERRIDE `report_generation` (openai only) | `user_msg`, `modality`, `normal_template`, `CENTER_Key`, `model` | D2 (or D3) | `requests.post(GapGPT)`; returns `{content, usage}`; client extracts JSON, filters to report keys, renders | Turbo bubble → report HTML card |
| **CT modality logic** | `openai_reporter.py:171-376` | HARD | (selected when `modality=="ct"`) | D2/D3 | same | embedded in system prompt | (report) |
| **MRI modality logic** (+ 4 worked examples) | `openai_reporter.py:377-575` | HARD | `modality=="mri"` | D2/D3 | same | embedded | (report) |
| **Ultrasound / OB-GYN logic** | `openai_reporter.py:576-~900` | HARD | `modality in {sonography,ultrasound}` | D2/D3 | same | embedded | (report) |
| **Other modalities** (mammography, radiology/x-ray, generic) | `openai_reporter.py` (continues to ~1257) | HARD | `modality` | D2/D3 | same | embedded | (report) |
| **Normal-template override logic** | `openai_reporter.py:142-162` | DYN (branch on `normal_template`) | `normal_template` | D2/D3 | same | embedded | (report) |
| **English-only + JSON + `<\|end\|>` guard** | `openai_reporter.py:1259-1268` | HARD | — | D2/D3 | same | output must end with `<\|end\|>`; parsed downstream | (report) |
| **Chat (clinical)** | `openai_reporter.py:1319+` (`chat()`); twin `openai_parallel_backend.py:62-74` ("You are EchoMind medical chat…") | HARD | `user_msg`, `model` | D2/D3 | same | `{content,usage}` → bubble | Turbo/chat path |
| **Correction / edit report** | `openai_reporter.py:2344-2501`; twin `openai_parallel_backend.py:232-254` | HARD | `user_report`, `correction_note` | D2/D3 | same | full corrected JSON | report edit |
| **Standardize (EN+FA)** | `openai_reporter.py:2115-2332`; twin `openai_parallel_backend.py:214-229` | HARD | `user_msg` | D2/D3 | same | returns `standardize_output_english` / `_persian` JSON | Standard tab (EN/FA) |
| **standard_assist_search** | `openai_reporter.py:2011-2101`; twin `:196-211` | HARD | `user_msg` | D2/D3 | same | structured JSON | Assist menu |
| **Translate text → Persian** | `openai_reporter.py:1745-1802`; twin `:158-175` | HARD | `user_msg` | D2/D3 | same | plain text | Persian toggle on a bubble |
| **Translate report → Persian (keep JSON keys)** | `openai_reporter.py:1814-2000`; twin `:178-193` | HARD | `user_msg` (report JSON) | D2/D3 | same | JSON same-keys | Persian report |
| **Image Quality Analyzer (vision)** | `openai_reporter.py:1465-1528`; twin `:107-134` | HARD + OVERRIDE `image_artifact` | `user_msg`, `image_path` (base64) | D2/D3 (vision model) | same (image_url content) | artifact analysis bubble |
| **Breast Expert Assistant** | `openai_reporter.py:1539-1733`; twin `:137-155` | HARD + OVERRIDE `breast_assistant` | `user_msg` | D2/D3 (report model) | same | assistant bubble |

> The `openai_parallel_backend.py` twins are deliberately short/generic and rely on the
> `prompt_*` **overrides** to carry detail. The legacy `openai_reporter.py` carries the full
> radiology knowledge **inline**. Whichever module is used is chosen at the call site by
> `backend == "openai"` (see §6).

### 4B. viewer_chat — server-side prompts (destination = AI-PACS backend, D1)

For these flows **the client sends only data; the prompt is constructed on the company server.**
The client code contains **no system prompt** for them.

| Flow / purpose | Where the request is built | Type | Payload sent | Destination | Endpoint | Response handling | Appears in UI |
|---|---|---|---|---|---|---|---|
| **Chat (Normal)** | `ai_chat_pages.py:5486-5499` | SERVER | `{session_id, user_message, images}` | D1 | `POST /chat` | `handle_chat_response()` | chat bubble |
| **Report (Normal)** | `ai_chat_pages.py:5538-5575` | SERVER | `{text, modality, normal_template, session_id, images, gpu_id}` | D1 | `POST /generate_report` | normalize → report HTML card | report bubble |
| **Assistant (Normal)** | `ai_chat_pages.py:5615-5630` | SERVER | `{text, session_id}` | D1 | `POST /generate_assistant` | render assistant HTML | assistant bubble |
| **Search** | `ai_chat_pages.py:~5660+` | SERVER | search payload | D1 | `POST /search` | unwrap `response`/`result` JSON | search bubble |
| **Voice transcription (viewer chat)** | `ai_chat_pages.py:117, 2572, 5262` | SERVER | multipart audio + `quality_mode` | D1 | `POST /generate_transcript` | `transcript` → Transcribe tab | composer transcript |

> The `gpu_id` field on `/generate_report` indicates the company backend runs **local GPU
> models** (its own STT and possibly its own report model), not purely a passthrough to ChatGPT.
> Exactly what the server forwards to ChatGPT vs. computes locally is **not determinable from the
> client** — it is server-side and opaque (this is the honest answer to question 7 for the Normal flows).

### 4C. secretary — command-agent prompts (destination = GapGPT/OpenAI, D2/D3)

| Prompt / purpose | Where defined | Type | Input variables | Destination | Endpoint | Response handling | Appears in UI |
|---|---|---|---|---|---|---|---|
| **Phase 1 — Module Router (v2, default)** verb+object → module list | `secretary/prompts/router_phase1_prompt_v2.txt` (selected by `config.get_phase1_prompt_file()`, flag `AIPACS_SECRETARY_ROUTING_V2` default-on) | HARD (txt) + DYN user msg + OVERRIDE `secretary_routing` (openai only) | `user_text`, `language`, `catalog_text`, `available_module_ids` | D2/D3 | `gapgpt_chat` (`brain/router.py:176`), model `gpt-5.2`/secretary, `temp 0`, `max_tokens 256` | parse `{modules, reason}` JSON | (no direct UI; drives next phase) |
| **Phase 1 — Module Router (legacy)** | `secretary/prompts/router_phase1_prompt.txt` | HARD (txt) | same | D2/D3 | same | same | used when routing-v2 flag off |
| **Phase 2 — Action Planner** spoken cmd → ONE executable JSON action (or multi-step plan) | `secretary/prompts/agent_phase2_prompt.txt` (loaded by `brain/agent.py`) | HARD (txt) + DYN context + OVERRIDE `secretary_action` (openai only) | `user_text`, `language`, `module_docs` (Document 2), `memory_context`, **computed date context** | D2/D3 | `gapgpt_chat` (`brain/agent.py:462`), `temp 0`, `max_tokens 512` | `_parse_action_plan` → `_normalize_multistep` → executor | confirmation dialog / executed action |
| **Single-phase parser (legacy/fallback)** | `secretary/parser_llm.py:150-172` builds from `secretary_action_prompt.txt` | HARD (txt) + DYN (`{{LANGUAGE}}`, `{{MODULE_MAP}}`, `{{USER_TEXT}}`) | `text`, `language`, module map | D2/D3 | `gapgpt_chat` (`parser_llm.py:99`) | strict action JSON | executed action |
| **Module catalog (Document 1)** | `secretary/catalog/catalog.yaml` + `catalog/modules/*.md` | HARD (data, not a prompt) | — | injected into Phase-1/2 user messages | — | — | — |
| **STT transcript cleanup** (openai STT route only) | `stt/providers/openai_transcribe.py:42,75-89` uses `prompt_transcript_cleanup` | OVERRIDE (config) | raw transcript | D3 | `chat_completion` cleanup pass | replaces transcript | secretary transcript |

> Phase-2 prompt is **dynamic** in an important way: it injects an **authoritative computed
> date block** (today/yesterday/2-3 days ago/this week) so relative dates ("today's MRIs")
> resolve correctly, plus a **conversation-memory** block so "open the 5th patient" resolves to
> a real numeric ID. The base system prompt itself is a static `.txt`.

---

## 5. Flow-by-flow traces (the required review areas)

### 5.1 Voice transcription
Two independent transcription paths exist:

- **Secretary voice command** → `stt/router.py` selects a provider by `secretary_stt_provider`:
  - `native` (default) → `NativeIrannobatProvider` → `POST /generate_transcript` on **D1** (company backend, multipart audio). Returns `transcript` + `session_id`.
  - `openai` → `OpenAITranscribeProvider` → `POST {base}/audio/transcriptions` on **D4** (OpenAI), model `gpt-4o-transcribe`; optional cleanup pass via `chat_completion`.
  - `v2t` → `V2tGoogleProvider` → Google Web Speech (`fa-IR`), chunked, local library.
  - **Fallback chain:** if primary returns empty and `secretary_stt_fallback` is true, it retries with `v2t` (or `native`).
- **Viewer-chat voice button** → `ai_chat_pages.py:117` → `POST /generate_transcript` on **D1** directly (no provider router). Transcript lands in the composer's Transcribe tab.

### 5.2 Standardization flow
- Trigger: composer "Standardize" → `ai_chat_pages._standardize_now()` (`:3469`).
- Engine selection (`:3626`): `fn = openai_direct.standardize if backend=="openai" else standardize`.
  → **company** = `openai_reporter.standardize()` (hardcoded big prompt, **GapGPT-direct D2**);
  → **openai** = `openai_parallel_backend.standardize()` (short prompt + override, **D3**).
- Output: JSON with `standardize_output_english` / `standardize_output_persian`; both EN/FA shown in the Standard tab; sets `composer._is_standardized = True`.

### 5.3 Normal report generation
- Trigger: Send button in **Report** mode → `_send_with_mode(text, "Report")` (`:5530`).
- Builds `{text, modality, normal_template, session_id, images, gpu_id}` and `POST /generate_report` on **D1 (company backend)**.
- **Prompt is server-side.** Response normalized (`_normalize_report_like_payload`) → `_render_kv_report_html` → report bubble. Stores `_pending_report_raw_en` for later Persian translation.

### 5.4 Turbo report generation
- Trigger: **⚡Turbo Mode** button → `_on_hq_all_modality_clicked()` (`:2861`).
- Gathers `user_msg` (from the active tab), persisted `modality`, optional `normal_template`.
- Engine selection (`:2921`): `reporter_fn = openai_direct.reporter if backend=="openai" else reporter`.
  → **company** = `openai_reporter.reporter()` (full hardcoded modality prompt, **GapGPT-direct D2**, model `gpt-4.1-mini`);
  → **openai** = `openai_parallel_backend.reporter()` (**D3**, report model e.g. `gpt-5.4`).
- **Prompt is client-side** (the big §4A prompt). Response → same normalize/filter/render as Normal, but bubble labelled "You (⚡Turbo Mode)".
- **In short: Turbo = bypass the company server and generate the report directly from the client using the embedded modality prompt.** That is why the detailed prompts live in the client.

### 5.5 Chat / message flow
- Send in **Chat** mode → `_send_with_mode(text, "Chat")` → `POST /chat` on **D1** with `{session_id, user_message, images}`. Server-side prompt. Multi-turn via `session_id`.
- (A client-side `chat()` exists in both reporter modules for the Turbo/direct path, but the main "Chat" Send button uses the company backend.)

### 5.6 Assistant / Search flow
- **Assistant** → `POST /generate_assistant` (**D1**, server prompt) → assistant HTML.
- **Search** → `POST /search` (**D1**, server prompt) → unwrap `response`/`result`.
- **Assist menu** (client-side) can also call `standard_assist_search()` direct to GapGPT.

### 5.7 Secretary command flow (voice → action)
1. **STT** (§5.1) → text.
2. **Phase 1 router** (`brain/router.py`) → GapGPT/OpenAI → `{modules:[...]}`.
3. **Phase 2 planner** (`brain/agent.py`) → injects module docs + date + memory → GapGPT/OpenAI → one JSON action (or multi-step plan).
4. **Validation / confirmation / execution** are **100% local** — `validator.py`, `confirm.py`, `executor.py`, and the `adapters/*` call into the real app (home/viewer/download/etc.). Side-effect actions (`open_patient`, `download_patient`) require confirmation.
- The LLM is used **only** to interpret intent. It never touches DICOM data; execution runs the production code paths (so the app's cross-patient / multi-study guards still apply).

### 5.8 Reception / report submission
- `ai_chat_pages._send_to_reception()` (`:3937`) routes a finished report bubble back to a patient (reception) — this is an **internal app handoff**, not an LLM call. (Surfaced here because the request asked about it; it does not construct prompts or call ChatGPT.)

---

## 6. Local vs backend responsibility split (questions 8, 9)

**Handled locally inside the app (client):**
- All UI, tab/composer logic, bubble rendering, report HTML, EN/FA toggling.
- **Center validation & key resolution** — fully local from the hardcoded registry (`api_manager.py`).
- **Client-side prompt construction** for: Turbo report, standardize, correction, translate, image-quality, breast assistant, **and the entire secretary brain** (router + planner prompts).
- **Secretary execution** (validator/confirm/executor/adapters) — entirely local.
- Token-usage logging (`api_usage.json` + SQLite); prompts/history are **not** stored.
- Optional Google STT (`v2t`) and the OpenAI STT cleanup pass.

**Handled by a backend:**
- **Company AI-PACS backend (D1, `81.16.117.196:8082`)** builds the prompt server-side for **Normal Chat/Report/Assistant/Search** and runs **native STT** (`/generate_transcript`, with `gpu_id` → server GPU models). What it forwards to ChatGPT vs computes locally is **not visible from the client.**
- **GapGPT (D2)** / **OpenAI (D3/D4)** are the actual LLM/transcription providers for all client-side flows. GapGPT is an OpenAI-compatible proxy reached with the center's hardcoded key.

**"How does the server decide what to send to ChatGPT?" (Q7):**
- For **client-side flows**, the *client* decides — it assembles the full system+user messages (§4A/§4C) and posts them to GapGPT/OpenAI. There is no server arbitration.
- For **Normal viewer_chat flows**, the **company backend decides** — the decision and prompt live on `81.16.117.196:8082` and are **out of scope of the client repo** (would require backend access to document).

---

## 7. Configurable prompt-override system (important for "move out of hardcoded logic")

`echomind_settings.json` exposes 6 override slots, read via `settings_store.get_prompt_settings()`:
`prompt_report_generation`, `prompt_breast_assistant`, `prompt_secretary_routing`,
`prompt_secretary_action`, `prompt_transcript_cleanup`, `prompt_image_artifact`.

Current behavior (verified in code):
- These overrides are **only applied when `llm_backend == "openai"`** (e.g. `openai_reporter._feature_prompt()` returns "" unless openai; `router.py:_system_prompt()` and `parser_llm.py:169` gate on `get_llm_backend()=="openai"`).
- When applied, the override is **prepended** to the hardcoded base prompt (`f"{extra}\n\n{base}"`), not replacing it.
- On the **default `company` backend, every override is ignored** → the hardcoded prompts in `openai_reporter.py` and the `secretary/prompts/*.txt` files are authoritative.

Implication for the next step: there are **two** "hardcoded prompt" surfaces to consider —
(a) the **client** prompts in `openai_reporter.py` (huge) + `secretary/prompts/*.txt` (clean, already externalized to txt), and
(b) the **server** prompts behind `/generate_report`, `/chat`, `/generate_assistant`, `/search` (not in this repo).
Externalizing/optimizing (a) is feasible here; (b) requires backend coordination.

---

## 8. Security & correctness observations (flagged, not changed)

> These are observations from the mapping. **No changes were made.** They matter for any
> "optimize / move prompts" decision.

1. **Hardcoded secrets in client code.** `api_manager.py` embeds, in plaintext, a **GapGPT
   secret key (`sk-…`) per center** plus each center's **license key**, shipped to every
   client build. Anyone with the binary/source can extract all centers' LLM keys. Center
   "validation" is a local dict lookup — no server check. (Reproduced keys are intentionally
   omitted from this report.) Worth a dedicated remediation discussion (server-side key
   brokering) separate from the prompt work.
2. **Plain HTTP to the AI backend.** `AI_BASE` is `http://81.16.117.196:8082` (no TLS). Report
   text, transcripts, and images traverse the network unencrypted. PHI/PII exposure risk.
3. **Two divergent report engines.** `openai_reporter.py` (detailed, GapGPT-direct) and
   `openai_parallel_backend.py` (short, provider-aware) implement the **same function names**
   with **different prompt quality**. Switching backend silently changes prompt behavior. If you
   consolidate prompts, decide which engine is canonical.
4. **Model names are config-declared, not verified.** `gpt-5.4`, `gpt-5.2`, `gpt-5-mini`,
   `gpt-4.1-mini`, `gpt-4o-transcribe` come from config/defaults; this review did not confirm
   they exist on the live GapGPT/OpenAI catalog.
5. **Prompt overrides are openai-only.** On the default `company` backend the Settings → EchoMind
   prompt fields have **no effect**, which can surprise an operator who edits them.

---

## 9. Open questions to resolve before editing prompts

1. **Server-side prompts (D1):** the Normal Chat/Report/Assistant/Search prompts are on
   `81.16.117.196:8082`. Do we have access to that backend's source to map/optimize those, or is
   only the client (Turbo/secretary) in scope?
2. **Canonical engine:** should `openai_reporter.py` (detailed) or `openai_parallel_backend.py`
   (override-driven) be the single source of report prompts going forward?
3. **Externalization target:** move the big client prompts from Python into the same
   `prompts/*.txt` pattern the secretary already uses (clean, reviewable) — and make overrides
   apply on the `company` backend too?
4. **Turbo vs Normal:** is Turbo meant to remain a separate client-side engine, or converge with
   the server `/generate_report`?

---

### Appendix — key source references

- Endpoints / GapGPT URL: `modules/EchoMind/ai_chat_config.py:23-49`
- Transport + provider toggle: `modules/EchoMind/llm_client.py` (`chat_completion` :363, `gapgpt_chat` :460)
- Hardcoded center registry: `modules/EchoMind/api_manager.py:34-105`
- Settings + model map + prompt overrides: `modules/EchoMind/settings_store.py`
- Legacy report engine + giant prompts: `modules/EchoMind/viewer_chat/openai_reporter.py`
- Provider-aware report engine: `modules/EchoMind/viewer_chat/openai_parallel_backend.py`
- Send/Turbo/Standardize wiring: `modules/EchoMind/viewer_chat/ai_chat_pages.py:30-31, 2861-2928, 3469-3681, 5403-5660`
- Secretary brain: `secretary/brain/router.py`, `secretary/brain/agent.py`, `secretary/parser_llm.py`, `secretary/config.py`
- Secretary prompts: `secretary/prompts/*.txt`
- STT: `secretary/stt/router.py` + `secretary/stt/providers/*`
