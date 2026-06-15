"""Guard the tab hover/active animation lifetime fix (2026-06-14).

native_fault.log (installed build, other PC) captured a Windows access violation:

    patient_tab_widget.py line 458 in animate_hover
    patient_tab_widget.py line 448 in enterEvent
    main.py line 907 in notify

Root cause: animate_hover / animate_active created a local QPropertyAnimation with
no parent and no stored reference, called start(), and returned. Python could then
garbage-collect the wrapper while the 150-200 ms animation was still running, which
freed the underlying C++ QObject mid-flight -> access violation. Fast hovering across
tabs (many short-lived animations) made it likely.

Fix: keep ONE animation per widget, parented to self and stored on self, so it is
never collected while running. This is a static source guard (constructing the Qt
widgets pulls heavy deps); it asserts the lifetime-safe shape in both sibling widgets.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_BASE = _REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
_PATIENT_TAB = _BASE / "patient_tab_widget.py"
_SERVICE_TAB = _BASE / "service_tab_widget.py"

# Exactly the buggy 2-arg form: QPropertyAnimation(self, b"geometry")  -> no parent.
_TWO_ARG = re.compile(r'QPropertyAnimation\(\s*self\s*,\s*b"geometry"\s*\)')
# The safe parented form: QPropertyAnimation(self, b"geometry", self)
_THREE_ARG = re.compile(r'QPropertyAnimation\(\s*self\s*,\s*b"geometry"\s*,\s*self\s*\)')


_THUMB_MGR = (
    _REPO / "PacsClient" / "pacs" / "patient_tab" / "utils" / "thumbnail_manager.py"
)
# Buggy bare-local form on the progress border (no parent / no kept ref).
_TWO_ARG_BORDER = re.compile(
    r'QPropertyAnimation\(\s*widget\.progress_border\s*,\s*b"_border_width"\s*\)'
)


def test_thumbnail_priority_flash_animation_is_parented_and_referenced():
    """thumbnail_manager priority-flash border animations must be parented + kept
    referenced — a bare local one GC'd mid-flash access-violates, and a large
    all-modality search flashes many at once (the 46692 crash class)."""
    src = _THUMB_MGR.read_text(encoding="utf-8-sig")
    assert not _TWO_ARG_BORDER.search(src), (
        "priority-flash QPropertyAnimation must be parented to progress_border (3-arg)"
    )
    # Both the flash and the return animation keep a reference on the border.
    assert "_priority_flash_anim" in src and "_priority_flash_anim2" in src
    assert 'b"_border_width", widget.progress_border)' in src


@pytest.mark.parametrize(
    "path, stored_attrs",
    [
        (_PATIENT_TAB, ("_hover_animation", "_active_animation")),
        (_SERVICE_TAB, ("_hover_animation",)),
    ],
)
def test_geometry_animation_is_parented_and_referenced(path, stored_attrs):
    src = path.read_text(encoding="utf-8")

    # No bare 2-arg geometry animation may remain (that is the GC-able crash form).
    assert not _TWO_ARG.search(src), (
        f"{path.name}: geometry QPropertyAnimation must be parented to self "
        f"(3-arg form) so it isn't GC'd while running"
    )
    # The parented form must be present (the fix).
    assert _THREE_ARG.search(src), (
        f"{path.name}: expected QPropertyAnimation(self, b\"geometry\", self)"
    )
    # And a reference must be kept on self for each animated effect.
    for attr in stored_attrs:
        assert f"self.{attr}" in src, (
            f"{path.name}: animation must be stored on self.{attr} (kept reference)"
        )
