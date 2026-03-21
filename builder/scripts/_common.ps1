Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-BuilderRoot {
    return (Join-Path (Get-RepoRoot) "builder")
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Get-Timestamp {
    return (Get-Date).ToString("yyyyMMdd_HHmmss")
}

function Get-LogFile {
    param(
        [Parameter(Mandatory = $true)][string]$Prefix
    )
    $logsDir = Join-Path (Get-BuilderRoot) "logs"
    Ensure-Directory -Path $logsDir
    return (Join-Path $logsDir ("{0}_{1}.log" -f $Prefix, (Get-Timestamp)))
}

function Get-BuildVenvPython {
    $repo = Get-RepoRoot
    $venvPy = Join-Path $repo ".venv_build\Scripts\python.exe"
    if (Test-Path $venvPy) {
        return $venvPy
    }
    return $null
}

function Get-PreferredPython {
    $venvPy = Get-BuildVenvPython
    if ($venvPy) { return $venvPy }
    return "python"
}

function Ensure-BuildVenv {
    $repo = Get-RepoRoot
    $venvPy = Get-BuildVenvPython
    if (-not $venvPy) {
        Write-Host "[builder] Creating .venv_build"
        & python -m venv (Join-Path $repo ".venv_build")
        $venvPy = Get-BuildVenvPython
        if (-not $venvPy) {
            throw "Failed to create .venv_build"
        }
    }
    return $venvPy
}

function Invoke-Logged {
    param(
        [Parameter(Mandatory = $true)][string]$LogFile,
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock
    )

    Write-Host "[builder] $Description"
    "[$([DateTime]::UtcNow.ToString('o'))] $Description" | Tee-Object -FilePath $LogFile -Append | Out-Null

    & $ScriptBlock 2>&1 | Tee-Object -FilePath $LogFile -Append
    $exitCode = $LASTEXITCODE
    if ($null -eq $exitCode) { $exitCode = 0 }
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode. See log: $LogFile"
    }
}

function Install-BuildDependencies {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$LogFile
    )
    $repo = Get-RepoRoot
    $buildReq = Join-Path $repo "builder\requirements\build_requirements.txt"
    $coreReq = Join-Path $repo "requirements-core.txt"
    $legacyReq = Join-Path $repo "requirements.txt"

    Invoke-Logged -LogFile $LogFile -Description "Upgrade pip/setuptools/wheel" -ScriptBlock {
        & $PythonExe -m pip install --upgrade pip setuptools wheel
    }
    Invoke-Logged -LogFile $LogFile -Description "Install build requirements" -ScriptBlock {
        & $PythonExe -m pip install -r $buildReq
    }
    if (Test-Path $coreReq) {
        Invoke-Logged -LogFile $LogFile -Description "Install project runtime requirements" -ScriptBlock {
            & $PythonExe -m pip install -r $coreReq
        }
    } elseif (Test-Path $legacyReq) {
        Invoke-Logged -LogFile $LogFile -Description "Install legacy project requirements" -ScriptBlock {
            & $PythonExe -m pip install -r $legacyReq
        }
    }
}

function Get-AppExePath {
    param([Parameter(Mandatory = $true)][ValidateSet("appA", "appB")] [string]$AppKey)
    $builder = Get-BuilderRoot
    switch ($AppKey) {
        "appA" { return (Join-Path $builder "output\dist\appA\AIPacs\AIPacs.exe") }
        "appB" { return (Join-Path $builder "output\dist\appB\AIPacsAdvancedViewerLauncher\AIPacsAdvancedViewerLauncher.exe") }
    }
}

function Get-AppWorkPath {
    param([Parameter(Mandatory = $true)][ValidateSet("appA", "appB")] [string]$AppKey)
    return (Join-Path (Get-BuilderRoot) ("output\build\{0}" -f $AppKey))
}

function Get-AppDistPath {
    param([Parameter(Mandatory = $true)][ValidateSet("appA", "appB")] [string]$AppKey)
    return (Join-Path (Get-BuilderRoot) ("output\dist\{0}" -f $AppKey))
}

function Invoke-PyInstallerBuild {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][ValidateSet("appA", "appB")] [string]$AppKey,
        [Parameter(Mandatory = $true)][string]$SpecPath,
        [Parameter(Mandatory = $true)][string]$LogFile
    )

    $workPath = Get-AppWorkPath -AppKey $AppKey
    $distPath = Get-AppDistPath -AppKey $AppKey
    Ensure-Directory -Path $workPath
    Ensure-Directory -Path $distPath

    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"

    Invoke-Logged -LogFile $LogFile -Description "PyInstaller build ($AppKey)" -ScriptBlock {
        & $PythonExe -m PyInstaller `
            --noconfirm `
            --clean `
            --workpath $workPath `
            --distpath $distPath `
            $SpecPath
    }
}

function Sync-ThemeQss {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("appA", "appB")] [string]$AppKey
    )
    $repo = Get-RepoRoot
    $source = Join-Path $repo "generated-files\css\main.css"
    if (-not (Test-Path $source)) {
        Write-Host "[builder] Theme stylesheet not found: $source"
        return
    }

    $distPath = Get-AppDistPath -AppKey $AppKey
    $bundleRoot = switch ($AppKey) {
        "appA" { Join-Path $distPath "AIPacs" }
        "appB" { Join-Path $distPath "AIPacsAdvancedViewerLauncher" }
    }
    $dest = Join-Path $bundleRoot "Qss\main.qss"
    Ensure-Directory -Path (Split-Path $dest)
    Copy-Item -Path $source -Destination $dest -Force
    Write-Host "[builder] Synced theme stylesheet to $dest"
}
