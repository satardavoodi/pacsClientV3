"""End-to-end local Brain workflow, intended for one background worker."""
from dataclasses import asdict
import csv
import json
from pathlib import Path
import tempfile
import threading

from .contracts import BrainError, BrainPlan, read_single_subject_csv, volume_rows
from .runtime import bundle_root, validate_bundle, run_process, synthseg_command, run_slicer, sha256

_ANALYSIS_LOCK = threading.Lock()

def run_analysis(t1_path, flair_path, output_root, *, plan=None, cancel=None, progress=None, bundle=None,
                 demographics=None, reference_id="volbrain"):
    if not _ANALYSIS_LOCK.acquire(blocking=False):
        raise BrainError("Another brain analysis is already running. Wait for it to complete.")
    try:
        return _run_analysis(t1_path, flair_path, output_root, plan=plan, cancel=cancel, progress=progress,
                             bundle=bundle, demographics=demographics, reference_id=reference_id)
    finally:
        _ANALYSIS_LOCK.release()


def _run_analysis(t1_path, flair_path, output_root, *, plan=None, cancel=None, progress=None, bundle=None,
                  demographics=None, reference_id="volbrain"):
    import numpy as np
    import SimpleITK as sitk
    from .images import read_volume, register_flair
    plan = plan or BrainPlan()
    cancel = cancel or threading.Event()
    progress = progress or (lambda message: None)
    if cancel.is_set():
        raise BrainError("Brain analysis cancelled.")
    from .normative import reference_assessment
    normative = reference_assessment(demographics, reference_id)
    root = Path(bundle).resolve() if bundle else bundle_root()
    progress("Checking the local model bundle")
    manifest = validate_bundle(root)
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="brain-", dir=output_root))
    try:
        progress("Preparing the selected 3D T1-weighted image")
        t1 = read_volume(t1_path)
        from .patient_context import dicom_context, demographics_for_report, require_same_examination
        patient_context = dicom_context(t1_path)
        normative = reference_assessment(demographics_for_report(patient_context, demographics), reference_id)
        # This v0.1 protocol is explicitly MPRAGE/3D T1w plus 3D FLAIR.
        # Sequence identity and full-head coverage are confirmed by the operator.
        if max(t1.GetSpacing()) > 2.0:
            raise BrainError("This protocol requires 3D T1-weighted imaging with spacing at most 2 mm.")
        sitk.WriteImage(t1, str(directory / "t1.nii.gz"))
        if flair_path:
            require_same_examination(patient_context, dicom_context(flair_path))
            progress("Registering 3D FLAIR to T1; overlay review will be required")
            flair = read_volume(flair_path, expected_protocol="flair")
            if max(flair.GetSpacing()) > 2.0:
                raise BrainError("This protocol requires 3D FLAIR with spacing at most 2 mm.")
            aligned, transform = register_flair(t1, flair, cancel)
            sitk.WriteImage(aligned, str(directory / "flair_registered.nii.gz"))
            sitk.WriteTransform(transform, str(directory / "flair_to_t1.tfm"))
        progress("Running local SynthSeg segmentation, parcellation and QC")
        run_process(synthseg_command(root, directory, plan), directory, cancel)
        volumes = read_single_subject_csv(directory / "posterior.csv")
        rows = volume_rows(volumes)
        qc = read_single_subject_csv(directory / "qc.csv")
        if any(value > 1 for value in qc.values()):
            raise BrainError("The model returned invalid quality scores.")
        names = {}
        labels_root = root / "SynthSeg/data/labels_classes_priors"
        for kind in ("segmentation", "parcellation"):
            suffix = "_2.0" if kind == "segmentation" else ""
            ids = np.load(labels_root / f"synthseg_{kind}_labels{suffix}.npy", allow_pickle=False)
            strings = np.load(labels_root / f"synthseg_{kind}_names{suffix}.npy", allow_pickle=False)
            names.update({str(int(label)): str(name) for label, name in zip(ids, strings) if int(label) != 0})
        (directory / "label_names.json").write_text(json.dumps(names), encoding="utf-8")
        # SynthSeg does not save --resample when no resampling was necessary.
        if not (directory / "resampled.nii.gz").exists():
            sitk.WriteImage(t1, str(directory / "resampled.nii.gz"))
        progress("Measuring and independently checking binary volumes in Slicer")
        slicer_result = run_slicer(directory, cancel)
        result = {"format_version": 1, "job_id": directory.name, "status": "review_required",
                  "model": "SynthSeg 2.0", "model_revision": manifest["revision"], "plan": asdict(plan),
                  "bundle_manifest_sha256": sha256(root / "manifest.json"),
                  "source_sha256": sha256(directory / "t1.nii.gz"), "posterior_rows": rows,
                  "binary_rows": slicer_result["rows"], "qc_scores": qc,
                  "slicer_revision": slicer_result["slicer_revision"],
                  "normative_status": "No qualified reference model installed", "normative": normative,
                  "patient_context": patient_context,
                  "flair_status": "Rigid registration requires review" if flair_path else "Not supplied",
                  "wmh_segmentation": "Not implemented", "clinical_validation": "not_established"}
        with (directory / "volumes.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        from .report import report_html, write_pdf
        if reference_id == 'volbrain':
            from .volbrain_reference import attach_reference
            attach_reference(result, directory, demographics_for_report(patient_context, demographics))
        from .report_evidence import segmentation_png
        result["report_evidence_png"] = segmentation_png(directory)
        result["medial_temporal_evidence_png"] = segmentation_png(directory, medial_temporal=True)
        html = report_html(result)
        (directory / "report.html").write_text(html, encoding="utf-8")
        # CLI callers may omit Qt; the workstation always has QApplication.
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is not None:
            write_pdf(html, directory / "report.pdf")
        result["pdf_available"] = (directory / "report.pdf").is_file()
        if cancel.is_set():
            raise BrainError("Brain analysis cancelled.")
        temporary = directory / "result.partial"
        temporary.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
        temporary.replace(directory / "result.json")
        result["artifact_directory"] = str(directory)
        return result
    except Exception:
        # A failed job must never appear complete to a later consumer.
        (directory / "FAILED").write_text("Analysis did not complete. Do not use partial outputs.\n", encoding="utf-8")
        raise
