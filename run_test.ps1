<#
    run_test.ps1 - the ONE test entry point (Q0, 2026-07-14).

    Before Q0 the full suite could not run to completion (a build test hung it forever) and was
    RED BY DEFAULT (~80 permanent failures), so it carried no regression signal. This is the
    single blessed command; the FAST lane runs GREEN in ~90s and any red is a REAL regression.
    pytest's own summary line + exit code are the source of truth (this wrapper does not
    editorialize the result).

    Lanes (see pyproject.toml [tool.pytest.ini_options]):
      fast   - pure + offscreen-Qt, parallel (-n auto), reruns flaky, EXCLUDES
               build/slow/live/flaky_parallel. Default.
      serial - the flaky_parallel tests (Qt worker-thread / global state; parallel-unsafe), run
               one at a time. Advisory (does not gate the merge on its own).

    Usage:
      .\run_test.ps1                 # fast lane, then the advisory serial pass
      .\run_test.ps1 -Fast           # fast lane only (the merge gate)
      .\run_test.ps1 -Cov            # fast lane with coverage
      .\run_test.ps1 tests/code/viewer   # pass through to pytest (targeted)
      .\run_test.ps1 -Build          # heavy build/packaging lane
      .\run_test.ps1 -Live           # live/clinical lane (needs app/server)

    Exit code == the FAST lane's pytest exit code (0 = green). The serial pass is advisory.
#>
param(
    [switch]$Fast,
    [switch]$Cov,
    [switch]$Build,
    [switch]$Live,
    [switch]$Property,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

Set-Location -Path $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$common = @("-m", "pytest", "-p", "no:debugging")

# Reliable integer exit code. Inside `powershell -File`, `& $py ...; $LASTEXITCODE` can surface
# as a BOOLEAN rather than the process int (a PowerShell quirk), which would mask a real failure.
# Start-Process -PassThru gives the true .ExitCode; output stays inherited on the console.
function Invoke-Pytest {
    # NB: the parameter must NOT be named $Args ($args is a reserved automatic variable — using it
    # breaks binding). Filter any null/empty elements so Start-Process -ArgumentList never chokes.
    param([string[]]$PyArgs)
    $clean = @($PyArgs | Where-Object { $null -ne $_ -and $_ -ne "" })
    $p = Start-Process -FilePath $py -ArgumentList $clean -NoNewWindow -Wait -PassThru
    if ($null -eq $p -or $null -eq $p.ExitCode) { return 0 }
    return [int]$p.ExitCode
}

$propOpts = "addopts=--timeout=600 --timeout-method=thread"
if ($Build) { exit (Invoke-Pytest ($common + @("-m", "build") + $PytestArgs)) }
if ($Live)  { exit (Invoke-Pytest ($common + @("-m", "live")  + $PytestArgs)) }
if ($Property) { exit (Invoke-Pytest ($common + @("tests/code", "-q", "-m", "property", "-o", $propOpts) + $PytestArgs)) }
if ($PytestArgs -and $PytestArgs.Count -gt 0) {
    exit (Invoke-Pytest ($common + $PytestArgs))
}

$covArgs = @()
if ($Cov) {
    $covArgs = @("--cov=PacsClient", "--cov=modules", "--cov-report=term-missing:skip-covered",
                 "--cov-report=xml:coverage.xml")
}

$fast = Invoke-Pytest ($common + @("tests/code", "-q", "-n", "auto") + $covArgs)
if ($fast -ne 0) { exit $fast }        # a real regression - pytest already printed the details
if ($Fast) { exit 0 }

# Advisory serial pass for the parallel-unsafe set (does not gate the exit code).
$serialOpts = "addopts=--timeout=120 --timeout-method=thread"
Invoke-Pytest ($common + @("tests/code", "-q", "-p", "no:xdist", "-m", "flaky_parallel", "-o", $serialOpts)) | Out-Null

# Property / stateful (hypothesis) pass — kept out of the parallel fast lane (its CPU load makes
# the timing-sensitive viewer tests flake). Run it here, serially, so `.\run_test.ps1` still covers
# it; a failure IS a real bug, so gate on it.
$prop = Invoke-Pytest ($common + @("tests/code", "-q", "-m", "property", "-o", $propOpts))
if ($prop -ne 0) { exit $prop }

exit 0
