@echo off
REM ===========================================================================
REM AI-PACS - S4b VTK-cache SHADOW validation launch  (MEASURE only, zero risk)
REM
REM Launches the SOURCE build with the S4b SHADOW flag. In shadow mode the VTK
REM volume cache OBSERVES every MPR + Advanced volume build and logs
REM   [VTK-VOLUME-SHADOW]
REM when the shared cache WOULD have avoided a rebuild, or when the MPR and the
REM Advanced builders produce DIVERGENT geometry for the SAME series. It does NOT
REM cache and changes NO behaviour - byte-identical to a normal run.
REM
REM   AIPACS_VTK_VOLUME_CACHE_SHADOW=1   -> observe + log, NO caching
REM
REM HOW TO VALIDATE
REM   1. Run this file instead of the VS Code Play button.
REM   2. Open a CT or MR series in MPR (toolbar MPR button).
REM   3. Open / switch the SAME series in the Advanced (VTK) viewer.
REM   4. Repeat on a multi-study patient if you have one; reopen MPR a 2nd time.
REM   5. In a SECOND PowerShell terminal run:   .\check_s4b.ps1
REM      -> "Cross-builder geometry" must be PASS (0 GEOMETRY DIVERGES) before
REM         the cache (act) mode is enabled.
REM
REM Revert: just use the Play button (no flag = byte-identical legacy).
REM ===========================================================================
cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
set AIPACS_VTK_VOLUME_CACHE_SHADOW=1
".venv\Scripts\python.exe" main.py
