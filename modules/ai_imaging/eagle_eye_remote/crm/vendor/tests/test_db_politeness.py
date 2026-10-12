"""The agent's manners on somebody else's database.

The reception system's MongoDB is shared, and it was sized for their workload,
not ours. These tests pin the four controls that keep a read-only companion from
behaving like a second tenant — each one chosen from a measurement on the live
server, each one recorded in docs/AGENT_SAFETY_REVIEW.md.

They are structural tests on purpose. A limit that depends on every future
caller remembering it is not a limit.
"""

from __future__ import annotations

import threading
import time

import pytest

from reception_crm.local import integrity, mongo, reports


# --------------------------------------------------------------------------- #
# 1. Every read carries a server-side deadline
# --------------------------------------------------------------------------- #
class _Spy:
    """Records the kwargs each read method was called with."""

    def __init__(self):
        self.name = "spy"
        self.calls: list[tuple[str, dict]] = []

    def find(self, filter=None, projection=None, **kw):
        self.calls.append(("find", kw))
        return iter(())

    def find_one(self, filter=None, projection=None, **kw):
        self.calls.append(("find_one", kw))
        return None

    def aggregate(self, pipeline, **kw):
        self.calls.append(("aggregate", kw))
        return iter(())

    def count_documents(self, filter=None, **kw):
        self.calls.append(("count_documents", kw))
        return 0

    def distinct(self, key, filter=None, **kw):
        self.calls.append(("distinct", kw))
        return []

    def estimated_document_count(self, **kw):
        self.calls.append(("estimated_document_count", kw))
        return 0


def test_every_read_gets_a_server_side_time_limit():
    """`maxTimeMS` is what makes mongod kill a long operation. Without it a
    runaway scan keeps consuming the clinical server even after we stop caring."""
    spy = _Spy()
    col = mongo.ReadOnlyCollection(spy)

    col.find({})
    col.find_one({})
    col.aggregate([{"$match": {}}])
    col.count_documents({})
    col.distinct("x")

    by_method = dict(spy.calls)
    assert by_method["find"]["max_time_ms"] == mongo.QUERY_TIMEOUT_MS
    assert by_method["find_one"]["max_time_ms"] == mongo.QUERY_TIMEOUT_MS
    assert by_method["aggregate"]["maxTimeMS"] == mongo.QUERY_TIMEOUT_MS
    assert by_method["count_documents"]["maxTimeMS"] == mongo.QUERY_TIMEOUT_MS
    assert by_method["distinct"]["maxTimeMS"] == mongo.QUERY_TIMEOUT_MS


def test_a_caller_can_ask_for_longer_but_has_to_say_so():
    spy = _Spy()
    col = mongo.ReadOnlyCollection(spy)
    col.find({}, max_time_ms=90_000)
    assert dict(spy.calls)["find"]["max_time_ms"] == 90_000


def test_the_free_count_is_not_given_a_pointless_deadline():
    """`estimated_document_count` reads collection metadata, not documents."""
    spy = _Spy()
    mongo.ReadOnlyCollection(spy).estimated_document_count()
    assert dict(spy.calls)["estimated_document_count"] == {}


def test_the_timeout_is_generous_against_the_measured_worst_case():
    """Measured on the live archive: a whole-archive report search is ~1.9 s of
    server time. A limit that could fire during normal use would be a bug
    generator, not a safety control."""
    assert mongo.QUERY_TIMEOUT_MS >= 10_000
    assert mongo.QUERY_TIMEOUT_MS <= 60_000, "nothing the agent starts may run for a minute"


# --------------------------------------------------------------------------- #
# 2. One scan at a time
# --------------------------------------------------------------------------- #
def test_two_scans_cannot_run_at_once():
    """A thread-per-request HTTP server will start three collection scans of a
    1.4 GB clinical collection given three taps on a phone. It must not."""
    inside = threading.Event()
    release = threading.Event()
    second_got_in = threading.Event()

    def hold():
        with mongo.scan_slot():
            inside.set()
            release.wait(timeout=5)

    def contend():
        inside.wait(timeout=5)
        try:
            with mongo.scan_slot():
                second_got_in.set()
        except mongo.ScanBusy:
            pass

    holder = threading.Thread(target=hold)
    other = threading.Thread(target=contend)
    holder.start()
    other.start()

    inside.wait(timeout=5)
    time.sleep(0.15)
    assert not second_got_in.is_set(), "two scans held the slot simultaneously"

    release.set()
    holder.join(timeout=5)
    other.join(timeout=5)
    assert second_got_in.is_set(), "the queued scan never ran after the slot freed"


def test_the_slot_is_released_when_a_scan_raises():
    """A scan that throws must not wedge every later scan behind it."""
    with pytest.raises(ValueError):
        with mongo.scan_slot():
            raise ValueError("boom")

    with mongo.scan_slot():
        pass  # would block forever if the slot had leaked


def test_waiting_forever_is_not_an_option(monkeypatch):
    monkeypatch.setattr(mongo, "SCAN_QUEUE_TIMEOUT_S", 0.05)
    with mongo.scan_slot():
        with pytest.raises(mongo.ScanBusy):
            with mongo.scan_slot():
                pass


def test_a_busy_scan_is_an_answer_not_a_stack_trace(monkeypatch):
    """The clinician should be told to try again, not shown an exception."""
    from reception_crm.core.tools import reports_local

    def busy(**_kw):
        raise mongo.ScanBusy("already scanning")

    result = reports_local._guard(busy)
    assert result["available"] is False
    assert result["busy"] is True
    assert "moment" in result["hint"]


# --------------------------------------------------------------------------- #
# 3. The expensive paths actually take the slot
# --------------------------------------------------------------------------- #
def _slot_taken_during(call) -> bool:
    """True if `call` held the scan slot while it ran."""
    seen = {"held": False}
    real = mongo._scan_slot

    class Watcher:
        def acquire(self, timeout=None):
            seen["held"] = True
            return real.acquire(timeout=timeout)

        def release(self):
            return real.release()

    mongo._scan_slot = Watcher()
    try:
        call()
    finally:
        mongo._scan_slot = real
    return seen["held"]


class _FakeCol:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.last_projection = None

    def find(self, filter=None, projection=None, **kw):
        self.last_projection = projection
        return _FakeCursor(self.docs)

    def count_documents(self, filter=None, **kw):
        return len(self.docs)

    def estimated_document_count(self, **kw):
        return len(self.docs)

    def aggregate(self, pipeline, **kw):
        return iter(())


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


def test_report_search_takes_the_slot(monkeypatch):
    col = _FakeCol([])
    monkeypatch.setattr(reports, "reception_db", lambda: {"receptions": col})
    assert _slot_taken_during(lambda: reports.search_reports("fibroadenoma"))


def test_archive_stats_takes_the_slot(monkeypatch):
    col = _FakeCol([])
    monkeypatch.setattr(reports, "reception_db", lambda: {"receptions": col})
    assert _slot_taken_during(reports.archive_stats)


def test_missing_reports_takes_the_slot(monkeypatch):
    col = _FakeCol([])
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": col})
    assert _slot_taken_during(lambda: integrity.missing_reports())


def test_opening_one_report_does_NOT_take_the_slot(monkeypatch):
    """An index lookup measured at 2 ms has no business queueing behind a scan
    — that would make the fast path as slow as the slow one."""
    class One(_FakeCol):
        def find_one(self, filter=None, projection=None, **kw):
            return None

    monkeypatch.setattr(reports, "reception_db", lambda: {"receptions": One()})
    assert not _slot_taken_during(lambda: reports.get_report(reception_id=1))


# --------------------------------------------------------------------------- #
# 4. Nothing asks mongod for whole clinical documents it does not need
# --------------------------------------------------------------------------- #
def test_the_backlog_check_projects_instead_of_fetching_whole_records(monkeypatch):
    """A reception document averages 28 KB. Twenty-five of them is 700 KB moved
    to display seven fields."""
    col = _FakeCol([])
    monkeypatch.setattr(integrity, "reception_db", lambda: {"receptions": col})
    integrity.missing_reports(limit=25)

    assert col.last_projection is not None, "no projection: whole documents were requested"
    assert "imagingWorkflow.report.content" not in col.last_projection


def test_search_does_not_scan_the_collection_twice(monkeypatch):
    """It used to `count_documents` with the identical filter purely to decide
    whether the cap was hit — doubling the cost of every whole-archive search."""
    counts = {"n": 0}

    class Counting(_FakeCol):
        def count_documents(self, filter=None, **kw):
            counts["n"] += 1
            return 0

    monkeypatch.setattr(reports, "reception_db", lambda: {"receptions": Counting()})
    reports.search_reports("fibroadenoma")
    assert counts["n"] == 0, "the search counted as well as scanned"


# --------------------------------------------------------------------------- #
# 5. The connection pool is bounded
# --------------------------------------------------------------------------- #
def test_the_connection_pool_is_small():
    """The reception stack already holds ~93 connections of its own; pymongo's
    default would let a read-only sidecar open 100 more."""
    assert mongo.MAX_POOL_SIZE <= 8


# --------------------------------------------------------------------------- #
# 6. The agent yields the CPU to the clinical software
# --------------------------------------------------------------------------- #
def test_lowering_priority_never_stops_the_service(monkeypatch):
    from reception_crm import politeness

    monkeypatch.setattr(politeness.sys, "platform", "win32")
    monkeypatch.delenv(politeness.ENV_YIELD, raising=False)
    # No ctypes/windll in this environment: the call must still return a string
    # and must not raise. A service that refuses to start because it could not
    # lower its own priority is worse than one running at normal priority.
    assert isinstance(politeness.yield_cpu_to_clinical_software(), str)


def test_the_outcome_is_reported_not_assumed():
    """The first deployment of this module set no priority at all — ctypes
    truncated the process handle and SetPriorityClass returned 0. It was found
    only because the outcome is a value that gets logged rather than a silent
    side effect. Keep it that way."""
    from reception_crm import politeness

    outcome = politeness.yield_cpu_to_clinical_software()
    assert outcome, "the call must always say what happened"
    assert outcome.startswith(("BELOW_NORMAL", "nice", "unchanged", "left at default"))


def test_a_windows_failure_says_why(monkeypatch):
    """`unchanged` on its own is not a diagnosis. The Windows error code is what
    turns a silent no-op into something someone can act on."""
    import sys as _sys

    from reception_crm import politeness

    if not _sys.platform.startswith("win"):
        pytest.skip("Windows-only path")
    outcome = politeness.yield_cpu_to_clinical_software()
    if outcome.startswith("unchanged"):
        assert "GetLastError" in outcome or ":" in outcome


def test_yielding_can_be_switched_off_for_a_dedicated_machine(monkeypatch):
    from reception_crm import politeness

    monkeypatch.setenv(politeness.ENV_YIELD, "false")
    assert "left at default" in politeness.yield_cpu_to_clinical_software()
