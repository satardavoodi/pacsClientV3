# AIPacs v2.5.0 Release Notes

Date: 2026-05-04
Branch: matab-conservative

## Scope

This release finalizes the Window Level toolbar enhancement by adding a split-button CT preset menu and bundles the runtime repair work needed to keep patient opening and viewer startup stable after the toolbar change.

## Included Changes

### 1. Window Level split-button with CT presets

The Window Level tool now follows the same split-button pattern used by the other toolbar tools.

- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`
  - Added a left-side hamburger button next to the existing Window Level action button.
  - Added `_show_wl_presets_dropdown(...)` for CT presets.
  - Presets included: `Lung`, `Abdomen`, `Brain`, `Bone`.
  - Preset selection applies the configured WW/WL values to the active FAST or Advanced viewer target.
  - Styling follows the existing toolbar theme and split-button treatment.

### 2. Toolbar regression repairs from the WL feature work

The WL toolbar work had introduced accidental regressions in the large toolbar manager file. This release keeps only the intended WL feature and the required runtime fixes.

- Restored the microphone timer/state initialization needed during `ToolbarManager` construction so patient tabs can open without the toolbar throwing during setup.
- Restored the `AI Analyze` button click wiring.
- Removed an accidental stray callback inserted into an unrelated import-error path.
- Reverted unrelated Curved MPR drift so the release diff stays focused on the intended toolbar change.

### 3. Release metadata update

- `pyproject.toml` bumped to `2.5.0`.
- `.github/copilot-instructions.md` current stable version banner updated to `v2.5.0`.
- `docs/releases/RELEASE_NOTES.md` updated to point to this release.

## Validation

Validated after the toolbar cleanup:

- `pytest tests/gui/qt/test_main_window_basic.py -q` → passed
- Offscreen `PatientWidget()` construction smoke → passed (`PATIENT_WIDGET_OK`)
- `toolbar_manager.py` static error check → no errors
- Latest May 4 log tail review showed no fresh `ERROR`/`CRITICAL` entries for the current run; only normal viewer/download activity plus a shutdown-time main-thread stall probe entry.

## Notes For Next Changes

- `toolbar_manager.py` is a high-risk file because it combines many unrelated responsibilities. Future edits should use exact local anchors and keep diffs tightly scoped.
- If another toolbar feature is added, prefer extending the split-button helpers already introduced here instead of open-coding one-off button styles.
- For runtime verification, clear or rotate `user_data/logs/*.log` before reproducing a flow so new errors are not mixed with older sessions.
