# Secretary guided software help

Status: source investigation and implementation design; not a shipped runtime capability.

## Verified baseline

Secretary has server-owned planning, local typed CommandBus adapters, reply UI and module navigation. Home patient opening is wired through patient_table_widget.py itemDoubleClicked. Storage cleanup already has local preview and confirmation. Viewer tool activation is domain-specific; current annotation mapping includes FAST arrow activation. There is no shared tutorial target registry or guided-help action in the inspected bus/catalog. Education content search is distinct from workstation software help.

## Behavior

A how-to question starts a tutorial, not the requested destructive/editing action. For example, "How do I delete previous images?" explains local storage scope and confirmation; it must not call cleanup. Clarify whether the user means local downloaded studies, temporary cache or annotations when ambiguous. Explain that local cleanup is different from deletion on a PACS server. Explicit execution requests continue through existing permissions.

Server returns bounded structured tutorial proposals owned by Eagle Eye. Local code validates topic, step and target against installed live capabilities. No generated Python, selectors, coordinates or unverified UI procedures may execute. Labels and content remain English under repository policy.

## Components

1. Versioned software-help catalog: topic ID, supported viewer domain, prerequisites, ordered steps, explanation, allowed semantic target and expected user event. Review against actual source and live GUI.
2. Local target registry: semantic target ID maps to a weak QWidget reference or resolver; optional live item rectangle and context receipt. Never identify a patient by name. Home rows use current list identity and authoritative study identity; reject stale targets after sorting/search.
3. Tutorial controller: states idle, preparing, showing_step, waiting_for_user, completed, unavailable and cancelled. Navigation may be proposed only when necessary and within permission policy. Previous/Next/Exit remain available; do not advance solely because a highlight appeared.
4. Noninteractive overlay: red pulsing ring with transparent center, mouse-transparent widget, anchored through mapToGlobal and screen/window transforms. Recompute on resize/move/scroll; dismiss or re-resolve on target destruction, page/domain change and stale context. Keep ring off screenshots sent to AI. Do not move the actual OS cursor, click controls or block reading. Offer reduced-motion static ring. VTK targets use their documented GUI boundaries, not viewer rendering changes.
5. Secretary response panel: step number, concise instruction, Next/Previous/Exit and progress. Current status says Guiding, Waiting for your action, Done or Target unavailable. Instructions stay readable while the user acts.

## Proposed shared actions

- get_help_topics: bounded installed topic list; read-only.
- start_guided_help: typed topic_id and optional domain; local tutorial activation.
- get_guided_help_status: tutorial_id, state, current step and safe target availability.
- advance_guided_help: tutorial_id and next/previous; stale ID rejected.
- stop_guided_help: tutorial_id; remove overlay and release references.

These are proposals, not advertised capabilities. Implement in a dedicated help service and thin adapter, register in the shared bus/schema/validator/permissions, then expose thin MCP wrappers and deploy the matching Eagle Eye catalog/contract. GUI overlay activation needs a distinct local UI-control permission; do not label it a passive read or bypass remote gateway policy.

## Initial vertical slices

A. Open a patient: locate live patient list; if empty explain how to search. Highlight a valid row and say "Double-click this row to open the study." Wait for the real open event and matching identity. Do not open it automatically.
B. Rotate and annotate: discover active viewer/domain, resolve existing toolbar control, describe gesture and expected effect. Unsupported domains yield an explicit limitation instead of a fabricated instruction.
C. Clear previous local studies: explain Settings/Storage preview, scope and confirmation; highlight controls step by step. Never delete during help. Completion is learning-step acknowledgement, not deletion success.

## Gates

Synthetic guards for question-versus-execution separation, typed target allowlist, stale list rejection, domain isolation, mouse pass-through, resize anchoring, destroyed-target cleanup, cancel and restart. Test DB patches DATABASE_FILE and clears the pool; real patient data is excluded. Mirror/runtime packaging parity applies to new files. Live source acceptance checks actual pointer target, double-click boundary, viewer controls and deletion nonexecution. Human launches and signs in once; unavailable live acceptance is not a pass.

## Outstanding decisions and work

Build slice A first, then verify live before adding B/C. No server deployment, new action exposure or UI runtime implementation was performed by this design task. Existing execution services remain the foundation.
