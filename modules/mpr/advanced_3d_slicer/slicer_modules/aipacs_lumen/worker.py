"""Private local worker entry point, launched by process.run_isolated."""
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import vtk
from aipacs_lumen.backend import analyze


def main(root):
    try:
        arrays = {key: np.load(root / (key + ".npy"), allow_pickle=False)
                  for key in ("mask", "affine", "endpoints")}
        manual = np.load(root / "manual.npy", allow_pickle=False) if (root / "manual.npy").is_file() else None
        result = analyze(arrays["mask"], arrays["affine"], arrays["endpoints"], manual, threading.Event())
        writer = vtk.vtkXMLPolyDataWriter()
        writer.SetFileName(str(root / "surface.vtp"))
        writer.SetInputData(result.pop("surface"))
        if not writer.Write():
            raise RuntimeError("Could not save the computed lumen surface")
        for key, array in result.items():
            np.save(root / (key + ".npy"), array, allow_pickle=False)
        metadata = {"ok": True}
    except Exception as exc:
        metadata = {"ok": False, "error": str(exc)}
    (root / "result.json").write_text(json.dumps(metadata), encoding="utf-8")
    return 0 if metadata["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
