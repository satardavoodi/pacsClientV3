"""Blocking service for use only in a background worker, never on a Qt GUI thread."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

from .bundle import validate_bundle


class AnalysisCancelled(RuntimeError):
    pass


def run_snapshot(bundle, work_root, array_kji, affine_ras, *, cancel=None, timeout=1800):
    import numpy as np
    bundle = Path(bundle).resolve()
    # Full model/dependency hashing runs in the standalone worker before import.
    validate_bundle(bundle, bootstrap_only=True)
    root = Path(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="lumbar-", dir=root))
    token = uuid.uuid4().hex
    environment = os.environ.copy()
    for name in list(environment):
        if name.startswith(("PYTHON", "NEWMPR2_", "QT_")):
            environment.pop(name)
    environment.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
    command = [str(bundle / "python/python.exe"), "-I", "-B",
               str(bundle / "app/offline_lumbar/worker.py"), "--job", str(job)]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = None
    try:
        np.save(job / "input.npy", array_kji, allow_pickle=False)
        request = {"format_version": 1, "modality": "MR",
                   "affine_ras": np.asarray(affine_ras).tolist(), "source_token": token}
        (job / "request.json").write_text(json.dumps(request), encoding="utf-8")
        process = subprocess.Popen(command, cwd=job, env=environment, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=flags)
        started = time.monotonic()
        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                raise AnalysisCancelled("Analysis cancelled")
            if time.monotonic() - started > timeout:
                raise TimeoutError("Offline lumbar analysis exceeded its time limit")
            time.sleep(0.1)
        if cancel is not None and cancel.is_set():
            raise AnalysisCancelled("Analysis cancelled")
        result = json.loads((job / "result.json").read_text(encoding="utf-8"))
        if process.returncode or result.get("status") != "succeeded":
            raise RuntimeError("Offline inference failed; verify bundle, input geometry, and available memory")
        if result.get("source_token") != token or result.get("shape_kji") != list(array_kji.shape):
            raise RuntimeError("Analysis result does not belong to this input")
        if not np.allclose(result.get("affine_ras"), affine_ras, atol=1e-4):
            raise RuntimeError("Analysis result geometry mismatch")
        labels = np.load(job / "labels.npy", allow_pickle=False)
        if labels.shape != array_kji.shape or labels.dtype != np.uint8 or labels.max() > 25:
            raise RuntimeError("Invalid output labelmap")
        result["artifact_directory"] = str(job)
        return result, labels
    finally:
        try:
            if process is not None and process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=flags, check=False)
                else:
                    process.terminate()
                process.wait(timeout=15)
        finally:
            # Also clean partial writes and failures before process creation.
            (job / "input.npy").unlink(missing_ok=True)
