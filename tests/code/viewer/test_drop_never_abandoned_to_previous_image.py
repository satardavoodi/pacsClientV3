"""OPT-36 — a drop is NEVER abandoned back to the previous image (50336, 2026-07-14).

THE BUG (live, patient 50336 series 1000002 — a previous exam dragged mid-download):

    14:35:03.083  [LOAD] Error loading series 1000002: WinError 3 (study folder not there yet)
    14:35:03.129  "not resident yet — awaiting download"   <- awaiting + spinner: CORRECT
    14:35:05.126  disk-ready resume: series=1000002 settled
                  (visible=1 disk=1 settled_visible=False exhausted=False authority=True)
                  -> ViewportLoadingStateCleared / ViewportLoadSucceeded    <- FAKE

The viewer entered the loading state correctly. Then the resume watchdog ABANDONED it:

  BUG A  `_disk_ready_complete` never saw the `_has_part` flag the call site had already
         computed. A PREVIOUS EXAM is not in the DB yet, so there is no server `expected`
         count -> the weak stable-count fallback ran -> a download that had written its
         FIRST file and not yet landed the second was "stable at 1" across two ticks ->
         a 1-of-N series was declared COMPLETE.

  BUG B  `_authority_settled` (and `_exhausted`) were OR'd into the settle stop-condition,
         BYPASSING the `_shows_awaited` guard. The live check had CORRECTLY decided the
         viewport was not showing the awaited series (`settled_visible=False`) — the
         authority overrode it, cleared `_awaiting_series_number`, hid the loading spinner
         and logged a FAKE `ViewportLoadSucceeded`. The PREVIOUS image stayed on screen.

Re-dragging later "worked" only because by then the files were on disk = the reported
unreliability.

REQUIREMENT: if the files are not on disk yet, the viewport STAYS in the loading state
until the image is available (or until the user drops another series). It must NEVER fall
back to the previous image.
"""

import ast
import os

import pytest


# ── the pure completeness decision (BUG A) ────────────────────────────────
def _load_disk_ready_complete():
    """Load the pure `_disk_ready_complete` from source (no Qt/VTK import)."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    path = os.path.join(
        root, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "_vc_progressive.py"
    )
    with open(path, encoding="utf-8-sig") as fh:   # the source carries a UTF-8 BOM
        src = fh.read()
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_disk_ready_complete":
            mod = ast.Module(body=[node], type_ignores=[])
            ns = {}
            exec(compile(mod, "<disk_ready_complete>", "exec"), ns)  # noqa: S102
            return ns["_disk_ready_complete"], src
    raise AssertionError("_disk_ready_complete not found")


DISK_READY_COMPLETE, PROGRESSIVE_SRC = _load_disk_ready_complete()


# ── BUG A: never settle a folder the DM is still writing ──────────────────
def test_A_the_exact_50336_case_1_file_stable_but_still_downloading():
    """disk=1, stable across two ticks, expected UNKNOWN, a .part in flight -> NOT complete."""
    assert DISK_READY_COMPLETE(1, 0, 1, True) is False


def test_A_legacy_3_arg_call_is_byte_identical():
    """has_part defaults to False -> every existing caller/test behaves exactly as before."""
    assert DISK_READY_COMPLETE(1, 0, 1) is True          # legacy stable-count fallback
    assert DISK_READY_COMPLETE(5, 10, 5) is False        # expected known, not met
    assert DISK_READY_COMPLETE(10, 10, 9) is True        # expected known and met
    assert DISK_READY_COMPLETE(0, 0, 0) is False         # nothing on disk


def test_A_part_only_gates_the_UNKNOWN_expected_fallback():
    """When the server count is KNOWN and MET, a stray .part must not block the load."""
    assert DISK_READY_COMPLETE(10, 10, 10, True) is True
    assert DISK_READY_COMPLETE(9, 10, 9, True) is False


def test_A_stable_count_with_no_part_still_completes():
    """The download finished (no .part) and the count settled -> complete, as before."""
    assert DISK_READY_COMPLETE(30, 0, 30, False) is True


def test_A_growing_download_is_never_complete():
    assert DISK_READY_COMPLETE(2, 0, 1, True) is False
    assert DISK_READY_COMPLETE(2, 0, 1, False) is False   # count changed -> not stable


def test_A_call_site_passes_has_part():
    assert "_disk_ready_complete(count, expected, prev, _has_part)" in PROGRESSIVE_SRC


# ── BUG B: settle requires the AWAITED series to be displayed ─────────────
def _settle(shows_awaited, vis, disk, attempts, authority, max_attempts=6,
            require_displayed=True):
    """Mirrors the settle stop-condition in _maybe_resume_awaiting_from_disk."""
    settled_visible = vis > 0 and vis >= disk and shows_awaited
    exhausted = attempts >= max_attempts
    authority_settled = bool(authority)
    if require_displayed and not shows_awaited:
        authority_settled = False
        exhausted = False
    return bool(settled_visible or exhausted or authority_settled)


def test_B_the_exact_50336_settle_must_NOT_fire():
    """settled_visible=False, exhausted=False, authority=True, series NOT displayed."""
    assert _settle(shows_awaited=False, vis=1, disk=1, attempts=0, authority=True) is False


def test_B_authority_cannot_settle_a_viewport_not_showing_the_awaited_series():
    for attempts in (0, 3, 99):
        assert _settle(False, vis=5, disk=5, attempts=attempts, authority=True) is False


def test_B_exhaustion_cannot_silently_abandon_the_drop():
    """Budget exhausted but the series was never displayed -> must NOT settle (no fake success)."""
    assert _settle(shows_awaited=False, vis=1, disk=90, attempts=6, authority=False) is False


def test_B_the_47084_livelock_stop_is_PRESERVED():
    """In the livelock this guard exists to break, the viewport IS showing the awaited series."""
    assert _settle(shows_awaited=True, vis=99, disk=99, attempts=0, authority=True) is True
    assert _settle(shows_awaited=True, vis=48, disk=99, attempts=6, authority=False) is True
    assert _settle(shows_awaited=True, vis=99, disk=99, attempts=0, authority=False) is True


def test_B_normal_settle_when_the_awaited_series_is_fully_displayed():
    assert _settle(shows_awaited=True, vis=30, disk=30, attempts=0, authority=False) is True


def test_B_kill_switch_restores_the_legacy_abandonment():
    assert _settle(False, vis=1, disk=1, attempts=0, authority=True,
                   require_displayed=False) is True


# ── BUG C: the retry budget is consumed only when there is NO progress ────
def _refund(prev, count, attempts, enabled=True):
    if enabled and prev is not None and count > prev and attempts > 0:
        return 0
    return attempts


def test_C_progress_refunds_the_retry_budget():
    assert _refund(prev=1, count=4, attempts=5) == 0      # download is progressing
    assert _refund(prev=1, count=4, attempts=0) == 0


def test_C_no_progress_consumes_the_budget():
    assert _refund(prev=4, count=4, attempts=5) == 5      # stalled -> budget stands
    assert _refund(prev=None, count=1, attempts=3) == 3


def test_C_kill_switch():
    assert _refund(prev=1, count=4, attempts=5, enabled=False) == 5


# ── wiring pins ───────────────────────────────────────────────────────────
def test_wiring_flags_default_on_with_kill_switches():
    for flag in ("AIPACS_SETTLE_REQUIRES_DISPLAYED", "AIPACS_RESUME_BUDGET_ON_PROGRESS"):
        assert flag in PROGRESSIVE_SRC, f"{flag} missing"
        assert f'_os.getenv("{flag}", "1")' in PROGRESSIVE_SRC, f"{flag} must default to ON"


def test_wiring_authority_and_exhaustion_are_gated_on_shows_awaited():
    """If this pin fails, the authority can once again abandon a drop."""
    assert "if _SETTLE_REQUIRES_DISPLAYED and not _shows_awaited:" in PROGRESSIVE_SRC
    assert "_authority_settled = False" in PROGRESSIVE_SRC
    assert "_exhausted = False" in PROGRESSIVE_SRC


def test_wiring_exhausted_and_undisplayed_shows_a_loading_state_not_a_revert():
    assert "resume_budget_exhausted_series_not_displayed" in PROGRESSIVE_SRC
    assert "download_not_caught_up" in PROGRESSIVE_SRC


def test_wiring_not_yet_downloaded_is_not_logged_as_an_ERROR():
    """A folder the DM has not created yet is an expected transient, not a failure."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    path = os.path.join(
        root, "PacsClient", "pacs", "patient_tab", "ui", "patient_ui", "_vc_load.py"
    )
    src = open(path, encoding="utf-8-sig").read()
    assert "isinstance(e, (FileNotFoundError, NotADirectoryError))" in src
    assert "not on disk yet" in src
