@echo off
cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
echo === python/pythonw === > _proc_dump.txt
C:\Windows\System32\tasklist.exe /fi "imagename eq python.exe" >> _proc_dump.txt 2>&1
C:\Windows\System32\tasklist.exe /fi "imagename eq pythonw.exe" >> _proc_dump.txt 2>&1
echo === processes whose window/title mentions PACS/Viewer/INO === >> _proc_dump.txt
C:\Windows\System32\tasklist.exe /v /fo list | C:\Windows\System32\findstr.exe /i "PACS Viewer INO aipacs" >> _proc_dump.txt 2>&1
echo === DONE === >> _proc_dump.txt
