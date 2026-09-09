"""One offline inference job in its own portable Python process.

Only a job-owned directory is accepted. Input is an immutable KJI array and RAS
affine; output is a same-grid labelmap and local provenance. No DICOM identities.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

NETWORK_ATTEMPTS = []

def deny_network(event, arguments):
    # Also installed when multiprocessing imports this script in spawned workers.
    # This is a Python network guard, not an OS sandbox for arbitrary native code.
    if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.bind"}:
        if len(NETWORK_ATTEMPTS) < 100:
            NETWORK_ATTEMPTS.append(event)
        raise PermissionError("Network access is disabled for offline lumbar inference")


sys.addaudithook(deny_network)


def run(bundle, job, *, preflight=False):
    sys.path.insert(0, str(bundle / "app"))
    from offline_lumbar.bundle import validate_bundle
    manifest = validate_bundle(bundle)
    state = job / "engine-state"
    state.mkdir(exist_ok=True)
    (state / "config.json").write_text(json.dumps({
        "totalseg_id": "offline", "send_usage_stats": False,
        "prediction_counter": 0, "statistics_disclaimer_shown": True,
    }), encoding="utf-8")
    os.environ.update(TOTALSEG_HOME_DIR=str(state), TOTALSEG_WEIGHTS_PATH=str(bundle / "weights"),
                      HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1",
                      OMP_NUM_THREADS="4", MKL_NUM_THREADS="4",
                      TEMP=str(job), TMP=str(job), nnUNet_compile="false")
    import importlib.metadata
    import numpy as np
    import nibabel as nib
    import torch
    from totalsegmentator.python_api import totalsegmentator
    from totalsegmentator.map_to_binary import class_map
    if importlib.metadata.version("TotalSegmentator") != "2.14.0":
        raise ValueError("Unexpected inference engine version")
    if preflight:
        return {"status": "ready", "bundle_id": manifest["bundle_id"], "device": "cpu",
                "torch_version": torch.__version__, "network_guard": "python-audit",
                "blocked_network_attempts": len(NETWORK_ATTEMPTS),
                "model_inference_executed": False}
    request = json.loads((job / "request.json").read_text(encoding="utf-8"))
    if set(request) != {"format_version", "modality", "affine_ras", "source_token"}:
        raise ValueError("Invalid inference request fields")
    if request["format_version"] != 1 or request["modality"] != "MR":
        raise ValueError("Only MR snapshot requests are supported")
    token = request["source_token"]
    if not isinstance(token, str) or len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Invalid source token")
    array = np.load(job / "input.npy", allow_pickle=False, mmap_mode="r")
    if (array.ndim != 3 or array.dtype.kind not in "iuf" or min(array.shape) < 2
            or array.size > 256 * 1024 * 1024 or not np.isfinite(array).all()):
        raise ValueError("Invalid or oversized volume")
    affine = np.asarray(request["affine_ras"], dtype=float)
    if (affine.shape != (4, 4) or not np.isfinite(affine).all()
            or not np.allclose(affine[3], [0, 0, 0, 1])
            or abs(np.linalg.det(affine[:3, :3])) < 1e-8):
        raise ValueError("Invalid reference geometry")
    original = nib.Nifti1Image(np.asarray(array, dtype=np.float32).transpose(2, 1, 0), affine)
    result = totalsegmentator(
        original, output=None, ml=True, task="vertebrae_mr", device="cpu",
        fast=False, fastest=False, preview=False, statistics=False, radiomics=False,
        nr_thr_resamp=1, nr_thr_saving=1, quiet=True, skip_saving=True,
    )
    if result.shape != original.shape or not np.allclose(result.affine, affine, atol=1e-4):
        raise ValueError("Model output geometry does not match source")
    labels = np.asanyarray(result.dataobj)
    mapping = class_map["vertebrae_mr"]
    if not np.isin(labels, [0, *mapping]).all():
        raise ValueError("Model output contains unsupported labels")
    labels_kji = labels.transpose(2, 1, 0).astype(np.uint8)
    np.save(job / "labels.npy", labels_kji, allow_pickle=False)
    nib.save(nib.Nifti1Image(labels.astype(np.uint8), affine), job / "segmentation.nii.gz")
    volume_per_voxel = abs(float(np.linalg.det(affine[:3, :3])))
    measurements = []
    for label, name in mapping.items():
        count = int(np.count_nonzero(labels == label))
        if count:
            measurements.append({"label": label, "name": name, "voxels": count,
                                 "volume_mm3": count * volume_per_voxel})
    return {"status": "succeeded", "bundle_id": manifest["bundle_id"], "task": "vertebrae_mr",
            "source_token": token, "shape_kji": list(array.shape), "affine_ras": affine.tolist(),
            "segments": measurements, "labels_file": "labels.npy",
            "nifti_file": "segmentation.nii.gz", "network_required": False,
            "blocked_network_attempts": len(NETWORK_ATTEMPTS),
            "clinical_validation": "not_established", "diagnosis": None,
            "warning": "Anatomy segmentation only; absence of a label is not absence of disease"}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    bundle = Path(__file__).resolve().parents[2]
    job = args.job.resolve(strict=True)
    if not job.is_dir() or job.is_relative_to(bundle):
        raise ValueError("Job directory must be outside the immutable bundle")
    output = job / "result.json"
    if output.exists():
        raise ValueError("Job has already completed")
    try:
        result = run(bundle, job, preflight=args.preflight)
    except Exception as exc:
        # Do not expose image paths, patient data, or upstream diagnostic output.
        result = {"status": "failed", "error_type": type(exc).__name__,
                  "message": "Offline analysis failed; check bundle integrity, input geometry, and memory"}
    temporary = job / "result.partial.json"
    temporary.write_text(json.dumps(result, indent=2), encoding="utf-8")
    temporary.replace(output)
    return 0 if result["status"] in ("succeeded", "ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
