# Responsive UI Scaling Plan — AIPacs Windows Desktop
**Created:** 2026-05-20
**Revised:** 2026-05-26 — pre-implementation review (see §16 Revision Log)
**Status:** Draft — review pass complete; ready for staged implementation with gates

---

## 1. Executive Summary

AIPacs currently hard-codes pixel dimensions throughout all UI modules. On 1920×1080 at 96 DPI (100% Windows scaling) this looks correct, but on 2560×1440 / 1366×768 or at 125%–150% Windows scaling, elements are visually misaligned or too small. This plan introduces a single central `sf()` helper that multiplies every hardcoded pixel value by a configurable scale factor. Scale 1.0 = **zero visual change** — this is the safety invariant. The user can later adjust the scale in Settings, or the app can auto-detect the monitor DPI.

**Reference implementation:** `modules/printing/ui/printing_widget.py` lines 135–144 — `_scaled(px)` using `screen.logicalDotsPerInch() / 96.0`, clamped `[1.0, 2.0]`.

---

## 2. Audit Findings — Hardcoded Values Inventory

### 2.1 `PacsClient/pacs/workstation_ui/mainwindow_ui.py`
| Location | Value | Type |
|----------|-------|------|
| Title bar | `setFixedHeight(84)` | geometry |
| User container | `setFixedHeight(70)` | geometry |
| User container | `setMinimumWidth(170)` | geometry |
| Window buttons × 3 | `setFixedSize(46, 32)` | geometry |
| User icon | `pixmap(36, 36)` | icon |
| Window minimum | `setMinimumSize(900, 520)` | geometry |
| CSS user name | `font-size: 13px` | font |
| CSS user role | `font-size: 10px` | font |
| CSS tab font | `font-size: 11px` | font |
| CSS button font | `font-size: 16px` | font |
| CSS padding | `6px 14px` | spacing |
| CSS tab min-width | `80px` | geometry |

### 2.2 `PacsClient/pacs/workstation_ui/AIPacs_ui.py`
Constants defined at lines 77–82 — updating only these 6 constants propagates everywhere:
| Constant | Value | Type |
|----------|-------|------|
| `size_button` | `QSize(29, 29)` | geometry |
| `_menu_button_size` | `54` | geometry |
| `_menu_collapsed_width` | `62` | geometry |
| `_menu_expanded_width` | `220` | geometry |
| `_center_panel_width` | `400` | geometry |
| `_right_panel_width` | `400` | geometry |
| CSS global font | `setPointSize(10)` | font |
| CSS footer font | `setPointSize(9)` | font |
| CSS padding | `8px 12px` | spacing |

### 2.3 `PacsClient/pacs/patient_tab/ui/patient_ui/patient_tab_widget.py`
| Location | Value | Type |
|----------|-------|------|
| Tab chip | `setFixedWidth(252)` | geometry |
| Tab chip | `setFixedHeight(70)` | geometry |
| Thumbnail container | `setFixedSize(52, 63)` | geometry |
| Thumbnail label | `setFixedSize(52, 63)` | geometry |
| Close button | `setFixedSize(18, 18)` | geometry |
| Pixmap scaled | `52×63` | icon |
| Default icon | `QPixmap(28, 28)` | icon |
| CSS font-size | `16px / 12px` | font |
| CSS min-height | `45px` | geometry |
| CSS max-width | `170px` | geometry |

### 2.4 `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/widget.py`
| Location | Value | Type |
|----------|-------|------|
| `default_panel_width` | `260` | geometry |
| `reception_panel_width` | `int(260 * 1.7) = 442` | geometry |

### 2.5 `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py`
| Location | Value | Type |
|----------|-------|------|
| Sidebar width | `setFixedWidth(40)` | geometry |
| Divider height | `setFixedHeight(1)` | geometry |
| CSS font-size | `14px` | font |
| CSS padding | `14px 0` | spacing |
| CSS border-radius | `6px` | spacing (keep fixed) |
| Thumbnail layout margins | `setContentsMargins(20, 6, 6, 6)` | spacing |
| Grid margins | `setContentsMargins(8, 6, 14, 6)` | spacing |
| Layout spacing | `6px` | spacing |
| CSS title/count labels | `font-size: 10px` | font |
| Reception labels | `font-size: 14px` | font |

### 2.6 `PacsClient/pacs/patient_tab/ui/patient_ui/sidebar_widget.py`
| Location | Value | Type |
|----------|-------|------|
| Sidebar | `setFixedWidth(40)` | geometry |

### 2.7 `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py`
| Location | Value | Type |
|----------|-------|------|
| Panel | `setFixedWidth(216)` | geometry |
| Grid spacing | `6px` | spacing |
| Title/count CSS | `font-size: 10px` | font |

### 2.8 `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`
| Location | Value | Type |
|----------|-------|------|
| Icon sizes | `16px / 20–23px / 25px / 31px` | icon |
| Badge height | `setFixedHeight(16)` | geometry |
| Badge width | `20 / 24 / 28px` | geometry |
| Separator | `24px wide / 1px line` | geometry |
| Scrollbar | `20px height` | geometry |
| Logo | `250×48px` | geometry |
| Dropdown popups | `220–500px wide` | geometry |
| Toolbar min-height | `60px` | geometry |
| Button min | `40×40px` | geometry |
| Split-left | `13×40px` | geometry |
| Badge font | `7pt` | font |
| Button fonts | `11–16px` | font |

### 2.9 `PacsClient/pacs/workstation_ui/settings_ui/settings_ui.py`
| Location | Value | Type |
|----------|-------|------|
| Tab padding | `11px 20px` | spacing |
| Tab font | `14px` | font |
| Tab min-width | `120px` | geometry |
| GroupBox title | `28px` (intentionally large) | font |
| Label font | `14px` | font |
| Input min-height | `34px` | geometry |
| Button min-height | `36px` | geometry |
| Scrollbar width | `12px` | geometry |
| GroupBox margin-top | `28px` | spacing |
| GroupBox padding | `18px 20px` | spacing |

### 2.10 `PacsClient/pacs/workstation_ui/settings_ui/server_settings.py`
| Location | Value | Type |
|----------|-------|------|
| Label widths | `55px / 95px` | geometry |
| Field heights | `28–30px` | geometry |
| Button heights | `30px` | geometry |
| Table row heights | `36–42px` | geometry |
| Column width | `70px` | geometry |
| CSS fonts | `11–18px` | font |

### 2.11 `PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py`
| Location | Value | Type |
|----------|-------|------|
| Grid buttons | `29×29px` | geometry |
| Combos | `108px / 90px` | geometry |
| CSS fonts | `14px / 18px / 13px` | font |
| Layout margins | `18×16px` | spacing |

### 2.12 `PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py`
| Location | Value | Type |
|----------|-------|------|
| Dialog minimum | `650×550px` | geometry |
| Label min widths | `100–180px` | geometry |
| CSS fonts | `14–16px` | font |
| Layout margins | `25px all sides` | spacing |

### 2.13 `PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py`
| Location | Value | Type |
|----------|-------|------|
| Widget max widths | `120–440px` | geometry |
| Input min-height | `88px` | geometry |

### 2.14 `modules/printing/ui/printing_widget.py`
**Status: PARTIALLY scaled** — `_scaled()` exists (lines 135–144) for some values, but thumbnails (72×54 / 96×72), splitter sizes, and CSS fonts are NOT routed through it yet. Keep `self._scaled()` as-is; route remaining values through it.

### 2.15 `modules/cd_burner/cd_burn_dialog.py`
| Location | Value | Type |
|----------|-------|------|
| Dialog minimum | `600×550px` | geometry |
| Icon | `32×32px` | icon |
| CSS fonts | `11–20px` | font |
| Various padding | raw px | spacing |

### 2.16 `modules/web_browser/widget.py`
| Location | Value | Type |
|----------|-------|------|
| Sidebar expanded | `310px` | geometry |
| Sidebar collapsed | `86px` | geometry |
| Dialogs | `420–500px` | geometry |
| Header | `42px` | geometry |
| Icon buttons | `24×24px` | geometry |
| Card width formula | dynamic | geometry |

---

## 3. Architecture Design

### 3.1 New central module: `PacsClient/utils/ui_scaling.py`

> **Revision 2026-05-26.** The original draft persisted to
> `BASE_PATH/config/...`. In a frozen Nuitka build `BASE_PATH` is the install
> directory (e.g. `d:\ai-pacs\aipacs\`), which is **not user-writable**.
> Persistence must go through `SOCKET_CONFIG_PATH` from
> `PacsClient.utils.config` — that resolves to `roaming_config_root()` in
> frozen mode and `BASE_PATH/config` in dev mode, exactly matching the rest of
> the project's writable-config pattern. We also stop coupling the UI-scale
> key to the viewer-backend config file (avoids accidental coupling with the
> `modules/viewer/viewer_backend_config.py` consumer) and use a dedicated
> `ui_settings.json`.

```python
"""Central UI scale-factor helper.

Scale 1.0 = zero visual change (safety invariant).
Range: [0.75, 1.50].
Persisted in {SOCKET_CONFIG_PATH}/ui_settings.json key "ui_scale_factor".
"""
from __future__ import annotations
import json
from pathlib import Path

_scale_factor: float = 1.0

_UI_SETTINGS_FILENAME = "ui_settings.json"
_SCALE_KEY = "ui_scale_factor"
_MIN_SCALE = 0.75
_MAX_SCALE = 1.50


def _clamp(factor: float) -> float:
    try:
        f = float(factor)
    except Exception:
        return 1.0
    return max(_MIN_SCALE, min(_MAX_SCALE, f))


def sf(px: int) -> int:
    """Scale an integer pixel value. Returns px unchanged when factor == 1.0."""
    if _scale_factor == 1.0:
        return int(px)
    return max(1, int(round(px * _scale_factor)))


def sf_f(px: float) -> float:
    """Scale a float pixel value (for CSS f-strings)."""
    if _scale_factor == 1.0:
        return float(px)
    return max(1.0, px * _scale_factor)


def sf_pt(pt: int) -> int:
    """Scale a font point size. Minimum 6pt."""
    if _scale_factor == 1.0:
        return int(pt)
    return max(6, int(round(pt * _scale_factor)))


def get_scale() -> float:
    return _scale_factor


def set_scale(factor: float) -> None:
    """Clamp to [0.75, 1.50] and update module-level factor."""
    global _scale_factor
    _scale_factor = _clamp(factor)


def _ui_settings_path() -> Path:
    """Resolve the writable UI-settings file.

    Uses SOCKET_CONFIG_PATH so frozen builds land in roaming_config_root()
    and dev builds land in BASE_PATH/config — same pattern as other
    user-mutable config in the project.
    """
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
    return Path(SOCKET_CONFIG_PATH) / _UI_SETTINGS_FILENAME


def detect_screen_scale() -> float:
    """Best-effort screen-DPI heuristic.

    **Caveat (Qt 6):** PySide6 enables high-DPI scaling by default and
    normalises `QScreen.logicalDotsPerInch()` to 96 on Windows. On most
    systems this function will therefore return 1.0 even at 125%/150%
    Windows scaling — Qt has already auto-scaled the UI. Treat this
    function as a fallback only; the authoritative source is the saved
    user preference. See §14 (Qt 6 high-DPI interaction).
    """
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return 1.0
        screen = app.primaryScreen()
        if screen is None:
            return 1.0
        dpi = float(screen.logicalDotsPerInch())
        return _clamp(dpi / 96.0)
    except Exception:
        return 1.0


def load_scale_from_config() -> float:
    """Read ui_scale_factor from ui_settings.json.
    Returns 1.0 on any error or if key is absent.
    """
    try:
        cfg_path = _ui_settings_path()
        if cfg_path.exists():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            return _clamp(data.get(_SCALE_KEY, 1.0))
    except Exception:
        pass
    return 1.0


def save_scale_to_config(factor: float) -> None:
    """Write ui_scale_factor to ui_settings.json (writable config dir)."""
    try:
        cfg_path = _ui_settings_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict = {}
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[_SCALE_KEY] = _clamp(factor)
        cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        # Persistence is best-effort; never crash the app over a settings write.
        pass
```

### 3.2 Integration in `main.py`

Insert after the existing `QApplication.setAttribute(...)` calls (around line ~804) but **before** the first widget is created:

```python
# ── UI scale: load saved user preference; default 1.0 (no auto-detect-and-apply) ──
# Qt 6 already auto-scales on high-DPI; we deliberately do NOT compound that
# at startup. The user adjusts the scale in Settings → restart-on-apply.
from PacsClient.utils.ui_scaling import load_scale_from_config, set_scale as _set_ui_scale
_set_ui_scale(load_scale_from_config())  # returns 1.0 if no preference saved
```

> **Revision 2026-05-26.** The earlier draft applied `detect_screen_scale()`
> when no saved value existed. This stacks on top of Qt 6's already-active
> high-DPI auto-scaling and would silently make the UI larger on first launch
> for any user above 100% Windows scaling. The new flow keeps `sf()` at 1.0
> until the user opts in via Settings.

### 3.3 Scaling Rules

| Rule | Description |
|------|-------------|
| **R1** | `sf(px)` is identity when `_scale_factor == 1.0` — zero overhead at default |
| **R2** | `sf()` is called only at `__init__` time — never inside `paintEvent`, `wheelEvent`, or `set_slice()` |
| **R3** | CSS stylesheets that contain pixel values are generated as f-strings at `__init__` time |
| **R4** | `border-radius`, 1px separators, and shadow parameters remain fixed (scale-immune) |
| **R5** | Minimum sidebar width guard: `max(sf(40), 28)` — never collapse below 28px |
| **R6** | GroupBox title: `28px` CSS → `sf_pt(18)pt` (converted to pt-based font spec) |

---

## 4. Risk Areas

| # | Risk | Severity | File | Mitigation |
|---|------|----------|------|------------|
| 1 | Toolbar reflow (6900+ lines, many interdependent sizes) | HIGH | `toolbar_manager.py` | Phase 5 — isolated; one size tier at a time; full scroll test after |
| 2 | CSS stylesheet string rebuilds at runtime | MEDIUM | All files | Generate CSS at `__init__` only; never re-generate on scroll/paint |
| 3 | Thumbnail geometry mismatch (thumbnail_panel + pw_panels both own thumbnail size) | MEDIUM | `thumbnail_panel.py`, `_pw_panels.py` | Scale both from same `sf(52)` call; verify pixel-perfect match |
| 4 | Sidebar collapse/expand animation if fixed widths change | LOW | `sidebar_widget.py`, `AIPacs_ui.py` | Scale both collapsed and expanded widths by same factor |
| 5 | PrintingWidget has its own `_scaled()` using screen DPI — must NOT be replaced by `sf()` | MEDIUM | `printing_widget.py` | Keep `self._scaled()` as-is; route only the remaining un-scaled values through it |
| 6 | Plugin package mirror for printing_widget.py | HIGH | `builder/plugin package/packages/printing/payload/python/modules/printing/ui/printing_widget.py` | Always copy after editing canonical; verify SHA equality |
| 7 | Font pt vs px mismatch (Qt treats pt and px differently per DPI) | MEDIUM | Settings UI, toolbar | Convert all CSS font-size from px to `sf_pt(N)pt` format |
| 8 | QSize / setFixedSize called with already-computed int — no type error | LOW | All geometry calls | `sf()` returns `int`; confirm at Phase 0 with one smoke test |
| 9 | R5/R22 DM table rebuild if settings UI changes trigger style update | LOW | `settings_ui.py` | Settings UI has no DM timing dependency; safe to scale |
| 10 | Viewer hot paths (set_slice, wheelEvent, paintEvent) | CRITICAL | `vtk_widget.py`, `lightweight_2d_pipeline.py` | **Out of scope** — these files are not touched in any phase |
| 11 | **Qt 6 auto-scaling already in effect** — Qt6 auto-scales geometry on high-DPI displays by default; `logicalDotsPerInch()` is normalised to 96. `sf()` therefore *stacks on top of* Qt auto-scaling, not in place of it. On a 150% Windows display set to `sf()=1.5` the effective scale would be **2.25×**, not 1.5×. | HIGH | all phases | Default `sf()` to 1.0 in production. Treat `detect_screen_scale()` as advisory only — never as auto-applied default. Document that the slider in Settings (Phase 10) is the user-facing knob, applied on restart. |
| 12 | Accidental edit of multi-study regression-guarded code (`_vc_load.py`, `_vc_switch.py`, `_pw_panels.py`, `patient_widget_core/widget.py`) | HIGH | files listed in project `CLAUDE.md` § "Multi-study viewer" | Before editing those files for Phase 4, re-read `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`. Touch only the literal numbers in the replacement table — no surrounding logic. |
| 13 | `_vc_load.py` contains incidental `font-size: 14px` (progress dialog at line ~2099) — **NOT** in Phase 4 scope; leaving it un-scaled is intentional. | LOW | `_vc_load.py` | Plan does not modify `_vc_load.py`. Drift between a progress-dialog font and the rest of the UI is cosmetically acceptable vs. the regression risk of touching a multi-study-sensitive file. |
| 14 | `PrintingWidget._scaled()` reads `self.screen().logicalDotsPerInch()` per-instance; the new `sf()` is module-level constant. On a multi-monitor setup where the print dialog is dragged to a different-DPI monitor, the two systems can disagree. | MEDIUM | `printing_widget.py` vs `ui_scaling.py` | Phase 7 keeps `self._scaled()` as documented; explicit known-limitation note added to §14. Both formulas only run at `__init__` so the drift is "what the screen was when the dialog opened" — acceptable. |
| 15 | External QSS files | LOW | none found | Verified 2026-05-26: no `.qss` files exist on disk. All stylesheets are embedded Python strings. Plan inventory is complete on this dimension. |

---

## 5. Conservative Execution Strategy

1. **One phase at a time.** Never start Phase N+1 before Phase N is verified.
2. **Scale 1.0 gate.** After each phase, run the app with `_scale_factor = 1.0` and confirm pixel-identical to pre-change baseline.
3. **Single import change per file.** Add `from PacsClient.utils.ui_scaling import sf, sf_f, sf_pt` at the top of the file and nothing else until the replacement table is fully applied.
4. **No collateral changes.** Touch only the values listed in the replacement table for that phase. Do not refactor, rename, or restructure anything else.
5. **Rollback is `git stash` or `git checkout -- <file>`.** Every phase is a clean atomic commit so rollback is one command.

---

## 6. Performance Protection Rules

| Rule | Description |
|------|-------------|
| **P1** | No `sf()` call inside `set_slice()`, `wheelEvent()`, or `paintEvent()` — these run at 60fps+ |
| **P2** | CSS stylesheets built at `__init__` time stored as instance variable — `setStyleSheet()` called once |
| **P3** | `sf()` with `_scale_factor == 1.0` is a no-op (`if _scale_factor == 1.0: return px`) |
| **P4** | `detect_screen_scale()` called at most once (during `main.py` startup) |
| **P5** | No `QApplication.primaryScreen()` calls in widget constructors — only in `detect_screen_scale()` at startup |

---

## 7. Rollback Strategy

Each phase is a single atomic Git commit. Rollback procedure:

```powershell
# Rollback last phase
git revert HEAD --no-edit

# Or reset to before the phase
git reset --hard HEAD~1
```

Phase 0 (`ui_scaling.py` creation) has zero risk — it is a new file with no callers yet. All subsequent phases depend on Phase 0 being present, so rolling back Phase N rolls back only that phase's caller changes; `ui_scaling.py` itself remains.

---

## 8. Implementation Phases

### Phase 0 — Create `PacsClient/utils/ui_scaling.py`
**Risk:** Zero (new file, no callers yet)  
**Action:** Create the file as specified in §3.1.  
**Verification:** `python -c "from PacsClient.utils.ui_scaling import sf; assert sf(100) == 100"`  
**Commit:** `feat(ui): add central sf() scale-factor helper (identity at 1.0)`

---

### Phase 1 — `mainwindow_ui.py` (title bar, window buttons)
**Risk:** Low  
**Files:** `PacsClient/pacs/workstation_ui/mainwindow_ui.py`  
**Replacements:**

| Before | After |
|--------|-------|
| `setFixedHeight(84)` | `setFixedHeight(sf(84))` |
| `setFixedHeight(70)` | `setFixedHeight(sf(70))` |
| `setMinimumWidth(170)` | `setMinimumWidth(sf(170))` |
| `setFixedSize(46, 32)` | `setFixedSize(sf(46), sf(32))` |
| `pixmap(36, 36)` | `pixmap(sf(36), sf(36))` |
| `setMinimumSize(900, 520)` | `setMinimumSize(sf(900), sf(520))` |
| CSS `font-size: 13px` | `f"font-size: {sf(13)}px"` |
| CSS `font-size: 10px` | `f"font-size: {sf(10)}px"` |
| CSS `font-size: 11px` | `f"font-size: {sf(11)}px"` |
| CSS `font-size: 16px` | `f"font-size: {sf(16)}px"` |
| CSS `padding: 6px 14px` | `f"padding: {sf(6)}px {sf(14)}px"` |
| CSS `min-width: 80px` | `f"min-width: {sf(80)}px"` |

**Verification:** Launch app at scale 1.0 → pixel-identical. Launch at scale 1.25 → title bar visibly taller.  
**Commit:** `feat(ui): scale mainwindow title bar and window buttons`

---

### Phase 2 — `AIPacs_ui.py` (shell constants)
**Risk:** Low (updating 6 constants propagates everywhere)  
**Files:** `PacsClient/pacs/workstation_ui/AIPacs_ui.py`  
**Replacements:** At the constant block (lines 77–82):

| Before | After |
|--------|-------|
| `size_button = QSize(29, 29)` | `size_button = QSize(sf(29), sf(29))` |
| `_menu_button_size = 54` | `_menu_button_size = sf(54)` |
| `_menu_collapsed_width = 62` | `_menu_collapsed_width = sf(62)` |
| `_menu_expanded_width = 220` | `_menu_expanded_width = sf(220)` |
| `_center_panel_width = 400` | `_center_panel_width = sf(400)` |
| `_right_panel_width = 400` | `_right_panel_width = sf(400)` |
| `setPointSize(10)` | `setPointSize(sf_pt(10))` |
| `setPointSize(9)` | `setPointSize(sf_pt(9))` |
| CSS `padding: 8px 12px` | `f"padding: {sf(8)}px {sf(12)}px"` |

**Commit:** `feat(ui): scale AIPacs_ui shell menu constants`

---

### Phase 3 — `patient_tab_widget.py` (tab chips)
**Risk:** Low  
**Files:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_tab_widget.py`  
**Replacements:**

| Before | After |
|--------|-------|
| `setFixedWidth(252)` | `setFixedWidth(sf(252))` |
| `setFixedHeight(70)` | `setFixedHeight(sf(70))` |
| `setFixedSize(52, 63)` | `setFixedSize(sf(52), sf(63))` — (both label and container) |
| `setFixedSize(18, 18)` | `setFixedSize(sf(18), sf(18))` |
| `scaled(52, 63, ...)` | `scaled(sf(52), sf(63), ...)` |
| `QPixmap(28, 28)` | `QPixmap(sf(28), sf(28))` |
| CSS `font-size: 16px` | `f"font-size: {sf(16)}px"` |
| CSS `font-size: 12px` | `f"font-size: {sf(12)}px"` |
| CSS `min-height: 45px` | `f"min-height: {sf(45)}px"` |
| CSS `max-width: 170px` | `f"max-width: {sf(170)}px"` |

**Commit:** `feat(ui): scale patient tab chips`

---

### Phase 4 — `_pw_panels.py`, `widget.py`, `sidebar_widget.py`, `thumbnail_panel.py`, `reception_panel_widget.py` (viewer sidebar)
**Risk:** Medium — thumbnails must stay aligned between `thumbnail_panel.py` and `_pw_panels.py`; multi-study regression-guard applies to `_pw_panels.py` and `patient_widget_core/widget.py` (see Risk #12).
**Files:**
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/widget.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/sidebar_widget.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/thumbnail_panel.py`
- `PacsClient/pacs/patient_tab/ui/patient_ui/reception_panel_widget.py` *(added 2026-05-26 — has 10× `font-size: 14px` plus a few fixed sizes; same scaling rules)*

**Replacements:**

`widget.py`:
| Before | After |
|--------|-------|
| `default_panel_width = 260` | `default_panel_width = sf(260)` |
| `reception_panel_width = int(260 * 1.7)` | `reception_panel_width = sf(442)` |

`_pw_panels.py`:
| Before | After |
|--------|-------|
| `setFixedWidth(40)` | `setFixedWidth(max(sf(40), 28))` |
| `setContentsMargins(20, 6, 6, 6)` | `setContentsMargins(sf(20), sf(6), sf(6), sf(6))` |
| `setContentsMargins(8, 6, 14, 6)` | `setContentsMargins(sf(8), sf(6), sf(14), sf(6))` |
| `setSpacing(6)` | `setSpacing(sf(6))` |
| CSS `font-size: 14px` | `f"font-size: {sf(14)}px"` |
| CSS `padding: 14px 0` | `f"padding: {sf(14)}px 0"` |
| CSS `font-size: 10px` | `f"font-size: {sf(10)}px"` |

`sidebar_widget.py`:
| Before | After |
|--------|-------|
| `setFixedWidth(40)` | `setFixedWidth(max(sf(40), 28))` |

`thumbnail_panel.py`:
| Before | After |
|--------|-------|
| `setFixedWidth(216)` | `setFixedWidth(sf(216))` |
| `setSpacing(6)` | `setSpacing(sf(6))` |
| CSS `font-size: 10px` | `f"font-size: {sf(10)}px"` |

**Commit:** `feat(ui): scale viewer sidebar, thumbnail panel, panel widths`

---

### Phase 5 — `toolbar_manager.py` (viewer toolbar) — HIGHEST RISK
**Risk:** High (6900+ lines, 4 icon size tiers, CSS-heavy)  
**Strategy:** Scale one size tier at a time within this phase; run toolbar smoke test between tiers.

**Files:** `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

**Tier A — Badge and separator (smallest, safest):**
| Before | After |
|--------|-------|
| `setFixedHeight(16)` (badge) | `setFixedHeight(sf(16))` |
| badge width `20` / `24` / `28` | `sf(20)` / `sf(24)` / `sf(28)` |
| `setFixedWidth(24)` (separator) | `setFixedWidth(sf(24))` |
| CSS `font-size: 7pt` (badge) | `f"font-size: {sf_pt(7)}pt"` |

**Tier B — Button geometry:**
| Before | After |
|--------|-------|
| `setMinimumSize(40, 40)` | `setMinimumSize(sf(40), sf(40))` |
| `setFixedSize(13, 40)` (split-left) | `setFixedSize(sf(13), sf(40))` |
| scrollbar `20px` | `sf(20)` |
| toolbar min-height `60` | `sf(60)` |

**Tier C — Icon sizes:**
| Before | After |
|--------|-------|
| `16` (hamburger) | `sf(16)` |
| `20` / `21` / `22` / `23` (split-main) | `sf(20)` … `sf(23)` |
| `25` (default tool) | `sf(25)` |
| `31` (dropdown) | `sf(31)` |

**Tier D — CSS fonts:**
| Before | After |
|--------|-------|
| `font-size: 11px` | `f"font-size: {sf(11)}px"` |
| `font-size: 12px` | `f"font-size: {sf(12)}px"` |
| `font-size: 14px` | `f"font-size: {sf(14)}px"` |
| `font-size: 16px` | `f"font-size: {sf(16)}px"` |

**Tier E — Logo and dropdown widths:**
| Before | After |
|--------|-------|
| `setFixedSize(250, 48)` (logo) | `setFixedSize(sf(250), sf(48))` |
| dropdown popup widths `220–500` | `sf(220)` … `sf(500)` |

**Revision 2026-05-26 — split commits per tier.** The original plan
proposed a single 4-hour commit for all five tiers. Given the file is 6900+
lines and 21 `QSize/setIconSize` call sites alone, a single atomic commit is
too risky to revert cleanly. Each tier is now its own commit:

- `feat(ui): scale viewer toolbar — Tier A badges/separator`
- `feat(ui): scale viewer toolbar — Tier B button geometry`
- `feat(ui): scale viewer toolbar — Tier C icon sizes`
- `feat(ui): scale viewer toolbar — Tier D CSS fonts`
- `feat(ui): scale viewer toolbar — Tier E logo and dropdown widths`

After **each** tier: run the toolbar smoke test (open a multi-image study,
exercise the dropdowns, switch tools), then commit. Do **not** start the
next tier until smoke passes.

---

### Phase 6 — Settings UI
**Risk:** Low  
**Files:**
- `PacsClient/pacs/workstation_ui/settings_ui/settings_ui.py`
- `PacsClient/pacs/workstation_ui/settings_ui/server_settings.py`
- `PacsClient/pacs/workstation_ui/settings_ui/viewerconfigsetting.py`
- `PacsClient/pacs/workstation_ui/settings_ui/storage_cleanup_panel.py`
- `PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py`

**`settings_ui.py` key replacements:**
| Before | After |
|--------|-------|
| `padding: 11px 20px` | `f"padding: {sf(11)}px {sf(20)}px"` |
| `font-size: 14px` (tab) | `f"font-size: {sf(14)}px"` |
| `min-width: 120px` | `f"min-width: {sf(120)}px"` |
| GroupBox title `font-size: 28px` | `f"font-size: {sf_pt(18)}pt"` |
| `min-height: 34px` | `f"min-height: {sf(34)}px"` |
| `min-height: 36px` | `f"min-height: {sf(36)}px"` |
| scrollbar `width: 12px` | `f"width: {sf(12)}px"` |
| `margin-top: 28px` | `f"margin-top: {sf(28)}px"` |
| `padding: 18px 20px` | `f"padding: {sf(18)}px {sf(20)}px"` |

**`server_settings.py` key replacements:**
| Before | After |
|--------|-------|
| label widths `55` / `95` | `sf(55)` / `sf(95)` |
| field heights `28–30` | `sf(28)` … `sf(30)` |
| button heights `30` | `sf(30)` |
| table row heights `36–42` | `sf(36)` … `sf(42)` |
| column width `70` | `sf(70)` |
| CSS fonts `11–18px` | `sf()` equivalents |

**`viewerconfigsetting.py` key replacements:**
| Before | After |
|--------|-------|
| grid buttons `29×29` | `sf(29)` × `sf(29)` |
| combos `108` / `90` | `sf(108)` / `sf(90)` |
| CSS fonts | `sf()` equivalents |
| margins `18×16` | `sf(18)` × `sf(16)` |

**`storage_cleanup_panel.py` key replacements:**
| Before | After |
|--------|-------|
| `setMinimumSize(650, 550)` | `setMinimumSize(sf(650), sf(550))` |
| label min widths `100–180` | `sf()` equivalents |
| CSS fonts `14–16px` | `sf()` equivalents |
| margins `25` all sides | `sf(25)` |

**`echomind_settings.py` key replacements:**
| Before | After |
|--------|-------|
| max widths `120–440` | `sf()` equivalents |
| input min-height `88` | `sf(88)` |

**Commit:** `feat(ui): scale settings UI (all subpanels)`

---

### Phase 7 — `printing_widget.py` (route remaining un-scaled values through `self._scaled()`)
**Risk:** Medium (plugin package mirror required)  
**Files:**
- `modules/printing/ui/printing_widget.py`
- `builder/plugin package/packages/printing/payload/python/modules/printing/ui/printing_widget.py`

**Note:** Do NOT replace `self._scaled()` with `sf()`. `PrintingWidget._scaled()` uses screen DPI per-instance for better multi-monitor accuracy. Route only the un-scaled thumbnail sizes and CSS fonts through `self._scaled()`.

**Replacements:**
| Before | After |
|--------|-------|
| `72, 54` (thumbnail) | `self._scaled(72), self._scaled(54)` |
| `96, 72` (thumbnail) | `self._scaled(96), self._scaled(72)` |
| CSS font `12px` | `f"font-size: {self._scaled(12)}px"` |
| splitter sizes raw px | `[self._scaled(v) for v in [...]]` |

**Post-edit:** Copy canonical to plugin package and verify SHA equality:
```powershell
$src = "modules/printing/ui/printing_widget.py"
$dst = "builder/plugin package/packages/printing/payload/python/modules/printing/ui/printing_widget.py"
Copy-Item $src $dst
(Get-FileHash $src).Hash -eq (Get-FileHash $dst).Hash
```

**Commit:** `feat(ui): route remaining printing_widget values through self._scaled(); sync plugin copy`

---

### Phase 8 — `cd_burn_dialog.py`
**Risk:** Low  
**Files:** `modules/cd_burner/cd_burn_dialog.py`  
**Replacements:**
| Before | After |
|--------|-------|
| `setMinimumSize(600, 550)` | `setMinimumSize(sf(600), sf(550))` |
| `QSize(32, 32)` (icon) | `QSize(sf(32), sf(32))` |
| CSS fonts `11–20px` | `sf()` equivalents |
| padding values | `sf()` equivalents |

**Commit:** `feat(ui): scale CD burn dialog`

---

### Phase 9 — `web_browser/widget.py`
**Risk:** Low  
**Files:** `modules/web_browser/widget.py`  
**Replacements:**
| Before | After |
|--------|-------|
| sidebar expanded `310` | `sf(310)` |
| sidebar collapsed `86` | `sf(86)` |
| dialogs `420–500` | `sf()` equivalents |
| header `42` | `sf(42)` |
| icon buttons `24×24` | `sf(24) × sf(24)` |

**Commit:** `feat(ui): scale web browser widget`

---

### Phase 10 — `main.py` integration + Settings UI hook
**Risk:** Low  
**Files:** `main.py`, `PacsClient/pacs/workstation_ui/settings_ui/settings_ui.py`

**`main.py`:** Add scale detection call (see §3.2).

**Settings UI:** Wire a scale factor slider/spinbox → calls `set_scale(factor)` + `save_scale_to_config(factor)` + application restart prompt (since Qt cannot re-apply sizes to live widgets without reinit).

**Commit:** `feat(ui): wire ui_scale_factor to main.py startup and Settings UI`

---

## 9. Module Coverage Checklist

| Module | Phase | Status |
|--------|-------|--------|
| `ui_scaling.py` (new) | 0 | ❌ Not started |
| `mainwindow_ui.py` | 1 | ❌ Not started |
| `AIPacs_ui.py` | 2 | ❌ Not started |
| `patient_tab_widget.py` | 3 | ❌ Not started |
| `_pw_panels.py`, `widget.py`, `sidebar_widget.py`, `thumbnail_panel.py` | 4 | ❌ Not started |
| `toolbar_manager.py` | 5 | ❌ Not started |
| `settings_ui.py`, `server_settings.py`, `viewerconfigsetting.py`, `storage_cleanup_panel.py`, `echomind_settings.py` | 6 | ❌ Not started |
| `printing_widget.py` + plugin copy | 7 | ❌ Not started |
| `cd_burn_dialog.py` | 8 | ❌ Not started |
| `web_browser/widget.py` | 9 | ❌ Not started |
| `main.py` + Settings hook | 10 | ❌ Not started |

---

## 10. Out of Scope (explicitly excluded)

- `vtk_widget.py` / `viewer_2d.py` — VTK render windows; touching these risks R16/R29/R30 regressions
- `lightweight_2d_pipeline.py` / `qt_slice_viewer.py` — hot-path viewer code; R17/R26 risk
- Download Manager UI (`_dm_*.py`) — R22 DM rebuild storm risk
- MPR 3D viewer (`standard_mpr_viewer_original.py`, `_mpr_*.py`)
- Stitching module (`modules/stitching/`)
- EchoMind chat window (`modules/EchoMind/viewer_chat/`)

---

## 11. File Mirror Requirements

Only one file has a required plugin package mirror for UI scaling work:

| Canonical | Plugin copy | Must sync after Phase |
|-----------|------------|----------------------|
| `modules/printing/ui/printing_widget.py` | `builder/plugin package/packages/printing/payload/python/modules/printing/ui/printing_widget.py` | 7 |

All other files modified in Phases 1–6, 8–10 are `PacsClient/` or `modules/` tier with no plugin copies — verified.

---

## 12. Testing Protocol

After each phase, run this sequence before committing:

1. **Identity gate:** Launch app with scale 1.0 — confirm pixel-identical to pre-change screenshot
2. **Scale 1.25 smoke:** Launch with `_scale_factor = 1.25` — confirm all affected elements are proportionally larger, no clipping, no overflow
3. **Scale 0.85 smoke:** Launch with `_scale_factor = 0.85` — confirm all elements still fit, minimum-width guards active
4. **Hot-path guard:** If the phase touched any file near `set_slice()` or `paintEvent()`, check `sf()` was NOT inserted in those functions
5. **Phase 5 only:** After each tier (A–E), run `toolbar_manager.py` smoke with a test patient to confirm toolbar layout intact

---

## 13. Summary Timeline

| Phase | Files | Risk | Estimated effort |
|-------|-------|------|-----------------|
| 0 — `ui_scaling.py` | 1 new | Zero | 0.5 h |
| 1 — mainwindow | 1 | Low | 0.5 h |
| 2 — AIPacs_ui (6 constants) | 1 | Low | 0.5 h |
| 3 — patient_tab_widget | 1 | Low | 1 h |
| 4 — viewer sidebar (4 files) | 4 | Medium | 1.5 h |
| 5 — toolbar_manager (5 tiers) | 1 | High | 4 h |
| 6 — settings UI (5 files) | 5 | Low | 2 h |
| 7 — printing_widget + mirror | 2 | Medium | 1 h |
| 8 — cd_burn_dialog | 1 | Low | 0.5 h |
| 9 — web_browser | 1 | Low | 0.5 h |
| 10 — main.py + settings hook | 2 | Low | 1 h |
| **Total** | **~20 files** | | **~13 h** |

> Revised total (2026-05-26): Phase 5 is now 5 separate commits, Phase 4 adds
> `reception_panel_widget.py`. Realistic total **≈ 15 h** end-to-end including
> verification, not counting any rework discovered during Phase 5 smoke tests.

---

## 14. Qt 6 High-DPI Interaction (Standards & Best Practices)

PySide6 / Qt 6 enables high-DPI scaling by default. The Qt 5 attributes
`AA_EnableHighDpiScaling` / `AA_DisableHighDpiScaling` were **removed in Qt 6**
— there is no longer a way to opt out. `main.py` (verified 2026-05-26) does
not set any DPI-related attribute, so the framework default applies.

What this means for `sf()`:

- On a 150% Windows display, Qt already renders `setFixedWidth(100)` at ~150
  device pixels. `QScreen.logicalDotsPerInch()` returns **96.0** in this
  configuration (Qt normalises coordinates to device-independent pixels).
- `dpi / 96.0` therefore evaluates to 1.0 on most Windows systems — meaning
  the existing `PrintingWidget._scaled()` is effectively a no-op there, and
  the new `detect_screen_scale()` will behave the same.
- A user-facing `sf()` slider in Settings (Phase 10) is the **only reliable
  knob** for relative size control on top of Qt's autoscale. Auto-detect
  remains as a non-default fallback only.

Best practices we are following:

1. **Pass logical (device-independent) pixels to Qt.** Qt handles the
   physical-pixel multiplication. `sf()` is a *user-preference* multiplier
   layered on top — never a substitute for Qt's high-DPI pipeline.
2. **`devicePixelRatio()` for raster images.** When loading icons/pixmaps
   that must stay crisp at scale, prefer vector (SVG) sources or supply `@2x`
   variants. (Out of scope for this plan; flagged for follow-up.)
3. **Use `pt` for fonts where possible.** Qt scales `pt`-typed fonts by
   `logicalDotsPerInch / 72`, which composes correctly with both system
   scaling and `sf_pt()`. The `font-size: 28px` → `sf_pt(18)pt` conversion in
   §3.3 R6 follows this guidance.
4. **Stylesheet rebuild only on `__init__`.** Re-applying a CSS string every
   paint or resize is what would actually hurt performance — not `sf()`
   itself. Performance rule P2 already encodes this.
5. **Single source of scale.** Only `ui_scaling.py` owns the scale factor.
   `PrintingWidget._scaled()` is the documented exception (its per-screen DPI
   read is correct in isolation; see Risk #14).

---

## 15. Implementation Standards — required by every phase

These are the non-negotiable rules each commit must satisfy:

1. **Imports.** Top of file only: `from PacsClient.utils.ui_scaling import sf, sf_f, sf_pt`. No deeper relative imports.
2. **Identity guarantee.** Every commit must keep the app pixel-identical at `_scale_factor = 1.0`. The reviewer will spot-check this with a screenshot diff against the pre-commit baseline.
3. **No structural changes.** A scaling commit edits literal numbers only — it does **not** rename, reorder, refactor, or add/remove widgets.
4. **CSS strings stay `__init__`-time.** If a CSS block was rebuilt on every signal in the old code, that is a separate pre-existing bug — do not "fix" it inside a scaling commit. File a follow-up.
5. **No `sf()` in hot paths.** Static analysis grep before each commit:
   ```powershell
   git diff --staged | Select-String "sf\(" | Select-String "paintEvent|wheelEvent|set_slice|mouseMoveEvent"
   ```
   Expected: zero hits. Any hit → revert the offending line.
6. **Tests before commit.** Run at minimum:
   - `pytest tests/ -q -x -k "not slow"` (whatever tests currently pass — do not introduce new failures)
   - Manual smoke per `CLAUDE.md` startup sequence: MRI modality → yesterday → click 3 patients → confirm thumbnails load.
7. **Plugin mirror sync (Phase 7 only).** Verify SHA equality between canonical and `builder/plugin package/...` copy of `printing_widget.py` before commit.
8. **Logging untouched.** No `print()`, no new logger calls inside a scaling commit. If you observe a logging gap, file a follow-up.

---

## 16. Revision Log

### 2026-05-26 — Pre-implementation review pass

Verified audit numbers against live code on `E:\ai-pacs\ai-pacs codes\ai-pacs beta version\`:
- `mainwindow_ui.py` — confirmed `setFixedHeight(84)` (line 598), `setFixedHeight(70)` (624), `setFixedSize(46, 32)` ×3 (981/1010/1039), `setMinimumSize(900, 520)` (74). ✓
- `AIPacs_ui.py` — confirmed constant block (lines 78–83). Plan had this at "77–82"; new range is 78–83 due to a one-line shift; functionally identical. ✓
- `patient_tab_widget.py` — confirmed `setFixedSize(52, 63)` (43, 48), `setFixedSize(18, 18)` (103), `setFixedWidth(252)` (114), `setFixedHeight(70)` (115), `QPixmap(28, 28)` (143). ✓
- `_pw_panels.py`, `widget.py`, `thumbnail_panel.py` — confirmed `setFixedWidth(40)`, `default_panel_width = 260`, `reception_panel_width`, `setFixedWidth(216)`. ✓
- `toolbar_manager.py` — 21 `QSize/setIconSize` call sites confirmed; Phase 5 sizing justified. ✓
- `PrintingWidget._scaled()` — confirmed at lines 135–144, formula `max(1.0, min(2.0, dpi / 96.0))`. ✓
- `PacsClient/utils/config.py` — confirmed `BASE_PATH = PROJECT_ROOT` (code dir, **not** writable in frozen builds) and `SOCKET_CONFIG_PATH = roaming_config_root()` in frozen mode. Plan §3.1 path corrected. ✓
- `main.py` — confirmed Qt high-DPI attributes **not** set; relies on Qt 6 framework default. §14 added to document this. ✓
- External `.qss` files — none found. Audit is complete on this dimension. ✓

Changes applied:
1. `§3.1` — moved persistence from `BASE_PATH/config/viewer_backend_settings.json` to a writable, frozen-safe `SOCKET_CONFIG_PATH/ui_settings.json`. Added `_clamp()` helper, hardened `save_scale_to_config()`, decoupled from viewer-backend config.
2. `§3.2` — main.py snippet no longer auto-applies `detect_screen_scale()`; default behaviour is `_scale_factor = 1.0` until the user opts in via Settings. Avoids silent double-scaling on top of Qt 6 auto-scale.
3. `§4` — added 5 new risk rows (#11–#15): Qt 6 auto-scale interaction, multi-study regression guard, intentional skip of `_vc_load.py`, multi-monitor drift between `_scaled()` and `sf()`, external QSS verification.
4. `§Phase 4` — added `reception_panel_widget.py` (10× font-size:14px).
5. `§Phase 5` — split single commit into 5 per-tier commits with smoke gate between tiers.
6. `§13` — timeline footnote updated to ~15 h realistic.
7. Added `§14` Qt 6 high-DPI interaction / best practices.
8. Added `§15` Implementation standards (per-commit gates).
9. Added `§16` this revision log.

Open questions — answered by user 2026-05-26:
- **(Q1) — RESTART-ONLY.** Settings slider writes the value via `save_scale_to_config()`, shows a "Restart to apply" prompt, and does **not** attempt live re-application. Justification: live polish/unpolish across the whole widget tree is fragile and would force us to touch a lot of widget lifecycles for marginal UX benefit. Restart is the standard, low-risk pattern for app-wide layout changes.
- **(Q2) — MANUAL FOR NOW, with follow-up.** The identity gate uses manual eyeball + screenshot comparison against a baseline saved before each phase under `docs/plans/responsive_ui_baselines/phaseN_pre.png`. A `pytest-qt` + perceptual-hash harness is filed as a non-blocking follow-up item (see §17 follow-ups). This avoids adding test infrastructure pressure on Phase 0–Phase 10 delivery.
- **(Q3) — RANGE CONFIRMED [0.75, 1.50].** Verified against Qt 6.11 high-DPI guidance (see §17): "Integer scale factors are preferred; 25% increments also give good results." The slider will therefore be **25%-step quantised** (0.75, 1.00, 1.25, 1.50) rather than free-floating. The `max(sf(40), 28)` guard on the 40-px sidebars covers the 0.75 floor (40 × 0.75 = 30 ≥ 28). Going below 0.75 is not supported.

---

## 17. Standards Conformance — Verified Against Qt 6.11 Official Documentation

**Source:** [Qt 6.11 High DPI documentation](https://doc.qt.io/qt-6/highdpi.html) (fetched 2026-05-26).

This section documents why each choice in this plan is consistent with the Qt-recommended approach, and what the Qt-native alternatives are and why we reject them for AI-PACS.

### 17.1 Qt 6 default high-DPI behaviour — what we inherit for free

Per Qt docs:
- "Qt supports high-DPI displays on all platforms and provides a unified API that abstracts over any platform differences."
- "Qt will automatically account for the display resolution when using higher-level APIs such as Qt Widgets … applications only need to provide high-resolution assets, such as images and icons. Changes in the platform's user preferences are automatically picked up."
- On Windows specifically: "Qt uses the Windows display scale settings automatically; no specific settings are required. For example, if a display is configured for 175% scale, then Qt apps will see a device pixel ratio of 1.75 on that screen."
- "Qt 6 is Per-Monitor DPI Aware V2 by default."

**Implication for AI-PACS:** at the default `_scale_factor = 1.0` we already get correct rendering at any Windows scale (100%, 125%, 150%, 175%, 200%) because Qt 6 handles it. `sf()` is **layered on top** of this — it is a user-preference multiplier, not a replacement for Qt's HiDPI pipeline.

### 17.2 Why we do NOT use `QT_SCALE_FACTOR`

Per Qt docs (verbatim from the Environment Variable Reference): "**QT_SCALE_FACTOR** — Sets a global scale factor. **For debugging and testing purposes.**"

Reasons this is wrong for AI-PACS:
1. Qt explicitly classifies it as a debug/test knob, not a user-preference mechanism.
2. It scales **everything** uniformly — including the viewer hot paths (`vtk_widget.py`, `lightweight_2d_pipeline.py`) that the project rules require us to leave alone. A global multiplier would alter clinical image presentation.
3. It is an environment variable and would have to be set before `QApplication` is constructed, which complicates Settings-driven user control.

### 17.3 Why we do NOT use `QT_SCREEN_SCALE_FACTORS` or `QT_USE_PHYSICAL_DPI`

Per Qt docs:
- "QT_SCREEN_SCALE_FACTORS — Setting this environment variable is **not recommended** since it prevents Qt from using system DPI values."
- "QT_USE_PHYSICAL_DPI — Using logical DPI is normally the best option; this environment variable can be set in cases where logical DPI is not available."

We rely on Windows display settings as the canonical platform-level scale source (Qt-recommended). The `sf()` user knob is layered on top per the project's clinical-ergonomics needs.

### 17.4 Why a custom helper IS the standard pattern for our use case

Per Qt docs (Configuring section): "Qt does **not** provide end-user facilities to configure the behavior of Qt's high-DPI support."

Translation: if an application wants a user-adjustable in-app UI scale slider (which we do), it must implement one itself. There is no Qt-supplied mechanism we are bypassing. A small helper that:
1. Multiplies geometry literals at `__init__` time
2. Identity-passes at scale 1.0
3. Persists the user preference to a writable config file
4. Applies on application restart

…is the established pattern in mature PySide6 codebases that need per-app scale control. The PrintingWidget `_scaled()` method (already in this codebase) follows the same pattern at a smaller scope; we are generalising it consistently.

### 17.5 Scale-factor rounding policy (Qt 6 default = `PassThrough`)

Per Qt docs: "Integer scale factors (for example, 1.0 or 2.0) are preferred for best results. 'Rounding' the scale factor to 25% increments can also give good results. Setting the scale factor or DPI to the exact physical display DPI may not give good visual results due to the fractional scaling involved."

Implications already incorporated:
- Slider quantised to 25% steps (Q3 above).
- We do **not** call `QGuiApplication.setHighDpiScaleFactorRoundingPolicy()` — Qt 6's default of `PassThrough` is correct for AI-PACS, since changing the rounding policy could alter the device pixel ratio that VTK code is currently happy with. Out of scope; flagged for follow-up only if rendering artifacts appear.

### 17.6 Image asset handling (follow-up, not in this plan)

Per Qt docs: "the application should also include high-DPI versions of static image assets … using a special naming convention for the high-density assets, for example `logo@2x.png` … Qt will automatically choose the best representation for the target display at runtime."

AI-PACS icons today are mostly Feather SVGs under `Qss/icons/fefefe/feather/`, which scale natively. Where raster PNGs exist (e.g. logo), an `@2x` variant would crisp them up at 200% Windows scaling. This is a **follow-up** task, explicitly **not** part of this plan — it is purely an asset-quality improvement and has no interaction with `sf()`.

### 17.7 Performance — sf() introduces no runtime overhead

- `sf()` is identity-fast at `_scale_factor == 1.0` (`if _scale_factor == 1.0: return px`). On the default install this is one integer comparison and one return — sub-nanosecond.
- Every `sf()` call site is at widget `__init__` time. No `sf()` is in `paintEvent`, `wheelEvent`, `set_slice`, `mouseMoveEvent`, or any hot path. The pre-commit grep gate in §15(5) enforces this.
- CSS stylesheets are built as f-strings exactly once per widget construction. `setStyleSheet()` is called once. No per-frame style recomputation.
- `_scale_factor` is a module-level Python float — read access is a dict-lookup-free local-namespace fetch. No QSettings round-trip, no I/O, no allocation.

Net runtime cost at default scale: **zero measurable overhead.** This was a top-line user requirement and is satisfied by the helper's design, not by adding caching or memoisation (which would introduce its own load).

### 17.8 Follow-ups (non-blocking, post-implementation)

1. **`@2x` icon variants** for the logo and any raster PNGs (§17.6).
2. **`pytest-qt` + perceptual-hash visual regression harness** (Q2).
3. **`setHighDpiScaleFactorRoundingPolicy()`** evaluation — only if rendering artifacts surface at 125%/175% Windows scaling.
4. **SVG migration** for any remaining raster icons in the toolbar.

None of these block Phase 0–Phase 10 delivery. They are quality-of-life improvements that should be filed as separate tickets after the core scaling work lands and is verified.

### 17.9 Approval gate

The user (project owner) confirmed on 2026-05-26: range [0.75, 1.50] OK, restart-on-apply OK, harness choice deferred to reviewer (manual chosen). With §17 confirming the approach matches Qt's documented standard pattern (no Qt-native alternative exists for our use case), and §14 / §15 / §16 covering risks, standards, and revision history, **Phase 0 implementation may begin** as soon as the user gives the explicit go-ahead.
