@echo off
REM ==========================================================================
REM  AIPacs - reproducible Nuitka build (simple / monolithic standalone)
REM ==========================================================================
REM  Builds the AIPacs executable with Nuitka into
REM      builder nuitka\output\dist\AIPacs_nuitka\main.dist\
REM  using a dedicated, isolated build virtual-environment so the result is
REM  reproducible and independent of your dev .venv.
REM
REM  Usage (run from anywhere; paths are resolved automatically):
REM      "builder nuitka\build_nuitka_simple.cmd"              REM incremental
REM      "builder nuitka\build_nuitka_simple.cmd" --clean      REM clean rebuild
REM      "builder nuitka\build_nuitka_simple.cmd" --onefile    REM single .exe
REM      "builder nuitka\build_nuitka_simple.cmd" --dry-run    REM show cmd only
REM
REM  Does NOT touch the PyInstaller build (builder\) or your dev .venv.
REM ==========================================================================
setlocal EnableExtensions EnableDelayedExpansion

REM --- Resolve project root (this script lives in "<root>\builder nuitka") ---
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%.." || (echo [ERROR] Cannot cd to project root & exit /b 1)
set "PROJECT_ROOT=%CD%"

echo ==========================================================================
echo   AIPacs Nuitka build
echo   Project root : %PROJECT_ROOT%
echo ==========================================================================

REM --- Pick a base Python (prefer the py launcher, then python on PATH) ---
set "BASE_PY="
where py >nul 2>&1 && set "BASE_PY=py -3"
if not defined BASE_PY (
    where python >nul 2>&1 && set "BASE_PY=python"
)
if not defined BASE_PY (
    echo [ERROR] No Python found on PATH. Install Python 3.13 x64 and retry.
    popd & exit /b 1
)

REM --- Dedicated isolated build venv ---
set "BUILD_VENV=%PROJECT_ROOT%\.venv_nuitka"
set "VENV_PY=%BUILD_VENV%\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [SETUP] Creating isolated build venv at %BUILD_VENV%
    %BASE_PY% -m venv "%BUILD_VENV%" || (echo [ERROR] venv creation failed & popd & exit /b 1)
    "%VENV_PY%" -m pip install --upgrade pip wheel setuptools || (echo [ERROR] pip bootstrap failed & popd & exit /b 1)
)

echo [SETUP] Installing / verifying build dependencies (requirements-nuitka.txt)
"%VENV_PY%" -m pip install -r "%PROJECT_ROOT%\requirements-nuitka.txt" || (echo [ERROR] dependency install failed & popd & exit /b 1)

echo [BUILD] Launching Nuitka driver...
"%VENV_PY%" "%PROJECT_ROOT%\build_nuitka.py" %*
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
    echo.
    echo [OK] Nuitka build finished. Output:
    echo      %PROJECT_ROOT%\builder nuitka\output\dist\AIPacs_nuitka\main.dist\
) else (
    echo.
    echo [FAIL] Nuitka build failed with exit code %RC%.
    echo        See builder nuitka\output\logs\ for the timestamped build log.
)

popd
exit /b %RC%
