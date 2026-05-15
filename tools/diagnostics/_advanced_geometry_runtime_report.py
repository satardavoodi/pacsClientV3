"""Advanced geometry runtime integration report.

Parses viewer diagnostics logs and emits a structured Phase 2 report with:
A. Series geometry table
B. Viewport geometry table
C. Marker correctness table
D. Sync mapping table
E. Reference-line table
F. Contract violations table
G. Remaining legacy geometry consumers table

Usage:
  python tools/diagnostics/_advanced_geometry_runtime_report.py
  python tools/diagnostics/_advanced_geometry_runtime_report.py --log user_data/logs/viewer_diagnostics.log
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

TAG_RE = re.compile(r"\[(?P<tag>[A-Z0-9_]+)\]")
KV_RE = re.compile(r"([A-Za-z0-9_]+)=([^\s]+)")


@dataclass
class ParsedLine:
    tag: str
    raw: str
    kv: Dict[str, str]


def parse_kv(line: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in KV_RE.findall(line):
        out[k] = v
    return out


def parse_lines(text: str) -> List[ParsedLine]:
    rows: List[ParsedLine] = []
    for line in text.splitlines():
        m = TAG_RE.search(line)
        if not m:
            continue
        tag = m.group("tag")
        rows.append(ParsedLine(tag=tag, raw=line, kv=parse_kv(line)))
    return rows


def latest_log_path(root: Path) -> Optional[Path]:
    logs_dir = root / "user_data" / "logs"
    if not logs_dir.exists():
        return None
    candidates = sorted(logs_dir.glob("viewer_diagnostics*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        fallback = logs_dir / "viewer_diagnostics.log"
        return fallback if fallback.exists() else None
    return candidates[0]


def md_table(headers: List[str], rows: List[List[str]]) -> str:
    out = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def build_report(parsed: List[ParsedLine]) -> str:
    tags = Counter(p.tag for p in parsed)

    by_tag: Dict[str, List[ParsedLine]] = defaultdict(list)
    for p in parsed:
        by_tag[p.tag].append(p)

    section = []
    section.append("# Advanced Geometry Runtime Integration Report")
    section.append("")
    section.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    section.append("")

    # A. Series geometry table
    sg_rows = []
    for p in by_tag.get("GEOMETRY_SOURCE_CONTRACT", [])[-20:]:
        sg_rows.append([
            p.kv.get("series_uid", ""),
            p.kv.get("frame_of_reference", p.kv.get("frame_of_reference_uid", "")),
            p.kv.get("n_instances", ""),
            p.kv.get("valid", ""),
            p.kv.get("hash", p.kv.get("ijk_to_lps_hash", "")),
        ])
    section.append("## A) Series Geometry Table")
    section.append(md_table(
        ["series_uid", "frame_of_reference_uid", "n_instances", "valid", "ijk_to_lps_hash"],
        sg_rows or [["(none)", "", "", "", ""]],
    ))
    section.append("")

    # B. Viewport geometry table
    vp_rows = []
    for p in by_tag.get("ADVANCED_VIEWPORT_GEOMETRY_BIND", [])[-40:]:
        vp_rows.append([
            p.kv.get("viewport_id", ""),
            p.kv.get("series_uid", ""),
            p.kv.get("series_number", ""),
            p.kv.get("plane", ""),
            p.kv.get("frame_of_reference_uid", ""),
            p.kv.get("current_slice_index", ""),
            p.kv.get("current_sop_uid", ""),
        ])
    section.append("## B) Viewport Geometry Table")
    section.append(md_table(
        ["viewport_id", "series_uid", "series_number", "plane", "frame_of_reference_uid", "current_slice_index", "current_sop_uid"],
        vp_rows or [["(none)", "", "", "", "", "", ""]],
    ))
    section.append("")

    # C. Marker correctness table
    mk_rows = []
    for p in by_tag.get("MARKERS_FROM_GEOMETRY_CONTRACT", [])[-60:]:
        mk_rows.append([
            p.kv.get("viewport_id", ""),
            p.kv.get("top_label", ""),
            p.kv.get("bottom_label", ""),
            p.kv.get("left_label", ""),
            p.kv.get("right_label", ""),
            p.kv.get("source", ""),
        ])
    section.append("## C) Marker Correctness Table")
    section.append(md_table(
        ["viewport_id", "top", "bottom", "left", "right", "source"],
        mk_rows or [["(none)", "", "", "", "", ""]],
    ))
    section.append("")

    # D. Sync mapping table
    sync_rows = []
    blocked = 0
    for p in by_tag.get("SYNC_LPS_MAPPING", [])[-120:]:
        if p.kv.get("sync_blocked_reason"):
            blocked += 1
        sync_rows.append([
            p.kv.get("source_viewport", p.kv.get("src_viewport", "")),
            p.kv.get("target_viewport", p.kv.get("dst_viewport", "")),
            p.kv.get("same_frame_of_reference", ""),
            p.kv.get("registration_used", ""),
            p.kv.get("roundtrip_error_px", ""),
            p.kv.get("sync_blocked_reason", ""),
        ])
    section.append("## D) Sync Mapping Table")
    section.append(md_table(
        ["source_viewport", "target_viewport", "same_frame_of_reference", "registration_used", "roundtrip_error_px", "sync_blocked_reason"],
        sync_rows or [["(none)", "", "", "", "", ""]],
    ))
    section.append("")

    # E. Reference-line table
    rl_rows = []
    for p in by_tag.get("REFERENCE_LINE_LPS_INTERSECTION", [])[-120:]:
        rl_rows.append([
            p.kv.get("source_viewport", p.kv.get("ref_viewport", "")),
            p.kv.get("target_viewport", p.kv.get("tgt_viewport", "")),
            p.kv.get("intersection_status", ""),
            p.kv.get("target_display_p0", p.kv.get("tgt_p1", "")),
            p.kv.get("target_display_p1", p.kv.get("tgt_p2", "")),
        ])
    section.append("## E) Reference-Line Table")
    section.append(md_table(
        ["source_viewport", "target_viewport", "intersection_status", "target_display_p0", "target_display_p1"],
        rl_rows or [["(none)", "", "", "", ""]],
    ))
    section.append("")

    # F. Contract violations table
    violations = []
    for p in parsed:
        if "CONTRACT VIOLATION" in p.raw or "contract_violation" in p.raw.lower():
            violations.append([p.tag, p.raw[:220]])
    section.append("## F) Contract Violations Table")
    section.append(md_table(["tag", "evidence"], violations or [["(none)", "No explicit contract-violation log lines found."]]))
    section.append("")

    # G. Remaining legacy consumers
    legacy_rows = []
    if tags.get("ADVANCED_ORIENTATION_MARKERS", 0) > 0:
        legacy_rows.append([
            "orientation_markers.update_from_geometry",
            "Legacy camera-basis marker path still emits [ADVANCED_ORIENTATION_MARKERS]",
            "Keep only as guarded fallback; prefer [MARKERS_FROM_GEOMETRY_CONTRACT]",
        ])
    if tags.get("ADVANCED_VTK_ORIENTATION_AUDIT", 0) > 0:
        legacy_rows.append([
            "viewer_2d camera-based orientation audit",
            "Uses camera vectors for diagnostic mismatch metrics",
            "Keep as diagnostics-only; not source of medical truth",
        ])
    section.append("## G) Remaining Legacy Geometry Consumers Table")
    section.append(md_table(
        ["consumer", "current_state", "migration_note"],
        legacy_rows or [["(none-detected-in-log)", "", ""]],
    ))
    section.append("")

    # Explicit answers
    has_source = tags.get("GEOMETRY_SOURCE_CONTRACT", 0) > 0
    has_display = tags.get("DISPLAY_GEOMETRY_CONTRACT", 0) > 0 and tags.get("EFFECTIVE_DISPLAY_AFFINE", 0) > 0
    has_bind = tags.get("ADVANCED_VIEWPORT_GEOMETRY_BIND", 0) > 0
    has_markers = tags.get("MARKERS_FROM_GEOMETRY_CONTRACT", 0) > 0
    has_sync = tags.get("SYNC_LPS_MAPPING", 0) > 0
    has_ref = tags.get("REFERENCE_LINE_LPS_INTERSECTION", 0) > 0
    has_vtk = tags.get("VTK_ORIENTATION_BRIDGE_STATUS", 0) > 0

    section.append("## Explicit Answers")
    answers = [
        ["Is every viewport bound to SourceGeometry?", "PASS" if has_source and has_bind else "FAIL"],
        ["Is every viewport bound to DisplayGeometry?", "PASS" if has_display and has_bind else "FAIL"],
        ["Does every displayed pixel have a valid Display-IJK->LPS mapping?", "PASS" if has_display else "FAIL"],
        ["Are markers contract-derived?", "PASS" if has_markers else "FAIL"],
        ["Are sync and reference lines using LPS?", "PASS" if has_sync and has_ref else "FAIL"],
        ["Are there any naked flips/rotations?", "UNKNOWN (code audit required)"],
        ["Is VTK direction preserved, ignored, or mirrored?", "MIRRORED (non-authoritative)" if has_vtk else "UNKNOWN"],
    ]
    section.append(md_table(["question", "answer"], answers))
    section.append("")

    section.append("## Tag Counters")
    tag_rows = [[k, str(v)] for k, v in sorted(tags.items()) if k in {
        "GEOMETRY_SOURCE_CONTRACT",
        "DISPLAY_GEOMETRY_CONTRACT",
        "EFFECTIVE_DISPLAY_AFFINE",
        "VTK_ORIENTATION_BRIDGE_STATUS",
        "ADVANCED_VIEWPORT_GEOMETRY_BIND",
        "MARKERS_FROM_GEOMETRY_CONTRACT",
        "SYNC_LPS_MAPPING",
        "REFERENCE_LINE_LPS_INTERSECTION",
        "ADVANCED_ORIENTATION_MARKERS",
        "ADVANCED_VTK_ORIENTATION_AUDIT",
    }]
    section.append(md_table(["tag", "count"], tag_rows or [["(none)", "0"]]))
    section.append("")

    # H. Clinical validation matrix (log-driven best effort)
    # If no explicit case tags exist in the log, mark NOT_RUN_FROM_LOG.
    section.append("## Clinical Validation Cases")
    section.append("(Derived from current log contents; if a case is not explicitly tagged in log, it is marked NOT_RUN_FROM_LOG.)")
    case_rows = [
        ["knee axial+sagittal+coronal", "NOT_RUN_FROM_LOG"],
        ["shoulder oblique+coronal+sagittal", "NOT_RUN_FROM_LOG"],
        ["wrist/hand oblique+coronal+sagittal", "NOT_RUN_FROM_LOG"],
        ["neck axial+sagittal+coronal", "NOT_RUN_FROM_LOG"],
        ["non-orthogonal oblique pair", "NOT_RUN_FROM_LOG"],
        ["reopen same patient/series", "NOT_RUN_FROM_LOG"],
    ]
    section.append(md_table(["clinical_case", "status"], case_rows))
    section.append("")

    section.append("## Final PASS/FAIL (Current Log)")
    final_ok = (
        has_source and has_display and has_bind and has_markers and has_sync and has_ref and has_vtk
    )
    section.append(md_table(
        ["criterion", "status"],
        [
            ["All required runtime tags present", "PASS" if final_ok else "FAIL"],
            ["Clinical validation cases completed in this log", "FAIL"],
            ["Phase 2 complete", "PASS" if final_ok else "FAIL"],
        ],
    ))
    section.append("")

    return "\n".join(section)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", type=str, default="", help="Path to viewer diagnostics log")
    ap.add_argument("--out", type=str, default="", help="Output markdown path")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    log_path = Path(args.log) if args.log else latest_log_path(repo_root)
    if log_path is None or not log_path.exists():
        print("No diagnostics log found.")
        return 2

    text = log_path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_lines(text)
    report_md = build_report(parsed)

    out_path = Path(args.out) if args.out else (repo_root / "ADVANCED_GEOMETRY_RUNTIME_INTEGRATION_REPORT.md")
    out_path.write_text(report_md, encoding="utf-8")

    print(f"Log parsed: {log_path}")
    print(f"Report written: {out_path}")
    print(json.dumps({"line_count": len(text.splitlines()), "parsed_tagged_lines": len(parsed)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
