@echo off
echo ==========================================
echo    Building AIPacs License Generator
echo ==========================================
echo.

REM Company management tool only; this is not a Client or Server release build.
set "AIPACS_COMPANY_PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
REM Check the existing project dependency; never install packages implicitly.
"%AIPACS_COMPANY_PYTHON%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller is unavailable in the project environment. Configure it before building.
    exit /b 1
)

echo Building executable...
echo.

"%AIPACS_COMPANY_PYTHON%" -m PyInstaller --name="AIPacs-License-Generator" ^
            --onefile ^
            --windowed ^
            --clean ^
            --paths "%~dp0..\.." ^
            --distpath "%~dp0dist" ^
            --workpath "%~dp0build" ^
            --specpath "%~dp0" ^
            "%~dp0license_generator.py"

if errorlevel 1 (
    echo.
    echo Build failed!
    pause
    exit /b 1
)

echo.
echo ==========================================
echo    Build completed successfully!
echo ==========================================
echo.
echo Executable location:
echo %~dp0dist\AIPacs-License-Generator.exe
echo.
pause
