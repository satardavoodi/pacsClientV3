# For Future Agents — Working in the AI-PACS Repository

If you're an AI agent (Claude Code, GitHub Copilot, Devin, etc.) opening this repo for the first time, **read this page top to bottom before touching code**. It will save you and the user a lot of time.

---

## 0. The framework's discipline

Every fix in this repo ships three things together:

1. **The code change itself** (minimal, local, safe).
2. **A structural guard test** under `tests/code/system/` or `tests/code/<domain>/`. The test must FAIL on the pre-fix code and PASS on the fixed code.
3. **A row in `docs/plans/architecture/REGRESSION_CATALOG.md`** documenting the date, module, bug summary, and the guard test that prevents its return.

If your change doesn't fit this pattern, you're probably making a refactor rather than a fix. Read the [project CLAUDE.md](../../CLAUDE.md) before continuing.

---

## 1. First five minutes — what to read

In this order:

1. **[`../../CLAUDE.md`](../../CLAUDE.md)** — the project rules (which build to run, never use the frozen exe, the regression-sensitive subsystems, the human-assisted bootstrap mode).
2. **[`../README.md`](../README.md)** — top-level docs README.
3. **[`../AUDIT_2026-05-28_OVERVIEW.md`](../AUDIT_2026-05-28_OVERVIEW.md)** — the staged-audit narrative + cumulative numbers.
4. **[`../INDEX_BY_SUBSYSTEM.md`](../INDEX_BY_SUBSYSTEM.md)** — given a subsystem name, which docs and tests apply.
5. **[`../../tests/QUICKSTART.md`](../../tests/QUICKSTART.md)** — how to run tests; the hard rules.
6. **[`../../tests/INDEX_BY_GUARD.md`](../../tests/INDEX_BY_GUARD.md)** — given a test name, what it protects.

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
