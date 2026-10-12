from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StoredSnapshot:
    endpoint: str
    business_date: date
    captured_at: datetime
    raw_path: Path
    record_count: int | None


class Storage:
    def __init__(self, data_root: Path):
        self.root = data_root

    def ensure_layout(self) -> None:
        for path in [
            self.root / "config",
            self.root / "data" / "raw",
            self.root / "data" / "processed",
            self.root / "exports",
            self.root / "logs",
            self.root / "manifests",
            self.root / "reports",
        ]:
            path.mkdir(parents=True, exist_ok=True)

    def store_raw(
        self,
        endpoint: str,
        business_date: date,
        captured_at: datetime,
        body: Any,
    ) -> StoredSnapshot:
        directory = (
            self.root
            / "data"
            / "raw"
            / f"{business_date:%Y}"
            / f"{business_date:%m}"
            / f"{business_date:%d}"
            / endpoint
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{captured_at:%H%M%S}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        return StoredSnapshot(
            endpoint=endpoint,
            business_date=business_date,
            captured_at=captured_at,
            raw_path=path,
            record_count=count_records(body),
        )

    def store_manifest(self, business_date: date, captured_at: datetime, rows: list[dict[str, Any]]) -> Path:
        directory = self.root / "manifests" / f"{business_date:%Y}" / f"{business_date:%m}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{business_date:%Y-%m-%d}_{captured_at:%H%M%S}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
        return path

    def store_daily_summary(self, business_date: date, rows: list[dict[str, Any]]) -> Path:
        directory = self.root / "data" / "processed" / f"{business_date:%Y}" / f"{business_date:%m}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{business_date:%Y-%m-%d}_summary.csv"

        fieldnames = ["endpoint", "record_count", "raw_path", "captured_at"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key) for key in fieldnames})
        return path


def count_records(body: Any) -> int | None:
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        for key in ("data", "items", "results", "records"):
            value = body.get(key)
            if isinstance(value, list):
                return len(value)
    return None


def snapshot_to_manifest(snapshot: StoredSnapshot) -> dict[str, Any]:
    row = asdict(snapshot)
    row["raw_path"] = str(snapshot.raw_path)
    return row
