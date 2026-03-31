# Tools Folder

This directory is organized by purpose:

- `diagnostics/` — one-off DB, printing, and patient/series investigation scripts plus their saved outputs/notebooks.
- `slicer/` — Advanced 3D Slicer runtime assembly, download, verification, and direct-load test helpers.
- `performance/` — performance instrumentation, monitoring, test runners, and log analysis.
- `vtk/` — VTK scratch/merge/reference files and comparison patches.
- `dev/` — temporary developer utilities and repo-maintenance helpers.
- `git/` — GitHub push/connectivity scripts and local network config templates.

If you add a new script, place it in the closest matching subfolder instead of the `tools/` root.

For full governance rules, lifecycle expectations, and the future improvement roadmap, see:

- `docs/development/tools-governance-and-roadmap.md`
