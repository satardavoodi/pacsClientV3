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
DEFAULT_ROOT = REPO / "generated-files/distribution-assets-native-3.6.7-vc143-20260923"
RUNTIME_ITEMS = ("AIPacsAdvancedViewer.exe", "AIPacsAdvancedViewerLauncherSettings.ini",
                 "bin", "deps", "lib", "python-install", "share", "Logo.png", "LogoFull.png", "SplashScreen.png",
                 "aipacs-native-build.json")


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


def verify(root, *, profile="all"):
    if profile not in {"all", "client"}:
        raise ValueError("Unknown distribution asset verification profile")
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1 or manifest.get("platform") != "win_amd64":
        raise ValueError("Unsupported distribution asset manifest")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 150000:
        raise ValueError("Invalid asset inventory")
    required = {"slicer-runtime/AIPacsAdvancedViewer.exe", "slicer-runtime/aipacs-native-build.json", "inno-setup/ISCC.exe",
                "downloads/python-3.13.5-amd64.exe", "build-environment.lock"}
    if profile == "all":
        required.update({"offline_lumbar/manifest.json", "offline_lumbar/python/python.exe"})
    seen = set()
    for item in files:
        name = item["path"]
        if name in seen or Path(name).as_posix() != name or ".." in Path(name).parts or ":" in name:
            raise ValueError("Unsafe or duplicate asset path")
        seen.add(name)
        if profile == "client" and name.startswith("offline_lumbar/"):
            continue
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


def reuse_non_slicer_assets(donor, destination):
    """Copy only hash-verified, inventoried non-Slicer inputs from a complete cache.

    The donor's native viewer is intentionally never copied: the new cache always
    snapshots the current Developer Run runtime and records its provenance.
    """
    donor = Path(donor).resolve()
    destination = Path(destination).resolve()
    if donor == destination or destination.is_relative_to(donor):
        raise ValueError("The new asset cache must be separate from its donor")
    manifest = json.loads((donor / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("format_version") != 1 or manifest.get("platform") != "win_amd64"
            or not manifest.get("model_weights_included")):
        raise ValueError("Donor must be a complete Windows Server asset cache")
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > 150000:
        raise ValueError("Invalid donor asset inventory")
    required = {"inno-setup/ISCC.exe", "downloads/python-3.13.5-amd64.exe",
                "build-environment.lock", "offline_lumbar/manifest.json",
                "offline_lumbar/python/python.exe"}
    seen = set()
    for item in files:
        name = item["path"]
        relative = Path(name)
        if (name in seen or relative.is_absolute() or relative.as_posix() != name
                or ".." in relative.parts or ":" in name):
            raise ValueError("Unsafe or duplicate donor asset path")
        seen.add(name)
        if name.startswith("slicer-runtime/"):
            continue
        source = (donor / relative).resolve()
        if not source.is_relative_to(donor) or not source.is_file():
            raise ValueError("Donor asset missing or outside cache: " + name)
        if source.stat().st_size != item["size"] or digest(source) != item["sha256"]:
            raise ValueError("Donor asset hash mismatch: " + name)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if target.stat().st_size != item["size"] or digest(target) != item["sha256"]:
            raise ValueError("Copied asset hash mismatch: " + name)
    if not required.issubset(seen):
        raise ValueError("Donor cache lacks required non-Slicer build inputs")
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
    parser.add_argument("--profile", choices=("all", "client"), default="all",
                        help="Client caches omit Eagle Eye server models and their download inputs")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--download-wheels", action="store_true")
    parser.add_argument("--refresh-wheels", action="store_true",
                        help="Verify a completed cache, refresh its locked wheels, and rebuild the inventory")
    parser.add_argument("--reuse-non-slicer-assets", type=Path,
                        help="Copy verified non-Slicer inputs from a complete old cache; snapshot current Slicer")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.check:
        manifest = verify(root, profile=args.profile)
        print(json.dumps({"verified_files": len(manifest["files"]), "bytes": sum(r["size"] for r in manifest["files"])}))
        return 0
    from aipacs_runtime import advanced_mpr_runtime_root
    from builder.offline_lumbar_payload import stage_offline_lumbar
    from builder.build_release import find_iscc
    from builder.slicer_runtime_payload import verify_native_build_provenance
    refreshing = args.refresh_wheels
    if args.reuse_non_slicer_assets and (args.profile != "all" or refreshing or args.download_wheels):
        parser.error("Reuse requires --profile all and cannot refresh or download wheels")
    if refreshing:
        verify(root, profile=args.profile)
        args.download_wheels = True
    elif (root / "manifest.json").exists():
        raise RuntimeError("Completed cache exists; verify it or choose a fresh root")
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 15 * 1024**3:
        raise RuntimeError("At least 15 GiB free space is required before preparation")
    donor_manifest = None
    if not refreshing:
        if args.reuse_non_slicer_assets:
            if any(root.iterdir()):
                raise RuntimeError("Reused asset cache destination must be empty")
            print("Copying hash-verified non-Slicer inputs from donor cache", flush=True)
            donor_manifest = reuse_non_slicer_assets(args.reuse_non_slicer_assets, root)
        print("Caching the assembled Slicer runtime without user settings", flush=True)
        slicer_runtime = advanced_mpr_runtime_root()
        verify_native_build_provenance(REPO, slicer_runtime)
        snapshot_runtime(slicer_runtime, root / "slicer-runtime")
        if args.profile == "all" and donor_manifest is None:
            print("Validating and caching the complete offline model environment", flush=True)
            stage_offline_lumbar(root, REPO / "generated-files/offline-lumbar/bundle")
    url = "https://www.python.org/ftp/python/3.13.5/python-3.13.5-amd64.exe"
    if donor_manifest is None:
        downloads = root / "downloads"
        downloads.mkdir(exist_ok=True)
        if args.profile == "all":
            for name in ("python.zip", "vertebrae_mr.zip"):
                shutil.copy2(REPO / "generated-files/offline-lumbar/downloads" / name, downloads / name)
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
        if args.profile == "all":
            model_python = root / "offline_lumbar/python/python.exe"
            model_lock = root / "model-environment.lock"
            model_lock.write_text(subprocess.check_output([str(model_python), "-c", expression], text=True), encoding="utf-8")
        if args.download_wheels:
            if args.profile == "all":
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
                "model": "vertebrae_mr" if args.profile == "all" else None,
                "model_weights_included": args.profile == "all",
                "wheels_cached": donor_manifest.get("wheels_cached", False) if donor_manifest else args.download_wheels,
                "python_installer_source": donor_manifest.get("python_installer_source", url) if donor_manifest else url,
                "offline_wheel_resolution_verified": (donor_manifest.get("offline_wheel_resolution_verified", False)
                                                       if donor_manifest else args.download_wheels and args.profile == "all"),
                "runtime_source": "current Developer Run native Slicer with verified provenance; workstation settings excluded",
                "release_approved": False, "files": records}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset_cache": str(root), "files": len(records), "bytes": sum(x["size"] for x in records)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
