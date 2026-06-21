# Running AI-PACS in an agent's Linux sandbox

This lets an assistant run the **offscreen pytest suite**, import checks and
ruff inside its headless Linux sandbox — so changes can be verified before a
live Windows GUI pass. It does **not** replace the clinical workflow: the actual
PySide6/VTK application still runs from the VS Code source build on Windows
(see `CLAUDE.md`). The sandbox is Linux + headless and cannot open the GUI app.

## One-time per session

The sandbox is ephemeral — installed packages are wiped between sessions, so run:

```bash
bash tools/dev/sandbox_setup.sh        # installs everything in requirements.txt
source tools/dev/sandbox_env.sh        # exports LD_LIBRARY_PATH + QT_QPA_PLATFORM=offscreen
python3 -m pytest tests/code/<target> -p no:debugging -q
```

`sandbox_setup.sh` is idempotent and the heavy wheels download **resumably**, so
if the run is interrupted just run it again — it skips what's installed and
resumes partial downloads.

## What gets installed

Every package in `requirements.txt`, all importable on Linux **except**:

- **`comtypes`** — Windows-only COM (Windows SAPI TTS). It installs but cannot
  import on Linux and stays inert, exactly as the app guards it. Not a problem.
- **`pyaudio`** — no Linux wheel; it is **compiled from source** against a
  vendored PortAudio (handled by the script).

Two system libraries Qt and the audio stack need (`libEGL`, `PortAudio`) are
vendored without root via `apt-get download` + `dpkg -x`, which is why
`sandbox_env.sh` puts them on `LD_LIBRARY_PATH`. Qt must run with
`QT_QPA_PLATFORM=offscreen` (no display).

## Caveats

- **Heavy download:** PySide6 + vtk + SimpleITK are ~360 MB and the sandbox link
  is ~1 MB/s, so the first setup takes several minutes (resumable).
- **Mount null-byte artifact:** the FUSE mount of the repo occasionally returns
  null bytes for a few very large source files, so a handful of tests **collect**
  with `source code string cannot contain null bytes` errors. This is a sandbox
  mount artifact, **not** a code bug. For a fully clean collect, copy the source
  to the local fs first:
  ```bash
  rsync -a --exclude user_data --exclude backups --exclude '.venv*' \
        --exclude generated-files "<repo>/" /tmp/aipacs-src/ && cd /tmp/aipacs-src
  ```
- **Disk:** the sandbox root has ~3.9 GB free; the full install fits but leaves
  little headroom.

## Verified (2026-06-21)

- 36/37 requirements import (only `comtypes` inert).
- `tests/code/ui_services/test_patient_study_set.py` → 26 passed (pure-Python).
- `test_v2_style_scaffold.py` + `test_ui_variant_scaffold.py` +
  `test_unified_pipeline_wiring.py` → 60 passed (Qt offscreen).
- Full suite: **1955 tests collect** (33 collection errors, mostly the mount
  null-byte artifact + Windows-only modules).
