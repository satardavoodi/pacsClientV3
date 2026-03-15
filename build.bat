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

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Error: Python is not installed or not in PATH
    echo Please install Python 3.8 or later and try again
    pause
    exit /b 1
)

echo ✅ Python is installed
echo.

REM Run the build script
echo Starting build process...
echo.
python build.py

if errorlevel 1 (
    echo.
    echo ❌ Build failed! Please check the error messages above.
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
echo Installer  : builder\output\installer\AIPacs_*.exe
echo.
echo You can now:
echo   1. Run the core bundle from builder\output\stage\core\AIPacs.exe
echo   2. Review builder\output\stage\manifest\release_manifest.json
echo   3. Use the installer from builder\output\installer if ISCC.exe was available
echo.
pause

