"""Synthetic reference applicability, report arithmetic and image isolation."""
import base64
import math

import numpy as np
import pytest

from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
from modules.ai_imaging.eagle_eye_brain.normative import BrainDemographics, REFERENCES, reference_assessment
from modules.ai_imaging.eagle_eye_brain.report import bilateral_rows, report_html


@pytest.mark.parametrize("age", [True, "46", -1, 121, math.nan, math.inf])
def test_invalid_demographic_age_rejected(age):
    with pytest.raises(BrainError):
        BrainDemographics(age, "female")


@pytest.mark.parametrize("reference", [r.id for r in REFERENCES])
def test_published_candidate_never_qualifies_synthseg_by_name(reference):
    result = reference_assessment(BrainDemographics(46, "male"), reference)
    assert not result["qualified"] and result["curves"] == []
    assert all(result[key] is None for key in ("z_score", "t_score", "percentile", "brain_age"))
    assert result["status"] == "unavailable" and result["reasons"]


def test_missing_and_out_of_domain_context_not_imputed():
    missing = reference_assessment()
    assert missing["demographics"] == {"age_years": None, "sex": "unknown"}
    outside = reference_assessment(BrainDemographics(95, "female"), "volbrain")
    assert any("outside" in reason for reason in outside["reasons"])
    with pytest.raises(BrainError):
        reference_assessment(reference_id="invented")


@pytest.mark.parametrize("age", [10, 14.9, 15, 17.7, 22])
def test_published_reference_preserves_actual_age(age):
    result = reference_assessment(BrainDemographics(age, "female"), "volbrain")
    assert result["demographics"]["age_years"] == age
    assert not result["qualified"] and result["z_score"] is None


def test_bilateral_units_sign_and_zero_denominator():
    rows = [{"structure": key, "volume_cm3": value} for key, value in
            [("total intracranial", 1500), ("left hippocampus", 9), ("right hippocampus", 11),
             ("left amygdala", 0), ("right amygdala", 0), ("left unmatched", 4)]]
    pairs = {row["structure"]: row for row in bilateral_rows(rows)}
    assert set(pairs) == {"hippocampus", "amygdala"}
    assert pairs["hippocampus"]["asymmetry_percent"] == pytest.approx(20)
    assert pairs["hippocampus"]["icv_percent"] == pytest.approx(20 / 1500 * 100)
    assert pairs["amygdala"]["asymmetry_percent"] is None


def test_reference_in_report_preserves_context_without_scores():
    result = {"posterior_rows": [], "binary_rows": [], "flair_status": "Not supplied",
              "qc_scores": {}, "model_revision": "synthetic",
              "normative": reference_assessment(BrainDemographics(42.5, "female"), "volbrain"),
              "report_evidence_png": "https://invalid.example/patient.png"}
    html = report_html(result)
    assert "42.5 years" in html and "female" in html and "volBrain" in html
    assert "Cross-method validation pending" in html and "invalid.example" not in html
    assert "T-score and age curves: unavailable" in html


def test_ui_demographics_default_to_unknown_and_do_not_start_io():
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    app = QApplication.instance() or QApplication([])
    widget = BrainVolumetryWidget()
    assert widget._demographics() == BrainDemographics()
    widget.age.setValue(46)
    widget.sex.setCurrentIndex(2)
    assert widget.reference.currentData() == 'volbrain'
    assert widget.reference.findData('centilebrain') == -1
    assert widget.reference_status.text()
    assert widget._future is None and not widget.pdf.isEnabled()
    widget._executor.shutdown(wait=False, cancel_futures=True)
    widget.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("failure", [None, "source_changed", "pdf_failed"])
def test_report_regeneration_preserves_measurements_and_rejects_partial_jobs(tmp_path, monkeypatch, failure):
    import json
    from modules.ai_imaging.eagle_eye_brain import report, report_evidence
    from modules.ai_imaging.eagle_eye_brain.report_service import regenerate_report
    from modules.ai_imaging.eagle_eye_brain.runtime import sha256
    job = tmp_path / "measurement"
    job.mkdir()
    (job / "t1.nii.gz").write_bytes(b"synthetic source")
    (job / "labels.nii.gz").write_bytes(b"synthetic labels")
    original = {"status": "review_required", "model": "SynthSeg 2.0", "job_id": "synthetic",
                "source_sha256": sha256(job / "t1.nii.gz"), "model_revision": "synthetic",
                "posterior_rows": [{"structure": "left hippocampus", "volume_cm3": 3,
                                    "volume_mm3": 3000}], "binary_rows": [],
                "qc_scores": {}, "flair_status": "Not supplied"}
    path = job / "result.json"
    path.write_text(json.dumps(original))
    before = path.read_bytes()
    monkeypatch.setattr(report_evidence, "segmentation_png", lambda directory, **kwargs: None)
    def write(html, target):
        if failure == "pdf_failed":
            raise RuntimeError("Synthetic failure")
        target.write_bytes(b"synthetic PDF")
    monkeypatch.setattr(report, "write_pdf", write)
    if failure == "source_changed":
        (job / "t1.nii.gz").write_bytes(b"different source")
    output = tmp_path / "reports"
    if failure:
        with pytest.raises((BrainError, RuntimeError)):
            regenerate_report(path, output)
        assert not list(output.glob("*/report_result.json"))
    else:
        result = regenerate_report(path, output, demographics=BrainDemographics(52, "female"), reference_id="none")
        assert result["normative"]["demographics"] == {"age_years": 52, "sex": "female"}
        assert result["posterior_rows"][0]["volume_cm3"] == 3
        assert result["posterior_rows"][0]["percentile"] is None
        assert result["pdf_available"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("oblique", [False, True])
def test_evidence_embeds_png_and_preserves_original_geometry(tmp_path, oblique):
    import SimpleITK as sitk
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase, QImage, QTextDocument
    from PySide6.QtCore import QUrl
    from modules.ai_imaging.eagle_eye_brain.report_evidence import segmentation_png
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/arial.ttf")
    image = sitk.GetImageFromArray(np.arange(960, dtype=np.float32).reshape(8, 10, 12))
    if oblique:
        angle = .2
        image.SetDirection((math.cos(angle), -math.sin(angle), 0,
                            math.sin(angle), math.cos(angle), 0, 0, 0, 1))
    labels = sitk.Cast(image > 400, sitk.sitkUInt16)
    sitk.WriteImage(image, str(tmp_path / "resampled.nii.gz"))
    sitk.WriteImage(labels, str(tmp_path / "labels.nii.gz"))
    before = (tmp_path / "labels.nii.gz").read_bytes()
    png = segmentation_png(tmp_path)
    decoded = base64.b64decode(png, validate=True)
    assert QImage.fromData(decoded).width() == 1050
    assert (tmp_path / "labels.nii.gz").read_bytes() == before
    doc = QTextDocument()
    url = QUrl("data:image/png;base64," + png)
    doc.setHtml('<img src="' + url.toString() + '"/>')
    assert doc.resource(QTextDocument.ResourceType.ImageResource, url) is not None
