# Build Checklist

- Activate or create `.venv_build`
- Install `builder/requirements/build_requirements.txt`
- Install project runtime dependencies from `requirements-core.txt`
- Assemble the optional Advanced MPR runtime if that payload should ship: `python tools/assemble_slicer_runtime.py`
- Run `python build.py`
- Verify `builder/output/stage/core/AIPacs.exe` exists
- Verify `builder/output/stage/manifest/release_manifest.json` marks optional payloads correctly
- If `ISCC.exe` is available, verify installers:
  - `builder/output/installer/ai-pacs installer.exe`
  - `builder/output/installer/ai-pacs installer v<version>.exe`
- Run installer validation using `builder/docs/INSTALLER_QA_CHECKLIST.md`
