# AI-PACS v3.6.3 — Release Record

**Version:** 3.6.3
**Release date:** 2026-08-23
**Previous stable:** v3.6.0 (2026-08-16)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor — AiPacs Chat module, verified module-install pipeline, stable license fingerprint, consultation/education settings, MPR stability

*(3.6.1 / 3.6.2 were intermediate internal iterations; this publishes the
consolidated state as 3.6.3.)*

---

## 1. Headline

Two threads: a new **AiPacs Chat** manager module, and hardening of the plumbing
around **modules and licensing** — a verified install pipeline so "installed" means
"usable", and a stable license fingerprint so licenses survive a reboot. Plus a
centralized Consultation & Education settings tab, and a batch of **MPR
interaction/lifecycle stability** work with report image insert and YBR colour /
import-freeze fixes.

---

## 2. AiPacs Chat manager module

A new installable module for team messaging: a workstation-side console plus a
Laravel-backed chat API. Ships as its own plugin package + definition
(`builder/plugin package/{definitions,packages}/aipacs_chat/`), module code
(`modules/aipacs_chat/`), config (`config/aipacs_chat/aipacs_chat.json`), a
Consultation & Education settings surface, and its guard suite
(`tests/code/aipacs_chat/`).

**Deployment caveat:** the chat **API is not yet deployed to production
ai-pacs.com**, so the client will report "server does not have the chat API" until
the backend is live. The client is shipped and ready. Design + gap docs:
`docs/plans/AIPACS_CHAT_MODULE_DESIGN_2026-08-19.md`,
`docs/reports/AIPACS_CHAT_WORKSTATION_CAPABILITY_AND_GAP_2026-08-22.md`.

---

## 3. Verified module-install pipeline (OPT-53)

The "icon visible, but the module isn't installed correctly" class is closed. Every
install channel — installer first-launch bootstrap, Settings (package / folder /
URL), and the update feed — now funnels through one `install_module_package()` path
that:

- **hash-verifies** the payload when the feed provides a sha256, and guards against
  zip-slip;
- **verifies after install** — the catalog `requires` dependencies resolve, and a
  healthcheck import/path succeeds — before reporting success;
- **auto-enables** the module's own feature flag on a verified install (the shipped
  template stays force-OFF; the flip happens per-workstation at install time);
- records everything to a module-install log and, on failure, marks the module
  `install_incomplete` with a **precise reason** rather than a generic string.

`installation_module_settings.py`, `aipacs_runtime.py`, `config_sanitizer.py`,
`builder/installer/AIPacs_Setup.iss`; guard
`tests/code/runtime/test_module_install_verification.py`. Review:
`docs/reports/MODULE_INSTALLATION_ARCHITECTURE_REVIEW_2026-08-22.md`.

---

## 4. Stable license fingerprint

Licenses were being lost on reboot: the hardware ID was recomputed each launch from
unstable inputs (`uuid.getnode()` + COMPUTERNAME), so the fingerprint drifted and
validation failed. It is now derived from the **Windows MachineGuid + volume serial**
(stable across reboots), with legacy-compatible validation so existing licenses keep
working, a dedicated `license.log`, and a probe + tests.
`modules/LicenseGenerator/license_manager.py`, `tests/code/licensing/`.

*(The prior implementation is preserved as `license_manager.py.bak_prestable`, which
is gitignored — not shipped.)*

---

## 5. Consultation & Education settings tab

Identity / website / consultation / chat / Google-Drive settings are centralized into
one Settings surface (`PacsClient/.../settings_ui/consultation_education_settings.py`),
with a new Identity **host-user resolver** (`modules/Identity/ui/host_user.py`) so
the signed-in operator is resolved through one shared authority. Sign-in remains via
the existing dialog; env vars still win at read time.

---

## 6. Viewer / MPR

- **MPR interaction + lifecycle stability** — crosshair interaction / render / state
  refactors, an explicit `_mpr_lifecycle` module, oblique / orientation /
  geometry-constraint work, and step instrumentation, addressing the MPR
  freeze/stability reports (`MPR_FREEZE_54675_2026-08-18.md`,
  `MPR_INTERACTION_STABILITY_2026-08-23.md`, `MPR_LIFECYCLE_RELEASE_2026-08-19.md`,
  `MPR_GEOMETRY_CONSTRAINTS_BRIEF_2026-08-23.md`).
- **Report image insert / capture** — capture viewport images and insert them into a
  report (`report_capture_images.py`, `report_image_picker_dialog.py`, report-editor
  wiring). Report: `REPORT_IMAGE_INSERT_2026-08-18.md`.
- **YBR colour + import-freeze fixes** — correct colour handling in the FAST pipeline
  (`dicom_color.py`, `decode_service.py`, `lightweight_2d_pipeline.py`,
  `qt_viewer_bridge.py`) and an import-path freeze fix
  (`IMPORT_FREEZE_AND_YBR_COLOR_2026-08-21.md`); text-annotation input and
  reference-line active-viewport refinements.

---

## 7. Stability / engineering

- GUI-thread disk-path audit (`GUI_THREAD_DISK_PATHS_2026-08-22.md`), close-path hang
  visibility, CPU-budget priority boost, assignment-snapshot batch write, list-stream
  backpressure, and an end-user stability review
  (`ENDUSER_SANAM_STABILITY_REVIEW_2026-08-23.md`).
- Regression catalog and open-findings refreshed; **15** module packages + the update
  feed advanced to 3.6.3.

---

## 8. Verification status

Offscreen (test lane): new guard suites for AiPacs Chat, module-install verification,
licensing, host-user resolution, settings UI, MPR interaction/lifecycle, report image
insert, reference-line active viewport, text-annotation input, GUI-thread disk paths,
list-stream backpressure, and close-path hang visibility live under `tests/code/`.

**Still required — live source-build verification:**

1. **Module install:** install a module via each channel → it verifies and actually
   opens; a broken install reports a precise reason.
2. **License:** activate, reboot, confirm the license is still valid.
3. **AiPacs Chat:** once the production API is deployed, confirm end-to-end; until
   then the client should degrade gracefully with the "no chat API" message.
4. **MPR:** interaction stability on the studies from the freeze reports; no
   lifecycle leaks across open/close.
5. **Consultation & Education settings:** the centralized tab reads/writes correctly.

---

## 9. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.6.3` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
