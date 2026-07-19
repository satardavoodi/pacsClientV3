# -*- coding: utf-8 -*-
"""Tests for the status -> INO approvalFlags mapping.

Guards the fix for "report/patient status set from AI-PACS doesn't update on the
INO reception side": ``/api/pacs/update-report`` now also sends
``approvalFlags`` derived from the chosen status (both the Report Editor and the
EchoMind send paths), so a downgrade clears the flags INO renders the status
from. See docs/reports/AINO_RECEPTION_STATUS_SYNC_REVIEW_2026-07-09.md.
"""

import pytest

pytest.importorskip("PySide6.QtCore")

from modules.network.socket_report_status_service import (  # noqa: E402
    UPDATE_REPORT_APPROVAL_FLAGS,
    VALID_STATUSES,
    approval_flags_for_status,
)


@pytest.mark.parametrize(
    "status,physician,secretary",
    [
        ("pending", False, False),
        ("awaiting_physician_approval", False, False),
        ("awaiting_approval", False, False),
        ("physician_approved", True, False),
        # 2026-07-15 (user directive): awaiting_secretary_approval is a clean slate
        # handed to the secretary — BOTH flags cleared (default on;
        # AIPACS_AWAITING_SECRETARY_BOTH_FALSE=0 restores True/False).
        ("awaiting_secretary_approval", False, False),
        ("secretary_approved", True, True),
        ("completed", True, True),
        ("archived", True, True),
    ],
)
def test_approval_flags_for_status(status, physician, secretary):
    flags = approval_flags_for_status(status)
    assert flags == {"physicianApproved": physician, "secretaryApproved": secretary}


def test_downgrade_clears_flags():
    """The core fix: moving a completed report back to awaiting clears both."""
    assert approval_flags_for_status("completed") == {
        "physicianApproved": True, "secretaryApproved": True,
    }
    assert approval_flags_for_status("awaiting_physician_approval") == {
        "physicianApproved": False, "secretaryApproved": False,
    }


def test_unknown_or_empty_status_is_safe():
    assert approval_flags_for_status("") == {"physicianApproved": False, "secretaryApproved": False}
    assert approval_flags_for_status("not_a_status") == {"physicianApproved": False, "secretaryApproved": False}
    assert approval_flags_for_status(None) == {"physicianApproved": False, "secretaryApproved": False}


def test_every_valid_status_maps_without_error():
    # Physician-approval must be monotonic: a secretary-approved report is also
    # physician-approved (you can't have secretary approval without physician).
    for status in VALID_STATUSES:
        flags = approval_flags_for_status(status)
        if flags["secretaryApproved"]:
            assert flags["physicianApproved"], f"{status}: secretary approved but not physician"


def test_flag_default_on():
    # Default-on so the fix is active out of the box.
    assert isinstance(UPDATE_REPORT_APPROVAL_FLAGS, bool)
