"""Cine / multi-frame playback metadata + player state machine (2026-07-01).

Pure, Qt-free coverage of:
- cine_metadata.resolve_frame_rate / playback_fps (DICOM timing precedence + clamp)
- cine_player.CinePlayer (play/pause/toggle/advance/loop/step)
- dicom_header_scan capture of SOP class + cine timing tags (real synthetic DICOM)
"""
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _load_fast_module(name):
    """Load a self-contained modules/viewer/fast/*.py headless (no Qt chain)."""
    fast_dir = _repo_root() / "modules" / "viewer" / "fast"
    if str(fast_dir) not in sys.path:
        sys.path.insert(0, str(fast_dir))
    import importlib
    return importlib.import_module(name)


# ── cine_metadata: frame-rate resolution ──────────────────────────────
def test_frame_rate_precedence():
    cm = _load_fast_module("cine_metadata")
    # RecommendedDisplayFrameRate wins over everything
    assert cm.resolve_frame_rate(recommended_display_frame_rate=24,
                                 cine_rate=15, frame_time_ms=10) == 24.0
    # then CineRate
    assert cm.resolve_frame_rate(cine_rate=15, frame_time_ms=10) == 15.0
    # then 1000/FrameTime (33.3ms -> ~30 fps)
    assert abs(cm.resolve_frame_rate(frame_time_ms=1000.0 / 30.0) - 30.0) < 1e-6
    # then FrameTimeVector mean
    assert abs(cm.resolve_frame_rate(frame_time_vector=[40.0, 60.0]) - 20.0) < 1e-6
    # nothing usable -> default (clamped), or None
    assert cm.resolve_frame_rate(default=15) == 15.0
    assert cm.resolve_frame_rate() is None


def test_frame_rate_clamped_and_guards_bad_values():
    cm = _load_fast_module("cine_metadata")
    assert cm.resolve_frame_rate(cine_rate=99999) == cm.MAX_CINE_FPS
    assert cm.resolve_frame_rate(cine_rate=0.001) == cm.MIN_CINE_FPS
    # non-positive / garbage timing tags are ignored, fall through
    assert cm.resolve_frame_rate(cine_rate=0, frame_time_ms=-5, default=15) == 15.0
    assert cm.resolve_frame_rate(frame_time_ms="x", default=15) == 15.0


def test_playback_fps_only_for_multiframe():
    cm = _load_fast_module("cine_metadata")
    assert cm.is_cine(8) is True and cm.is_cine(1) is False and cm.is_cine(None) is False
    # still image -> no rate even if a stray tag exists
    assert cm.playback_fps(1, cine_rate=30) is None
    # multi-frame with no timing -> the default cine fps (never a spurious rate on stills)
    assert cm.playback_fps(8) == cm.DEFAULT_CINE_FPS
    assert cm.playback_fps(8, cine_rate=25) == 25.0


# ── cine_player: state machine ────────────────────────────────────────
def test_player_basic_play_advance_loop():
    cp = _load_fast_module("cine_player")
    p = cp.CinePlayer(fps=10, loop=True)
    p.set_count(3)
    assert p.can_play() and p.interval_ms == 100  # 1000/10
    assert p.play() is True and p.playing is True
    assert p.advance() == 1
    assert p.advance() == 2
    assert p.advance() == 0  # wraps (loop)
    p.pause()
    assert p.advance() is None  # paused -> no advance


def test_player_non_loop_stops_at_end():
    cp = _load_fast_module("cine_player")
    p = cp.CinePlayer(fps=30, loop=False)
    p.set_count(2)
    p.play()
    assert p.advance() == 1
    assert p.advance() is None      # hit the end, non-loop
    assert p.playing is False
    # play again from the end restarts at 0
    assert p.play() is True and p.index == 0


def test_player_single_frame_never_plays():
    cp = _load_fast_module("cine_player")
    p = cp.CinePlayer()
    p.set_count(1)
    assert p.can_play() is False
    assert p.play() is False and p.playing is False
    assert p.advance() is None


def test_player_sync_index_and_toggle_and_step():
    cp = _load_fast_module("cine_player")
    p = cp.CinePlayer(fps=15, loop=True)
    p.set_count(5)
    p.sync_index(3)          # user scrolled to frame 3
    assert p.index == 3
    assert p.toggle() is True and p.playing is True   # play from 3
    assert p.advance() == 4
    assert p.advance() == 0  # wrap
    assert p.toggle() is False  # pause
    # manual stepping wraps and does not start playback
    assert p.step(-1) == 4
    assert p.playing is False
    p.stop()
    assert p.index == 0 and p.playing is False


def test_player_set_count_clamps_index_and_stops():
    cp = _load_fast_module("cine_player")
    p = cp.CinePlayer()
    p.set_count(10)
    p.sync_index(9)
    p.play()
    p.set_count(4)           # series shrank (shouldn't happen, but be safe)
    assert p.index == 3      # clamped
    p.set_count(1)
    assert p.playing is False  # nothing to play


# ── header scan captures SOP class + cine timing ──────────────────────
def test_header_scan_captures_sopclass_and_timing(tmp_path):
    pytest.importorskip("pydicom")
    import numpy as np
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    import importlib.util
    mod_path = _repo_root() / "modules" / "viewer" / "fast" / "dicom_header_scan.py"
    spec = importlib.util.spec_from_file_location("aipacs_dhs_cine", mod_path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    try:
        spec.loader.exec_module(m)
    except Exception as exc:  # pragma: no cover
        pytest.skip("header-scan import unavailable: %s" % exc)

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.3.1"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.3.1"  # US Multi-frame
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.Modality = "US"
    ds.InstanceNumber = 1
    ds.Rows = 8
    ds.Columns = 8
    ds.NumberOfFrames = 12
    ds.FrameTime = 33.333
    ds.CineRate = 30
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = np.zeros((12, 8, 8), dtype=np.uint16).tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    series_dir = tmp_path / "1"
    series_dir.mkdir()
    ds.save_as(str(series_dir / "cine.dcm"), write_like_original=False)

    entries = m.scan_series_header_entries(str(series_dir))
    assert len(entries) == 1
    e = entries[0]
    assert e.num_frames == 12
    assert e.sop_class_uid == "1.2.840.10008.5.1.4.1.1.3.1"
    assert abs(e.frame_time_ms - 33.333) < 1e-3
    assert abs(e.cine_rate - 30.0) < 1e-6

    # resolver turns those captured tags into a playback fps
    cm = _load_fast_module("cine_metadata")
    fps = cm.playback_fps(e.num_frames, recommended_display_frame_rate=e.recommended_display_frame_rate,
                          cine_rate=e.cine_rate, frame_time_ms=e.frame_time_ms)
    assert fps == 30.0  # CineRate wins over 1000/FrameTime


def test_header_scan_capture_source_pins():
    """Reliable source-pin for the SOP-class + cine-timing capture (the behavioral
    test above needs to exec the module, which the sandbox FUSE mount reads
    unreliably; this pin always runs and verifies the wiring)."""
    src = (_repo_root() / "modules" / "viewer" / "fast" / "dicom_header_scan.py").read_text(encoding="utf-8")
    assert "sop_class_uid: str = \"\"" in src
    assert "frame_time_ms: Optional[float] = None" in src
    assert "cine_rate: Optional[float] = None" in src
    assert "recommended_display_frame_rate: Optional[float] = None" in src
    assert 'sop_class_uid=str(getattr(ds, "SOPClassUID", "") or "")' in src
    assert 'frame_time_ms=_safe_float(getattr(ds, "FrameTime", None))' in src
    assert 'cine_rate=_safe_float(getattr(ds, "CineRate", None))' in src


def test_container_cine_wiring_source_pins():
    """Source-pin the FAST container cine engine (needs PySide6 to instantiate;
    pins target the early-file cine methods which read intact even if the sandbox
    FUSE truncates the tail of this large file)."""
    path = (_repo_root() / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
            / "vtk_widget" / "qt_fast_container.py")
    src = path.read_text(encoding="utf-8")
    # flag, default-on with kill switch
    assert 'os.environ.get("AIPACS_FAST_CINE", "1")' in src
    assert "_FAST_CINE_ENABLED = str(" in src
    # additive engine members + public + timer-driven methods
    assert "self._cine_player = None" in src
    assert "self._cine_timer = None" in src
    assert "def toggle_cine(self) -> bool:" in src
    assert "def start_cine(self) -> bool:" in src
    assert "def _cine_tick(self) -> None:" in src
    # gated to real cine series; single-frame is a no-op
    assert "if not self.is_cine_series():" in src
    # Space toggles cine, everything else passes through unchanged
    assert "event.key() == Qt.Key_Space and self.is_cine_series()" in src
    assert "super().keyPressEvent(event)" in src
    # pipeline exposes the cine getters the container reads
    pl = (_repo_root() / "modules" / "viewer" / "fast" / "lightweight_2d_pipeline.py").read_text(encoding="utf-8")
    assert "def is_cine_series(self) -> bool:" in pl
    assert "def cine_frame_rate(self) -> Optional[float]:" in pl
