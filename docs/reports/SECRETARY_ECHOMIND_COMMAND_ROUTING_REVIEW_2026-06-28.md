# Secretary / EchoMind — Command Routing Review (web-search → patient-search misroute)

**Date:** 2026-06-28
**Reviewer:** engineering agent
**Status:** Review complete + fix IMPLEMENTED behind `AIPACS_SECRETARY_ROUTING_V2`
(default **OFF** → byte-identical legacy). See §6 "Implementation status" and §3 for the
per-layer changes. Pending: live source-build validation before the flag is flipped on.
**Trigger:** A correctly-transcribed voice command to search the internet executed a
**patient-list search** instead. This is a **command-understanding / routing / tool-selection**
failure, not a speech-to-text failure.
**Scope:** Full read of `modules/EchoMind/secretary/` (voice → STT → intent → parse → tool
selection → bus routing), the brain prompts + catalog, the rule parser, the tool registry, and
the live session log of the failed command.

> **Conclusion up front:** The transcription was correct. The Phase-1 *module router* sent an
> internet-search request to the **homepage (patient list)** module because its authoritative
> "VERB → MODULE MAP" binds the verb **search → homepage** and contains **no web/browser row**.
> Phase-2 then received only the homepage document, recognised the user wanted an internet search,
> found no web action available, and **silently degraded to `list_patients`**. The web-search tool
> exists and works — it was simply never offered to the planner. This is the same "degrade to a
> patient action" disease already recorded for the 2026-06-23 *"load series 3" → `list_patients`*
> misroute.

---

## 0. Evidence — the actual failed command (live log)

`user_data/echomind/session_logs/2026-06-27.jsonl` (yesterday), session `echomind-c9677f383e74`:

```json
user_text: "constipation  رو روی اینترنت برام سرچ کن"      // "search 'constipation' for me on the internet"
plan:   { "action": "list_patients", "entities": {}, "confidence": 0.2,
          "needs_confirmation": false,
          "reason": "User requested an internet search for 'constipation', which is not a
                     supported PACS action; defaulting to a non-destructive list action with no filters." }
result: { "ok": true, "action": "list_patients", "message": "Found 100 patient(s) from server source." }
```

The planner's own `reason` is the confession: it **understood** the intent ("an internet search
for 'constipation'") but believed web search "is not a supported PACS action" in the context it was
given, and **chose `list_patients` as a safe default**. 100 patients were returned.

(The English phrasing in the ticket, *"Search this word on the internet,"* is the same intent as
the logged Persian command.)

---

## 1. Pipeline as built (what actually runs in production)

Production constructs the orchestrator with the **brain enabled**:

```
modules/EchoMind/secretary_bridge.py:16-18  →  SecretaryOrchestrator(..., use_brain=True)
```

So `SecretaryOrchestrator._parse_plan()` (`orchestrator.py:182`) tries the **AgentBrain first**,
and only falls back to the rule parser / single-shot LLM if the brain returns nothing:

```
voice ──► STT (stt/router.py + providers)         # transcription (worked correctly)
      ──► SecretaryOrchestrator.handle()
            ├─ is_chitchat() fast-path (greetings)            parser_rules.py
            └─ _parse_plan():
                 ┌─ use_brain=True ─► AgentBrain.plan()       brain/agent.py
                 │     Phase 1  route_request()               brain/router.py
                 │               + prompts/router_phase1_prompt.txt
                 │               + catalog/catalog.yaml         ← picks module_id(s)
                 │     Phase 2  _phase2_plan()                 brain/agent.py
                 │               + prompts/agent_phase2_prompt.txt
                 │               + catalog/modules/<id>.md      ← picks action (the "tool")
                 │   (if brain returns a plan → that plan wins)
                 ├─ rule parser   parse_command_rule()        parser_rules.py   (fallback)
                 └─ single-shot LLM parse_command_llm()       parser_llm.py     (fallback)
            ──► validate_plan()                               validator.py
            ──► executor → CommandBus → adapter               executor.py / bus_factory.py
```

Because the brain produced a valid `list_patients` plan, the rule parser and single-shot LLM
**never ran** for this command. The misroute happened entirely inside **Phase 1 routing**, with
Phase 2 finishing the damage.

---

## 2. Required analysis — answers to the eight questions

### Q1. What tools are currently available to Secretary EchoMind?

~50 bus actions across 11 adapters (`bus_factory.py`, `validator.py::_BUS_ALLOWED_ACTIONS`,
`docs/agent_control/tools.md`). The relevant groups:

| Domain | Actions (selected) | Adapter |
|---|---|---|
| **Patient list (homepage)** | `list_patients`, `select_patient`, `open_patient`, `download_patient` | `home_command_adapter` |
| **Internet / web (web_browser)** | `web_search`, `open_url`, `open_browser`, `browser_back/forward`, `refresh_page` | `browser_command_adapter` |
| **Browser page tools** | `browser_get_text/html/links`, `browser_find_element`, `browser_fill_field`, `browser_click`, `browser_submit_form`, … | `browser_command_adapter` |
| **Viewer (read)** | `get_active_tab`, `get_thumbnails_data`, `get_active_series`, `get_series_info`, `get_multistudy_info`, `list_open_tabs` | `viewer_command_adapter` |
| **Viewer (safe write)** | `change_series`, `scroll_slices`, `switch_tab`, `query_viewport_state`, `change_layout` | `viewer_write_adapter` |
| **Modules** | `open_module`, `open_mpr`, `open_printing`, `open_education`, `toggle_eagle`, `list_modules` | `module_command_adapter` |
| **Reporting (echomind)** | `start_report`, `transcribe_voice`, `generate_report`, `send_report_to_pacs` | `echomind_command_adapter` |
| **Education** | `open_consultation`, `show_consultant_profiles`, `open_courses`, `open_case_of_day`, `search_education` | `education_command_adapter` |
| **Background agent** | `login_website`, `search_education_content`, `agent_task_status`, `cancel_agent_task` | `agent_command_adapter` |
| **System probes** | `snapshot_resources`, `count_aipacs_processes`, … | `system_command_adapter` |

**`web_search` is present, validator-allowed, and fully implemented**
(`browser_command_adapter.py:154`). The browser adapter is registered whenever the Web Browser
module is enabled (`bus_factory.py:144`). So the tool was available — it was a routing problem,
not a missing tool.

### Q2. Which tool was called for the failed command?

`list_patients` (homepage module), with empty entities → 100 patients. Confirmed by the live log
(§0).

### Q3. Which tool should have been called?

`web_search` with `entities.query = "constipation"` (web_browser module).

### Q4. Why did the wrong tool get selected? (root cause)

A chain of **four** reinforcing defects, in order of impact:

1. **PRIMARY — Phase-1 router has no web row and is verb-first.**
   `prompts/router_phase1_prompt.txt` instructs: *"Focus on the VERB first"* and presents a
   **"VERB → MODULE MAP (authoritative — override any other heuristic)"** that lists
   `… search patients … homepage` but has **no `web_browser` and no `education` entry at all**.
   The only home for the verb *search* is **homepage**. The object of the sentence
   (*the internet* / *اینترنت*) — which `catalog.yaml`'s `routing_hints` would map to
   `web_browser` (`pattern: google|browser|website|url|web|internet`) — is explicitly
   **overridden** by the verb rule. So Phase 1 returned `modules: ["homepage"]`.

2. **SECONDARY — Phase-2 degrades to `list_patients` instead of declaring "unknown".**
   With only `homepage.md` supplied, the planner (`agent_phase2_prompt.txt`) had no web action.
   Rather than returning an unrecognised/clarification result, it **substituted a "safe"
   `list_patients`** (its own `reason` says so). There is no rule telling Phase 2 *"if the request
   is for something not in the provided module document, do not substitute a patient action."*
   This is the identical failure mode flagged in `secretary_echo_mind_instruction_map.md` lines
   55-56 for *"load series 3" → `list_patients`*.

3. **REINFORCING — Phase-2 verb semantics are patient-centric and context-blind.**
   Both `agent_phase2_prompt.txt` and `homepage.md` declare
   *"SEARCH / FIND / LOCATE → `select_patient`"* and *"Ignore surrounding context — the VERB is the
   decision signal."* Even if Phase 1 had also routed `web_browser`, this rule biases *search* back
   toward patient operations and tells the model to disregard the object ("on the internet").

4. **LATENT — the deterministic fallback would also miss this phrasing.**
   The rule parser (`parser_rules.py`) is structured correctly (web/education fast-paths run
   *before* the patient branches), but its coverage has gaps:
   - English: `_RE_WEB_SEARCH_PATTERNS[0]` matches `… on google|the web|web|internet` but **not
     `the internet`** — so *"search X on **the** internet"* fails. (Only the `look up …` pattern,
     #8, handles `on the internet`.)
   - Persian: the loose fallback requires a topic marker `راجع به / درباره / در مورد X`
     (`_RE_FA_TOPIC`). The logged command used the object-first form *"X رو روی اینترنت … سرچ کن"*,
     which has no such marker → no match → `parse_command_rule` returns `None`.
   This layer didn't fire here (the brain answered first), but if the AI service were down, the
   offline path would fail this exact command too.

> Of the candidate causes in the ticket: **"intent classifier doesn't distinguish web vs patient
> search"** and **"agent defaults to patient search when unsure"** are both correct. **"Web search
> tool missing"** is **not** the cause — the tool exists and is wired.

### Q5. Are tool descriptions / instructions clear enough?

Split verdict:

- **Per-tool execution docs are good.** `catalog/modules/web_browser.md` and
  `docs/agent_control/browser_tools.md` describe `web_search` clearly, including *"strip command
  words … keep only the actual query."*
- **The cross-module routing instructions are not.** The Phase-1 verb map (the de-facto routing
  spec) **omits web_browser and education entirely** and is declared *authoritative + verb-first*,
  which structurally cannot route an internet search. The Phase-2 "ignore context, verb wins" rule
  compounds it. There is **no documented rule for disambiguating "search a patient" vs "search the
  web,"** and **no documented fallback** ("when unsure, ask; never substitute a patient action").

### Q6. Is there a proper distinction between patient search / web search / app navigation / browser interaction / report (EchoMind) actions?

At **execution** time, yes — the adapters are cleanly separated (home vs browser vs viewer vs
echomind vs education), and the structured `browser_*` page tools are well isolated. At **routing**
time, **no** for the one pair that collides on a verb: **patient search vs web search**. "Search"
is overloaded and the router resolves it patient-first with no web alternative. Navigation
(`open_url`, `browser_back/forward`), browser page interaction (`browser_*`), reporting
(`start_report` …) and education are individually distinct; the single broken boundary is
**search-verb → {patient | web}**.

### Q7. What documentation exists for the agent?

- `docs/agent_control/tools.md` — authoritative tool inventory + permission modes.
- `docs/agent_control/browser_tools.md` — browser/web tool surface (excellent, execution-side).
- `docs/agent_control/secretary_echo_mind_instruction_map.md` — intent → tool map (single +
  compound). **Patient/viewer/report/download only — no web/browser/education/internet rows.**
- `docs/agent_control/workflows.md`, `qa_workflows.md` — multi-step + QA.
- `docs/reports/SECRETARY_ECHOMIND_PIPELINE_REVIEW_2026-06-06.md`,
  `SECRETARY_BUS_BRIDGE_ASBUILT_2026-06-06.md`, `WEB_BROWSER_MODULE_FIXES_2026-06-27.md`,
  `AGENT_CONTROL_ARCHITECTURE_REVIEW_2026-06-23.md`.
- The brain's own prompts + `catalog/catalog.yaml` + `catalog/modules/*.md` (the live routing spec).
- `modules/EchoMind/secretary/AGENT_BRAIN_ROADMAP.md`.

### Q8. What documentation is missing or outdated?

- **Missing:** a single **Command Routing Rules** document that defines the intent domains and the
  **verb + object** disambiguation (especially *search the web* vs *search a patient*), the
  available tool per domain, correct/incorrect examples, and the **ambiguous-→-clarify** fallback.
  *(Added in this pass — see `docs/agent_control/command_routing_rules.md`.)*
- **Outdated:** `secretary_echo_mind_instruction_map.md` predates the web_browser / education /
  background-agent surface and has no rows for them; it should point at the new routing doc.
- **Outdated/incorrect:** `prompts/router_phase1_prompt.txt`'s verb map (no web/education rows) and
  the Phase-2 "ignore context" rule — these are the live spec and they encode the bug.
- **Missing:** persisted routing trace. The Phase-1 decision (`modules` + `reason`) is only written
  to **stderr** (`router.py`'s `_elog`), not to the JSONL session log — so the log shows
  transcription → plan → result but **not the module-routing step** that actually went wrong.

---

## 3. Required fix direction — stabilise routing first (no new features)

Per the directive, **fix the routing model before adding capability.** Target intent domains:

```
Patient search        Internet / web search     Open patient        Viewer command
Report command        EchoMind command          Browser command     Settings command
Education command     Unknown / needs clarification
```

**The governing principle: route on VERB *plus* OBJECT, not the verb alone.** A *search* whose
object names the web (`internet / web / online / google / اینترنت / وب / گوگل`) is a **web search**;
a *search* whose object is a patient / code / name / study (or has no web object) is a **patient
search**.

Proposed changes (each minimal, reversible, flag-gated default-OFF until live-validated; legacy
path preserved as the kill switch — consistent with project rules):

| # | Layer | File | Change | Risk |
|---|---|---|---|---|
| **A** | Phase-1 router prompt | `prompts/router_phase1_prompt.txt` | Add `web_browser` + `education` rows to the VERB→MODULE MAP; add an explicit rule: *search/find/look-up + internet\|web\|online\|google → `web_browser`*; *search/find/locate + patient/code/name/study (or no web object) → `homepage`*. Add: *if no module fits, return `modules: []` — never substitute `homepage`.* | Low (prompt only) |
| **B** | Phase-1 catalog | `catalog/catalog.yaml` | Make the web routing hint explicit and ranked above the patient hint when a web object is present; keep the patient hint qualified (`…patient`). | Low (prompt only) |
| **C** | Phase-2 planner | `prompts/agent_phase2_prompt.txt`, `catalog/modules/homepage.md` | Scope *SEARCH→`select_patient`* to *search **for a patient***. Add: *if the request needs an action not present in the provided module document, return `action:"unknown"` (clarify) — do **not** substitute `list_patients`/`select_patient`.* Kills the recurring degrade-to-patient disease. | Low–Med (behaviour) |
| **D** | Deterministic fallback | `parser_rules.py` | Add `the internet`/`the web` to `_RE_WEB_SEARCH_PATTERNS[0]`; broaden the Persian fallback to the object-first form (*"X رو روی اینترنت سرچ کن"*); ensure a sentence containing a net-word + search-verb can never fall into the patient/list branches. | Low (additive regex) |
| **E** | Logging | `session_log.py` + `orchestrator._parse_plan` | Persist the Phase-1 routing decision (`modules`, `reason`) and the chosen action into the JSONL so the log shows **transcription → routing → tool → result** (acceptance #5). | Low (log only) |
| **F** | Fallback behaviour | `orchestrator.py` | Add an explicit **Unknown / needs-clarification** result that asks the user to choose the domain when the object is ambiguous or no module fits, instead of running a default action (acceptance #6). | Med (behaviour) |

Lowest-risk first (D + E are additive and clinically inert); A–C are prompt-only; F is a small,
contained behaviour addition. Each change ships with a unit test and is verified on the live source
build before its flag is flipped on.

### Behaviour rule to encode (from the ticket)

- *"search this on the internet" / "look this up online" / "google this" / "find this on the web"*
  → **web/browser search path** (`web_search`).
- *"search patient" / "find patient code" / "open patient" / "find this patient in the list"*
  → **patient-list path** (`select_patient` / `open_patient`).
- Object names the web **and** a patient ambiguously, or no module fits → **ask which** (don't guess).

---

## 4. Acceptance criteria — status & how each is met

| # | Criterion | Status | Met by |
|---|---|---|---|
| 1 | Command transcribed correctly | ✅ already true | STT confirmed correct in the log |
| 2 | "Search … on the internet" → web search | ⛔→fix A/B (+D offline) | router verb+object rule routes to `web_browser.web_search` |
| 3 | Patient search not triggered unless clearly a patient | ⛔→fix A/C | web object outranks default patient interpretation; Phase-2 won't substitute a patient action |
| 4 | Tool routing rules documented | ✅ this pass | `docs/agent_control/command_routing_rules.md` |
| 5 | Logs show transcription → intent → tool → result | ⚠️ partial→fix E | persist Phase-1 routing into the JSONL |
| 6 | Ambiguous → clarify, not wrong domain | ⛔→fix C/F | explicit Unknown/needs-clarification path |

---

## 6. Implementation status (2026-06-28)

All of A–F are implemented behind a single flag **`AIPACS_SECRETARY_ROUTING_V2`**
(default **OFF** → byte-identical legacy routing; the legacy prompt/path is the kill switch).

| # | Change | Files |
|---|---|---|
| flag | `routing_v2_enabled()` + flag-aware Phase-1 prompt selection | `secretary/config.py` |
| A | Phase-1 router v2 prompt (verb+object; web_browser + education rows; "no module → modules:[]") | `secretary/prompts/router_phase1_prompt_v2.txt`, `secretary/brain/router.py` |
| C | Phase-2 override prefix (search-by-object; **never substitute a patient action**; emit `unknown`) + `unknown` pass-through | `secretary/brain/agent.py` |
| D | Rule-parser web coverage ("on the internet/the web", "… online", object-first Persian) | `secretary/parser_rules.py` |
| E | Phase-1 routing decision persisted to the JSONL session log | `secretary/orchestrator.py` |
| F | `unknown` → **needs_clarification** result (ask, don't guess) | `secretary/orchestrator.py` |

> B (catalog) was folded into A: `catalog.yaml` already lists `web_browser` + a web routing hint;
> the authority is the Phase-1 prompt, so the verb+object rule lives there (no parallel catalog
> file to maintain).

**Tests:** `tests/code/echomind/test_routing_v2.py` (flag on/off prompt selection, rule-parser
web routing for the exact failing commands, patient-routing-unharmed regression, `unknown`→clarify,
route-trace logging). The deterministic regexes were additionally validated standalone (the legacy
pattern is confirmed to miss "on the internet"; all patient/negative inputs return `None`).

**Plugin mirror:** EchoMind is **not** in `tools/dev/sync_plugin_mirrors.py`; the source build reads
`modules/EchoMind/` directly, so no mirror sync is needed for source-build validation. If a packaged
build is cut with the flag on, mirror the changed files into
`builder/plugin package/packages/echomind/payload/...` first.

## 7. How to validate on the live source build (before flipping the flag on)

1. Launch the **source build** with `AIPACS_SECRETARY_ROUTING_V2=1`.
2. Run `python -m pytest tests/code/echomind/test_routing_v2.py -p no:debugging -q` (and the
   existing `tests/code/echomind/` suite) — all green.
3. Voice/text the **exact failing commands**: `constipation رو روی اینترنت برام سرچ کن` and
   *"search this on the internet"* → must open the Web Browser and Google-search the topic
   (`web_search`), **not** the patient list.
4. **Patient-routing regression** (must be unchanged): `بیمار X رو سرچ کن` / *"find patient 12345"*
   → patient search; *"show today's patients"* → list; *"open patient 12345"* → open.
   *"google rotator cuff tear"* → web search.
5. Check the JSONL session log shows a `route` entry (modules + reason) per command.
6. If all pass, flip the build default (or set the env var) ON. Only then resume feature work.
