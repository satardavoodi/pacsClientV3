@echo off
chcp 65001 >nul
title AIPacs Build Script

echo.
echo ===============================================================================
echo                     AIPacs Application Build Process
echo ===============================================================================
echo.
echo This script will build the staged Windows release for AIPacs
echo Please wait while the build process completes...
echo.

REM ---------------------------------------------------------------------------
REM Resolve the Python interpreter.
REM Prefer .venv_build (the isolated build environment) over ambient Python so
REM the build always runs with the correct pinned toolchain regardless of what
REM Python version or packages are installed system-wide on this machine.
REM
REM If .venv_build does not exist yet, run setup_build_env.ps1 first:
REM   powershell -ExecutionPolicy Bypass -File setup_build_env.ps1
REM ---------------------------------------------------------------------------
set "VENV_PYTHON=%~dp0.venv_build\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    echo [build] Using build venv: .venv_build\Scripts\python.exe
    set "BUILD_PYTHON=%VENV_PYTHON%"
) else (
    echo [build] .venv_build not found. Falling back to ambient Python.
    echo [build] For a reproducible build, run setup_build_env.ps1 first.
    echo.
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python is not installed or not in PATH.
        echo Run setup_build_env.ps1 to create the build environment.
        pause
        exit /b 1
    )
    set "BUILD_PYTHON=python"
)

echo.
echo [build] Starting build process...
echo.
"%BUILD_PYTHON%" build.py %*

if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Check the error messages above.
    echo.
    pause
    exit /b 1
)

echo.
echo ===============================================================================
echo                           Build Completed Successfully!
echo ===============================================================================
echo.
echo Core bundle: builder\output\stage\core\AIPacs.exe
echo Installer  : builder\output\installer\ai-pacs installer.exe
echo.
echo You can now:
echo   1. Run the core bundle from builder\output\stage\core\AIPacs.exe
echo   2. Review builder\output\stage\manifest\release_manifest.json
echo   3. Review builder\output\installer\SHA256.txt if ISCC.exe was available
echo   4. Use the installer from builder\output\installer if ISCC.exe was available
echo.
pause

