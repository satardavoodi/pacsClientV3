@echo off
cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
C:\Windows\System32\taskkill.exe /F /IM python.exe /T
C:\Windows\System32\taskkill.exe /F /IM pythonw.exe /T
C:\Windows\System32\taskkill.exe /F /IM aipacs.exe /T
C:\Windows\System32\PING.EXE -n 6 127.0.0.1 >nul
echo === after kill: python.exe === > _force_kill_status.txt
C:\Windows\System32\tasklist.exe /fi "imagename eq python.exe" >> _force_kill_status.txt 2>&1
echo === DONE === >> _force_kill_status.txt
