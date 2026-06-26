# ===========================================================================
# AI-PACS - S4b VTK-cache SHADOW validation launch  (MEASURE only, zero risk)
#
# Run from PowerShell, in the project root:
#     .\run_s4b_shadow.ps1
# If blocked by execution policy, run it this once instead:
#     powershell -ExecutionPolicy Bypass -File .\run_s4b_shadow.ps1
#
# Launches the SOURCE build with the S4b SHADOW flag. The VTK volume cache
# OBSERVES every MPR + Advanced build and logs [VTK-VOLUME-SHADOW] when the
# shared cache WOULD avoid a rebuild, or when MPR vs Advanced geometry DIVERGES.
# It does NOT cache and changes NO behaviour (byte-identical to a normal run).
#
# THEN, in a SECOND PowerShell window:   .\check_s4b.ps1
#   -> "Cross-builder geometry GATE" must be PASS (0 divergences) before the
#      cache (act) mode (run_s4b_cache.ps1) is enabled.
# ===========================================================================
Set-Location "E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
$env:AIPACS_VTK_VOLUME_CACHE_SHADOW = "1"
& ".\.venv\Scripts\python.exe" main.py
