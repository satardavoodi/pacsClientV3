"""Invariants of the extracted report catalogue.

`reception_crm/reports_catalog.json` is generated from the reception software's
own router by `scripts/_extract_report_catalog.py`. These tests do not check
the extractor's logic — that lives on the reception box with the source it
reads. They check the shipped artefact, because the artefact is what the report
router will trust, and every defect this file has had so far was invisible in
the data and obvious in an assertion:

  * an empty `collections` list, because the cashier family queries
    `Transaction` and the extractor matched only names ending in `Model`;
  * `default_when_no_dates: "today"` on a route with no default at all,
    because `getCurrentPersianDate()` also stamps the response envelope;
  * a byte-order mark, because the shell that ran the extractor wrote one and
    `json.load` rejects it.

Each of those shipped once. Each is one assertion below.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CATALOG_PATH = Path(__file__).resolve().parents[1] / "reception_crm" / "reports_catalog.json"

KNOWN_BASES = {
    "reception_date",
    "transaction_date",
    "patient_created_at",
    "record_created_at",
    "warehouse_movement_date",
    "deletion_date",
    "mixed",
    "not_dated",
}
KNOWN_DEFAULTS = {"all_time", "today", "current_month", "rejects_request", "not_applicable"}


@pytest.fixture(scope="module")
def catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_is_plain_utf8_without_a_byte_order_mark():
    """`json.load(open(path))` must work with no encoding argument.

    The extractor's output was piped through PowerShell once, which writes
    UTF-8 with a BOM, and every Python consumer failed on the first character.
    """
    raw = CATALOG_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    json.loads(raw.decode("utf-8"))


def test_every_report_names_at_least_one_collection(catalog):
    """An empty list reads as "this report has no data source", which is false."""
    orphans = [report["path"] for report in catalog["reports"] if not report["collections"]]
    assert orphans == []


def test_every_report_has_a_recognised_date_basis(catalog):
    """A basis outside this set means the extractor met a field nobody has mapped.

    It must fail here rather than reach the router as `unmapped:something`,
    which the router would have no rule for and would most likely ignore.
    """
    unknown = {
        report["path"]: report["date_basis"]
        for report in catalog["reports"]
        if report["date_basis"] not in KNOWN_BASES
    }
    assert unknown == {}


def test_every_report_says_what_it_means_with_no_dates(catalog):
    unknown = {
        report["path"]: report["default_when_no_dates"]
        for report in catalog["reports"]
        if report["default_when_no_dates"] not in KNOWN_DEFAULTS
    }
    assert unknown == {}


def test_a_dated_report_carries_the_evidence_for_its_basis(catalog):
    """The verdict is only useful if the line that produced it travels with it.

    A basis with no evidence is a claim about the vendor's software with
    nothing behind it, and this catalogue exists precisely so that such claims
    are checkable rather than trusted.
    """
    naked = [
        report["path"]
        for report in catalog["reports"]
        if report["date_bases"] and not any(f["evidence"] for f in report["date_fields"])
    ]
    assert naked == []


def test_date_coverage_reports_counts_and_never_a_verdict(catalog):
    """Coverage is a heuristic and must not present itself as a fact.

    Three attempts to decide mechanically whether a route's date filter reaches
    all of its queries were each wrong in a new way. The counts are kept
    because they are a useful read-list; a verdict field would be trusted, so
    there must not be one.
    """
    for report in catalog["reports"]:
        coverage = report["date_coverage"]
        assert "verdict" not in coverage
        assert coverage["verified_by_hand"] is None or isinstance(
            coverage["verified_by_hand"], str
        )
        assert coverage["visible_date_constraint"] <= coverage["query_sites"]


def test_a_shadowed_route_is_marked_rather_than_offered_twice(catalog):
    """Express keeps the first registration; a duplicate path is dead code.

    The router must not be given a choice between two entries that the web
    server would never distinguish.
    """
    seen: set[tuple[str, str]] = set()
    for report in catalog["reports"]:
        key = (report["method"], report["path"])
        if key in seen:
            assert report.get("shadowed_by_earlier_route") is True
        else:
            assert not report.get("shadowed_by_earlier_route")
            seen.add(key)
    assert len(seen) == catalog["distinct_routes"]


def test_the_two_case_differing_date_fields_are_both_present(catalog):
    """`Date` and `date` are different fields and the catalogue must keep both.

    `Date` on receptions is when the visit was booked; `date` on transactions
    is when money moved. Any consumer that folds case — PowerShell's
    ConvertFrom-Json does, and refuses the document outright — loses the one
    distinction this catalogue was built to preserve.
    """
    bases = {
        field["field"]: field["basis"]
        for report in catalog["reports"]
        for field in report["date_fields"]
    }
    assert bases.get("Date") == "reception_date"
    assert bases.get("date") == "transaction_date"


def test_every_report_carries_a_meaning_written_by_the_vendor(catalog):
    """The selection layer needs a meaning per report, and it must not be mine.

    Sixty-two meanings written by hand would be sixty-two guesses about someone
    else's software. The vendor comments every route in Persian and describes
    most responses, so every entry here is lifted from the router — a title, a
    description, or both.
    """
    undocumented = [
        report["path"]
        for report in catalog["reports"]
        if not report["title_fa"] and not report["description_fa"]
    ]
    assert undocumented == []


def test_the_vendor_text_survived_the_trip_as_persian(catalog):
    """Persian that reached the file through a console pipe arrives as mojibake.

    The extractor writes the file itself for this reason. If the text ever
    comes back as `╪»╪º╪┤╪¿┘ê╪▒╪»`, every term the ranker matches on is
    silently gone while the field count still looks right.
    """
    persian = re.compile(r"[؀-ۿ]")
    for report in catalog["reports"]:
        for text in (report["title_fa"], report["description_fa"]):
            if text:
                assert persian.search(text), (report["path"], text)


def test_field_labels_are_labels_and_not_fragments_of_switch_statements(catalog):
    """`regex:` and `then:` values are Persian, and are not descriptions.

    The cashier routes classify payments with
    `regex: 'بیمه|تامین اجتماعی|درمان|سلامت'` and `/patients` buckets ages with
    `then: 'کمتر از 18 سال'`. Both are Persian strings sitting next to a key,
    which is exactly the shape a label has — so they are excluded by key, and
    this asserts none of them slipped through.
    """
    for report in catalog["reports"]:
        for key, value in report["field_labels_fa"].items():
            assert key not in {"regex", "then", "default", "case"}, (report["path"], key)
            assert "|" not in value, (report["path"], key, value)


def test_the_patient_reports_are_dated_by_registration_not_by_visit(catalog):
    """The finding most likely to be assumed away, pinned as a test.

    `/patients` and its breakdowns filter on the patient's `createdAt`, so
    "how many patients this month" from those endpoints means how many
    REGISTERED this month, not how many were seen. The vendor's own response
    schema says so in Persian. Anything that quietly re-points these at the
    reception date would change what the agent's answers mean.
    """
    by_path = {report["path"]: report for report in catalog["reports"]}
    for path in ("/patients", "/patients/by-gender", "/patients/by-age", "/patients/by-insurance"):
        assert by_path[path]["date_basis"] == "patient_created_at", path
