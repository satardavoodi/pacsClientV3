# AI-PACS Module Installation Architecture — Comprehensive Review & Hardening

**Date:** 2026-08-22 · **Trigger:** AiPacs Chat reports "not installed correctly" although its icon and Settings section are visible · **Scope:** every module, every install channel · **Outcome:** root cause fixed, install pipeline made verified and self-diagnosing, v3.6.2 rebuilt

---

## 1. How the module system actually works (as-built)

The workstation has one module authority and five layers around it:

**`MODULE_CATALOG` (aipacs_runtime.py)** is the single source of truth: 15 modules, each with `id`, `tier` (`basic` = always installed with core, `optional` = per-workstation), `package_kind`, healthcheck, and (new) `requires` / `feature_flag` metadata.

**Build time:** `builder/plugin package/definitions/<id>/plugin_package.json` defines each distributable package; `materialize_plugin_packages.py` mirrors module sources into `builder/plugin package/packages/<id>/payload/…`; `build_release.py` stages them to `builder/output/stage/plugin_packages/<id>/` with a generated `module_package.json` (manifest: version, payload_dir, python_paths, healthcheck, sha256 in the feed) plus `module_package_feed.json`. The release gate (`builder/release_gate.py`) enforces mirror freshness, frozen-PYZ sentinels, and that every optional catalog id has a staged package.

**Installer (`builder/installer/AIPacs_Setup.iss`):** each optional module is a component (`optional\<id>`); selected components' packages are copied to `C:\ProgramData\AIPacs\module_packages\<id>\`; `WriteInstallationProfile()` writes `C:\ProgramData\AIPacs\config\installation_profile.json` with `modules.<id>: true/false` and `module_packages.<id>.status: selected_for_install | not_installed`. Unselected ⇒ `false`, no package files. The checkbox is *not* cosmetic at this layer.

**First launch (frozen only):** `main.py` → `bootstrap_installer_selected_module_packages()` → for every selected-but-not-installed module, `install_module_package()` installs from the ProgramData package: registers a manifest in `%APPDATA%\AIPacs\module_registry\<id>.json`, updates the roaming `runtime_profile.json`, copies payloads to `%LOCALAPPDATA%\AIPacs\modules_runtime\<id>` and appends their `python` dirs to `sys.path` (append-only — engine code always wins, rule R24).

**Runtime gate:** `is_module_enabled(id)` reads runtime profile ⟶ installation profile ⟶ catalog defaults. On source runs it returns `True` for everything (`development_module_defaults`) unless `AIPACS_RESPECT_MODULE_PROFILE_IN_DEV=1`. Feature-level modules add their own flag files (e.g. `aipacs_chat_available()` = Identity flag AND own flag AND registry).

**Settings ▸ Installation & Updates:** table of `module_installation_statuses()`; Install Package / From Folder / From URL; Enable/Disable (`set_module_enabled` — flips the profile, files stay); Test Module (`validate_module_installation`); update feed (`summarize_available_updates` → `install_component_update` for modules, full installer or OPT-38 delta for core).

### Per-module inventory

| Module | Tier | Kind | Code ships in | Package payload | Healthcheck | Own feature flag |
|---|---|---|---|---|---|---|
| viewer | basic | core | engine | — | — | — |
| download_manager | basic | core | engine | — | — | — |
| zeta_boost | basic | core | engine | — | — | — |
| education | basic | core | engine (mirrored pkg) | modules/education | education_main_widget | — |
| stitching | basic | core | engine | modules/stitching | modules.stitching | — |
| offline_cloud_server | basic | core | engine | modules/offline_cloud_server | service | — |
| identity | basic | core | engine | modules/Identity | feature_flags | `identity/identity.json` (ships ON) |
| data_analysis | optional | bundled_unlock | engine + pkg | modules/data_analysis | modules.data_analysis | — |
| advanced_mpr | optional | **runtime_payload** | **package only** | Slicer runtime + exe | AIPacsAdvancedViewer.exe | — |
| printing | optional | bundled_unlock | engine + pkg | modules/printing | printing_widget | — |
| run_cd | optional | bundled_unlock | engine + pkg | modules/cd_burner | cd_burn_dialog | — |
| web_browser | optional | bundled_unlock | engine + pkg | modules/web_browser | modules.web_browser | — |
| echomind | optional | bundled_unlock | engine + pkg | modules/EchoMind | settings_store | — |
| consultation | optional | bundled_unlock | engine + pkg | modules/cloud_consultation | feature_flags | education/consultation flags |
| aipacs_chat | optional | bundled_unlock | engine + pkg | modules/aipacs_chat | feature_flags | `aipacs_chat/aipacs_chat.json` (ships OFF) |

Key structural fact: for `bundled_unlock` modules the Python code also ships inside the core engine (PYZ); the "package" install is a registration/unlock, not the code's only carrier. Only `advanced_mpr` (runtime_payload) is physically absent when unselected. See §6.

---

## 2. The AiPacs Chat bug — root causes (verified live, not inferred)

The dialog "The AiPacs Chat module is not installed or not enabled for this workstation" fires when `aipacs_chat_available()` is false. That is one string for **three independent conditions**, and two of them were broken:

**Cause A — the module registry says no.** `C:\ProgramData\AIPacs\config\installation_profile.json` on this machine (installed 3.5.0, July 12) contains 14 modules — **no `aipacs_chat` key at all**. `configured_module_map()` then falls back to the catalog default `default_enabled: False`. This applies to *every* machine whose profile predates the chat module: installs from any pre-8/19 installer, and — importantly — machines whose engine was brought forward by the OPT-38 **delta auto-update**, because deltas only rewrite `engine/**` and never touch the installation profile or ship module packages. Such machines get the chat-era engine (icon + Settings ship in core, deliberately always visible) with no way for the registry leg to pass. The `.iss` itself was already correct: `aipacs_chat` component, `[Files]` line, and both profile writers landed 8/19–8/20 — tonight's v3.6.1 (built 21:04) was the first complete chat installer.

**Cause B — the module's own flag ships OFF and nothing turned it on.** `builder/config_sanitizer.py` forces the shipped `config/aipacs_chat/aipacs_chat.json` template to `{"enabled": false}` (correct: the dev tree must not leak its state into releases). But no code path enabled it after an install — so even a *perfect* fresh install with the checkbox ticked showed the exact same dialog until the user found Settings ▸ Consultation & Education ▸ AiPacs Chat. "Selected during installation → runnable" was false by design.

**Cause C — the diagnostic was useless.** One generic sentence covered: package never installed, package installed but disabled, install actually failed, own flag off, Identity off. Nobody — including the installer's author — could tell which applied from the dialog.

Also audited and ruled out: the staged package is complete (payload/python/modules/aipacs_chat + manifest, correct version + sha256); the plugin definition exists; the parity guards (`test_iss_write_installation_profile_covers_module_catalog`, `test_plugin_package_registry`) pass; the chat code is present in the engine (which is why the icon and dialog work at all).

---

## 3. What was fixed (all channels, not just chat)

**One verified install pipeline** — `install_module_package()` now runs, for installer bootstrap, Settings (package / folder / URL) and feed updates alike:

```
download → sha256 verify (when the caller knows the hash — feed hashes now enforced)
→ extract (zip-slip guarded) → manifest validate → payload copy → register manifest
→ profile update → runtime path activation
→ POST-INSTALL VERIFICATION (dependencies + healthcheck)
→ feature-flag auto-enable → "installed"
```

A package whose verification fails is recorded as **`install_incomplete`** with the specific reason, its module stays disabled, and the UI says so honestly — "download finished" is never reported as "installed" (requirements 9, 10, 16).

**Feature-flag auto-enable** (requirement 2): new catalog key `feature_flag: {config, key}`. After a successful *verified* install with `enable_on_install`, `apply_module_feature_flag()` switches the module's own toggle ON in the workstation's roaming config — the shipped template stays force-OFF, the flip happens per-machine at install time, honoring the user's explicit selection. `aipacs_chat` opted in; the mechanism is generic for future modules.

**Dependency validation with named diagnostics** (requirement 14): new catalog key `requires: [ids]`. `validate_module_installation()` now checks each dependency is installed, enabled, and (when it declares a flag file) not switched off — producing e.g. *"AiPacs Chat cannot start because the Identity & Accounts module is switched off in this workstation's settings."* Identity declares its flag read-only for this purpose.

**Precise unavailability reasons** (requirements 12, 13, 14): new `aipacs_chat_unavailable_reason()` names each failing gate condition and where to fix it (Installation & Updates for install/enable; Consultation & Education for the toggle; the recorded warning for failed installs; the env var when forced). `open_aipacs_chat` shows it instead of the generic string. The icon stays always-visible (your chosen policy) but can no longer *pretend* readiness.

**Honest states end-to-end** (requirements 11, 12): `_package_record` no longer flattens recorded `install_failed` / `install_incomplete` back to installed/not_installed — failure states win until a later successful install clears them. The Settings table gained a **Status** column (`core / installed / not_installed / ⚠ install_failed / ⚠ install_incomplete`) with the recorded warning as tooltip, alongside the existing Installed/Enabled columns — Disabled (files present, not loaded) and Not Installed are now visibly distinct states.

**Package integrity** (requirements 7, 9, 10): the feed's per-package sha256 is enforced in `install_component_update`; zip extraction rejects path-traversal members. The package format itself was already unified (same `module_package.json` + payload structure for installer, folder, package and URL installs — requirement 7 was architecturally satisfied; it now also *verifies* uniformly).

**Logging** (requirement 17): dedicated `<User Data>/logs/module_install.log` (`aipacs.module_install`, also propagating to the app log): bootstrap's installer-selected set and available bundled packages, download size, hash result, manifest version, payload target, registration, profile updates, verification verdict, feature-flag application, and every failure with its reason.

**Docs/plan:** master plan §9 **OPT-53** + §15 entry; CLAUDE.md "New module checklist" step 7 (install-pipeline invariants + the two new catalog keys); project memory `module_install_verified_pipeline_2026-08-22`.

**Version:** bumped to **3.6.2** so the fixed installer is distinguishable from tonight's earlier 3.6.1 and so 3.6.1 installs see a core update in the feed.

### Files changed

`aipacs_runtime.py` (catalog metadata, pipeline, verification, diagnostics, logging) · `modules/aipacs_chat/feature_flags.py` + its plugin-package mirror (unavailable-reason) · `PacsClient/.../home_panel/_hp_modules.py` (precise dialog) · `PacsClient/.../settings_ui/installation_module_settings.py` (Status column, honest install dialogs) · `pyproject.toml` (3.6.2) · CLAUDE.md, master plan · new tests (below).

---

## 4. Requirement-by-requirement status

| # | Requirement | Status |
|---|---|---|
| 1 | Review every module individually | Done — §1 inventory |
| 2 | Installer checkbox has real effect | Done — was already real for files/profile; now also verified + auto-enabled, so the module *opens* |
| 3 | Unselected modules not installed | Done at package/profile level; engine-code caveat in §6 |
| 4 | Shared core vs module-specific files | Mapped in §1; bundled_unlock caveat in §6 (staged) |
| 5 | Chat bug root cause | Fixed (§2, §3) — not hidden: the error now names its cause |
| 6 | Settings ▸ Installation/Update workflow | Reviewed + hardened (verification, states, honest dialogs) |
| 7 | One package format for all channels | Already unified; now uniformly validated (manifest + hash) |
| 8 | Install from Folder | Validate → manifest → install → register → **verify** ✔ |
| 9 | Install from Package | Same pipeline + zip-slip guard ✔ |
| 10 | Install from URL | Download → hash → same pipeline; success ≠ download ✔ |
| 11 | Disabled vs Not Installed | Distinct in profile, record, and UI |
| 12 | Module status set | core / installed / not_installed / disabled(=enabled No) / install_failed / install_incomplete / update_available (feed table) |
| 13 | UI visibility | Your choice: icon stays, click gives precise reason + fix path |
| 14 | Dependency validation | `requires` + flag-value checks, named messages |
| 15 | Versioning & updates | Already present (manifest version, feed compare, update statuses); hash now enforced |
| 16 | Post-install verification | Implemented as the pipeline's final gate |
| 17 | Logging | `module_install.log` covering selection→verification |
| 18 | Test matrix | §5 |

---

## 5. Verification

**Automated (all green):**
- New `tests/code/runtime/test_module_install_verification.py` (7): install registers + verifies + auto-enables the flag; verification failure ⇒ `install_incomplete` + disabled + no flag flip; sha256 mismatch rejected; zip-slip rejected; failure status preserved in records; switched-off dependency named; feed sha256 forwarded.
- New `tests/code/aipacs_chat/test_unavailable_reason.py` (8): each gate condition produces its own named reason; none when available.
- Regression: `tests/code/runtime` + `tests/code/aipacs_chat` + `tests/code/builder` + `tests/code/settings_ui` = **346 passed, 0 new failures**. The 6 reds in `test_nuitka_arm64_parity.py` are the documented pre-existing Nuitka-pipeline breakage (`git diff HEAD` is empty on every file they read; restore patch pending since 2026-08-02).
- Parity guards (catalog ↔ .iss ↔ plugin definitions ↔ config templates ↔ mirrors) all pass; the chat mirror was re-synced after the feature_flags edit.

**Release build:** v3.6.2 (PyInstaller x64 + WoA installer) launched via the scheduled-task recipe (survives MCP-host restarts); the release gate runs inside it. Status at report time is in the chat conversation.

**Needs a live install to close (the part no unit test can prove):**
1. Fresh v3.6.2 install, chat **ticked** → first launch → `module_install.log` shows bootstrap + verification → chat opens with **no Settings visit**.
2. Fresh install, chat **unticked** → icon click names "not installed" + the install path; Settings shows `not_installed`; nothing chat-related in ProgramData.
3. Settings ▸ Install From URL/Package with the staged `aipacs_chat-3.6.2.zip` → "installed and verified" → restart → opens.
4. Disable → precise "installed but disabled" dialog; Re-enable → opens.
5. Update path: point the update source at the 3.6.2 feed from a 3.6.1/older install → Apply Selected Update on AiPacs Chat → verified install. **This is the recovery path for the clinic machine that showed the bug — no reinstall needed.**

---

## 6. Remaining risks & staged work (deliberately not done tonight)

**Physical code separation (staged).** For `bundled_unlock` modules the implementation still ships inside the core engine; "not installed" means *locked by the registry*, not *absent from disk*. True separation (per-module PYZ exclusion + payload-only import through `modules_runtime`) is the architecture your requirement 3/4 ultimately describes, but it changes the frozen build's import graph for seven modules and must be piloted (chat first) with dedicated live-build testing — a wrong exclusion bricks a module for every customer. The runtime already supports payload-only loading (advanced_mpr proves it), so the staged plan is: exclude one module from the spec → healthcheck via payload path → release-gate probe that the PYZ does *not* contain it → live matrix.

**Nuitka installer is chat-blind.** `builder nuitka/installer/AIPacs_Nuitka_Setup.iss` (untouched since 7/16) has no `aipacs_chat`; the Nuitka pipeline is already known-broken (ARM64 restore patch pending). Fix it there when that pipeline is revived — do not ship a Nuitka build expecting chat.

**Enabling ≠ backend.** Install/enable fixes the *gate*. The chat console still needs the production Laravel chat API deployed on ai-pacs.com (probed 404 on 2026-08-20), and shipped builds blank `identity/aipacs_web.json` base_url until the workstation is configured/signed in. The console will open and then report the server state truthfully — that part is by design.

**Consultation module** could adopt the same `requires`/`feature_flag` metadata; left unchanged tonight to keep the blast radius at chat + shared pipeline.
