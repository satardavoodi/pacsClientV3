# Prompt for VS Code Copilot — AI-PACS repo / runtime / build situation report

Copy everything below the line into VS Code Copilot (Agent mode, so it can run terminal commands).

---

You are auditing this AI-PACS workstation repo. A SEPARATE assistant (in a Claude
"Cowork" session) has been editing source files directly on disk to add a "Previous
Exams" feature plus viewer fixes (viewport origin border, a multi-study **stable-slot
registry**, a study-scoped cache guard, and a `[VIEWPORT-LOAD-TRACE]` log line). Those
edits appear in the files on disk but **do NOT take effect in the running app**, even
after restarting it from VS Code. Meanwhile this repo also had commits + a v3.3.4
installer build done from here. I need a precise, evidence-based report — run commands,
don't guess. Do NOT change, commit, stash, reset, build, or delete anything; this is
read-only diagnosis. Report exact command output.

Please produce a structured report answering ALL of the following.

## 1. Repository identity & location
- Run `git rev-parse --show-toplevel` and report the absolute repo path. Confirm whether
  it is exactly `E:\ai-pacs\ai-pacs codes\ai-pacs beta version`.
- `git rev-parse --abbrev-ref HEAD`, `git remote -v`, `git log --oneline -10`.
- Is there MORE THAN ONE copy of this project on the machine? Search common roots for a
  second working tree, e.g.:
  `Get-ChildItem -Path C:\,D:\,E:\ -Recurse -Directory -Filter "ai-pacs beta version" -ErrorAction SilentlyContinue | Select-Object FullName`
  and `Get-ChildItem -Path C:\,D:\,E:\ -Recurse -Filter "_vc_load.py" -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime`
  (limit depth/time as needed). List every path found.

## 2. Working-tree state & recent git operations
- `git status` (full) and `git status --porcelain`.
- `git stash list`.
- `git reflog -30` — I specifically need to see any recent `checkout`, `reset`,
  `stash`, `merge`, or `commit` that could have reverted/overwritten uncommitted edits.
- For these files, report tracked/modified/untracked state AND `git diff --stat` for each:
  `PacsClient/utils/previous_exams.py`,
  `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_previous_exams.py`,
  `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py`,
  `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py`,
  `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py`,
  `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py`,
  `PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py`,
  `PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py`,
  `modules/network/socket_client.py`, `modules/network/socket_patient_service.py`,
  `PacsClient/utils/patient_study_set.py`,
  `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py`,
  `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py`.

## 3. Do the on-disk source files contain the new code?
Report PRESENT/ABSENT (with line numbers) for each marker, in the repo from §1:
- `_vc_load.py` contains `VIEWPORT-LOAD-TRACE` and `_multistudy_slot_order`
- `_vc_cache.py` contains `_cache_entry_study_matches` and `CACHE-STUDY-MISMATCH`
- `_pw_thumbnails.py` contains `_multistudy_slot_order`
- `_vc_layout.py` contains `_origin_is_previous` and `_viewport_container_styles(active: bool, previous`
- `previous_exams.py` exists and defines `build_previous_exam_set`
Use e.g. `Select-String -Path <file> -Pattern "VIEWPORT-LOAD-TRACE","_multistudy_slot_order"`.

## 4. The RUNNING app process (the key question)
- List python processes with full command line, start time, and working directory:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe' OR Name='aipacs.exe'" | Select-Object ProcessId,Name,CommandLine,CreationDate`
  and for the AI-PACS one, get its current directory if possible.
- From the command line, report: which **python.exe** (venv path) and which **main.py**
  (absolute path) it launched. **Is that main.py inside the §1 repo, or a different copy?**
- Is the running app a **source build** (python.exe running main.py) or a **frozen build**
  (aipacs.exe / PyInstaller)? Check for `aipacs.exe` and any `sys.frozen`/`_MEIPASS` usage.
- Confirm the process the user interacts with is the one whose pid most recently called
  `single_instance_lock.try_acquire` in `user_data/logs/app.log`.

## 5. Bytecode cache (stale `.pyc`?)
- For `PacsClient/pacs/patient_tab/ui/patient_ui/__pycache__/_vc_load.cpython-313.pyc`
  vs `_vc_load.py`: report both sizes + LastWriteTime, and whether the `.pyc` contains
  the string `VIEWPORT-LOAD-TRACE` (`Select-String -Path <pyc> -Pattern VIEWPORT-LOAD-TRACE`).
- Note: a prior check showed the `.pyc` was compiled from a source that was 636 bytes
  LARGER and ~11 min NEWER than the current `_vc_load.py` — explain how that could be
  (e.g., the file was reverted by a git op after the `.pyc` was built).

## 6. The v3.3.4 build provenance
- Where was the installer built (e.g. `builder/output/...`), what is the installer
  filename/version, and **which git commit** was it built from?
- Does the built/bundled payload include `PacsClient/utils/previous_exams.py` and the
  previous-exams code? (If it's a PyInstaller/Nuitka bundle, check the spec/`--paths`/
  hidden-imports and whether `previous_exams` is referenced.)
- Critically: **does the v3.3.4 build contain the Previous-Exams + viewport + stable-slot
  changes, or was it built before/without them?**

## 7. Concurrent-edit / two-agent check
- Are there signs another tool/agent is modifying files concurrently (file locks,
  recent writes to the same files from different times, the COMMIT marker file)?
- Is there an untracked marker file named `COMMIT` (or similar)? Report it.

## Deliverable
Give me a concise report with: (a) the ONE repo path the app actually runs from and
whether it equals where the edits live; (b) whether my fixes are on disk, committed, and
in the build; (c) the precise reason the running app does not execute them (different
copy / stale pyc / reverted by git / not restarted); (d) a safe, ordered reconciliation
plan to get all edits committed once, loaded by a fresh run (confirm `[VIEWPORT-LOAD-TRACE]`
appears in `user_data/logs/app.log`), and included in a rebuilt installer — without losing
either agent's work. Read-only until I approve the plan.
