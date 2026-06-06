@echo off
REM Launch the AI-PACS SOURCE build (.venv) with the UI geometry tracer ON.
REM Used to verify the title-bar freeze fix (patient tab open/close jump).
REM Trace lines: user_data\logs\viewer_diagnostics.log  [UI_GEOM_TRACE]
cd /d "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
set AIPACS_UI_GEOMETRY_TRACE=1
".venv\Scripts\python.exe" main.py
pause
