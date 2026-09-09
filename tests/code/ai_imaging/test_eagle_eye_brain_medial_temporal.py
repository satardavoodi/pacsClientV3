"""Synthetic medial temporal evidence guards; no diagnostic inference."""
import json
import pytest
from modules.ai_imaging.eagle_eye_brain.medial_temporal import focus_rows, section_html


def test_missing_side_not_zero_and_asymmetry_sign_matches_general_report():
    rows = [{"structure": name, "volume_cm3": value} for name, value in
            [("total intracranial", 1500), ("left hippocampus", 3), ("right hippocampus", 4),
             ("ctx-lh-entorhinal", 2)]]
    result = focus_rows({"posterior_rows": rows})
    assert result[0]["asymmetry_percent"] == pytest.approx(200 / 7)
    assert result[0]["left_icv_percent"] == pytest.approx(.2)
    assert result[1]["right_cm3"] is None and result[1]["asymmetry_percent"] is None
    html = section_html({"posterior_rows": rows})
    assert "Right: not rated; Left: not rated" in html
    assert "does not establish Alzheimer's disease" in html
    assert "not a measured temporal-horn width" in html


def test_hippocampal_images_are_local_and_do_not_change_labels(tmp_path):
    import base64
    import numpy as np
    import SimpleITK as sitk
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QFontDatabase
    from modules.ai_imaging.eagle_eye_brain.report_evidence import segmentation_png
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/arial.ttf")
    array = np.arange(1000, dtype=np.float32).reshape(10, 10, 10)
    labels = np.zeros_like(array, dtype=np.uint16)
    labels[3:7, 1:9, 2:4] = 17
    labels[3:7, 1:9, 6:8] = 53
    for name, value in (("resampled", array), ("labels", labels)):
        sitk.WriteImage(sitk.GetImageFromArray(value), str(tmp_path / (name + ".nii.gz")))
    names = tmp_path / "label_names.json"
    names.write_text(json.dumps({"17": "left hippocampus", "53": "right hippocampus"}))
    before = (tmp_path / "labels.nii.gz").read_bytes()
    png = segmentation_png(tmp_path, medial_temporal=True)
    assert not QImage.fromData(base64.b64decode(png)).isNull()
    assert (tmp_path / "labels.nii.gz").read_bytes() == before
    names.write_text(json.dumps({"17": "other structure", "53": "another structure"}))
    assert segmentation_png(tmp_path, medial_temporal=True) is None
