@echo off
echo ==========================================
echo   Running AIPacs License Generator
echo ==========================================
echo.

"%~dp0..\..\.venv\Scripts\python.exe" "%~dp0license_generator.py"

if errorlevel 1 (
    echo.
    echo Error running application!
    echo Verify the project Python environment and the company signing-store access.
    pause
)
