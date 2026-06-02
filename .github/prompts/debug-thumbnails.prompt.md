---
mode: agent
description: Debug the patient/thumbnail sidebar loading workflow (socket download pipeline).
---

# Debug thumbnail / patient-open workflow

Goal: thumbnails load automatically in the sidebar when a patient is single-clicked.

## Reproduce
1. In the running source build: select **MRI**, pick **yesterday** or **two days ago**.
2. Wait for the patient list, then single-click several different patients.
3. Watch whether thumbnails populate in the right-panel sidebar.

## Read the log
Open `user_data/logs/download_diagnostics.log` for the run:
- **Success:** `right_panel_socket_start` → within ~1–3 s →
  `right_panel_socket_done thumbnail_count=N`.
- **Failure:** `right_panel_socket_error`, a ~45123 ms timeout, port `105` usage, or no
  thumbnail UI update.

## Likely root cause (known trap)
The thumbnail/patient sockets must use the **socket-protocol port** from
`config/socket_config.json` (e.g. `50052`) resolved via `get_socket_server_settings()`.
**Do not** use the `port` field from `config/servers.json` (e.g. `105`) — that is the
DICOM port; feeding it to the socket client makes fetches hang until a ~45 s timeout.

## Guardrails
Before editing the sidebar, the series-load path (`_vc_load.py` / `_vc_switch.py`),
`thumbnail_manager.py`, or the home-page right-panel thumbnails, read the relevant
regression-guard sections in `CLAUDE.md` (multi-study viewer + thumbnail pipeline) and
keep every invariant. Make **one** targeted fix from the log evidence, then retest once.
