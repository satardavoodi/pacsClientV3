"""Cache build inputs locally; never build, install, publish, or change the active environments."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
DEFAULT_ROOT = REPO / "generated-files/distribution-assets"
RUNTIME_ITEMS = ("AIPacsAdvancedViewer.exe", "AIPacsAdvancedViewerLauncherSettings.ini",
                 "bin", "deps", "lib", "python-install", "share", "Logo.png", "LogoFull.png", "SplashScreen.png")


def digest(path):
    # hashlib.file_digest() may delegate to a platform-optimized read path that
    # intermittently raises EINVAL for large files on Windows.  The release
    # asset cache contains multi-hundred-megabyte wheels and model archives, so
    # use an explicit bounded read loop for deterministic verification.
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def snapshot_runtime(source, destination):
    """Keep required package resources; exclude workstation settings and probe files at root."""
    for name in RUNTIME_ITEMS:
        source_path = source / name
        if not source_path.exists():
            raise FileNotFoundError("Required Slicer runtime item is missing: " + name)
        target = destination / name
        if source_path.is_dir():
            for path in source_path.rglob("*"):
                if path.is_symlink() or path.is_junction():
                    raise ValueError("Runtime snapshot cannot include filesystem links")
            shutil.copytree(source_path, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target)


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or manifest.get("platform") != "win_amd64":
        raise ValueError("Unsupported distribution asset manifest")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 150000:
        raise ValueError("Invalid asset inventory")
    required = {"slicer-runtime/AIPacsAdvancedViewer.exe", "offline_lumbar/manifest.json",
                "offline_lumbar/python/python.exe", "inno-setup/ISCC.exe",
                "downloads/python-3.13.5-amd64.exe", "build-environment.lock"}
    seen = set()
    for item in files:
        name = item["path"]
        if name in seen or Path(name).as_posix() != name or ".." in Path(name).parts or ":" in name:
            raise ValueError("Unsafe or duplicate asset path")
        seen.add(name)
        file = (root / item["path"]).resolve()
        if not file.is_relative_to(root.resolve()) or not file.is_file():
            raise ValueError("Build asset missing or outside cache: " + item["path"])
        try:
            actual_size = file.stat().st_size
            actual_digest = digest(file)
        except OSError as exc:
            raise OSError(
                exc.errno,
                "Build asset could not be read during verification: " + item["path"],
                str(file),
            ) from exc
        if actual_size != item["size"] or actual_digest != item["sha256"]:
            raise ValueError("Build asset hash mismatch: " + item["path"])
    if not required.issubset(seen):
        raise ValueError("Required runtime or build assets are absent from the inventory")
    return manifest


def cache_wheels(python, requirements, destination, log, *, model=False):
    destination.mkdir(parents=True, exist_ok=True)
    # Exact installed versions; no dependency resolution or environment modification.
    command = [sys.executable, "-m", "pip", "--isolated", "--python", str(python),
               "wheel", "--no-deps", "--no-build-isolation", "--progress-bar", "off",
               "--wheel-dir", str(destination), "--index-url", "https://pypi.org/simple"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "PIP_"))}
    env["PIP_CACHE_DIR"] = str(REPO / "generated-files/offline-lumbar/downloads/pip")
    lines = requirements.read_text(encoding="utf-8").splitlines()
    if model:
        lines = [line for line in lines if not line.lower().startswith("torch==")]
        cpu_command = command[:-2] + ["--index-url", "https://download.pytorch.org/whl/cpu", "torch==2.6.0+cpu"]
        with log.open("w", encoding="utf-8") as stream:
            subprocess.run(cpu_command, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=1200)
    filtered = destination.parent / (destination.name + "-requirements.txt")
    filtered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with log.open("a", encoding="utf-8") as stream:
        subprocess.run(command + ["-r", str(filtered)], env=env, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=1800)
    records = []
    from packaging.utils import parse_wheel_filename, canonicalize_name
    wheels = {}
    for file in destination.glob("*.whl"):
        name, version, _, _ = parse_wheel_filename(file.name)
        wheels[(canonicalize_name(name), str(version))] = file
    for line in requirements.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        file = wheels.get((canonicalize_name(name), version))
        if file is None:
            raise RuntimeError("A required wheel was not cached: " + line)
        records.append(line + " --hash=sha256:" + digest(file))
    hashed = destination.parent / (destination.name + "-hashed.lock")
    hashed.write_text("\n".join(records) + "\n", encoding="utf-8")
    # Resolve the complete dependency graph with networking disabled. This catches
    # dependencies such as argparse that pip freeze omits as stdlib-shadowing packages.
    with log.open("a", encoding="utf-8") as stream:
        subprocess.run([sys.executable, "-m", "pip", "--isolated", "--python", str(python),
                        "install", "--dry-run", "--ignore-installed", "--no-index",
                        "--find-links", str(destination), "--require-hashes", "-r", str(hashed)],
                       env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=300)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--download-wheels", action="store_true")
    parser.add_argument("--refresh-wheels", action="store_true",
                        help="Verify a completed cache, refresh its locked wheels, and rebuild the inventory")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.check:
        manifest = verify(root)
        print(json.dumps({"verified_files": len(manifest["files"]), "bytes": sum(r["size"] for r in manifest["files"])}))
        return 0
    from aipacs_runtime import advanced_mpr_runtime_root
    from builder.offline_lumbar_payload import stage_offline_lumbar
    from builder.build_release import find_iscc
    refreshing = args.refresh_wheels
    if refreshing:
        verify(root)
        args.download_wheels = True
    elif (root / "manifest.json").exists():
        raise RuntimeError("Completed cache exists; verify it or choose a fresh root")
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 15 * 1024**3:
        raise RuntimeError("At least 15 GiB free space is required before preparation")
    if not refreshing:
        print("Caching the assembled Slicer runtime without user settings", flush=True)
        snapshot_runtime(advanced_mpr_runtime_root(), root / "slicer-runtime")
        print("Validating and caching the complete offline model environment", flush=True)
        stage_offline_lumbar(root, REPO / "generated-files/offline-lumbar/bundle")
    downloads = root / "downloads"
    downloads.mkdir(exist_ok=True)
    for name in ("python.zip", "vertebrae_mr.zip"):
        shutil.copy2(REPO / "generated-files/offline-lumbar/downloads" / name, downloads / name)
    url = "https://www.python.org/ftp/python/3.13.5/python-3.13.5-amd64.exe"
    target = downloads / "python-3.13.5-amd64.exe"
    if not target.exists():
        print("Downloading the pinned workstation Python installer", flush=True)
        partial = target.with_suffix(".partial")
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output)
        partial.replace(target)
    compiler = find_iscc()
    if compiler is None:
        raise RuntimeError("Inno Setup compiler is missing")
    shutil.copytree(compiler.parent, root / "inno-setup", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("unins*"))
    build_python = REPO / ".venv_build/Scripts/python.exe"
    expression = ("import importlib.metadata as m; "
                  "print('\\n'.join(sorted(d.metadata['Name']+'=='+d.version for d in m.distributions())))")
    freeze = subprocess.check_output([str(build_python), "-c", expression], text=True)
    build_lock = root / "build-environment.lock"
    build_lock.write_text(freeze, encoding="utf-8")
    model_python = root / "offline_lumbar/python/python.exe"
    model_lock = root / "model-environment.lock"
    model_lock.write_text(subprocess.check_output([str(model_python), "-c", expression], text=True), encoding="utf-8")
    if args.download_wheels:
        print("Caching all pinned model wheels (Python 3.12, CPU)", flush=True)
        cache_wheels(model_python, model_lock,
                     root / "model-wheels", root / "model-wheel-download.log", model=True)
        print("Caching all pinned workstation/build wheels (Python 3.13, x64)", flush=True)
        cache_wheels(build_python, build_lock, root / "build-wheels", root / "build-wheel-download.log")
    records = []
    for path in sorted(root.rglob("*")):
        if (path.is_file() and path != root / "manifest.json" and
                path.suffix not in {".log", ".pyc", ".pyo"} and "__pycache__" not in path.parts):
            records.append({"path": path.relative_to(root).as_posix(), "size": path.stat().st_size, "sha256": digest(path)})
    manifest = {"format_version": 1, "platform": "win_amd64", "arm_package": "x64_on_arm64",
                "model": "vertebrae_mr", "model_weights_included": True,
                "wheels_cached": args.download_wheels, "python_installer_source": url,
                "offline_wheel_resolution_verified": args.download_wheels,
                "runtime_source": "assembled custom Slicer ae061ac; workstation settings excluded",
                "release_approved": False, "files": records}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset_cache": str(root), "files": len(records), "bytes": sum(x["size"] for x in records)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
