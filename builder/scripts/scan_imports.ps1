Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_common.ps1"

$repo = Get-RepoRoot
$py = Get-PreferredPython
$logFile = Get-LogFile -Prefix "scan_imports"

Write-Host "[builder] Scan log: $logFile"

Invoke-Logged -LogFile $logFile -Description "Run build audit (Phase 1)" -ScriptBlock {
    & $py (Join-Path $repo "builder\audit\scripts\run_audit.py") --verbose
}

Invoke-Logged -LogFile $logFile -Description "Generate build docs (Phase 2)" -ScriptBlock {
    & $py (Join-Path $repo "builder\audit\scripts\generate_build_docs.py")
}

Write-Host "[builder] Audit summary: builder/audit/reports/AUDIT_SUMMARY.md"
Write-Host "[builder] Build document: builder/docs/BUILD_DOCUMENT.md"

