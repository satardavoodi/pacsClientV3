@echo off
setlocal
cd /d "%~dp0"

REM Build EchoMind with Nuitka (GUI app)
python build_nuitka.py %*

endlocal
