@echo off
chcp 65001 > nul
echo ==========================================
echo    AIPacs License Generator Tool
echo ==========================================
echo.

cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" "%~dp0modules\LicenseGenerator\license_generator.py"

if errorlevel 1 (
    echo.
    echo Error running the program!
    echo Please verify the company signing store and the project Python environment.
    pause
)
