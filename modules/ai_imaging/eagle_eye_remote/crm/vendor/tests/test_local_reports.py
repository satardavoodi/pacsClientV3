"""The local report layer: HTML stripping, query shaping, and the read-only rule.

These run without a database. The Mongo-dependent paths are exercised against a
fake collection, because the point of the tests is the query we BUILD and the
shape we RETURN — the driver itself is not ours to test.
"""

from __future__ import annotations

import pytest

from reception_crm.local import html_text, mongo
from reception_crm.local import reports as local_reports


# --------------------------------------------------------------------------- #
# HTML -> text. The 97%-markup problem.
# --------------------------------------------------------------------------- #
def test_strips_markup_and_keeps_the_clinical_text():
    html = (
        '<div style="font-family:Tahoma"><p><b>Findings:</b></p>'
        "<p>No focal lesion identified.</p>"
        "<table><tr><td>Right</td><td>Normal</td></tr></table>"
        "<style>.x{color:red}</style><script>var a=1;</script></div>"
    )
    text = html_text.html_to_text(html)
    assert "Findings:" in text
    assert "No focal lesion identified." in text
    assert "Right" in text and "Normal" in text
    assert "<" not in text and ">" not in text
    assert "color:red" not in text, "style bodies are not content"
    assert "var a=1" not in text, "script bodies are not content"


def test_entities_and_invisible_characters_are_resolved():
    text = html_text.html_to_text("<p>BI&#8209;RADS&nbsp;3 &amp; follow&shy;up‌</p>")
    assert "&" in text and "&amp;" not in text
    assert "‌" not in text, "zero-width joiners cost tokens and break matching"


def test_never_raises_on_malformed_markup():
    for junk in ("<p>unclosed", "<<>>", "<div", None, "", "<p>ok</p" * 500):
        html_text.html_to_text(junk)


def test_truncation_is_marked():
    out = html_text.html_to_text("<p>" + ("word " * 500) + "</p>", max_chars=100)
    assert len(out) < 200
    assert "truncated" in out


def test_looks_empty_recognises_an_untouched_template():
    assert html_text.looks_empty("")
    assert html_text.looks_empty("  \n .. -- // ")
    assert not html_text.looks_empty("No focal lesion identified in either breast. BIRADS 2.")


# --------------------------------------------------------------------------- #
# The two data shapes that silently corrupt a naive query
# --------------------------------------------------------------------------- #
def test_modality_filter_matches_both_storage_shapes():
    """Several hundred receptions embed the whole Modality document instead of
    its code. A plain {"modality": "3"} filter misses them, which reads as
    'we did fewer ultrasounds than we did'."""
    f = local_reports.modality_filter("3")
    assert f == {"$or": [{"modality": "3"}, {"modality._id": "3"}]}


def test_modality_filter_accepts_a_human_name():
    assert local_reports.modality_filter("MRI") == local_reports.modality_filter("2")
    assert local_reports.modality_filter("sonography") == local_reports.modality_filter("3")


def test_modality_filter_is_absent_when_not_asked_for():
    assert local_reports.modality_filter(None) is None
    assert local_reports.modality_filter("") is None


def test_date_filter_only_accepts_jalali_strings():
    """Date is a zero-padded Jalali STRING, so lexicographic ranges are valid.
    createdAt is a real datetime and must never be mixed into the same filter."""
    assert local_reports.date_range_filter("1405/05/01", "1405/05/29") == {
        "Date": {"$gte": "1405/05/01", "$lte": "1405/05/29"}
    }
    assert local_reports.date_range_filter("2026-08-21", None) is None
    assert local_reports.date_range_filter(None, None) is None


def test_phrase_pattern_matches_how_this_archive_really_writes_grades():
    """Measured from the live archive: the grade follows BIRADS as ' :3', ': 2',
    '&nbsp;&nbsp; 2 :' and — critically — as a ROMAN numeral, 'BIRADS:IV'.
    A search for 3 that cannot find III is wrong in a way nobody would notice."""
    import re

    pattern = re.compile(local_reports.phrase_pattern("BIRADS 3"), re.IGNORECASE)
    for real in ("BIRADS :3", "BIRADS: 3", "BI-RADS 3", "BIRADS   3 :", "BIRADS:III", "birads iii"):
        assert pattern.search(real), real
    for wrong in ("BIRADS :2", "BIRADS: 4"):
        assert not pattern.search(wrong), wrong


def test_roman_and_arabic_grades_are_interchangeable():
    import re

    for query, text in (("BIRADS 4", "BIRADS:IV"), ("BIRADS IV", "BIRADS: 4")):
        assert re.search(local_reports.phrase_pattern(query), text, re.IGNORECASE), (query, text)


def test_a_grade_does_not_match_a_higher_grade_that_starts_with_it():
    """Found on the live archive: a search for BI-RADS 5 returned reception
    52047, whose own snippet reads "BIRADS: VI". "V" is a prefix of "VI", and
    "I" is a prefix of "II", "III" and "IV" — so without a boundary the search
    reports a known malignancy as a lower grade. That is the direction of error
    that actually harms someone."""
    import re

    def matches(query, text):
        return bool(re.search(local_reports.phrase_pattern(query), text, re.IGNORECASE))

    assert not matches("BIRADS 5", "BIRADS: VI"), "grade 6 reported as grade 5"
    assert not matches("BIRADS 1", "BIRADS: III")
    assert not matches("BIRADS 1", "BIRADS: IV")
    assert not matches("BIRADS 2", "BIRADS: III")
    assert not matches("BIRADS 4", "BIRADS: 45")

    # ...while the grades themselves still match, in both spellings.
    for query, text in (
        ("BIRADS 5", "BIRADS: V"),
        ("BIRADS 5", "BIRADS 5"),
        ("BIRADS 6", "BIRADS: VI"),
        ("BIRADS 1", "BIRADS: I "),
        ("BIRADS 3", "BIRADS:III</span>"),
    ):
        assert matches(query, text), (query, text)


def test_a_grade_is_not_used_to_narrow_mongo_in_either_spelling():
    """`III` is long enough to look like a good pre-filter word and is exactly
    the wrong one: narrowing on it drops every report that wrote `3`."""
    digits = local_reports._narrow_filter("BIRADS 3")
    romans = local_reports._narrow_filter("BIRADS III")
    assert digits == romans, "the same question must narrow the same way"


def test_narrow_filter_uses_words_not_digits():
    """'3' appears in nearly every report, so it is useless as a pre-filter.
    Only the distinctive word narrows; the digit is decided in phase two."""
    narrow = local_reports._narrow_filter("BIRADS 3")
    assert narrow == {
        "$and": [{"imagingWorkflow.report.content": {"$regex": "BIRADS", "$options": "i"}}]
    }
    assert local_reports._narrow_filter("3") is None, "a bare number cannot narrow anything"


# --------------------------------------------------------------------------- #
# Read-only is structural, not a convention
# --------------------------------------------------------------------------- #
class _FakeCollection:
    name = "receptions"

    def __init__(self, docs=None):
        self.docs = docs or []
        self.last_filter = None

    def find(self, filter=None, projection=None, **kw):
        self.last_filter = filter
        return _FakeCursor(self.docs)

    def find_one(self, filter=None, projection=None, **kw):
        self.last_filter = filter
        return self.docs[0] if self.docs else None

    def aggregate(self, pipeline, **kw):
        return iter([])

    def count_documents(self, filter=None, **kw):
        self.last_filter = filter
        return len(self.docs)

    def estimated_document_count(self, **kw):
        return len(self.docs)

    def distinct(self, key, filter=None, **kw):
        return []

    def index_information(self):
        return {}

    # The methods that must never be reachable through the wrapper.
    def update_one(self, *a, **k):  # pragma: no cover
        raise AssertionError("a write reached the reception database")

    def insert_one(self, *a, **k):  # pragma: no cover
        raise AssertionError("a write reached the reception database")

    def delete_many(self, *a, **k):  # pragma: no cover
        raise AssertionError("a write reached the reception database")

    def create_index(self, *a, **k):  # pragma: no cover
        raise AssertionError("an index was created on a live clinical collection")


class _FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self.docs = self.docs[:n]
        return self

    def __iter__(self):
        return iter(self.docs)


def test_write_methods_are_not_reachable():
    col = mongo.ReadOnlyCollection(_FakeCollection())
    for forbidden in ("update_one", "insert_one", "insert_many", "delete_one",
                      "delete_many", "create_index", "drop", "replace_one",
                      "find_one_and_update", "bulk_write"):
        assert not hasattr(col, forbidden), forbidden


def test_aggregate_refuses_write_stages():
    """$out and $merge write. 'aggregate' must not become a back door."""
    col = mongo.ReadOnlyCollection(_FakeCollection())
    for stage in ({"$out": "copy"}, {"$merge": {"into": "copy"}}):
        with pytest.raises(mongo.LocalMongoUnavailable):
            col.aggregate([{"$match": {}}, stage])


def test_aggregate_allows_ordinary_pipelines():
    col = mongo.ReadOnlyCollection(_FakeCollection())
    assert list(col.aggregate([{"$match": {}}, {"$group": {"_id": None}}])) == []


def test_direct_access_can_be_switched_off(monkeypatch):
    monkeypatch.setenv(mongo.ENV_ENABLED, "false")
    assert mongo.is_enabled() is False
    with pytest.raises(mongo.LocalMongoUnavailable):
        mongo.reception_db()


def test_direct_access_is_on_by_default(monkeypatch):
    monkeypatch.delenv(mongo.ENV_ENABLED, raising=False)
    assert mongo.is_enabled() is True


def test_there_is_no_remote_host_setting():
    """An agent installed at clinic A must not be repointable at clinic B's
    database. The URI is a constant, exactly like local_host.py's rule for the
    HTTP API."""
    assert mongo.DEFAULT_URI.startswith("mongodb://127.0.0.1")


# --------------------------------------------------------------------------- #
# Result shaping
# --------------------------------------------------------------------------- #
def _reception(
    content="<p>Breast: BIRADS 2. No suspicious mass.</p>",
    modality="3",
    services=None,
):
    return {
        "ReceptionID": 55040,
        "Date": "1405/05/29",
        "Time": "08:10:56",
        "modality": modality,
        "nationalCode": "0000000000",
        "patientNameSnapshot": "TEST PATIENT",
        "services": services or [{"Service": "سونوگرافی پستان"}],
        "imagingWorkflow": {
            "workflowStatus": "inProgress",
            "report": {
                "content": content,
                "status": "completed",
                "reportDate": "2026-08-20T00:00:00.000Z",
                "approvalFlags": {"physicianApproved": True},
            },
        },
    }


def test_summarize_row_flattens_and_names_the_modality():
    row = local_reports.summarize_row(_reception(), text="hello")
    assert row["receptionId"] == 55040
    assert row["modalityCode"] == "3"
    assert row["modality"] == "Sonography"
    assert row["physicianApproved"] is True
    assert row["reportStatus"] == "completed"
    assert row["reportText"] == "hello"


def test_summarize_row_handles_the_embedded_modality_document():
    doc = _reception(modality={"_id": "2", "Modality": "MR", "FullName": "MRI"})
    row = local_reports.summarize_row(doc)
    assert row["modalityCode"] == "2"
    assert row["modality"] == "MRI"


def test_get_report_returns_text_not_html(monkeypatch):
    fake = _FakeCollection([_reception()])
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})
    result = local_reports.get_report(reception_id=55040)
    assert result["found"] is True
    assert "<p>" not in result["reportText"]
    assert "BIRADS 2" in result["reportText"]
    assert fake.last_filter["ReceptionID"] == 55040


def test_get_report_requires_an_identifier():
    assert local_reports.get_report()["found"] is False


def test_search_returns_snippets_not_whole_reports(monkeypatch):
    """25 full bodies would be ~19 KB of prompt to answer 'which ones matched'."""
    fake = _FakeCollection([_reception()])
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})
    result = local_reports.search_reports("BIRADS", limit=5)
    assert result["count"] == 1
    row = result["rows"][0]
    assert "reportText" not in row
    assert "BIRADS" in row["snippet"]


def test_search_decides_on_stripped_text_not_html(monkeypatch):
    """The Mongo pre-filter is deliberately loose; phase two is what decides.
    A candidate that does not really contain the phrase must be dropped."""
    hit = _reception(content="<p>Breast <span>BIRADS</span>&nbsp;: 3 probably benign</p>")
    miss = _reception(content="<p>Breast BIRADS : 2 benign</p>")
    fake = _FakeCollection([hit, miss])
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})

    result = local_reports.search_reports("BIRADS 3", limit=5)
    assert result["count"] == 1, "the BIRADS 2 report must not match a search for 3"
    assert result["candidatesScanned"] == 2, "both were candidates; only one matched"
    assert "3" in result["rows"][0]["snippet"]


def test_search_can_apply_service_and_finding_to_the_same_records(monkeypatch):
    """The old planner fetched two capped row samples and asked the model to
    intersect them.  The database query itself must now carry both criteria."""
    fake = _FakeCollection([
        _reception(
            content="<p>L4-L5 broad based disc bulge is present.</p>",
            modality="2",
            services=[{"Service": "ام آر آی ستون فقرات کمری"}],
        )
    ])
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})
    monkeypatch.setattr(
        local_reports.dm,
        "matching_services",
        lambda value, *, modality=None: ["ام آر آی ستون فقرات کمری"],
    )

    result = local_reports.search_reports(
        "disc bulge",
        service="کمر",
        modality="MRI",
        date_from="1405/01/01",
        date_to="1405/06/31",
        approved_only=True,
    )

    assert result["count"] == 1
    assert result["rows"][0]["services"] == ["ام آر آی ستون فقرات کمری"]
    assert result["filters"]["service"]["matchedCatalogServices"] == [
        "ام آر آی ستون فقرات کمری"
    ]
    conditions = fake.last_filter["$and"]
    service_condition = next(
        condition
        for condition in conditions
        if "$or" in condition
        and all("services.Service" in branch for branch in condition["$or"])
    )
    patterns = [
        branch["services.Service"]["$regex"]
        for branch in service_condition["$or"]
    ]
    import re

    for performed_name in (
        "ام آر آی ستون فقرات کمری",
        "MRI کانال spinal لومبر",
        "MRI ناحیه لومبار",
    ):
        assert any(re.search(pattern, performed_name, re.IGNORECASE) for pattern in patterns)
    assert result["filters"]["service"]["canonicalConcept"] == "lumbar_spine"
    assert {"imagingWorkflow.report.approvalFlags.physicianApproved": True} in conditions
    assert local_reports.dm.LIVE_ONLY in conditions


def test_service_filtered_report_search_refuses_an_unbounded_scan(monkeypatch):
    """services.Service has no index; a missing range must fail before Mongo is opened."""
    opened = {"value": False}

    def database():
        opened["value"] = True
        return {"receptions": _FakeCollection()}

    monkeypatch.setattr(local_reports, "reception_db", database)
    with pytest.raises(ValueError, match="both dateFrom and dateTo"):
        local_reports.search_reports("disc bulge", service="کمر")
    assert opened["value"] is False

    with pytest.raises(ValueError, match="both dateFrom and dateTo"):
        local_reports.search_reports(
            "disc bulge",
            service="کمر",
            date_to="1405/06/31",
        )
    assert opened["value"] is False


def test_report_search_refuses_a_reversed_date_range_before_opening_mongo(monkeypatch):
    opened = {"value": False}

    def database():
        opened["value"] = True
        return {"receptions": _FakeCollection()}

    monkeypatch.setattr(local_reports, "reception_db", database)
    with pytest.raises(ValueError, match="dateFrom must not be later"):
        local_reports.search_reports(
            "atrophy",
            date_from="1405/06/31",
            date_to="1405/01/01",
        )
    assert opened["value"] is False


def test_alternative_report_phrases_match_any_without_hardcoded_diseases(monkeypatch):
    docs = [
        _reception("<p>L4-L5 disc bulging is seen.</p>"),
        _reception("<p>There is a bulging disc at L5-S1.</p>"),
        _reception("<p>No focal disc protrusion.</p>"),
    ]
    fake = _FakeCollection(docs)
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})

    result = local_reports.search_reports(
        "lumbar disc bulging",
        queries=["disc bulge", "disc bulging", "bulging disc"],
        match_mode="any",
    )

    assert result["count"] == 2
    assert result["queries"] == ["disc bulge", "disc bulging", "bulging disc"]
    assert all(row["matchedQueries"] for row in result["rows"])
    assert all(row["snippets"] for row in result["rows"])


def test_several_findings_can_be_required_in_the_same_report(monkeypatch):
    docs = [
        _reception("<p>Cerebral atrophy with chronic small vessel changes.</p>"),
        _reception("<p>Mild cerebral atrophy. No acute infarct.</p>"),
        _reception("<p>Chronic small vessel ischemic changes.</p>"),
    ]
    fake = _FakeCollection(docs)
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})

    result = local_reports.search_reports(
        "atrophy and small-vessel disease",
        queries=["atrophy", "small vessel"],
        match_mode="all",
    )

    assert result["count"] == 1
    assert result["rows"][0]["matchedQueries"] == ["atrophy", "small vessel"]


def test_search_vocabulary_is_bounded_and_validated():
    with pytest.raises(ValueError, match="between 1 and"):
        local_reports._normalise_queries("x", ["x"] * (local_reports.MAX_QUERY_TERMS + 1))
    with pytest.raises(ValueError, match="must be a string"):
        local_reports._normalise_queries("x", ["x", 3])
    with pytest.raises(ValueError, match="matchMode"):
        local_reports._normalise_match_mode("semantic")


def test_any_mode_never_uses_a_lossy_mongo_prefilter():
    assert local_reports._combined_narrow_filter(["BIRADS", "3"], "any") is None
    narrowed = local_reports._combined_narrow_filter(["atrophy", "small vessel"], "all")
    assert narrowed and "$and" in narrowed


def test_search_limit_is_clamped(monkeypatch):
    """The display budget is enforced, and `count` ignores it.

    Sized from MAX_LIMIT rather than a literal, so raising the budget does not
    silently turn this into a test of nothing. It once asserted 500 matches were
    truncated; when the budget went to 1000 that assertion started describing
    the test's own fixture instead of the behaviour.
    """
    over = local_reports.MAX_LIMIT + 50
    fake = _FakeCollection([_reception() for _ in range(over)])
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})
    result = local_reports.search_reports("BIRADS", limit=10_000)
    assert result["returned"] <= local_reports.MAX_LIMIT
    assert result["count"] == over, "count is every match, not just the returned page"
    assert result["truncated"] is True


def test_search_under_the_budget_is_not_truncated(monkeypatch):
    """The other half: a result that fits must not be labelled partial."""
    fake = _FakeCollection([_reception() for _ in range(500)])
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})
    result = local_reports.search_reports("BIRADS", limit=10_000)
    assert result["count"] == 500
    assert result["truncated"] is False, "500 rows fit in the budget; nothing was cut"


def test_history_returns_full_text_for_comparison(monkeypatch):
    fake = _FakeCollection([_reception(), _reception()])
    monkeypatch.setattr(local_reports, "reception_db", lambda: {"receptions": fake})
    result = local_reports.patient_report_history("0000000000", limit=5)
    assert result["count"] == 2
    assert all("reportText" in r for r in result["rows"])


# --------------------------------------------------------------------------- #
# Tool wiring
# --------------------------------------------------------------------------- #
def test_tools_are_registered_as_reads():
    from reception_crm.core.registry import default_registry

    registry = default_registry()
    for name in ("report.get", "report.search", "report.history", "report.archive-stats"):
        tool = registry.get(name)
        assert tool.safety == "read"
        assert tool.permission_action == "read"
        assert tool.requires_confirmation is False


def test_tools_degrade_cleanly_without_a_database(monkeypatch):
    """An agent installed somewhere other than the reception server must keep
    working; it just cannot answer these."""
    from reception_crm.core.tools import reports_local

    monkeypatch.setenv(mongo.ENV_ENABLED, "false")
    mongo.reset()
    out = reports_local._search({"query": "BIRADS"})
    assert out["available"] is False
    assert "reception server" in out["hint"]


def test_report_search_tool_passes_the_generic_cohort_contract(monkeypatch):
    from reception_crm.core.tools import reports_local

    captured = {}

    def search_reports(**kwargs):
        captured.update(kwargs)
        return {"count": 0, "rows": []}

    monkeypatch.setattr(reports_local.local_reports, "search_reports", search_reports)
    result = reports_local._search(
        {
            "query": "lumbar reports with disc bulging",
            "queries": ["disc bulge", "disc bulging", "bulging disc"],
            "matchMode": "any",
            "dateFrom": "1405/01/01",
            "dateTo": "1405/06/31",
            "modality": "MRI",
            "service": "کمر",
            "status": "final",
            "approvedOnly": True,
            "limit": 500,
        }
    )

    assert result["skill"] == "report.search"
    assert captured == {
        "query": "lumbar reports with disc bulging",
        "queries": ["disc bulge", "disc bulging", "bulging disc"],
        "match_mode": "any",
        "date_from": "1405/01/01",
        "date_to": "1405/06/31",
        "modality": "MRI",
        "service": "کمر",
        "status": "final",
        "approved_only": True,
        "limit": 500,
    }
