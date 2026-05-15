import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PacsClient.utils.data_paths import USER_DATA_ROOT


LOG_FILE = USER_DATA_ROOT / "logs" / "viewer_diagnostics.log"


def _extract_key(line: str, key: str):
    m = re.search(rf"\b{re.escape(key)}=([^\s].*?)(?=\s+\w+=|$)", line)
    return m.group(1).strip() if m else ""


def _parse_float(value: str):
    try:
        return float(value)
    except Exception:
        return None


def _iter_audit_lines(text: str):
    for raw in text.splitlines():
        if "[ADVANCED_VTK_ORIENTATION_AUDIT]" not in raw:
            continue
        yield raw


def build_report(log_path: Path):
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return

    text = log_path.read_text(encoding="utf-8", errors="replace")
    rows = []

    for line in _iter_audit_lines(text):
        payload = line.split("[ADVANCED_VTK_ORIENTATION_AUDIT]", 1)[-1].strip()
        stage = _extract_key(payload, "stage")
        # Only use per-viewport slice logs for proof table.
        if stage:
            continue

        plane = _extract_key(payload, "plane")
        if not plane:
            # Try to infer from series metadata if line already flattened.
            plane = _extract_key(payload, "geometry_plane") or "UNKNOWN"

        viewport = _extract_key(payload, "viewport_id") or _extract_key(payload, "series_uid")
        row = {
            "viewport": viewport or "unknown",
            "plane": plane,
            "dicom_row": _extract_key(payload, "iop_row"),
            "dicom_col": _extract_key(payload, "iop_col"),
            "dicom_normal": _extract_key(payload, "iop_normal"),
            "sitk_direction": _extract_key(payload, "sitk_direction"),
            "vtk_direction": _extract_key(payload, "vtk_direction_matrix"),
            "actor_camera": (
                f"actor={_extract_key(payload, 'actor_matrix')} "
                f"cam_pos={_extract_key(payload, 'camera_position')} "
                f"cam_up={_extract_key(payload, 'camera_view_up')}"
            ).strip(),
            "mismatch": (
                f"row={_extract_key(payload, 'row_axis_mismatch_deg')} "
                f"col={_extract_key(payload, 'col_axis_mismatch_deg')} "
                f"normal={_extract_key(payload, 'normal_mismatch_deg')}"
            ).strip(),
            "failure_class": _extract_key(payload, "failure_class") or "?",
            "orientation_valid": _extract_key(payload, "orientation_valid") or "",
        }
        rows.append(row)

    if not rows:
        print("No per-viewport [ADVANCED_VTK_ORIENTATION_AUDIT] lines found yet.")
        print("Run a real knee side-by-side Advanced VTK session first, then re-run this script.")
        return

    # Deduplicate by viewport keeping last observation.
    latest = {}
    for r in rows:
        latest[r["viewport"]] = r

    print("\n[ADVANCED_VTK_ORIENTATION_AUDIT] PROOF TABLE\n")
    print("| viewport | plane | DICOM row/col/normal | SITK direction | VTK direction | actor/camera axes | mismatch_deg | failure_class |")
    print("|---|---|---|---|---|---|---|---|")

    for viewport in sorted(latest.keys()):
        r = latest[viewport]
        dicom = f"row={r['dicom_row']} col={r['dicom_col']} normal={r['dicom_normal']}"
        print(
            f"| {r['viewport']} | {r['plane']} | {dicom} | {r['sitk_direction']} | {r['vtk_direction']} | "
            f"{r['actor_camera']} | {r['mismatch']} | {r['failure_class']} |"
        )

    counts = {}
    for r in latest.values():
        c = r["failure_class"] or "?"
        counts[c] = counts.get(c, 0) + 1
    print("\nFailure-class counts:")
    for k in sorted(counts.keys()):
        print(f"  {k}: {counts[k]}")


if __name__ == "__main__":
    build_report(LOG_FILE)
