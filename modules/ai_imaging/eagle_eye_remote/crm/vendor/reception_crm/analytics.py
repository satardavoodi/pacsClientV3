from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

from . import snapshots as snapshot_store


def load_daily_summary(data_root: Path, business_date: date) -> list[dict[str, Any]]:
    path = (
        data_root
        / "data"
        / "processed"
        / f"{business_date:%Y}"
        / f"{business_date:%m}"
        / f"{business_date:%Y-%m-%d}_summary.csv"
    )
    if not path.exists():
        raise FileNotFoundError(f"No processed summary exists for {business_date}: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_daily_report(data_root: Path, business_date: date) -> Path:
    rows = load_daily_summary(data_root, business_date)
    report_dir = data_root / "reports" / f"{business_date:%Y}" / f"{business_date:%m}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{business_date:%Y-%m-%d}_daily_report.md"

    lines = [
        f"# Reception CRM Daily Report - {business_date:%Y-%m-%d}",
        "",
        "## Collection Summary",
        "",
        "| Endpoint | Records | Captured At | Raw Snapshot |",
        "| --- | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('endpoint', '')} | {row.get('record_count') or ''} | "
            f"{row.get('captured_at') or ''} | {row.get('raw_path') or ''} |"
        )

    lines.extend(
        [
            "",
            "## Management Questions Ready From Stored Data",
            "",
            "- Patient admissions volume, once the admissions endpoint schema is mapped.",
            "- Daily revenue, once financial amount fields are mapped.",
            "- Busiest modalities, once modality or service fields are mapped.",
            "- Financial statistics, once payments, discounts, receivables, and refunds are mapped.",
        ]
    )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def inspect_raw_snapshot(path: Path) -> dict[str, Any]:
    # Through `snapshots.read` so a compacted file is still found. Opening the
    # path directly stopped working the moment compaction ran, and stopped
    # working QUIETLY: "no snapshot for that day" reads exactly like "nothing
    # happened that day".
    body = snapshot_store.read(path)
    sample: Any
    if isinstance(body, list):
        sample = body[:1]
    elif isinstance(body, dict):
        sample = {key: body[key] for key in list(body)[:10]}
    else:
        sample = body
    return {"type": type(body).__name__, "sample": sample}
