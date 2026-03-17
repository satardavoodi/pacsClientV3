@echo off
setlocal
cd /d "%~dp0"

REM Build EchoMind with PyInstaller (GUI app)
pyinstaller --noconfirm --clean --windowed --name EchoMind echomind_main.py ^
  --collect-all PacsClient ^
  --collect-all PySide6 ^
  --collect-all qasync ^
  --collect-all vtkmodules

endlocal
