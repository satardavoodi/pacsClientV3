@echo off
REM This batch file runs the quick build process without showing cmd window
REM It uses PowerShell to hide the console window
powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -Command "& {Set-Location '%CD%'; cmd /c quick_build.bat}"