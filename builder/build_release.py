from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aipacs_runtime import (
    APP_NAME,
    CORE_COMPONENT_ID,
    CORE_COMPONENT_TITLE,
    INSTALLATION_PROFILE_FILENAME,
    MODULE_CATALOG,
    MODULE_PACKAGE_FEED_FILENAME,
    MODULE_PACKAGE_FORMAT_VERSION,
    MODULE_PACKAGE_MANIFEST_FILENAME,
    MODULE_PACKAGE_PAYLOAD_DIRNAME,
    UPDATE_FEED_FILENAME,
    advanced_mpr_runtime_root,
    detect_software_graphics_support,
    default_installation_profile,
)
from builder.plugin_package_registry import load_plugin_package_definitions
BUILDER_DIR = PROJECT_ROOT / "builder"
OUTPUT_DIR = BUILDER_DIR / "output"
DIST_DIR = OUTPUT_DIR / "dist"
BUILD_DIR = OUTPUT_DIR / "build"
STAGE_DIR = OUTPUT_DIR / "stage"
MANIFEST_DIR = STAGE_DIR / "manifest"
INSTALLER_OUTPUT_DIR = OUTPUT_DIR / "installer"
PACKAGE_OUTPUT_DIR = OUTPUT_DIR / "packages"
UPDATES_OUTPUT_DIR = OUTPUT_DIR / "updates"
UPDATES_CORE_DIR = UPDATES_OUTPUT_DIR / "core"
UPDATES_MODULES_DIR = UPDATES_OUTPUT_DIR / "modules"
STAGED_PLUGIN_PACKAGE_DIR = STAGE_DIR / "plugin_packages"
SPEC_FILE = BUILDER_DIR / "spec" / "appA_workstation.spec"
INSTALLER_SCRIPT = BUILDER_DIR / "installer" / "AIPacs_Setup.iss"
REQUIRED_RELEASE_GRAPHICS_BINARIES = ("opengl32sw.dll", "osmesa.dll", "pipe_swrast.dll")
PRIMARY_INSTALLER_BASENAME = "ai-pacs installer"
PACKAGE_IGNORE_PATTERNS = (
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd.orig",
    "*.pdb",
    "*.lib",
    "tests",
    "test",
    "testing",
    "docs",
    "doc",
    "examples",
    "example",
    "*.pyi",
    ".pytest_cache",
    ".mypy_cache",
)
THEME_QSS_SOURCE = PROJECT_ROOT / "generated-files" / "css" / "main.css"
THEME_QSS_RELATIVE_PATH = Path("Qss") / "main.qss"
ADVANCED_MPR_REQUIRED_RUNTIME_FILES = (
    "AIPacsAdvancedViewer.exe",
    "AIPacsAdvancedViewerLauncherSettings.ini",
    "bin/Python/startup_script.py",
    "python-install/Lib/site-packages/numpy/testing/__init__.py",
    "python-install/Lib/site-packages/pydicom/examples/__init__.py",
)


def print_step(message: str) -> None:
    print("\n" + "=" * 78)
    print(message)
    print("=" * 78)


def load_version() -> str:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return "0.0.0"
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore

    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return str((data.get("project") or {}).get("version") or "0.0.0")


def run_command(args: list[str], cwd: Path | None = None) -> None:
    print(f"[RUN] {' '.join(str(arg) for arg in args)}")
    completed = subprocess.run(
        args,
        cwd=str(cwd or PROJECT_ROOT),
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _sync_tree_incremental(src: Path, dst: Path) -> tuple[int, int, int]:
    """Sync *src* tree into *dst* in-place, copying only new/changed files
    and removing files that no longer exist in *src*.

    Uses (size, mtime) comparison — no full-file hashing — so the scan of
    7000+ files in a 1.4 GB bundle completes in < 1 second on a local drive.

    Returns *(copied, skipped, removed)* file counts.

    Reliability note:
    PyInstaller may regenerate files with new timestamps even when bytes are
    unchanged. To avoid unnecessary recopy churn, we first compare
    size+mtime and, when only mtime differs, fall back to a SHA-256 check.
    """
    dst.mkdir(parents=True, exist_ok=True)

    # Inventory source
    src_index: dict[str, Path] = {}
    for p in src.rglob("*"):
        if p.is_file():
            src_index[str(p.relative_to(src))] = p

    copied = skipped = removed = 0

    # Copy new or changed files
    for rel, src_file in src_index.items():
        dst_file = dst / rel
        if dst_file.exists():
            ss = src_file.stat()
            ds = dst_file.stat()
            # shutil.copy2 preserves mtime, so this comparison is reliable
            if ss.st_size == ds.st_size and abs(ss.st_mtime - ds.st_mtime) < 2.0:
                skipped += 1
                continue
            # If only timestamp changed, compare content hash before copying.
            if ss.st_size == ds.st_size and _sha256_file(src_file) == _sha256_file(dst_file):
                skipped += 1
                continue
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst_file)
        copied += 1

    # Remove files that were deleted from src
    for dst_file in list(dst.rglob("*")):
        if dst_file.is_file():
            if str(dst_file.relative_to(dst)) not in src_index:
                dst_file.unlink()
                removed += 1

    # Prune directories that became empty after removal
    for d in sorted(dst.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()  # only succeeds when empty
            except OSError:
                pass

    return copied, skipped, removed


def clean_outputs(
    preserve_dist: bool = False,
    preserve_build: bool = False,
    preserve_stage: bool = False,
    preserve_installer: bool = False,
) -> None:
    """Remove generated release outputs.

    Args:
        preserve_dist:  Keep the existing dist/AIPacs PyInstaller bundle intact
                        (used with --skip-pyinstaller and default incremental
                        runs that patch dist in-place from a temporary build).
        preserve_build: Keep PyInstaller's BUILD_DIR work-cache so that the next
                        run can reuse Analysis-00.toc and skip the expensive
                        dependency-scanning phase (saves ~3–4 min on incremental
                        builds).  Pass False only when a forced full clean is
                        needed (i.e. when --clean-build is given on the CLI).
        preserve_stage: Keep stage/core/ so the next run can use incremental
                        file-sync instead of a full 1.4 GB copytree (saves
                        ~30–60 s on incremental builds).  Sub-directories for
                        manifests and plugin-packages are always regenerated by
                        their own functions so they are unaffected.
        preserve_installer: Keep existing installer artifacts in output/installer
                        (useful when running with --skip-installer-compile or
                        when a build is interrupted before installer compile).
    """
    print_step("Cleaning previous release outputs")
    # Package/update outputs are regenerated each run. Installer artifacts are
    # optionally preserved so distribution does not lose the last good setup EXE.
    targets = [PACKAGE_OUTPUT_DIR, UPDATES_OUTPUT_DIR]
    if not preserve_installer:
        targets.append(INSTALLER_OUTPUT_DIR)
    if not preserve_stage:
        targets.append(STAGE_DIR)
    if not preserve_dist:
        targets.append(DIST_DIR)
    if not preserve_build:
        targets.append(BUILD_DIR)
    for path in targets:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    # Incremental staging only caches stage/core/. All other stage subtrees are
    # derived artifacts and must be rebuilt from scratch to avoid stale package
    # directories or manifest files surviving across builds.
    if preserve_stage and STAGE_DIR.exists():
        for derived_stage_dir in (MANIFEST_DIR, STAGED_PLUGIN_PACKAGE_DIR):
            if derived_stage_dir.exists():
                shutil.rmtree(derived_stage_dir, ignore_errors=True)


def _temp_dist_root() -> Path:
    """Return temporary dist root used for incremental PyInstaller builds."""
    return OUTPUT_DIR / "dist_tmp"


def _build_lock_path() -> Path:
    """Lock file to prevent overlapping release builds."""
    return OUTPUT_DIR / ".build_release.lock"


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _acquire_build_lock() -> Path:
    """Acquire process-level build lock or fail fast if another run is active."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _build_lock_path()
    payload = {
        "pid": os.getpid(),
        "utc": datetime.now(timezone.utc).isoformat(),
        "argv": sys.argv,
    }

    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            existing = json.loads(lock_path.read_text(encoding="utf-8"))
            existing_pid = int(existing.get("pid") or 0)
        except Exception:
            existing = {}
            existing_pid = 0

        if existing_pid and _pid_is_alive(existing_pid):
            raise SystemExit(
                "Another build_release.py run is active "
                f"(pid={existing_pid}). Wait for it to finish or terminate it first."
            )

        # Stale lock (or unreadable payload); recover automatically.
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            raise SystemExit(
                "Build lock exists but could not be removed. "
                f"Delete '{lock_path}' manually and rerun."
            )

        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)

    return lock_path


def _release_build_lock(lock_path: Path) -> None:
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def sync_theme_qss(bundle_root: Path) -> None:
    print_step("Syncing theme stylesheet")
    if not THEME_QSS_SOURCE.exists():
        print(f"[WARN] Theme stylesheet not found: {THEME_QSS_SOURCE}")
        return

    destination = bundle_root / THEME_QSS_RELATIVE_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(THEME_QSS_SOURCE, destination)
    print(f"[OK] Theme stylesheet synced to: {destination}")


def build_pyinstaller(force_clean: bool = False, distpath: Path | None = None) -> Path:
    """Run PyInstaller to produce the onedir bundle.

    Args:
        force_clean: When True, pass ``--clean`` to PyInstaller so it deletes
                     both its global hook cache and the local Analysis toc files
                     before building.  Use this only when dependencies have
                     genuinely changed (new packages, removed packages, spec
                     changes).  When False (the default) PyInstaller reuses the
                     cached Analysis-00.toc in BUILD_DIR and skips the slow
                     dependency-scanning phase, cutting typical incremental
                     builds from ~5 min down to ~1–2 min.
    """
    print_step("Building application with PyInstaller")
    dist_root = distpath or DIST_DIR
    dist_root.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
    ]
    if force_clean:
        cmd.append("--clean")
    cmd += [
        "--noconfirm",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(BUILD_DIR),
        str(SPEC_FILE),
    ]
    run_command(cmd)
    app_dir = dist_root / "AIPacs"
    if not (app_dir / "AIPacs.exe").exists():
        raise SystemExit(
            f"PyInstaller finished without producing {dist_root / 'AIPacs' / 'AIPacs.exe'}"
        )
    return app_dir


def sync_dist_bundle_incremental(source_dir: Path, destination_dir: Path) -> tuple[int, int, int]:
    """Incrementally patch destination dist bundle from source build output."""
    print_step("Syncing dist bundle (incremental)")
    copied, skipped, removed = _sync_tree_incremental(source_dir, destination_dir)
    print(
        f"[OK] Dist sync: {copied} copied, {skipped} skipped, "
        f"{removed} removed -> {destination_dir}"
    )
    return copied, skipped, removed


def validate_local_graphics_runtime() -> None:
    if sys.platform != "win32":
        return

    support = detect_software_graphics_support()
    if bool(support.get("ready", False)):
        return

    missing = ", ".join(support.get("missing") or []) or "unknown"
    raise SystemExit(
        "Software OpenGL runtime is incomplete for the release build. "
        f"Missing: {missing}. Place Mesa runtime files in 'graphics_runtime/' "
        "before running builder/build_release.py."
    )


def validate_release_bundle_graphics_runtime(source_dir: Path) -> None:
    if sys.platform != "win32":
        return

    # Support both "engine" (current) and "_internal" (legacy) bundle layouts
    engine_dir = source_dir / "engine"
    internal_dir = source_dir / "_internal"
    missing = []
    for name in REQUIRED_RELEASE_GRAPHICS_BINARIES:
        if (source_dir / name).exists() or (engine_dir / name).exists() or (internal_dir / name).exists():
            continue
        missing.append(name)
    if not missing:
        return

    raise SystemExit(
        "PyInstaller bundle is missing required software-render runtime files: "
        f"{', '.join(missing)}. The packaged workstation would not be able to "
        "run on CPU + Software OpenGL fallback."
    )


def stage_core_bundle(source_dir: Path, incremental: bool = False) -> Path:
    """Copy (or incrementally sync) the PyInstaller bundle into stage/core/.

    Args:
        incremental: When True and stage/core/ already exists, only copy files
                     that are new or changed (by size+mtime), and remove files
                     that were deleted.  For a 1.4 GB / 7700-file bundle this
                     saves ~30–60 s compared with a full copytree.
    """
    print_step("Staging Core bundle")
    core_dir = STAGE_DIR / "core"
    if incremental and core_dir.exists():
        copied, skipped, removed = _sync_tree_incremental(source_dir, core_dir)
        print(
            f"[OK] Staged (incremental): {copied} copied, "
            f"{skipped} skipped, {removed} removed -> {core_dir}"
        )
    else:
        shutil.copytree(source_dir, core_dir, dirs_exist_ok=True)
        print(f"[OK] Staged (full copy) -> {core_dir}")
    return core_dir


def stage_advanced_mpr_payload() -> dict[str, object]:
    print_step("Staging Advanced MPR runtime payload")
    runtime_root = advanced_mpr_runtime_root()
    payload_info = {
        "source": str(runtime_root),
        "staged": False,
        "destination": "",
        "reason": "",
    }

    missing: list[str] = []
    if runtime_root.exists():
        for relative in ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
            candidate = runtime_root / relative
            if not candidate.exists():
                missing.append(relative)
    else:
        missing = list(ADVANCED_MPR_REQUIRED_RUNTIME_FILES)

    if runtime_root.exists() and not missing:
        payload_info["staged"] = True
    else:
        if runtime_root.exists():
            payload_info["reason"] = (
                "Advanced MPR runtime is incomplete. Missing required runtime files: "
                + ", ".join(missing)
            )
        else:
            payload_info["reason"] = (
                "Advanced MPR runtime was not found. "
                "Run tools/slicer/assemble_slicer_runtime.py before building the installer payload."
            )

    payload_info["missing_required_files"] = missing

    return payload_info


def _package_ignore_filter(_directory: str, names: list[str]) -> set[str]:
    ignored = set(shutil.ignore_patterns(*PACKAGE_IGNORE_PATTERNS)(_directory, names))
    lower_name_map = {name.lower(): name for name in names}
    for candidate in (
        "tests",
        "test",
        "testing",
        "docs",
        "doc",
        "examples",
        "example",
        "build",
        ".pytest_cache",
        ".mypy_cache",
    ):
        actual = lower_name_map.get(candidate)
        if actual:
            ignored.add(actual)
    return ignored


def _copy_package_source_tree(package_dir: Path, source_dirs: list[str]) -> bool:
    payload_root = package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME / "python"
    copied = False
    for relative in source_dirs:
        source = PROJECT_ROOT / relative
        if not source.exists():
            continue
        destination = payload_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=_package_ignore_filter,
            )
        else:
            shutil.copy2(source, destination)
        copied = True
    return copied


def _write_package_archive(source_dir: Path, archive_path: Path) -> str:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    shutil.make_archive(str(archive_path.with_suffix("")), "zip", root_dir=source_dir)
    with archive_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _project_relative_path(path: str | Path) -> str:
    candidate = Path(path)
    try:
        relative = candidate.resolve().relative_to(PROJECT_ROOT.resolve())
    except Exception:
        relative = candidate
    return str(relative).replace("\\", "/")


def _write_package_feed(target_dir: Path, version: str, package_index: list[dict[str, object]]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / MODULE_PACKAGE_FEED_FILENAME).write_text(
        json.dumps(
            {
                "app_name": APP_NAME,
                "version": version,
                "packages": package_index,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def build_module_packages(version: str, advanced_payload: dict[str, object]) -> list[dict[str, object]]:
    print_step("Building module packages")
    PACKAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    STAGED_PLUGIN_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    package_index: list[dict[str, object]] = []
    for definition in load_plugin_package_definitions(optional_only=True):
        module_id = str(definition["module_id"])
        package_dir = STAGED_PLUGIN_PACKAGE_DIR / module_id
        if package_dir.exists():
            shutil.rmtree(package_dir, ignore_errors=True)

        has_payload = False
        if str(definition.get("build_strategy") or "") == "runtime_payload":
            source_root = Path(str(advanced_payload.get("source") or ""))
            if bool(advanced_payload.get("staged")) and source_root.exists():
                package_dir.mkdir(parents=True, exist_ok=True)
                # Runtime payloads (Advanced MPR / custom Slicer) must be copied
                # losslessly. Applying _package_ignore_filter here strips
                # required runtime folders such as numpy/testing and causes
                # launch-time import failures (e.g. numpy.testing missing).
                shutil.copytree(
                    source_root,
                    package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME,
                    dirs_exist_ok=True,
                )
                _copy_package_source_tree(package_dir, list(definition.get("source_paths") or []))
                has_payload = True
        else:
            package_dir.mkdir(parents=True, exist_ok=True)
            has_payload = _copy_package_source_tree(package_dir, list(definition.get("source_paths") or []))

        manifest = {
            "format_version": MODULE_PACKAGE_FORMAT_VERSION,
            "app_name": APP_NAME,
            "module_id": module_id,
            "title": str(definition.get("title") or module_id),
            "tier": str(definition.get("tier") or "optional"),
            "version": version,
            "package_kind": str(definition.get("package_kind") or "bundled_unlock"),
            "payload_dir": MODULE_PACKAGE_PAYLOAD_DIRNAME if has_payload else "",
            "python_paths": list(definition.get("python_paths") or []) if has_payload else [],
            "requires_restart": True,
            "healthcheck_import": str(definition.get("healthcheck_import") or ""),
            "healthcheck_path": str(definition.get("healthcheck_path") or ""),
            "integration_points": list(definition.get("integration_points") or []),
            "install_channels": list(definition.get("install_channels") or []),
            "sdk_entrypoint_group": str(definition.get("sdk_entrypoint_group") or ""),
            "sdk_entrypoint_name": str(definition.get("sdk_entrypoint_name") or ""),
        }
        if not has_payload:
            if package_dir.exists():
                shutil.rmtree(package_dir, ignore_errors=True)
            package_index.append(
                {
                    "module_id": module_id,
                    "title": manifest["title"],
                    "version": version,
                    "package_kind": manifest["package_kind"],
                    "archive_name": "",
                    "archive_path": "",
                    "sha256": "",
                    "has_payload": False,
                    "available": False,
                    "package_format": "directory" if manifest["package_kind"] == "runtime_payload" else "zip",
                    "staged_package_path": "",
                    "definition_path": _project_relative_path(str(definition.get("definition_path") or "")),
                    "install_channels": list(definition.get("install_channels") or []),
                }
            )
            continue

        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / MODULE_PACKAGE_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if module_id == "advanced_mpr":
            package_index.append(
                {
                    "module_id": module_id,
                    "title": manifest["title"],
                    "version": version,
                    "package_kind": manifest["package_kind"],
                    "archive_name": package_dir.name,
                    "archive_path": package_dir.name,
                    "sha256": "",
                    "has_payload": has_payload,
                    "available": True,
                    "package_format": "directory",
                    "staged_package_path": package_dir.name,
                    "definition_path": _project_relative_path(str(definition.get("definition_path") or "")),
                    "install_channels": list(definition.get("install_channels") or []),
                }
            )
            continue

        archive_path = PACKAGE_OUTPUT_DIR / f"{module_id}-{version}.zip"
        sha256 = _write_package_archive(package_dir, archive_path)
        package_index.append(
            {
                "module_id": module_id,
                "title": manifest["title"],
                "version": version,
                "package_kind": manifest["package_kind"],
                "archive_name": archive_path.name,
                "archive_path": archive_path.name,
                "sha256": sha256,
                "has_payload": has_payload,
                "available": has_payload,
                "package_format": "zip",
                "staged_package_path": package_dir.name,
                "definition_path": _project_relative_path(str(definition.get("definition_path") or "")),
                "install_channels": list(definition.get("install_channels") or []),
            }
        )

    _write_package_feed(PACKAGE_OUTPUT_DIR, version, package_index)
    _write_package_feed(STAGED_PLUGIN_PACKAGE_DIR, version, package_index)
    return package_index


def write_manifest(
    version: str,
    core_dir: Path,
    advanced_payload: dict[str, object],
    module_packages: list[dict[str, object]],
) -> None:
    print_step("Writing release manifest")
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    install_profile = default_installation_profile()
    install_profile["app_version"] = version
    install_profile["installer"] = {
        "current_version": version,
        "detected_existing_version": "",
        "install_action": "fresh_install",
        "should_update": False,
    }
    install_profile["generated_at_utc"] = ""
    (MANIFEST_DIR / INSTALLATION_PROFILE_FILENAME).write_text(
        json.dumps(install_profile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest = {
        "version": version,
        "core_dir": str(core_dir),
        "modules": MODULE_CATALOG,
        "payloads": {
            "advanced_mpr": advanced_payload,
        },
        "installer": {
            "version": version,
            "supports_existing_install_detection": True,
            "supports_version_comparison": True,
        },
        "module_packages": module_packages,
    }
    (MANIFEST_DIR / "release_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def find_iscc() -> Path | None:
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    candidates = [
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    if local_appdata:
        candidates.append(str(Path(local_appdata) / "Programs" / "Inno Setup 6" / "ISCC.exe"))
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def compile_installer(version: str) -> Path | None:
    print_step("Compiling Inno Setup installer")
    iscc = find_iscc()
    if iscc is None:
        print("[WARN] Inno Setup compiler (ISCC.exe) was not found. Installer script was prepared but not compiled.")
        return None

    INSTALLER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            str(iscc),
            f"/DMyAppVersion={version}",
            f"/DStageDir={STAGE_DIR}",
            f"/DInstallerOutputDir={INSTALLER_OUTPUT_DIR}",
            f"/DInstallerBaseName={PRIMARY_INSTALLER_BASENAME}",
            str(INSTALLER_SCRIPT),
        ],
        cwd=BUILDER_DIR / "installer",
    )

    expected = INSTALLER_OUTPUT_DIR / f"{PRIMARY_INSTALLER_BASENAME}.exe"
    if expected.exists():
        return expected

    fallback_candidates = sorted(
        INSTALLER_OUTPUT_DIR.glob("*.exe"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not fallback_candidates:
        raise SystemExit(
            "Installer compile finished but no .exe output was found in builder/output/installer/."
        )
    return fallback_candidates[0]


def normalize_installer_artifacts(compiled_installer: Path, version: str) -> dict[str, str]:
    INSTALLER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    primary = INSTALLER_OUTPUT_DIR / f"{PRIMARY_INSTALLER_BASENAME}.exe"
    versioned = INSTALLER_OUTPUT_DIR / f"{PRIMARY_INSTALLER_BASENAME} v{version}.exe"

    if compiled_installer.resolve() != primary.resolve():
        shutil.copy2(compiled_installer, primary)
    shutil.copy2(primary, versioned)

    return {
        "compiled": str(compiled_installer),
        "primary": str(primary),
        "versioned": str(versioned),
    }


def write_installer_release_metadata(installer_artifacts: dict[str, str], version: str) -> None:
    primary = Path(installer_artifacts["primary"])
    versioned = Path(installer_artifacts["versioned"])
    primary_sha = _sha256_file(primary)
    versioned_sha = _sha256_file(versioned)

    install_notes_en = "\n".join(
        [
            "AIPacs Installation Notes (English)",
            "==================================",
            "",
            "Files to share with installation staff:",
            f"1) {primary.name}",
            f"2) {versioned.name} (version-labeled copy, same build)",
            "3) SHA256.txt (checksum verification)",
            "",
            "Recommended install steps:",
            '- Right-click installer and choose "Run as administrator".',
            "- Choose setup type:",
            "  - Core: core platform only",
            "  - Custom: choose optional modules for this workstation",
            "- In Custom mode, confirm the optional modules needed on the target PC.",
            "- Review the Graphics Acceleration page:",
            "  - The installer probes Windows for a compatible GPU",
            "  - The checkbox can still be overridden manually",
            "  - AIPacs will probe again at first launch and fall back safely when required",
            "- If the selected install folder already has AIPacs, the installer compares versions",
            "  - Older installed version: update in place",
            "  - Same installed version: reinstall/repair",
            "  - Newer installed version: downgrade warning before continuing",
            "- Complete the wizard and launch AIPacs.",
            "",
            "Post-install quick check:",
            "- App opens successfully.",
            "- Optional modules selected during setup are available.",
            "- Graphics mode works (GPU when available, software fallback otherwise).",
            "- installation_profile.json records the chosen modules and graphics preference.",
            "- installation_profile.json records the detected previous version and planned install action.",
            "",
            "Note:",
            "You only need one installer EXE for end users. Keep the versioned EXE for release tracking.",
            "",
        ]
    )
    install_notes_fa = "\n".join(
        [
            "راهنمای نصب AIPacs (فارسی)",
            "===========================",
            "",
            "فایل هایی که باید به تیم نصب تحویل داده شود:",
            f"1) {primary.name}",
            f"2) {versioned.name} (نسخه دارای شماره ورژن، همان بیلد)",
            "3) SHA256_FA.txt (برای بررسی صحت فایل)",
            "",
            "مراحل پیشنهادی نصب:",
            '- روی فایل نصب راست کلیک کنید و گزینه "Run as administrator" را بزنید.',
            "- نوع نصب را انتخاب کنید:",
            "  - Core: فقط هسته اصلی نرم افزار",
            "  - Custom: هسته + ماژول های اختیاری انتخاب شده",
            "- مراحل Wizard را کامل کنید و AIPacs را اجرا کنید.",
            "",
            "بررسی سریع بعد از نصب:",
            "- نرم افزار بدون خطا اجرا شود.",
            "- ماژول های اختیاری انتخاب شده در دسترس باشند.",
            "- حالت گرافیکی درست کار کند (GPU در صورت وجود، وگرنه Software OpenGL).",
            "",
            "نکته:",
            "برای کاربر نهایی فقط یک فایل EXE کافی است. فایل نسخه دار را برای آرشیو و رهگیری انتشار نگه دارید.",
            "",
        ]
    )
    sha256_en = "\n".join(
        [
            "AIPacs Installer SHA256 Checksums (English)",
            "==========================================",
            "",
            primary.name,
            f"SHA256: {primary_sha}",
            "",
            versioned.name,
            f"SHA256: {versioned_sha}",
            "",
            f"Version: {version}",
            "Status: Both files should be identical builds.",
            "",
        ]
    )
    sha256_fa = "\n".join(
        [
            "هش های SHA256 نصب کننده AIPacs (فارسی)",
            "======================================",
            "",
            primary.name,
            f"SHA256: {primary_sha}",
            "",
            versioned.name,
            f"SHA256: {versioned_sha}",
            "",
            f"Version: {version}",
            "وضعیت: هر دو فایل باید بیلد یکسان باشند.",
            "",
        ]
    )

    (INSTALLER_OUTPUT_DIR / "INSTALL_NOTES.txt").write_text(install_notes_en, encoding="utf-8")
    (INSTALLER_OUTPUT_DIR / "INSTALL_NOTES_FA.txt").write_text(install_notes_fa, encoding="utf-8")
    (INSTALLER_OUTPUT_DIR / "SHA256.txt").write_text(sha256_en, encoding="utf-8")
    (INSTALLER_OUTPUT_DIR / "SHA256_FA.txt").write_text(sha256_fa, encoding="utf-8")


def publish_update_bundle(
    version: str,
    module_packages: list[dict[str, object]],
    installer_artifacts: dict[str, str],
) -> dict[str, object]:
    print_step("Publishing update bundle")
    UPDATES_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    UPDATES_CORE_DIR.mkdir(parents=True, exist_ok=True)
    UPDATES_MODULES_DIR.mkdir(parents=True, exist_ok=True)

    if (PACKAGE_OUTPUT_DIR / MODULE_PACKAGE_FEED_FILENAME).exists():
        shutil.copy2(PACKAGE_OUTPUT_DIR / MODULE_PACKAGE_FEED_FILENAME, UPDATES_MODULES_DIR / MODULE_PACKAGE_FEED_FILENAME)

    optional_index = {str(item.get("module_id") or ""): dict(item) for item in module_packages}
    for package in module_packages:
        module_id = str(package.get("module_id") or "").strip()
        if not module_id or not bool(package.get("available")):
            continue
        package_format = str(package.get("package_format") or "")
        if package_format == "directory":
            staged_name = str(package.get("staged_package_path") or module_id)
            source_dir = STAGED_PLUGIN_PACKAGE_DIR / staged_name
            if source_dir.exists():
                shutil.copytree(source_dir, UPDATES_MODULES_DIR / staged_name, dirs_exist_ok=True)
        else:
            archive_name = str(package.get("archive_name") or "").strip()
            if archive_name and (PACKAGE_OUTPUT_DIR / archive_name).exists():
                shutil.copy2(PACKAGE_OUTPUT_DIR / archive_name, UPDATES_MODULES_DIR / archive_name)

    core_entry = {
        "module_id": CORE_COMPONENT_ID,
        "title": CORE_COMPONENT_TITLE,
        "release_version": version,
        "artifact_type": "installer",
        "artifact_path": "",
        "sha256": "",
        "available": False,
    }
    if installer_artifacts:
        for name in ("primary", "versioned"):
            artifact_path = Path(installer_artifacts[name])
            shutil.copy2(artifact_path, UPDATES_CORE_DIR / artifact_path.name)
        for name in ("SHA256.txt", "SHA256_FA.txt", "INSTALL_NOTES.txt", "INSTALL_NOTES_FA.txt"):
            source = INSTALLER_OUTPUT_DIR / name
            if source.exists():
                shutil.copy2(source, UPDATES_CORE_DIR / name)
        versioned_name = Path(installer_artifacts["versioned"]).name
        core_entry.update(
            {
                "artifact_path": f"core/{versioned_name}",
                "sha256": _sha256_file(UPDATES_CORE_DIR / versioned_name),
                "available": True,
            }
        )

    components: list[dict[str, object]] = []
    for definition in load_plugin_package_definitions(optional_only=False):
        module_id = str(definition["module_id"])
        tier = str(definition.get("tier") or "optional")
        item = {
            "module_id": module_id,
            "title": str(definition.get("title") or module_id),
            "tier": tier,
            "package_kind": str(definition.get("package_kind") or ("core" if tier == "basic" else "bundled_unlock")),
            "release_version": version,
            "delivery": "core_bundle" if tier == "basic" else "package",
            "artifact_type": "core_bundle" if tier == "basic" else "",
            "artifact_path": "",
            "sha256": "",
            "available": True if tier == "basic" else False,
        }
        optional = optional_index.get(module_id)
        if optional:
            package_format = str(optional.get("package_format") or "")
            artifact_name = str(optional.get("archive_name") or optional.get("staged_package_path") or "")
            item.update(
                {
                    "artifact_type": "package_directory" if package_format == "directory" else "package_zip",
                    "artifact_path": f"modules/{artifact_name}" if artifact_name else "",
                    "sha256": str(optional.get("sha256") or ""),
                    "available": bool(optional.get("available")),
                }
            )
        components.append(item)

    feed = {
        "app_name": APP_NAME,
        "channel": "stable",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "core": core_entry,
        "components": components,
    }
    (UPDATES_OUTPUT_DIR / UPDATE_FEED_FILENAME).write_text(
        json.dumps(feed, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return feed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and stage the AIPacs Windows release bundle.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Incremental build notes:\n"
            "  By default both the PyInstaller Analysis cache (BUILD_DIR) AND the\n"
            "  staging tree (stage/core/) and dist tree (dist/AIPacs) are preserved\n"
            "  between runs.\n"
            "  - Analysis cache skips the 3-4 min dependency-scanning phase.\n"
            "  - PyInstaller builds to a temp dist dir, then only changed files are\n"
            "    synced into dist/AIPacs (stable DLLs remain untouched).\n"
            "  - Incremental staging skips ~30-60 s of copying 1.4 GB of DLLs.\n"
            "  Only changed Python files are recompiled and only changed/new\n"
            "  files are synced to stage/core/.\n"
            "  Use --clean-build when you add/remove packages or change the spec.\n"
            "\n"
            "Typical workflows:\n"
            "  python build.py                          # incremental (default)\n"
            "  python build.py --clean-build            # full clean rebuild\n"
            "  python build.py --skip-pyinstaller       # reuse existing dist bundle\n"
            "  python build.py --skip-installer-compile # no ISCC, just dist+stage\n"
        ),
    )
    parser.add_argument(
        "--skip-pyinstaller",
        action="store_true",
        help="Reuse the existing builder/output/dist/AIPacs bundle (no PyInstaller run).",
    )
    parser.add_argument(
        "--skip-installer-compile",
        action="store_true",
        help="Prepare staging and manifests without running ISCC.exe.",
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="Only remove generated build outputs.",
    )
    parser.add_argument(
        "--clean-build",
        action="store_true",
        help=(
            "Force a full clean rebuild: wipe BUILD_DIR and pass --clean to "
            "PyInstaller.  Use when packages/dependencies have changed.  Without "
            "this flag the Analysis cache is preserved for faster incremental builds."
        ),
    )
    return parser.parse_args()


def main() -> int:
    lock_path = _acquire_build_lock()
    args = parse_args()
    try:
        if args.clean_only:
            clean_outputs(preserve_build=False, preserve_installer=False)
            return 0

        # On incremental runs preserve both the PyInstaller work-cache (BUILD_DIR)
        # and cached dist/stage bundles so that:
        #   - PyInstaller reuses Analysis-00.toc -> skips 3-4 min dependency scan.
        #   - dist/AIPacs is patched in-place from temp output (changed files only).
        #   - stage_core_bundle only copies changed/new files -> skips ~30-60 s
        #     of copying the full 1.4 GB bundle.
        # Use --clean-build to wipe both caches and force a full rebuild.
        incremental = not args.clean_build
        clean_outputs(
            preserve_dist=(args.skip_pyinstaller or incremental),
            preserve_build=incremental,
            preserve_stage=incremental,
            preserve_installer=(incremental or args.skip_installer_compile),
        )
        version = load_version()
        source_dir = DIST_DIR / "AIPacs"
        if not args.skip_pyinstaller:
            validate_local_graphics_runtime()
            if incremental:
                tmp_dist = _temp_dist_root()
                if tmp_dist.exists():
                    shutil.rmtree(tmp_dist, ignore_errors=True)
                try:
                    source_dir = build_pyinstaller(force_clean=False, distpath=tmp_dist)
                    destination_dir = DIST_DIR / "AIPacs"
                    sync_dist_bundle_incremental(source_dir, destination_dir)
                    source_dir = destination_dir
                finally:
                    if tmp_dist.exists():
                        shutil.rmtree(tmp_dist, ignore_errors=True)
            else:
                source_dir = build_pyinstaller(force_clean=True)
        elif not (source_dir / "AIPacs.exe").exists():
            raise SystemExit("--skip-pyinstaller was used but builder/output/dist/AIPacs/AIPacs.exe is missing.")

        sync_theme_qss(source_dir)
        validate_release_bundle_graphics_runtime(source_dir)

        core_dir = stage_core_bundle(source_dir, incremental=incremental)
        advanced_payload = stage_advanced_mpr_payload()
        if not bool(advanced_payload.get("staged")):
            allow_missing = os.environ.get("AIPACS_ALLOW_MISSING_ADVANCED_MPR", "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            reason = str(advanced_payload.get("reason") or "Advanced MPR payload is unavailable.")
            if allow_missing:
                print(f"[WARN] {reason}")
                print("[WARN] Continuing because AIPACS_ALLOW_MISSING_ADVANCED_MPR is enabled.")
            else:
                raise SystemExit(
                    "Advanced MPR runtime payload validation failed. "
                    + reason
                    + " Set AIPACS_ALLOW_MISSING_ADVANCED_MPR=1 to bypass deliberately."
                )
        module_packages = build_module_packages(version, advanced_payload)
        write_manifest(version, core_dir, advanced_payload, module_packages)

        installer_artifacts: dict[str, str] = {}
        if not args.skip_installer_compile:
            compiled_installer = compile_installer(version)
            if compiled_installer is not None:
                installer_artifacts = normalize_installer_artifacts(compiled_installer, version)
                write_installer_release_metadata(installer_artifacts, version)

        publish_update_bundle(version, module_packages, installer_artifacts)

        print_step("Release staging complete")
        print(f"Core bundle: {core_dir}")
        print(f"Packages:    {PACKAGE_OUTPUT_DIR}")
        print(f"Stage root:  {STAGE_DIR}")
        print(f"Updates:     {UPDATES_OUTPUT_DIR}")
        print(f"Version:     {version}")
        if installer_artifacts:
            print(f"Installer:   {installer_artifacts['primary']}")
            print(f"Installer v: {installer_artifacts['versioned']}")
        return 0
    finally:
        _release_build_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
