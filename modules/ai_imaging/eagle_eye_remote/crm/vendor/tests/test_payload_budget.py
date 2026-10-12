"""What survives the trip from the tool result into the model's prompt.

Measured against the deployed server on 1405/06/02, before this change:

    patient-list      100,192 chars -> cut to 12,000.  88,192 thrown away.
    reception.search   39,220 chars -> cut to 12,000.  27,220 thrown away.

In both cases nearly all of it was a display row list — `patients` was 99.7% of
one payload and `rows` 98.7% of the other — while every figure the answer needed
(`totals`, `breakdown`, `filters`) is a few hundred characters. The old slice cut
by character count, so it spent the whole budget on the sample and dropped
`rowsInfo`, the note saying the rows ARE only a sample, while keeping the rows.

Trimming the list instead of slicing the string gives the model more usable
information, not less.
"""

from __future__ import annotations

import json

from reception_crm.llm import interpreter


def _big_search_result(rows: int = 100) -> dict:
    """The real shape of `reception.search`, at the size it actually reaches."""
    return {
        "skill": "reception.search",
        "filters": {"dateFrom": "1405/06/02", "dateTo": "1405/06/02"},
        "period": {"from": "1405/06/02", "to": "1405/06/02"},
        "totals": {"patients": 213, "receptions": 219, "serviceLines": 267,
                   "discountAmount": 1_730_000},
        "count": 219,
        "figuresAreComplete": True,
        "breakdown": {"by": "modality", "nMeans": "receptions",
                      "items": [{"value": "2", "n": 61, "patients": 61}]},
        "rows": [
            {"ReceptionID": 55000 + i, "Date": "1405/06/02", "Time": "10:%02d:00" % (i % 60),
             "modality": "MRI", "insuranceType": "2", "totalAmount": 3_500_000,
             "patientTotal": 2_900_000, "settled": True,
             "services": ["MRI کانال و محتویات ناحیه لومبر بدون کنتراست"],
             "patientRef": "a" * 24, "discountAmount": 0}
            for i in range(rows)
        ],
        "rowsInfo": {"shown": rows, "note": "display sample, never the basis of a count"},
    }


def test_the_row_list_really_is_what_blows_the_budget():
    """Establishes the premise rather than asserting it from memory."""
    data = _big_search_result()
    whole = len(json.dumps(data, ensure_ascii=False))
    rows_only = len(json.dumps(data["rows"], ensure_ascii=False))
    assert whole > interpreter.MAX_ANALYSIS_PAYLOAD_CHARS
    assert rows_only / whole > 0.9, "the sample should dominate — that is the problem"


def test_trimming_keeps_every_figure_the_answer_needs():
    payload = interpreter.build_analysis_payload(_big_search_result())
    assert len(payload) <= interpreter.MAX_ANALYSIS_PAYLOAD_CHARS

    # The whole point: these survive, where the character slice could drop them.
    restored = json.loads(payload)
    assert restored["totals"]["receptions"] == 219
    assert restored["totals"]["patients"] == 213
    assert restored["breakdown"]["items"]
    assert restored["figuresAreComplete"] is True
    assert restored["rowsInfo"], "the note explaining the sample must not be the casualty"


def test_the_trimmed_payload_is_still_valid_json():
    """A character slice produces a fragment cut mid-object. The model then has
    to guess where the data ended, which is how a partial list gets read as a
    whole one."""
    payload = interpreter.build_analysis_payload(_big_search_result())
    json.loads(payload)  # raises if the old slicing path was taken


def test_the_omission_is_stated_with_its_count_and_a_do_not_count_warning():
    restored = json.loads(interpreter.build_analysis_payload(_big_search_result()))
    omitted = restored["rows_omitted"]
    assert omitted["total"] == 100
    assert omitted["shown"] == interpreter.DISPLAY_SAMPLE_KEPT
    assert "Never count these rows" in omitted["note"]
    assert "شمارش نکن" in omitted["note_fa"]
    assert len(restored["rows"]) == interpreter.DISPLAY_SAMPLE_KEPT


def test_a_small_payload_is_passed_through_untouched():
    """Trimming is for payloads that do not fit. A small result must arrive
    whole — including all of its rows."""
    small = _big_search_result(rows=3)
    payload = interpreter.build_analysis_payload(small)
    assert json.loads(payload) == small
    assert "rows_omitted" not in payload


def test_patient_list_shaped_results_are_trimmed_too():
    """`patients` was 99.7% of a 100 KB payload — the worst offender measured."""
    data = {
        "skill": "patient-list",
        "filter": {"date": "1405/06/02"},
        "period": {"from": "1405/06/02", "to": "1405/06/02"},
        "patients": [{"row": i, "service": "x" * 200} for i in range(300)],
        "source_paths": {"a": "b"},
    }
    restored = json.loads(interpreter.build_analysis_payload(data))
    assert len(restored["patients"]) == interpreter.DISPLAY_SAMPLE_KEPT
    assert restored["patients_omitted"]["total"] == 300
    # The trailing keys used to be cut off entirely by the character slice.
    assert restored["source_paths"] == {"a": "b"}


def test_a_large_payload_with_no_row_list_uses_a_valid_structured_fallback():
    """Not every oversized result is rows, but none may become a JSON fragment."""
    data = {"skill": "x", "blob": {"k%d" % i: "v" * 50 for i in range(500)}}
    payload = interpreter.build_analysis_payload(data)
    restored = json.loads(payload)
    assert restored["payloadCompacted"] is True
    assert len(payload) < len(json.dumps(data, ensure_ascii=False))


def test_trimming_reports_nothing_to_do_when_lists_are_short():
    assert interpreter._trim_display_lists({"rows": [1, 2]}) is None
    assert interpreter._trim_display_lists("not a dict") is None


def test_reconciliation_corroboration_keeps_debt_and_risk_summary_as_valid_json():
    data = {
        "skill": "cashier-reconciliation",
        "period": {"start_date": "1405/06/02", "end_date": "1405/06/02"},
        "expected_vs_actual": {"same_reception_difference": 0, "transaction_date_difference": 100},
        "supporting_financials": {
            "basis": "service", "patient_debt": 1_637_600_000,
            "settled_count": 178, "unsettled_count": 41,
        },
        "possible_causes": ["پرداخت مربوط به پذیرش روز دیگر"],
        "high_risk_receptions": [
            {
                "total_amount": 300_000_000, "settled": False,
                "discount_amount": 1, "update_history_count": 7,
                "risk_factors": ["ویرایش مکرر"], "patient_name": "نباید ارسال شود",
            },
            {
                "total_amount": 142_240_000, "settled": True,
                "discount_amount": 0, "update_history_count": 1, "risk_factors": [],
            },
        ],
    }
    payload = interpreter.build_corroborating_payload("cashier-reconciliation", data)
    restored = json.loads(payload)
    assert restored["supporting_financials"]["unsettled_count"] == 41
    assert restored["high_risk_summary"]["count"] == 2
    assert restored["high_risk_summary"]["total_amount"] == 442_240_000
    assert restored["high_risk_summary"]["repeated_edits_count"] == 1
    assert "patient_name" not in payload


def test_generic_corroboration_never_returns_a_cut_json_fragment():
    data = {"skill": "unknown", "rows": [{"blob": "x" * 2000} for _ in range(100)]}
    payload = interpreter.build_corroborating_payload("unknown", data)
    restored = json.loads(payload)
    assert len(payload) <= interpreter.MAX_EVIDENCE_CHARS
    assert restored


def test_nested_multistep_payload_trims_rows_recursively_and_keeps_later_sources():
    risks = [
        {
            "cashier": "کاربر الف",
            "total_amount": 10 + i,
            "settled": i % 2 == 0,
            "update_history_count": i,
            "risk_factors": ["ویرایش مکرر"] if i >= 5 else [],
        }
        for i in range(8)
    ]
    data = {
        "steps": [
            {"tool": "reception.search", "data": _big_search_result(rows=100)},
            {
                "tool": "risk-analysis",
                "data": {
                    "skill": "risk-analysis",
                    "high_risk_receptions": risks,
                    "distribution": {"high": {"count": 8}},
                },
            },
            {
                "tool": "reception.search",
                "arguments": {"deletedOnly": True},
                "data": {"totals": {"receptions": 2}, "rows": [{"x": "y"}]},
            },
        ]
    }

    restored = json.loads(interpreter.build_analysis_payload(data))
    assert len(restored["steps"][0]["data"]["rows"]) == interpreter.DISPLAY_SAMPLE_KEPT
    assert restored["steps"][0]["data"]["rows_omitted"]["total"] == 100
    assert len(restored["steps"][1]["data"]["high_risk_receptions"]) == 8
    assert restored["steps"][2]["data"]["totals"]["receptions"] == 2


def test_risk_corroboration_aggregates_every_row_without_patient_phi():
    rows = [
        {
            "cashier": "الف" if i < 5 else "ب",
            "patient_name": f"بیمار {i}",
            "total_amount": 100,
            "settled": i % 2 == 0,
            "discount_amount": 1 if i == 0 else 0,
            "update_history_count": 6 if i in {1, 6} else 1,
            "risk_factors": ["ویرایش مکرر"] if i in {1, 6} else [],
        }
        for i in range(8)
    ]
    payload = interpreter.build_corroborating_payload(
        "risk-analysis",
        {
            "skill": "risk-analysis",
            "period": {"start_date": "1405/06/11", "end_date": "1405/06/11"},
            "distribution": {"high": {"count": 8}},
            "high_risk_receptions": rows,
        },
    )
    restored = json.loads(payload)
    grouped = restored["high_risk_by_reception_creator"]
    assert sum(item["count"] for item in grouped) == 8
    assert grouped[0]["reception_creator"] == "الف"
    assert grouped[0]["count"] == 5
    assert restored["high_risk_summary"]["count"] == 8
    assert "patient_name" not in payload
