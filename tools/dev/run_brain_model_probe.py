"""Patient-free inference smoke test. Does not measure clinical accuracy."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main():
    import numpy as np
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain.runtime import bundle_root, run_process
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-v1", action="store_true", help="Engine-only test with upstream's included v1 weights; never a v2 fallback")
    args = parser.parse_args()
    root = bundle_root()
    probes = root / "probes"
    probes.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="model-smoke-", dir=probes))
    z, y, x = np.mgrid[:128, :128, :128]
    radius = ((x - 64) / 44)**2 + ((y - 64) / 53)**2 + ((z - 64) / 49)**2
    array = np.zeros(radius.shape, dtype=np.float32)
    array[radius < 1.1] = 35
    array[radius < 1] = 70
    array[radius < 0.7] = 110
    array[((x - 64) / 8)**2 + ((y - 64) / 15)**2 + ((z - 67) / 8)**2 < 1] = 20
    array += np.random.default_rng(1729).uniform(0, 2, array.shape).astype(np.float32)
    image = sitk.GetImageFromArray(array)
    sitk.WriteImage(image, str(job / "t1.nii.gz"))
    if args.legacy_v1:
        command = [root / "runtime/Scripts/python.exe", "-B", root / "SynthSeg/scripts/commands/SynthSeg_predict.py",
                   "--i", job / "t1.nii.gz", "--o", job / "labels.nii.gz", "--v1", "--cpu", "--threads", "2"]
        run_process(command, job, threading.Event(), timeout=600)
        labels = sitk.GetArrayFromImage(sitk.ReadImage(str(job / "labels.nii.gz")))
        allowed = np.load(root / "SynthSeg/data/labels_classes_priors/synthseg_segmentation_labels.npy", allow_pickle=False)
        assert labels.shape == array.shape and np.isfinite(labels).all()
        assert set(np.unique(labels)).issubset(set(allowed))
        result = {"passed": True, "scope": "SynthSeg 1 engine smoke only; not the Brain v2 workflow",
                  "clinical_validation": "not_established", "label_count": len(np.unique(labels))}
    else:
        from modules.ai_imaging.eagle_eye_brain.service import run_analysis
        result = run_analysis(job / "t1.nii.gz", None, job / "workflow", bundle=root)
        result = {"passed": True, "scope": "Synthetic v2 full pipeline only", "clinical_validation": "not_established",
                  "artifact_directory": result["artifact_directory"]}
    (job / "probe.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(dict(result, evidence=str(job / "probe.json"))))


if __name__ == "__main__":
    main()
