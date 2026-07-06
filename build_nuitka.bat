@echo off
chcp 65001 >nul
title AIPacs Nuitka Build Script

echo.
echo ===============================================================================
echo               AIPacs Incremental Build Process (Nuitka)
echo ===============================================================================
echo.
echo This script runs the staged, resumable Nuitka pipeline.
echo It preserves checkpoints and avoids restarting from zero after failures.
echo.

REM Prefer build venv used by release scripts.
set "PYTHON_EXE=.venv_build\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo .venv_build not found. Running setup_build_env.ps1 ...
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\setup_build_env.ps1"
    if errorlevel 1 (
        echo Failed to prepare .venv_build.
        pause
        exit /b 1
    )
)
echo.
echo Using build venv Python: %PYTHON_EXE%

REM Ensure the staged release toolchain is installed before invoking the pipeline.
"%PYTHON_EXE%" -c "import nuitka, ordered_set, zstandard" >nul 2>&1
if errorlevel 1 (
    echo Installing Nuitka toolchain requirements...
    "%PYTHON_EXE%" -m pip install -r requirements-nuitka.txt
    if errorlevel 1 (
        echo Failed to install requirements-nuitka.txt.
        pause
        exit /b 1
    )
)

REM Route to staged orchestrator.
echo Starting staged Nuitka pipeline...
echo.
if "%~1"=="" (
    "%PYTHON_EXE%" "builder nuitka\build_nuitka_release.py" --resume
) else (
    "%PYTHON_EXE%" "builder nuitka\build_nuitka_release.py" %*
)

if errorlevel 1 (
    echo.
    echo Build failed! Please check the error messages above.
    echo.
    pause
    exit /b 1
)

echo.
echo ===============================================================================
echo                   Nuitka Pipeline Completed Successfully!
echo ===============================================================================
echo.
echo Check staged outputs at: builder nuitka\output\
if exist "builder nuitka\output\installer\ai-pacs-nuitka-installer.exe" (
    echo Installer: builder nuitka\output\installer\ai-pacs-nuitka-installer.exe
    for /f "delims=" %%F in ('dir /b /o-d "builder nuitka\output\installer\ai-pacs-nuitka-installer v*.exe" 2^>nul') do (
        echo Versioned installer: builder nuitka\output\installer\%%F
        goto :printed_versioned_installer
    )
)
:printed_versioned_installer
echo For a full smoke check run:
echo   .venv_build\Scripts\python.exe "builder nuitka\build_nuitka_release.py" --smoke-test
echo.
pause
