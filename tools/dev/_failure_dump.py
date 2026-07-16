"""Tiny pytest plugin: dump failing node IDs + reasons to JSON (Q0, 2026-07-14).

Parsing pytest's `FAILED ...` text is fragile: a parametrised test with non-ASCII ids (e.g. the
Persian strings in `test_ino_report_workflow`) is printed with `\\uXXXX` escapes, so the parsed
node id never matches the real one at collection time and the quarantine silently misses it.

This records the node id as pytest itself sees it. Enable with:

    pytest -p tools.dev._failure_dump  --failure-dump out.json
"""

from __future__ import annotations

import json
import os

_FAILURES: dict[str, str] = {}


def pytest_addoption(parser):
    parser.addoption("--failure-dump", action="store", default=None,
                     help="write {nodeid: reason} JSON for failing tests")


def pytest_runtest_logreport(report):
    # Ignore pytest-rerunfailures' intermediate "rerun" reports — only the FINAL outcome counts.
    # Otherwise a flaky test that passes on retry would be captured as a permanent failure.
    if getattr(report, "outcome", "") == "rerun":
        return
    if report.failed and not getattr(report, "wasxfail", None):
        reason = ""
        try:
            reason = str(report.longrepr.reprcrash.message)  # type: ignore[union-attr]
        except Exception:
            reason = str(getattr(report, "longrepr", "")) or "no reason captured"
        _FAILURES[report.nodeid] = reason.strip().splitlines()[0][:180] if reason else "failed"


def pytest_sessionfinish(session, exitstatus):
    path = session.config.getoption("--failure-dump")
    if not path:
        return
    # xdist: each worker writes its own shard; the controller merges.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        path = f"{path}.{worker}"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_FAILURES, fh, ensure_ascii=False, indent=1)
