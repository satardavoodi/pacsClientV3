@echo off
setlocal

echo ================================================================================
echo   AIPacs - Nuitka Release Build
echo ================================================================================
echo.

set "PYTHON=.venv_build\Scripts\python.exe"

:: Ensure build venv exists; bootstrap if missing
if not exist "%PYTHON%" (
    echo .venv_build not found. Bootstrapping with setup_build_env.ps1 ...
    powershell -NoProfile -ExecutionPolicy Bypass -File ".\setup_build_env.ps1"
    if errorlevel 1 (
        echo.
        echo [FAILED] Could not create .venv_build environment.
        pause
        exit /b 1
    )
)

if not exist "%PYTHON%" (
    echo.
    echo [FAILED] .venv_build\Scripts\python.exe is still missing after bootstrap.
    pause
    exit /b 1
)

echo Using .venv_build Python: %PYTHON%
echo.

:: Ensure Nuitka toolchain is present in build venv
"%PYTHON%" -c "import nuitka, ordered_set, zstandard" >nul 2>&1
if errorlevel 1 (
    echo Installing Nuitka toolchain requirements...
    "%PYTHON%" -m pip install -r requirements-nuitka.txt
    if errorlevel 1 (
        echo.
        echo [FAILED] Unable to install requirements-nuitka.txt
        pause
        exit /b 1
    )
)
echo.

:: Full orchestrated release (compile + stage + installer)
%PYTHON% "builder nuitka\build_nuitka_release.py" %*

if errorlevel 1 (
    echo.
    echo [FAILED] Nuitka release build failed - see output above.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Nuitka release build complete.
echo Output: builder nuitka\output\dist\AIPacs_nuitka\main.dist\AIPacs.exe
pause
