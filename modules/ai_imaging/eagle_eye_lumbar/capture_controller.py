"""The Eagle Eye capture engine. Protocol in, screenshot sessions out.

This file contains no body-part knowledge. It reads a ``protocols.Protocol``
and does what that protocol says: which SERIES ROLES exist, what order their
viewports sit in, and which capture sessions to sweep. Lumbar MRI is simply the
first protocol configured; Brain MRI is meant to be a new entry in
``protocols.py``, not a new branch in here.

Shape of the run::

    ASSIGN  -> put each role's series into its viewport, in protocol order
    READY   -> wait until every viewport carries ALL of its series
    for each CAPTURE SESSION the protocol declares:
        park the reference panes if the session says so
        for each slice of the PRIMARY series, in geometric order:
            primary moves; SYNCED roles follow (Lock Sync, verified by
            geometry); REFERENCE roles follow or hold
            reference lines redrawn, then CLEARED on the panes this session
            is evaluating - the image being read is captured clean
            the whole layout is captured as one frame
    FINISH  -> manifests written and validated against what is on disk

Every frame is recorded keyed by ROLE, so a manifest reader never has to know
what a protocol's viewport 2 happened to be.

Everything runs on the GUI thread but NEVER in a blocking loop: each step is
one ``QTimer.singleShot`` tick, so the event loop keeps breathing and a 30-frame
sweep does not freeze the workstation. That is also why there is no QThread
here - the VTK viewers can only be driven from the GUI thread, and a worker
thread would buy nothing but the "destroyed while running" class of crash this
codebase has already paid for once.

No LLM call, no upload, no analysis: stage 1 stops when the session is written.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtWidgets import QApplication

from . import evidence_bundle, geometry
from .lock_sync import LockSyncSession, follower_source
from .reference_lines import ReferenceLinePolicy
from .constants import (
    EAGLE_EYE_VERSION,
    ORDER_UNKNOWN,
    PLANE_AXIAL,
    PLANE_SAGITTAL,
    PLANE_UNKNOWN,
    SLOT_LABELS,
    SLOT_REQUIRED_PLANE,
)
from .session_store import PassSpec, create_session, save_pixmap

logger = logging.getLogger(__name__)

# Settle budgets. Deliberately generous rather than tight: a dropped or
# half-rendered frame is unrecoverable once the session is written, and 120 ms
# per frame over ~30 frames is under four seconds total.
_ASSIGN_STEP_MS = 150
_READY_POLL_MS = 250
_READY_TIMEOUT_MS = 90_000
# How many readiness polls between re-issuing an assignment that did not stick.
# Every 4 polls (~1 s) is often enough to recover from the tab's own pipeline
# re-targeting a pane, and rare enough not to thrash the decoder.
_REASSERT_EVERY_TICKS = 4
# How long a pane may sit at the same slice count, short of its on-disk total,
# before the run is refused. Long enough not to trip on a slow download pausing
# between images; far short of the 90 s budget, because the answer is the same
# either way and a reader should not wait a minute and a half to hear it.
_STALL_TIMEOUT_S = 10.0
_STEP_SETTLE_MS = 130
_PASS_GAP_MS = 400

# A T1 slice further than this from its T2 counterpart is still shown (it IS
# the nearest one) but the manifest records the correspondence as weak.
_MAX_MATCH_MM = 12.0


class EagleEyeCaptureController(QObject):
    """One capture run over one study. Single-use: create, ``start()``, done.

    Protocol-driven: see the module docstring. Not lumbar-specific.
    """

    progress = Signal(str, int, int)   # message, done, total
    finished = Signal(object)          # EagleEyeCaptureSession
    failed = Signal(str)

    def __init__(
        self,
        patient_widget: Any,
        selection: Any,
        capture_widget: Any,
        study_context: Optional[Dict[str, Any]] = None,
        session_root: Optional[Any] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.patient_widget = patient_widget
        self.selection = selection
        self.capture_widget = capture_widget
        self.study_context = dict(study_context or {})
        self.session_root = session_root

        self.session = None
        self._running = False
        self._aborted = False
        self._ready_deadline = 0.0
        self._ready_ticks = 0
        # slot -> (slice count last seen, when it last changed). A pane that
        # stops growing short of its on-disk total is refused early rather than
        # waited out; see _wait_until_ready.
        self._decode_progress: Dict[str, Any] = {}

        # The workstation's Lock Sync, held ON for this run and handed back
        # afterwards. Enabled in _prepare_geometry, not here: registration
        # reads each viewport's series UID and the panes are still empty now.
        self.lock_sync = LockSyncSession(patient_widget)

        # The protocol IS the configuration: which roles exist, what order
        # they sit in, and which sweeps to run. Nothing below names a body part.
        self.protocol = getattr(selection, "protocol", None)
        self.roles: List[str] = list(
            getattr(selection, "slot_order", None) or getattr(self.protocol, "slot_keys", ())
        )
        self.sessions = list(getattr(self.protocol, "sessions", ()) or ())

        # Reference-line policy: the panes a sweep is evaluating are captured
        # clean. Which panes those are comes from the session, not from here.
        self.reference_lines = ReferenceLinePolicy(
            viewer_for=self._viewer_for,
            widget_for=self._widget_for,
            redraw=self._redraw_reference_lines,
        )

        # slot -> viewport node, resolved during ASSIGN
        self._nodes: Dict[str, Any] = {}
        # slot -> the series KEY handed to change_series_on_viewer (see _series_key)
        self._series_keys: Dict[str, str] = {}
        # slot -> geometry instance list, resolved once the series are loaded
        self._instances: Dict[str, List[Dict[str, Any]]] = {}
        self._orders: Dict[str, geometry.CaptureOrder] = {}
        self._midline_x: Optional[float] = None
        self._axial_positions: List[float] = []
        self._parked_reference: Dict[str, int] = {}

        self._queue: List[int] = []
        self._queue_pos = 0
        self._session_index = -1
        self._session = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Begin the run. Returns False if it cannot even be attempted."""
        if self._running:
            logger.warning("eagle_eye: capture already running; ignoring re-entry")
            return False

        if not self.roles:
            self._fail("cannot start: the protocol declares no series roles")
            return False
        if not self.sessions:
            self._fail(f"cannot start: {self._protocol_name()} declares no capture sessions")
            return False

        missing = [role for role in self.roles if self.selection.candidate_for(role) is None]
        if missing:
            self._fail(f"cannot start: no series resolved for {', '.join(missing)}")
            return False

        nodes = list(getattr(self.patient_widget, "lst_nodes_viewer", []) or [])
        if len(nodes) < len(self.roles):
            self._fail(
                f"cannot start: the Eagle Eye layout has {len(nodes)} viewport(s), "
                f"needs {len(self.roles)}"
            )
            return False

        try:
            self.session = create_session(
                str(self.study_context.get("study_instance_uid") or getattr(self.patient_widget, "study_uid", "")),
                root=self.session_root,
                passes=[PassSpec.from_capture_session(s) for s in self.sessions],
                protocol_id=getattr(self.protocol, "id", "") or "",
            )
        except Exception as exc:
            self._fail(f"cannot create the session folder: {exc}")
            return False

        self.session.set_study_context(**self.study_context)
        self.session.set_selection(self.selection.as_dict())
        layout = tuple(getattr(self.protocol, "layout", (1, len(self.roles))) or (1, len(self.roles)))
        self.session.set_layout(layout[0], layout[1], self.roles)
        for slot in self.selection.uncertain_slots:
            self.session.add_note(
                f"{slot}: selection is uncertain "
                f"(confidence={self.selection[slot].confidence}) - review before relying on it"
            )

        self._running = True
        self._nodes = {role: nodes[i] for i, role in enumerate(self.roles)}
        self._emit(f"Loading {len(self.roles)} series", 0, 0)
        QTimer.singleShot(0, self._assign_series)
        return True

    def abort(self, reason: str = "cancelled") -> None:
        """Stop after the current tick; whatever was captured is still written."""
        if self._running:
            self._aborted = True
            logger.info("eagle_eye: capture aborted (%s)", reason)

    # ------------------------------------------------------------------
    # phase 1: assign series to viewports
    # ------------------------------------------------------------------

    def _series_key(self, candidate) -> str:
        """The key ``change_series_on_viewer`` expects for this series.

        NOT a list index. Despite its ``series_index`` parameter name, that
        method's first statement is ``series_number = str(series_index)`` and
        everything downstream treats it as a series KEY (it resolves canonical
        identity, previous-exam origin and download state from it). Passing a
        position in ``lst_thumbnails_data`` loaded series "1" and "2" — the
        localizer and the coronal myelogram — into the lumbar panes, and the
        readiness check then waited forever for series it had never asked for.
        """
        number = str(candidate.series_number or "").strip()
        uid = str(getattr(candidate, "series_uid", "") or "").strip()
        resolve = getattr(self.patient_widget, "resolve_series_key", None)
        # resolve_series_key maps a SeriesInstanceUID to the series NUMBER the
        # viewer keys on, and returns its argument unchanged when it does not
        # know it. The UID is the identity the resolver validated, so it is
        # tried first; the header's series number is the fallback.
        if resolve is not None and uid:
            try:
                resolved = str(resolve(uid) or "").strip()
                if resolved and resolved != uid:
                    return resolved
            except Exception:
                pass
        return number or uid

    def _assign_series(self) -> None:
        if not self._alive():
            return
        try:
            for slot in self.roles:
                candidate = self.selection.candidate_for(slot)
                node = self._nodes[slot]
                key = self._series_key(candidate)
                self._series_keys[slot] = key
                logger.info("eagle_eye: %s <- series key %s", slot, key)
                # flag_change_selected_widget MUST stay False: when it is True the
                # method overwrites the vtk_widget argument with
                # ``self.selected_widget``, so all three assignments would land in
                # the same pane and the other two would stay empty.
                self.patient_widget.change_series_on_viewer(
                    key,
                    flag_change_selected_widget=False,
                    vtk_widget=getattr(node, "vtk_widget", None),
                    slider=getattr(node, "slider", None),
                    allow_paired=False,
                )
                QApplication.processEvents()
        except Exception as exc:
            self._fail(f"could not load the selected series into the layout: {exc}")
            return

        self._ready_deadline = time.monotonic() + (_READY_TIMEOUT_MS / 1000.0)
        QTimer.singleShot(_ASSIGN_STEP_MS, self._wait_until_ready)

    def _viewer_for(self, slot: str):
        return getattr(self._widget_for(slot), "image_viewer", None)

    def _widget_for(self, slot: str):
        node = self._nodes.get(slot)
        return getattr(node, "vtk_widget", None) if node is not None else None

    def _viewport_bounds(self) -> Dict[str, Dict[str, float]]:
        """Measured image-pane rectangles relative to the captured widget.

        These are recorded rather than inferred later because the captured
        container includes variable sidebar and viewer chrome. Normalized
        coordinates remain valid across display scaling and PNG pixel density.
        """
        container = self.capture_widget
        if container is None:
            return {}
        try:
            container_width = int(container.width())
            container_height = int(container.height())
        except Exception:
            return {}
        if container_width <= 0 or container_height <= 0:
            return {}

        regions: Dict[str, Dict[str, float]] = {}
        for role in self.roles:
            widget = self._widget_for(role)
            if widget is None:
                continue
            try:
                origin = widget.mapTo(container, QPoint(0, 0))
                region = evidence_bundle.normalized_bounds(
                    origin.x(), origin.y(), widget.width(), widget.height(),
                    container_width, container_height,
                )
            except Exception as exc:
                logger.warning("eagle_eye: could not measure %s viewport: %s", role, exc)
                continue
            if region:
                regions[role] = region
        return regions

    def _protocol_name(self) -> str:
        return str(getattr(self.protocol, "name", "") or "this protocol")

    def _viewer_series_number(self, slot: str) -> str:
        viewer = self._viewer_for(slot)
        try:
            return str((getattr(viewer, "metadata", {}) or {}).get("series", {}).get("series_number", "")).strip()
        except Exception:
            return ""

    def _expected_slices(self, slot: str) -> int:
        """How many images this series has ON DISK.

        Counted by the probe (`len(_dicom_files(folder))`, deduped for the
        Windows case-insensitive-glob trap) at resolution time, so it is the
        number the viewport has to reach before the series is whole.

        Returns 0 when unknown, and for a multi-frame series it under-reports
        (one file, many frames) — both degrade to "any slice will do", which is
        the old behaviour, never something stricter than the truth.
        """
        candidate = self.selection.candidate_for(slot)
        try:
            return int(getattr(candidate, "slice_count", 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _decoded_slices(self, slot: str) -> int:
        viewer = self._viewer_for(slot)
        if viewer is None:
            return 0
        try:
            return int(viewer.get_count_of_slices())
        except Exception:
            return 0

    def _slot_ready(self, slot: str) -> bool:
        """Right series AND all of it.

        `> 0` was the original test and it is what produced the 2026-08-26
        "1 sagittal + 8 axial frames" session: the tab decodes progressively, so
        a pane that has one slice of nine passes a non-empty check, and the
        capture order built from that snapshot had exactly one entry. The sweep
        then ran to completion, reported success, and wrote a session covering a
        ninth of the study. A partial series must read as NOT READY.
        """
        viewer = self._viewer_for(slot)
        if viewer is None:
            return False
        showing = self._viewer_series_number(slot)
        candidate = self.selection.candidate_for(slot)
        wanted = {self._series_keys.get(slot, ""), str(candidate.series_number or "").strip()}
        if showing not in wanted:
            return False

        decoded = self._decoded_slices(slot)
        if decoded <= 0:
            return False
        expected = self._expected_slices(slot)
        return decoded >= expected if expected > 1 else True

    def _wait_until_ready(self) -> None:
        if not self._alive():
            return
        pending = [slot for slot in self.roles if not self._slot_ready(slot)]
        if not pending:
            QTimer.singleShot(_ASSIGN_STEP_MS, self._prepare_geometry)
            return

        if time.monotonic() >= self._ready_deadline:
            detail = ", ".join(self._pending_detail(slot) for slot in pending)
            self._fail(f"timed out loading {detail}")
            return

        # A pane that has stopped growing short of its on-disk total is not
        # going to finish: the file count and the decodable slice count simply
        # disagree for this series. The verdict is the same as the timeout's, so
        # deliver it in ten seconds rather than ninety.
        stalled = [slot for slot in pending if self._decode_stalled(slot)]
        if stalled:
            detail = ", ".join(self._pending_detail(slot) for slot in stalled)
            self._fail(f"loading stopped short for {detail}")
            return

        # Re-issue the request periodically, but ONLY at a pane showing the
        # WRONG series: a viewport can be re-targeted behind this controller's
        # back while the tab's own pipeline is still settling, and without this
        # the sweep would wait out the whole budget on a pane the pipeline had
        # quietly pointed elsewhere. A pane on the RIGHT series that is merely
        # still decoding must be left alone — re-issuing there restarts the very
        # load it is waiting on, which would hold a slow study at slice one.
        self._ready_ticks += 1
        if self._ready_ticks % _REASSERT_EVERY_TICKS == 0:
            for slot in pending:
                showing = self._viewer_series_number(slot)
                if showing and showing != self._series_keys.get(slot, ""):
                    self._reassert_slot(slot)

        self._emit(
            "Loading " + ", ".join(self._pending_detail(slot) for slot in pending), 0, 0,
        )
        QTimer.singleShot(_READY_POLL_MS, self._wait_until_ready)

    def _decode_stalled(self, slot: str) -> bool:
        """True once this pane's slice count has sat still past the budget.

        Only meaningful for a pane that is on the right series and has started
        decoding — a pane at zero is waiting to begin, not stalled, and a pane
        showing the wrong series is the re-assert path's problem.
        """
        if self._viewer_series_number(slot) != self._series_keys.get(slot, ""):
            return False
        decoded = self._decoded_slices(slot)
        if decoded <= 0:
            return False
        now = time.monotonic()
        seen, since = self._decode_progress.get(slot, (-1, now))
        if decoded != seen:
            self._decode_progress[slot] = (decoded, now)
            return False
        return (now - since) >= _STALL_TIMEOUT_S

    def _pending_detail(self, slot: str) -> str:
        """Why this slot is not ready, in words a reader can act on."""
        showing = self._viewer_series_number(slot)
        wanted = self._series_keys.get(slot, "?")
        if showing != wanted:
            return (f"{self._label(slot)} (wanted series {wanted}, "
                    f"pane shows {showing or 'nothing'})")
        expected = self._expected_slices(slot)
        decoded = self._decoded_slices(slot)
        if expected > 1:
            return f"{self._label(slot)} ({decoded} of {expected} images decoded)"
        return f"{self._label(slot)} ({decoded} image(s) decoded)"

    @staticmethod
    def _label(slot: str) -> str:
        from .constants import SLOT_LABELS
        return SLOT_LABELS.get(slot, slot)

    def _reassert_slot(self, slot: str) -> None:
        """Ask again for a pane that is showing something other than its series."""
        node = self._nodes.get(slot)
        key = self._series_keys.get(slot)
        if node is None or not key:
            return
        logger.info("eagle_eye: re-asserting %s <- series %s (pane shows %s)",
                    slot, key, self._viewer_series_number(slot) or "nothing")
        try:
            self.patient_widget.change_series_on_viewer(
                key,
                flag_change_selected_widget=False,
                vtk_widget=getattr(node, "vtk_widget", None),
                slider=getattr(node, "slider", None),
                allow_paired=False,
            )
        except Exception as exc:
            logger.warning("eagle_eye: re-assert of %s failed: %s", slot, exc)

    # ------------------------------------------------------------------
    # phase 2: resolve geometry and capture orders
    # ------------------------------------------------------------------

    def _geometry_instances(self, slot: str) -> List[Dict[str, Any]]:
        """Instance list for a viewport, via the shared geometry authority.

        ``_geometry_instances_for_viewer`` is what the sync and reference-line
        engines use; going through it keeps this pipeline in the same instance
        ORDER domain as the lines it is capturing. Reading the viewer's
        ``metadata['instances']`` directly would silently diverge.
        """
        viewer = self._viewer_for(slot)
        if viewer is None:
            return []
        try:
            current = int(viewer.GetSlice())
        except Exception:
            current = 0
        try:
            instances = self.patient_widget._geometry_instances_for_viewer(
                viewer,
                caller="eagle_eye.EagleEyeCaptureController",
                current_slice_index=current,
            )
            return list(instances or [])
        except Exception as exc:
            logger.warning("eagle_eye: geometry instances unavailable for %s: %s", slot, exc)
            try:
                return list((getattr(viewer, "metadata", {}) or {}).get("instances", []) or [])
            except Exception:
                return []

    def _prepare_geometry(self) -> None:
        if not self._alive():
            return

        self._enable_lock_sync()

        for slot in self.roles:
            self._instances[slot] = self._geometry_instances(slot)

        for session in self.sessions:
            if not self._instances.get(session.primary):
                self._fail(f"the {self._label(session.primary)} viewport reports no instances")
                return

        # Second line of defence behind _slot_ready. The capture order IS the
        # sweep: an order built from a half-decoded stack produces a session
        # that is short by exactly the slices that were missing, and — because
        # every frame in it is individually valid — nothing downstream can tell.
        # The 2026-08-26 run wrote "1 sagittal + 8 axial" this way and reported
        # success. Refuse instead, and say what was counted.
        for slot in self.roles:
            expected = self._expected_slices(slot)
            have = len(self._instances.get(slot) or [])
            if expected > 1 and have < expected:
                self._fail(
                    f"{self._label(slot)} reports {have} of {expected} images "
                    f"after loading finished; refusing to capture a partial series"
                )
                return

        # One capture order per sweep, built from the primary series' own plane.
        for session in self.sessions:
            instances = self._instances[session.primary]
            order = geometry.build_capture_order(instances, session.plane)
            self._orders[session.name] = order
            payload = order.as_dict()
            payload["session"] = session.name
            payload["driving_slot"] = session.primary
            payload["driving_series_uid"] = self.selection.candidate_for(session.primary).series_uid
            payload["synced_slots"] = list(session.synced)
            payload["reference_slots"] = list(session.reference)
            payload["reference_lines_hidden_on"] = list(session.hide_reference_lines_on)
            self.session.set_pass_geometry(session.name, payload)
            if order.direction == ORDER_UNKNOWN:
                self.session.add_note(
                    f"{session.name}: could not resolve an anatomical direction from "
                    f"ImagePositionPatient; captured in stack order instead"
                )

        # Mid-line and the axial level table are the spatial-context inputs.
        # Both need a sagittal and an axial stack; a protocol without either
        # simply gets no context labels rather than a failure.
        self._midline_x = self._estimate_midline()
        self._axial_positions = self._axial_level_positions()

        self._begin_session(0)

    # ------------------------------------------------------------------
    # lock sync
    # ------------------------------------------------------------------

    def _enable_lock_sync(self) -> None:
        """Hold the workstation's Lock Sync ON for this run.

        A failure here is not fatal: the sweep already positions every pane
        from DICOM geometry, so Lock Sync makes the panes move *together the
        way the reader's own workstation moves them* rather than being the only
        thing that moves them. What the session must never do is claim a
        correspondence it did not get, so the outcome is written down either
        way and every frame records how its follower pane got there.
        """
        ok = self.lock_sync.enable()
        if self.session is None:
            return
        if ok:
            self.session.add_note(
                "Lock Sync enabled for this session (previous state: "
                + ("on" if self.lock_sync.previous.get("lock_sync") else "off")
                + "); sagittal T1 follows T2 by DICOM IPP/IOP correspondence"
            )
        else:
            self.session.add_note(
                f"Lock Sync unavailable ({self.lock_sync.detail}); "
                f"the sweep positioned every pane itself"
            )

    def _restore_lock_sync(self) -> None:
        """Give the reader their own Lock Sync setting back. Idempotent."""
        try:
            self.lock_sync.restore()
        except Exception as exc:
            logger.warning("eagle_eye: Lock Sync restore failed: %s", exc)

    def _restore_reference_lines(self) -> None:
        """Put every pane's reference lines back. Idempotent.

        Unlike Lock Sync this runs on the SUCCESS path too. Leaving two panes
        with their lines cleared would be a visible change to the reader's
        viewer that they never asked for — and unlike Lock Sync, keeping it is
        no use to them: the suppression exists for the screenshots, not for
        reading.
        """
        try:
            self.reference_lines.restore()
        except Exception as exc:
            logger.warning("eagle_eye: reference lines not restored: %s", exc)

    def _current_slice(self, slot: str) -> int:
        viewer = self._viewer_for(slot)
        if viewer is None:
            return -1
        try:
            return int(viewer.GetSlice())
        except Exception:
            return -1

    def _set_slice_quietly(self, slot: str, index: int) -> int:
        """Move one pane without Lock Sync propagating out of it."""
        with self.lock_sync.suspended():
            return self._set_slice(slot, index)

    def _settle_follower(self, slot: str, wanted: int):
        """Where a follower pane actually is, corrected only if it drifted.

        Lock Sync is the mechanism, but it is not infallible: ``_map_sync_cursor``
        returns None when the source point falls outside the target stack, and
        ``_do_lock_sync`` then hides the sync overlay and leaves that pane where
        it was. Trusting it blindly would pair a T2 slice with a stale T1 one —
        a defect invisible in the screenshot and fatal to everything downstream.
        So the geometric answer is still computed and remains the verdict:
        agreement is recorded as such, disagreement is corrected in place.
        """
        landed = self._current_slice(slot)
        if landed == wanted:
            return wanted, follower_source(self.lock_sync.active, True)
        applied = self._set_slice_quietly(slot, wanted)
        if self.lock_sync.active:
            logger.debug(
                "eagle_eye: %s corrected %s -> %s (Lock Sync did not map)",
                slot, landed, applied,
            )
        return applied, follower_source(self.lock_sync.active, False)

    # ------------------------------------------------------------------
    # sweeps
    # ------------------------------------------------------------------

    def _begin_session(self, index: int) -> None:
        """Start capture session ``index``; everything about it is protocol data."""
        self._session_index = index
        session = self._session = self.sessions[index]
        self._queue = list(self._orders[session.name].indices)
        self._queue_pos = 0

        if session.park_reference:
            # The primary is now the moving plane, so the reference panes hold
            # one slice for the whole sweep: the only thing changing in them is
            # the reference line, which is exactly the level information each
            # frame needs.
            self._park_reference_panes(session)

        self._emit(f"Capturing the {session.label}", 0, len(self._queue))
        QTimer.singleShot(_PASS_GAP_MS, self._sweep_step)

    def _park_reference_panes(self, session) -> None:
        for slot in session.reference:
            instances = self._instances.get(slot) or []
            if not instances:
                continue
            values = geometry.axis_values(instances, 0)
            index = 0
            if values and self._midline_x is not None:
                index = min(range(len(values)), key=lambda k: abs(values[k] - self._midline_x))
            elif values:
                index = len(values) // 2
            # Quietly: with Lock Sync live, parking T2 would push the axial pane
            # off the very slice the axial pass is about to capture.
            self._set_slice_quietly(slot, index)
            self._parked_reference[slot] = index
        if self._parked_reference:
            self.session.add_note(
                f"{session.name} sweep: reference panes parked at their mid-line slice "
                + ", ".join(f"{slot}=#{idx + 1}" for slot, idx in self._parked_reference.items())
            )

    def _set_slice(self, slot: str, index: int) -> int:
        """Move one viewport to ``index``; returns the index actually applied."""
        node = self._nodes.get(slot)
        widget = getattr(node, "vtk_widget", None) if node is not None else None
        viewer = getattr(widget, "image_viewer", None)
        if widget is None or viewer is None:
            return -1
        try:
            total = int(viewer.get_count_of_slices())
        except Exception:
            total = 0
        if total <= 0:
            return -1
        index = max(0, min(int(index), total - 1))
        try:
            widget.set_slice(index)
        except Exception as exc:
            logger.warning("eagle_eye: set_slice(%s, %s) failed: %s", slot, index, exc)
            return -1
        return index

    def _sweep_step(self) -> None:
        if not self._alive():
            return

        if self._aborted or self._queue_pos >= len(self._queue):
            nxt = self._session_index + 1
            if nxt < len(self.sessions) and not self._aborted:
                QTimer.singleShot(_PASS_GAP_MS, lambda: self._begin_session(nxt))
            else:
                QTimer.singleShot(0, self._finish)
            return

        session = self._session
        driver_index = self._queue[self._queue_pos]
        try:
            frame = self._position_frame(session, driver_index)
        except Exception as exc:
            logger.error("eagle_eye: positioning failed at %s #%s: %s",
                         session.name, driver_index, exc, exc_info=True)
            self._fail(f"failed while positioning the {session.name} sweep: {exc}")
            return

        self._refresh_reference_lines()
        QTimer.singleShot(_STEP_SETTLE_MS, lambda: self._capture_step(frame))

    def _refresh_reference_lines(self) -> None:
        """Redraw the cross-reference lines NOW rather than on the 50 ms throttle.

        The throttle exists to keep interactive scrolling smooth; here the very
        next thing that happens is a screenshot, so the lines must already be
        correct when the pixels are read.

        Lock Sync ends every propagation with ``_schedule_reference_line_update``,
        which arms that 50 ms throttle. Left running, its next tick would land
        inside our settle window and repaint ONE target round-robin — leaving a
        pane half-updated at the moment of the grab. So the pending tick is
        stood down first and the full repaint done here instead.
        """
        if self._session is None:
            self._redraw_reference_lines()
            return
        self.reference_lines.apply_for(self._session)

    def _redraw_reference_lines(self) -> None:
        """One full all-pairs repaint, with the throttle stood down first."""
        try:
            timer = getattr(self.patient_widget, "_rl_throttle_timer", None)
            if timer is not None and timer.isActive():
                timer.stop()
                self.patient_widget._rl_pending = False
        except Exception as exc:
            logger.debug("eagle_eye: reference line throttle not stood down: %s", exc)
        try:
            self.patient_widget.manage_reference_line(repaint=True)
        except Exception as exc:
            logger.debug("eagle_eye: reference line refresh failed: %s", exc)

    # ------------------------------------------------------------------
    # frame positioning
    # ------------------------------------------------------------------

    def _instance_at(self, slot: str, index: int) -> Dict[str, Any]:
        instances = self._instances.get(slot) or []
        if 0 <= index < len(instances):
            return instances[index] or {}
        return {}

    @staticmethod
    def _sop(instance: Dict[str, Any]) -> str:
        return str((instance or {}).get("sop_uid") or (instance or {}).get("sop_instance_uid") or "")

    @staticmethod
    def _ipp(instance: Dict[str, Any]):
        ipp = (instance or {}).get("image_position_patient")
        if ipp is None:
            return None
        try:
            return [round(float(v), 3) for v in ipp]
        except (TypeError, ValueError):
            return None

    def _pane_record(self, slot: str, index: int, role: str) -> Dict[str, Any]:
        """One viewport's identity in a frame, keyed by its SERIES ROLE.

        Everything a later stage needs to go from a pixel back to the source
        image: which series, which SOP instance, which slice, and where that
        slice sits in patient coordinates.
        """
        instance = self._instance_at(slot, index)
        candidate = self.selection.candidate_for(slot)
        return {
            "role": role,
            "label": self._label(slot),
            "series_uid": candidate.series_uid if candidate else None,
            "series_description": candidate.series_description if candidate else None,
            "instance": self._sop(instance),
            "slice_index": index,
            "position": self._ipp(instance),
        }

    def _position_frame(self, session, driver_index: int) -> Dict[str, Any]:
        """Position every pane for one frame of ``session`` and describe it.

        One builder for every protocol. What differs between a lumbar sagittal
        sweep and a brain axial one is entirely in the session's roles:

        - the PRIMARY moves to ``driver_index``. When it also has synced roles
          and Lock Sync is live, this single move is what carries them: the
          slice-changed callback fires, ``_do_lock_sync`` reads the true
          patient-LPS centre from IPP/IOP, and every other registered viewport
          navigates to the corresponding anatomy. Moved loudly for that reason.
        - SYNCED roles are then verified against the geometric match and
          corrected only if Lock Sync did not land them (``_settle_follower``).
        - REFERENCE roles either hold their parked slice or follow the primary,
          depending on ``park_reference``.

        When the sweep must NOT propagate — a parked-reference session — the
        primary moves quietly, or the parked panes would walk off frame by frame
        and the reference line would be drawn on different anatomy every time.
        """
        parked = bool(session.park_reference)
        if parked:
            applied_primary = self._set_slice_quietly(session.primary, driver_index)
        else:
            applied_primary = self._set_slice(session.primary, driver_index)
            if self.lock_sync.active and session.synced:
                # Let the propagation land before reading where the followers went.
                QApplication.processEvents()

        panes: Dict[str, Any] = {
            session.primary: self._pane_record(session.primary, applied_primary, "primary"),
        }
        primary_instances = self._instances.get(session.primary) or []

        for slot in session.synced:
            match = geometry.match_slice_across_series(
                primary_instances, applied_primary,
                self._instances.get(slot) or [], _MAX_MATCH_MM,
            )
            applied, source = self._settle_follower(slot, match.index)
            record = self._pane_record(slot, applied, "synced")
            record["match"] = match.as_dict()
            record["followed_by"] = source
            panes[slot] = record

        for slot in session.reference:
            if parked:
                index = self._parked_reference.get(slot, 0)
                record = self._pane_record(slot, index, "reference")
                record["parked"] = True
            else:
                # An unbounded match: the reference pane should show the level
                # that best intersects the primary slice, however far that is,
                # so the frame carries a real cross-reference rather than
                # whatever level happened to be showing.
                match = geometry.match_slice_across_series(
                    primary_instances, applied_primary,
                    self._instances.get(slot) or [], float("inf"),
                )
                applied, source = self._settle_follower(slot, match.index)
                record = self._pane_record(slot, applied, "reference")
                record["match"] = match.as_dict()
                record["followed_by"] = source
                record["parked"] = False
            panes[slot] = record

        frame: Dict[str, Any] = {
            "session": session.name,
            "driving_pane": session.primary,
            "reference_lines_hidden_on": list(session.hide_reference_lines_on),
            "panes": panes,
        }
        frame.update(self._spatial_context(session, panes))
        return frame

    def _spatial_context(self, session, panes: Dict[str, Any]) -> Dict[str, Any]:
        """Anatomical labels for this frame, where the geometry supports them.

        Sagittal offset needs a mid-line; axial level needs the axial position
        table. A protocol that provides neither simply gets no labels — an
        absent label is honest, an invented one is not.
        """
        context: Dict[str, Any] = {}

        primary_pos = (panes.get(session.primary) or {}).get("position")
        if session.plane == PLANE_SAGITTAL and self._midline_x is not None:
            x_lps = self._axis(primary_pos, 0)
            if x_lps is not None:
                context["spatial_context"] = geometry.sagittal_context(x_lps, self._midline_x)

        # The axial level comes from whichever pane in this frame is axial: the
        # primary in an axial sweep, the reference pane in a sagittal one.
        if self._axial_positions:
            for slot, record in panes.items():
                if self._plane_of(slot) != PLANE_AXIAL:
                    continue
                z_lps = self._axis(record.get("position"), 2)
                if z_lps is not None:
                    context["axial_context"] = geometry.axial_context(z_lps, self._axial_positions)
                break
        return context

    def _plane_of(self, slot: str) -> str:
        """The acquisition plane of a role, from the protocol's slot definition."""
        try:
            spec = self.protocol.slot(slot)
            if spec is not None and spec.plane:
                return spec.plane
        except Exception:
            pass
        return SLOT_REQUIRED_PLANE.get(slot, PLANE_UNKNOWN)

    @staticmethod
    def _axis(position, axis: int):
        if not position:
            return None
        try:
            return float(position[axis])
        except (TypeError, ValueError, IndexError):
            return None

    def _estimate_midline(self):
        """Patient mid-line X, from the first axial + first sagittal roles."""
        axial = next((self._instances.get(r) for r in self.roles
                      if self._plane_of(r) == PLANE_AXIAL and self._instances.get(r)), None)
        sagittal = next((self._instances.get(r) for r in self.roles
                         if self._plane_of(r) == PLANE_SAGITTAL and self._instances.get(r)), None)
        if not axial or not sagittal:
            return None
        try:
            return geometry.estimate_midline_x(axial, sagittal)
        except Exception:
            return None

    def _axial_level_positions(self) -> List[float]:
        axial = next((self._instances.get(r) for r in self.roles
                      if self._plane_of(r) == PLANE_AXIAL and self._instances.get(r)), None)
        if not axial:
            return []
        try:
            return geometry.axis_values(axial, 2) or []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # capture
    # ------------------------------------------------------------------

    def _capture_step(self, frame: Dict[str, Any]) -> None:
        if not self._alive():
            return

        target = self.session.next_capture_path(self._session.name)
        viewport_bounds = self._viewport_bounds()
        try:
            from modules.viewer.viewport_capture import grab_widget_pixmap
            widget = self.capture_widget
            if widget is not None:
                widget.repaint()
            QApplication.processEvents()
            pixmap = grab_widget_pixmap(widget)
        except Exception as exc:
            self._fail(f"screen capture failed: {exc}")
            return

        if not save_pixmap(pixmap, target):
            self._fail(f"could not write {target.name}")
            return

        frame = dict(frame)
        frame["captured_at"] = _now_iso()
        if viewport_bounds:
            frame["viewport_bounds"] = viewport_bounds
        try:
            frame["source_image"] = {
                "pixel_width": int(pixmap.width()),
                "pixel_height": int(pixmap.height()),
                "device_pixel_ratio": float(pixmap.devicePixelRatio()),
            }
        except Exception:
            pass
        self.session.add_capture(self._session.name, frame)

        self._queue_pos += 1
        self._emit(f"Capturing the {self._session.label}", self._queue_pos, len(self._queue))
        QTimer.singleShot(0, self._sweep_step)

    # ------------------------------------------------------------------
    # finish
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        if self.session is None:
            self._restore_lock_sync()
            self._fail("no session to write")
            return
        try:
            if self._aborted:
                self.session.add_note("run was aborted before every slice was captured")
            self.session.set_study_context(lock_sync=self.lock_sync.as_dict())
            # Lock Sync deliberately stays ON here. The Eagle Eye SESSION is the
            # layout being on screen, not the four seconds of sweeping: the
            # reader's next act is to scroll back through the sagittals, and
            # that is exactly when the two stacks have to move together. Ending
            # it with the sweep is what made the panes land at 5/9 and 9/9 with
            # nothing following. It costs the workstation nothing — this is the
            # Eagle Eye tab's OWN AIPatientWidget, so the state dies with the
            # tab and never reaches the reader's normal patient tab. Only a
            # FAILED run restores (see _fail), because a run that died should
            # not leave behind a setting nobody asked for.
            if self.lock_sync.active:
                self.session.add_note(
                    "Lock Sync left ON for review: scrolling either synced pane "
                    "moves the other to the corresponding anatomy"
                )
            # The reference lines, however, DO come back: they were cleared for
            # the screenshots, and the reader still wants them on screen.
            self._restore_reference_lines()
            self.session.write()
            problems = self.session.validate()
        except Exception as exc:
            self._fail(f"could not write the session: {exc}")
            return

        self._running = False
        if problems:
            for problem in problems:
                logger.error("eagle_eye: session validation - %s", problem)
                self.session.add_note(f"validation: {problem}")
            try:
                self.session.write()
            except Exception:
                pass

        logger.info(
            "eagle_eye: session %s written - %s - %d problem(s)",
            self.session.session_id,
            ", ".join(
                f"{name} {self.session.capture_count(name)}"
                for name in self.session.pass_names
            ),
            len(problems),
        )
        self.finished.emit(self.session)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _alive(self) -> bool:
        """False once the widget tree is gone - a tab closed mid-sweep must not
        keep firing timers into deleted C++ objects."""
        if not self._running:
            return False
        try:
            import shiboken6
            if not shiboken6.isValid(self.patient_widget):
                self._running = False
                return False
        except Exception:
            pass
        return True

    def _emit(self, message: str, done: int, total: int) -> None:
        try:
            self.progress.emit(message, int(done), int(total))
        except Exception:
            pass

    def _fail(self, reason: str) -> None:
        self._running = False
        logger.error("eagle_eye: %s", reason)
        # A run that dies must not leave the reader's viewer in a state they
        # did not choose. Restore first: everything below can itself throw.
        self._restore_lock_sync()
        self._restore_reference_lines()
        if self.session is not None:
            try:
                self.session.add_note(f"failed: {reason}")
                self.session.write()
            except Exception:
                pass
        try:
            self.failed.emit(reason)
        except Exception:
            pass


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _first_region(protocol: Any) -> Optional[str]:
    regions = tuple(getattr(protocol, "regions", ()) or ())
    return regions[0] if regions else None


def build_study_context(
    patient_widget: Any,
    selection: Any,
    handoff_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Session-level metadata for session.json (spec 13)."""
    fixed = getattr(patient_widget, "metadata_fixed", {}) or {}
    protocol = getattr(selection, "protocol", None)
    context: Dict[str, Any] = {
        "eagle_eye_version": EAGLE_EYE_VERSION,
        "study_instance_uid": str(getattr(patient_widget, "study_uid", "") or ""),
        "patient_id": str(getattr(patient_widget, "patient_id", "") or fixed.get("patient_id", "") or ""),
        "patient_name": str(fixed.get("patient_name", "") or ""),
        "study_date": str(fixed.get("study_date", "") or ""),
        "study_description": str(fixed.get("study_description", "") or ""),
        "protocol_id": getattr(protocol, "id", "") or "",
        "protocol_name": getattr(protocol, "name", "") or "",
        "region": _first_region(protocol),
        "modality": getattr(protocol, "modality", "") or "",
    }
    from .series_context import sanitize_series_inventory, snapshot_series_catalog

    inventory_scope, inventory = snapshot_series_catalog(patient_widget, selection)
    context["study_series_inventory_scope"] = inventory_scope
    context["study_series_inventory"] = inventory

    handoff = handoff_context if isinstance(handoff_context, dict) else {}
    handoff_patient_id = str(handoff.get("patient_id") or "").strip()
    if not context["patient_id"] and handoff_patient_id:
        context["patient_id"] = handoff_patient_id

    handoff_scope = str(
        handoff.get("study_series_inventory_scope") or ""
    ).strip()
    handoff_inventory = sanitize_series_inventory(
        handoff.get("study_series_inventory")
    )
    if (
        handoff_scope == "pacs_series_catalog"
        and handoff_inventory
        and (
            inventory_scope != "pacs_series_catalog"
            or len(handoff_inventory) >= len(inventory)
        )
    ):
        context["study_series_inventory_scope"] = handoff_scope
        context["study_series_inventory"] = handoff_inventory

    for slot in (getattr(selection, "slot_order", None) or getattr(protocol, "slot_keys", ())):
        candidate = selection.candidate_for(slot)
        context[f"{slot}_series_uid"] = candidate.series_uid if candidate else None
        context[f"{slot}_series_number"] = candidate.series_number if candidate else None
        context[f"{slot}_series_description"] = candidate.series_description if candidate else None
    return context


# Historical name, kept so existing callers and guards keep working.
LumbarCaptureController = EagleEyeCaptureController
