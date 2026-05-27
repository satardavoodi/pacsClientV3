# Workspace Context — AI-PACS Workstation

This repository is **one half of a two-project workspace.** The other
half is the public AI-PACS website (WordPress + Laravel), which lives
on a separate drive at `d:\laragon-www\ai-pacs\public_html\`.

For workstation-internal work, the canonical entry points remain:

- [`README.md`](README.md) — top-level overview
- [`CLAUDE.md`](CLAUDE.md) — hard runtime/testing rules (login flow,
  monitor placement, multi-study viewer regression guards, etc.)
- [`docs/README.md`](docs/README.md) — extensive architecture,
  pipelines, performance, releases

This `WORKSPACE.md` file exists only to direct cross-project work to
the right place.

## Cross-project work starts here

If your task touches anything below, **read the workspace docs first**
before changing code in this repository:

- A shared user / login identity that exists on both the workstation
  and the website.
- License activation that calls back to the website.
- Sending a study from this workstation to the website as a
  Case-of-the-Day, course slide, or educational case.
- ATI workflows (training/assessment) — currently unimplemented on
  both sides; architecture is pre-designed so changes here stay
  compatible.
- Any new HTTP client in this codebase whose base URL is the AI-PACS
  website (not the existing private backend at `81.16.117.196`).

Workspace docs live at:

- [`d:\laragon-www\AGENTS.md`](file:///d:/laragon-www/AGENTS.md) —
  workspace entry point.
- [`d:\laragon-www\workspace-docs\`](file:///d:/laragon-www/workspace-docs/README.md)
  — full cross-project documentation (system overview, integration
  surface, shared user model, licensing, Case-of-the-Day bridge, ATI
  prep, glossary).
- [`d:\work space AI-Pacs company\`](file:///d:/work%20space%20AI-Pacs%20company/) —
  workspace container: `WORKSPACE_CONTEXT.md` (safety/clinical
  guardrails), `docs\decisions\` (ADRs that affect both projects),
  `docs\runbooks\` (cross-project ops), `docs\INDEX.md` (navigation
  hub). The three-root VS Code workspace
  (`AI-PACS-Ecosystem.code-workspace`) lives here too.

## What is *not* cross-project (no workspace-doc needed)

- Viewer pipelines, MPR, VTK geometry, ITK filter changes.
- Zeta Download Manager work.
- Anything inside `database/`, `modules/viewer/`, `modules/network/`
  that does not introduce a new endpoint or contract.
- Build / Nuitka / PyInstaller changes.
- Per-release notes.

Those continue to be governed by this repository's own docs.

## Outbound integration today (quick reference)

The workstation currently talks to a private backend (not in the
workspace) at `81.16.117.196`:
- socket protocol on port `50052` (DICOM, patient list, thumbnails,
  attachments) — see `modules/network/socket_config.py`
- HTTP REST on port `8080` (reception API) — see
  `modules/network/reception_api_config.py`
- HTTP REST for AI services — see
  `PacsClient/pacs/workstation_ui/settings_ui/servers_config.py`

There is currently **no HTTP client in this codebase whose base URL
points at the AI-PACS website**. When the workspace bridges
(licensing, case publishing, ATI) introduce one, it will live under
`modules/identity/`, `modules/web_publish/`, or `modules/ati/`, and
its base URL will be configured in
`config/website_api_config.json` — see the workspace docs for the
shape of that file.
