# ===========================================================================
# AI-PACS - S4b VTK-cache ACT validation launch  (build-once + REUSE)
#
# *** Run ONLY AFTER run_s4b_shadow.ps1 + .\check_s4b.ps1 showed ZERO
#     "GEOMETRY DIVERGES". ***
#
# Run from PowerShell, in the project root:
#     .\run_s4b_cache.ps1
# If blocked by execution policy:
#     powershell -ExecutionPolicy Bypass -File .\run_s4b_cache.ps1
#
# Enables the actual shared VTK volume cache: an MPR / Dental open builds the
# full VTK volume ONCE per series and REUSES it on the next open (the
# _load_full_vtk_for_mpr double-build removed). The shadow flag stays on so it
# keeps logging build/reuse evidence.
#
# VALIDATE: open MPR on a series, close it, reopen the SAME series -> it must
# build once and the REOPEN must show the correct image (NOT blank/stale); the
# FAST 2D viewer must stay fast; closing a tab mid-build must not crash.
#
# Revert: open a new terminal (or set the vars to "0") and use the Play button.
# ===========================================================================
Set-Location "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
$env:AIPACS_VTK_VOLUME_CACHE = "1"
$env:AIPACS_VTK_VOLUME_CACHE_SHADOW = "1"
& ".\.venv\Scripts\python.exe" main.py
