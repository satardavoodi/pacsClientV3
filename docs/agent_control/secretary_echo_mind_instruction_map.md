# Secretary EchoMind — intent → tool map

**Status:** 2026-06-23. Tells Secretary EchoMind which agent-control action(s) to call for each
user intent, and which read action verifies success. Single-action intents use the legacy path;
compound intents use the **workflow engine** (`workflows.md`).

> Language note: the live UI is primarily **Persian**. The brain already understands the intent
> (Phase-1 routing was correct for all six live test orders on 2026-06-23); the mapping below is
> what each understood intent should call.

## Single-action intents

| User intent (EN / FA example) | Call | Verify with |
|---|---|---|
| "Show today's MRI patient list" / "لیست بیماران ام‌آر‌آی امروز" | `list_patients {modality, date, source}` | result rows non-empty |
| "Open this patient" / "این بیمار را باز کن" | `open_patient {patient_code}` (confirm) | `get_active_tab` patient matches |
| "Download this patient" / "این بیمار را دانلود کن" | `download_patient {patient_code}` (confirm) | `check_download_status` complete |
| "Select / show thumbnails" | `select_patient {patient_id}` | `get_thumbnails_data` non-empty |
| "What patient is open?" | `get_active_tab` | — (read) |
| "List the series" | `get_series_info` / `get_thumbnails_data` | — (read) |
| "Load the first series into the viewport" | `change_series {series_index: 0, viewport: 0}` | `query_viewport_state` shows series |
| "Drag this series into viewport 2" | `change_series {series_number: N, viewport: 1}` *(by-UID variant 🟧)* | `query_viewport_state` viewport 1 has series |
| "Open MPR" | `open_mpr` | `list_open_tabs` / module opened |
| "Open Dental Curve MPR" | `viewer.open_dental_curve_mpr` 🟧 (staged) | — |
| "Open the report editor" | `start_report` | report page open |
| "Send the report to PACS" | `send_report_to_pacs` (confirm + in-app dialog) | reception dialog |
| "Pause/Resume/Cancel download" | `pause_download` / `resume_download` / `cancel_download` | `check_download_status` |

Viewport-numbering convention: user "viewport 1/2" → zero-based `viewport: 0/1`.

## Compound intents → workflow (run all steps, verify each)

| User intent | Steps (each verified before the next) |
|---|---|
| "Download this patient and open it" | `download_patient` → *verify download_complete* → `open_patient` → *verify patient_open* |
| "Download, open, and load the first series" | `download_patient` → `open_patient` → `get_thumbnails_data` → `change_series {series_index:0}` (each verified) |
| "Open this patient and load series 3" | `open_patient` → `get_thumbnails_data` → `change_series {series_index:2}` |

The assistant should NOT collapse a compound request to a single action (the old behavior). It
builds a `WorkflowPlan` and runs it; if a step fails verification it reports which step and stops.

## Permission behavior the assistant must respect

- Runs in **`assistant`** mode (when `AIPACS_AGENT_ASSISTANT_MODE=1`): `open_patient` /
  `download_patient` / `send_report_to_pacs` are server-write/local actions that take a **confirm
  turn** (reply "yes"/"بله"). Destructive actions (e.g. `cancel_download`) are **denied** to the
  assistant by default — escalate to the user.
- A compound command is confirmed **once**; the workflow then proceeds step by step.

## Known capability gaps to surface to the user (don't fake success)

- "Load series into viewport" by voice works via `change_series`, but **by series UID** and
  **window/level, screenshot, dental-curve MPR, toolbar, explicit layout** are 🟧 staged
  (`patient_tab_viewer.md`). If asked, the assistant should say the action isn't available yet
  rather than degrade to an unrelated action (the 2026-06-23 "load series 3" → `list_patients`
  misroute must not recur — prefer a clear "not yet supported" reply).
