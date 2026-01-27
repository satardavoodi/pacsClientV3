@echo off
chcp 65001 >nul
title AIPacs Build Script

echo.
echo ===============================================================================
echo                     AIPacs Application Build Process
echo ===============================================================================
echo.
echo This script will create a standalone executable for AIPacs
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
echo Your application is ready at: dist\AIPacs\AIPacs.exe
echo.
echo You can now:
echo   1. Run the executable directly from dist\AIPacs\AIPacs.exe
echo   2. Copy the entire 'dist\AIPacs' folder to another location
echo   3. Create a shortcut to AIPacs.exe on your desktop
echo.
pause

