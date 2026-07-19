@echo off
rem Build the AI-PACS Lite Viewer portable bundle with the project venv.
setlocal
cd /d "%~dp0..\.."
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv not found at %CD%\.venv
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "tools\build\build_lite_viewer.py"
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (echo Lite Viewer build finished OK.) else (echo Lite Viewer build FAILED with code %RC%.)
pause
exit /b %RC%
