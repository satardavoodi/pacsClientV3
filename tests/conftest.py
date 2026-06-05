"""Shared pytest configuration — adds project root to sys.path."""
import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


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
