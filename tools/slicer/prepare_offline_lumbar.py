"""Developer-only preparation of a portable CPU inference bundle; never run on installation.

Network access occurs here, on the build machine. Inference never invokes pip or this tool.
An existing output is refused; retain the wheel cache and manifest for reproducibility.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

REPO = Path(__file__).resolve().parents[2]
MODEL_URL = ("https://github.com/wasserth/TotalSegmentator/releases/download/"
             "v2.5.0-weights/Dataset756_mri_vertebrae_1076subj.zip")
PYTHON_URL = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"


def download(url, target):
    if not target.exists():
        partial = target.with_suffix(target.suffix + ".partial")
        if url == MODEL_URL:
            # Bounded ranges avoid gateways that stall on one large response.
            total, chunk_size = 230791939, 4 * 1024 * 1024
            def fetch(offset):
                end = min(offset + chunk_size, total) - 1
                part = target.parent / f"model-part-{offset}.bin"
                if part.exists() and part.stat().st_size == end - offset + 1:
                    return part
                request = urllib.request.Request(url + f"?aipacs_chunk={offset}",
                                                 headers={"Range": f"bytes={offset}-{end}"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    if response.status != 206 or response.headers.get("Content-Range") != f"bytes {offset}-{end}/{total}":
                        raise RuntimeError("Unexpected model range response")
                    data = response.read(end - offset + 2)
                if len(data) != end - offset + 1:
                    raise RuntimeError("Incomplete model range")
                part.write_bytes(data)
                return part
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                parts = list(pool.map(fetch, range(0, total, chunk_size)))
            with partial.open("wb") as output:
                for part in parts:
                    with part.open("rb") as stream:
                        shutil.copyfileobj(stream, output)
        else:
            with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
        partial.replace(target)
    with target.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(archive, destination):
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            target = (destination / info.filename).resolve()
            if not target.is_relative_to(destination) or ":" in info.filename or "\\" in info.filename:
                raise ValueError("Unsafe archive member")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive links are not allowed")
        zipped.extractall(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPO / "generated-files/offline-lumbar/bundle")
    parser.add_argument("--resume", action="store_true", help="Resume this tool's incomplete staging directory")
    args = parser.parse_args()
    output = args.output.resolve()
    marker = output / ".preparing"
    if output.exists() and (not args.resume or not marker.is_file()):
        raise RuntimeError("Output exists; choose a new directory or resume an incomplete preparation")
    output.mkdir(parents=True, exist_ok=True)
    marker.write_text("AI-PACS offline lumbar preparation\n", encoding="utf-8")
    cache = output.parent / "downloads"
    cache.mkdir(exist_ok=True)
    sources = {}
    source_lock = json.loads((REPO / "tools/slicer/offline_lumbar_sources.json").read_text(encoding="utf-8"))
    for name, url in (("python.zip", PYTHON_URL), ("vertebrae_mr.zip", MODEL_URL)):
        print("Obtaining " + name, flush=True)
        sources[name] = {"url": url, "sha256": download(url, cache / name)}
        if sources[name]["sha256"] != source_lock[name]:
            raise RuntimeError("Downloaded source archive hash does not match the reviewed lock")
    python_root = output / "python"
    if not (python_root / "python.exe").exists():
        extract(cache / "python.zip", python_root)
    (python_root / "python312._pth").write_text(
        "python312.zip\n.\nLib/site-packages\nimport site\n", encoding="utf-8")
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PIP_CACHE_DIR"] = str(cache / "pip")
    pip = [sys.executable, "-m", "pip", "--python", str(python_root / "python.exe")]
    lock = REPO / "tools/slicer/offline_lumbar_requirements.lock"
    constraints = ["--constraint", str(lock)] if lock.exists() else []
    def install(*arguments):
        subprocess.run(pip + ["install", "--no-warn-script-location", *constraints, *arguments],
                       env=env, check=True)
    install("--index-url", "https://download.pytorch.org/whl/cpu", "--no-deps", "torch==2.6.0")
    install("setuptools==80.9.0", "wheel==0.45.1")
    install("TotalSegmentator==2.14.0", "nnunetv2==2.6.2", "numpy==2.2.6", "torch==2.6.0")
    subprocess.run(pip + ["check"], env=env, check=True)
    freeze = subprocess.check_output(pip + ["freeze", "--all"], env=env, text=True)
    (output / "requirements-resolved.txt").write_text(freeze, encoding="utf-8")
    weights = output / "weights"
    if not (weights / "Dataset756_mri_vertebrae_1076subj").exists():
        extract(cache / "vertebrae_mr.zip", weights)
    source = REPO / "modules/ai_imaging/offline_lumbar"
    if not source.exists():
        raise RuntimeError("Offline adapter source is missing")
    shutil.copytree(source, output / "app/offline_lumbar", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    notices = output / "licenses"
    notices.mkdir(exist_ok=True)
    for directory in (python_root / "Lib/site-packages").glob("*.dist-info"):
        for item in directory.rglob("*"):
            if item.is_file() and any(word in item.name.lower() for word in ("license", "notice", "copying")):
                target = notices / directory.name / item.relative_to(directory)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    notice = (
        "TotalSegmentator 2.14.0, vertebrae_mr (Dataset756).\n"
        "Upstream lists this task under Apache-2.0 open-use models.\n"
        "Source: https://github.com/wasserth/TotalSegmentator\n"
        "Anatomy assistance only. Not independently validated for clinical diagnosis.\n"
        "CPU package; CUDA is not required or bundled.\n"
    )
    (notices / "MODEL-NOTICE.txt").write_text(notice, encoding="utf-8")
    records = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc" and path != marker:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            records.append({"path": path.relative_to(output).as_posix(),
                            "size": path.stat().st_size, "sha256": digest})
    manifest = {"format_version": 1, "bundle_id": "vertebrae-mr-cpu-2.14.0",
                "task": "vertebrae_mr", "engine_version": "2.14.0", "python_version": "3.12.10",
                "platform": "win_amd64", "device": "cpu", "network_required": False,
                "source_archives": sources, "files": records}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    marker.unlink()
    print(json.dumps({"bundle": str(output), "files": len(records),
                      "bytes": sum(item["size"] for item in records)}), flush=True)


if __name__ == "__main__":
    main()
