from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from .config import AppConfig
from .http_client import CrmHttpClient
from .jalali import gregorian_to_jalali
from .storage import Storage, snapshot_to_manifest


def date_params(date_filter: dict[str, str], business_date: date) -> dict[str, Any]:
    if not date_filter:
        return {}
    if date_filter.get("format") == "YYYY/MM/DD":
        formatted_date = gregorian_to_jalali(business_date)
    else:
        formatted_date = business_date.isoformat()
    start_param = date_filter.get("start_param")
    end_param = date_filter.get("end_param")
    params: dict[str, Any] = {}
    if start_param:
        params[start_param] = formatted_date
    if end_param:
        params[end_param] = formatted_date
    return params


def collect_day(config: AppConfig, business_date: date) -> dict[str, Any]:
    captured_at = datetime.combine(business_date, time.min).astimezone()
    captured_at = datetime.now(tz=captured_at.tzinfo)
    storage = Storage(config.data_root)
    storage.ensure_layout()
    client = CrmHttpClient(config.api)

    manifest_rows = []
    for endpoint in config.endpoints:
        response = client.fetch(endpoint, date_params(endpoint.date_filter, business_date))
        snapshot = storage.store_raw(endpoint.name, business_date, captured_at, response.body)
        row = snapshot_to_manifest(snapshot)
        row.update({"url": response.url, "status_code": response.status_code})
        manifest_rows.append(row)

    manifest_path = storage.store_manifest(business_date, captured_at, manifest_rows)
    summary_path = storage.store_daily_summary(business_date, manifest_rows)
    return {
        "business_date": business_date.isoformat(),
        "captured_at": captured_at.isoformat(),
        "manifest_path": str(manifest_path),
        "summary_path": str(summary_path),
        "endpoints": manifest_rows,
    }
