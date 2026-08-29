"""Eagle Eye borrows the workstation's Lock Sync; it never reimplements it.

Lock Sync already does exactly what the lumbar sweep needs: when one viewport
changes slice, every other viewport navigates to the corresponding anatomical
location. It is worth being precise about *how* it gets there, because the
alternative that looks the same on a well-behaved study is wrong on a real one:

    PatientWidget._do_lock_sync()   -> world-space centre of the source slice,
                                       read from IPP/IOP for FAST viewers
                                       rather than from the mock VTK spacing
    PatientWidget._map_sync_cursor() -> "PRIMARY: DICOM IOP/IPP mapping (same as
                                       reference_line.py)", with the ITK
                                       direction matrix and fractional position
                                       only as fallbacks

So the correspondence is physical, not ordinal. Sag T2 with 11 slices at 4 mm
and Sag T1 with 15 at 3 mm land on the same anatomy, which is the whole point:
matching slice INDEX would pair the wrong images and every screenshot after
that would be wrong in a way no downstream reader could detect.

This module owns three things and nothing else:

* turning Lock Sync on for an Eagle Eye run, using the same call sequence the
  toolbar uses, so the workstation and Eagle Eye cannot drift apart;
* putting the reader's own Lock Sync setting back when the run ends;
* suspending propagation for the few controller-driven moves that must NOT
  cascade — via the engine's own re-entrancy flag, not a second mechanism.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _cursor_mode():
    """``SyncMode.CURSOR``, or None if the sync package cannot be imported.

    Imported lazily so this module stays importable in a headless test run that
    has no Qt/VTK stack behind ``modules.zeta_sync``.
    """
    try:
        from modules.zeta_sync import SyncMode
        return SyncMode.CURSOR
    except Exception as exc:  # pragma: no cover - import guard
        logger.debug("eagle_eye_lumbar: SyncMode unavailable (%s)", exc)
        return None


class LockSyncSession:
    """Lock Sync held ON for one Eagle Eye session, then handed back as it was.

    "Session" means the layout being on screen, not the few seconds of
    sweeping. A successful run therefore LEAVES Lock Sync on: the reader's next
    act is to scroll back through the sagittals, and that is precisely when the
    two stacks have to move together. ``restore()`` is for the paths where the
    session did not really happen — a failed run — and for a caller that is
    tearing the layout down.

    Leaving it on changes nothing outside Eagle Eye: the tab builds its own
    ``AIPatientWidget``, so this state is per-widget and dies with the tab. The
    reader's normal patient tab is never touched.

    ``enable()`` and ``restore()`` are both idempotent, because ``restore()``
    has to be safe to call without the caller tracking whether it already ran.
    """

    __slots__ = ("patient_widget", "_previous", "_active", "detail")

    def __init__(self, patient_widget: Any):
        self.patient_widget = patient_widget
        self._previous: Dict[str, bool] = {}
        self._active = False
        self.detail = ""

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        """True while this session is holding Lock Sync on."""
        return self._active

    @property
    def previous(self) -> Dict[str, bool]:
        """The reader's own settings, captured at ``enable()``."""
        return dict(self._previous)

    def as_dict(self) -> Dict[str, Any]:
        """What the manifest records about the sync state of this run."""
        return {
            "enabled": self._active,
            "previous": dict(self._previous),
            "mechanism": "workstation_lock_sync",
            "correspondence": "dicom_ipp_iop",
            "detail": self.detail,
        }

    # ------------------------------------------------------------------
    # enable / restore
    # ------------------------------------------------------------------

    def enable(self) -> bool:
        """Turn Lock Sync on for the Eagle Eye viewports. Returns success.

        The call sequence deliberately mirrors
        ``ToolbarManager._toggle_lock_sync`` line for line: sync pipeline up
        (``_register_sync_viewers_pipeline_only``, which registers the viewers
        WITHOUT installing the click-to-target interactor or the red cursor),
        then ``set_lock_sync(True)`` to wire the slice-changed callbacks. Doing
        it any other way would give Eagle Eye a subtly different Lock Sync from
        the one the reader gets by hand.

        Must be called only once the three viewports really carry their series:
        registration reads each viewer's series UID, and a viewport that is
        still empty registers with none.
        """
        if self._active:
            return True

        pw = self.patient_widget
        self._previous = {
            "lock_sync": bool(getattr(pw, "_lock_sync_enabled", False)),
            "sync_point": bool(getattr(pw, "_sync_enabled", False)),
            "target_mode": bool(getattr(pw, "target_mode_enabled", False)),
        }

        register = getattr(pw, "_register_sync_viewers_pipeline_only", None)
        set_lock_sync = getattr(pw, "set_lock_sync", None)
        if register is None or set_lock_sync is None:
            self.detail = "this viewer has no Lock Sync support"
            logger.warning("eagle_eye_lumbar: %s; the sweep will position every pane itself",
                           self.detail)
            return False

        try:
            pw._sync_enabled = True
            manager = getattr(pw, "sync_manager", None)
            mode = _cursor_mode()
            if manager is not None and mode is not None:
                manager.set_mode(mode)
            register()
            set_lock_sync(True)
        except Exception as exc:
            self.detail = f"could not enable Lock Sync: {exc}"
            logger.warning("eagle_eye_lumbar: %s", self.detail)
            self._rollback_enable()
            return False

        self._active = True
        self.detail = "enabled for the Eagle Eye session"
        logger.info("eagle_eye_lumbar: Lock Sync ON (was %s)",
                    "on" if self._previous["lock_sync"] else "off")
        self._update_toolbar_icon(True)
        return True

    def restore(self) -> None:
        """Put the reader's Lock Sync setting back. Safe to call repeatedly."""
        if not self._active:
            return
        self._active = False

        pw = self.patient_widget
        previous = self._previous
        try:
            set_lock_sync = getattr(pw, "set_lock_sync", None)
            if set_lock_sync is not None:
                set_lock_sync(previous.get("lock_sync", False))

            if not previous.get("lock_sync", False) and not previous.get("sync_point", False):
                # Same teardown the toolbar performs when the reader switches
                # Lock Sync off and has no manual Sync Image running: the
                # pipeline comes down rather than being left half-alive.
                # Order matters — set_lock_sync(False) first, or
                # toggle_sync_point takes its keep-the-pipeline branch.
                toggle = getattr(pw, "toggle_sync_point", None)
                if toggle is not None:
                    toggle(False)
            else:
                pw._sync_enabled = previous.get("sync_point", False)
                pw.target_mode_enabled = previous.get("target_mode", False)
        except Exception as exc:
            logger.warning("eagle_eye_lumbar: could not restore Lock Sync: %s", exc)

        logger.info("eagle_eye_lumbar: Lock Sync restored to %s",
                    "on" if previous.get("lock_sync", False) else "off")
        self._update_toolbar_icon(previous.get("lock_sync", False))

    # ------------------------------------------------------------------
    # suspension
    # ------------------------------------------------------------------

    @contextmanager
    def suspended(self):
        """Move a viewport WITHOUT Lock Sync propagating from it.

        This holds ``PatientWidget._lock_sync_updating`` — the engine's OWN
        re-entrancy guard, the flag it already sets around
        ``_do_lock_sync`` so a target viewer's move cannot bounce back at the
        source. Borrowing it is the difference between reusing Lock Sync and
        growing a second, competing synchroniser.

        Two moves in the sweep need it:

        * parking (and holding) the sagittal panes during the axial pass —
          without suspension the re-park would drag the axial pane straight
          back off the slice the pass is capturing;
        * correcting a follower that Lock Sync could not map — the correction
          must land in that pane only, not push the driver off its own slice.
        """
        pw = self.patient_widget
        if not self._active:
            yield
            return
        held = bool(getattr(pw, "_lock_sync_updating", False))
        try:
            pw._lock_sync_updating = True
            yield
        finally:
            try:
                pw._lock_sync_updating = held
            except Exception:
                pass

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _rollback_enable(self) -> None:
        """Undo a half-applied enable so a failure leaves no residue."""
        pw = self.patient_widget
        try:
            pw._sync_enabled = self._previous.get("sync_point", False)
            pw.target_mode_enabled = self._previous.get("target_mode", False)
        except Exception:
            pass

    def _update_toolbar_icon(self, lock_active: bool) -> None:
        """Keep the toolbar's link/hamburger icon honest about the state."""
        try:
            manager = getattr(self.patient_widget, "toolbar_manager", None)
            update = getattr(manager, "_update_sync_menu_icon", None)
            if update is not None:
                update(bool(lock_active))
        except Exception as exc:
            logger.debug("eagle_eye_lumbar: sync menu icon not updated: %s", exc)


def follower_source(lock_active: bool, landed_where_expected: bool) -> str:
    """How the follower pane got to the slice this frame captured.

    Written into every sagittal frame so a reader of the manifest can tell a
    Lock Sync correspondence from a controller correction without guessing.
    """
    if not lock_active:
        return "controller"
    return "lock_sync" if landed_where_expected else "lock_sync_corrected"
