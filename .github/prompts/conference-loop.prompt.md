---
mode: agent
description: AI-PACS Conference Loop — pass every issue through Person A (analysis + plan), Person B (critical review), Person C (arbitration), then a Final consolidated decision, before writing any code.
---

# Conference Loop (A → B → C → Final)

Run four reviewers sequentially before any edit. **Do not jump to implementation** — the loop
ends at a Final plan; implement only after approval. Ground every claim in evidence (a log line,
a file, a `CLAUDE.md` guard). All reviewers share the same context: code via
`.github/copilot-instructions.md` + `CLAUDE.md`, logs in `user_data/logs/`, the verify and
clinical test lanes, and live-app observation. Even a small issue gets all four passes — keep
each section short when the issue is small.

**Loop 1 — Person A (analysis + plan):** understand the exact issue; find the affected
module / UI / backend / pipeline; review code, logs, docs; analyse side effects; propose a fix;
define acceptance criteria.
Output: `Person A Analysis` / `Person A Proposed Plan` / `Person A Risks` / `Person A Acceptance Criteria`.

**Loop 2 — Person B (critical review):** check A against the *actual* repo — missed points, wrong
assumptions, duplicate logic, unsafe architecture, regression risk, touched `CLAUDE.md` guards.
Output: `Person B Review` / `Concerns About Person A Plan` / `Suggested Corrections` / `Regression Risks`.

**Loop 3 — Person C (arbitration):** decide which points from A and B are valid, resolve
conflicts, choose the safest project-aligned direction, prioritise.
Output: `Person C Judgment` / `Accepted Points from A` / `Accepted Points from B` / `Rejected or Deferred Points` / `Final Technical Direction`.

**Loop 4 — Final decision:** one implementable instruction.
Output: `Final Implementation Plan` / `Files/Modules to Inspect` / `Safe Fix Strategy` / `Test Plan` / `Acceptance Criteria`.
State explicitly what must NOT change: FAST never instantiates VTK render windows; never remove
metadata / overlays / measurements / sync / reference lines / sidebars; keep cross-patient
isolation and multi-study gating; never write the live `dicom.db`.

Then stop and wait for approval. On go-ahead, follow `/root-cause-fix` and `/regression-guard`.
