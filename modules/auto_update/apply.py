"""Staged-update application: helper generation, launch, boot reconcile.

The app process cannot replace its own locked files, so the actual file swap
runs in a small PowerShell helper AFTER the app exits.  Everything the helper
does is driven by a validated ``apply_plan.json`` written here.

HARD RULES (test-pinned — see design doc §5):
- The plan may only contain paths accepted by ``manifest.is_safe_manifest_path``
  (top-level file or ``engine/**``) → the helper can never touch ``User Data``,
  ``%APPDATA%`` config, or anything outside the install root.
- The helper WAITS for the app to exit (never kills it) and aborts untouched
  on timeout.
- Any copy failure → automatic restore of every backed-up file + relaunch of
  the previous version (ROLLBACK logged).
- No Qt at import time (usable from tests and non-GUI contexts).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aipacs_runtime
from aipacs_runtime import (
    compare_release_versions,
    current_app_version,
    save_runtime_profile,
    updates_cache_root,
)

from . import manifest as manifest_mod

logger = logging.getLogger(__name__)

APP_EXE_NAME = "AIPacs.exe"
APPLY_PLAN_FILENAME = "apply_plan.json"
APPLY_SCRIPT_FILENAME = "apply_update.ps1"
ROLLBACK_SCRIPT_FILENAME = "rollback_update.ps1"
APPLIED_MARKER_FILENAME = "applied.json"
HEALTH_MARKER_FILENAME = "update_health.json"
_HELPER_WAIT_TIMEOUT_MS = 90_000
_KEEP_BACKUPS = 2


def is_dir_writable(path: str | Path) -> bool:
    try:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=str(target), prefix="~aipacs_w", delete=True):
            pass
        return True
    except Exception:
        return False


def bundled_version_file() -> Path:
    """``engine/version.json`` in a frozen install; absent in dev runs."""
    return aipacs_runtime.bundled_config_root().parent / "version.json"


def backup_root_for(from_version: str) -> Path:
    safe = str(from_version or "unknown").replace("/", "_").replace("\\", "_")
    return updates_cache_root() / "backup" / safe


def helper_logs_root() -> Path:
    return updates_cache_root() / "logs"


# ── plan preparation ───────────────────────────────────────────────────────

def prepare_apply(
    staging_root: str | Path,
    version: str,
    *,
    from_version: str | None = None,
    install_root: str | Path | None = None,
    exe_name: str = APP_EXE_NAME,
    wait_pid: int | None = None,
) -> dict[str, Any]:
    """Validate the staged tree and write plan + helper scripts.

    Returns ``{"plan_file", "script_file", "rollback_file", "plan"}``.
    Raises on ANY unsafe/missing path — an invalid plan must never launch.
    """
    staging = Path(staging_root)
    snapshot_path = staging / "staged_plan.json"
    if not snapshot_path.is_file():
        raise FileNotFoundError(f"staged plan missing: {snapshot_path}")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    files = [str(item) for item in (snapshot.get("files") or [])]
    if not files:
        raise ValueError("staged plan contains no files")

    unsafe = manifest_mod.iter_unsafe_paths(files)
    if unsafe:
        raise ValueError(f"unsafe paths in staged plan: {unsafe[:5]}")
    for rel in files:
        if not (staging / rel).is_file():
            raise FileNotFoundError(f"staged file missing: {rel}")

    root = Path(install_root) if install_root is not None else aipacs_runtime.install_root()
    effective_from = str(from_version or snapshot.get("from_version") or current_app_version() or "unknown")
    backup_root = backup_root_for(effective_from)
    logs_root = helper_logs_root()
    logs_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_file = logs_root / f"apply-{version}-{timestamp}.log"

    plan: dict[str, Any] = {
        "version": str(version),
        "from_version": effective_from,
        "install_root": str(root),
        "staging_root": str(staging),
        "backup_root": str(backup_root),
        "exe_path": str(root / exe_name),
        "profile_path": str(aipacs_runtime.installation_profile_path()),
        "log_file": str(log_file),
        "wait_pid": int(wait_pid if wait_pid is not None else os.getpid()),
        "wait_timeout_ms": _HELPER_WAIT_TIMEOUT_MS,
        "files": files,
    }

    plan_file = staging / APPLY_PLAN_FILENAME
    plan_file.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    script_file = staging / APPLY_SCRIPT_FILENAME
    script_file.write_text(_APPLY_SCRIPT_TEMPLATE, encoding="utf-8-sig")
    rollback_file = staging / ROLLBACK_SCRIPT_FILENAME
    rollback_file.write_text(_ROLLBACK_SCRIPT_TEMPLATE, encoding="utf-8-sig")
    return {
        "plan_file": str(plan_file),
        "script_file": str(script_file),
        "rollback_file": str(rollback_file),
        "plan": plan,
    }


# ── helper launch ──────────────────────────────────────────────────────────

def _ps_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def launch_apply_helper(prepared: dict[str, Any], *, elevate: bool | None = None) -> None:
    """Start the helper (detached). The caller then quits the app normally."""
    if sys.platform != "win32":  # pragma: no cover - windows-only product
        raise RuntimeError("update apply is Windows-only")
    plan = prepared["plan"]
    script = str(prepared["script_file"])
    plan_file = str(prepared["plan_file"])
    if elevate is None:
        elevate = not is_dir_writable(Path(plan["install_root"]) / "engine")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0
    )
    if not elevate:
        subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-WindowStyle", "Hidden", "-File", script, "-PlanFile", plan_file,
            ],
            cwd=str(Path(script).parent),
            creationflags=creationflags,
            close_fds=True,
        )
        logger.info("auto-update: apply helper launched (non-elevated)")
        return

    inner = (
        f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
        f'-File "{script}" -PlanFile "{plan_file}"'
    )
    command = (
        "Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden "
        f"-ArgumentList {_ps_single_quote(inner)}"
    )
    subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=str(Path(script).parent),
        creationflags=creationflags,
        close_fds=True,
    )
    logger.info("auto-update: apply helper launched (elevated via UAC)")


# ── boot-time reconcile + maintenance ──────────────────────────────────────

def reconcile_version_on_boot() -> str | None:
    """After a delta apply the payload carries the new version in
    ``engine/version.json``; stamp it into the runtime profile (which
    ``current_app_version()`` reads first) when they disagree."""
    try:
        version_file = bundled_version_file()
        if not version_file.is_file():
            return None
        payload = json.loads(version_file.read_text(encoding="utf-8"))
        bundled = str(payload.get("version") or "").strip()
        if not bundled:
            return None
        current = current_app_version()
        if current == bundled:
            return None
        save_runtime_profile({"app_version": bundled})
        logger.info("auto-update: reconciled app_version %s -> %s", current, bundled)
        return bundled
    except Exception as exc:  # noqa: BLE001 — must never break startup
        logger.warning("auto-update: version reconcile failed: %s", exc)
        return None


def post_boot_maintenance(*, keep_backups: int = _KEEP_BACKUPS) -> None:
    """Write the boot-ok health marker; prune applied staging + old backups.

    Best-effort only — must never raise into startup.
    """
    try:
        cache = updates_cache_root()
        cache.mkdir(parents=True, exist_ok=True)
        current = current_app_version()
        (cache / HEALTH_MARKER_FILENAME).write_text(
            json.dumps(
                {
                    "boot_ok": True,
                    "version": current,
                    "at_utc": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )

        staging_root = cache / "staging"
        if staging_root.is_dir():
            for child in staging_root.iterdir():
                if not child.is_dir():
                    continue
                applied = child / APPLIED_MARKER_FILENAME
                stale = applied.is_file() or (
                    current and compare_release_versions(child.name, current) <= 0
                )
                if stale:
                    import shutil

                    shutil.rmtree(child, ignore_errors=True)

        backups_root = cache / "backup"
        if backups_root.is_dir():
            dirs = [d for d in backups_root.iterdir() if d.is_dir()]
            dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            for old in dirs[keep_backups:]:
                import shutil

                shutil.rmtree(old, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto-update: post-boot maintenance failed: %s", exc)


# ── PowerShell helper templates ────────────────────────────────────────────
# NOTE: static scripts — every machine-specific value comes from apply_plan.json,
# so nothing here needs string interpolation (no quoting pitfalls).

_APPLY_SCRIPT_TEMPLATE = r"""param([Parameter(Mandatory=$true)][string]$PlanFile)
$ErrorActionPreference = 'Stop'
$plan = Get-Content -LiteralPath $PlanFile -Raw | ConvertFrom-Json
$logDir = Split-Path -Parent $plan.log_file
if ($logDir) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
function Write-Log([string]$msg) {
  $line = ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
  Add-Content -LiteralPath $plan.log_file -Value $line
}
Write-Log ('AIPacs update apply start: {0} -> {1}' -f $plan.from_version, $plan.version)

# 1) Wait for the application to exit CLEANLY. Never kill it.
if ($plan.wait_pid -gt 0) {
  try {
    $proc = Get-Process -Id $plan.wait_pid -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Log ('waiting for pid {0} to exit...' -f $plan.wait_pid)
      if (-not $proc.WaitForExit([int]$plan.wait_timeout_ms)) {
        Write-Log 'ERROR: application did not exit in time - update ABORTED, nothing was changed'
        exit 2
      }
    }
  } catch { Write-Log ('wait warning: {0}' -f $_) }
}
Start-Sleep -Milliseconds 750

$applied = New-Object System.Collections.Generic.List[string]
function Copy-WithRetry([string]$src, [string]$dst) {
  $dir = Split-Path -Parent $dst
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  for ($i = 1; $i -le 6; $i++) {
    try { Copy-Item -LiteralPath $src -Destination $dst -Force; return }
    catch { if ($i -eq 6) { throw }; Start-Sleep -Milliseconds 800 }
  }
}

try {
  foreach ($rel in $plan.files) {
    # defense in depth: refuse anything that could escape the install root
    if ($rel -match '\.\.' -or $rel -match '^[A-Za-z]:' -or $rel.StartsWith('\') -or $rel.StartsWith('/')) {
      throw ('unsafe path in plan: ' + $rel)
    }
    $src = Join-Path $plan.staging_root $rel
    if (-not (Test-Path -LiteralPath $src)) { throw ('staged file missing: ' + $rel) }
    $dst = Join-Path $plan.install_root $rel
    if (Test-Path -LiteralPath $dst) {
      $bak = Join-Path $plan.backup_root $rel
      $bakDir = Split-Path -Parent $bak
      if ($bakDir) { New-Item -ItemType Directory -Force -Path $bakDir | Out-Null }
      Copy-Item -LiteralPath $dst -Destination $bak -Force
    }
    Copy-WithRetry $src $dst
    $applied.Add($rel) | Out-Null
  }
  Write-Log ('applied {0} files' -f $applied.Count)
} catch {
  Write-Log ('ERROR during apply: {0}' -f $_)
  Write-Log 'ROLLBACK: restoring backed-up files'
  foreach ($rel in $applied) {
    try {
      $bak = Join-Path $plan.backup_root $rel
      $dst = Join-Path $plan.install_root $rel
      if (Test-Path -LiteralPath $bak) { Copy-Item -LiteralPath $bak -Destination $dst -Force }
      else { Remove-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue }
    } catch { Write-Log ('rollback warning for {0}: {1}' -f $rel, $_) }
  }
  Write-Log 'ROLLBACK complete - relaunching previous version'
  Start-Process -FilePath $plan.exe_path -WorkingDirectory $plan.install_root
  exit 3
}

# 2) Best-effort: stamp the new version into the installation profile.
try {
  if ($plan.profile_path -and (Test-Path -LiteralPath $plan.profile_path)) {
    $prof = Get-Content -LiteralPath $plan.profile_path -Raw | ConvertFrom-Json
    $prof.app_version = $plan.version
    if ($prof.PSObject.Properties['installer'] -and $prof.installer) {
      $prof.installer.current_version = $plan.version
    }
    $prof | ConvertTo-Json -Depth 16 | Set-Content -LiteralPath $plan.profile_path -Encoding UTF8
    Write-Log 'installation profile version stamped'
  }
} catch { Write-Log ('profile stamp warning (non-fatal): {0}' -f $_) }

# 3) Success marker + relaunch.
try {
  $marker = @{ version = $plan.version; from_version = $plan.from_version;
               applied_at_utc = (Get-Date).ToUniversalTime().ToString('o');
               file_count = $applied.Count } | ConvertTo-Json
  Set-Content -LiteralPath (Join-Path $plan.staging_root 'applied.json') -Value $marker -Encoding UTF8
} catch { Write-Log ('marker warning: {0}' -f $_) }

Write-Log 'apply complete - relaunching application'
Start-Process -FilePath $plan.exe_path -WorkingDirectory $plan.install_root
exit 0
"""

_ROLLBACK_SCRIPT_TEMPLATE = r"""param([Parameter(Mandatory=$true)][string]$PlanFile)
# Manual rollback: restores every backed-up file of this update.
# Close AIPacs before running this script.
$ErrorActionPreference = 'Stop'
$plan = Get-Content -LiteralPath $PlanFile -Raw | ConvertFrom-Json
$running = Get-Process -Name 'AIPacs' -ErrorAction SilentlyContinue
if ($running) { Write-Host 'Please close AIPacs first.'; exit 2 }
$restored = 0
foreach ($rel in $plan.files) {
  if ($rel -match '\.\.' -or $rel -match '^[A-Za-z]:' -or $rel.StartsWith('\') -or $rel.StartsWith('/')) { continue }
  $bak = Join-Path $plan.backup_root $rel
  $dst = Join-Path $plan.install_root $rel
  if (Test-Path -LiteralPath $bak) {
    $dir = Split-Path -Parent $dst
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Copy-Item -LiteralPath $bak -Destination $dst -Force
    $restored++
  }
}
Write-Host ('Restored {0} files from backup ({1}).' -f $restored, $plan.backup_root)
exit 0
"""

__all__ = [
    "APP_EXE_NAME",
    "APPLY_PLAN_FILENAME",
    "APPLY_SCRIPT_FILENAME",
    "ROLLBACK_SCRIPT_FILENAME",
    "APPLIED_MARKER_FILENAME",
    "HEALTH_MARKER_FILENAME",
    "is_dir_writable",
    "bundled_version_file",
    "backup_root_for",
    "helper_logs_root",
    "prepare_apply",
    "launch_apply_helper",
    "reconcile_version_on_boot",
    "post_boot_maintenance",
]
