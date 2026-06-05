@echo off
REM ============================================================================
REM run_app_canon_fresh.bat
REM Foolproof source-build launch for validating the Zeta MPR canonicalization fix.
REM  1) Kills any running app/python instance (so the single-instance guard can't
REM     hand off to a stale process).
REM  2) Launches the SOURCE build with the EXPLICIT .venv interpreter (the one
REM     proven to load the edited modules) + the fix enabled.
REM Do NOT use the desktop icon / installed app / system python for this test.
REM ============================================================================
echo [canon_fresh] Killing any running AI-PACS / Python instances...
taskkill /F /IM python.exe /T  >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1
taskkill /F /IM aipacs.exe /T  >nul 2>&1

REM Wait for processes to FULLY terminate and the single-instance lock (QLocalServer)
REM to release, so the new launch becomes primary instead of handing off to a survivor.
echo [canon_fresh] Waiting 4s for old instances to exit + lock to release...
timeout /t 4 /nobreak >nul
taskkill /F /IM python.exe /T  >nul 2>&1
taskkill /F /IM pythonw.exe /T >nul 2>&1

cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"

REM Clear STALE compiled bytecode so edited .py sources are recompiled.
REM (The editor preserves file mtime, so Python's timestamp check otherwise keeps
REM  loading old .pyc and ignores source edits. This rd works on Windows.)
echo [canon_fresh] Clearing stale __pycache__ under modules\mpr ...
for /d /r "modules\mpr" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
REM Belt-and-suspenders: also redirect bytecode cache to a fresh dir for this run.
set "PYTHONPYCACHEPREFIX=%TEMP%\aipacs_pyc_fresh_run"
rd /s /q "%TEMP%\aipacs_pyc_fresh_run" 2>nul

set "AIPACS_ZETA_MPR_CANONICALIZE=1"
REM ZETA_MPR_DIAG must stay OFF in validation/production: =1 draws the YELLOW diagnostic
REM overlay on top of the real (camera-derived) markers, which looks like duplicate markers.
set "ZETA_MPR_DIAG=0"

if not exist ".venv\Scripts\python.exe" (
    echo [canon_fresh] ERROR: .venv\Scripts\python.exe not found.
    pause
    exit /b 1
)

echo [canon_fresh] Launching SOURCE build: .venv\Scripts\python.exe main.py
".venv\Scripts\python.exe" main.py
echo [canon_fresh] App exited with code %ERRORLEVEL%.
pause
