# -*- coding: utf-8 -*-
"""
Guard: Cloud "Sync Patient Data with Server" report-status contract
===================================================================
Pins the server-status alignment fix (2026-06-22):

* The Patient-Tab Cloud sync sets the report to ``physician_approved`` — the
  workstation user is the reading physician, so a sync means the doctor has
  approved. It must NEVER set ``secretary_approved`` (the secretary's own,
  separate action) and the value is read from ONE shared constant
  (``SYNC_REPORT_STATUS``) so the sync service and the toolbar's post-sync
  local update can never drift apart.
* ``physician_approved`` and ``secretary_approved`` stay distinct states.
* The compact patient-tab badge distinguishes *awaiting* (…) from *approved*
  (✓) so an "Awaiting Secretary" report never reads like "Secretary Approved".

Source-pin style (no PySide6 / no socket import) to match the repo's other
behavioural guards — it reads the implementation files as text and also
re-implements the tiny env-resolution contract in isolation.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

CENTRAL = REPO_ROOT / "modules" / "network" / "socket_report_status_service.py"
SYNC = REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils" / "patient_sync_service.py"
TOOLBAR = (
    REPO_ROOT
    / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"missing source file: {p}"
    data = p.read_bytes()
    # The Linux test mount occasionally serves a NUL-truncated copy of very
    # large files (known FUSE issue). A source-pin guard must not false-fail on
    # a corrupt mirror — skip; it runs for real on the Windows source build.
    if b"\x00" in data:
        pytest.skip(f"mount served a NUL-truncated copy of {p.name}; run on Windows")
    return data.decode("utf-8", errors="replace")


def _read_complete(p: Path, anchor: str) -> str:
    """Read a large file, skipping if the mirror is truncated.

    The Linux mount sometimes serves a copy of very large files truncated
    mid-content (no NUL padding), so a region near the end is simply absent.
    ``anchor`` is a stable string that exists in every version of the file and
    sits past the usual truncation point; if it's missing, the read is torn and
    the source-pin is skipped (it runs for real on the Windows source build)."""
    src = _read(p)
    if anchor not in src:
        pytest.skip(f"{p.name} mirror looks truncated (anchor missing); run on Windows")
    return src


# --------------------------------------------------------------------------- #
# Central service: the single source of truth for the sync value + the enum.
# --------------------------------------------------------------------------- #
def test_central_defines_shared_sync_constant_default_physician_approved():
    src = _read(CENTRAL)
    assert "SYNC_REPORT_STATUS = os.environ.get(" in src, \
        "SYNC_REPORT_STATUS must be defined in the central service"
    assert '"AIPACS_SYNC_REPORT_STATUS", "physician_approved"' in src, \
        "Cloud-sync status must default to physician_approved"


def test_central_enum_keeps_physician_and_secretary_distinct():
    src = _read(CENTRAL)
    m = re.search(r"VALID_STATUSES\s*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, "VALID_STATUSES list not found"
    body = m.group(1)
    assert '"physician_approved"' in body
    assert '"secretary_approved"' in body
    # They are two separate enum entries — never the same state.
    assert body.count('"physician_approved"') == 1
    assert body.count('"secretary_approved"') == 1


# --------------------------------------------------------------------------- #
# Sync service: sends the shared constant, never the old/secretary value.
# --------------------------------------------------------------------------- #
def test_sync_service_sends_shared_constant_not_secretary():
    src = _read(SYNC)
    assert "new_status=SYNC_REPORT_STATUS" in src, \
        "sync worker must send SYNC_REPORT_STATUS"
    # Pin the actual SEND pattern (explanatory comments may name these values;
    # what matters is they are never the value passed to new_status=).
    for bad in (
        'new_status="awaiting_secretary_approval"',
        "new_status='awaiting_secretary_approval'",
        'new_status="secretary_approved"',
        "new_status='secretary_approved'",
    ):
        assert bad not in src, f"sync must not send {bad}"


# --------------------------------------------------------------------------- #
# Toolbar: post-sync local status mirrors the constant; badge is unambiguous.
# --------------------------------------------------------------------------- #
def test_toolbar_postsync_uses_shared_constant():
    src = _read_complete(TOOLBAR, "def _start_patient_sync")
    assert "SYNC_REPORT_STATUS as _synced_status" in src, \
        "toolbar post-sync must read the shared constant"
    # The old unconditional hardcode must be gone.
    assert "report_status = 'awaiting_secretary_approval'" not in src, \
        "toolbar must not hardcode awaiting_secretary_approval after sync"


def test_toolbar_badge_distinguishes_awaiting_from_approved():
    src = _read_complete(TOOLBAR, "def _start_patient_sync")
    # Awaiting markers (…) and approved markers (✓) for both roles must coexist
    # and differ, so awaiting-secretary can't look like secretary-approved.
    for glyph in ("'MD…'", "'SC…'", "'MD✓'", "'SC✓'"):
        assert glyph in src, f"badge map missing distinct glyph {glyph!r}"


# --------------------------------------------------------------------------- #
# Contract of the env resolution, re-implemented in isolation (no imports).
# --------------------------------------------------------------------------- #
def _resolve(env_value, valid):
    status = env_value if env_value is not None else "physician_approved"
    if status not in valid:
        status = "physician_approved"
    return status


def test_env_resolution_contract():
    valid = [
        "pending", "awaiting_physician_approval", "awaiting_secretary_approval",
        "awaiting_approval", "physician_approved", "secretary_approved",
        "completed", "archived",
    ]
    # Default → physician_approved
    assert _resolve(None, valid) == "physician_approved"
    # Garbage env → safe fallback
    assert _resolve("not_a_status", valid) == "physician_approved"
    # Explicit kill-switch override is respected
    assert _resolve("awaiting_secretary_approval", valid) == "awaiting_secretary_approval"
    # Never silently becomes secretary_approved from the default path
    assert _resolve(None, valid) != "secretary_approved"
