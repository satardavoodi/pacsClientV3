# 1 · EchoMind architecture and workflows

**Scope:** what the modules are, which backend serves which action, and what each
user-facing workflow actually calls.

---

## 1.1 Module map

```
modules/EchoMind/
    echomind_main.py          entry point for the standalone EchoMind window
    echomind_http.py          HTTP surface
    voice_transcription.py    audio capture → transcript (provider-aware)
    session_metadata.py       per-chat case record: storage + three-layer merge   ← doc 4
    reception_prefetch.py     warms the reception cache during dictation          ← doc 4
    normal_templates.py       the physician's saved normal templates
    settings_store.py         backend/model/key settings — the single read
    api_manager.py            company key validation, CENTERS registry
    llm_client.py             provider-agnostic chat_completion
    secretary_bridge.py       secretary agent integration

modules/EchoMind/viewer_chat/
    ai_chat_pages.py          the controller: buttons, modes, send, Turbo, gate profile
    ai_chat_widgets.py        composer, chat history, bubbles
    metadata_panel.py         the in-chat metadata card (CaseMetadataCard)         ← doc 4
    openai_reporter.py        COMPANY backend implementation (GapGPT direct)
    openai_parallel_backend.py  OPENAI backend implementation (user key/provider)
    turbo_prompt.py           Turbo's own prompt builder — seam + narrowing        ← doc 2
    turbo_template.py         the nine-slot prompt TEMPLATE (v2)                   ← doc 2
    turbo_modules.py          the (modality, region) registry — the only lookup
    turbo_region_modules.py   GENERATED · 21 CT region packages                    ← doc 3
    turbo_mri_modules.py      GENERATED · 19 MRI region packages                   ← doc 3
    turbo_xr_modules.py       GENERATED · 19 X-ray regions + 18 study types        ← doc 3
    turbo_us_modules.py       GENERATED · 12 US regions + 9 obstetric study types  ← doc 3
    turbo_mammo_modules.py    GENERATED · breast context + 5 study types (PREFIX)  ← doc 2
    turbo_regions.py          GENERATED · extracted spans of the shared prompt
    turbo_regions_extra.py    AUTHORED · three extra CT blocks

tools/dev/
    regen_turbo_regions.py    regenerates turbo_regions.py from the shared prompt
    gen_turbo_modules.py      regenerates turbo_region_modules.py (CT)
    gen_turbo_mri_modules.py  regenerates turbo_mri_modules.py (MRI)
    turbo_mri_authored.py     MRI pathology rules, literature-sourced (review)
    gen_turbo_xr_modules.py   regenerates turbo_xr_modules.py (radiography)
    turbo_xr_authored.py      almost the whole X-ray library (review)
    turbo_xr_subtypes.py      18 radiography study types (review)
    gen_turbo_us_modules.py   regenerates turbo_us_modules.py (ultrasound)
    turbo_us_authored.py      US pathology + the 9 obstetric study types (review)
    turbo_mammo_authored.py   the mammography prefix and its 5 study types (review)
    turbo_region_authored.py  literature-sourced region content (needs review)     ← doc 6
    sync_plugin_mirrors.py    keeps builder/plugin package/… mirrors in step
```

**Mirrors.** `builder/plugin package/packages/echomind/payload/python/modules/EchoMind/`
is a mirror of the runtime module tree. Run `tools/dev/sync_plugin_mirrors.py` after any
change under `modules/EchoMind/`. Adding a *new* file needs `--add` with the explicit
path; the sync only refreshes files it already knows about.

---

## 1.2 The three backends

There are two *implementations* and three *routes* to them.

| Route | Chosen by | Module | Endpoint | Model | Prompts |
|---|---|---|---|---|---|
| **Company** (default) | `llm_backend != "openai"` | `openai_reporter` | GapGPT, company account | `company_direct.PRIMARY_REPORT_MODEL` | `build_report_system_prompt` |
| **User OpenAI** | `llm_backend == "openai"` in Settings | `openai_parallel_backend` | user's provider via `llm_client.chat_completion` | user-selected per feature | short "twin" prompts, `build_report_system_prompt` for the report |
| **Turbo** | the ⚡ button | `openai_reporter` **always** | GapGPT, company account | `PRIMARY_REPORT_MODEL` | `build_turbo_system_prompt` → falls back to the shared builder |

The authority is two functions in `ai_chat_pages.py`, and call sites must use them rather
than re-reading the setting:

```python
def _ai_backend() -> str:            # line 244
    return "openai" if get_llm_backend() == "openai" else "company"

def _ai_module(backend=None):        # line 249
    resolved = backend or _ai_backend()
    return openai_direct if resolved == "openai" else company_direct
```

Both modules expose the same names: `reporter`, `correction`, `standardize`,
`standard_assist_search`, `translate_text_to_persian`, `translate_report`,
`BreastExpertAssistant`, `ImageQualityAnalyzer`.

### Turbo is pinned, and that is deliberate

`_on_hq_all_modality_clicked` (line 3196) sets `backend = TURBO_BACKEND` — a constant, not
a settings read. Before that was fixed, switching Send to the user's OpenAI key moved
Turbo onto the user's key, model and endpoint too. Turbo is a fixed company-controlled
workflow: hardcoded connection, hardcoded prompts, authorized centres only, company-
selected model.

Turbo additionally refuses to run without an authorized company key (validated through
`APIKeyManager`) and only from `page_mode` in `("report", "chatgpt")`.

---

## 1.3 The workflows

### Transcription

`voice_transcription.VoiceTranscriptionService`. Provider-aware: `resolve_endpoint()` and
`resolve_auth_token()` read the endpoint config when `endpoint_config_enabled()`, and fall
back to `URL_GEN_TRANSCRIPT` otherwise. The company route is "AI-PACS Server 3", an
OpenAI-compatible Whisper endpoint (`gapgpt/whisper-1`).

**Recording is also when the reception prefetch fires.** `UnifiedComposer.recordingStarted`
is emitted as the first statement of `_start_record` and is connected to
`_prefetch_reception` (ai_chat_pages.py:1370). Dictation is the only part of a session
where the network is idle and nobody is waiting — see doc 4.

### Report generation — Standard (Send)

```
composer text
  → _send_with_mode(text, "Report", modality=<menu value>)
  → _ai_module(backend).reporter(...)
  → build_report_system_prompt(modality, normal_template)
  → POST
  → _validate_report_json()
  → _normalize_report_like_payload()  → bubble
```

Modality menu: `["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY"]`
(recorded at `openai_reporter.py:192`; the branch match is on `modality_lower`).

The prompt is selected **by modality**, and each modality prompt carries every body region
internally. That is still true for this path.

### Report generation — Turbo (⚡)

Same shape, one seam:

```
_on_hq_all_modality_clicked
  → backend = TURBO_BACKEND
  → profile = _build_gate_profile()                   ← reads chat metadata (doc 4)
  → _turbo_sys = build_turbo_system_prompt(modality, normal_template, profile=profile)
  → _ai_module(backend).reporter(..., system_prompt_override=_turbo_sys)
```

`build_turbo_system_prompt` returns `None` whenever it cannot do better than the shared
builder — no profile, no regions, no module for the region, kill switch set, or any
exception. `reporter()` treats `system_prompt_override=None` as "build it yourself", so a
failure here costs the physician nothing.

**The seam is at the call site, not inside `reporter`.** `openai_reporter.reporter` serves
both Turbo (line 3301) and Send (line 8457, `company` by default). Narrowing inside
`reporter` would have silently changed the Send path too.

### Normal Template

`normal_templates.py` plus `normal_template_dialog.py`. When the physician supplies a
template, it is passed to the builder as `normal_template` and the prompt switches from
"construct the normal findings" to "use this template". Independently, the *dictation* can
request the normal report (`کد طبیعی`, `کد نرمال`, `دگنش هم کد طبیعی بیاد`, …) — that is a
prompt rule, not a template load, and it switches the register from qualified to
definitive. See doc 2 §2.4.

### Correction

`_send_report_correction()` — takes the report selected in the Correction dropdown plus
the physician's instruction, and returns the corrected report. **Not region-gated**, but
Turbo prepends an editing frame (doc 2 §2.9).

Turbo in the Correction tab routes through `_turbo_correction()`, which delegates back
to the same sender with two extra arguments: the frame, and the pinned company backend.
Before 2026-08-09 there was no correction branch in the Turbo handler at all — it fell
through to the report path, treated the edit note as a dictation, and generated a new
report while never sending the selected one.

### Standard / Standardize

`_ai_module(backend).standardize(user_msg=..., CENTER_Key=...)` — line 4096. Cleans the
raw dictation into standardised Persian/English and extracts the dictated impression and
recommendation arrays. Runs *before* the report call when used. **Not region-gated.**

### Chat / Assist / Search

- `mode == "Chat"` → `_ai_module(backend).chat(...)` (line 8449)
- `mode == "Assist"` → assistant flow (2761, 3188)
- `mode == "Search"` → `standard_assist_search` (4092)
- `BreastExpertAssistant` (8264) and `ImageQualityAnalyzer` (8336) are specialised assists

None of these are region-gated.

### Translation

`translate_text_to_persian` (5075) and `translate_report` (5079).

---

## 1.4 Which workflows the gate touches

| Workflow | Gated today | Why not |
|---|---|---|
| Turbo report, CT | **yes** | narrowing on by default, template opt-in |
| Turbo report, MRI | **template path only** | narrowing is CT-only; with v2 off an MRI report is byte-identical to today |
| Turbo report, radiography | **template path only** | same seam as MRI; adds a `projection` section |
| Turbo report, ultrasound | **template + study types** | obstetric gates on subtype as well as region |
| Turbo report, mammography | **prefix only** | its JSON schema is regex-locked; the template would emit the wrong shape |
| **Turbo correction** | **yes — editing frame** | prepended to the shared correction prompt (doc 2 §2.9) |
| Send report | no | deliberately — the seam is Turbo-only until v2 is evaluated |
| Correction | no | operates on a finished report, not on region knowledge |
| Standardize | no | operates on raw dictation before any region is known |
| Chat / Assist / Search | no | not report generation |

---

## 1.5 The output contract

Every report path returns one JSON object. `_validate_report_json` requires
`Report Title`, `Pathological Findings`, `Normal Findings`; `Impression` and
`Recommendations` are inserted as `null` when absent. Mammography has its own schema
(`Breast Composition`, `Normal Findings{R,L}`, `Axillary Evaluation`, `BI-RADS Category{R,L}`)
and **no** Impression/Recommendations keys — a dictated impression is preserved inside
Pathological Findings there rather than promoted to a key that does not exist.

**The preservation rule, unchanged and load-bearing across every path:** the model must
never independently generate an impression, recommendation, suggestion, follow-up or
clinical correlation — and must always preserve one the physician dictated, never
deleting, weakening or softening it.

---

## 1.6 Kill switches

| Variable | Default | Effect |
|---|---|---|
| `AIPACS_TURBO_PROMPT` | on | `=0` reverts everything Turbo-specific — the template, the mammography prefix and the correction frame |
| `AIPACS_TURBO_PROMPT_V2` | **on** | `=0` reverts to narrowing (CT) or the shared prompt |

Both are read at call time, so they take effect on the next report.
