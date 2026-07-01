"""Case-of-Day media capture — Screenshot + Record Viewport.

Deliberately independent of DICOM loading, viewport rendering, the annotation
system, and viewer interaction: this module only *observes* whatever a
viewport widget currently paints (via the same OpenGL-safe grab already used
by the app's "Screenshot" toolbar action) and either saves one frame as a
JPEG or feeds a stream of frames to a background thread that encodes them
into an MP4. Nothing here loads DICOM, changes rendering, or drives the
viewer — it is a pure capture/encode layer on top.

Privacy: patient-identifying corner overlay text (name/ID/age/sex) is
temporarily suppressed on the ONE viewport being captured via the FAST
viewer's existing (pre-existing, previously unused) `set_show_annotations()`
toggle, and restored immediately afterwards. This never touches DICOM data
and never permanently disables the overlay — see ``OverlayGuard`` below.
Tool annotations/measurements are a separate paint layer and are NOT
affected, per the feature spec ("preserve... non-identifying annotations").

Recording performance: frames are grabbed on the GUI thread (a QTimer tick —
cheap, since the FAST viewer paints via QPainter, not OpenGL) but the actual
MP4 encode happens on a background thread via a bounded queue, so a slow
disk/encoder cannot block the UI. When the queue is full (encoder falling
behind), new frames are dropped rather than blocking — recording keeps the
viewport responsive at the cost of a slightly choppier video, never a frozen
UI.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() not in ("0", "false", "no", "off", "")


# Flag-gated per repo convention — default ON, kill switch available without
# touching code. See docs/reports/CASE_OF_DAY_MEDIA_CAPTURE_2026-07-01.md.
PRIVACY_HIDE_OVERLAY = _env_flag("AIPACS_CASE_OF_DAY_PRIVACY_OVERLAY", True)

# Candidate MP4 fourccs tried in order — H.264 (small, good quality) first,
# falling back to the always-available MPEG-4 codec if this OpenCV build
# lacks an H.264 encoder. Exposed as a module constant so the fallback order
# is unit-testable without a real OpenCV VideoWriter.
FOURCC_CANDIDATES: Tuple[str, ...] = ("avc1", "H264", "mp4v")

# Bounded producer/consumer queue between the GUI-thread frame grabber and the
# background encoder thread. ~6s of buffer at the default 10fps — enough to
# absorb a brief encoder stall without growing memory unboundedly.
_QUEUE_MAX_FRAMES = int(os.environ.get("AIPACS_CASE_OF_DAY_RECORD_QUEUE", "60") or 60)


def _record_fps_default() -> int:
    try:
        return max(1, int(os.environ.get("AIPACS_CASE_OF_DAY_RECORD_FPS", "10")))
    except Exception:
        return 10


def opencv_available() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_active_capture_target(patient_widget):
    """Return ``(capture_widget, overlay_container)`` for *patient_widget*'s
    currently active viewport, or ``(None, None)`` if nothing usable is
    selected.

    ``capture_widget`` is exactly the one viewport cell — grabbing it never
    includes window borders, menus, toolbars, or the patient list, because
    those are sibling widgets elsewhere in the layout, not children of this
    cell.
    """
    container = getattr(patient_widget, "selected_widget", None)
    if container is None:
        return None, None
    try:
        import shiboken6
        if not shiboken6.isValid(container):
            return None, None
    except Exception:
        pass  # shiboken unavailable — fall through to duck typing
    return container, container


def _get_fast_qt_viewer(container):
    """Reach the FAST `QtSliceViewer` (has `set_show_annotations`) inside a
    `QtFastContainer`, if that's what *container* is. Returns ``None`` for any
    other viewer surface (VTK/MPR) — overlay suppression is FAST-only today,
    a documented limitation rather than a silent assumption."""
    if container is None:
        return None
    viewer = getattr(container, "_qt_viewer_widget", None)
    if viewer is not None:
        return viewer
    bridge = getattr(container, "_qt_bridge", None)
    return getattr(bridge, "qt_viewer", None) if bridge is not None else None


class OverlayGuard:
    """Temporarily hides the FAST corner patient-identity overlay (name / ID /
    age / sex) on ONE viewport for the duration of a capture, then restores
    whatever it was before. No-op (safe) when the container isn't a FAST
    viewer or overlay hiding is disabled via ``PRIVACY_HIDE_OVERLAY``/passing
    ``None``. Never touches DICOM data; never leaves the overlay permanently
    hidden even if capture raises — call ``restore()`` in a ``finally``.
    """

    def __init__(self, container):
        self._viewer = _get_fast_qt_viewer(container)
        self._previous: Optional[bool] = None

    def hide(self) -> None:
        if self._viewer is None:
            return
        try:
            self._previous = bool(getattr(self._viewer, "_show_annotations", True))
            self._viewer.set_show_annotations(False)
        except Exception:
            logger.warning("case_media_capture: failed to hide patient overlay", exc_info=True)

    def restore(self) -> None:
        if self._viewer is None or self._previous is None:
            return
        try:
            self._viewer.set_show_annotations(self._previous)
        except Exception:
            logger.warning("case_media_capture: failed to restore patient overlay", exc_info=True)
        finally:
            self._previous = None


# ---------------------------------------------------------------------------
# Screenshot (JPEG)
# ---------------------------------------------------------------------------

def capture_screenshot_jpeg(patient_widget, case_dicom_folder_path: str, *, quality: int = 92) -> Optional[str]:
    """Capture the active viewport and save it as a high-quality JPEG inside
    this case's ``screenshots/`` subfolder. Returns the saved path, or
    ``None`` when there's no active viewport or no on-disk case folder yet.
    """
    from modules.education.case_of_day_database import case_media_dir
    from modules.viewer.viewport_capture import grab_widget_pixmap

    widget, container = resolve_active_capture_target(patient_widget)
    if widget is None:
        return None
    target_dir = case_media_dir(case_dicom_folder_path, "screenshots")
    if target_dir is None:
        return None

    guard = OverlayGuard(container if PRIVACY_HIDE_OVERLAY else None)
    guard.hide()
    try:
        try:
            widget.repaint()  # flush pending paints (incl. the overlay hide) before reading pixels
        except Exception:
            pass
        pixmap = grab_widget_pixmap(widget)
    finally:
        guard.restore()

    if pixmap is None or pixmap.isNull():
        return None

    dest = _unique_path(target_dir, "screenshot", "jpg")
    try:
        if pixmap.save(str(dest), "JPG", int(quality)):
            return str(dest)
    except Exception:
        logger.error("case_media_capture: failed to save screenshot", exc_info=True)
    return None


def _unique_path(target_dir: Path, stem: str, suffix: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = target_dir / f"{stem}_{stamp}.{suffix}"
    counter = 1
    while dest.exists():
        dest = target_dir / f"{stem}_{stamp}_{counter}.{suffix}"
        counter += 1
    return dest


def resolve_recording_output_path(case_dicom_folder_path: str) -> Optional[str]:
    from modules.education.case_of_day_database import case_media_dir

    target_dir = case_media_dir(case_dicom_folder_path, "videos")
    if target_dir is None:
        return None
    return str(_unique_path(target_dir, "viewport_record", "mp4"))


# ---------------------------------------------------------------------------
# Frame conversion + MP4 writer
# ---------------------------------------------------------------------------

def _pixmap_to_bgr_array(pixmap):
    """Convert a QPixmap frame to a contiguous BGR ``numpy`` array for
    ``cv2.VideoWriter``. Returns ``None`` (frame dropped, logged once) on any
    conversion failure rather than raising into the capture timer."""
    try:
        import numpy as np
        from PySide6.QtGui import QImage

        image = pixmap.toImage().convertToFormat(QImage.Format_RGB888)
        width, height = image.width(), image.height()
        if width <= 0 or height <= 0:
            return None
        bytes_per_line = image.bytesPerLine()
        raw = bytes(image.constBits())
        needed = height * bytes_per_line
        if len(raw) < needed:
            return None
        arr = np.frombuffer(raw, dtype=np.uint8, count=needed).reshape((height, bytes_per_line))
        arr = arr[:, : width * 3].reshape((height, width, 3))
        return np.ascontiguousarray(arr[:, :, ::-1])  # RGB -> BGR
    except Exception:
        logger.warning("case_media_capture: failed to convert a frame", exc_info=True)
        return None


def _open_video_writer(path: str, fps: int, frame_size: Tuple[int, int]):
    """Try each candidate fourcc in order, returning the first VideoWriter
    that actually opens. ``frame_size`` is ``(width, height)``."""
    import cv2

    width, height = frame_size
    for fourcc_str in FOURCC_CANDIDATES:
        try:
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            writer = cv2.VideoWriter(str(path), fourcc, float(fps), (int(width), int(height)))
        except Exception:
            continue
        if writer is not None and writer.isOpened():
            logger.info("case_media_capture: opened MP4 writer (fourcc=%s) -> %s", fourcc_str, path)
            return writer
        try:
            writer.release()
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

class ViewportRecorder:
    """Grabs *widget* on a QTimer and encodes the frames into an MP4 on a
    background thread. Construct, call :meth:`start`, later call
    :meth:`stop` — both are cheap/non-blocking on the GUI thread (stop joins
    the encoder thread with a bounded timeout so the UI never hangs waiting
    for a slow flush).
    """

    def __init__(self, widget, output_path: str, fps: Optional[int] = None):
        from PySide6.QtCore import QTimer

        self._widget = widget
        self._output_path = str(output_path)
        self._fps = int(fps or _record_fps_default())
        self._timer = QTimer()
        self._timer.setInterval(max(1, int(1000 / self._fps)))
        self._timer.timeout.connect(self._on_tick)
        self._queue: "queue.Queue" = queue.Queue(maxsize=_QUEUE_MAX_FRAMES)
        self._writer = None
        self._writer_frame_size: Optional[Tuple[int, int]] = None
        self._worker: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_count = 0
        self._dropped_count = 0
        self._start_time = 0.0
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def elapsed_seconds(self) -> float:
        if not self._start_time:
            return 0.0
        return max(0.0, time.monotonic() - self._start_time)

    def start(self) -> bool:
        if self._active or self._widget is None:
            return False
        self._active = True
        self._frame_count = 0
        self._dropped_count = 0
        self._stop_event.clear()
        self._worker = threading.Thread(
            target=self._encode_loop, name="CaseOfDayViewportRecorder", daemon=True
        )
        self._worker.start()
        self._start_time = time.monotonic()
        self._timer.start()
        return True

    def stop(self, *, timeout: float = 5.0) -> Tuple[int, float]:
        """Stop capturing, flush remaining queued frames, and release the
        writer. Returns ``(frame_count, elapsed_seconds)``."""
        if not self._active:
            return self._frame_count, self.elapsed_seconds
        self._active = False
        try:
            self._timer.stop()
        except Exception:
            pass
        self._stop_event.set()
        try:
            self._queue.put_nowait(None)  # wake a blocked get()
        except Exception:
            pass
        if self._worker is not None:
            self._worker.join(timeout=timeout)
        elapsed = self.elapsed_seconds
        if self._dropped_count:
            logger.info(
                "case_media_capture: recording finished, dropped %d/%d frames under backpressure",
                self._dropped_count, self._frame_count + self._dropped_count,
            )
        return self._frame_count, elapsed

    def _on_tick(self):
        if not self._active:
            return
        try:
            self._widget.repaint()
        except Exception:
            pass
        try:
            from modules.viewer.viewport_capture import grab_widget_pixmap
        except Exception:
            return
        pixmap = grab_widget_pixmap(self._widget)
        if pixmap is None or pixmap.isNull():
            return
        array = _pixmap_to_bgr_array(pixmap)
        if array is None:
            return
        try:
            self._queue.put_nowait(array)
        except queue.Full:
            self._dropped_count += 1  # backpressure: drop, never block the GUI thread

    def _encode_loop(self):
        while (not self._stop_event.is_set()) or (not self._queue.empty()):
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                continue
            frame = item
            if self._writer is None:
                self._writer_frame_size = (int(frame.shape[1]), int(frame.shape[0]))
                self._writer = _open_video_writer(self._output_path, self._fps, self._writer_frame_size)
                if self._writer is None:
                    logger.error(
                        "case_media_capture: no usable MP4 writer for %s (tried %s)",
                        self._output_path, FOURCC_CANDIDATES,
                    )
                    return
            if (int(frame.shape[1]), int(frame.shape[0])) != self._writer_frame_size:
                try:
                    import cv2
                    frame = cv2.resize(frame, self._writer_frame_size)
                except Exception:
                    continue
            try:
                self._writer.write(frame)
                self._frame_count += 1
            except Exception:
                logger.warning("case_media_capture: dropped a frame during encode", exc_info=True)
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass


def begin_recording(
    patient_widget, case_dicom_folder_path: str, *, fps: Optional[int] = None
) -> Tuple[Optional[ViewportRecorder], Optional[OverlayGuard], Optional[str]]:
    """High-level entry point used by the Case-of-Day dialog's Record button.

    Resolves the active viewport, hides the patient-identity overlay on it
    (if enabled), and starts a :class:`ViewportRecorder`. Returns
    ``(recorder, overlay_guard, error_message)`` — exactly one of
    ``recorder``/``error_message`` is non-``None``. The caller MUST call
    ``overlay_guard.restore()`` when recording stops (see
    :func:`end_recording`).
    """
    if not opencv_available():
        return None, None, "Video recording is unavailable (OpenCV is not installed)."

    widget, container = resolve_active_capture_target(patient_widget)
    if widget is None:
        return None, None, "No active viewport to record."

    output_path = resolve_recording_output_path(case_dicom_folder_path)
    if output_path is None:
        return None, None, "This case has no on-disk folder yet — pick or export a DICOM folder first."

    guard = OverlayGuard(container if PRIVACY_HIDE_OVERLAY else None)
    guard.hide()
    recorder = ViewportRecorder(widget, output_path, fps=fps)
    if not recorder.start():
        guard.restore()
        return None, None, "Failed to start the recorder."
    return recorder, guard, None


def end_recording(recorder: ViewportRecorder, guard: Optional[OverlayGuard]) -> Tuple[str, int, float]:
    """Stop *recorder*, restore the overlay via *guard*, and return
    ``(output_path, frame_count, elapsed_seconds)``."""
    frame_count, elapsed = recorder.stop()
    if guard is not None:
        guard.restore()
    return recorder._output_path, frame_count, elapsed
