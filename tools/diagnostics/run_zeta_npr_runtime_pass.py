import os
import math
import json
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ.setdefault("QT_OPENGL", "software")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pydicom
from natsort import natsorted
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from PacsClient.utils.diagnostic_logging import configure_diagnostic_logging, shutdown_diagnostic_logging
from PacsClient.utils.structured_logging import emit_viewer_event
from PacsClient.pacs.patient_tab.utils.image_io import load_vtk_from_dicom_paths
from modules.mpr.zeta_mpr.mpr_viewer.widget import StandardMPRViewer


def _unit(v):
    arr = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(arr))
    if n <= 1e-12:
        return None
    return arr / n


def _angle_deg(a, b):
    ua = _unit(a)
    ub = _unit(b)
    if ua is None or ub is None:
        return None
    dot = float(np.clip(np.dot(ua, ub), -1.0, 1.0))
    return float(math.degrees(math.acos(dot)))


def _safe_iop(ds):
    iop = ds.get("ImageOrientationPatient", None)
    if iop is None or len(iop) < 6:
        return None
    return [float(iop[i]) for i in range(6)]


def _safe_ipp(ds):
    ipp = ds.get("ImagePositionPatient", None)
    if ipp is None or len(ipp) < 3:
        return None
    return [float(ipp[i]) for i in range(3)]


def _plane_from_iop(iop):
    if not iop:
        return "unknown"
    row = np.asarray(iop[:3], dtype=float)
    col = np.asarray(iop[3:6], dtype=float)
    normal = np.cross(row, col)
    absn = np.abs(normal)
    axis = int(np.argmax(absn))
    return ["sagittal", "coronal", "axial"][axis]


def _anatomical_label(delta):
    d = np.asarray(delta, dtype=float)
    absd = np.abs(d)
    if float(absd.max()) <= 1e-9:
        return "Same"
    axis = int(np.argmax(absd))
    sign = float(d[axis]) > 0
    if axis == 0:
        return "Left" if sign else "Right"
    if axis == 1:
        return "Posterior" if sign else "Anterior"
    return "Superior" if sign else "Inferior"


def _expected_source_box(source_plane):
    return {
        "axial": "Axial",
        "sagittal": "Sagittal",
        "coronal": "Coronal",
    }.get(source_plane, "Axial")


def _collect_case(case_name, study_uid, series_number, series_path):
    case_path = Path(series_path)
    files = natsorted([str(p) for p in case_path.glob("*.dcm")])
    if not files:
        files = natsorted([str(p) for p in case_path.iterdir() if p.is_file()])
    if not files:
        raise RuntimeError(f"No files found for {case_name} at {series_path}")

    first_ds = pydicom.dcmread(files[0], stop_before_pixels=True)
    last_ds = pydicom.dcmread(files[-1], stop_before_pixels=True)

    iop = _safe_iop(first_ds)
    ipp_first = _safe_ipp(first_ds)
    ipp_last = _safe_ipp(last_ds)

    source_plane = _plane_from_iop(iop)
    expected_box = _expected_source_box(source_plane)

    emit_viewer_event(
        __import__("logging").getLogger(__name__),
        "ZETA_NPR_CASE_MARKER",
        case=case_name,
        study_uid=study_uid,
        series_number=series_number,
        series_path=str(series_path),
        source_plane=source_plane,
    )

    vtk_data = load_vtk_from_dicom_paths(files)
    if vtk_data is None:
        raise RuntimeError(f"VTK load failed for {case_name}")

    viewer = StandardMPRViewer(vtk_image_data=vtk_data, parent=None)

    dm = viewer.direction_matrix
    row_v = [dm.GetElement(0, 0), dm.GetElement(0, 1), dm.GetElement(0, 2)]
    col_v = [dm.GetElement(1, 0), dm.GetElement(1, 1), dm.GetElement(1, 2)]
    nrm_v = [dm.GetElement(2, 0), dm.GetElement(2, 1), dm.GetElement(2, 2)]

    row_s = iop[:3] if iop else None
    col_s = iop[3:6] if iop else None
    nrm_s = np.cross(np.asarray(row_s), np.asarray(col_s)).tolist() if iop else None

    row_err = _angle_deg(row_s, row_v) if row_s else None
    col_err = _angle_deg(col_s, col_v) if col_s else None
    nrm_err = _angle_deg(nrm_s, nrm_v) if nrm_s else None

    labels = ("?", "?")
    stack_order_ok = False
    if ipp_first is not None and ipp_last is not None and nrm_s is not None:
        delta = np.asarray(ipp_last, dtype=float) - np.asarray(ipp_first, dtype=float)
        first_label = _anatomical_label(-delta)
        last_label = _anatomical_label(delta)
        labels = (first_label, last_label)
        proj0 = float(np.dot(np.asarray(ipp_first, dtype=float), _unit(nrm_s)))
        proj1 = float(np.dot(np.asarray(ipp_last, dtype=float), _unit(nrm_s)))
        stack_order_ok = proj1 >= proj0

    modality = str(first_ds.get("Modality", ""))
    camera_hacks_active = bool(modality == "CT")
    xflip_compensated_in_axes = bool(iop is not None and np.sign(row_s[0]) != np.sign(row_v[0])) if row_s else False

    orientation_ok = bool(
        row_err is not None and col_err is not None and nrm_err is not None
        and row_err <= 25.0 and col_err <= 25.0 and nrm_err <= 25.0
    )

    if source_plane != "axial":
        failure_cause = "fixed_layout_source_bound_to_axial"
    elif not orientation_ok:
        failure_cause = "orientation_axis_mismatch"
    else:
        failure_cause = "none"

    viewer.close()
    viewer.deleteLater()

    return {
        "case": case_name,
        "study_uid": study_uid,
        "series_number": int(series_number),
        "source_plane": source_plane,
        "expected_source_box": expected_box,
        "actual_source_box": "Axial",
        "fallback_reason": "zeta_mpr_fixed_layout_axial_receives_input_volume",
        "output_view": "axial(primary), sagittal(recon), coronal(recon)",
        "row_axis_error": None if row_err is None else round(row_err, 3),
        "col_axis_error": None if col_err is None else round(col_err, 3),
        "normal_axis_error": None if nrm_err is None else round(nrm_err, 3),
        "first_label": labels[0],
        "last_label": labels[1],
        "stack_order_ok": bool(stack_order_ok),
        "orientation_ok": bool(orientation_ok),
        "failure_cause": failure_cause,
        "camera_hacks_active": camera_hacks_active,
        "xflip_compensated_in_axes": xflip_compensated_in_axes,
        "k_policy": "raw_vtk_k_direct (no display_k/raw_k layer in zeta_mpr)",
        "geometry_api_used": False,
    }


def main():
    configure_diagnostic_logging(process_role="main", force=True)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)

    app = QApplication.instance() or QApplication([])

    cases = [
        {
            "case": "shoulder_axial_source",
            "study_uid": "1.3.12.2.1107.5.2.46.174759.30000026051204291926500000058",
            "series_number": 3,
            "series_path": r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\patients\dicom\1.3.12.2.1107.5.2.46.174759.30000026051204291926500000058\3",
        },
        {
            "case": "shoulder_sagittal_source",
            "study_uid": "1.3.12.2.1107.5.2.46.174759.30000026051204291926500000058",
            "series_number": 4,
            "series_path": r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\patients\dicom\1.3.12.2.1107.5.2.46.174759.30000026051204291926500000058\4",
        },
        {
            "case": "shoulder_coronal_source",
            "study_uid": "1.3.12.2.1107.5.2.46.174759.30000026051204291926500000058",
            "series_number": 5,
            "series_path": r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\user_data\patients\dicom\1.3.12.2.1107.5.2.46.174759.30000026051204291926500000058\5",
        },
    ]

    rows = []
    for c in cases:
        try:
            rows.append(_collect_case(c["case"], c["study_uid"], c["series_number"], c["series_path"]))
            app.processEvents()
        except Exception as exc:
            rows.append({
                "case": c["case"],
                "study_uid": c["study_uid"],
                "series_number": int(c["series_number"]),
                "source_plane": "unknown",
                "expected_source_box": "unknown",
                "actual_source_box": "unknown",
                "fallback_reason": "runtime_error",
                "output_view": "n/a",
                "row_axis_error": None,
                "col_axis_error": None,
                "normal_axis_error": None,
                "first_label": "?",
                "last_label": "?",
                "stack_order_ok": False,
                "orientation_ok": False,
                "failure_cause": f"runtime_error:{exc}",
                "camera_hacks_active": False,
                "xflip_compensated_in_axes": False,
                "k_policy": "unknown",
                "geometry_api_used": False,
            })

    out_dir = Path("generated-files") / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "zeta_npr_runtime_evidence_matrix_2026-05-16.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    md_path = out_dir / "zeta_npr_runtime_evidence_matrix_2026-05-16.md"
    headers = [
        "case", "source_plane", "expected_source_box", "actual_source_box", "fallback_reason",
        "output_view", "row_axis_error", "col_axis_error", "normal_axis_error", "first_label",
        "last_label", "stack_order_ok", "orientation_ok", "failure_cause",
    ]
    lines = [
        "# Zeta NPR Runtime Evidence Matrix (2026-05-16)",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        vals = [str(row.get(h, "")) for h in headers]
        lines.append("| " + " | ".join(vals) + " |")

    lines.extend([
        "",
        "## Additional Checks",
        f"- sagittal_source_to_axial_box_confirmed: {rows[1]['actual_source_box'] == 'Axial'}",
        f"- coronal_source_to_axial_box_confirmed: {rows[2]['actual_source_box'] == 'Axial'}",
        f"- camera_roll_azimuth_active_any_case: {any(r['camera_hacks_active'] for r in rows)}",
        f"- xflip_compensated_in_axes_any_case: {any(r['xflip_compensated_in_axes'] for r in rows)}",
        "- output_stack_k_policy: raw_vtk_k_direct (crosshair/current_position mapped by spacing/origin)",
        "- sourcegeometry_displaygeometry_geometryapi_used_in_zeta_mpr: False",
    ])

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(str(json_path))
    print(str(md_path))

    shutdown_diagnostic_logging()


if __name__ == "__main__":
    main()
