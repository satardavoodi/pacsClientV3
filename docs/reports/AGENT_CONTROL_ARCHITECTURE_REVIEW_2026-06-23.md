# AI-PACS Agent-Control / Internal-MCP Architecture Review

**Date:** 2026-06-23
**Author:** AI-PACS engineering agent (architecture review, read-only — no code changed)
**Scope:** `modules/EchoMind/secretary/*`, `tools/testing/aipacs_control_mcp/*`, and the agent-control docs.
**Status:** Review only. No production code was modified. This is the evidence base for a future, flag-gated implementation.

> Method note: every claim below cites `file:line`. I read the control spine directly
> (`command_bus.py`, `registry.py`, `command_envelope.py`, `contracts.py`, `bus_factory.py`,
> `config.py`, `audit.py`, `confirm.py`, `__init__.py`) and used three sub-audits for the
> adapters, the MCP/test-server layer, and the existing docs. Absence claims ("no X") were
> grounded with targeted searches, not assumed.

---

## 0. TL;DR

**The bones are right; the ownership, the safety layer, and the MCP surface are not finished.**

AI-PACS already has a clean, GUI-agnostic control plane — a `CommandBus` + `AdapterRegistry`
+ 11 adapters exposing ~50 actions — plus a real `FastMCP` server and a per-user
`QLocalServer` test channel that runs every command through the **production code path** (so
the clinical cross-patient / multi-study guards stay enforced). That is a strong foundation and
is close to what you sketched.

Three things are wrong or missing:

1. **It lives inside EchoMind but is not EchoMind-specific.** The control plane has almost no
   dependency on the assistant. Physical placement implies ownership it shouldn't have.
2. **The execution layer has no permission/side-effect enforcement.** `CommandPlan.needs_confirmation`
   exists as a field but `bus.execute()` → `registry.dispatch()` **never reads it**
   (`command_bus.py:70-82`, `registry.py:79-112`). Side-effect class and confirmation rules live
   only in catalog metadata and the *voice* validator — both **bypassed** by the MCP / test-server
   path. An external agent can call `send_report_to_pacs`, `download_patient`, `cancel_download`,
   `close_patient_tab` with zero in-app gate.
3. **It is tools-only.** No MCP **resources** (read-only state URIs) and no MCP **prompts**
   (reusable workflows); read-state is exposed as tools and workflows are scenario JSON fed to a
   tool. There is also **no audit on the bus path** and **no auth on the IPC channel**.

**Recommendation:** Promote the control plane out of EchoMind into a dedicated
`modules/agent_control/` package, make EchoMind and the QA harness *consumers*, and add the
missing safety layer **first** (permissions, audit, channel auth) before the physical move.
Do it the AI-PACS way: flag-gated, re-export shims, no behavior change until validated.

**QA-agent readiness: ~6/10** (strong state-driven control; weak on visual capture, assertions,
structured logs, audit). **End-user-assistant readiness: ~5/10** (voice still capped at 9 actions;
bridge to the full bus only partially wired).

---

## 1. Current MCP / agent-control architecture

There are **three layers today**, but only two are cleanly separated. The control plane and the
assistant are tangled together under one module.

```
External AI agent (Claude / Copilot / QA harness)
        │  (stdio, MCP protocol — real `mcp` package / FastMCP)
        ▼
tools/testing/aipacs_control_mcp/server.py   ── FastMCP, 26 @mcp.tool()
        │  AipacsControlClient.send()  (client.py)
        ▼  QLocalSocket  →  per-user Windows named pipe  "AIPACS_TEST_<user>", JSON-lines, id-correlated
modules/EchoMind/secretary/test_server.py    ── QLocalServer, drains 1 cmd / Qt event-loop turn
        │  bus.execute(CommandPlan(action, entities))
        ▼
modules/EchoMind/secretary/command_bus.py    ── CommandBus.execute()  ← THE control plane
        │  registry.dispatch(plan, state)
        ▼
modules/EchoMind/secretary/registry.py       ── AdapterRegistry: action_name → bound method
        │
        ▼
modules/EchoMind/secretary/adapters/*.py     ── 11 adapters → REAL app functions (production path)


        ── SEPARATE, half-connected path ──
SecretaryOrbButton (voice/text) → STT → orchestrator.py → validator.py (caps at 9 actions)
        → executor.py → HomeWidgetAdapter   [confirmation + audit live ONLY here]
```

Key structural facts (verified):

- **The CommandBus is generic.** `CommandBus(registry, orchestrator=None)` works with no
  assistant at all; the orchestrator (the EchoMind LLM brain) is optional and only used for the
  *parse* path (`command_bus.py:39-49, 52-67`). The agent SDK / tests / test-server construct a
  `CommandPlan` directly and call `execute()`, never touching EchoMind logic.
- **`bus_factory.build_command_bus()` is the single wiring point** and is explicitly
  "CI-runnable without PySide6 … the factory NEVER imports the production GUI directly"
  (`bus_factory.py:18-27`). It is wired in production at
  `PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py:233-259`.
- **Two execution paths exist and are only partially bridged.** The voice/text assistant is
  hard-capped at 9 home actions by `validator._ALLOWED_ACTIONS`; the full ~50-action bus is
  reachable by the MCP/test-server path. This split is the central finding of
  `docs/reports/SECRETARY_ECHOMIND_PIPELINE_REVIEW_2026-06-06.md` (W1).

---

## 2. What is implemented now (the strengths)

| Capability | Where | Notes |
|---|---|---|
| Unified control plane | `command_bus.py`, `registry.py`, `command_envelope.py` | Clean, typed (Pydantic), idempotent registration, normalizes any return into `CommandResult`. Unit-tested. |
| ~50 actions / 11 adapters | `adapters/*.py`, wired in `bus_factory.py:78-255` | patient (home), viewer read, viewer write (safe subset), download, module launch, browser, education, reporting (echomind), system probes, background agent. |
| Read-only state probes (de-facto "resources") | `viewer_command_adapter.py` (strictly read-only, :1-14), `system_command_adapter.py`, `download_command_adapter.py` | `get_active_tab`, `list_open_tabs`, `get_thumbnails_data`, `get_active_series`, `get_multistudy_info`, `query_viewport_state`, `get_series_info`, `snapshot_resources`, download status/list/stats. |
| Real MCP server | `tools/testing/aipacs_control_mcp/server.py:29-365` | Uses `mcp.server.fastmcp.FastMCP`; stdio; 26 tools incl. lifecycle, workflow, pressure (`burst`, `run_scenario`). FastMCP auto-generates JSON schemas from signatures. |
| Hardened IPC channel | `test_server.py:194-239` | Default OFF; requires `AIPACS_TEST_SERVER=1`; **refuses frozen build** (`sys.frozen`); per-user socket name; stale-endpoint cleanup; loud banner. |
| Production-path fidelity (T1) | (by construction) | Commands run the real app functions → cross-patient isolation + multi-study guards stay enforced. This is genuinely good and rare. |
| Scenario engine (de-facto "prompts"/workflows) | `server.py:242-293`, `scenarios/*.json` | Deterministic, seeded, looped, jittered; pseudo-actions `wait_ms`, `wait_for_download`, `assert_health`. |
| Lifecycle automation | `lifecycle.py` | `launch_app` (source build only, forces `AIPACS_TEST_SERVER=1`), `login` (pywinauto UIA Invoke), `dismiss_startup_dialogs`, `move_app_to_monitor` (pywin32). |
| Visual observation harness | `ui_probe.py` | `mss` ~25 fps screen-diff for flicker/blank detection around commands. |
| Catalog metadata WITH side-effect intent | `catalog/catalog.yaml`, `catalog/modules/*.md`, `module_map.yaml` | Per-module/action `side_effects` + `confirmation_required`/`needs_confirmation` flags — but these inform the **LLM**, not the executor. |
| Confirmation flow (voice path) | `executor.py:382-393`, `validator.py:96-98`, `confirm.py` | 2-turn confirm; multilingual yes/no (incl. Persian). Enforced for `send_report_to_pacs` at runtime; `open_patient`/`download_patient` at plan level. |
| Best-effort audit (voice path) | `audit.py:6-65` | `log_start`/`log_end` → DB (`ai_log_secretary_action_*`); records `confirmation_required`, entities, action, latency, status. |
| Capability discovery | `server.py:90-93` (`list_actions`), `registry.list_actions()` | An agent can enumerate registered actions. |

---

## 3. What is missing

Ordered roughly by clinical-safety importance.

1. **No permission / side-effect enforcement in the execution layer (the big one).**
   `registry.dispatch()` is the *only* universal choke point and it does: look up the action,
   call the method, normalize the result (`registry.py:79-112`). It checks **no** permission level,
   **no** side-effect class, and **ignores `CommandPlan.needs_confirmation`** entirely.
   `bus.execute()` likewise (`command_bus.py:70-82`). The catalog `side_effects`/`confirmation_required`
   and the validator's `_BUS_CONFIRM_REQUIRED_ACTIONS = {"send_report_to_pacs"}` only run on the
   *voice* path — the MCP / test-server / direct-`bus.execute` path skips them.

2. **No tool input/output schemas on the app side.** FastMCP generates schemas from the MCP
   server's Python signatures, but the in-app adapters have **no declared input schema, no output
   schema, no side-effect attribute, no permission level**. Argument validation is ad-hoc per
   adapter (e.g. `home_command_adapter.py` MISSING_PATIENT_ID guards). `CommandPlan`/`CommandResult`
   are `extra="allow"` (`command_envelope.py:32,52`) — they validate envelope shape, not contents.

3. **No MCP resources.** No `@mcp.resource(...)` anywhere in `server.py`; no URI scheme, no
   `read_resource`. Read-only state (viewport, thumbnails, download status, health) is surfaced as
   **tools**, not as `resource://…` resources.

4. **No MCP prompts.** No `@mcp.prompt(...)`. Reusable workflows exist only as scenario JSON files
   handed to the `run_scenario` tool — not first-class prompts the host can enumerate.

5. **No audit on the bus / MCP / test-server path.** `audit.py` is invoked only by the voice
   orchestrator/executor. The MCP server writes a *server-side* session JSONL (`server.py` `_record`),
   but the **application has no record** that an external agent searched, opened, downloaded, or
   closed anything. No correlation ID spans the chain.

6. **No authentication / authorization on the `QLocalServer` channel.** `_execute` parses the line,
   builds a `CommandPlan`, calls `bus.execute()` — zero caller verification (`test_server.py:163-185`).
   Any local process that can open the per-user pipe can issue **every** registered command,
   including destructive ones. The only boundaries are env-flag + frozen-refusal + pipe name.

7. **No session manager / mode / scope (roots).** There is no "read-only session" vs "QA session"
   vs "server-write session." The only switches are binary: `AIPACS_TEST_SERVER` on/off and the
   `enable_viewer_write` flag (`bus_factory.py:47, 212`). There is no notion of *which* patients,
   studies, screens, or files a session may touch.

8. **`raw_command` arbitrary-action escape hatch** (`server.py:96-99`) routes any string action +
   JSON entities straight to the bus. Excellent for QA, but ungated — it must be mode-restricted.

9. **Prompt-injection / unsafe-tool-trust exposure.** The EchoMind LLM brain plans actions from
   user text (and, via the browser/education agents, from web/document text). As the
   orchestrator→bus bridge completes, an injected instruction could trigger a side-effecting action;
   the runtime confirmation gate currently covers only `send_report_to_pacs`.

10. **Catalog ↔ contract ↔ adapter divergence.** `contracts.BrainActionName` lists 18 actions but
    several have **no adapter handler**: `apply_preset`, `measure`, `run_analysis`, `export_report`,
    `print_series`, `export_pdf`, `ai_chat`, `generate_summary`, `show_findings`, `explain_finding`
    (`contracts.py:10-36`). The LLM can plan actions that cannot execute.

11. **Two divergent action-declaration conventions** — module-level `*_ACTIONS` dicts vs class
    `SUPPORTED_ACTIONS` tuples — and the *canonical* mapping actually used in production lives in
    `bus_factory.py`, so an adapter's declared list can silently drift from what's registered.

12. **Missing tools you explicitly asked for:**
    - `viewer.capture_screenshot` — **absent** from the bus/MCP surface. Capture exists only in the
      external `ui_probe.py` (`mss`) and the background `verification.py` helper, neither exposed as
      an agent tool.
    - `status.get` / `status.update_server_status` — **absent**. Only *download* status is read
      (`download_command_adapter.py:90,180`); the reception/server status-update UI is not exposed.
    - `attachment.record_voice` / `attachment.list` / `attachment.sync` — **absent**. Only
      `echomind` reporting attaches the newest voice file (`echomind_command_adapter.py`).
    - `viewer.open_dental_curve_mpr` — **absent**. Wired module launchers are only `eagle_ai`,
      `mpr` (standard Zeta), `printing`, `education`, `web_browser` (`widget.py:245-254`).
      Curve / Dental-Curve / Orthogonal MPR are not reachable.
    - `viewer.set_layout` — present as `change_layout` but a **typed `NOT_IMPLEMENTED` stub**
      (`viewer_write_adapter.py:311-314`).
    - `resource://logs/latest` — no structured log resource/tool; logs are read via files +
      `count_native_faults_since`.

---

## 4. Should Secretary EchoMind own this — or only consume it?

**EchoMind should be a *consumer*, not the owner.** The evidence is decisive:

- The control plane already has **no meaningful EchoMind dependency**. `CommandBus`,
  `AdapterRegistry`, `command_envelope`, and `bus_factory` run with `orchestrator=None` and import
  no GUI/assistant code (`command_bus.py:39-49`, `bus_factory.py:18-27`). The only thing that ties
  them to EchoMind is the **directory they sit in**.
- The genuinely EchoMind-specific code is the **assistant**: `orchestrator.py`, `brain/*`,
  `validator.py`, `parser_*`, `repair_loop.py`, `memory/*`, `stt/*`, `config.py` (LLM model +
  prompt files only — `config.py:20-49`), `prompts/`, `catalog/`. That is the user-facing module.
- The **QA harness** (`test_server.py` + `tools/testing/aipacs_control_mcp/`) is a third concern
  that today is *physically split* — half inside `EchoMind/secretary/` (`test_server.py`), half in
  `tools/` (the MCP server). Both consume the same bus.
- The 2026-06-04 review already reached the same conclusion: *"Reuse, don't rebuild: the CommandBus
  + adapters are the control plane; the test server and MCP are thin transports around them"*
  (`TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md` §5).

So your instinct is correct: split into **(1) Agent Control Core**, **(2) EchoMind (consumer)**,
**(3) QA / Coding-Agent Harness (consumer)**. The good news is this is mostly a *re-home + add a
safety layer*, not a rewrite — ~80% of the control surface already exists.

**Caveat for a clinical app:** the physical move is the **riskiest, lowest-clinical-value** step.
The CLAUDE.md guardrails (preserve functionality, minimal safe edits, no unrelated refactors) mean
the *safety layer* (permissions, audit, channel auth) should land **first** and the directory move
should come later, behind re-export shims, flag-gated, with the existing tests kept green.

---

## 5. Recommended module structure

Target tree (your proposal, with current files mapped onto it):

```
modules/agent_control/
    core/
        command_bus.py        ← MOVE   from EchoMind/secretary/command_bus.py
        tool_registry.py      ← MOVE   (rename of registry.py / AdapterRegistry)
        command_envelope.py   ← MOVE   (CommandPlan/Request/Result = the tool schemas)
        contracts.py          ← MOVE   (split: keep BrainActionName in EchoMind)
        permissions.py        ← NEW    side-effect classes + permission levels + per-action policy
        audit_log.py          ← MOVE+EXTEND  wrap registry.dispatch so the BUS path logs
        session_manager.py    ← NEW    mode (read-only/test/assistant/qa/server-write/destructive) + scope/roots + correlation id
        resource_registry.py  ← NEW    read-only state → resource://… URIs
        prompt_registry.py    ← NEW    scenarios become first-class prompts
        sandbox.py            ← NEW    allowlist + scope enforcement, no raw shell/OS exec
    tools/
        patient_tools.py      ← MOVE   home_command_adapter + home_widget_adapter
        viewer_tools.py       ← MOVE   viewer_command_adapter + safe viewer_write subset
        mpr_tools.py          ← NEW/MOVE  open_mpr + (NEW) open_dental_curve_mpr, set_layout
        report_tools.py       ← MOVE   echomind_command_adapter (report open/save/send)
        status_tools.py       ← NEW    status.get / status.update_server_status
        attachment_voice_tools.py ← NEW  attachment.record_voice / list / sync
        screenshot_tools.py   ← NEW    viewer.capture_screenshot (promote from ui_probe)
        navigation_tools.py   ← MOVE   module_command_adapter + browser_command_adapter + education_command_adapter
        download_tools.py     ← MOVE   download_command_adapter
        system_tools.py       ← MOVE   system_command_adapter
    resources/
        current_patient_state, current_viewer_state, open_tabs_state, loaded_series_state,
        thumbnail_state, status_state, logs_state    ← NEW thin wrappers over existing read probes
    qa/
        workflow_runner.py    ← MOVE   run_scenario engine
        gui_test_harness.py   ← MOVE   test_server.py (QLocalServer)
        assertions.py         ← NEW    structured expect/assert + pass-fail report
        screenshot_compare.py ← NEW    baseline diff (built on ui_probe)

modules/EchoMind/                      (the user-facing assistant — CONSUMER)
    secretary/  orchestrator, brain/, validator, parser_*, repair_loop, memory/, stt/, catalog/, prompts/, config.py
        bus_factory.py  → calls modules.agent_control to build the bus  (or is handed one)
    # re-export shim: `from modules.agent_control.core import CommandBus, CommandPlan, …`
    # so every existing `from modules.EchoMind.secretary import CommandBus` keeps working.

tools/testing/aipacs_control_mcp/      (external MCP transport — CONSUMER)
    server.py   → adds @mcp.resource and @mcp.prompt; declares per-tool permission level
    client.py, lifecycle.py, ui_probe.py, scenarios/   (unchanged transport)
```

**Migration principle (non-negotiable for this codebase):** move with **re-export shims** in
`modules/EchoMind/secretary/__init__.py` (which already re-exports the whole control layer —
`__init__.py:15-26`) so no caller breaks; flag-gate every behavior change; keep
`tests/code/echomind/` and the bus tests green at each step.

---

## 6. Tool & resource inventory

### 6.1 Tools (executable, side-effecting) — current state

Side-effect legend: **R** read · **NAV** UI nav · **LW** local write · **SW** server/network write · **DESTR** destructive.

| Tool (proposed name) | Current action | Adapter / file | Side-effect | Runtime gate today |
|---|---|---|---|---|
| `patient.search` / `patient.list` | `list_patients` | home | SW (server search) | none on bus path |
| `patient.open` | `open_patient` | home | NAV/LW | confirm **voice path only** |
| `patient.select` | `select_patient` | home | NAV+R | none |
| `patient.download` | `download_patient` | home | SW | confirm **voice path only** |
| `patient.load_thumbnails` | (via `select_patient`) | home | NAV+R | none |
| `viewer.drop_series_to_viewport` | `change_series` | viewer_write (safe) | LW (may trigger DL) | none |
| `viewer.scroll_slices` | `scroll_slices` | viewer_write | LW | none |
| `viewer.switch_tab` | `switch_tab` | viewer_write | NAV | none |
| `viewer.set_layout` | `change_layout` | viewer_write | — | **stub (NOT_IMPLEMENTED)** |
| `viewer.close_patient_tab` | `close_patient_tab` | viewer_write | **DESTR** | **test-server only** (not in prod bus) |
| `viewer.open_mpr` | `open_mpr` → `mpr` launcher | modules | NAV | none |
| `viewer.open_dental_curve_mpr` | — | — | — | **MISSING** |
| `report.open_editor` | `start_report` | echomind | NAV+LW | none |
| `report.generate` | `generate_report` | echomind | LW (AI gen) | none |
| `report.send_to_pacs` | `send_report_to_pacs` | echomind | SW | **confirm + UI dialog** (only gated SW) |
| `report.transcribe_voice` | `transcribe_voice` | echomind | NAV+LW | none |
| `status.get` / `status.update_server_status` | — | — | — | **MISSING** |
| `attachment.record_voice` / `list` / `sync` | — | — | — | **MISSING** |
| `viewer.capture_screenshot` | — (external `ui_probe`) | — | R | **MISSING on bus** |
| `download.cancel` | `cancel_download` | download | **DESTR** | none |
| `download.pause` / `resume` | `pause/resume_download` | download | LW / SW | none |
| `module.open` / `toggle_eagle` / `open_printing` / `open_education` | `open_module`+aliases | modules | NAV | none |
| `browser.open` / `web_search` / `open_url` / back / fwd / refresh | browser actions | browser | NAV / SW | none |
| `education.open_consultation` / courses / case_of_day / search | education actions | education | NAV | none |
| `agent.login_website` | `login_website` | agent | SW | none |
| `agent.cancel_task` | `cancel_agent_task` | agent | DESTR | none |
| `app.launch` / `login` / `move_to_monitor` / `stop` | lifecycle | `lifecycle.py` | OS automation | source-build only |

### 6.2 Resources (read-only state) — exist as tools, should become `resource://…`

| Proposed resource | Current action | Adapter | Read source |
|---|---|---|---|
| `resource://app/current-screen` | (partial) `get_active_tab` | viewer | active tab study/patient/layout |
| `resource://patient/current` | `get_active_tab` | viewer | active patient/study |
| `resource://patient/list` | `list_patients` / `read_patient_rows` | home | last search rows |
| `resource://viewer/layout` | `query_viewport_state` | viewer_write | per-viewport state |
| `resource://viewer/active-viewports` | `query_viewport_state` | viewer_write | series/await/slice/spinner |
| `resource://viewer/loaded-series` | `get_active_series` / `get_series_info` | viewer / viewer_write | `_server_series_info` |
| `resource://viewer/thumbnails` | `get_thumbnails_data` | viewer | `lst_thumbnails_data` |
| `resource://patient/multistudy` | `get_multistudy_info` | viewer | `_studies_series` |
| `resource://patient/status` | — | — | **MISSING** |
| `resource://download/state` | `check_download_status` / `list_downloads` / `download_statistics` | download | DM store |
| `resource://app/health` | `snapshot_resources` / `count_native_faults_since` / `probe_idle_cpu` | system | psutil + native_fault.log |
| `resource://logs/latest` | — | — | **MISSING (structured)** |
| `resource://capabilities` | `list_actions` | bus | registered actions |

**Reading these is currently a "tool call."** Reclassifying them as MCP resources is the cleanest
fix for #3 and #4: resources are read-only by contract, so an agent (or a future read-only session
mode) can be allowed resources but denied tools.

---

## 7. Security / sandbox gaps

| # | Gap | Evidence | Risk | Suggested control |
|---|---|---|---|---|
| S1 | `needs_confirmation` ignored on the execution path | `command_bus.py:70-82`, `registry.py:79-112` | An agent performs SW/DESTR actions with no in-app gate | Enforce a permission/side-effect check **inside `registry.dispatch`** (single choke point) |
| S2 | No auth on the IPC channel | `test_server.py:163-185` | Any local process on the per-user pipe drives the full bus | Per-session token handshake; reject unauthenticated frames |
| S3 | No audit on bus/MCP/test path | `audit.py` only called from voice path | Agent mutations are unlogged in-app; no forensics | Wrap dispatch with `audit_log.start/end` + correlation id |
| S4 | No scope / roots | no such concept anywhere | Agent may touch any patient/study/screen/file | `session_manager` scope: allowed patient IDs / modules / screens |
| S5 | `raw_command` ungated arbitrary action | `server.py:96-99` | Bypasses any per-tool restriction | Allow only in `qa`/`developer` mode |
| S6 | Prompt-injection / unsafe tool trust | EchoMind brain plans from user/web/doc text; bridge in progress | Injected text could trigger a side-effect action | Confirmation required for all SW/DESTR; allowlist tools; never auto-confirm |
| S7 | Destructive actions not isolated by policy | `cancel_download`, `download_patient`, `send_report_to_pacs` in prod bus | One mis-plan = clinical side-effect | `destructive` tier requires explicit session mode + confirm |
| S8 | No timeout/rate policy per tool in-app | MCP sets client timeouts (`server.py`); bus has none | A slow/looping tool can stall the Qt thread | Per-action timeout + the existing 1-cmd/event-loop drain |

**What is already done well (keep):** env-gate + frozen-build refusal + per-user socket
(`test_server.py:207-214`); **production-code-path fidelity** so clinical isolation/multi-study
guards still run; the read-only discipline of `viewer_command_adapter` (:1-14); `close_patient_tab`
kept out of the production bus (`bus_factory.py:207-211`); no arbitrary shell/OS exec on the bus
(lifecycle automation is a separate, source-build-only concern). Net: the *safety posture* is
"off-by-default + frozen-refusal + production guards" — solid for a QA tool, **insufficient for an
in-app end-user assistant** that will run while clinicians read studies.

---

## 8. QA-agent readiness score

Target QA loop: open app → search → open patient → load thumbnails → drag/drop series → open MPR →
open Dental Curve MPR → screenshot → verify state → read logs → pass/fail.

| Sub-capability | Score | Basis |
|---|---|---|
| App lifecycle (launch/login/monitor) | 9/10 | `lifecycle.py` solid; Windows-only; source-build-only |
| Patient workflow (search/open/select/download) | 9/10 | All four actions exist + verified |
| Thumbnail load + verify | 8/10 | `select_patient` + `get_thumbnails_data` / `query_thumbnail_state` |
| Viewer control (drag series, switch, scroll) | 7/10 | Works at **T1 state level**; `change_layout` stub; real OLE drag is T3/pywinauto only |
| MPR / advanced viewers | 5/10 | `open_mpr` only; **Dental-Curve / Curve / Orthogonal not exposed**; many catalog actions unimplemented |
| State verification ("resources") | 8/10 | Rich read probes; not modeled as MCP resources; no log resource |
| Screenshot / visual capture | 4/10 | External `ui_probe` (mss) + computer-use only; **no in-bus tool**; no `screenshot_compare` |
| Assertions / pass-fail report | 3/10 | Only scenario `allow_fail` + `assert_health`; no assertion library / structured report |
| Log access | 5/10 | File reads + `count_native_faults_since`; no structured log resource |
| Audit / repeatability of QA runs | 5/10 | MCP session JSONL exists; no in-app audit; scenarios are deterministic/seeded (good) |

**Composite QA-agent readiness ≈ 6 / 10.** The happy-path *control* (open → search → open →
thumbnails → drag → MPR → verify-by-state) is largely done at high fidelity; the *verification &
reporting* half (visual capture, assertions, structured logs, audit) and a few *tools* (Dental
Curve MPR, screenshot, set_layout) are the gap.

**End-user-assistant (EchoMind) readiness ≈ 5 / 10:** voice/text reaches only ~9 actions
(`validator._ALLOWED_ACTIONS`); the bridge to the full bus is partially wired (echomind/browser/
education/safe-viewer-write adapters added 2026-06-06/06-11) but the orchestrator→bus routing for
arbitrary actions and the bus-path confirmation gate are incomplete.

---

## 9. Documentation gaps

`docs/agent_control/` **does not exist.** Equivalent content is scattered:

| Requested doc | Status | Where it lives now |
|---|---|---|
| `overview.md` | Exists (mislocated) | `docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md` |
| `tools.md` | Exists (split) | `tools/testing/aipacs_control_mcp/README.md` + `TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md` §4.2 + adapter tables |
| `resources.md` | **Partial** | read probes scattered across adapter docs; no first-class catalog |
| `security.md` | **Partial** | hard rules in the guide §6 + test-server gates §4.1; **no consolidated permission-model doc** |
| `qa_workflows.md` | Exists | guide §4/§7 + `AIPACS_LAUNCH_CONTROL_RUNBOOK.md` + scenarios |
| `secretary_eco_mind_integration.md` | Exists (as a gap analysis) | `SECRETARY_ECHOMIND_PIPELINE_REVIEW_2026-06-06.md` |

**Missing entirely:** a single permission/mode-model spec (read-only / test / assistant / QA /
server-write / destructive), a resources catalog, and per-tool spec sheets (name, input schema,
output schema, side-effect class, permission, timeout, error format, confirmation requirement).

---

## 10. Prioritized implementation roadmap

Sequenced by **clinical-safety value ÷ risk**, respecting the CLAUDE.md rules (flag-gated, minimal,
reversible, tests green). Do **not** start with the directory move.

### P0 — Safety layer on the existing bus (high value, low risk, no move)
- **P0.1 Permission/side-effect enforcement at the single choke point.** Add `permissions.py`
  (side-effect class + permission level per action) and have `registry.dispatch` consult it +
  honor `CommandPlan.needs_confirmation` before calling the method. Flag `AIPACS_AGENT_PERMISSIONS`
  (default-on once validated). Reuse the catalog's existing `side_effects`/`confirmation_required`
  metadata as the seed.
- **P0.2 Audit on the bus path.** Wrap `dispatch` with `audit_log.start/end` + a correlation id
  carried from the MCP server through `test_server.py`. Reuse `audit.py`'s DB sink.
- **P0.3 Channel auth + mode.** Add a per-session token handshake to `test_server.py`; tag each
  session with a **mode** (`read_only` / `qa` / `assistant` / `server_write` / `destructive`).
  Gate `raw_command` and all DESTR/SW actions on mode. Keep env-gate + frozen-refusal.
- **P0.4 Confirmation for all SW/DESTR.** Extend `_BUS_CONFIRM_REQUIRED_ACTIONS` enforcement to the
  bus path (currently voice-only) so injected/auto plans can't silently mutate.

### P1 — Capability + verification completeness (medium)
- **P1.1 MCP resources.** Add `@mcp.resource(...)` for the §6.2 read-state set; reclassify reads
  off the tool list. Enables a true read-only session.
- **P1.2 MCP prompts.** Promote `scenarios/*.json` to first-class `@mcp.prompt(...)`.
- **P1.3 Missing tools:** `viewer.capture_screenshot` (promote from `ui_probe`), `status.get` /
  `status.update_server_status`, `attachment.record_voice` / `list` / `sync`,
  `viewer.open_dental_curve_mpr` (+ Curve / Orthogonal launchers), finish `viewer.set_layout`.
- **P1.4 QA harness:** `assertions.py` + structured pass/fail report + `screenshot_compare.py`
  baseline diff. Add a `resource://logs/latest` tail.
- **P1.5 Reconcile catalog ↔ contracts ↔ adapters** so the LLM cannot plan unimplemented actions
  (`contracts.BrainActionName` vs registered actions).

### P2 — Structural re-home (higher risk, do last, behind shims)
- **P2.1 Create `modules/agent_control/`**, move the control plane, leave re-export shims in
  `EchoMind/secretary/__init__.py`. No behavior change; tests stay green.
- **P2.2 `session_manager` + scope/roots** (which patients/modules/screens a session may touch).
- **P2.3 Consolidate the two action-declaration conventions** onto one (decorator or single dict),
  with the registry as the source of truth instead of `bus_factory`.
- **P2.4 Finish the EchoMind orchestrator→bus bridge** so the assistant consumes the same tools
  (closes the W1 split) — now safe because P0 added the gates.

### P3 — Documentation
- Create `docs/agent_control/{overview,tools,resources,security,qa_workflows,secretary_eco_mind_integration}.md`
  with per-tool spec sheets (name, input/output schema, side-effect class, permission, timeout,
  error format, confirmation, audit). Fold in the existing guide + reviews.

---

## Appendix A — Files reviewed (evidence base)

**Control spine (read directly):** `modules/EchoMind/secretary/`{`command_bus.py`, `registry.py`,
`command_envelope.py`, `contracts.py`, `bus_factory.py`, `config.py`, `audit.py`, `confirm.py`,
`__init__.py`}.

**Adapters (sub-audit):** `adapters/`{`agent`, `browser`, `download`, `echomind`, `education`,
`home_command`, `home_widget`, `module`, `system`, `viewer_command`, `viewer_write`}`_adapter.py`,
plus `module_map.yaml`, `catalog/catalog.yaml`, `catalog/modules/*.md`, `validator.py`,
`executor.py`, `orchestrator.py`.

**MCP / test layer (sub-audit):** `tools/testing/aipacs_control_mcp/`{`server.py`, `client.py`,
`lifecycle.py`, `ui_probe.py`, `README.md`, `scenarios/*.json`}, `modules/EchoMind/secretary/test_server.py`,
`PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py`.

**Docs (sub-audit):** `docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md`,
`docs/reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md`,
`docs/reports/SECRETARY_ECHOMIND_PIPELINE_REVIEW_2026-06-06.md`,
`docs/AIPACS_LAUNCH_CONTROL_RUNBOOK.md`, `modules/EchoMind/secretary/`{`AGENT_BRAIN_ROADMAP.md`,
`LLM_COMMAND_SYSTEM_IMPLEMENTATION_PLAN.md`, `LLM_PROMPT_STRUCTURE_GUIDE.md`}.

## Appendix B — The single most important code fact

```python
# command_bus.py:70-82  — the execution entry point
def execute(self, plan, state=None) -> CommandResult:
    if isinstance(plan, dict):
        plan = CommandPlan.model_validate(plan)
    result = self.registry.dispatch(plan, state or {})   # ← no permission/confirm/audit
    ...

# registry.py:97-99 — the only universal choke point
adapter_name, method = self._actions[plan.action]
raw = method(plan, state)                                # ← calls the real app function directly
```

`CommandPlan` *carries* `needs_confirmation` (`command_envelope.py:36`) but **nothing on this path
reads it.** Putting the permission/side-effect/confirm/audit checks **here** (P0) is the
highest-leverage, lowest-risk change in the whole roadmap: one function, every caller covered.

---

## Appendix C — Implementation status (P0 landed 2026-06-23)

The P0 safety layer is implemented and offscreen-verified (NOT yet live-verified on the
Windows source build, and NOT yet wired to any caller — see "Pending" below). All changes are
flag-gated and behavior-preserving.

**Files:**
- **NEW** `modules/EchoMind/secretary/permissions.py` — pure stdlib policy: side-effect classes
  (`READ_ONLY`/`UI_NAV`/`LOCAL_WRITE`/`SERVER_WRITE`/`DESTRUCTIVE`), session modes
  (`unrestricted`/`read_only`/`assistant`/`qa`/`server_write`/`destructive`), the
  `ACTION_SIDE_EFFECTS` classification map (seeded from §6.1), and `classify()` / `decide()`.
- **EDIT** `registry.py` — `dispatch()` now consults `permissions.decide(...)` at the single
  choke point (after the UNKNOWN_ACTION check, before calling the adapter method), returning
  `PERMISSION_DENIED` / `CONFIRM_REQUIRED` without running the method, and emits a best-effort
  audit line on every dispatch. Guarded by `_PERMISSIONS_ENABLED` (env `AIPACS_AGENT_PERMISSIONS`,
  default-on; `=0` → byte-identical legacy dispatch).
- **EDIT** `audit.py` — `record_bus_action()`: best-effort, never-raising structured audit for the
  bus/MCP/test-server path (logger `aipacs.agent_control.audit`).
- **NEW** `tests/code/echomind/test_agent_permissions.py` — 11 guard tests.

**Safety contract (must not be broken):**
1. The gate is **inert** unless the caller sets `state["agent_mode"]` to a restrictive mode
   (mode `unrestricted` = today's behavior; `plan.needs_confirmation` is honored only in a
   restrictive mode). Every current caller (voice executor `executor.py:407`, test server
   `test_server.py:184`, direct `bus.execute`) passes no mode → unaffected.
2. **Fail-open on internal policy error** (a bug in `permissions` must never wedge a clinical
   action) and **fail-closed on an unknown *explicit* mode** (→ `read_only`).
3. Kill switch `AIPACS_AGENT_PERMISSIONS=0`.

**Verification:** 11/11 green offscreen (pure policy + `registry.dispatch` integration: denied
under `read_only`, confirm under `assistant`, allowed under `unrestricted`/`qa`, method never runs
when denied/unconfirmed, flag-off byte-identical, unknown action unchanged). The sandbox FUSE
mount served torn copies of the two just-edited files, so the suite was run against a faithful
local-fs copy; the **canonical `pytest tests/code/echomind` run must be done on Windows**, and the
existing echomind suites re-confirmed green there.

### Caller wiring (added 2026-06-23, same session)

- **Test Control Server → `qa` (ACTIVE).** `test_server.py::_execute` now calls
  `bus.execute(plan, {"agent_mode": mode})`, default `qa`, per-request overridable
  (e.g. a client may send `{"mode": "read_only"}` for safe exploration). `qa` allows every action
  with no confirmation pause, so the QA harness is **behaviourally identical** to before — now
  gated and audited as `mode=qa`. This activates the permission gate on the coding/QA-agent
  channel (use case #2). Needs a live source-build run to confirm the harness + scenarios behave
  identically.
- **Voice assistant → `assistant` (STAGED, default OFF).** `executor.py::_try_command_bus` now
  propagates `confirmed` into a per-call bus state and stamps `agent_mode="assistant"` only when
  `AIPACS_AGENT_ASSISTANT_MODE=1` (default off → no mode → gate inert → byte-identical to today).
  When enabled, server-write actions route through the **existing** `CONFIRM_REQUIRED` confirm
  turn (the orchestrator already stores the pending plan and re-runs with `confirmed=True`), and
  destructive actions are denied for the assistant. Enabling it is a **behavior change** and a
  live-verification item — including a policy call (e.g. should the assistant be allowed to
  `cancel_download`? it is `destructive` today).
- `qa` / `read_only` / `unrestricted` modes now never pause on `plan.needs_confirmation` (only
  `assistant` / `server_write` / `destructive` do), so a stray flag cannot wedge the automated
  harness. Guard test count: **12** (added the qa-ignores-confirmation case).

**Still pending (needs live verification / later phases):**
- Live-verify on the Windows source build: the `qa` wiring (harness + the two scenario JSONs behave
  identically) and, once enabled, the `assistant` wiring (confirm UX for server-write, destructive
  policy).
- Channel auth/token on `test_server.py` (S2) — any local process can still open the per-user pipe.
- MCP `resources` / `prompts`, the missing tools (screenshot / status / attachment / dental-curve
  MPR), and the optional re-home to `modules/agent_control/` (P1/P2/P3).

---

## Appendix D — Multi-step workflow engine + docs + viewer fix (2026-06-23)

**Multi-step task execution (the "download and open it → only downloads" bug).** Root cause: the
brain plans one action per utterance and `orchestrator._run_plan` runs one plan (confirmed live on
patient 47734 — the LLM logged *"only one action is allowed so I prioritized download"*).

- **NEW** `modules/EchoMind/secretary/workflow.py` (pure stdlib): `WorkflowPlan` / `WorkflowStep` /
  `VerifySpec` / `WorkflowExecutor(run_step, sleep)` — runs steps in order, **verifies each step**
  against existing read actions (`check_download_status` / `get_active_tab` / `get_thumbnails_data`
  / `query_viewport_state`) before advancing, threads context (`"$patient_id"` from an earlier
  step), retries async effects, and **stops on the first failed step**. Plus `decompose()` for the
  documented compound commands. Injectable → drives both the voice path (`executor.execute`) and the
  MCP path (`bus.execute`). Flag `AIPACS_SECRETARY_WORKFLOWS`.
- **NEW** `tests/code/echomind/test_workflow.py` — 7 tests, green offscreen (sequential exec,
  stop-on-failed-verify so a second step never runs, context threading, async retry, decompose).
- The engine sequences tools that **already exist**, so "download → open" and "download → open →
  load first series" work at the logic level today. The only NEW capability is ordering +
  verification.

**Documentation** — created `docs/agent_control/`: `tools.md` (inventory + Available/Partial/Staged
gap map), `workflows.md`, `patient_tab_viewer.md`, `secretary_echo_mind_instruction_map.md`,
`qa_workflows.md`.

**Isolated viewer fix (separate subsystem, not mixed with the MCP work).**
`modules/viewer/interactor_styles/abstract_interactorstyle.py`: the three mouse-wheel handlers
called `obj.AbortFlagOn()` but `obj` is the interactor *style* (no such method) → every wheel tick
raised `AttributeError` into VTK's observer handler (log spam, found during the 2026-06-23 log
review). Guarded with `if hasattr(obj, "AbortFlagOn")` — behavior-preserving (Qt handles slice
navigation regardless), stops the spam. Needs a quick live wheel-scroll confirm.

**Brain multi-step planning (IMPLEMENTED same day, flag-gated `AIPACS_SECRETARY_WORKFLOWS`).** The
general, language-agnostic solution: the brain emits the steps, deterministic code validates +
executes + verifies them.
- **NEW** `brain/multistep.py` (pure): `to_brain_plan` (single vs `__workflow__`), `to_workflow_plan`.
- **NEW** `workflow.build_plan` / `make_step` / `DEFAULT_VERIFY` — enrich a bare action list with the
  right verify + capture per action.
- **NEW** `validator.validate_steps` — per-step validation reusing `validate_plan`.
- **EDIT** `brain/agent.py` — `_normalize_multistep`: flag-on + ≥2 steps → `__workflow__`; **flag-off
  → collapses to the FIRST action (byte-identical to today)**, so the prompt change is safe either
  way. `plan()` validates steps.
- **EDIT** `orchestrator.py` — flag-gated early branch runs the `__workflow__` plan via
  `WorkflowExecutor` (run_step = `executor.execute(..., confirmed=True)`), confirming ONCE up front
  via a new `confirm_workflow` pending state. Single-action path untouched when off.
- **EDIT** `prompts/agent_phase2_prompt.txt` — multi-step output contract + EN/FA examples.
- **NEW** `tests/code/echomind/test_brain_multistep.py`. Offscreen: build_plan + multistep parsing
  green (4); `validate_steps` logic confirmed (2 ran against a torn-mount-truncated `validator.py`,
  not a code defect — `validate_plan` verified present at line 396). All six edited modules
  **compile on Windows** (authoritative, via Desktop Commander).

**Still staged (needs the source build):** the LLM actually emitting steps + end-to-end execution +
confirm-once UX (set `AIPACS_SECRETARY_WORKFLOWS=1` and say *"download this patient and open it"*),
and the new GUI tools in `patient_tab_viewer.md` (drop-by-UID, window/level, screenshot, dental-curve
MPR, toolbar, explicit layout). The engine + verification logic (criteria 7, 8) are proven offscreen.
