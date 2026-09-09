"""Prepare a source-development SynthSeg bundle, without modifying the app venv.

Run after the documented isolated Python/environment setup. Models may be copied
from a local FreeSurfer installation with --models, or fetched with --download-models.
Every model must match the official FreeSurfer annex SHA256 at the pinned revision.
This does not build or publish an installer and does not establish clinical accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from modules.ai_imaging.eagle_eye_brain.runtime import SYNTHSEG_REVISION, sha256

FREESURFER_REVISION = "8c1d37cb14593ec06931bbdfea7c955a4b584163"
MODELS = ("synthseg_2.0.h5", "synthseg_robust_2.0.h5", "synthseg_parc_2.0.h5", "synthseg_qc_2.0.h5")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / "generated-files/brain-volumetry")
    parser.add_argument("--models", type=Path, help="Local directory with the four official model files")
    parser.add_argument("--download-models", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    source = root / "SynthSeg"
    interpreter = root / "runtime/Scripts/python.exe"
    if not interpreter.is_file():
        raise RuntimeError("Prepare the isolated Python environment first; see the Brain runbook.")
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != SYNTHSEG_REVISION:
        raise RuntimeError("The SynthSeg source revision does not match the pinned revision.")
    references = {}
    for name in MODELS:
        url = f"https://raw.githubusercontent.com/freesurfer/freesurfer/{FREESURFER_REVISION}/mri_synthseg/{name}"
        with urllib.request.urlopen(url, timeout=30) as response:
            annex = response.read(4096).decode("ascii").strip()
        match = re.search(r"SHA256E-s(\d+)--([a-f0-9]{64})", annex)
        if not match or "/.git/annex/objects/" not in annex:
            raise RuntimeError("Unexpected upstream model reference.")
        size, expected = int(match[1]), match[2]
        destination = source / "models" / name
        if not destination.exists():
            partial = destination.with_suffix(".partial")
            if args.models:
                shutil.copyfile(args.models / name, partial)
            elif args.download_models:
                model_url = "https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/repo/annex.git/" + annex.split("/.git/", 1)[1]
                print("Downloading " + name, flush=True)
                with urllib.request.urlopen(model_url, timeout=30) as response, partial.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
            else:
                raise RuntimeError("Missing model " + name + "; provide --models or --download-models.")
            if partial.stat().st_size != size or sha256(partial) != expected:
                raise RuntimeError("The downloaded model does not match the official checksum.")
            partial.replace(destination)
        if destination.stat().st_size != size or sha256(destination) != expected:
            raise RuntimeError("Model checksum mismatch: " + name)
        references[name] = {"reference": url, "sha256": expected, "bytes": size}
    subprocess.run([str(interpreter), "-c", "import tensorflow,keras,nibabel,h5py; print('Model dependencies import successfully')"], check=True)
    files = {}
    for directory in (source / "SynthSeg", source / "ext", source / "scripts/commands",
                      source / "data/labels_classes_priors", source / "models", root / "runtime"):
        for path in sorted(directory.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files[path.relative_to(root).as_posix()] = sha256(path)
    manifest = {"format_version": 1, "revision": revision, "model_references": references,
                "sha256": files, "clinical_validation": "not_established"}
    temporary = root / "manifest.partial"
    temporary.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    temporary.replace(root / "manifest.json")
    print("Bundle integrity manifest created. Run the synthetic model probe before patient use.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Preparation incomplete: " + type(exc).__name__ + ". See the Brain runbook for prerequisites.", file=sys.stderr)
        raise SystemExit(1)
