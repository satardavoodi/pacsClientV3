@echo off
echo ==========================================
echo   Running AIPacs License Generator
echo ==========================================
echo.

python license_generator.py

if errorlevel 1 (
    echo.
    echo Error running application!
    echo Please make sure Python and dependencies are installed.
    echo Run: pip install -r requirements.txt
    pause
)
