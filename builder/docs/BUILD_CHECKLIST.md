# Build Checklist

- Activate/create `.venv_build`
- Install `builder/requirements/build_requirements.txt`
- Install project dependencies (pinned)
- Run `builder/audit/scripts/run_audit.py`
- Run `builder/audit/scripts/generate_build_docs.py`
- Review `builder/audit/reports/AUDIT_SUMMARY.md`
- Confirm privacy exclusions include `Education/`, `source/`, `attachment/`, `generated-files/`, `thumbnails/`, `database/`, logs, `.env`
- Build App A with `builder/spec/appA_workstation.spec`
- Build App B with `builder/spec/appB_slicer.spec`
- Run diagnostics (`builder/scripts/diagnose_imports.ps1`)
- Smoke test App A and App B exes from `builder/output/dist/`
- Record issues/fixes in `builder/docs/BUILD_DOCUMENT.md` (Section F)
