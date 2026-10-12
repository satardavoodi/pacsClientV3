"""Integrity checks: the queries they build, and the honesty of what they report.

The recurring risk in a quality check is a bounded scan presented as a complete
answer. These tests pin the bound AND the disclosure of it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from reception_crm.local import integrity


def _matches_sync_status(doc, filter):
    """Evaluate just the ``syncStatus`` clause of a filter, if it has one.

    The fake deliberately understands only this one field. `broken_file_links`
    now excludes deleted rows *in the query*, so a fake that ignored filters
    entirely would hand back rows Mongo would never have returned — and the
    tests below would pass while the real check stayed broken.
    """
    spec = (filter or {}).get("syncStatus")
    if spec is None:
        return True
    value = doc.get("syncStatus")
    if isinstance(spec, dict):
        return value != spec["$ne"] if "$ne" in spec else True
    return value == spec


class _FakeCollection:
    def __init__(self, docs=None, count=None):
        self.docs = docs or []
        self._count = count
        self.last_filter = None

    def find(self, filter=None, projection=None, **kw):
        self.last_filter = filter
        return _FakeCursor([d for d in self.docs if _matches_sync_status(d, filter)])

    def count_documents(self, filter=None, **kw):
        self.last_filter = filter
        if (filter or {}).get("syncStatus") is not None:
            return sum(1 for d in self.docs if _matches_sync_status(d, filter))
        return self._count if self._count is not None else len(self.docs)


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


def _reception(rid=55040, approved_at="2026-08-01T10:00:00.000Z"):
    return {
        "ReceptionID": rid,
        "Date": "1405/05/29",
        "modality": "3",
        "patientNameSnapshot": "TEST",
        "nationalCode": "0000000000",
        "imagingWorkflow": {
            "workflowStatus": "inProgress",
            "report": {
                "status": "completed",
                "approvalFlags": {"physicianApproved": True, "physicianApprovedAt": approved_at},
            },
        },
    }


# --------------------------------------------------------------------------- #
# missing reports
# --------------------------------------------------------------------------- #
def test_missing_reports_excludes_cancelled_and_returned(monkeypatch):
    """A returned or deleted reception has no report because it did not happen.
    Counting it as a backlog item makes the number useless."""
    fake = _FakeCollection([_reception()])
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": fake})
    integrity.missing_reports(older_than_days=7)

    conditions = fake.last_filter["$and"]
    assert {"deleted": {"$ne": True}} in conditions
    assert {"returned": {"$ne": True}} in conditions


def test_missing_reports_ages_on_createdat_not_the_jalali_string(monkeypatch):
    """`Date` is a Jalali string and cannot be compared to a datetime.
    `createdAt` is the real timestamp, so the age test must use it."""
    fake = _FakeCollection([])
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": fake})
    integrity.missing_reports(older_than_days=30)

    age = [c for c in fake.last_filter["$and"] if "createdAt" in c]
    assert len(age) == 1
    cutoff = age[0]["createdAt"]["$lt"]
    assert isinstance(cutoff, datetime)
    expected = datetime.now(timezone.utc) - timedelta(days=30)
    assert abs((cutoff - expected).total_seconds()) < 60


def test_an_explicit_window_replaces_the_age_cutoff(monkeypatch):
    fake = _FakeCollection([])
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": fake})
    result = integrity.missing_reports(date_from="1405/05/01", date_to="1405/05/30")

    assert not any("createdAt" in c for c in fake.last_filter["$and"])
    assert {"Date": {"$gte": "1405/05/01", "$lte": "1405/05/30"}} in fake.last_filter["$and"]
    assert result["criteria"]["olderThanDays"] is None


def test_missing_reports_declares_truncation(monkeypatch):
    fake = _FakeCollection([_reception(rid=i) for i in range(100)], count=873)
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": fake})
    result = integrity.missing_reports(limit=5)
    assert result["count"] == 873
    assert result["returned"] == 5
    assert result["truncated"] is True


# --------------------------------------------------------------------------- #
# broken file links
# --------------------------------------------------------------------------- #
def test_only_paths_under_known_roots_are_opened():
    """A path out of the database is a stored string like any other. Opening
    whatever it names would make the database a file-read primitive."""
    assert integrity._under_known_root(r"D:\api\images\ReceptionAttachments\x.jpg")
    assert integrity._under_known_root(r"D:\Program Files\AI_PACS_SERVER\data\dicom_data\1\a.dcm")
    for outside in (r"C:\Windows\System32\config\SAM", r"D:\RAZI crm\config\server.json",
                    r"\\server\share\x", "", None):
        assert not integrity._under_known_root(outside), outside


def test_broken_links_counts_paths_it_refused_to_check(monkeypatch, tmp_path):
    """A row pointing outside the known roots is neither 'fine' nor 'broken' —
    it was not checked, and the answer has to say so."""
    rows = [
        {"receptionID": 1, "dicomFilePath": r"C:\Windows\System32\x.dcm"},
        {"receptionID": 2, "dicomFilePath": r"D:\api\images\ReceptionAttachments\gone.jpg"},
    ]
    fake = _FakeCollection(rows, count=2)
    monkeypatch.setattr(integrity, "reception_db", lambda: {"document_attachments": fake})
    result = integrity.broken_file_links()

    assert result["pathsOutsideKnownRoots"] == 1
    assert result["brokenFound"] == 1
    assert result["checked"] == 2


def test_broken_links_does_not_report_a_file_that_exists(monkeypatch, tmp_path):
    real = tmp_path / "present.dcm"
    real.write_text("x", encoding="utf-8")
    monkeypatch.setattr(integrity, "FILE_ROOTS", (str(tmp_path),))
    fake = _FakeCollection([{"receptionID": 3, "dicomFilePath": str(real)}], count=1)
    monkeypatch.setattr(integrity, "reception_db", lambda: {"document_attachments": fake})
    assert integrity.broken_file_links()["brokenFound"] == 0


def _attachment(rid, path, sync=None):
    doc = {"receptionID": rid, "dicomFilePath": path}
    if sync is not None:
        doc["syncStatus"] = sync
    return doc


def test_a_deliberately_deleted_row_is_not_a_broken_link(monkeypatch):
    """The first live run called 24 rows broken and every one was `deleted` —
    a file the reception system removed on purpose. Its path is *meant* to lead
    nowhere, so reporting it as damage answers a different question."""
    root = integrity.FILE_ROOTS[0]
    rows = [
        _attachment(1, root + r"\tidied-away.jpg", sync="deleted"),
        _attachment(2, root + r"\really-gone.jpg", sync="synced"),
    ]
    fake = _FakeCollection(rows)
    monkeypatch.setattr(integrity, "reception_db", lambda: {"document_attachments": fake})
    result = integrity.broken_file_links()

    assert result["brokenFound"] == 1
    assert result["rows"][0]["receptionId"] == 2
    assert result["deletedRowsExcluded"] == 1
    assert result["checked"] == 1, "a deleted row should not even spend scan budget"


def test_deleted_rows_can_be_asked_for_explicitly(monkeypatch):
    root = integrity.FILE_ROOTS[0]
    rows = [_attachment(1, root + r"\tidied-away.jpg", sync="deleted")]
    fake = _FakeCollection(rows)
    monkeypatch.setattr(integrity, "reception_db", lambda: {"document_attachments": fake})
    result = integrity.broken_file_links(include_deleted=True)

    assert result["brokenFound"] == 1
    assert result["includedDeleted"] is True
    assert result["deletedRowsExcluded"] == 0


def test_broken_links_count_is_not_capped_by_the_display_limit(monkeypatch):
    """`brokenFound` answers "how many", `returned` answers "how many are
    listed". Collapsing them made a scan that found 300 defects report 25."""
    root = integrity.FILE_ROOTS[0]
    rows = [_attachment(i, root + ("\\missing-%d.jpg" % i), sync="synced") for i in range(12)]
    fake = _FakeCollection(rows)
    monkeypatch.setattr(integrity, "reception_db", lambda: {"document_attachments": fake})
    result = integrity.broken_file_links(limit=3)

    assert result["brokenFound"] == 12
    assert result["returned"] == 3
    assert result["truncated"] is True


def test_missing_reports_excludes_bookings_that_never_happened(monkeypatch):
    """`waiting_appointment` means the patient has not attended. Counting those
    made the first run report 26,590 unreported studies, nearly all of them
    future appointments."""
    fake = _FakeCollection([])
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": fake})
    result = integrity.missing_reports(older_than_days=7)

    assert {"imagingWorkflow.workflowStatus": {"$ne": integrity.NOT_YET_PERFORMED}} in (
        fake.last_filter["$and"]
    )
    assert result["criteria"]["excludedNotYetPerformed"] is True


def test_bookings_can_be_included_on_request(monkeypatch):
    fake = _FakeCollection([])
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": fake})
    result = integrity.missing_reports(include_not_yet_performed=True)

    assert not any("imagingWorkflow.workflowStatus" in c for c in fake.last_filter["$and"])
    assert result["criteria"]["excludedNotYetPerformed"] is False


def test_a_string_false_does_not_switch_the_exclusions_back_on():
    """The flags arrive through an LLM, which may send the word "false".
    Plain truthiness would read that as *on* and undo both defaults."""
    from reception_crm.core.tools.integrity_local import _flag

    for off in (None, False, "", "false", "False", "no", "0", "off"):
        assert _flag(off) is False, off
    for on in (True, "true", "yes", "1"):
        assert _flag(on) is True, on


# --------------------------------------------------------------------------- #
# post-approval edits
# --------------------------------------------------------------------------- #
class _FakeDb(dict):
    pass


class _FakeLogs(_FakeCollection):
    """A log collection whose `find` honours the ``changedAt`` lower bound.

    The check now reads the *earliest* qualifying edit to measure its distance
    from the approval, so a fake that returned rows regardless of the time bound
    would let a grace window pass its tests while doing nothing in production.
    """

    def find(self, filter=None, projection=None, **kw):
        self.last_filter = filter
        floor = ((filter or {}).get("changedAt") or {}).get("$gt")
        kept = [d for d in self.docs if floor is None or _parse(d["changedAt"]) > floor]
        return _FakeCursor(sorted(kept, key=lambda d: d["changedAt"]))

    def count_documents(self, filter=None, **kw):
        self.last_filter = filter
        floor = ((filter or {}).get("changedAt") or {}).get("$gt")
        return sum(1 for d in self.docs if floor is None or _parse(d["changedAt"]) > floor)


def _parse(value):
    return integrity._parse_iso(value)


def _edit(at):
    return {"changedAt": at, "field": "content"}


def test_post_approval_edits_compares_against_the_approval_time(monkeypatch):
    receptions = _FakeCollection([_reception(approved_at="2026-08-01T10:00:00.000Z")], count=1)
    logs = _FakeLogs([
        _edit("2026-08-01T09:00:00.000Z"),   # before approval — not a finding
        _edit("2026-08-01T11:30:00.000Z"),
        _edit("2026-08-02T08:00:00.000Z"),
    ])
    monkeypatch.setattr(
        integrity, "reception_db", lambda: _FakeDb(receptions=receptions, ReportLogs=logs)
    )

    result = integrity.post_approval_edits()
    assert result["found"] == 1
    assert result["rows"][0]["editsAfterApproval"] == 2
    assert result["rows"][0]["minutesAfterApproval"] == 90.0

    # The log query must be time-bounded by the approval, and scoped to the
    # fields that carry report text.
    assert logs.last_filter["changedAt"]["$gt"] == datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    assert logs.last_filter["field"]["$in"] == ["content", "findings"]


def test_a_grace_window_moves_the_bound_and_is_reported(monkeypatch):
    """A save two minutes after the approval click is the same act finishing.
    Nothing is hidden silently: the window used comes back in the answer."""
    receptions = _FakeCollection([_reception(approved_at="2026-08-01T10:00:00.000Z")], count=1)
    logs = _FakeLogs([_edit("2026-08-01T10:02:00.000Z")])
    monkeypatch.setattr(
        integrity, "reception_db", lambda: _FakeDb(receptions=receptions, ReportLogs=logs)
    )

    assert integrity.post_approval_edits()["found"] == 1
    wide = integrity.post_approval_edits(grace_minutes=10)
    assert wide["found"] == 0
    assert wide["graceMinutes"] == 10


def test_a_report_with_no_later_edits_is_not_a_finding(monkeypatch):
    receptions = _FakeCollection([_reception()], count=1)
    logs = _FakeLogs([])
    monkeypatch.setattr(
        integrity, "reception_db", lambda: _FakeDb(receptions=receptions, ReportLogs=logs)
    )
    assert integrity.post_approval_edits()["found"] == 0


def test_an_unparseable_approval_timestamp_is_skipped_not_guessed(monkeypatch):
    receptions = _FakeCollection([_reception(approved_at="not a date")], count=1)
    logs = _FakeLogs([_edit("2026-08-01T11:00:00.000Z")])
    monkeypatch.setattr(
        integrity, "reception_db", lambda: _FakeDb(receptions=receptions, ReportLogs=logs)
    )
    assert integrity.post_approval_edits()["found"] == 0


def test_post_approval_scan_is_bounded_and_says_so(monkeypatch):
    receptions = _FakeCollection([_reception(rid=i) for i in range(10)], count=25209)
    logs = _FakeLogs([_edit("2026-08-01T11:00:00.000Z")])
    monkeypatch.setattr(
        integrity, "reception_db", lambda: _FakeDb(receptions=receptions, ReportLogs=logs)
    )
    result = integrity.post_approval_edits(scan=10, limit=3)
    assert result["approvedReportsTotal"] == 25209
    assert result["checked"] == 10
    assert result["capped"] is True, "a partial scan must never look complete"
    assert result["found"] == 10, "the count is of what was found, not of what is shown"
    assert len(result["rows"]) == 3
    assert result["truncated"] is True


def test_iso_parser_handles_the_stored_format():
    parsed = integrity._parse_iso("2026-08-01T10:00:00.000Z")
    assert parsed == datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    assert integrity._parse_iso(None) is None
    assert integrity._parse_iso("") is None
    assert integrity._parse_iso("garbage") is None


# --------------------------------------------------------------------------- #
def test_tools_are_registered_as_reads():
    from reception_crm.core.registry import default_registry

    registry = default_registry()
    for name in ("integrity.missing-reports", "integrity.broken-files",
                 "integrity.post-approval-edits"):
        tool = registry.get(name)
        assert tool.safety == "read"
        assert tool.permission_action == "read"
