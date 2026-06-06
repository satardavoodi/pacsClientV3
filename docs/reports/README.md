# docs/reports — dated investigation & as-built reports

Engineering session reports moved here from the repository root on 2026-06-06
(root cleanup). Each file is a point-in-time record: investigations, root-cause
analyses, as-built fix records, reviews, and KPI/stress evaluations — named
`TOPIC_YYYY-MM-DD.md`.

Conventions:
- New session reports go HERE, not in the repository root.
- `CLAUDE.md` regression guards reference several of these by path
  (`docs/reports/<name>.md`) — keep names stable.
- Cross-references between reports use bare filenames (same directory).
- Measurement artifacts (CSV/JSON) these reports cite live in
  `docs/analysis/data/<YYYY-MM>/`.
- One-off diagnostic scripts cited by older reports live in
  `tools/analysis/oneoff/`.
