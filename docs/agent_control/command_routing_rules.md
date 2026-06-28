# Secretary / EchoMind — Command Routing Rules

**Date:** 2026-06-28
**Status:** Authoritative routing specification for the Secretary / EchoMind voice-and-text agent.
Enforced by the **`AIPACS_SECRETARY_ROUTING_V2`** flag (default **OFF** → legacy; set `=1` to
enable verb+object routing). Implementation + validation steps:
`../reports/SECRETARY_ECHOMIND_COMMAND_ROUTING_REVIEW_2026-06-28.md` §6–§7.
**Companion docs:** `tools.md` (tool inventory), `browser_tools.md` (web tool surface),
`secretary_echo_mind_instruction_map.md` (per-intent call map), and the review
`../reports/SECRETARY_ECHOMIND_COMMAND_ROUTING_REVIEW_2026-06-28.md`.

This document defines **how a spoken/typed command is mapped to a domain and a tool**. It exists
because the verb *search* is overloaded — *"search a patient"* and *"search the internet"* are
different domains — and the agent must not confuse them. Read this before editing
`prompts/router_phase1_prompt.txt`, `catalog/catalog.yaml`, `catalog/modules/*.md`,
`prompts/agent_phase2_prompt.txt`, or `parser_rules.py`.

---

## 1. The golden rule: route on VERB **+ OBJECT**, never the verb alone

The verb sets the *kind* of action; the **object** sets the *domain*. The single most important
rule in this whole system:

> A **search/find/look-up** whose object names the **web** (`internet`, `web`, `online`, `google`,
> `اینترنت`, `وب`, `گوگل`) is an **internet search** → `web_search`.
> A **search/find/locate** whose object is a **patient / code / name / study** (or has **no** web
> object) is a **patient search** → `select_patient`.

If a command satisfies neither cleanly (ambiguous object, or an action no module supports), the
agent **asks the user which domain they meant** — it never substitutes a default patient action.

---

## 1b. Two-brain architecture (how a command becomes an action)

Routing is a cooperation between two parts. Neither works alone.

**Internal orchestrator (local, not intelligent).** Owns app state and the tools. Its jobs:
1. Receive the transcript.
2. **Advertise the available capabilities** (the tool list) to the LLM — completely and
   accurately. (This is where the historical bugs were: the verb map omitted web tools, the
   Phase-2 module doc omitted the browser page tools, and the single-shot fallback advertised
   only 3 patient actions.)
3. **Validate** the LLM's chosen action against the allow-list (`validator.py`).
4. **Execute** it through the right adapter and return the result.
5. **Log** the full path.

**External LLM (the reasoning brain).** Receives the transcript + the advertised capabilities +
app/date/memory context + these tool-selection rules, and **chooses the tool**. It must not be
boxed in by a lossy pre-selection — when a search could be web or patient, it needs to see both.

**Pipeline (must stay intact):**

```
voice → transcription → orchestrator gathers capabilities + context
      → LLM selects intent/tool  (Phase-1 module routing → Phase-2 action planning, or single-shot)
      → orchestrator validates the selected tool
      → orchestrator executes the adapter
      → result returned to the user
      → session log records: transcript → routing(modules,reason) → tool → validation → result
```

**Capability advertisement format** (what the orchestrator tells the LLM). Phase-1 receives the
module catalog + the available `module_id` list; Phase-2 receives the chosen modules' full tool
docs; the single-shot fallback receives the flat capability registry (`prompt_context.py`). Each
tool is advertised as `name {entities} — one-line purpose`, e.g.:

```
web_search {query} — search the internet/Google for information or a medical topic.
select_patient {patient_code} — find/locate a patient row in the list (no viewer).
browser_fill_field {selector,value} — type a value into a page field.
```

**Lossy-bottleneck rule:** Phase-1 must not pre-select a single module when the command is
ambiguous between domains. For a search whose object is a medical topic (not a patient), Phase-1
returns **web_browser AND homepage** so the planner chooses with full context; if nothing fits it
returns `modules: []` (→ clarify) and never substitutes the patient list.

## 2. Intent domains

| Domain | What it means | Primary tool(s) | Module |
|---|---|---|---|
| **Patient search** | Find/locate/select a patient *in the list* (no viewer) | `select_patient`, `list_patients` | homepage |
| **Internet / web search** | Search the web/Google for information | `web_search` | web_browser |
| **Open patient** | Open a study in the DICOM viewer | `open_patient` | homepage → patient_viewer |
| **Viewer command** | Series/slice/layout/tab inside an open study | `change_series`, `scroll_slices`, `switch_tab`, `change_layout`, `query_viewport_state` | viewer_write |
| **Browser command** | Navigate / read / interact with the web page | `open_url`, `browser_back/forward`, `refresh_page`, `browser_get_text`, `browser_find_element`, `browser_fill_field`, `browser_click`, `browser_submit_form` | web_browser |
| **Report / EchoMind command** | Dictate / transcribe / generate / send a report; AI chat | `start_report`, `transcribe_voice`, `generate_report`, `send_report_to_pacs` | echomind |
| **Download command** | Queue / manage study downloads | `download_patient`, `check_download_status`, `pause/resume/cancel_download`, `download_statistics` | download |
| **Module / navigation** | Open a module or switch source tab | `open_module`, `open_mpr`, `open_printing`, `open_education`, `toggle_eagle`, `set_source_mode` | modules / homepage |
| **Education command** | Library / courses / consultation / case of the day | `search_education`, `open_courses`, `open_consultation`, `show_consultant_profiles`, `open_case_of_day` | education |
| **Settings command** | Change a setting (font size, etc.) | `change_font_size`, `sort_patients` | homepage (more staged) |
| **Unknown / needs clarification** | Object ambiguous, or no module fits | *(ask the user)* | — |

> **Note on "Settings command":** today only list-surface settings (font size, sort) are wired.
> A general settings domain is **staged, not implemented** — if asked for an unsupported setting,
> say so; do not substitute another action.

---

## 3. Available tools (registry summary)

Full reference: `tools.md` and `browser_tools.md`. Web tools: `browser_tools.md`. All are
CommandBus actions validated by `validator.py` (`_ALLOWED_ACTIONS` + `_BUS_ALLOWED_ACTIONS`) and
dispatched to the adapter named below.

- **homepage / home_command_adapter:** `list_patients`, `select_patient`, `open_patient`,
  `download_patient`, `set_source_mode`, `sort_patients`, `change_font_size`, `select_and_download`.
- **web_browser / browser_command_adapter:** `web_search`, `open_url`, `open_browser`,
  `browser_back`, `browser_forward`, `refresh_page`, plus structured page tools `browser_get_text`,
  `browser_get_html`, `browser_get_links`, `browser_dom_summary`, `browser_find_element`,
  `browser_fill_field`, `browser_click`, `browser_submit_form`, `browser_extract_table`,
  `browser_screenshot`, `browser_get_url`, `browser_selected_text`.
- **download / download_command_adapter:** `check_download_status`, `list_downloads`,
  `download_statistics`, `pause_download`, `resume_download`, `cancel_download`.
- **viewer (read) / viewer_command_adapter:** `get_active_tab`, `list_open_tabs`,
  `get_thumbnails_data`, `get_active_series`, `get_multistudy_info`, `get_series_info`.
- **viewer (write) / viewer_write_adapter:** `change_series`, `scroll_slices`, `switch_tab`,
  `query_viewport_state`, `change_layout`.
- **modules / module_command_adapter:** `open_module`, `open_mpr`, `open_printing`,
  `open_education`, `toggle_eagle`, `list_modules`.
- **echomind / echomind_command_adapter:** `start_report`, `transcribe_voice`, `generate_report`,
  `send_report_to_pacs`.
- **education / education_command_adapter:** `search_education`, `open_courses`,
  `open_consultation`, `show_consultant_profiles`, `open_case_of_day`.
- **agent (background) / agent_command_adapter:** `login_website`, `search_education_content`,
  `agent_task_status`, `cancel_agent_task`.
- **system / system_command_adapter:** resource probes (not user-facing).

> `web_search` **exists and is available** whenever the Web Browser module is enabled. A missing
> web result is a *routing* problem, not a missing tool.

---

## 4. Tool-selection rules (verb + object)

Apply in order; first match wins.

1. **Web object present** (`internet`, `web`, `online`, `google`, `اینترنت`, `وب`, `گوگل`)
   - with a search verb (`search`, `look up`, `find`, `google`, `سرچ`, `جستجو`, `بگرد`) → `web_search` (query = the topic, command words stripped).
   - with "open/go to" + a URL/domain → `open_url`.
   - "open the browser" alone → `open_browser`.
   - "go back / forward / refresh" → `browser_back` / `browser_forward` / `refresh_page`.
2. **Patient object present** (`patient`, `code`, `id`, a name, a study, `بیمار`, `کد`) **or no web object**
   - search/find/locate/look-up → `select_patient`.
   - open/view/enter → `open_patient` (confirm).
   - download/fetch → `download_patient` (confirm).
   - list/show (no specific patient) → `list_patients` (+ date/modality filters).
3. **Open study context** (series/slice/layout/tab/viewport) → viewer command (`change_series`,
   `scroll_slices`, `switch_tab`, `change_layout`).
4. **Report words** (report, dictate, transcribe, generate, send to PACS) → echomind command.
5. **Education words** (course, library, consultation, consultant, case of the day) → education command.
6. **Module words** (MPR, eagle, printing, education, browser) with "open" → `open_module`.
7. **None of the above, or ambiguous object** → **Unknown / needs clarification** (ask the user).

**Never** resolve an unsatisfiable request by substituting `list_patients` / `select_patient`.
If the routed module cannot perform the requested action, return `unknown` and ask.

---

## 5. Examples — correct routing

| User command (EN / FA) | Domain | Correct tool call |
|---|---|---|
| "Search this on the internet" / "این رو روی اینترنت سرچ کن" | Internet search | `web_search { query: "this" }` |
| "Look up rotator cuff tear online" | Internet search | `web_search { query: "rotator cuff tear" }` |
| "Google constipation" / "constipation رو روی اینترنت سرچ کن" | Internet search | `web_search { query: "constipation" }` |
| "Find this on the web" | Internet search | `web_search { query: "this" }` |
| "Open google.com" / "برو به google.com" | Browser nav | `open_url { url: "https://google.com" }` |
| "Go back" / "refresh the page" | Browser nav | `browser_back` / `refresh_page` |
| "Search patient Ahmadi" / "بیمار احمدی رو سرچ کن" | Patient search | `select_patient { patient_code: "Ahmadi" }` |
| "Find patient code 12345" / "کد بیمار ۱۲۳۴۵ رو پیدا کن" | Patient search | `select_patient { patient_code: "12345" }` |
| "Open patient 12345" / "بیمار ۱۲۳۴۵ رو باز کن" | Open patient | `open_patient { patient_code: "12345" }` (confirm) |
| "Show today's MRI patients" / "بیماران ام‌آر‌آی امروز" | Patient list | `list_patients { date: "today", modality: "MR" }` |
| "Load the third series" / "سری سوم رو باز کن" | Viewer | `change_series { series_index: 2 }` |
| "Search the library for ACL" | Education | `search_education { query: "ACL" }` |

---

## 6. Examples — WRONG routing (must not happen)

| User command | Wrong (observed/possible) | Correct | Why it was wrong |
|---|---|---|---|
| "constipation رو روی اینترنت سرچ کن" | `list_patients {}` → 100 patients *(the 2026-06-27 bug)* | `web_search { query: "constipation" }` | Verb-only routing sent *search* → homepage; planner had no web action and degraded to a patient list |
| "Search this on the internet" | `select_patient { patient_code: "this" }` | `web_search { query: "this" }` | Web object ignored; *search* treated as patient search |
| "Look this up online" | `list_patients {}` | `web_search { query: "this" }` | Web object ("online") not honoured |
| "Load series 3" *(no series support in routed module)* | `list_patients {}` *(2026-06-23 bug)* | `change_series { series_index: 2 }` or "not supported yet" | Degraded to a patient action instead of the viewer tool / a clear gap message |

The shared failure in every wrong row is the same: **the verb was honoured, the object was
ignored, and an unsatisfiable request was silently replaced with a patient action.**

---

## 7. Fallback behaviour when intent is ambiguous

1. **Object names two domains** (e.g. a sentence that mentions both a patient and the web) → ask:
   *"Do you want me to search the web, or find a patient?"*
2. **No module supports the request** → say it plainly (*"I can't do that yet"*) — do **not**
   substitute a patient list/search.
3. **Low routing confidence** → return **Unknown / needs clarification** and offer the two most
   likely domains, rather than guessing.
4. **AI service unreachable** → the deterministic rule parser handles the common web/patient
   phrasings offline; if it also can't map the command, report the connectivity problem
   (`LLM_UNREACHABLE`) rather than a wrong action.

The guiding value: **a clarifying question is always better than a confident wrong domain** — this
is especially true in a clinical workstation where a wrong "search" dumps the patient list.

---

## 8. Where these rules are enforced (for implementers)

| Rule | Enforced in |
|---|---|
| Phase-1 domain routing (verb + object) | `prompts/router_phase1_prompt.txt`, `catalog/catalog.yaml` |
| Phase-2 action selection + "don't substitute a patient action" | `prompts/agent_phase2_prompt.txt`, `catalog/modules/homepage.md`, `catalog/modules/web_browser.md` |
| Deterministic offline routing | `parser_rules.py` (`_parse_browser_education`, `_RE_WEB_SEARCH_PATTERNS`, the FA fallback) |
| Allowed actions / validation | `validator.py` (`_ALLOWED_ACTIONS`, `_BUS_ALLOWED_ACTIONS`) |
| Tool execution | `adapters/*_command_adapter.py` via `bus_factory.py` |
| Routing trace (transcription → routing → tool → result) | `session_log.py` + `orchestrator._parse_plan` (Phase-1 decision should be persisted, not stderr-only) |

When you change any routing rule here, add a unit test and validate on the **live source build**
with both the failing web command **and** a patient-search regression set, to prove patient routing
is unharmed.
