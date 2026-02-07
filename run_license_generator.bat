@echo off
chcp 65001 > nul
echo ==========================================
echo    AIPacs License Generator Tool
echo ==========================================
echo.

cd /d "%~dp0"
python PacsClient\utils\license_generator_gui.py

if errorlevel 1 (
    echo.
    echo Error running the program!
    echo Please make sure Python is installed.
    pause
)
