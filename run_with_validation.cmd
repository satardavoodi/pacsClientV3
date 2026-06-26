@echo off
REM ============================================================================
REM AI-PACS — launch the SOURCE build with the unified-pipeline VALIDATION flags.
REM Use this INSTEAD of the VS Code Play button when you want to validate the
REM viewer-unification work (S1 identity shadow + S2 state authority). It sets the
REM env vars the Play button can't, then runs the same main.py source build.
REM
REM   AIPACS_VIEWER_SPINE_SHADOW=1   -> logs [VIEWER-IDENTITY-SHADOW] (A1 evidence)
REM                                     + [STATE-AUTHORITY-SHADOW] (divergence)
REM   AIPACS_VIEWER_STATE_AUTHORITY=1-> authority is an ADDITIONAL settled-stop
REM                                     signal (authority=True in the stop log)
REM   AIPACS_TEST_SERVER=1           -> in-app control server (for agent driving)
REM
REM All three are SAFE: shadows are read-only; the authority only ADDS a stop
REM condition for already-complete series. Remove this file or use the Play button
REM for a normal (flags-off) run.
REM ============================================================================
cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
REM --- unified-viewer validation flags (all SAFE: shadows are read-only; the authority and
REM     stable-identity only ADD checks; grow-sibling is already default-on) ---
set AIPACS_VIEWER_SPINE_SHADOW=1
set AIPACS_VIEWER_STATE_AUTHORITY=1
set AIPACS_VIEWER_STABLE_IDENTITY=1
set AIPACS_VIEWER_UNIFIED_TEARDOWN=1
set AIPACS_TEST_SERVER=1
".venv\Scripts\python.exe" main.py
