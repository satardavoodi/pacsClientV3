@echo off
chcp 65001 >nul
title AIPacs Nuitka Build Script

echo.
echo ===============================================================================
echo               AIPacs Application Build Process (Nuitka)
echo ===============================================================================
echo.
echo This script will build a standalone executable using Nuitka compiler.
echo Nuitka compiles Python to C for better performance and protection.
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.8 or later and try again
    pause
    exit /b 1
)

echo Python is installed
echo.

REM Run the Nuitka build script
echo Starting Nuitka build process...
echo.
python build_nuitka.py --clean

if errorlevel 1 (
    echo.
    echo Build failed! Please check the error messages above.
    echo.
    pause
    exit /b 1
)

echo.
echo ===============================================================================
echo                     Nuitka Build Completed Successfully!
echo ===============================================================================
echo.
echo Your application is ready at: dist\AIPacs_nuitka\main.dist\AIPacs.exe
echo.
echo Nuitka advantages over PyInstaller:
echo   - Compiled to native C code (faster startup and execution)
echo   - Better source code protection (no .pyc files in dist)
echo   - Smaller binary size in many cases
echo.
pause
