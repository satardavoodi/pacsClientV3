@echo off
REM ===========================================================================
REM AI-PACS - S4b VTK-cache ACT validation launch  (build-once + REUSE)
REM
REM *** Run this ONLY AFTER run_s4b_shadow.cmd + .\check_s4b.ps1 showed ZERO
REM     "GEOMETRY DIVERGES". ***
REM
REM Enables the actual shared VTK volume cache: an MPR / Dental / (future)
REM Advanced open builds the full VTK volume ONCE per series and REUSES it on the
REM next open - the _load_full_vtk_for_mpr double-build is removed. The shadow
REM flag is kept on so build/reuse evidence keeps logging.
REM
REM   AIPACS_VTK_VOLUME_CACHE=1          -> the cache ACTS (build-once + reuse)
REM   AIPACS_VTK_VOLUME_CACHE_SHADOW=1   -> keep measuring (logs real builds)
REM
REM HOW TO VALIDATE
REM   1. Open MPR on a series, close it, open MPR on the SAME series again.
REM      -> it must build ONCE (check_s4b.ps1 shows few/no repeat rebuilds) AND
REM         the REOPEN must show the correct image (NOT a blank / stale volume).
REM   2. Confirm the FAST 2D viewer still scrolls fast (unchanged).
REM   3. Close a patient / tab while an MPR build is loading -> no crash.
REM
REM Kill switch: use the Play button (or run_s4b_shadow.cmd) to revert. Setting
REM AIPACS_VTK_VOLUME_CACHE=0 also restores byte-identical legacy.
REM ===========================================================================
cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
set AIPACS_VTK_VOLUME_CACHE=1
set AIPACS_VTK_VOLUME_CACHE_SHADOW=1
".venv\Scripts\python.exe" main.py
