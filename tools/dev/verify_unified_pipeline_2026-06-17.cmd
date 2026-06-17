@echo off
REM ==========================================================================
REM verify_unified_pipeline_2026-06-17.cmd
REM
REM Full verification for the 2026-06-17 DM P0 + unified-pipeline work:
REM   - Download Manager critical-intent P0 hardening + repaired tests
REM   - Attachment local-first persistence guard
REM   - Unified-pipeline Phase-1 foundation + Phase-2 shadow detector
REM   - Plugin-mirror parity (389/389)
REM
REM The three pytest targets run as SEPARATE processes on purpose (a home-panel
REM suite collected before download_manager can trip a latent circular-import).
REM -p no:debugging is the project policy.
REM
REM Usage (run from anywhere; the script finds the repo root itself):
REM   tools\dev\verify_unified_pipeline_2026-06-17.cmd           - run tests + mirror verify
REM   tools\dev\verify_unified_pipeline_2026-06-17.cmd sync      - also sync mirrors first
REM   tools\dev\verify_unified_pipeline_2026-06-17.cmd app       - launch SOURCE build with shadow detector ON (46630 evidence)
REM   tools\dev\verify_unified_pipeline_2026-06-17.cmd taillog   - show shadow traces from the diagnostics log
REM ==========================================================================
setlocal EnableExtensions

REM Repo root = two levels up from this script (tools\dev\..\..)
pushd "%~dp0..\.." || (echo Cannot cd to project root & exit /b 1)
set "PROJ=%CD%"
echo Project: %PROJ%

set "PY=%PROJ%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo Python : %PY%
"%PY%" --version

if /I "%~1"=="taillog" (
    echo --- patient_study_set traces from user_data\logs\download_diagnostics.log ---
    findstr /C:"patient_study_set_open" /C:"patient_study_set_late_growth" "%PROJ%\user_data\logs\download_diagnostics.log"
    popd & exit /b 0
)

if /I "%~1"=="app" (
    set "AIPACS_PATIENT_STUDY_SET_SHADOW=1"
    echo AIPACS_PATIENT_STUDY_SET_SHADOW=1 set. Launching SOURCE build ^(python main.py^).
    echo This is the source build, NOT the frozen exe. Startup is slow.
    echo Open patient 46630, then close. Afterwards run:
    echo    tools\dev\verify_unified_pipeline_2026-06-17.cmd taillog
    "%PY%" main.py
    popd & exit /b %ERRORLEVEL%
)

set "FAIL=0"

echo.
echo ==== tests/code/download_manager ====
"%PY%" -m pytest tests/code/download_manager -q -p no:debugging
if not "%ERRORLEVEL%"=="0" set "FAIL=1"

echo.
echo ==== tests/code/network/test_attachment_local_first_persistence.py ====
"%PY%" -m pytest tests/code/network/test_attachment_local_first_persistence.py -q -p no:debugging
if not "%ERRORLEVEL%"=="0" set "FAIL=1"

echo.
echo ==== tests/code/ui_services (incl. test_patient_study_set) ====
"%PY%" -m pytest tests/code/ui_services -q -p no:debugging
if not "%ERRORLEVEL%"=="0" set "FAIL=1"

if /I "%~1"=="sync" (
    echo.
    echo ==== sync_plugin_mirrors ====
    "%PY%" tools\dev\sync_plugin_mirrors.py
)

echo.
echo ==== verify_plugin_mirrors ====
"%PY%" tools\dev\verify_plugin_mirrors.py
if not "%ERRORLEVEL%"=="0" set "FAIL=1"

if "%FAIL%"=="1" (
    echo.
    echo RESULT: FAILED
    popd & exit /b 1
)
echo.
echo RESULT: ALL GREEN
popd & exit /b 0
