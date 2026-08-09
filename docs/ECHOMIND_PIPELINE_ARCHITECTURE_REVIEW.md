# EchoMind Module — Three-Pipeline Architecture Review

**Date:** 2026-08-05 · **Scope:** EchoMind proper (`modules/EchoMind/*.py`, `modules/EchoMind/viewer_chat/**`, `settings_ui/echomind_settings.py`). **Secretary excluded.**
**Status:** review only — **no code changed.** Per the project rule *"never start with refactoring"*, the defects below should be fixed before any reorganisation, and the reorganisation itself needs your sign-off (§6).

---

# 1. VERDICT

| Your intended pipeline | Implemented? |
|---|---|
| **1 · Send → AI-PACS backend** (server prompt, client sends data only) | ✅ **Correct.** Clean, no leakage. |
| **2 · Turbo** (local prompt, *our* model/provider, not the user's) | ⚠️ **Half correct.** The prompt is local ✅ — but the model and the prompt are both overridable by end-user settings ❌. |
| **3 · Fully user-configured OpenAI** (user prompt, key, model — independent of Turbo) | ❌ **Not implemented as a pipeline.** |

### The core finding

**Pipelines 2 and 3 are not two pipelines. They are one code path with a transport switch.**

There is exactly one report function — `reporter()` — and `llm_backend ∈ {company, openai}` only decides *who answers it*. `_ai_module()` picks `openai_reporter` (GapGPT) or `openai_parallel_backend` (OpenAI); both then call the **same** `build_report_system_prompt()`.

Consequences that follow directly from that:

- Turbo **cannot** run on an OpenAI model while the user's own OpenAI mode also exists — selecting `llm_backend = "openai"` moves *Turbo itself* onto the user's key, model and prompt.
- Pipeline 3 **cannot** be "user prompt only" — the user's prompt is *prepended* to Turbo's ~39 KB clinical prompt, never substituted.
- There is no place to put "the Turbo LLM we configure", because Turbo has no provider/model/credential of its own. It borrows whichever backend the user selected.

Everything in §3 is a symptom of that one structural gap.

---

# 2. YOUR MIXED-PATH CHECKLIST, ANSWERED

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | Turbo accidentally uses a **server-side prompt** | ✅ **No** | `_on_hq_all_modality_clicked:3163` → `reporter()` → `build_report_system_prompt`. Never touches `URL_GEN_REPORT`. |
| 2 | Send/AI-PACS accidentally sends the **local Turbo prompt** | ✅ **No** | `_send_with_mode:6330-6358` payload is exactly `{text, modality, normal_template, session_id, images, gpu_id}`. No prompt key. |
| 3 | User-configured OpenAI accidentally uses a **hardcoded Turbo prompt** | ❌ **YES — confirmed** | `openai_parallel_backend.py:149-154`. See §3.1. |
| 4 | Different tabs implement **duplicate LLM connection logic** | ❌ **YES** | 24 distinct request-construction sites; `ChatGPTPage` re-implements the whole send handler. See §3.4. |
| 5 | Transcription settings **mixed with** report settings | ❌ **YES** | 7 shared/overloaded keys. See §3.5. |
| 6 | Chat / Report / Assist use **inconsistent backend routing** | ❌ **YES — the worst offender** | See §3.6. |
| 7 | API keys read from **multiple unrelated locations** | ❌ **YES** | 19 credential read sites, 5 distinct authorities. See §3.7. |
| 8 | Model selection **duplicated across files** | ❌ **YES** | 5 competing authorities. See §3.8. |

---

# 3. FINDINGS

## 3.1 · Pipeline 3 is running Turbo's prompt — CONFIRMED

`viewer_chat/openai_parallel_backend.py:43-56` — the flag, **default ON**:

```python
_ENV_PROMPT_PARITY = "AIPACS_ECHOMIND_BACKEND_PROMPT_PARITY"

def _prompt_parity_enabled() -> bool:
    raw = os.environ.get(_ENV_PROMPT_PARITY)
    if raw is None:
        return True          # ← default
```

`:149-154` — its only call site:

```python
if _prompt_parity_enabled():
    system_prompt = build_report_system_prompt(modality, normal_template)
    result = _call(
        feature_name="report",
        system_prompt=_compose_prompt(system_prompt, "report_generation"),
```

`:66-71` — the composition rule:

```python
def _compose_prompt(base_prompt, feature_name=""):
    extra = _feature_prompt(feature_name) if feature_name else ""
    if not extra:
        return base_prompt
    return f"{extra}\n\n{base_prompt}"      # PREPEND — never replace
```

**What actually goes to the user's OpenAI key today:**

```
[user's prompt_report_generation]  +  \n\n  +  [our ~39 KB Turbo clinical prompt]
```

Your specification is `User Prompt + Text + User API Configuration → OpenAI`. What ships is `User Prompt + OUR Prompt + Text → OpenAI`. Pipeline 3 is not independent from Pipeline 2 — it *is* Pipeline 2 with the user's key.

**Note this is currently load-bearing.** Turning parity off (`=0`) does not give you Pipeline 3 — it falls back to `_legacy_reporter`, a *different* hardcoded generic prompt, whose own comment warns it "deletes clinical content". So today there is no configuration in which a user's prompt runs alone.

## 3.2 · Which prompts a user can actually influence

Only **3 of 6** Settings prompt fields ever reach an LLM, and only on the OpenAI backend:

| Function | User prompt honoured? | Key |
|---|---|---|
| `reporter()` | ✅ prepended | `prompt_report_generation` |
| `ImageQualityAnalyzer()` | ✅ prepended | `prompt_image_artifact` |
| `BreastExpertAssistant()` | ✅ prepended | `prompt_breast_assistant` |
| `correction()`, `standardize()`, `translate_report()`, `translate_text_to_persian()`, `chat()`, `standard_assist_search()` | ❌ never | — |

**On the company backend, none of them work at all.** `openai_reporter._compose_prompt` (`:133`), `_feature_prompt` (`:124`) and `_is_openai_backend` (`:120`) are defined and have **zero call sites** — a whole dead prompt-override subsystem. The Settings dialog gives no hint that these fields are inert.

## 3.3 · Live functional defects found during the review

These are bugs, not architecture opinions, and they are independent of any refactor.

**(a) `chat()` answers with a corrector.** `openai_reporter.py:2444-2470` — the system message for the *chat* function is the report-correction editor prompt ("You are a medical report editor… USER_REPORT then CORRECTION_NOTE"). **Every company-backend ChatGPT chat message is being answered by a corrector.**

**(b) The Correction tab is silently inert on the ChatGPT page.** `ChatGPTPage` overrides `_on_send_clicked` (`:7925`) without re-adding the parent's correction-tab dispatch (`:3062-3075`), so `ChatGPTPage._send_correction` (`:7860`) has no caller. The user types a correction note, presses send, and gets an ordinary report/chat turn.

**(c) The ChatGPT model combo overrides the primary report model — on both backends.** `GPT_MODELS` (`:7474-7481`) lists OpenAI names only (`gpt-5.4 … gpt-4o-mini`); `gpt-5.6-terra` is absent. `model = self._current_model` (`:8177`) is sent verbatim as `payload["model"]` to **GapGPT**. `_default_model_for_mode` (`:7633`) resolves through `get_openai_model_for_feature(...)` **even on the company backend**, so OpenAI model settings leak into GapGPT requests.

**(d) The Assist tile ignores `llm_backend`.** The divert at `ai_chat_viewer.py:160-168` covers only `{"Chat", "Report"}`. With `llm_backend = "openai"` selected — and possibly no company credential at all — **Assist still posts to the company server.**

**(e) Settings shows defaults the store does not apply.** `echomind_settings.py:910-916` falls back to `report_model = "gpt-5.4"` and `timeout = 60`; `settings_store` defaults are `"gpt-5.6-terra"` and `180`. The dialog misreports the live configuration.

## 3.4 · Duplicate request construction

**24 distinct payload-building sites**, of which 22 are live. Four different transport styles coexist:

| Style | Where | Gets proxy policy? | Gets retry? | Gets `[EchoMind-HTTP]` log? |
|---|---|---|---|---|
| `echomind_http.post` | `_send_with_mode` ×4, `llm_client` | ✅ | ✅ | ✅ |
| bare `requests.post` + delegated helpers | `openai_reporter` ×9 live | ✅ | ❌ | ❌ |
| bare `requests` | reception ×2 | ❌ | ❌ | ❌ |
| `ChatApiClient.post` | `ai_chat_api.py:57` | ❌ | ❌ | ❌ — **dead**, but instantiated and held on `ChatController.api` |

`ChatGPTPage` re-implements the entire send handler — mode branching, typing bubble, worker wiring, correction flow — bypassing `_send_with_mode` completely. It does reuse the engine (`_ai_module`/`_ai_model` and the shared builders), so this is duplicated *plumbing*, not a duplicated LLM client. Its `_on_send_chatgpt` also computes modality/`normal_template` twice (`:8127-8151`), then discards the result at `:8156-8157`.

## 3.5 · Transcription settings are mixed with LLM settings

One flat `echomind_settings.json` namespace, with **7 keys serving both concerns**:

| Key | LLM use | Transcription use |
|---|---|---|
| `openai_api_key` | chat-completions | OpenAI STT |
| `openai_base_url` | chat-completions base | STT base |
| `connection_type` / `proxy_port` | LLM proxy | STT proxy |
| `api_key` (centre) | backend gate | **STT bearer fallback** via `resolve_auth_token:181-190` |
| `stt_auth_token` | — | overrides a built-in **GapGPT LLM key** for `aipacs_3` |
| `openai_transcription_model` | resolved by the **same** `get_openai_model_for_feature` table as `report`/`correction` | — |
| `secretary_stt_provider` | — | legacy back-compat source of `stt_provider` |

So a user who changes their OpenAI key to fix report generation also silently changes their transcription credentials, and vice versa. There is no namespace boundary between the two subsystems.

Routing itself is sound: `VoiceTranscriptionService.transcribe():334-347` is the single dispatch, and **no in-scope caller bypasses it**. Two caveats: `SttRouter` is imported at `ai_chat_pages.py:59` and never used (a second routing authority left in the import graph), and `stt_provider_to_legacy_route()` collapses `aipacs_1`, `aipacs_2`, `aipacs_3` **and** `custom` all to `"native"`, so anything reading the legacy key cannot tell Server 1 from Server 3.

## 3.6 · Chat / Report / Assist do not route consistently

The mode picker offers four tiles. What each one means depends on the tile *and* the backend setting:

**"Chat" → 3 implementations**
1. `POST {AI_BASE}/chat` — the Chat tile, **company backend only**
2. `openai_reporter.chat()` — the Chat tile when backend is OpenAI, or the ChatGPT tile *(and see 3.3a — it's a corrector)*
3. `openai_parallel_backend.chat()` — the OpenAI twin

**"Report" → 3 implementations**
1. `POST {AI_BASE}/generate_report` — the **Send** button (company only)
2. `reporter()` via Turbo — the **⚡Turbo** button, *both* backends
3. `reporter()` via ChatGPT report mode

**Send and Turbo sit next to each other on the same page and hit two entirely different systems** — one server-prompted, one client-prompted. Nothing in the UI says so.

**"Assist" → 2 implementations**
1. `POST {ASSIST_BASE}/generate_assistant` — the Assist page's Send button
2. `standard_assist_search()` — reachable **only from a button labelled "Standardize"** (`:3996-4000`), never from anything called Assist. Its `page_mode == "Search"` half is unreachable.

## 3.7 · Credentials: 19 read sites, 5 authorities

`api_manager.CENTERS` (8 hardcoded GapGPT `sk-` keys + 8 Irannobat allow-lists) · `settings_store.openai_api_key` (+ `org_id`, `project_id`) · `voice_transcription.AIPACS_SERVER_3_KEY` (hardcoded) · `stt_auth_token` · the PACS socket JWT. Plus `_resolve_active_ai_identity()` (`:63-75`) branching by backend, and a separate `APIKeyManager.get_current_key()` fallback inside Turbo (`:3176-3179`).

## 3.8 · Model selection: 5 competing authorities

1. `_ai_model(feature, company_default, backend)` — **3 call sites only** (correction, Turbo report, one dead)
2. `settings_store.get_openai_model_for_feature` — the 16-entry mapping table
3. `openai_reporter` **function-signature defaults** — `PRIMARY_REPORT_MODEL` for 5 functions, bare `"gpt-4.1-mini"` / `"gpt-4.1"` for 5 others
4. `openai_parallel_backend` `feature_name=` strings — 10 sites
5. `ChatGPTPage.GPT_MODELS` + `_default_model_for_mode`

`_standardize_now` and `_persian_bubble` pass **no** `model=`, so they silently take signature defaults — `translate_text_to_persian` really does still run on `gpt-4.1-mini` on the company path.

## 3.9 · Dead code inventory (17 items)

Highlights: the entire company-side prompt-override subsystem (`_compose_prompt`/`_feature_prompt`/`_is_openai_backend`); `chat_with_api_key`; `ChatApiClient.post`; `_transcribe_with_active_backend`; the `SttRouter` import; `OneChatPage._open_mode_menu`; the unreachable block at `_on_send_clicked:3125-3144` (and `_open_report_modality_menu`, reachable only from inside it); `ChatGPTPage._send_correction` + its `_ai_model`/`correction` call sites; `_init_api_key_input`/`_prompt_for_api_key`/`_detect_and_set_center`; a duplicate `_apply_access_state` (`:1062` shadowed by `:1079`); a duplicated `except Exception: pass` (`:6345-6347`); the `"ChatGPT"` entry in the `_send_with_mode` gate that has no branch.

---

# 4. THE TARGET ARCHITECTURE

Your routing structure is right. Making it real requires one new concept: **Turbo must own its provider, model and credential**, so that it stops being "whatever backend the user picked".

```
EchoMindFunction  =  report | chat | assist | standardize | correction | translate | vision
Pipeline          =  AIPACS_BACKEND | TURBO | USER_OPENAI

resolve(function) -> PipelinePlan {
    pipeline        # which of the 3
    provider        # aipacs-server | gapgpt | user-openai
    prompt_source   # SERVER | LOCAL_BUNDLE | USER_SETTINGS
    model           # one authority, never a signature default
    credential      # one authority per pipeline
    request_builder # one per pipeline, not per tab
    response_parser # shared
}
```

| Function | AI-PACS backend | Turbo | User OpenAI |
|---|---|---|---|
| prompt | server-side | `build_report_system_prompt` (**ours, not user-editable**) | **user's only** |
| model | server-chosen | `TURBO_MODEL` — *new, app-controlled* | user's |
| credential | centre key | `TURBO_KEY` — *new, app-controlled* | user's |
| endpoint | `{AI_BASE}/…` | `TURBO_BASE` — *new, app-controlled* | user's base URL |

Three invariants to enforce mechanically, not by convention:

1. **The AI-PACS request builder must not be able to see the prompt module.** Import-level separation, so a leak is an ImportError, not a code-review miss.
2. **The user-OpenAI builder must not call `build_report_system_prompt`.** That is exactly the bug in §3.1.
3. **Turbo must not read any `prompt_*` or `openai_*` setting.** Today it reads both.

Plus: one settings namespace split (`transcription.*` / `llm.*` / `turbo.*`), one model authority, one credential resolver per pipeline, one request builder per pipeline, one shared response parser.

---

# 5. WHY I HAVE NOT STARTED THE REFACTOR

Three reasons, in order:

1. **The project rule is explicit** — *"never start with refactoring", "avoid architecture rewrites", "prefer minimal, isolated, reversible edits"*. This is a clinical workstation.
2. **The defects in §3.3 are worth more than the refactor** and are independent of it. A chat function answering as a corrector, and an inert Correction tab, are affecting users today. Fixing them first also means the refactor lands on known-good behaviour.
3. **Splitting Turbo from user-OpenAI changes behaviour by design.** Today, a user who selects `llm_backend = "openai"` gets Turbo on their own model. After the split they get Turbo on *our* model. That is what you specified — but it is a live behaviour change for every OpenAI-backend user, and it needs your explicit go-ahead plus a decision on what `TURBO_MODEL`/`TURBO_KEY`/`TURBO_BASE` should actually be.

---

# 6. PROPOSED PLAN — staged, each stage independently testable

### Stage A — defect fixes (no architecture change, ~1 session)
| # | Fix | File | Risk |
|---|---|---|---|
| A1 | Give `chat()` a real chat system prompt | `openai_reporter.py:2444` | low — currently plainly wrong |
| A2 | Re-add the correction-tab dispatch to `ChatGPTPage._on_send_clicked` | `ai_chat_pages.py:7925` | low — restores dead code |
| A3 | Stop `_default_model_for_mode` resolving OpenAI models on the company backend; add `gpt-5.6-terra` to `GPT_MODELS` | `ai_chat_pages.py:7474, 7633` | low |
| A4 | Extend the backend divert to `Assist` | `ai_chat_viewer.py:164` | low |
| A5 | Align the Settings dialog fallbacks with `settings_store` | `echomind_settings.py:910-916` | very low |
| A6 | Pass explicit `model=` in `_standardize_now` / `_persian_bubble` | `ai_chat_pages.py:3999, 4982` | low |

### Stage B — visible truth, no logic change
| B1 | Disable/annotate the 3 Settings prompt fields that are inert on the company backend (or wire `_compose_prompt` into `openai_reporter` — **your call**) |
| B2 | Delete the 17 dead items in §3.9 (each individually, with its guard test) |
| B3 | Label Send vs Turbo in the UI so the two report systems are distinguishable |

### Stage C — the three-pipeline split (needs §7 answered)
| C1 | Introduce `echomind/pipeline.py`: the `Pipeline` enum + `resolve(function) -> PipelinePlan`, one authority |
| C2 | Add app-controlled `TURBO_*` provider/model/credential; stop Turbo reading user settings |
| C3 | Split the settings namespace into `transcription.*` / `llm.*` / `turbo.*` with a migration shim |
| C4 | Route every call site through `resolve()`; delete `_ai_module`/`_ai_model` in favour of it |
| C5 | Guard tests: AI-PACS payload key-set is exactly 6 keys and prompt-free; Turbo system message == bundle entry; user-OpenAI system message == user prompt **only** |

### Stage D — consolidate transport
| D1 | Move `openai_reporter`'s 9 live `requests.post` sites onto `echomind_http` so they gain retry + structured logging |
| D2 | Collapse `ChatGPTPage`'s duplicated send handler onto the shared builder |

---

# 7. DECISIONS I NEED

1. **Turbo's own LLM.** What should `TURBO_BASE` / `TURBO_MODEL` / `TURBO_KEY` be? Options: (a) always GapGPT + `gpt-5.6-terra` + centre key — matches today's company behaviour and is the smallest change; (b) a dedicated app-owned OpenAI account; (c) configurable by you in a config file, not by the end user.
2. **Pipeline 3 purity.** Confirm: when the user selects OpenAI mode, the system message should be **their prompt alone**, with no clinical prompt underneath. That removes the SOURCE FIDELITY safety contract from their reports — deliberate, but I want it in writing before I ship it.
3. **The inert prompt fields (B1).** Wire `prompt_report_generation` into the company backend too, or disable those fields when the backend is company?
4. **Stage A now?** These are six small, isolated, reversible fixes. I can do them today and report before/after, or hold everything until the whole plan is approved.

Once §7 is answered I'll start with Stage A, run the EchoMind guard tests in `tests/code/echomind/`, and report results before touching Stage C.
