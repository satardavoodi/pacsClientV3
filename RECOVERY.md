# RECOVERY.md - ai-pacs beta version

> Part of the environment recovery set. Master guide: `D:\_RECOVERY\Document Recovery Account Vahid.md`
> Generated 2026-08-27.

```text
Project Name:        ai-pacs beta version
Primary Path:        E:\ai-pacs\ai-pacs codes\ai-pacs beta version
Repository:          https://github.com/Vahid-INO/ai-pacs.git
Branch:              beta-version
Main Technology:     claude-agent, git, python
Main Entry Point:    main.py
Size:                60274 files, 62425.6 MB
Last Modified:       2026-08-23
```

## How to run

```bash
python build.py           # Builds installer automatically
python -m venv .venv
python -m venv .venv_build
python main.py
python tools/diagnostics/run_database_backbone_evaluation_bundle.py \
Pytest suites
python -m pytest test_module_harness.py -v
python test_module_harness.py
```

## Important documentation

- `CLAUDE.md` - AI-PACS — Project Instructions
- `README.md` - Stable release: `v3.0.6` (`2026-05-18`)
- `docs/ADVANCED_OPTION_B_AFFINE_IMPLEMENTATION.md` - ADVANCED_OPTION_B_AFFINE_IMPLEMENTATION.md
- `docs/AIPACS_LAUNCH_CONTROL_RUNBOOK.md` - AI-PACS — Launch & Control Runbook (agent standard procedure)
- `docs/AUDIT_2026-05-28_OVERVIEW.md` - AI-PACS Staged Audit — 2026-05-28 to 2026-05-29
- `docs/ECHOMIND_PIPELINE_ARCHITECTURE_REVIEW.md` - EchoMind Module — Three-Pipeline Architecture Review
- `docs/INDEX_BY_SUBSYSTEM.md` - AI-PACS Documentation — Index by Subsystem
- `docs/matab-conservative-fast-cache-plan.md` - Conservative FAST Cache Architecture Plan
- `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` - Multi-Study Single-Tab Viewer — Implementation Record
- `docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` - AI-PACS — Software Optimization, Stability & Reliability Master Plan
- `docs/README.md` - AIPacs Documentation
- `docs/THEME_COLOR_REFERENCE.md` - Theme Color Reference
- `docs/VSCODE_AGENT_MODE_SETUP_2026-06-02.md` - VS Code Agent Mode — setup & optimization (2026-06-02)
- `docs/agent_control/browser_tools.md` - Browser Control Tools (Secretary e Command ↔ Web Browser)
- `docs/agent_control/clinical_agent_validation_pipeline.md` - EchoMind Secretary Clinical Agent Validation Pipeline
- `docs/agent_control/command_routing_rules.md` - Secretary / EchoMind — Command Routing Rules
- `docs/agent_control/echomind_secretary_agent_handoff.md` - EchoMind Secretary Agent Handoff
- `docs/agent_control/patient_tab_viewer.md` - Patient-Tab / Viewer control surface
- `docs/agent_control/qa_workflows.md` - QA / coding-agent workflows
- `docs/agent_control/secretary_echo_mind_instruction_map.md` - Secretary EchoMind — intent → tool map

## Required services

express, node, pyside6, s3, sqlite

## Configuration & environment

(no .env files in this project root)

## Skills

- agent-personality-workflow-engine
- aipacs-conference-loop
- aipacs-debug-thumbnails
- aipacs-inspect-logs
- aipacs-regression-guard
- aipacs-root-cause-fix
- aipacs-run-tests
- titan-engineering-system

Project agent config present: `E:\ai-pacs\ai-pacs codes\ai-pacs beta version\.claude\`

## MCPs

github, telegram, sqlite, jetbrains

Definitions and validation tests: master document, section 8.

## External integrations

clarity, openai

Domains referenced in docs: doc.qt.io, google.com, vtk.org, www.cornerstonejs.org

## Google Cloud dependencies

None.

## Recovery notes

- This local copy is the **authoritative** one. Do not clone a fresh duplicate.
- Recovery status as of 2026-08-27: **FOUND / VALIDATED** (path resolves, documentation readable).
- Conversation history that touched this project: `D:\_RECOVERY\out\index.html`

---

Recovery documentation:  
`D:\_RECOVERY\Document Recovery Account Vahid.md`
