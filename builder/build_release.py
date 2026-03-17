from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aipacs_runtime import (
    APP_NAME,
    INSTALLATION_PROFILE_FILENAME,
    MODULE_CATALOG,
    MODULE_PACKAGE_FEED_FILENAME,
    MODULE_PACKAGE_FORMAT_VERSION,
    MODULE_PACKAGE_MANIFEST_FILENAME,
    MODULE_PACKAGE_PAYLOAD_DIRNAME,
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


def clean_outputs(preserve_dist: bool = False) -> None:
    print_step("Cleaning previous release outputs")
    targets = [BUILD_DIR, STAGE_DIR, INSTALLER_OUTPUT_DIR, PACKAGE_OUTPUT_DIR]
    if not preserve_dist:
        targets.insert(0, DIST_DIR)
    for path in targets:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def build_pyinstaller() -> Path:
    print_step("Building application with PyInstaller")
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            str(BUILD_DIR),
            str(SPEC_FILE),
        ]
    )
    app_dir = DIST_DIR / "AIPacs"
    if not (app_dir / "AIPacs.exe").exists():
        raise SystemExit("PyInstaller finished without producing dist/AIPacs/AIPacs.exe")
    return app_dir


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

    internal_dir = source_dir / "_internal"
    missing = []
    for name in REQUIRED_RELEASE_GRAPHICS_BINARIES:
        if (source_dir / name).exists() or (internal_dir / name).exists():
            continue
        missing.append(name)
    if not missing:
        return

    raise SystemExit(
        "PyInstaller bundle is missing required software-render runtime files: "
        f"{', '.join(missing)}. The packaged workstation would not be able to "
        "run on CPU + Software OpenGL fallback."
    )


def stage_core_bundle(source_dir: Path) -> Path:
    print_step("Staging Core bundle")
    core_dir = STAGE_DIR / "core"
    shutil.copytree(source_dir, core_dir, dirs_exist_ok=True)
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

    exe_path = runtime_root / "AIPacsAdvancedViewer.exe"
    if runtime_root.exists() and exe_path.exists():
        payload_info["staged"] = True
    else:
        payload_info["reason"] = (
            "Advanced MPR runtime was not found. "
            "Run tools/assemble_slicer_runtime.py before building the installer payload."
        )

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
                shutil.copytree(
                    source_root,
                    package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME,
                    dirs_exist_ok=True,
                    ignore=_package_ignore_filter,
                )
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and stage the AIPacs Windows release bundle.")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="Reuse the existing builder/output/dist/AIPacs bundle.")
    parser.add_argument("--skip-installer-compile", action="store_true", help="Prepare staging and manifests without running ISCC.exe.")
    parser.add_argument("--clean-only", action="store_true", help="Only remove generated build outputs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.clean_only:
        clean_outputs()
        return 0

    clean_outputs(preserve_dist=args.skip_pyinstaller)
    version = load_version()
    source_dir = DIST_DIR / "AIPacs"
    if not args.skip_pyinstaller:
        validate_local_graphics_runtime()
        source_dir = build_pyinstaller()
    elif not (source_dir / "AIPacs.exe").exists():
        raise SystemExit("--skip-pyinstaller was used but builder/output/dist/AIPacs/AIPacs.exe is missing.")

    validate_release_bundle_graphics_runtime(source_dir)

    core_dir = stage_core_bundle(source_dir)
    advanced_payload = stage_advanced_mpr_payload()
    module_packages = build_module_packages(version, advanced_payload)
    write_manifest(version, core_dir, advanced_payload, module_packages)

    installer_artifacts: dict[str, str] = {}
    if not args.skip_installer_compile:
        compiled_installer = compile_installer(version)
        if compiled_installer is not None:
            installer_artifacts = normalize_installer_artifacts(compiled_installer, version)

    print_step("Release staging complete")
    print(f"Core bundle: {core_dir}")
    print(f"Packages:    {PACKAGE_OUTPUT_DIR}")
    print(f"Stage root:  {STAGE_DIR}")
    print(f"Version:     {version}")
    if installer_artifacts:
        print(f"Installer:   {installer_artifacts['primary']}")
        print(f"Installer v: {installer_artifacts['versioned']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
