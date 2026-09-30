"""Cancellable local geometry worker; never import scene or Qt objects here."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import time

import numpy as np


def run_isolated(python, mask, affine, endpoints, manual, cancel, timeout=1800):
    """Called off the GUI thread. Cancellation terminates only the owned child."""
    with tempfile.TemporaryDirectory(prefix="aipacs-lumen-") as directory:
        root = Path(directory)
        if cancel.is_set():
            raise InterruptedError("Analysis cancelled")
        np.save(root / "mask.npy", mask, allow_pickle=False)
        np.save(root / "affine.npy", affine, allow_pickle=False)
        np.save(root / "endpoints.npy", endpoints, allow_pickle=False)
        if manual is not None:
            np.save(root / "manual.npy", manual, allow_pickle=False)
        command = [str(python), str(Path(__file__).with_name("worker.py")), str(root)]
        options = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            options["startupinfo"] = startup
        process = subprocess.Popen(command, **options)
        job = None
        try:
            if os.name == "nt":
                spec = importlib.util.spec_from_file_location(
                    "aipacs_lumen_owned_process", Path(__file__).resolve().parents[2] / "owned_process.py")
                ownership = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(ownership)
                job = ownership.ProcessJob()
                job.assign(process)
            started = time.monotonic()
            while process.poll() is None:
                if cancel.wait(.05):
                    raise InterruptedError("Analysis cancelled")
                if time.monotonic() - started > timeout:
                    raise TimeoutError("Lumen analysis exceeded its time limit. Crop the region and retry.")
            if cancel.is_set():
                raise InterruptedError("Analysis cancelled")
            receipt = root / "result.json"
            if not receipt.is_file():
                raise RuntimeError("The geometry worker exited without a result")
            metadata = json.loads(receipt.read_text(encoding="utf-8"))
            if process.returncode or not metadata.get("ok"):
                raise RuntimeError(metadata.get("error", "Geometry computation failed"))
            import vtk
            reader = vtk.vtkXMLPolyDataReader()
            reader.SetFileName(str(root / "surface.vtp"))
            reader.Update()
            surface = vtk.vtkPolyData()
            surface.DeepCopy(reader.GetOutput())
            result = {key: np.load(root / (key + ".npy"), allow_pickle=False)
                      for key in ("points", "distance", "tangents", "ups", "area", "diameter")}
            result["surface"] = surface
            return result
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            if job is not None:
                job.close()
