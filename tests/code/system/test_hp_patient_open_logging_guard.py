"""Regression guard: error paths in _hp_patient_open.py must use _logger,
not the print() rebind which sends everything to DEBUG level (below the
app.log INFO threshold).

Background — 2026-05-28 (Stage 10 audit)
=========================================
_hp_patient_open.py installs a module-level rebind at lines 13-16:

    def print(*args, **_kw):
        _print_logger.debug(' '.join(str(a) for a in args))

That rebind protects against synchronous console I/O on Windows but it
also downgrades EVERYTHING to DEBUG level. The app.log handler ships at
INFO threshold, so error-path messages like "Error in patient
double-click handler" never reach the file when called via print().

Stage 10 fix: route error/warning paths through _logger.error /
_logger.warning directly so they bypass the rebind and clear the
threshold. Success-path workflow traces ("Activated tab at index N",
"Removed study from opening studies set") stay at print() → DEBUG —
they\'re low-priority and would flood app.log if promoted.

This guard makes sure the error-path call sites do not silently revert
to print(). The failure mode is invisible (no exception, just less
observability) so a structural check is the only reliable defence.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
HP_PATIENT_OPEN = (
    REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
    / "home_panel" / "_hp_patient_open.py"
)


@pytest.fixture(scope="module")
def src() -> str:
    return HP_PATIENT_OPEN.read_text(encoding="utf-8-sig")


def test_print_rebind_remains(src: str) -> None:
    """The rebind itself is intentional — keep it. The Stage 10 fix routes
    error paths AROUND it via _logger.error/warning, not by removing it.
    """
    assert "def print(*args" in src, (
        "The module-level print() → _logger.debug rebind has been removed. "
        "That rebind protects against synchronous console I/O on Windows. "
        "If you intend to drop it, restore an equivalent guard or document "
        "why the protection is no longer needed."
    )


def test_error_paths_use_logger_not_print(src: str) -> None:
    """13 error-path messages must NOT regress to print()."""
    forbidden_substrings = [
        # L258 + L733 — attachment download error (two occurrences in the file)
        'print(f"⚠️ [THREAD] Error downloading attachments',
        # L398 — existing widget recovery
        'print(f"⚠️ Existing widget for study',
        # L422 — existing tab switch
        'print(f"⚠️ Error switching to existing tab',
        # L513 — tab activate
        'print(f"⚠️ [TAB] Error activating tab',
        # L519 — setCurrentWidget
        'print(f"⚠️ [TAB] Error setting current widget',
        # L543 — forced on_tab_activated
        'print(f"⚠️ [TAB] Failed forced on_tab_activated',
        # L604 — series info fetch (Warning text)
        'print(f"Warning: Could not fetch series info',
        # L679 — DM add
        'print(f"⚠️ Error adding to Download Manager',
        # L710 — UI scheduling
        'print(f"⚠️ [UI] Error scheduling UI tasks',
        # L808 — background setup
        'print(f"⚠️ [BACKGROUND] Error in background setup',
        # L821 + L935 — patient double-click handler
        'print(f"Error in patient double-click handler',
        # L870 — opening studies cleanup
        'print(f"Error removing study from opening studies',
        # L930 — Zeta DM creation
        'print("Failed to create Zeta Download Manager")',
        # L977 — tab close
        'print(f"⚠️ Error closing tab',
        # L1015 — signal-emit
        'print(f"⚠️ Error emitting series_downloaded signal',
    ]
    offending = [s for s in forbidden_substrings if s in src]
    assert not offending, (
        "One or more error-path messages reverted to print(). The "
        "module-level rebind sends them to DEBUG level which is below the "
        "app.log INFO threshold, so failures become invisible. Use "
        "_logger.error / _logger.warning directly instead. Offending: "
        f"{offending}"
    )


def test_workflow_trace_prints_remain(src: str) -> None:
    """The success-trace prints SHOULD stay at print() → debug.

    Promoting them to INFO would flood app.log on every patient open.
    """
    expected_present = [
        'print(f"✅ [TAB] Activated tab at index {tab_index}")',
        'print("✅ [TAB] Activated tab via setCurrentWidget")',
        'print(f"✅ [TAB] Forced on_tab_activated for study {study_uid}")',
        'print(f"Removed study {study_uid} from opening studies set")',
    ]
    missing = [s for s in expected_present if s not in src]
    assert not missing, (
        "Success-trace print() lines were removed or promoted out of "
        f"DEBUG. Missing: {missing}. Keep these as print() → debug so "
        "they\'re available when AIPACS_LOG_LEVEL=DEBUG without flooding "
        "the normal INFO+ stream."
    )


def test_minimum_logger_call_count_on_error_paths(src: str) -> None:
    """A quick sanity counter: there should be at least 12 _logger.error
    / _logger.warning calls in this file after Stage 10.

    A bulk revert to print() would drop this count.
    """
    error_count = src.count("_logger.error(") + src.count("_logger.warning(")
    assert error_count >= 12, (
        f"_logger.error/warning call count dropped to {error_count} "
        "(expected >= 12 after Stage 10). Someone likely reverted error "
        "paths back to print()."
    )
