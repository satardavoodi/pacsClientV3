@echo off
REM ============================================================================
REM run_app_mpr_canon.bat
REM Launch the AI-PACS SOURCE build with the Zeta MPR orientation fix ENABLED.
REM
REM The fix is OFF unless AIPACS_ZETA_MPR_CANONICALIZE is set, so this .bat is the
REM only thing that turns it on. Runs the .venv interpreter directly on main.py.
REM
REM IMPORTANT: fully CLOSE any already-running source build first, or the
REM single-instance guard will just raise the old window (new env/code won't load).
REM
REM Usage (CMD): double-click this file, or from a Command Prompt:
REM   cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
REM   run_app_mpr_canon.bat
REM ============================================================================

cd /d "%~dp0"

set "AIPACS_ZETA_MPR_CANONICALIZE=1"
set "ZETA_MPR_DIAG=1"

if not exist ".venv\Scripts\python.exe" (
    echo [run_app_mpr_canon] .venv not found. Create it first:
    echo     powershell -NoProfile -ExecutionPolicy Bypass -File setup_env.ps1
    pause
    exit /b 1
)

echo [run_app_mpr_canon] AIPACS_ZETA_MPR_CANONICALIZE=%AIPACS_ZETA_MPR_CANONICALIZE%  ZETA_MPR_DIAG=%ZETA_MPR_DIAG%
echo [run_app_mpr_canon] Launching source build (.venv\Scripts\python.exe main.py) ...

".venv\Scripts\python.exe" main.py
set "RC=%ERRORLEVEL%"

echo.
echo [run_app_mpr_canon] App exited with code %RC%.
pause
exit /b %RC%
