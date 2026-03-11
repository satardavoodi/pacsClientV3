from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from modules.EchoMind.secretary.executor import SecretaryExecutor
from modules.EchoMind.secretary.parser_rules import parse_command_rule


class _FakeAdapter:
    def __init__(self, rows):
        self._rows = rows
        self.last_search = None

    def is_available(self):
        return True

    def get_active_source(self):
        return "server"

    def search(self, source, criteria):
        self.last_search = {"source": source, "criteria": dict(criteria)}

    def list_rows(self):
        return self._rows


class TestParserAndExecutorDate(unittest.TestCase):
    def test_persian_yesterday_maps_to_list_and_range(self):
        plan = parse_command_rule("لیست بیماران دیروز رو به من نشون بده")
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["action"], "list_patients")
        self.assertIn("date", plan["entities"])
        self.assertIn("..", str(plan["entities"]["date"]))

    def test_executor_filters_yesterday_rows(self):
        y = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
        t = datetime.now().strftime("%Y%m%d")
        rows = [
            {
                "patient_id": "P1",
                "patient_name": "Yesterday Match",
                "study_uid": "S1",
                "modality": "CT",
                "date": y,
            },
            {
                "patient_id": "P2",
                "patient_name": "Today NonMatch",
                "study_uid": "S2",
                "modality": "CT",
                "date": t,
            },
        ]
        adapter = _FakeAdapter(rows)
        executor = SecretaryExecutor(adapter)

        plan = {
            "action": "list_patients",
            "entities": {"date": "yesterday"},
            "confidence": 0.9,
            "needs_confirmation": False,
            "reason": "test",
        }
        result = executor.execute(plan, state={})
        self.assertTrue(result["ok"])
        data = result["data"] or []
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["patient_id"], "P1")


if __name__ == "__main__":
    unittest.main()
