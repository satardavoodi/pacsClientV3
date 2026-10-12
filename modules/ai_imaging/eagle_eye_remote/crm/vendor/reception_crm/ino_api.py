from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import politeness


class InoApiError(RuntimeError):
    """Raised when INO CRM API access fails."""


@dataclass
class InoClient:
    host: str = "81.16.117.196"
    crm_port: int = 8080
    username: str | None = None
    password: str | None = None
    timeout_seconds: int = 30
    token: str | None = None

    @classmethod
    def from_env(cls) -> "InoClient":
        from .settings import load_settings

        profile = load_settings().active()
        host = os.getenv("INO_HOST") or os.getenv("RECEPTION_CRM_HOST") or profile.host
        crm_port = int(os.getenv("INO_CRM_PORT") or os.getenv("RECEPTION_CRM_PORT") or profile.crm_port)
        username = os.getenv("INO_USER") or os.getenv("RECEPTION_CRM_USERNAME") or profile.username
        password = os.getenv("INO_PASS") or os.getenv("RECEPTION_CRM_PASSWORD") or profile.resolved_password()
        return cls(host=host, crm_port=crm_port, username=username, password=password)

    @classmethod
    def from_profile(cls, profile: Any, password_override: str | None = None) -> "InoClient":
        return cls(
            host=profile.host,
            crm_port=profile.crm_port,
            username=profile.username,
            password=profile.resolved_password(password_override),
        )

    @property
    def base_url(self) -> str:
        normalized_host = self.host.replace("http://", "").replace("https://", "").strip("/")
        return f"http://{normalized_host}:{self.crm_port}"

    def login(self) -> str:
        if not self.username or not self.password:
            raise InoApiError("Set INO_USER/INO_PASS or RECEPTION_CRM_USERNAME/RECEPTION_CRM_PASSWORD.")
        response = self.request(
            "POST",
            "/api/auth/login",
            body={"username": self.username, "password": self.password},
            authenticated=False,
        )
        token = response.get("token") if isinstance(response, dict) else None
        if not token:
            raise InoApiError("INO login succeeded but no token was returned.")
        self.token = token
        return token

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post_json(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, body=body)

    def patch_json(self, path: str, body: dict[str, Any] | None = None) -> Any:
        return self.request("PATCH", path, body=body)

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> Any:
        if authenticated and not self.token:
            self.login()

        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"

        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = Request(url, data=payload, headers=headers, method=method)
        try:
            # Every reception API call in this process passes through here, so
            # this is the one place worth bounding. CPU priority protects the
            # reception software's CPU and does nothing for its thread pool: a
            # below-normal process can still occupy twenty of its connections,
            # and they queue at ITS priority, which is the reception desk's.
            #
            # This used to be bounded by accident — one question, one call. The
            # gathering loop ended that accident.
            with politeness.reception_gate.slot():
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    raw = response.read().decode("utf-8", errors="replace")
                    return json.loads(raw) if raw else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if authenticated and retry_auth and exc.code in {401, 403}:
                self.token = None
                self.login()
                return self.request(method, path, params, body, authenticated, retry_auth=False)
            raise InoApiError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise InoApiError(f"{method} {path} failed: {exc.reason}") from exc

    def patients_by_service_insurance(
        self,
        start_date: str,
        end_date: str,
        modality: str | None = None,
        insurance_type: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        path = "/api/Reports/patients-by-service-insurance"
        base_params = {
            "startDate": start_date,
            "endDate": end_date,
            "modality": modality,
            "insuranceType": insurance_type,
            "limit": limit,
        }
        first = self.get_json(path, {**base_params, "page": 1})
        return collect_paginated_receptions(self, path, base_params, first)

    def cashdesk_risk_analysis(
        self,
        start_date: str,
        end_date: str,
        cashier: str | None = None,
    ) -> dict[str, Any]:
        return self.get_json(
            "/api/CashDeskAnalysis/risk-analysis",
            {
                "startDate": start_date,
                "endDate": end_date,
                "cashier": cashier,
            },
        )

    def cashier_report(self, start_date: str, end_date: str) -> dict[str, Any]:
        """The reception system's OWN cashier report, for a Jalali period.

        It honours `startDate`/`endDate`: 108 transactions today against 191
        yesterday, and no parameters defaults to today.

        It IGNORES `startTime`/`endTime`, and that cost me a wrong conclusion
        worth recording. Reading those two names out of the minified UI bundle,
        I probed with them, got today's numbers back for every period including
        yesterday, and documented the report as having no period at all. Three
        of the four probes were really the same call. The confounding is the
        lesson: when testing whether a parameter is honoured, the control must
        be a DIFFERENT VALUE of the same parameter, never a different parameter
        name — otherwise "ignored" and "misspelled" produce identical evidence.

        `reportInfo.scope` is `cashier_active`, which describes which cashier
        sessions are included, not the time window. `reportInfo.filters` echoes
        back whatever you send, honoured or not, so it is not evidence either.
        """
        return self.get_json(
            "/api/Reports/cashier-report",
            {"startDate": start_date, "endDate": end_date},
        )

    def cashier_deleted_transactions(
        self,
        start_date: str,
        end_date: str,
        *,
        category: str | None = None,
        user_id: str | None = None,
        max_items: int = 5000,
    ) -> dict[str, Any]:
        """Read deleted cash-desk transaction details, bounded and paginated.

        This is deliberately separate from :meth:`cashier_report`: the main
        report publishes only a total for deleted transactions and cannot say
        who registered or deleted one.  The detail endpoint can, but it is a
        collection and therefore must never be fetched without a hard ceiling.
        """
        max_items = max(1, min(int(max_items or 5000), 5000))
        page_size = min(200, max_items)
        path = "/api/Reports/cashier-report/deleted-details"
        params = {
            "startDate": start_date,
            "endDate": end_date,
            "category": category,
            "userId": user_id,
            "limit": page_size,
        }
        first = self.get_json(path, {**params, "page": 1})
        return collect_paginated_items(
            self,
            path,
            params,
            first,
            item_key="transactions",
            max_items=max_items,
        )

    def physician_performance_summary(
        self,
        start_date: str,
        end_date: str,
        radiologist_id: str | None = None,
    ) -> dict[str, Any]:
        """Per-radiologist workload and revenue for a Jalali period.

        Genuinely date-scoped -- confirmed by asking for two different days and
        getting two different answers (3 radiologists / 30 patients today
        against 7 / 123 yesterday).

        Counts patients ASSIGNED TO A RADIOLOGIST, which is a smaller number
        than the day's receptions: 30 here against 96 admissions. Both are
        correct answers to different questions, and confusing them is how
        "workload" turns into a figure nobody can reconcile.
        """
        return self.get_json(
            "/api/Reports/physician-performance/summary",
            {
                "startDate": start_date,
                "endDate": end_date,
                "radiologistId": radiologist_id,
            },
        )

    def reporting_worklist(
        self,
        *,
        reception_id: str | int | None = None,
        page: int = 1,
        limit: int = 20,
        start_date: str | None = None,
        end_date: str | None = None,
        search: str | None = None,
        modality: str | None = None,
        status: str | None = None,
        radiologist: str | None = None,
        has_voice_attachment: str | None = None,
        include_stats: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": page,
            "limit": limit,
            "startDate": start_date,
            "endDate": end_date,
            "receptionID": reception_id,
            "search": search,
            "modality": modality,
            "status": status,
            "radiologist": radiologist,
            "includeStats": "true" if include_stats else "false",
        }
        if has_voice_attachment in {"yes", "no"}:
            params["hasVoiceAttachment"] = has_voice_attachment
        return self.get_json("/api/imagingWorkflow/workflow/reporting", params)

    def pacs_report(self, reception_id: str | int) -> dict[str, Any]:
        return self.get_json(f"/api/pacs/report/{reception_id}")

    def pacs_patient_detail(self, reception_id: str | int) -> dict[str, Any]:
        return self.get_json(f"/api/pacs/patients/{reception_id}")

    def report_logs(
        self,
        workflow_id: str,
        *,
        page: int = 1,
        limit: int = 50,
        action: str | None = None,
        field: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        changed_by: str | None = None,
        sort: str = "desc",
    ) -> dict[str, Any]:
        return self.get_json(
            f"/api/imagingWorkflow/{workflow_id}/workflow/report/logs",
            {
                "page": page,
                "limit": limit,
                "action": action,
                "field": field,
                "startDate": start_date,
                "endDate": end_date,
                "changedBy": changed_by,
                "sort": sort,
            },
        )

    def report_status_history(self, workflow_id: str) -> dict[str, Any]:
        return self.get_json(f"/api/imagingWorkflow/{workflow_id}/workflow/report/status/history")

    def print_layout(self) -> dict[str, Any]:
        return self.get_json("/api/print-layout")

    def report_settings(self) -> dict[str, Any]:
        return self.get_json("/api/Setting/Setting/get")

    def stamp_settings(self) -> dict[str, Any]:
        return self.get_json("/api/Setting/RequireStamp/get")


def collect_paginated_receptions(
    client: InoClient,
    path: str,
    base_params: dict[str, Any],
    first_response: dict[str, Any],
) -> dict[str, Any]:
    data = first_response.get("data") if isinstance(first_response, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("receptions"), list):
        return first_response

    pagination = data.get("pagination") or {}
    total_pages = safe_int(pagination.get("totalPages"), 1)
    has_next = bool(pagination.get("hasNextPage"))
    if total_pages <= 1 and not has_next:
        return first_response

    combined = deepcopy(first_response)
    combined_data = combined["data"]
    receptions = list(combined_data.get("receptions", []))
    page = 2
    while page <= total_pages or has_next:
        response = client.get_json(path, {**base_params, "page": page})
        response_data = response.get("data") if isinstance(response, dict) else {}
        if not isinstance(response_data, dict):
            break
        page_receptions = response_data.get("receptions") or []
        if isinstance(page_receptions, list):
            receptions.extend(page_receptions)
        page_pagination = response_data.get("pagination") or {}
        has_next = bool(page_pagination.get("hasNextPage"))
        total_pages = max(total_pages, safe_int(page_pagination.get("totalPages"), total_pages))
        if not has_next and page >= total_pages:
            break
        page += 1

    combined_data["receptions"] = receptions
    combined_pagination = dict(combined_data.get("pagination") or {})
    combined_pagination["collectedCount"] = len(receptions)
    combined_pagination["collectedPages"] = page
    combined_data["pagination"] = combined_pagination
    return combined


def collect_paginated_items(
    client: InoClient,
    path: str,
    base_params: dict[str, Any],
    first_response: dict[str, Any],
    *,
    item_key: str,
    max_items: int,
) -> dict[str, Any]:
    """Collect a vendor-paginated list without allowing an unbounded read."""
    data = first_response.get("data") if isinstance(first_response, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get(item_key), list):
        return first_response

    combined = deepcopy(first_response)
    combined_data = combined["data"]
    items = list(combined_data.get(item_key) or [])[:max_items]
    pagination = data.get("pagination") or {}
    total_pages = max(1, safe_int(pagination.get("totalPages"), 1))
    has_next = bool(pagination.get("hasNextPage"))
    page = 1

    while len(items) < max_items and (page < total_pages or has_next):
        page += 1
        response = client.get_json(path, {**base_params, "page": page})
        page_data = response.get("data") if isinstance(response, dict) else None
        if not isinstance(page_data, dict):
            break
        page_items = page_data.get(item_key) or []
        if not isinstance(page_items, list):
            break
        items.extend(page_items[: max_items - len(items)])
        page_pagination = page_data.get("pagination") or {}
        has_next = bool(page_pagination.get("hasNextPage"))
        total_pages = max(total_pages, safe_int(page_pagination.get("totalPages"), total_pages))

    total_count = safe_int(pagination.get("totalCount"), len(items))
    combined_data[item_key] = items
    combined_pagination = dict(combined_data.get("pagination") or {})
    combined_pagination.update(
        {
            "collectedCount": len(items),
            "collectedPages": page,
            "collectionComplete": len(items) >= total_count and not has_next,
            "maxItems": max_items,
        }
    )
    combined_data["pagination"] = combined_pagination
    return combined


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
