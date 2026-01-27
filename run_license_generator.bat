@echo off
chcp 65001 > nul
echo ==========================================
echo    ابزار تولید لایسنس AIPacs
echo ==========================================
echo.

cd /d "%~dp0"
python PacsClient\utils\license_generator_gui.py

if errorlevel 1 (
    echo.
    echo خطا در اجرای برنامه!
    echo لطفا مطمئن شوید که Python نصب شده است.
    pause
)
