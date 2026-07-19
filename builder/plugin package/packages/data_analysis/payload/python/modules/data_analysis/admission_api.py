# -*- coding: utf-8 -*-
"""Admission Reports REST API client for the Data Analysis dashboard.

This talks to the **web admission software's Reports API** — the same second
server channel already used by the Reception/Workflow REST layer (default
``http://81.16.117.196:8080``, resolved via
``modules.network.reception_api_config``). It is intentionally kept separate
from the PACS imaging **socket** channel (patient list / thumbnails / DICOM
download); this module never touches that pipeline.

Design guarantees
-----------------
* **Non-blocking.** All HTTP I/O runs on a background daemon thread inside
  :class:`AdmissionReportsWorker`; results are delivered via Qt signals which
  Qt queues onto the GUI thread. The GUI thread is NEVER blocked by a network
  call, JSON parse, or snapshot build.
* **Auth is reused, never stored.** The JWT is read from the logged-in
  ``SocketTokenManager`` (the same token the workstation obtained at login and
  the same one the admission web app sends as ``Authorization: Bearer``). No
  password or token is persisted by this module. When the session has expired
  a single best-effort re-login is attempted from the saved login config (only
  if the user chose "remember me"); otherwise a clear auth error is surfaced.
* **Circuit breaker + logging.** Reuses the Reception/API breaker so a dead or
  slow admission server can't be hammered on every refresh.

The snapshot builder (:func:`build_admission_snapshot`) is a **pure function**
(stdlib only) so it is unit-testable headless and safe to run off-thread.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

try:
    import requests
except Exception:  # pragma: no cover - requests is a hard dependency of the app
    requests = None  # type: ignore

from modules.network.reception_api_config import (
    get_reception_api_base_url,
    get_reception_api_timeout,
    reception_api_breaker_open,
    record_reception_api_failure,
    record_reception_api_success,
)
from modules.network.socket_token_manager import get_socket_token_manager

logger = logging.getLogger(__name__)

# The report the admission "Insurance by Service" page is built on.
REPORT_PATH = "/api/Reports/patients-by-service-insurance"
LOGIN_PATH = "/api/auth/login"

# Rows pulled per refresh. High enough to compute an accurate daily trend and
# modality/insurance breakdown for a normal date window, capped so a huge range
# can't balloon memory. The summary block is authoritative for the KPI cards;
# the rows drive the daily trend + the recent-admissions table.
_DEFAULT_ROW_LIMIT = int(os.environ.get("AIPACS_ADMISSION_ROW_LIMIT", "3000") or "3000")
_TABLE_MAX_ROWS = 250


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class AdmissionAuthError(Exception):
    """Raised when there is no valid session / the server returns 401/403."""


class AdmissionApiError(Exception):
    """Raised for connectivity, timeout, HTTP, or payload errors."""


# ---------------------------------------------------------------------------
# Jalali (Shamsi) date helpers — self-contained, no third-party dependency.
# The admission Reports API expects Jalali dates formatted "YYYY/MM/DD".
# ---------------------------------------------------------------------------
def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += g_d_m[gm2] + gd2
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    if j_day_no < 186:
        jm = 1 + j_day_no // 31
        jd = 1 + j_day_no % 31
    else:
        jm = 7 + (j_day_no - 186) // 30
        jd = 1 + (j_day_no - 186) % 30
    return jy, jm, jd


def _fmt_jalali(gy: int, gm: int, gd: int) -> str:
    jy, jm, jd = _gregorian_to_jalali(gy, gm, gd)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def jalali_today(offset_days: int = 0) -> str:
    """Return today's Jalali date (optionally offset by *offset_days*)."""
    import datetime as _dt

    d = _dt.date.today() + _dt.timedelta(days=offset_days)
    return _fmt_jalali(d.year, d.month, d.day)


# Preset keys are stable identifiers; labels are the Persian UI captions.
DATE_PRESETS: List[Tuple[str, str]] = [
    ("today", "امروز"),
    ("yesterday", "دیروز"),
    ("last7", "۷ روز اخیر"),
    ("last30", "۳۰ روز اخیر"),
]


def resolve_date_range(preset: str) -> Tuple[str, str]:
    """Resolve a preset key to a (startDate, endDate) Jalali pair.

    Ranges are computed in Gregorian then converted, so they stay correct
    across Jalali month/year boundaries without a calendar library.
    """
    if preset == "today":
        return jalali_today(0), jalali_today(0)
    if preset == "yesterday":
        return jalali_today(-1), jalali_today(-1)
    if preset == "last7":
        return jalali_today(-6), jalali_today(0)
    if preset == "last30":
        return jalali_today(-29), jalali_today(0)
    # Safe default: today.
    return jalali_today(0), jalali_today(0)


# ---------------------------------------------------------------------------
# Pure snapshot builder — maps the raw API JSON to the dashboard view-model.
# ---------------------------------------------------------------------------
# Canonical modality-code -> Persian label (the API also returns
# ``modalityFullName``; this is a fallback / ordering aid only).
_MODALITY_LABELS = {
    "1": "سی‌تی‌اسکن",
    "2": "ام‌آر‌آی",
    "3": "سونوگرافی",
    "4": "رادیولوژی",
}
# Keys used for the fixed "highlight" cards the user asked for.
_HIGHLIGHT_MODALITIES = [
    ("2", "ام‌آر‌آی (MRI)"),
    ("1", "سی‌تی‌اسکن (CT)"),
    ("3", "سونوگرافی (US)"),
    ("4", "رادیولوژی (X-Ray)"),
]


def _to_int(v: Any) -> int:
    try:
        return int(round(float(v)))
    except Exception:
        return 0


def build_admission_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Turn the raw report JSON into the dashboard view-model.

    Pure / stdlib-only so it is unit-testable and safe to run off the GUI
    thread. Never raises on a partial/odd payload — missing pieces degrade to
    empty lists / zero counts.
    """
    data = (payload or {}).get("data") or {}
    summary = data.get("summary") or {}
    overall = summary.get("overall") or {}
    debt = summary.get("debt") or {}
    by_modality = summary.get("byModality") or []
    by_insurance = summary.get("byInsurance") or []
    receptions = data.get("receptions") or []
    pagination = data.get("pagination") or {}

    # --- KPI / summary cards -------------------------------------------------
    total_patients = _to_int(overall.get("uniquePatients"))
    total_receptions = _to_int(overall.get("totalReceptions"))
    total_services = _to_int(overall.get("totalServices"))

    # --- Financial summary ---------------------------------------------------
    # Field mapping to the Reports API summary:
    #   Patient Share     = overall.totalPatientShare
    #   Insurance Share   = overall.totalOrganizationShare (Σ of the per-insurer
    #                       shares: salamat + tamin + army + supplementary)
    #   Total Discounts   = overall.totalDiscount
    #   Cashier Discount  = debt.totalCashDeskDiscount   (تخفیف صندوق)
    #   Manual Withdrawal = debt.totalFundDiscount       (برداشت دستی — the only
    #                       remaining cashier-side deduction the API exposes)
    # Final revenue is computed per the agreed business formula:
    #   Total Revenue = Patient Share + Insurance Share
    #                   − Manual Withdrawal − Cashier Discount
    patient_share = _to_int(overall.get("totalPatientShare"))
    insurance_share = _to_int(overall.get("totalOrganizationShare"))
    total_discount = _to_int(overall.get("totalDiscount"))
    cashier_discount = _to_int(debt.get("totalCashDeskDiscount"))
    manual_withdrawal = _to_int(debt.get("totalFundDiscount"))
    total_revenue = patient_share + insurance_share - manual_withdrawal - cashier_discount

    financial = {
        "patient_share": patient_share,
        "insurance_share": insurance_share,
        "total_discount": total_discount,
        "manual_withdrawal": manual_withdrawal,
        "cashier_discount": cashier_discount,
        "total_revenue": total_revenue,
        # Extra context (not required cards, but handy for tooltips/future use):
        "gross_amount": _to_int(overall.get("totalAmount")),
        "total_paid": _to_int(debt.get("totalPaidAmount")),
        "patient_debt": _to_int(debt.get("totalPatientDebt")),
        "salamat_share": _to_int(overall.get("totalSalamatInsurance")),
        "tamin_share": _to_int(overall.get("totalTaminInsurance")),
        "army_share": _to_int(overall.get("totalArmyInsurance")),
        "supplementary_share": _to_int(overall.get("totalSupplementaryInsurance")),
    }
    # Headline revenue card now reflects the business definition (not the gross
    # services amount).
    total_amount = total_revenue

    modality_by_code = {str(m.get("modality")): m for m in by_modality}
    highlight_cards = []
    for code, label in _HIGHLIGHT_MODALITIES:
        m = modality_by_code.get(code) or {}
        highlight_cards.append(
            {
                "code": code,
                "label": label,
                "count": _to_int(m.get("count")),
                "patients": _to_int(m.get("uniquePatients")),
                "amount": _to_int(m.get("totalAmount")),
            }
        )

    # --- Charts --------------------------------------------------------------
    modality_rows = [
        {
            "label": str(m.get("modalityFullName") or _MODALITY_LABELS.get(str(m.get("modality")), str(m.get("modality")))),
            "count": _to_int(m.get("count")),
            "percent": float(m.get("percentageOfTotal") or 0.0),
            "amount": _to_int(m.get("totalAmount")),
        }
        for m in by_modality
    ]
    modality_rows.sort(key=lambda r: r["count"], reverse=True)

    insurance_rows = [
        {
            "label": str(i.get("insuranceTypeLabel") or i.get("insuranceType")),
            "count": _to_int(i.get("count")),
            "percent": float(i.get("percentageOfTotal") or 0.0),
            "amount": _to_int(i.get("totalAmount")),
        }
        for i in by_insurance
    ]
    insurance_rows.sort(key=lambda r: r["count"], reverse=True)

    # Daily trend — aggregate receptions by Jalali Date (client-side, since the
    # API summary has no time series). Sorted chronologically by the string,
    # which is safe for zero-padded "YYYY/MM/DD".
    daily_counts: Dict[str, int] = {}
    for rec in receptions:
        d = str(rec.get("Date") or "").strip()
        if d:
            daily_counts[d] = daily_counts.get(d, 0) + 1
    daily_rows = [{"date": d, "count": c} for d, c in sorted(daily_counts.items())]

    # --- Recent-admissions table --------------------------------------------
    table_rows: List[Dict[str, Any]] = []
    for rec in receptions[:_TABLE_MAX_ROWS]:
        pd = rec.get("patientDetails") or {}
        patient_name = (
            pd.get("fullName")
            or pd.get("name")
            or pd.get("FullName")
            or " ".join(str(x) for x in [pd.get("firstName"), pd.get("lastName")] if x)
        ).strip() if isinstance(pd, dict) else ""
        svc = rec.get("service") or {}
        service_name = svc.get("name") or svc.get("title") if isinstance(svc, dict) else ""
        table_rows.append(
            {
                "receptionId": rec.get("ReceptionID"),
                "date": rec.get("Date"),
                "time": rec.get("Time"),
                "patient": patient_name or "-",
                "modality": str(
                    (rec.get("modalityDetails") or {}).get("fullName")
                    if isinstance(rec.get("modalityDetails"), dict)
                    else ""
                ) or _MODALITY_LABELS.get(str(rec.get("modality")), str(rec.get("modality") or "-")),
                "insurance": rec.get("insuranceTypeLabel") or "-",
                "service": service_name or "-",
                "amount": _to_int(rec.get("totalAmount")),
            }
        )

    return {
        "cards": {
            "total_patients": total_patients,
            "total_receptions": total_receptions,
            "total_services": total_services,
            "total_amount": total_amount,
        },
        "financial": financial,
        "highlight_cards": highlight_cards,
        "modality_rows": modality_rows,
        "insurance_rows": insurance_rows,
        "daily_rows": daily_rows,
        "table_rows": table_rows,
        "row_count_fetched": len(receptions),
        "total_count": _to_int(pagination.get("totalCount")) or total_receptions,
    }


# ---------------------------------------------------------------------------
# REST client
# ---------------------------------------------------------------------------
class AdmissionReportsClient:
    """Thin REST client for the admission Reports API (auth reused, not stored)."""

    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        self._base_url = (base_url or get_reception_api_base_url()).rstrip("/")
        try:
            self._timeout = int(timeout) if timeout else max(15, int(get_reception_api_timeout()))
        except Exception:
            self._timeout = 15

    # -- auth --------------------------------------------------------------
    def _bearer(self) -> Optional[str]:
        try:
            tok = get_socket_token_manager().get_token()
            return tok or None
        except Exception:
            return None

    def _headers(self) -> Dict[str, str]:
        tok = self._bearer()
        if not tok:
            raise AdmissionAuthError("no active session token")
        return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

    def try_reauth(self) -> bool:
        """Best-effort re-login using the saved 'remember me' credentials.

        Only succeeds when the user previously chose to store credentials.
        On success the fresh JWT is written back into the SocketTokenManager so
        every channel (including this one) picks it up. Returns True on success.
        This method performs one blocking HTTP call and is therefore only ever
        invoked from the worker thread, never the GUI thread.
        """
        if requests is None:
            return False
        try:
            if os.name == "nt":
                base_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "AIPacs")
            else:
                base_dir = os.path.join(os.path.expanduser("~"), ".aipacs")
            cfg_path = os.path.join(base_dir, "login_config.json")
            if not os.path.exists(cfg_path):
                return False
            with open(cfg_path, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            username = (cfg.get("username") or "").strip()
            password = cfg.get("password") or ""
            if not username or not password:
                return False
            resp = requests.post(
                f"{self._base_url}{LOGIN_PATH}",
                json={"username": username, "password": password},
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                return False
            body = resp.json()
            token = body.get("token")
            if not token:
                return False
            get_socket_token_manager().set_token(token, body.get("user"))
            logger.info("[admission-api] session re-authenticated via saved credentials")
            return True
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[admission-api] re-auth attempt failed: %s", exc)
            return False

    # -- fetch -------------------------------------------------------------
    def fetch_report(
        self,
        start_date: str,
        end_date: str,
        *,
        limit: int = _DEFAULT_ROW_LIMIT,
        modality: Optional[str] = None,
        insurance_type: Optional[str] = None,
        sort_by: str = "Date",
        sort_order: str = "desc",
        _allow_reauth: bool = True,
    ) -> Dict[str, Any]:
        """Fetch one report page (summary + rows). Blocking — worker-thread only."""
        if requests is None:
            raise AdmissionApiError("requests library unavailable")

        if reception_api_breaker_open(self._base_url):
            raise AdmissionApiError("admission API temporarily unavailable (circuit open)")

        params = {
            "startDate": start_date,
            "endDate": end_date,
            "page": 1,
            "limit": int(limit),
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        if modality:
            params["modality"] = modality
        if insurance_type:
            params["insuranceType"] = insurance_type

        url = f"{self._base_url}{REPORT_PATH}"
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=self._timeout)
        except AdmissionAuthError:
            raise
        except requests.exceptions.Timeout as exc:
            record_reception_api_failure(self._base_url)
            raise AdmissionApiError("timeout contacting admission server") from exc
        except requests.exceptions.ConnectionError as exc:
            record_reception_api_failure(self._base_url)
            raise AdmissionApiError("cannot reach admission server") from exc
        except Exception as exc:
            record_reception_api_failure(self._base_url)
            raise AdmissionApiError(f"request failed: {exc}") from exc

        if resp.status_code in (401, 403):
            # Session expired — try a single silent re-login, then retry once.
            if _allow_reauth and self.try_reauth():
                return self.fetch_report(
                    start_date, end_date, limit=limit, modality=modality,
                    insurance_type=insurance_type, sort_by=sort_by,
                    sort_order=sort_order, _allow_reauth=False,
                )
            raise AdmissionAuthError("session expired (HTTP %d)" % resp.status_code)

        if resp.status_code >= 400:
            record_reception_api_failure(self._base_url)
            raise AdmissionApiError(f"server returned HTTP {resp.status_code}")

        try:
            payload = resp.json()
        except Exception as exc:
            record_reception_api_failure(self._base_url)
            raise AdmissionApiError("invalid JSON from admission server") from exc

        record_reception_api_success(self._base_url)
        return payload


# ---------------------------------------------------------------------------
# Background worker — fetch + build snapshot off the GUI thread.
# ---------------------------------------------------------------------------
class AdmissionReportsWorker(QObject):
    """Runs one fetch+build on a daemon thread and emits the result.

    Signals (all delivered queued onto the GUI thread by Qt):
      * ``finished(dict)``       — the ready dashboard snapshot
      * ``failed(str, str)``     — (human message, kind) where kind is
                                   ``'auth'`` or ``'network'``
    A new worker is created per refresh; overlapping refreshes are coalesced by
    the widget, so at most one worker is ever in flight.
    """

    finished = Signal(object)      # snapshot dict
    failed = Signal(str, str)      # (message, kind)

    def start(
        self,
        client: AdmissionReportsClient,
        start_date: str,
        end_date: str,
        *,
        modality: Optional[str] = None,
        insurance_type: Optional[str] = None,
    ) -> None:
        def _run() -> None:
            try:
                payload = client.fetch_report(
                    start_date, end_date, modality=modality, insurance_type=insurance_type
                )
                snapshot = build_admission_snapshot(payload)
            except AdmissionAuthError as exc:
                logger.warning("[admission-api] auth error: %s", exc)
                self._safe_fail("نشست کاربری منقضی شده است. لطفاً دوباره وارد شوید.", "auth")
                return
            except AdmissionApiError as exc:
                logger.warning("[admission-api] api error: %s", exc)
                self._safe_fail("خطا در ارتباط با سرور پذیرش. دوباره تلاش کنید.", "network")
                return
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("[admission-api] unexpected error: %s", exc)
                self._safe_fail("خطای غیرمنتظره در دریافت داده‌ها.", "network")
                return
            try:
                self.finished.emit(snapshot)
            except RuntimeError:
                pass  # receiver destroyed during shutdown

        threading.Thread(target=_run, name="AdmissionReportsFetch", daemon=True).start()

    def _safe_fail(self, message: str, kind: str) -> None:
        try:
            self.failed.emit(message, kind)
        except RuntimeError:
            pass
