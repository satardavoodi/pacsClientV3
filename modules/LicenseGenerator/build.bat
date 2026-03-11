@echo off
echo ==========================================
echo    Building AIPacs License Generator
echo ==========================================
echo.

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
    echo.
)

echo Building executable...
echo.

pyinstaller --name="AIPacs-License-Generator" ^
            --onefile ^
            --windowed ^
            --clean ^
            license_generator.py

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
echo %CD%\dist\AIPacs-License-Generator.exe
echo.
pause
