param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

Set-Location -Path $PSScriptRoot

if (-not $PytestArgs -or $PytestArgs.Count -eq 0) {
    $PytestArgs = @("tests/test_pydicom_backend_geometry.py")
}

python main.py --run-tests @PytestArgs
exit $LASTEXITCODE
