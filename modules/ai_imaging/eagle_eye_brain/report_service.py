"""Regenerate a completed local job's report without rerunning segmentation."""
import json
from pathlib import Path
import tempfile

from .contracts import BrainError
from .normative import reference_assessment
from .runtime import sha256


def regenerate_report(result_path, output_root, *, demographics=None, reference_id="volbrain", cancel=None, dicom_source=None):
    """Worker-only operation. Preserve the original measurement job and its demographics."""
    if cancel is not None and cancel.is_set():
        raise BrainError("Report generation cancelled.")
    assessment = reference_assessment(demographics, reference_id)
    path = Path(result_path).resolve()
    directory = path.parent
    if path.name != "result.json" or (directory / "FAILED").exists():
        raise BrainError("Choose result.json from a completed brain measurement job.")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        if (result.get("status") != "review_required" or result.get("model") != "SynthSeg 2.0"
                or not result.get("posterior_rows") or not (directory / "labels.nii.gz").is_file()
                or sha256(directory / "t1.nii.gz") != result["source_sha256"]):
            raise ValueError("Invalid job")
    except (OSError, ValueError, KeyError):
        raise BrainError("The selected measurement job is incomplete or its source image has changed.") from None
    from .patient_context import dicom_context, demographics_for_report, require_same_examination
    context = result.get("patient_context", {})
    if dicom_source:
        import numpy as np
        import SimpleITK as sitk
        from .images import read_volume
        original = read_volume(dicom_source)
        staged = sitk.ReadImage(str(directory / "t1.nii.gz"))
        if (original.GetSize() != staged.GetSize()
                or any(not np.allclose(getattr(original, key)(), getattr(staged, key)(), atol=1e-4)
                       for key in ("GetOrigin", "GetSpacing", "GetDirection"))
                or not np.array_equal(sitk.GetArrayFromImage(original), sitk.GetArrayFromImage(staged))):
            raise BrainError("Selected DICOM pixels or geometry do not match this completed analysis.")
        selected_context = dicom_context(dicom_source)
        require_same_examination(context, selected_context)
        context = selected_context
    result["patient_context"] = context
    assessment = reference_assessment(demographics_for_report(context, demographics), reference_id)
    from .report import report_html, write_pdf
    from .report_evidence import segmentation_png
    result["normative"] = assessment
    result["normative_status"] = "No qualified reference model installed"
    for row in result["posterior_rows"]:
        row.update(percentile=None, z_score=None, t_score=None,
                   normative_status="No qualified reference model installed")
    result["report_evidence_png"] = segmentation_png(directory)
    result["medial_temporal_evidence_png"] = segmentation_png(directory, medial_temporal=True)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="report-", dir=root))
    try:
        if reference_id == 'volbrain':
            from .volbrain_reference import attach_reference
            attach_reference(result, directory, demographics_for_report(context, demographics))
        html = report_html(result)
        (destination / "report.html").write_text(html, encoding="utf-8")
        write_pdf(html, destination / "report.pdf")
        if cancel is not None and cancel.is_set():
            raise BrainError("Report generation cancelled.")
        result["pdf_available"] = (destination / "report.pdf").is_file()
        if not result["pdf_available"]:
            raise BrainError("PDF generation did not complete.")
        result["report_source_job"] = result["job_id"]
        (destination / "report_result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
        result["artifact_directory"] = str(destination)
        return result
    except Exception:
        (destination / "FAILED").write_text("Report generation did not complete.\n", encoding="utf-8")
        raise
