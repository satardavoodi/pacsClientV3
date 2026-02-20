from __future__ import annotations

import unittest

from EchoMind.secretary.errors import (
    ERR_INVALID_ACTION,
    ERR_INVALID_TYPE,
    ERR_INVALID_VALUE,
    ERR_MISSING_FIELD,
)
from EchoMind.secretary.validator import validate_plan


class TestSecretaryValidator(unittest.TestCase):
    def _valid_list_plan(self):
        return {
            "action": "list_patients",
            "entities": {"source": "active_tab", "date": "today", "modality": "MR"},
            "confidence": 0.91,
            "needs_confirmation": False,
            "reason": "rule: list command",
        }

    def test_valid_plan_passes(self):
        normalized, errors = validate_plan(self._valid_list_plan())
        self.assertIsNotNone(normalized)
        self.assertEqual(errors, [])

    def test_missing_field(self):
        plan = self._valid_list_plan()
        del plan["reason"]
        normalized, errors = validate_plan(plan)
        self.assertIsNone(normalized)
        self.assertTrue(any(e.code == ERR_MISSING_FIELD and e.field == "reason" for e in errors))

    def test_wrong_type(self):
        plan = self._valid_list_plan()
        plan["entities"] = "not-an-object"
        normalized, errors = validate_plan(plan)
        self.assertIsNone(normalized)
        self.assertTrue(any(e.code == ERR_INVALID_TYPE and e.field == "entities" for e in errors))

    def test_invalid_action(self):
        plan = self._valid_list_plan()
        plan["action"] = "search_patient"
        normalized, errors = validate_plan(plan)
        self.assertIsNone(normalized)
        self.assertTrue(any(e.code == ERR_INVALID_ACTION and e.field == "action" for e in errors))

    def test_confirmation_policy_mismatch(self):
        plan = {
            "action": "download_patient",
            "entities": {"patient_code": "P123"},
            "confidence": 0.9,
            "needs_confirmation": False,
            "reason": "download request",
        }
        normalized, errors = validate_plan(plan)
        self.assertIsNone(normalized)
        self.assertTrue(any(e.code == ERR_INVALID_VALUE and e.field == "needs_confirmation" for e in errors))

    def test_yesterday_date_token_is_valid(self):
        plan = self._valid_list_plan()
        plan["entities"]["date"] = "yesterday"
        normalized, errors = validate_plan(plan)
        self.assertIsNotNone(normalized)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
