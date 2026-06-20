# Follow-up prompt for VS Code Copilot — prove the runtime cause, then reconcile

Context confirmed by your last pass: ONE repo (`E:\ai-pacs\ai-pacs codes\ai-pacs beta
version`); the Previous-Exams + viewer fixes are on disk but UNCOMMITTED and NOT in the
v3.3.4 build (commit 392db5c8). The remaining question is why the running SOURCE app
doesn't execute the on-disk edits. Hypothesis: stale `__pycache__` bytecode. Do Phase 1
now. Do Phase 2 only after I explicitly approve.

## Phase 1 — Prove (and clear) the stale-bytecode cause  [safe: only deletes regenerable .pyc]

1. Identify the venv the app uses (from the running process command line) and, from the
   repo root, print the EXACT source file Python resolves for `_vc_load` and whether it
   has the trace:
   ```
   & "<venv>\Scripts\python.exe" -c "import importlib.util as u; s=u.find_spec('PacsClient.pacs.patient_tab.ui.patient_ui._vc_load'); print('ORIGIN:', s.origin); print('HAS_TRACE:', 'VIEWPORT-LOAD-TRACE' in open(s.origin, encoding='utf-8').read())"
   ```
   Report ORIGIN (must be inside this repo) and HAS_TRACE (expect True).
2. Fully STOP the running AI-PACS app (close it / Ctrl+C its terminal). Confirm no
   python.exe is still running it.
3. Delete all bytecode caches in the repo (regenerated on next run):
   ```
   Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
   ```
4. Relaunch the app the normal way (Run `main.py` from VS Code). Then check the log:
   ```
   Select-String -Path "user_data\logs\app.log" -Pattern "VIEWPORT-LOAD-TRACE","single_instance_lock.try_acquire" | Select-Object -Last 6
   ```
   Report: did a NEW pid `try_acquire`, and does `[VIEWPORT-LOAD-TRACE]` now appear when a
   series is dragged into a viewport?
   - If YES → confirmed stale bytecode; the fixes are now live. Proceed to verify the bug.
   - If NO → report the import ORIGIN, `python -c "import sys; print(sys.path)"`, and any
     `sys.dont_write_bytecode`/`-B`/`PYTHONDONTWRITEBYTECODE` in the launch config.

5. With the fixes live, verify the actual bug on patient 44030: drag a CURRENT (ankle)
   series → the viewport must show the ankle (not a previous brain series); confirm the
   viewport border is blue for current and red for a previous-exam series. Report result.

## Phase 2 — Reconcile + rebuild  [ONLY after I approve; this commits + builds]

6. On branch `beta-version`, stage and commit ALL the Cowork changes as ONE commit,
   INCLUDING the untracked new file `PacsClient/utils/previous_exams.py`:
   ```
   git add PacsClient/utils/previous_exams.py PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_previous_exams.py PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py PacsClient/pacs/patient_tab/ui/patient_ui/_vc_layout.py PacsClient/pacs/patient_tab/ui/patient_ui/_vc_switch.py PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py PacsClient/pacs/patient_tab/ui/patient_ui/_vc_cache.py PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py modules/network/socket_client.py modules/network/socket_patient_service.py PacsClient/utils/patient_study_set.py PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py tests/code/ui_services/test_previous_exams*.py docs/pipelines/previous-exams.md
   git status   # confirm nothing else unexpected is staged
   git commit -m "feat(viewer): Previous Exams (National-ID prior studies) + stable multi-study slot keys, origin viewport/thumbnail borders, study-scoped pixel-cache guard"
   ```
   (Adjust the file list to whatever `git status` shows as the Cowork edits; do not sweep
   in unrelated changes.)
7. Run the test suites and report pass/fail:
   ```
   python -m pytest tests/code/ui_services/test_previous_exams.py tests/code/ui_services/test_previous_exams_wiring.py tests/code/viewer -q -p no:debugging
   ```
   Also run any multi-study / thumbnail suites.
8. Regression-check a SAME-PatientID multi-study patient (e.g. 42471 KNEE+ANKLE): both
   studies' series group and load correctly, no flicker — the stable-slot change must not
   break the original multi-study feature.
9. Rebuild the installer from the new commit; then CONFIRM the feature is included:
   ```
   # after build, search the staged payload and dist:
   Get-ChildItem -Recurse -Filter previous_exams.py builder\... | Select FullName
   ```
   The build must pass `builder/release_gate.py` (do NOT use `--skip-release-gate`) and
   `previous_exams.py` MUST be present in both stage and dist.
10. Report: new commit hash, pytest result, 42471 regression result, and confirmation
    that `previous_exams.py` is in the rebuilt installer. Only then is the build safe to
    install on other PCs.
