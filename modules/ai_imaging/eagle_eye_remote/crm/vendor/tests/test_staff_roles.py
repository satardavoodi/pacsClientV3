"""The typist target is neither the change actor nor the performing doctor."""
from reception_crm.local.staff_roles import typist_assignments
from reception_crm.llm import interpreter, prompt_store

TYPIST_A = "a" * 24
TYPIST_B = "b" * 24
DOCTOR = "c" * 24
ACTOR = "d" * 24


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def limit(self, count):
        return iter(self.docs[:count])


class Collection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query, projection):
        assert query == {
            "action": {"$in": ["typist_assigned", "typist_changed"]},
            "field": "typist", "persianDate": {"$gte": "1405/06/12", "$lte": "1405/06/12"},
        }
        assert "newValue" in projection
        assert not ({"content", "findings", "changedBy", "radiologist"} & projection.keys())
        return Cursor(self.docs)


def event(report, typist, time="10:00:00", **kwargs):
    return dict(receptionID=report, newValue=typist, persianDate="1405/06/12",
                persianTime=time, **kwargs)


def run(docs, max_scan=20000, limit=50):
    return typist_assignments(
        {"ReportLogs": Collection(docs)}, {"$gte": "1405/06/12", "$lte": "1405/06/12"},
        max_scan=max_scan, limit=limit,
        resolve_names=lambda ids: {key: {TYPIST_A: "Typist A", TYPIST_B: "Typist B"}[key]
                                  for key in ids if key in {TYPIST_A, TYPIST_B}},
    )


def test_latest_assignment_deduplicates_and_ignores_actor_and_doctor():
    out = run([
        event(1, TYPIST_B, "11:00:00", changedBy=ACTOR, radiologist=DOCTOR),
        event(1, TYPIST_A, "10:00:00", changedBy=None),
        event(2, TYPIST_A, changedBy=None),
        event(2, TYPIST_A, "10:01:00", changedBy=ACTOR),
    ])
    assert out["assigned_reports"] == 2
    assert out["assignment_events"] == 4
    assert {row["userId"]: row["assigned_reports"] for row in out["rows"]} == {TYPIST_A: 1, TYPIST_B: 1}
    assert all(row["userId"] not in {ACTOR, DOCTOR} for row in out["rows"])
    assert "تایپ قطعی" in out["meaning_fa"]


def test_missing_targets_unresolved_names_and_bad_time_are_not_guessed():
    out = run([
        event(1, TYPIST_A), event(1, None, "11:00:00"),
        event(2, "not a user id"), event(3, DOCTOR),
        event(4, TYPIST_A), event(4, TYPIST_B, ""), event(None, TYPIST_A),
    ])
    assert out["reports_missing_or_invalid_target"] == 2
    assert out["reports_with_unresolved_typist_name"] == 1
    assert out["reports_with_unorderable_events"] == 1
    assert out["events_missing_reception_id"] == 1
    assert out["assigned_reports"] == 1
    assert out["rows"][0]["name"] is None
    assert "not a user id" not in str(out)


def test_both_scan_cap_and_roster_limit_are_visible():
    out = run([event(1, TYPIST_A), event(2, TYPIST_B), event(3, TYPIST_B)], max_scan=2, limit=1)
    assert out["capped"] is True
    assert out["rows_truncated"] is True
    assert out["assigned_reports"] == 2
    assert out["assignment_events"] == 2
    assert len(out["rows"]) == 1


def test_empty_is_not_an_authorship_claim():
    out = run([])
    assert out["rows"] == []
    assert out["assigned_reports"] == 0
    assert out["capped"] is False


def test_role_rules_reach_both_answer_modes():
    shared = prompt_store.read_default("crm_data_analysis.md")
    assert "performing PHYSICIAN" in shared
    assert "changedBy" in shared and "not proven authorship" in shared
    for name in ("answer_analysis.md", "answer_report.md"):
        prompt = prompt_store.read_default(name)
        assert "typist_assignments.rows" in prompt
        assert "report_content_activity.distinct_edited_reports" in prompt


def test_corroborating_payload_keeps_role_and_edit_evidence():
    payload = {
        "role_definitions": {"service_performer": "physician"},
        "typist_assignments": {"assigned_reports": 122},
        "report_content_activity": {"distinct_edited_reports": 122, "reports_with_attributed_edits": 4},
    }
    result = interpreter.build_corroborating_payload("staff.activity", payload)
    assert "typist_assignments" in str(result)
    assert "report_content_activity" in str(result)
    assert "service_performer" in str(result)
