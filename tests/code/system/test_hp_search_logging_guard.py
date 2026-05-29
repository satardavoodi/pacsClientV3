"""Regression guard: error paths in _hp_search.py must use _logger, not print().

Background — 2026-05-28 (Stage 2 audit)
=======================================
The catch-all ``app.log`` handler that landed earlier in the day made
every previously-invisible application record visible. The Stage 2 audit
found that ``_hp_search.py`` had nine ``print()`` calls — five of them
on error paths (default search, socket-row add, download-status check
inner + outer, socket-thumbnail error). ``print()`` only reaches stderr,
so the new catch-all handler couldn't surface failures from those
paths. The fix replaced those five with ``_logger.error`` /
``_logger.warning`` so a per-row failure leaves a stack-trace record in
``app.log``.

This guard makes sure no one quietly reverts those error paths back to
``print()`` during a future refactor — the failure mode is invisible
(no exception, just less observability) so a structural check is the
only reliable defence.

The three remaining ``print()`` calls in the file are workflow-trace
markers in ``cancel_search`` (``[CANCEL_SEARCH] ...``); those are
allowed because they're informational, not error-path.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HP_SEARCH = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "_hp_search.py"


@pytest.fixture(scope="module")
def src() -> str:
    return HP_SEARCH.read_text(encoding="utf-8-sig")


def test_default_search_error_uses_logger(src: str) -> None:
    """`perform_default_search` must log failures via _logger.error."""
    # Locate `perform_default_search` body.
    idx = src.find("def perform_default_search(self):")
    assert idx >= 0, "perform_default_search() removed?"
    # Look ahead ~30 lines for the except block.
    block = src[idx : idx + 1500]
    assert "_logger.error" in block, (
        "perform_default_search() no longer logs errors via _logger.error. "
        "Failures here happen at boot; if they're print()-only, the app.log "
        "handler can't surface them. See Stage 2 audit 2026-05-28."
    )
    assert 'print(f"Error in default search' not in block, (
        "perform_default_search() reverted to print() for the error path. "
        "That makes default-search failures invisible in app.log."
    )


def test_socket_row_add_error_uses_logger(src: str) -> None:
    """_add_socket_patient_to_table must log per-row failures via _logger."""
    idx = src.find("def _add_socket_patient_to_table(self, patient):")
    assert idx >= 0, "_add_socket_patient_to_table() removed?"
    # The error handler is at the end of the method — search ~25KB ahead
    # to cover the whole method body.
    block = src[idx : idx + 25000]
    assert 'print(f"Error adding Socket patient to table' not in block, (
        "_add_socket_patient_to_table() reverted to print() on its error path. "
        "That hides silently-dropped patient rows — exactly the failure mode "
        "the user has flagged repeatedly."
    )
    # The guard requires the structured-log style introduced by the fix.
    assert 'Error adding Socket patient to table' in block, (
        "Error-path message text changed — review whether the new message "
        "is logged via _logger.error and update this guard if so."
    )


def test_socket_thumbnail_error_uses_logger(src: str) -> None:
    """The right-panel socket-thumbnail error path must log via _logger.error."""
    # The socket thumbnail error sits inside the right-panel fetch helper.
    assert 'print(f"Socket thumbnail error' not in src, (
        "Socket thumbnail error path reverted to print(). The 2026-05-27 "
        "GetStudyInfo stall regression depends on this path having a "
        "stack-trace record in app.log when it fires."
    )
    assert "Socket thumbnail error" in src, (
        "Socket thumbnail error message text changed — review whether the "
        "new message is logged via _logger.error and update this guard."
    )


def test_download_status_check_errors_use_logger(src: str) -> None:
    """Both download-status error paths must log via _logger (warning + error)."""
    assert 'print(f"[WARN] Error in download status check' not in src, (
        "Download status inner-except reverted to print(). That hides "
        "DB-lock and storage-layer issues that mark every row not_downloaded."
    )
    assert 'print(f"Error checking download status' not in src, (
        "Download status outer-except reverted to print()."
    )
    # Both error messages should still appear, now via logger.
    assert "Error in download status check" in src
    assert "Error checking download status" in src


def test_cancel_search_prints_allowed(src: str) -> None:
    """`cancel_search` may keep its [CANCEL_SEARCH] print() trace.

    Allow-listed: those are workflow markers, not error paths. The
    test exists so future audits don't accidentally lump them in with
    the error-path replacements.
    """
    # Find the cancel_search method and verify it still has the markers.
    idx = src.find("def cancel_search(self):")
    assert idx >= 0
    block = src[idx : idx + 1500]
    assert "[CANCEL_SEARCH]" in block, (
        "The cancel-search workflow markers disappeared. They're not "
        "errors but they're useful diagnostic context — restore them or "
        "remove this guard."
    )
