# For Future Agents — Working in the AI-PACS Repository

If you're an AI agent (Claude Code, GitHub Copilot, Devin, etc.) opening this repo for the first time, **read this page top to bottom before touching code**. It will save you and the user a lot of time.

---

## 0. The framework's discipline

**Workstream ownership (user decision, 2026-09-16):** Unify owns shared coordination,
identity/catalog/thumbnail presentation and data handoff, not viewer-specific decoding,
filters, rendering or decoded-cache internals. Fast, Advanced and individual VTK tools
retain separate execution domains. Read the [two-way handoff contract](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#02-workstream-ownership-and-two-way-handoff-user-decision-2026-09-16)
before acting on a finding from another conversation. Record it in the destination
owner's existing document with a backlink; do not implement competing fixes or sync
another task's unfinished mirrors. These are shared repository records, not evidence
that an external cloud document or conversation has automatically synchronized.

**Single active Unify queue (2026-09-18):** continue shared-pipeline work only through
the [U0-U5 execution ledger](../plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md#current-execution-ledger---2026-09-18).
The master plan owns priority/status; reports append evidence only. Do not start a new
plan, skip an acceptance gate, or implement two shared-trunk behavioral slices in
parallel. A failed gate extends its existing owner and regression guard. Native shutdown
failure pauses the queue and is routed to the crash audit rather than guessed to be a
thumbnail, download or viewer cause.

**Persistent verification rule (user decision, 2026-09-14):** every runtime fix/Unify slice
requires both automated code tests and a live source-GUI pass. Read section 0 of
[`AGENT_CONTROL_AND_TESTING_GUIDE.md`](./AGENT_CONTROL_AND_TESTING_GUIDE.md) for the current
MCP/CLI attachment procedure, multi-study case discovery, input-fidelity gaps and evidence
receipt. Probe the existing bridge before delegating the whole workflow to the human.
The human bootstraps one source instance; unavailable live control is recorded as BLOCKED,
not PASS. Older counts, Linux-only assumptions and lifecycle examples below are historical;
current `AGENTS.md` and the readiness report govern test execution and safety.

Every fix in this repo ships three things together:

1. **The code change itself** (minimal, local, safe).
2. **A structural guard test** under `tests/code/system/` or `tests/code/<domain>/`. The test must FAIL on the pre-fix code and PASS on the fixed code.
3. **A row in `docs/plans/architecture/REGRESSION_CATALOG.md`** documenting the date, module, bug summary, and the guard test that prevents its return.

If your change doesn't fit this pattern, you're probably making a refactor rather than a fix. Read the [project CLAUDE.md](../../CLAUDE.md) before continuing.

---

## 1. First five minutes — what to read

> **Need to control or test the running app?** Read
> [`AGENT_CONTROL_AND_TESTING_GUIDE.md`](./AGENT_CONTROL_AND_TESTING_GUIDE.md). **The fastest way to
> control the app is the in-app command surface (`aipacs-control` MCP → EchoMind CommandBus), not
> pixel-clicking — see §3.1.** The guide also covers the offscreen **sandbox test lane**, logs, the
> tool tiers, and the hard rules.

In this order:

1. **[`../../CLAUDE.md`](../../CLAUDE.md)** — the project rules (which build to run, never use the frozen exe, the regression-sensitive subsystems, the human-assisted bootstrap mode).
2. **[`../release-and-build/README.md`](../release-and-build/README.md)** — the map for Git, build, backend details, outputs, and release evidence.
3. **[`../../RELEASE.md`](../../RELEASE.md)** — the only versioned commit/tag/multi-remote push route and the prerequisite for full builds.
4. **[`../../BUILD.md`](../../BUILD.md)** — the only combined PyInstaller/Nuitka release-build route.
5. **[`../README.md`](../README.md)** — top-level docs README.
6. **[`../AUDIT_2026-05-28_OVERVIEW.md`](../AUDIT_2026-05-28_OVERVIEW.md)** — the staged-audit narrative + cumulative numbers.
7. **[`../INDEX_BY_SUBSYSTEM.md`](../INDEX_BY_SUBSYSTEM.md)** — given a subsystem name, which docs and tests apply.
8. **[`../../tests/QUICKSTART.md`](../../tests/QUICKSTART.md)** — how to run tests; the hard rules.
9. **[`../../tests/INDEX_BY_GUARD.md`](../../tests/INDEX_BY_GUARD.md)** — given a test name, what it protects.

---

## 2. The four high-value rituals

### 2.1 Before you touch anything

```bash
# Run the sandbox-safe sweep — should be 121 / 0 / 0
QT_QPA_PLATFORM=offscreen PYTHONPATH=. pytest tests/code/echomind tests/code/system \
    --ignore=tests/code/system/test_system_stress.py -q

# Read the health dashboard
PYTHONPATH=. python3 tools/kpi_dashboard.py
```

If the sweep isn't green or the dashboard reports new warnings, **stop and investigate** before making any change. You're on a broken baseline.

### 2.2 When you find a bug

1. Reproduce it. If you can't reproduce, **don't fix** — it might already be fixed or environmental.
2. Identify the root cause. Don't fix symptoms.
3. Write the structural guard FIRST. Confirm it fails on the bug.
4. Apply the minimal fix.
5. Confirm the guard now passes.
6. Add the catalog row.
7. Run the full sweep one more time.

### 2.3 When you add a new test

- Code-only headless tests → `tests/code/<domain>/test_*.py`. Must run under `QT_QPA_PLATFORM=offscreen`.
- Cross-cutting structural guards → `tests/code/system/test_<scope>_guard.py`.
- Bus-driven scenarios → `tests/gui/echomind_driven/test_*.py`.
- Real Win32 UI Automation → `tests/gui/pywinauto/test_*.py`. **Must call `_verify_source_build.require_source_build()` as the first action.**

### 2.4 When you add a new KPI

1. Register the key in `tests/_kpi/schema.py` with workflow + unit + warn/hard thresholds.
2. The schema-integrity test in `tests/code/system/test_kpi_schema.py` will catch typos.
3. Emit it via the `kpi` pytest fixture or hook the bus with `KpiCollector.hook_bus(bus)`.
4. After a few runs, update `tests/_kpi/baseline.json` with the last-known-good value.

---

## 3. Critical knowledge — read once, remember forever

### 3.1 Which build to run

**Always the source build, launched from VS Code's Play button on `main.py`.** Never the installed `aipacs.exe`, never the desktop icon, never the black AI-PACS taskbar icon. The source build's taskbar icon is the **Python snake icon**.

The frozen build does NOT contain uncommitted source changes — testing it does not test your fix.

### 3.2 Which port for thumbnails

Thumbnail/patient sockets use the **socket-protocol port** from `config/socket_config.json` (e.g. `50052`), resolved via `get_socket_server_settings()`. Do NOT use the `port` field from `config/servers.json` (e.g. `105`) — that's the DICOM port and feeding it to the socket client makes thumbnail fetches hang for ~45 s.

### 3.3 Which transport is live

**Socket, not gRPC.** `GrpcMetadataClient` is socket-backed despite the name. The gRPC stack in `modules/network/` (`grpc_client.py`, `dicom_downloader*.py`, etc.) is dead. Don't reconnect it.

### 3.4 Which database path for test isolation

Patch `PacsClient.utils.data_paths.DATABASE_FILE`. Patching `database.core._DB_PATH` does nothing — the live pool resolves the path from `data_paths` via an in-function import. Also: clear `database._pool._connection_pool` under `database._pool._pool_lock` so pooled connections don't survive the patch.

### 3.5 The multi-study viewer invariants

Read [`MULTI_STUDY_SINGLE_TAB_PLAN.md`](../MULTI_STUDY_SINGLE_TAB_PLAN.md) before editing the viewer sidebar, `_vc_load.py`, `_vc_switch.py`, `thumbnail_manager.py`, or the right-panel thumbnails. Series numbers can repeat across studies; offset keys (`study_slot * 1_000_000 + original_series_number`) keep them distinct. Single-study patients must run the original (non-multi-study) code path unchanged.

### 3.6 Drag-drop & COM 0x8001010d

The Eagle Eye MG/DX drag-drop path uses `QTimer.singleShot(0, _do_mirror)` to release the OLE/COM context. Any future drag-drop work that runs synchronous code after a primary series switch must use the same defer pattern. The regression catalog row + `test_mg_mirror_is_deferred_via_qtimer` + the pywinauto OLE drag-drop test together cover it.

The normal in-app drop path (`_vw_dragdrop.py:dropEvent`) already uses the same defer. **Don't remove it.**

### 3.7 Thumbnail native safety and source worker windows

The 2026-09-01 `0xc0000374` crash ended in
`ThumbnailManager.create_thumbnail_widget` while a late, unscoped root
stylesheet recursively repolished a completed card subtree. Keep the scoped
`QWidget#seriesThumbnailCard` style before layouts, child widgets, graphics
effects, and event filters. Read
[`THUMBNAIL_HEAP_CRASH_AND_WINDOWS_SPAWN_FLASH_2026-09-01.md`](../reports/THUMBNAIL_HEAP_CRASH_AND_WINDOWS_SPAWN_FLASH_2026-09-01.md)
before changing card construction.

Windows source runs must configure multiprocessing through
`PacsClient.utils.windows_multiprocessing.configure_hidden_multiprocessing`
before `freeze_support()`. A `.venv/Scripts/pythonw.exe` is a redirector and
must never be selected: its extra process hop breaks shared Event/semaphore
handles and caused download workers to fail with WinError 5. Supported `.venv`
source runs retain Python's default spawn executable. Only a direct, non-venv
`python.exe` may select its direct `pythonw.exe` sibling. Frozen/installed
builds must remain unchanged.

Multiprocessing bootstrap policy does **not** cover embedded Qt viewer
replacement. Live verification on 2026-09-01 showed the FAST flash remained
independent of worker executable selection. The drop intentionally rendered
a one-frame preview and then promoted it to the complete series. During each
replacement, `QtFastContainer` detached the old visible `QtSliceViewer` with
`setParent(None)` before `deleteLater()`, briefly making it a Windows top-level
widget. Keep both bridge-install paths routed through
`_retire_embedded_viewer_widget`: hide, retain the container parent, then defer
deletion. Do not deduplicate the valid Preview -> Complete promotion.

---

## 4. Things to NEVER do

- **Never run the frozen build** (`d:\ai-pacs\aipacs\aipacs.exe`) to test source changes.
- **Never spawn multiple AI-PACS instances** — press Play once and wait.
- **Never use `setFixed*`** when `setMinimum*` + `setMaximum*` would do; Qt layout is more flexible.
- **Never patch `database.core._DB_PATH`** — see 3.4.
- **Never bypass the structural guard discipline** — code without a guard test eventually regresses.
- **Never use `print()` for error paths** in the home-panel mixins (`_hp_*.py`) — see Stage 2 + Stage 10 audits. Use `_logger.error(... exc_info=True)` so failures reach `app.log`.

---

## 5. The most common mistakes (from this audit session)

| Mistake | Symptom | Fix |
|---|---|---|
| Calling `setHorizontalScrollMode` on a `QScrollArea` | Silent fallback to non-scrolling container; chip overlap on narrow monitors | Use `horizontalScrollBar().setSingleStep(N)` |
| Setting `setMinimumHeight` without `setMaximumHeight` + Fixed vertical policy | Qt's Preferred/Preferred grows the widget unboundedly | Add the ceiling + Fixed policy |
| Using `print()` in error paths | Messages go only to stderr; invisible in `app.log` | Use `_logger.error(..., exc_info=True)` |
| Letting `data` be `dict\|list\|None` only | Scalar payloads from adapters fail Pydantic validation | Widen to `data: Any = None` |
| Trusting the test file to be unique by content | False uniqueness errors when the same f-string appears twice | Replace with count = -1 or grep the literal first |

---

## 6. Where to ship documentation

Cloud/recovered decisions must be curated through
[`CLOUD_DECISION_LEDGER.md`](./CLOUD_DECISION_LEDGER.md). Never bulk-copy transcripts or raw
clinical logs into the repository; current code/tests remain authoritative.

- **As-built plans for new subsystems** → `docs/plans/<category>/`
- **Audit reports** → `docs/plans/architecture/AUDIT_*_<date>.md`, plus a row in [`../AUDIT_2026-05-28_OVERVIEW.md`](../AUDIT_2026-05-28_OVERVIEW.md)
- **Conventions** (Qt patterns, naming, layout primitives) → `docs/conventions/`
- **Pipelines** (data flow contracts) → `docs/pipelines/`
- **Subsystem references** → `docs/modules/` or `docs/viewer/`

When you add a doc, link it from `docs/INDEX_BY_SUBSYSTEM.md` so future agents find it.

---

## 7. Where to ship tests

- **Headless code tests** → `tests/code/<domain>/test_*.py`
- **Cross-cutting structural guards** → `tests/code/system/test_<scope>_guard.py`
- **Bus-driven scenarios** → `tests/gui/echomind_driven/test_*.py`
- **Live Win32 UI Automation** → `tests/gui/pywinauto/test_*.py`

When you add a test, link it from `tests/INDEX_BY_GUARD.md` so future agents know what it covers.

---

## 8. Final tip — the user is your collaborator, not your auditor

The user has invested significant time in this framework's discipline. When you ship a fix:

- **Show the diff** in the first response, not the conclusion.
- **Run the guard test** and paste the output.
- **Add the catalog row in the same change**.
- **Mark task list completion** as you go (`TaskCreate` / `TaskUpdate`).

This matches the rhythm of the existing audit reports. Read three of them — Stage 2 / Stage 9 / Stage 10 are good representative samples — to internalize the format.

Welcome aboard.
