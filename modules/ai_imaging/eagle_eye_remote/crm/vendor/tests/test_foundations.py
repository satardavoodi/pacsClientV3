from __future__ import annotations

import unittest
import tempfile
import json
from datetime import date
from pathlib import Path

from reception_crm.ino_api import InoClient
from reception_crm.jalali import gregorian_to_jalali, jalali_to_gregorian
from reception_crm.management import _num
from reception_crm.permissions import PermissionPolicy
from reception_crm.collector import date_params
from reception_crm.core.registry import default_registry
from reception_crm.core.dispatcher import dispatch
from reception_crm.core.types import DispatchContext, Principal, ToolCall
from reception_crm.core.tools.reports import approval_flags_for_status, build_report_html


class FakePaginatedClient(InoClient):
    def __init__(self) -> None:
        super().__init__(username="u", password="p")
        self.pages = {
            1: {
                "success": True,
                "data": {
                    "receptions": [{"ReceptionID": 1}, {"ReceptionID": 2}],
                    "summary": {"overall": {"totalReceptions": 3}},
                    "pagination": {
                        "currentPage": 1,
                        "totalPages": 2,
                        "totalCount": 3,
                        "limit": 2,
                        "hasNextPage": True,
                    },
                },
            },
            2: {
                "success": True,
                "data": {
                    "receptions": [{"ReceptionID": 3}],
                    "summary": {"overall": {"totalReceptions": 3}},
                    "pagination": {
                        "currentPage": 2,
                        "totalPages": 2,
                        "totalCount": 3,
                        "limit": 2,
                        "hasNextPage": False,
                    },
                },
            },
        }
        self.requested_pages: list[int] = []

    def get_json(self, path, params=None):  # type: ignore[override]
        self.requested_pages.append(int(params["page"]))
        return self.pages[int(params["page"])]


class FakeDeletedTransactionsClient(InoClient):
    def __init__(self) -> None:
        super().__init__(username="u", password="p")
        self.requested_pages: list[int] = []

    def get_json(self, path, params=None):  # type: ignore[override]
        page = int(params["page"])
        self.requested_pages.append(page)
        rows = [{"_id": str(i)} for i in ([1, 2] if page == 1 else [3, 4])]
        return {
            "success": True,
            "data": {
                "transactions": rows,
                "pagination": {
                    "currentPage": page,
                    "totalPages": 2,
                    "totalCount": 4,
                    "hasNextPage": page == 1,
                },
            },
        }


class FoundationTests(unittest.TestCase):
    def test_jalali_roundtrip(self) -> None:
        for value in [date(2026, 7, 11), date(2025, 3, 20), date(2024, 2, 29)]:
            self.assertEqual(jalali_to_gregorian(gregorian_to_jalali(value)), value)

    def test_pagination_over_1000(self) -> None:
        client = FakePaginatedClient()
        result = client.patients_by_service_insurance("1405/04/20", "1405/04/20", limit=2)
        self.assertEqual(client.requested_pages, [1, 2])
        self.assertEqual([row["ReceptionID"] for row in result["data"]["receptions"]], [1, 2, 3])
        self.assertEqual(result["data"]["pagination"]["collectedCount"], 3)

    def test_deleted_transaction_pagination_is_bounded_and_marks_incompleteness(self) -> None:
        client = FakeDeletedTransactionsClient()
        result = client.cashier_deleted_transactions(
            "1405/06/11", "1405/06/11", max_items=3
        )
        self.assertEqual(client.requested_pages, [1, 2])
        self.assertEqual([row["_id"] for row in result["data"]["transactions"]], ["1", "2", "3"])
        self.assertFalse(result["data"]["pagination"]["collectionComplete"])
        self.assertEqual(result["data"]["pagination"]["collectedCount"], 3)

    def test_num_formatted_input(self) -> None:
        self.assertEqual(_num("1,234"), 1234)
        self.assertEqual(_num("۱٬۲۳۴"), 1234)
        self.assertEqual(_num(" 12,345.0 "), 12345)
        self.assertEqual(_num(None), 0)

    def test_permission_unknown_user_default_denies(self) -> None:
        policy = PermissionPolicy(
            {
                "roles": {"agent_readonly": {"can_read": ["*"], "can_plan": [], "can_execute": []}},
                "users": {"known": {"center": "RAZI", "roles": ["agent_readonly"]}},
            },
            Path("test-roles.json"),
        )
        self.assertFalse(policy.check("unknown", "RAZI", "reports.patients_by_service_insurance", "read", "read").allowed)
        self.assertTrue(policy.check("known", "RAZI", "reports.patients_by_service_insurance", "read", "read").allowed)

    def test_collector_uses_jalali_date_when_configured(self) -> None:
        params = date_params(
            {"start_param": "startDate", "end_param": "endDate", "format": "YYYY/MM/DD"},
            date(2026, 7, 11),
        )
        self.assertEqual(params, {"startDate": "1405/04/20", "endDate": "1405/04/20"})

    def test_core_registry_has_analytics_and_reporting_tools(self) -> None:
        registry = default_registry()
        self.assertEqual(
            set(registry.tools),
            {
                "daily-summary",
                "patient-list",
                "financial-analysis",
                "cashier-reconciliation",
                # The reception software's own reports, rather than something
                # derived from a different endpoint that happens to be nearby.
                "cashier-report",
                "cashier-deleted-transactions",
                "physician-performance",
                "risk-analysis",
                "trend-analysis",
                "reporting-queue",
                "report-current",
                "report-logs",
                "report-print-preview",
                "report-template-list",
                "report-template-search",
                "report-template-get",
                "report-template-refresh",
                "report-draft-plan",
                # Patient/appointment reads (docs/RECEPTION_CRM_INTEGRATION.md §7.2)
                "patients.search",
                "appointments.list",
                # Clinical report retrieval and search, read straight from the
                # reception database on this machine. The vendor HTTP API has no
                # equivalent — see docs/LOCAL_CAPABILITY_REVIEW.md.
                "report.get",
                "report.search",
                "report.history",
                "report.archive-stats",
                # The reception RECORD rather than the report text: what was
                # performed, for whom, under which insurer. Added because
                # "how many mammograms" has no answer in any of the above —
                # mammography is a service here, not a modality.
                "reception.search",
                "reception.vocabulary",
                # Cross-checks between records, reports and files on disk.
                "integrity.missing-reports",
                "integrity.broken-files",
                "integrity.post-approval-edits",
                # The four capabilities the v3 challenge benchmark found
                # missing. Twenty-one of seventy questions were unanswerable
                # without them, and every field they read was already populated
                # in the database the agent was reading — the gap was the tool,
                # not the record. `appointments.day` is the DIARY and is
                # deliberately not `appointments.list`, which is the waiting
                # queue: the first draft of it claimed that name and replaced
                # the queue tool in silence.
                "marketing.referrers",
                "staff.activity",
                "audit.name-changes",
                "appointments.day",
                "appointments.availability",
                "appointments.vs-receptions",
                # The PATIENT chat, on the central IranNoobat server. The only
                # tool here that reads a source which is not on this machine —
                # and the only subject the agent used to answer with somebody
                # else's data rather than admitting it could not see it.
                "conversation.summary",
                # Money asked for BY MEANING rather than by field, and the
                # catalogue that makes a metric something you look up instead of
                # guess at. Both delegate to the report tools above through the
                # same dispatcher — they add semantics, not a second data path.
                "finance.metric",
                "finance.vocabulary",
                # The first — and currently only — write, gated by confirmation,
                # idempotency, operations.json `enabled`, and RECEPTION_ENABLE_WRITES.
                "appointments.schedule",
            },
        )

    def test_dispatch_validates_required_input(self) -> None:
        result = dispatch(
            ToolCall("daily-summary", {"date": "today"}),
            context=DispatchContext(audit=False),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "VALIDATION")

    def test_dispatch_permission_denies_unknown_user_for_read(self) -> None:
        result = dispatch(
            ToolCall("daily-summary", {"date": "today", "data_root": "D:\\RAZI crm"}),
            context=DispatchContext(principal=Principal(user="unknown", center="RAZI"), audit=False),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "PERMISSION_DENIED")

    def test_report_html_builder_defaults_to_rtl_and_wraps_ltr_segments(self) -> None:
        html = build_report_html("کبد طبیعی است. اندازه 105 mm")
        self.assertIn('text-align: right; direction: rtl', html)
        self.assertIn('dir="ltr"', html)
        self.assertIn("105 mm", html)

    def test_report_status_flags_mapping(self) -> None:
        self.assertEqual(approval_flags_for_status("pending"), {"physicianApproved": False, "secretaryApproved": False})
        self.assertEqual(approval_flags_for_status("awaiting_secretary_approval"), {"physicianApproved": True, "secretaryApproved": False})
        self.assertEqual(approval_flags_for_status("completed"), {"physicianApproved": True, "secretaryApproved": True})

    def test_report_template_list_reads_local_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            template_dir = Path(tmp) / "data" / "templates" / "report" / "US" / "normal"
            template_dir.mkdir(parents=True)
            (template_dir / "abdomen.json").write_text(
                json.dumps(
                    {
                        "template_id": "us-abdomen-normal",
                        "title_fa": "گزارش نرمال شکم",
                        "modality": "US",
                        "modality_id": "3",
                        "category": "تشخیصی",
                        "body_part": "abdomen",
                        "content_html": "<p>کبد طبیعی است.</p>",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = dispatch(
                ToolCall("report-template-list", {"data_root": tmp}),
                context=DispatchContext(principal=Principal(user="vahid", center="RAZI"), audit=False),
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.data["count"], 1)
            self.assertEqual(result.data["templates"][0]["template_id"], "us-abdomen-normal")
            search_result = dispatch(
                ToolCall("report-template-search", {"data_root": tmp, "query": "کبد", "modality_id": "3"}),
                context=DispatchContext(principal=Principal(user="vahid", center="RAZI"), audit=False),
            )
            self.assertTrue(search_result.ok)
            self.assertEqual(search_result.data["count"], 1)
            self.assertEqual(search_result.data["results"][0]["template_id"], "us-abdomen-normal")

    def test_report_draft_plan_denies_readonly_user(self) -> None:
        result = dispatch(
            ToolCall("report-draft-plan", {"reception_id": "50142", "report_text": "متن آزمایشی"}),
            context=DispatchContext(principal=Principal(user="local_cli", center="RAZI"), audit=False),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error["code"], "PERMISSION_DENIED")


if __name__ == "__main__":
    unittest.main()
