@echo off
cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
set "WINDIR=C:\Windows"
".venv\Scripts\python.exe" -m pytest tests/code/mpr/test_mpr_canonicalize.py -p no:debugging -q > _mpr_canon_test.txt 2>&1
echo EXIT=%errorlevel% >> _mpr_canon_test.txt
