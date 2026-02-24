Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. "$PSScriptRoot\_common.ps1"

$repo = Get-RepoRoot
$py = Get-PreferredPython
$logFile = Get-LogFile -Prefix "diagnose_imports"

$diagnosePy = @'
import importlib
import json
import sys
from pathlib import Path
import warnings

warnings.filterwarnings("ignore", category=ResourceWarning)

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo))
inv_path = repo / "builder" / "inventory" / "entrypoints.json"
entrypoints = json.loads(inv_path.read_text(encoding="utf-8")) if inv_path.exists() else {}

def path_to_module(rel):
    if not rel:
        return None
    p = Path(rel)
    if p.name == "main.py":
        return "main"
    if p.suffix == ".py":
        return ".".join(p.with_suffix("").parts)
    return None

def try_import(name):
    if not name:
        print(f"[diag] skip: empty module name")
        return False
    try:
        mod = importlib.import_module(name)
        print(f"[diag] OK import {name} -> {getattr(mod, '__file__', '<built-in>')}")
        return True
    except Exception as exc:
        print(f"[diag] FAIL import {name}: {exc.__class__.__name__}: {exc}")
        return False

print(f"[diag] repo={repo}")
print(f"[diag] python={sys.executable}")
print(f"[diag] version={sys.version}")

modules = [
    "PySide6",
    "PySide6.QtCore",
    "vtk",
    "vtkmodules",
    "vtkmodules.vtkCommonCore",
    "SimpleITK",
]
for m in modules:
    try_import(m)

app_a_rel = ((entrypoints.get("appA") or {}).get("entrypoint"))
app_b_rel = ((entrypoints.get("appB") or {}).get("entrypoint"))
app_a_mod = path_to_module(app_a_rel)
app_b_mod = path_to_module(app_b_rel)

print(f"[diag] appA entrypoint rel={app_a_rel} module={app_a_mod}")
print(f"[diag] appB entrypoint rel={app_b_rel} module={app_b_mod}")

try_import(app_a_mod)
try_import(app_b_mod)
'@

Write-Host "[builder] Diagnose log: $logFile"
$tmpPy = Join-Path ([System.IO.Path]::GetTempPath()) ("aipacs_diagnose_imports_{0}.py" -f (Get-Timestamp))
Set-Content -Path $tmpPy -Value $diagnosePy -Encoding UTF8

try {
    Invoke-Logged -LogFile $logFile -Description "Diagnose imports" -ScriptBlock {
        $cmd = "`"$py`" -W ignore::ResourceWarning `"$tmpPy`" `"$repo`" 2>&1"
        cmd /c $cmd
    }
}
finally {
    if (Test-Path $tmpPy) { Remove-Item -Force $tmpPy }
}

Write-Host "[builder] Diagnose complete"
