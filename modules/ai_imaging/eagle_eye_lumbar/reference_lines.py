"""Which viewports may carry a reference line during a capture session.

The rule is one sentence: **the pane being evaluated is captured clean.** A
reference line is spatial context for a pane you are looking *from*, and an
obstruction across a pane you are looking *at* — it can lie over exactly the
disc, canal or root the frame exists to show, and once it is baked into the PNG
no later stage can remove it.

So during the sagittal sweep both sagittal panes are clean and the axial pane
keeps its line; during the axial sweep the axial pane is clean and both
sagittals keep theirs, because that is what shows the level being imaged. Which
panes those are is NOT decided here — ``CaptureSession.hide_reference_lines_on``
decides, so a future protocol changes the answer by changing its configuration.

**How, given the engine draws all-pairs.** ``_manage_reference_line_all_pairs``
paints every viewport from every other one; there is no per-viewport switch, and
adding one would mean editing a shared, plugin-mirrored authority used by the
whole workstation. Instead this draws normally and then clears the overlay on
the suppressed panes, using the same helpers the engine itself uses to clear
them. One extra pass over at most three viewports, no fork of the drawing code.

**What is restored.** Eagle Eye never mutates a global reference-line setting —
not the ``AIPACS_REFERENCE_LINES_ALL_PAIRS`` env flag, not the line style, not a
toolbar toggle. The only state it changes is which overlays are currently
painted, so restoring means one unsuppressed redraw: every pane gets its lines
back. ``restore()`` does exactly that and nothing more, because claiming to
save and restore a setting that was never touched would be theatre.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)


def _hide_lines_on_viewer(viewer: Any) -> bool:
    """Clear every reference-line overlay on one image viewer.

    Both backends, via their own clearing paths: the Qt bridge keeps overlay
    lines as a list on the widget, the VTK path keeps one actor per slot.
    Returns True if a clear was actually issued.
    """
    if viewer is None:
        return False
    try:
        if getattr(viewer, "IS_QT_BRIDGE", False):
            viewer.qt_viewer.clear_overlay_lines()
            return True
    except Exception as exc:
        logger.debug("eagle_eye: could not clear Qt overlay lines: %s", exc)
        return False

    try:
        # The engine's own "hide every slot" helper — importing it beats
        # reaching into `_ref_actor` / `_ref_line_slots` by hand, which is
        # private state that has already been restructured once.
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import reference_line
        reference_line.rl_hide_actor_if_any(viewer)
        return True
    except Exception as exc:
        logger.debug("eagle_eye: could not hide VTK reference lines: %s", exc)
        return False


class ReferenceLinePolicy:
    """Applies one capture session's reference-line rules, then puts them back.

    Single instance per run; ``apply_for(session)`` on every frame (it is cheap
    and idempotent), ``restore()`` once at the end.
    """

    __slots__ = ("_viewer_for", "_widget_for", "_redraw", "_active_session", "_applied")

    def __init__(self, viewer_for, widget_for, redraw):
        # Injected rather than reaching into the controller, so this is
        # testable with three fakes and no Qt.
        self._viewer_for = viewer_for      # role -> image viewer (or None)
        self._widget_for = widget_for      # role -> vtk widget   (or None)
        self._redraw = redraw              # () -> None, full all-pairs repaint
        self._active_session: Optional[str] = None
        self._applied: Dict[str, Any] = {}

    # ------------------------------------------------------------------

    @property
    def active_session(self) -> Optional[str]:
        return self._active_session

    @property
    def hidden_roles(self) -> Sequence[str]:
        return tuple(self._applied.get("hidden", ()))

    def apply_for(self, session, roles: Optional[Iterable[str]] = None) -> Sequence[str]:
        """Redraw all lines, then clear them on this session's clean panes.

        Draw-then-clear rather than don't-draw: the drawing engine has no
        per-viewport switch, and the pair of operations is still finished long
        before the settle delay that precedes the grab.
        """
        self._redraw()
        wanted = tuple(roles) if roles is not None else tuple(
            getattr(session, "hide_reference_lines_on", ()) or ()
        )
        hidden = []
        for role in wanted:
            viewer = self._viewer_for(role)
            if _hide_lines_on_viewer(viewer):
                hidden.append(role)
                widget = self._widget_for(role)
                if widget is not None:
                    try:
                        widget.update()
                    except Exception:
                        pass
        self._active_session = getattr(session, "name", None)
        self._applied = {"hidden": tuple(hidden), "requested": wanted}
        return tuple(hidden)

    def restore(self) -> None:
        """Give every pane its reference lines back. Safe to call repeatedly."""
        if self._active_session is None:
            return
        self._active_session = None
        self._applied = {}
        try:
            self._redraw()
        except Exception as exc:
            logger.warning("eagle_eye: reference lines not restored: %s", exc)

    def as_dict(self) -> Dict[str, Any]:
        """What the manifest records about this session's line policy."""
        return {
            "session": self._active_session,
            "hidden_on": list(self._applied.get("hidden", ())),
            "requested": list(self._applied.get("requested", ())),
            "rule": "the viewports being evaluated are captured without reference lines",
        }
