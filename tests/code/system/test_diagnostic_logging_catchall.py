"""Regression guard: ensure app.log catch-all handler stays wired.

Background — 2026-05-28
=======================
For weeks the source-build's user_data/logs/ directory only contained
``download_diagnostics.log``, ``viewer_diagnostics.log`` and
``db_diagnostics.log``. All other application activity (home panel,
search, patient open, ``aipacs.resource_run`` heartbeat, etc.) was
silently dropped on the floor by the three component-scoped file
filters and only reached the console / stderr stream that VS Code
caught.

The fix in ``PacsClient/utils/diagnostic_logging.py`` introduced:
  * ``CatchAllOtherFilter`` — passes any record whose ``component`` is
    NOT in ``{download, viewer, db}``.
  * a new ``app.log`` SafeRotatingFileHandler wired into both the async
    QueueListener path and the synchronous fallback path.

This test makes sure those two pieces don't quietly disappear during
future refactors. The bug is invisible (no exception, no warning) so
without a structural guard a one-line edit could re-break it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
DIAG_LOG_PATH = REPO_ROOT / "PacsClient" / "utils" / "diagnostic_logging.py"


@pytest.fixture(scope="module")
def diag_source() -> str:
    return DIAG_LOG_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def diag_ast(diag_source: str) -> ast.Module:
    return ast.parse(diag_source)


def _class_node(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def test_catchall_filter_class_exists(diag_ast: ast.Module) -> None:
    """``CatchAllOtherFilter`` must be a top-level class in diagnostic_logging."""
    cls = _class_node(diag_ast, "CatchAllOtherFilter")
    assert cls is not None, (
        "CatchAllOtherFilter is missing from diagnostic_logging.py — "
        "app.log will become empty again. See "
        "docs/plans/architecture/LIVE_VALIDATION_2026-05-28_v2.md Gap #1."
    )


def test_catchall_filter_inherits_logging_filter(diag_ast: ast.Module) -> None:
    cls = _class_node(diag_ast, "CatchAllOtherFilter")
    assert cls is not None
    base_names = []
    for base in cls.bases:
        # Accept both `logging.Filter` and `Filter` (in case of from-imports).
        if isinstance(base, ast.Attribute):
            base_names.append(base.attr)
        elif isinstance(base, ast.Name):
            base_names.append(base.id)
    assert "Filter" in base_names, (
        "CatchAllOtherFilter must subclass logging.Filter so addFilter "
        f"accepts it. Bases found: {base_names!r}"
    )


def test_catchall_filter_excludes_three_specialised_components(
    diag_source: str,
) -> None:
    """The exclusion set must keep all three specialised components present.

    Removing one (e.g. dropping ``db``) would silently re-route every
    db_diagnostics.log line into app.log too, doubling I/O.
    """
    expected = {"download", "viewer", "db"}
    for component in expected:
        assert f'"{component}"' in diag_source, (
            f"CatchAllOtherFilter._SPECIALISED_COMPONENTS no longer mentions "
            f"{component!r}. The catch-all filter is supposed to EXCLUDE the "
            "three component-specific files."
        )


def test_app_log_handler_is_constructed(diag_source: str) -> None:
    """A ``logs_dir / 'app.log'`` SafeRotatingFileHandler must be built."""
    assert 'logs_dir / "app.log"' in diag_source or "logs_dir / 'app.log'" in diag_source, (
        "No app.log handler is constructed in diagnostic_logging.py. "
        "Without it, records with component=ui (most of the app) only "
        "reach the console."
    )
    assert "app_handler" in diag_source, (
        "Expected the new handler to be named app_handler for readability."
    )


def test_app_handler_has_catchall_filter_attached(diag_source: str) -> None:
    """Locate the app_handler block and require addFilter(CatchAllOtherFilter())."""
    # Slice the source around the app_handler construction so we don't
    # accidentally match on the wrong handler.
    idx = diag_source.find('logs_dir / "app.log"')
    if idx < 0:
        idx = diag_source.find("logs_dir / 'app.log'")
    assert idx >= 0, "app.log handler block not found"
    block = diag_source[idx : idx + 600]
    assert "CatchAllOtherFilter()" in block, (
        "app_handler is constructed but CatchAllOtherFilter() is no longer "
        "attached. That means every record (including db / download / viewer) "
        "will now leak into app.log."
    )


def test_app_handler_is_registered_in_async_and_sync_paths(diag_source: str) -> None:
    """Both the QueueListener path and the bare addHandler path must include app_handler."""
    # async path: handlers are passed in a list to _install_async_file_logging
    async_path_present = (
        "viewer_handler, download_handler, db_handler, app_handler" in diag_source
    )
    # sync path: explicit root.addHandler(app_handler)
    sync_path_present = "root.addHandler(app_handler)" in diag_source

    assert async_path_present, (
        "_install_async_file_logging is no longer called with app_handler. "
        "When AIPACS_ASYNC_LOGGING is enabled (default), app.log will stay empty."
    )
    assert sync_path_present, (
        "root.addHandler(app_handler) is missing in the synchronous logging "
        "path. When AIPACS_ASYNC_LOGGING=0, app.log will stay empty."
    )


def test_no_handler_dropped_from_async_list(diag_source: str) -> None:
    """All four file handlers must appear in the async listener list together."""
    # If someone removes one handler from the list, async logging silently
    # stops emitting to that file. Guard with a literal substring check.
    assert "viewer_handler" in diag_source
    assert "download_handler" in diag_source
    assert "db_handler" in diag_source
    assert "app_handler" in diag_source
