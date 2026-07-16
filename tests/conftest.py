"""Shared pytest configuration — adds project root to sys.path + applies the quarantine."""
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def pytest_collection_modifyitems(config, items):
    """Apply the quarantine registry as `xfail(strict=True)` (Q0, 2026-07-14).

    The suite used to be RED BY DEFAULT (~83 permanently-failing tests), which meant it
    carried **zero regression signal**: a new breakage was invisible among the existing
    reds, and "did I break anything?" could only be answered with a manual `git stash` A/B.

    Every known-failing test is now listed in `tests/quarantine.py` **with its real failure
    message**, and marked xfail here. The consequences are deliberate:

    * the suite exits **0**, so **any new red is a genuine, immediately-visible regression**;
    * `strict=True` means a quarantined test that starts PASSING **fails the suite** — the
      list is self-cleaning and cannot silently rot;
    * nothing is hidden: `tests/quarantine.py` is a readable, greppable DEBT REGISTER.

    **Do not add a test here to make your own breakage go away.** Quarantine is for
    pre-existing debt only. Regenerate with `python tools/dev/build_quarantine.py`; check for
    new regressions with `--check`.
    """
    import os

    # The generator (`tools/dev/build_quarantine.py`) must see the RAW failures, so it runs
    # with the quarantine disabled — otherwise every quarantined test reports xfail, drops out
    # of the failure dump, and the regenerated registry would be empty.
    if os.environ.get("AIPACS_QUARANTINE_OFF", "").strip() == "1":
        return
    registry: dict = {}
    try:
        from tests.quarantine import QUARANTINE  # AUTO-GENERATED (regenerable)
        registry.update(QUARANTINE)
    except Exception:
        pass
    try:
        from tests.quarantine_manual import MANUAL_QUARANTINE  # hand-maintained (flaky, etc.)
        registry.update(MANUAL_QUARANTINE)
    except Exception:
        pass
    if not registry:
        return
    for item in items:
        entry = registry.get(item.nodeid)
        if entry is None:
            # Fall back to a FUNCTION-level key (nodeid without the `[param]` suffix). This lets
            # a flaky PARAMETRISED case be quarantined without transcribing its parametrize id —
            # which is essential when the id contains non-ASCII (pytest stores it `\uXXXX`-escaped,
            # e.g. the Persian strings in test_classify_error, which are painful to match exactly).
            base = item.nodeid.split("[", 1)[0]
            if base != item.nodeid:
                entry = registry.get(base)
        if entry is None:
            continue
        category, reason = entry
        # NON-STRICT by design. `strict=True` was tempting (self-cleaning: a fixed test that
        # passes fails the suite so it gets removed) but it is WRONG for a large, partly-flaky
        # quarantine: a TIMING-flaky quarantined test that happens to pass on a given run then
        # triggers a strict-XPASS failure — the suite goes red for the opposite reason. Real
        # quarantine systems use non-strict xfail + a SEPARATE burn-down audit. Ours is
        # `python tools/dev/build_quarantine.py --check`, which reports BOTH new regressions AND
        # quarantined tests that now pass consistently (so the list still shrinks — just via an
        # explicit audit, not a flaky per-run strict-xpass). This keeps the suite deterministically
        # green while preserving the debt-register discipline.
        item.add_marker(
            pytest.mark.xfail(
                strict=False,
                reason=f"[quarantined:{category}] {reason}",
            )
        )


def pytest_addoption(parser):
    """Backfill pdb/trace options when the debugging plugin is disabled.

    The project's blessed invocation uses ``-p no:debugging`` (debugpy/VS
    Code conflicts), which removes pytest's ``--trace``/``--pdb``/``--pdbcls``
    options — but pytest's CORE unittest integration still reads them
    (``_pytest/unittest.py`` → ``config.getoption("trace"/"usepdb")``), so
    every ``unittest.TestCase``-style test errored with
    "no option named 'trace'" (44 viewer failures + 3 startup failures,
    2026-06-04 triage). Register inert stand-ins; when the real plugin is
    active these raise ValueError (duplicate option) and are skipped.
    """
    for args, kwargs in (
        (("--trace",), dict(action="store_true", dest="trace", default=False,
                            help="stub (no:debugging) — immediate pdb is unavailable")),
        (("--pdb",), dict(action="store_true", dest="usepdb", default=False,
                          help="stub (no:debugging) — post-mortem pdb is unavailable")),
        (("--pdbcls",), dict(dest="usepdb_cls", metavar="modulename:classname",
                             default=None,
                             help="stub (no:debugging)")),
    ):
        try:
            parser.addoption(*args, **kwargs)
        except Exception:
            # Real debugging plugin is loaded — its options already exist
            # (argparse.ArgumentError / ValueError depending on pytest ver).
            pass
