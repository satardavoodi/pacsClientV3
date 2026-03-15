# Build Checklist

- Activate/create `.venv_build`
- Install `builder/requirements/build_requirements.txt`
- Install project dependencies (pinned)
- Assemble the optional Advanced MPR runtime if that payload should ship: `python tools/assemble_slicer_runtime.py`
- Run `python build.py`
- Verify `builder/output/stage/core/AIPacs.exe` exists
- Verify `builder/output/stage/manifest/release_manifest.json` marks optional payloads correctly
- If `ISCC.exe` is available, verify the installer is written to `builder/output/installer/`
- Smoke test the installed app on a clean Windows profile
