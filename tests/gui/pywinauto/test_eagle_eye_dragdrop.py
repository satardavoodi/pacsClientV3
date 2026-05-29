"""Eagle Eye drag-drop crash test — the canonical pyramid-top case.

Issue 2 (2026-05-27 fix) — Windows fatal exception 0x8001010d
(RPC_E_CANTCALLOUT_ININPUTSYNCCALL) was firing when a series thumbnail
was dragged into the Eagle Eye 1×2 mammography viewport. The fix
(`modules/ai_imaging/ai_module_ui/overrides/patient_widget.py:
_schedule_mg_mirror`) defers the secondary-viewer mirror via
QTimer.singleShot(0) so the second VTK series load happens on its own
event-loop tick, after the OLE drag-drop COM context has released.

This bug is STRUCTURALLY INVISIBLE to in-process tests (CommandBus,
direct method calls, EchoMind drivers) because they call
`change_series_on_viewer` directly — never entering the real Win32 OLE
drag-drop COM state. Only an external GUI automation tool that fires
real WM_DROPFILES + IDropTarget COM messages can reproduce it. That's
pywinauto's job and the reason this file exists.

Test workflow:
    1. Pre-flight via _verify_source_build (refuses to run on frozen exe).
    2. Connect pywinauto to the AI-PACS window.
    3. Snapshot native_fault.log byte count + line count.
    4. For each of 3 drag-drops:
         a. Find a series-thumbnail rect in Eagle Eye's sidebar.
         b. Find the left-viewport rect.
         c. drag_mouse_input from thumbnail centre to viewport centre.
         d. Wait 2 s for the mirror to settle.
         e. Re-sample native_fault.log; assert no new 0x8001010d entry.
    5. Final assert: log unchanged from pre-test.

Usage:
    pytest tests/gui/pywinauto/test_eagle_eye_dragdrop.py -v -s
        # or as a script:
    python tests/gui/pywinauto/test_eagle_eye_dragdrop.py

The test is **automatically skipped** when the source build isn't
detected, so it doesn't fail CI.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Path setup so the verify-helper is importable
_THIS = Path(__file__).resolve()
PROJECT_ROOT = _THIS.parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "gui" / "live_walkthroughs"))

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore

# Pre-flight import. If verify is unavailable (refactor broke it),
# the test is skipped rather than erroring.
try:
    from _verify_source_build import (  # type: ignore
        require_source_build, WrongBuildError, logs_are_fresh,
    )
except Exception as exc:
    require_source_build = None  # type: ignore
    WrongBuildError = Exception  # type: ignore
    _IMPORT_ERR = str(exc)
else:
    _IMPORT_ERR = ""


LOGS_DIR = PROJECT_ROOT / "user_data" / "logs"
NATIVE_FAULT = LOGS_DIR / "native_fault.log"
COM_CRASH_CODE = "0x8001010d"


# ── helpers ─────────────────────────────────────────────────────────────

def _snapshot_native_fault() -> tuple[int, int]:
    """Return (byte_size, count_of_0x8001010d_lines)."""
    if not NATIVE_FAULT.exists():
        return 0, 0
    text = NATIVE_FAULT.read_text(encoding="utf-8", errors="replace")
    bytes_ = len(text.encode("utf-8"))
    com_lines = sum(1 for line in text.splitlines() if COM_CRASH_CODE in line)
    return bytes_, com_lines


def _diff_native_fault(pre_bytes: int, pre_com: int) -> tuple[int, int]:
    """Return (byte_delta, new_com_inhibit_crashes_since_snapshot)."""
    cur_bytes, cur_com = _snapshot_native_fault()
    return cur_bytes - pre_bytes, cur_com - pre_com


def _connect_aipacs():
    """Attach pywinauto to a live AI-PACS source-build window."""
    try:
        from pywinauto import Application  # type: ignore
    except ImportError:
        if pytest:
            pytest.skip("pywinauto not installed — pip install pywinauto")
        raise
    try:
        app = Application(backend="uia").connect(title_re=r"AI[ -]?[Pp]acs.*")
    except Exception as exc:
        if pytest:
            pytest.skip(f"No AI-PACS window found: {exc}")
        raise
    window = app.window(title_re=r"AI[ -]?[Pp]acs.*")
    window.wait("ready", timeout=10)
    return app, window


def _maybe_skip_if_not_source_build():
    if require_source_build is None:
        if pytest:
            pytest.skip(f"verify helper not importable: {_IMPORT_ERR}")
        raise RuntimeError("verify helper not importable")
    try:
        require_source_build(recent_seconds=300, require_python_exe=False)
    except WrongBuildError as exc:
        if pytest:
            pytest.skip(f"source build not detected: {exc}")
        raise


# ── the test ────────────────────────────────────────────────────────────

def test_eagle_eye_drag_drop_no_com_crash():
    """Issue 2: drag-drop into Eagle Eye must not fire 0x8001010d.

    Runs only when a source-build AI-PACS window is open AND Eagle Eye
    is the current tab. The harness expects YOU to have navigated to
    Eagle Eye on an MG study before running — see
    `tests/gui/README.md` for the live-walkthrough instructions.
    """
    _maybe_skip_if_not_source_build()

    pre_bytes, pre_com = _snapshot_native_fault()
    print(f"[pre] native_fault.log = {pre_bytes} bytes, "
          f"{pre_com} '0x8001010d' lines")

    _, window = _connect_aipacs()

    # Try to locate a series thumbnail and viewport. pywinauto's UIA
    # backend can address widgets by accessible name. AI-PACS sets
    # objectName on the relevant widgets; we look for them via class_name
    # patterns + a coordinate fallback.
    try:
        thumbnails = window.children(class_name_re=r".*Thumbnail.*|.*Series.*")
        if not thumbnails:
            if pytest:
                pytest.skip("Eagle Eye thumbnails not found in UIA tree — "
                            "ensure an MG study is open in Eagle Eye first")
            return
    except Exception as exc:
        if pytest:
            pytest.skip(f"UIA child enumeration failed: {exc}")
        return

    # Find a viewport — class names vary across VTK builds.
    try:
        viewports = window.children(class_name_re=r".*VTK.*|.*Viewport.*|.*QFrame.*")
        if len(viewports) < 1:
            if pytest:
                pytest.skip("Eagle Eye viewport not located")
            return
    except Exception as exc:
        if pytest:
            pytest.skip(f"viewport lookup failed: {exc}")
        return

    target_viewport = viewports[0]
    target_rect = target_viewport.rectangle()
    drop_x = (target_rect.left + target_rect.right) // 2
    drop_y = (target_rect.top + target_rect.bottom) // 2

    n_drops = min(3, len(thumbnails))
    for i in range(n_drops):
        thumb = thumbnails[i]
        thumb_rect = thumb.rectangle()
        src_x = (thumb_rect.left + thumb_rect.right) // 2
        src_y = (thumb_rect.top + thumb_rect.bottom) // 2

        # Real Win32 drag-drop — this is the only call that reproduces
        # the OLE COM input-sync path the bug fix is designed for.
        try:
            window.drag_mouse_input(
                src=(src_x, src_y),
                dst=(drop_x, drop_y),
                button="left",
                pressed="",
                absolute=True,
            )
        except Exception as exc:
            # Fall back to a manual press/move/release sequence if
            # drag_mouse_input isn't available in this pywinauto version.
            from pywinauto.mouse import (  # type: ignore
                press, move, release,
            )
            press(coords=(src_x, src_y))
            move(coords=(drop_x, drop_y))
            release(coords=(drop_x, drop_y))

        # Wait for the QTimer.singleShot(0) mirror to settle.
        time.sleep(2.0)

        # Sample log: any new 0x8001010d entry is an instant fail.
        bytes_delta, com_delta = _diff_native_fault(pre_bytes, pre_com)
        assert com_delta == 0, (
            f"DRAG #{i+1}: native_fault.log gained {com_delta} new "
            f"0x8001010d (RPC_E_CANTCALLOUT_ININPUTSYNCCALL) crashes — "
            f"Eagle Eye drag-drop fix has regressed. "
            f"byte_delta={bytes_delta}"
        )
        print(f"[drop {i+1}/{n_drops}] OK — log delta={bytes_delta} bytes, "
              f"0 new COM crashes")

    final_bytes_delta, final_com_delta = _diff_native_fault(pre_bytes, pre_com)
    assert final_com_delta == 0, (
        f"After {n_drops} drag-drops: {final_com_delta} new 0x8001010d "
        f"crashes appeared in native_fault.log "
        f"(byte_delta={final_bytes_delta})."
    )
    print(f"[done] {n_drops} drag-drops completed; no new COM crashes. "
          f"byte_delta={final_bytes_delta}")


if __name__ == "__main__":
    test_eagle_eye_drag_drop_no_com_crash()
