# OPT-01 (startup main-thread) — idempotent theme-apply dedup — 2026-07-03

**Backlog item:** OPT-01 (main-thread blocking) in
`docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` §9. Second increment (after the status-refresh
dicom-only trim).
**Type:** minimal safe edit, flag-gated default-on, offscreen-verified. **Live-verify pending.**
**Kill switch:** `AIPACS_THEME_APPLY_DEDUP=0` → byte-identical always-apply.

## Root cause (from the 2026-07-03 probe run)

After the status-refresh fix, the fresh probe run (`sess-4e53e3d33995`, pid 38204) showed the largest
remaining main-thread freeze was **theme application at startup**:

```
gap=2264 ms  ... _hp_layout.apply_theme -> patient_search_widget.apply_theme -> _apply_field_styling
```

`PatientSearchWidget.apply_theme` runs ~15 `setStyleSheet` calls, including `_apply_field_styling` over
**11 input fields** (each a large QSS block). It is invoked several times during construction with the
**same** theme:

- `setup_ui()` calls `_apply_field_styling()` (line 89),
- `__init__` then calls `self.apply_theme(self._active_theme)` (line 29) → `_apply_field_styling` again,
- `_hp_layout.apply_theme` (line 731) re-applies the theme to the search widget,
- `home_panel/widget.py` applies theme again.

Every stylesheet is a **pure function of the theme dict**, so re-applying an unchanged theme is redundant
work with a byte-identical visual result — but each call forces a full Qt style recomputation + relayout.

## Fix

Idempotent skip-guard in `PatientSearchWidget.apply_theme`: remember the last applied theme
(`_applied_theme_sig`) and return early when the incoming theme is unchanged.

```python
self._active_theme = theme or self.theme_manager.current_theme()
t = self._active_theme
if os.getenv("AIPACS_THEME_APPLY_DEDUP", "1") != "0":
    try:
        if t is not None and getattr(self, "_applied_theme_sig", None) == t:
            return
    except Exception:
        pass
... (unchanged styling) ...
self._apply_field_styling(t)
self._apply_date_field_styling(t)
self._applied_theme_sig = t
```

## Why it is safe

- **Idempotent:** re-applying the identical theme produces byte-identical stylesheets, so skipping is
  behavior-preserving. Verified visually-equivalent by construction (pure function of `t`).
- **Nothing left unstyled:** every styleable child widget is created in `setup_ui()` *before* the first
  `apply_theme` (line 29), so the first (applied) call styles them all; only later identical re-applies
  are skipped.
- **Real theme changes still re-style:** `themeChanged` delivers a *different* theme dict → `!= t` →
  full apply. Value comparison (`==`) also catches a fresh dict with identical content.
- Flag-gated default-on; `=0` restores the exact legacy always-apply.
- Scope is one method on one widget (the measured hot one); other widgets' `apply_theme` are untouched.

## Files changed

- `PacsClient/pacs/workstation_ui/home_ui/patient_search_widget.py` — `import os`; skip-guard + signature
  in `apply_theme`.
- `tests/code/ui_services/test_theme_apply_dedup.py` — new guard (source-pins + mirror-behavioral).

## Verification

- `py_compile` clean.
- Offscreen: 20 passed (`test_theme_apply_dedup` + `test_status_refresh_dicom_only` +
  `test_status_refresh_chunked`, `-p no:debugging`).

## Acceptance / rollback

- **Acceptance (live):** re-run the stall-trace probe; `apply_theme` / `_apply_field_styling` should drop
  out of the startup stall traces (or shrink markedly); the app looks identical across themes; switching
  themes still restyles.
- **Rollback:** `AIPACS_THEME_APPLY_DEDUP=0` (or git revert the two files).

## Remaining OPT-01 startup work

The ~1.3 s `add_AIPacs_tab` / `_wrap_home_tripane_in_splitter` tab construction (P1.4 / OPT-12) and the
~0.3 s thumbnail-widget build remain. Same dedup pattern may apply to `data_access_panel.apply_theme` /
`import_preview_dialog.apply_theme` if a future trace shows them hot (not yet measured).
