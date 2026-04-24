@echo off
chcp 65001 >nul
title AIPacs Incremental Build

echo.
echo ===============================================================================
echo                     AIPacs Incremental Build
echo ===============================================================================
echo.
echo Only the changed Python files are recompiled and repackaged.
echo Stable DLLs, VTK/PySide6 binaries, and the Analysis cache are PRESERVED.
echo Use this after small code changes (modules/, PacsClient/, database/, etc.)
echo.
echo For a full clean rebuild (new packages, spec changes):
echo     build.bat --clean-build
echo.

REM ---------------------------------------------------------------------------
REM Resolve the Python interpreter (same logic as build.bat).
REM ---------------------------------------------------------------------------
set "VENV_PYTHON=%~dp0.venv_build\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    echo [build] Using build venv: .venv_build\Scripts\python.exe
    set "BUILD_PYTHON=%VENV_PYTHON%"
) else (
    echo [build] .venv_build not found. Falling back to ambient Python.
    python --version >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Python is not installed or not in PATH.
        echo Run setup_build_env.ps1 to create the build environment.
        pause
        exit /b 1
    )
    set "BUILD_PYTHON=python"
)

echo [build] Starting incremental build (Analysis cache preserved)...
echo.

REM Pass all extra CLI args through (e.g. --skip-installer-compile).
"%BUILD_PYTHON%" build.py %*

if errorlevel 1 (
    echo.
    echo ERROR: Incremental build failed.
    echo If the error mentions missing modules or stale cache, try:
    echo     build.bat --clean-build
    echo.
    pause
    exit /b 1
)

echo.
echo ===============================================================================
echo                       Incremental Build Complete
echo ===============================================================================
echo.
pause
