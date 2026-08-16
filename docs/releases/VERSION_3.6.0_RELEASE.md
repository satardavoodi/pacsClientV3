# AI-PACS v3.6.0 — Release Record

**Version:** 3.6.0
**Release date:** 2026-08-16
**Previous stable:** v3.5.9 (2026-08-10)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Milestone — EchoMind entitlement + Turbo refinements, browser-prewarm freeze fix, persistent pixel cache, footer removal, off-site server

---

## 1. Headline

**3.6.0** rolls the version to the 3.6 milestone. It consolidates the large 3.5.x
line and adds a focused set of fixes and features:

- an **EchoMind entitlement/licensing** layer plus further Turbo reporting
  refinements;
- a fix for a **72-second startup freeze** caused by the in-app browser warming up;
- a **persistent, async-initialised disk pixel cache** so images load faster on
  reopen;
- removal of the **redundant main-window footer bar**;
- support for an **off-site (external) server profile** alongside the local one.

---

## 2. EchoMind — entitlement + Turbo refinements

- **Entitlement / licensing layer** (`modules/EchoMind/entitlement.py`) that gates
  EchoMind features, with its own guard suite (`tests/code/echomind/test_entitlement.py`).
  `api_manager`, `llm_client`, `settings_store`, and the STT router/native provider
  were adjusted alongside it.
- **Turbo reporting refinements:**
  - **multi-region study** handling (`test_multi_region_study.py`);
  - **region detection from free text** (`test_region_from_text.py`) so a dictated
    region routes to the right module;
  - a **report-title rule** (`test_report_title_rule.py`);
  - Turbo prompt/template + session-metadata tweaks; the correction and
    turbo-is-locked guards updated.
  Turbo remains **pinned to the company pipeline** (locked configuration).

`modules/EchoMind/*` is plugin-mirrored — canonical and payload copies updated in
sync.

---

## 3. 72-second browser-prewarm startup freeze

**The problem.** The in-app web-browser (Chromium/WebEngine) prewarm — a warm boot
deferred to idle — could still land at an unlucky moment and block the **GUI thread
for ~72 seconds**, freezing the whole workstation at startup.

**The fix.** The idle gate is hardened with additional **busy** and **recency**
vetoes: the warm boot only proceeds when the user has genuinely paused and has not
just interacted, so it never competes with the first clicks after launch. Kept behind
the existing kill switch.

Guards: `tests/code/web_browser/test_prewarm_busy_veto.py`,
`test_prewarm_recency_veto.py`, `test_prewarm_idle_gate.py`,
`tests/code/system/test_browser_prewarm_idle_gate.py`. Reports:
`docs/reports/FREEZE_72S_BROWSER_PREWARM_2026-08-16.md`,
`WEBENGINE_WARMUP_EVALUATION_2026-08-16.md`.

---

## 4. Persistent + async-init disk pixel cache

The FAST viewer's decoded-pixel **disk** cache (`modules/viewer/fast/disk_pixel_cache.py`)
now **persists across sessions** and **initialises off the hot path** (async), so
reopening a study reads decoded pixels from the on-disk cache instead of re-decoding —
faster reopen on a warm cache, with no added latency on the open path. Guards:
`tests/code/viewer/test_disk_pixel_cache_persistence.py`,
`test_disk_pixel_cache_async_init.py`, `test_viewer_import_warm.py`. Report:
`docs/reports/PIXEL_CACHE_PERSISTENCE_2026-08-16.md`.

---

## 5. Main-window footer bar removed

The redundant bottom footer bar (which duplicated status shown elsewhere) is removed
across `AIPacs_ui.py`, `mainwindow_ui.py`, `_hp_search.py`, and
`secretary_button_widget.py`, reclaiming vertical space and simplifying the window.
Guard: `tests/code/ui_services/test_main_footer_bar_removed.py`. Report:
`docs/reports/MAIN_FOOTER_BAR_REMOVAL_2026-08-10.md`.

---

## 6. Off-site (external) server profile

Centers can now add an **external / off-site server endpoint** alongside the LAN one.
This release adds the razi center's own off-site profile (`config/servers.json`,
`config/server_profiles.json`) — its public host with the AI modules and reception API
— while **preserving the existing LAN `razi` profile and `active_profile_id`**. This is
a deliberate own-config addition, not a foreign environment: the local profile and the
active selection are unchanged.

---

## 7. Engineering

- **Regression catalog** (`docs/plans/architecture/REGRESSION_CATALOG.md`) and an
  open-findings log (`docs/reports/OPEN_FINDINGS_2026-08-16.md`).
- Subsystem / guard indexes refreshed (`docs/INDEX_BY_SUBSYSTEM.md`,
  `tests/INDEX_BY_GUARD.md`).
- Update feed metadata (`module_package_feed.json`) and all 14 `module_package.json`
  advanced to 3.6.0.

---

## 8. Verification status

Offscreen (test lane): new guard suites for the entitlement layer, multi-region
study, browser-prewarm busy/recency vetoes, disk-pixel-cache persistence + async init,
and the footer-bar removal all live under `tests/code/`.

**Still required — live source-build verification:**

1. **Startup:** launch the app and confirm no multi-second freeze from the browser
   prewarm; the workstation is responsive from the first click.
2. **Reopen speed:** open a study, close it, reopen — decoded pixels come from the
   persistent cache (faster) with no slower first open.
3. **EchoMind:** the entitlement gating behaves as intended; a multi-region study
   routes to the right reporting modules.
4. **Footer:** the main window renders correctly without the footer bar.
5. **Off-site server:** select the off-site profile and confirm connectivity; the LAN
   profile still works.

---

## 9. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.6.0` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
