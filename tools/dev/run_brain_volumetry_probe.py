"""Exercise the Brain Slicer adapter on a synthetic, oblique labelled volume."""
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
    from modules.ai_imaging.eagle_eye_brain.runtime import run_slicer
    root = REPO / "generated-files/brain-volumetry/probes"
    root.mkdir(parents=True, exist_ok=True)
    job = Path(tempfile.mkdtemp(prefix="synthetic-", dir=root))
    array = np.zeros((12, 24, 32), dtype=np.int16)
    array[2:6, 3:8, 4:10] = 17
    array[7:10, 13:17, 18:23] = 53
    image = sitk.GetImageFromArray(array)
    image.SetSpacing((0.8, 1.2, 1.5))
    image.SetOrigin((12, -9, 4))
    theta = np.deg2rad(23)
    image.SetDirection((np.cos(theta), -np.sin(theta), 0, np.sin(theta), np.cos(theta), 0, 0, 0, 1))
    sitk.WriteImage(image, str(job / "labels.nii.gz"))
    sitk.WriteImage(sitk.Cast(image, sitk.sitkFloat32), str(job / "resampled.nii.gz"))
    (job / "label_names.json").write_text(json.dumps({"17": "left hippocampus", "53": "right hippocampus"}), encoding="utf-8")
    result = run_slicer(job, threading.Event())
    rows = {row["label"]: row for row in result["rows"]}
    assert np.isclose(rows[17]["volume_mm3"], 120 * 1.44, rtol=1e-5)
    assert np.isclose(rows[53]["volume_mm3"], 60 * 1.44, rtol=1e-5)
    assert (job / "brain.seg.nrrd").is_file() and (job / "brain_review.mrb").is_file()
    print(json.dumps({"passed": True, "scope": "Synthetic geometry and Slicer adapter only",
                      "result": str(job / "slicer_result.json"), "rows": result["rows"]}))


if __name__ == "__main__":
    main()
