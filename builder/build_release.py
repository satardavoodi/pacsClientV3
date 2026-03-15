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
BUILDER_DIR = PROJECT_ROOT / "builder"
OUTPUT_DIR = BUILDER_DIR / "output"
DIST_DIR = OUTPUT_DIR / "dist"
BUILD_DIR = OUTPUT_DIR / "build"
STAGE_DIR = OUTPUT_DIR / "stage"
MANIFEST_DIR = STAGE_DIR / "manifest"
INSTALLER_OUTPUT_DIR = OUTPUT_DIR / "installer"
PACKAGE_OUTPUT_DIR = OUTPUT_DIR / "packages"
SPEC_FILE = BUILDER_DIR / "spec" / "appA_workstation.spec"
INSTALLER_SCRIPT = BUILDER_DIR / "installer" / "AIPacs_Setup.iss"
REQUIRED_RELEASE_GRAPHICS_BINARIES = ("opengl32sw.dll", "osmesa.dll", "pipe_swrast.dll")


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
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "tests", "docs"),
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


def build_module_packages(version: str, advanced_payload: dict[str, object]) -> list[dict[str, object]]:
    print_step("Building module packages")
    PACKAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    package_index: list[dict[str, object]] = []
    for item in MODULE_CATALOG:
        if str(item.get("tier") or "") != "optional":
            continue

        module_id = str(item["id"])
        if module_id == "advanced_mpr":
            package_dir = PACKAGE_OUTPUT_DIR / f"{module_id}-{version}"
        else:
            package_dir = STAGE_DIR / "package_build" / module_id
        if package_dir.exists():
            shutil.rmtree(package_dir, ignore_errors=True)
        package_dir.mkdir(parents=True, exist_ok=True)

        has_payload = False
        if module_id == "advanced_mpr":
            source_root = Path(str(advanced_payload.get("source") or ""))
            if bool(advanced_payload.get("staged")) and source_root.exists():
                shutil.copytree(source_root, package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME, dirs_exist_ok=True)
                has_payload = True
        else:
            source_dirs = list(item.get("package_sources") or [])
            has_payload = _copy_package_source_tree(package_dir, source_dirs)

        manifest = {
            "format_version": MODULE_PACKAGE_FORMAT_VERSION,
            "app_name": APP_NAME,
            "module_id": module_id,
            "title": str(item.get("title") or module_id),
            "tier": str(item.get("tier") or "optional"),
            "version": version,
            "package_kind": str(item.get("package_kind") or "bundled_unlock"),
            "payload_dir": MODULE_PACKAGE_PAYLOAD_DIRNAME if has_payload else "",
            "python_paths": list(item.get("package_python_paths") or []) if has_payload else [],
            "requires_restart": True,
            "healthcheck_import": str(item.get("healthcheck_import") or ""),
            "healthcheck_path": str(item.get("healthcheck_path") or ""),
        }
        (package_dir / MODULE_PACKAGE_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if manifest["package_kind"] == "runtime_payload" and not has_payload:
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
                    "package_format": "directory",
                }
            )
            continue

        if module_id == "advanced_mpr":
            package_index.append(
                {
                    "module_id": module_id,
                    "title": manifest["title"],
                    "version": version,
                    "package_kind": manifest["package_kind"],
                    "archive_name": package_dir.name,
                    "archive_path": str(package_dir),
                    "sha256": "",
                    "has_payload": has_payload,
                    "available": True,
                    "package_format": "directory",
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
                "archive_path": str(archive_path),
                "sha256": sha256,
                "has_payload": has_payload,
                "available": has_payload or manifest["package_kind"] == "bundled_unlock",
                "package_format": "zip",
            }
        )

    (PACKAGE_OUTPUT_DIR / MODULE_PACKAGE_FEED_FILENAME).write_text(
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
    candidates = [
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def compile_installer(version: str) -> None:
    print_step("Compiling Inno Setup installer")
    iscc = find_iscc()
    if iscc is None:
        print("[WARN] Inno Setup compiler (ISCC.exe) was not found. Installer script was prepared but not compiled.")
        return

    INSTALLER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            str(iscc),
            f"/DMyAppVersion={version}",
            f"/DStageDir={STAGE_DIR}",
            f"/DInstallerOutputDir={INSTALLER_OUTPUT_DIR}",
            str(INSTALLER_SCRIPT),
        ],
        cwd=BUILDER_DIR / "installer",
    )


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

    if not args.skip_installer_compile:
        compile_installer(version)

    print_step("Release staging complete")
    print(f"Core bundle: {core_dir}")
    print(f"Packages:    {PACKAGE_OUTPUT_DIR}")
    print(f"Stage root:  {STAGE_DIR}")
    print(f"Version:     {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
