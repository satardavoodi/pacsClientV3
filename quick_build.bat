@echo off
chcp 65001 >nul
title AIPacs Quick Build

echo.
echo ===============================================================================
echo                     AIPacs Quick Build (with verbose output)
echo ===============================================================================
echo.

REM Clean previous build
echo Cleaning previous build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo.

echo Starting PyInstaller build...
echo This will show all output in real-time. Please be patient...
echo.
echo ===============================================================================
echo.

REM Run PyInstaller with verbose output
pyinstaller --clean --noconfirm --log-level=ERROR AIPacs.spec

echo.
echo ===============================================================================

if errorlevel 1 (
    echo.
    echo ❌ Build FAILED! Check the errors above.
    echo.
    pause
    exit /b 1
) else (
    echo.
    echo ✅ Build completed successfully!
    echo.
    echo Output: dist\AIPacs\AIPacs.exe
    echo.
    pause
)

