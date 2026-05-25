@echo off
REM ===========================================================================
REM  Run-AIPacs-Diagnostic.bat
REM  --------------------------------------------------------------------------
REM  Launches the installed AI-PACS build with crash diagnostics turned on.
REM  Use this INSTEAD of the normal AI-PACS desktop shortcut while we are
REM  hunting the auto-close crash.
REM
REM  AIPACS_LOG_SYNC=1
REM     Logs are written to disk immediately instead of through a background
REM     queue. Without this, the last ~1 second of log lines before a crash
REM     is lost -- which is exactly why the current logs "go quiet" instead
REM     of showing the crash. With it, the logs capture the real final events.
REM     Side effect: the viewer may feel slightly less smooth during fast
REM     scrolling. This is harmless and only for the diagnostic period.
REM
REM  PYTHONFAULTHANDLER=1 / AIPACS_MAIN_THREAD_PROBE=1
REM     Extra fault and main-thread instrumentation. Harmless.
REM ===========================================================================

set "AIPACS_LOG_SYNC=1"
set "PYTHONFAULTHANDLER=1"
set "AIPACS_MAIN_THREAD_PROBE=1"

echo.
echo   Starting AI-PACS in DIAGNOSTIC mode...
echo   (use this launcher until the crash has been captured)
echo.

start "" "D:\AIPacs\AIPacs.exe"
