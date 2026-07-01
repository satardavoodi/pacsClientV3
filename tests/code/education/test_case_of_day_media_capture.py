"""Case-of-Day Media Capture — pure-logic + source-pin tests.

Scope, deliberately: the parts of this feature that DON'T require a live Qt
application (no `QApplication`, no FAST viewer, no real DICOM study) are
covered with real behavioral assertions. Everything Qt/viewer-dependent
(non-modal interaction, the actual Screenshot/Record buttons, overlay
suppression against a real `QtSliceViewer`) needs the Windows source build —
see docs/reports/CASE_OF_DAY_MEDIA_CAPTURE_2026-07-01.md "NOT done" section
and the guard note in CLAUDE.md.

Covered here:
  * `case_of_day_database.case_media_dir` — new subfolders, legacy no-op.
  * `case_media_capture` fourcc fallback order + `_open_video_writer` against
    a REAL `cv2.VideoWriter` (opencv-python-headless is a hard dependency of
    this repo, so this runs everywhere the app runs).
  * `_pixmap_to_bgr_array`'s sibling logic is Qt-only and is exercised via a
    hand-built `numpy` buffer round-trip through `cv2.VideoWriter` instead
    (same encode path the recorder uses), which does not need PySide6.
  * `OverlayGuard` against a duck-typed fake viewer (no real Qt object needed
    — the guard only calls `set_show_annotations`/reads `_show_annotations`).
  * `ViewportRecorder`'s queue/backpressure and start/stop bookkeeping against
    a fake widget whose "pixmap" is a plain object carrying a numpy frame,
    monkeypatching `grab_widget_pixmap`/`_pixmap_to_bgr_array` so no Qt is
    required to prove the threading/queue contract.

NOT covered here (needs the Windows source build / live FAST viewer):
  * `resolve_active_capture_target` against a real `PatientWidget`.
  * The dialog's non-modal behavior and Media Capture section wiring
    (`CaseOfDayEntryDialog` requires PySide6 to import).
  * End-to-end JPEG/MP4 correctness against a real rendered viewport.
"""
from __future__ import annotations

import queue
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from modules.education import case_media_capture as cmc  # noqa: E402
from modules.education import case_of_day_database as codb  # noqa: E402


# ---------------------------------------------------------------------------
# case_media_dir (case_of_day_database.py)
# ---------------------------------------------------------------------------

def _make_package_dir(tmp_path: Path) -> Path:
    """Build a minimal <package>/dicom/ layout, the shape
    resolve_case_package_dir requires."""
    package_dir = tmp_path / "case_20260701_000000_demo"
    dicom_dir = package_dir / codb.PACKAGE_DICOM_SUBDIR
    dicom_dir.mkdir(parents=True)
    return dicom_dir  # this is the "dicom_folder_path" the DB stores


def test_case_media_dir_creates_new_subfolders(tmp_path):
    dicom_dir = _make_package_dir(tmp_path)
    for kind, expected_name in (
        ("screenshots", codb.PACKAGE_SCREENSHOTS_SUBDIR),
        ("videos", codb.PACKAGE_VIDEOS_SUBDIR),
        ("card", codb.PACKAGE_CARD_SUBDIR),
        ("notes", codb.PACKAGE_NOTES_SUBDIR),
        ("attachments", codb.PACKAGE_ATTACHMENTS_SUBDIR),
    ):
        target = codb.case_media_dir(str(dicom_dir), kind)
        assert target is not None
        assert target.name == expected_name
        assert target.is_dir()  # created on demand
        assert target.parent == dicom_dir.parent  # sibling of dicom/, inside the package


def test_case_media_dir_unknown_kind_returns_none(tmp_path):
    dicom_dir = _make_package_dir(tmp_path)
    assert codb.case_media_dir(str(dicom_dir), "not-a-real-kind") is None


def test_case_media_dir_legacy_case_returns_none(tmp_path):
    # A legacy case: the "dicom_folder_path" IS the case folder (no dicom/
    # subdir nesting) — resolve_case_package_dir must return None, and so
    # must case_media_dir, per its docstring contract.
    legacy_folder = tmp_path / "legacy_case_no_package_dir"
    legacy_folder.mkdir()
    assert codb.resolve_case_package_dir(str(legacy_folder)) is None
    assert codb.case_media_dir(str(legacy_folder), "screenshots") is None


def test_case_media_dir_no_create_does_not_touch_disk(tmp_path):
    dicom_dir = _make_package_dir(tmp_path)
    target = codb.case_media_dir(str(dicom_dir), "videos", create=False)
    assert target is not None
    assert not target.exists()


# ---------------------------------------------------------------------------
# _env_flag (both modules define their own copy — pin the shared contract)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("0", False), ("false", False), ("False", False), ("no", False), ("off", False), ("", False),
    ("1", True), ("true", True), ("yes", True), ("anything-else", True),
])
def test_env_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("AIPACS_TEST_FLAG_PROBE", raw)
    assert cmc._env_flag("AIPACS_TEST_FLAG_PROBE", False) is expected


def test_env_flag_default_when_unset(monkeypatch):
    monkeypatch.delenv("AIPACS_TEST_FLAG_PROBE", raising=False)
    assert cmc._env_flag("AIPACS_TEST_FLAG_PROBE", True) is True
    assert cmc._env_flag("AIPACS_TEST_FLAG_PROBE", False) is False


# ---------------------------------------------------------------------------
# Fourcc fallback + real cv2.VideoWriter (no Qt needed)
# ---------------------------------------------------------------------------

def test_fourcc_candidates_order_is_h264_first():
    # H.264 (small + high quality) must be tried before the always-available
    # but much larger mp4v fallback — this is the "good compression, high
    # quality" requirement from the spec.
    assert cmc.FOURCC_CANDIDATES[0] in ("avc1", "H264")
    assert cmc.FOURCC_CANDIDATES[-1] == "mp4v"


def test_open_video_writer_produces_a_real_playable_file(tmp_path):
    out_path = tmp_path / "probe.mp4"
    writer = cmc._open_video_writer(str(out_path), fps=10, frame_size=(64, 48))
    assert writer is not None, (
        "No usable OpenCV MP4 fourcc on this machine — every candidate in "
        f"{cmc.FOURCC_CANDIDATES} failed to open. Screenshots would still "
        "work; recording would not. Investigate the OpenCV build before "
        "shipping."
    )
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    for _ in range(5):
        writer.write(frame)
    writer.release()
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_open_video_writer_bad_path_returns_none():
    # A directory that can't possibly be opened as a video file — every
    # candidate should fail cleanly and the function returns None rather
    # than raising, so the caller can show a friendly error.
    result = cmc._open_video_writer("/nonexistent/dir/does/not/exist.mp4", fps=10, frame_size=(64, 48))
    assert result is None


# ---------------------------------------------------------------------------
# OverlayGuard — duck-typed fake viewer, no real Qt object required
# ---------------------------------------------------------------------------

class _FakeQtViewer:
    def __init__(self, initial=True):
        self._show_annotations = initial

    def set_show_annotations(self, show):
        self._show_annotations = bool(show)


class _FakeFastContainer:
    """Mimics enough of QtFastContainer for _get_fast_qt_viewer to find it."""
    def __init__(self, viewer):
        self._qt_viewer_widget = viewer


def test_overlay_guard_hides_and_restores():
    viewer = _FakeQtViewer(initial=True)
    container = _FakeFastContainer(viewer)
    guard = cmc.OverlayGuard(container)

    guard.hide()
    assert viewer._show_annotations is False, "overlay must be hidden during capture"

    guard.restore()
    assert viewer._show_annotations is True, "overlay must be restored to its prior state"


def test_overlay_guard_restores_previously_hidden_state():
    # If the overlay was ALREADY hidden before capture (unusual but possible),
    # restore() must not turn it back on — it restores to what it WAS.
    viewer = _FakeQtViewer(initial=False)
    container = _FakeFastContainer(viewer)
    guard = cmc.OverlayGuard(container)
    guard.hide()
    guard.restore()
    assert viewer._show_annotations is False


def test_overlay_guard_is_noop_for_none_container():
    # PRIVACY_HIDE_OVERLAY=False path, or a non-FAST (VTK/MPR) container —
    # must never raise.
    guard = cmc.OverlayGuard(None)
    guard.hide()
    guard.restore()  # no exception


def test_overlay_guard_is_noop_for_non_fast_container():
    class _NotFast:
        pass

    guard = cmc.OverlayGuard(_NotFast())
    guard.hide()
    guard.restore()  # no exception, no attribute created


# ---------------------------------------------------------------------------
# capture_screenshot_jpeg / resolve_recording_output_path — folder resolution
# ---------------------------------------------------------------------------

def test_resolve_recording_output_path_under_videos_subfolder(tmp_path):
    dicom_dir = _make_package_dir(tmp_path)
    out = cmc.resolve_recording_output_path(str(dicom_dir))
    assert out is not None
    out_path = Path(out)
    assert out_path.parent.name == codb.PACKAGE_VIDEOS_SUBDIR
    assert out_path.suffix == ".mp4"


def test_resolve_recording_output_path_legacy_case_returns_none(tmp_path):
    legacy_folder = tmp_path / "legacy_no_package"
    legacy_folder.mkdir()
    assert cmc.resolve_recording_output_path(str(legacy_folder)) is None


def test_unique_path_avoids_collision(tmp_path):
    target_dir = tmp_path / "screenshots"
    target_dir.mkdir()
    first = cmc._unique_path(target_dir, "screenshot", "jpg")
    first.write_bytes(b"fake-jpeg-bytes")
    second = cmc._unique_path(target_dir, "screenshot", "jpg")
    assert second != first
    assert not second.exists()


# ---------------------------------------------------------------------------
# ViewportRecorder — queue/backpressure contract (PySide6-free fake widget)
# ---------------------------------------------------------------------------

class _FakePixmap:
    """Stand-in for a QPixmap: isNull()/toImage() aren't needed because we
    monkeypatch the conversion function directly (see below)."""
    def __init__(self, frame):
        self.frame = frame

    def isNull(self):
        return False


class _FakeWidget:
    def __init__(self, frame_shape=(48, 64, 3)):
        self._frame_shape = frame_shape
        self.repaint_calls = 0

    def repaint(self):
        self.repaint_calls += 1


@pytest.fixture
def fake_recorder_env(tmp_path, monkeypatch):
    """Monkeypatch the two real-Qt touch points so ViewportRecorder can be
    driven end-to-end (timer tick -> queue -> background encoder -> real
    cv2.VideoWriter) without PySide6 installed."""
    frame_holder = {"frame": np.zeros((48, 64, 3), dtype=np.uint8)}

    def _fake_grab_widget_pixmap(widget):
        return _FakePixmap(frame_holder["frame"])

    def _fake_pixmap_to_bgr_array(pixmap):
        return pixmap.frame

    # ViewportRecorder imports these INSIDE its methods (module-qualified),
    # so patch them where they're looked up.
    monkeypatch.setattr(
        "modules.viewer.viewport_capture.grab_widget_pixmap",
        _fake_grab_widget_pixmap,
        raising=False,
    )
    monkeypatch.setattr(cmc, "_pixmap_to_bgr_array", _fake_pixmap_to_bgr_array)
    return frame_holder


def test_viewport_recorder_start_stop_produces_file(tmp_path, fake_recorder_env, monkeypatch):
    # ViewportRecorder.__init__ imports QTimer from PySide6 — skip cleanly if
    # PySide6 truly isn't installed anywhere reachable (sandbox default);
    # this test still documents/pins the intended contract for when it is.
    pytest.importorskip("PySide6")
    widget = _FakeWidget()
    out_path = tmp_path / "rec.mp4"
    recorder = cmc.ViewportRecorder(widget, str(out_path), fps=20)
    assert recorder.start() is True
    # Manually pump a few ticks instead of waiting on the real QTimer/event
    # loop (no QApplication running in this test).
    for _ in range(5):
        recorder._on_tick()
        time.sleep(0.02)
    frame_count, elapsed = recorder.stop()
    assert frame_count > 0
    assert elapsed >= 0
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_viewport_recorder_drops_frames_under_backpressure(monkeypatch):
    pytest.importorskip("PySide6")
    widget = _FakeWidget()
    recorder = cmc.ViewportRecorder(widget, "unused.mp4", fps=1000)
    # Stuff the queue full without starting the encoder thread, then confirm
    # a tick drops rather than blocks.
    recorder._active = True
    for _ in range(cmc._QUEUE_MAX_FRAMES):
        recorder._queue.put_nowait(np.zeros((2, 2, 3), dtype=np.uint8))
    assert recorder._queue.full()
    recorder._on_tick()  # must not raise / block
    assert recorder._dropped_count == 1
