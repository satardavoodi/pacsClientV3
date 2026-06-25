# Patient-Tab / Viewer control surface

**Status:** 2026-06-23. What the agent can do in the Patient Viewer today, and the precise plan for
the staged additions. Staged items touch clinical viewer code, so each is **flag-gated and must be
verified on the Windows source build** before default-on (per project rules: FAST viewer must never
instantiate VTK render windows; preserve overlays/measurements/sync/reference-lines).

## Available now (structured, no mouse automation)

| Capability | Action | Notes |
|---|---|---|
| Read active tab (patient/study/layout hint) | `get_active_tab` | read-only |
| List open tabs | `list_open_tabs` | read-only |
| Series thumbnails / list | `get_thumbnails_data`, `get_series_info` | read-only |
| Active series on focused viewport | `get_active_series` | read-only |
| Multi-study info | `get_multistudy_info` | read-only |
| Per-viewport state | `query_viewport_state` | read-only; series/await/slice/spinner |
| **Load series into a viewport** | `change_series {series_index|series_number, viewport}` | runs the real drop path `method_change_series_on_viewer(...)`; structured + testable |
| Scroll slices | `scroll_slices {index|delta|direction}` | local-write |
| Switch tab | `switch_tab {index}` | ui-nav |
| Open standard (Zeta) MPR | `open_mpr` | via module launcher |
| Close patient tab | `close_patient_tab` | **destructive — Test Control Server only** |

`change_series` already satisfies `viewer.load_series_to_viewport` /
`viewer.drop_series_to_viewport(series_number, viewport)`.

## Staged additions (designed; not yet wired)

Each new viewer/toolbar action belongs on a **`viewer_write` / `toolbar` / `layout` adapter**,
flag-gated (suggest `AIPACS_AGENT_VIEWER_TOOLS`), registered in `bus_factory` only when the live
widgets are present, and exposed as MCP tools in `server.py`.

| Tool | Approach (where the real logic already lives) |
|---|---|
| `viewer.drop_series_to_viewport(series_uid, viewport)` | In `viewer_write_adapter`, resolve `series_uid → series_number` from the active tab's `_server_series_info`, then reuse `change_series`. |
| `viewer.select_viewport(viewport)` / `get_active_viewport` | Set/read the patient tab's selected viewport widget (the same selection a click sets). |
| `viewer.set_layout(rows, cols)` / `get_layout` / `layout.set/get/reset` | Replace the `change_layout` `NOT_IMPLEMENTED` stub by calling the patient toolbar's existing layout handler (the grid the layout buttons drive). |
| `viewer.apply_window_preset(name)` | Call the existing W/L preset handler (the toolbar preset menu). |
| `viewer.set_window_level_width(level, width)` / `get_window_level_width` | The viewer already tracks W/L (`get_window_level()` is read in the Dental Curve MPR path); expose get/set. |
| `viewer.open_dental_curve_mpr` | Add a `curved_mpr` module launcher (the toolbar `_show_curved_mpr_panel` / VTK host) alongside the wired `eagle_ai/mpr/printing/education/web_browser`. |
| `viewer.capture_screenshot(target)` | Grab the viewport/window via Qt `grab()` (Qt-main-thread) and save to the outputs/attachments folder; promote from the external `ui_probe.py` mss capture. |
| `toolbar.list_tools` / `activate_tool` / `deactivate_tool` / `get_active_tool` | Wrap `toolbar_manager` (`turn_off_all_tools`, per-tool toggles) as structured actions. |

**Invariants for the staged work**
- Reuse the existing toolbar/viewer handlers — do NOT re-implement geometry, W/L, MPR, or layout.
- `capture_screenshot` and any pixmap op are **Qt-main-thread only**.
- No new path may instantiate VTK render windows in FAST mode.
- Classify each new action in `permissions.py` (`change_series`/`set_layout`/W-L = local_write;
  reads = read_only; `close_patient_tab` = destructive) so the gate covers them.

## Verification resources for viewer actions

| After | Probe | Expect |
|---|---|---|
| `change_series` / drop | `query_viewport_state` | target viewport holds the series number/UID |
| `open_mpr` | `list_open_tabs` | MPR view present |
| `set_layout` | `query_viewport_state` / `get_layout` | viewport count matches |
| `set_window_level_width` | `get_window_level_width` | values match |
