"""Owned startup preparation must not transfer Qt/executor ownership or reread pixels."""
from concurrent.futures import CancelledError, ThreadPoolExecutor
from copy import deepcopy
import threading

import numpy as np
import pydicom
import pytest
from PySide6.QtWidgets import QApplication

from modules.viewer.fast import lightweight_2d_pipeline as lw
from tests.code.viewer.test_fast_multiframe import _make_multiframe_dicom


@pytest.fixture
def source(tmp_path, monkeypatch):
    # Only synthetic files and no process decoder / persistent disk pixel cache.
    path = tmp_path / "cine.dcm"
    _make_multiframe_dicom(path, n_frames=8, rows=16, cols=12)
    monkeypatch.setattr(lw, "get_disk_pixel_cache", lambda: lw._NULL_DISK_PIXEL_CACHE)
    cfg = lw.PipelineConfig(opencv_filter_enabled=False)
    metadata = {"series": {"study_uid": "1.2.3", "series_uid": "1.2.3.4",
                           "series_number": "1", "modality": "US"},
                "instances": [{"instance_path": str(path)}]}
    return str(tmp_path), metadata, cfg


def prepare(source, **kwargs):
    path, metadata, cfg = source
    with ThreadPoolExecutor(max_workers=1) as worker:
        return worker.submit(lw.Lightweight2DPipeline.prepare_initial_display,
                             path, metadata=metadata, config=cfg,
                             request_key=("viewer-A", "1.2.3", "1.2.3.4", 1),
                             **kwargs).result(timeout=10)


KEY = ("viewer-A", "1.2.3", "1.2.3.4", 1)


def test_worker_prepares_and_gui_adopts_without_dicom_reads(source, monkeypatch):
    app = QApplication.instance() or QApplication([])
    before = deepcopy(source[1])
    calls = []
    read = pydicom.dcmread

    def counted(*args, **kwargs):
        calls.append(threading.get_ident())
        return read(*args, **kwargs)

    monkeypatch.setattr(pydicom, "dcmread", counted)
    prepared = prepare(source)
    assert calls and threading.get_ident() not in calls
    assert source[1] == before
    target = lw.Lightweight2DPipeline(config=source[2])
    try:
        facts = target.adopt_initial_display(prepared, request_key=KEY)
        assert target.thread() == app.thread()
        assert facts.slice_index == 4
        assert target.slice_count == 8
        assert facts.scalar_range == (0.0, 0.0)
        reads_before = len(calls)
        assert target.get_scalar_range(0) == facts.scalar_range
        target.get_default_window_level(0)
        target.get_default_window_level(4)
        frame = target.get_rendered_frame(4)
        assert frame.cache_source == "hit"
        assert (frame.width, frame.height) == (12, 16)
        np.testing.assert_array_equal(target.get_pixel_array(4), np.full((16, 12), 4))
        assert len(calls) == reads_before
        assert not target._prefetch_pending and not target._frame_prefetch_pending
    finally:
        target.shutdown()


@pytest.mark.parametrize("key", [("viewer-B", "1.2.3", "1.2.3.4", 1),
                                  ("viewer-A", "1.2.3", "1.2.3.4", 2),
                                  ("viewer-A", "1.2.8", "1.2.8.9", 1)])
def test_wrong_owner_identity_or_revision_cannot_consume(source, key):
    prepared = prepare(source)
    target = lw.Lightweight2DPipeline(config=source[2])
    try:
        with pytest.raises(ValueError, match="request"):
            target.adopt_initial_display(prepared, request_key=key)
        assert target.slice_count == 0
        target.adopt_initial_display(prepared, request_key=KEY)
        assert target.slice_count == 8
    finally:
        target.shutdown()


def test_payload_has_only_one_consumer_and_can_be_discarded(source):
    prepared = prepare(source)
    first = lw.Lightweight2DPipeline(config=source[2])
    second = lw.Lightweight2DPipeline(config=source[2])
    try:
        first.adopt_initial_display(prepared, request_key=KEY)
        with pytest.raises(ValueError, match="consumed"):
            second.adopt_initial_display(prepared, request_key=KEY)
        prepared.discard()  # Must not clear the adopted caches.
        assert first.slice_count == 8
        assert first.get_pixel_array(4) is not None
        abandoned = prepare(source)
        abandoned.discard()
        abandoned.discard()
        with pytest.raises(ValueError, match="consumed"):
            second.adopt_initial_display(abandoned, request_key=KEY)
    finally:
        first.shutdown()
        second.shutdown()


def test_cancelled_preparation_does_no_reads(source, monkeypatch):
    monkeypatch.setattr(pydicom, "dcmread", lambda *a, **k: pytest.fail("cancelled read"))
    with pytest.raises(CancelledError):
        prepare(source, cancelled=lambda: True)


def test_preparation_never_starts_background_prefetch(source, monkeypatch):
    monkeypatch.setattr(lw.Lightweight2DPipeline, "_prefetch_around",
                        lambda *a, **k: pytest.fail("startup must not fan out"))
    result = prepare(source)
    result.discard()


def test_config_mismatch_keeps_payload_unconsumed(source):
    prepared = prepare(source)
    target = lw.Lightweight2DPipeline(config=lw.PipelineConfig(opencv_filter_enabled=True))
    try:
        with pytest.raises(ValueError, match="configuration"):
            target.adopt_initial_display(prepared, request_key=KEY)
        assert target.slice_count == 0
    finally:
        target.shutdown()
        prepared.discard()


def test_missing_pixel_failure_is_not_a_successful_black_frame(source, monkeypatch):
    monkeypatch.setattr(lw.Lightweight2DPipeline, "_get_pixel_array", lambda *a: None)
    with pytest.raises(ValueError, match="pixel"):
        prepare(source)


def test_existing_live_pipeline_cannot_be_overwritten(source):
    prepared = prepare(source)
    target = lw.Lightweight2DPipeline(config=source[2])
    try:
        target.open_series(source[0], metadata=source[1])
        slices = target._slices
        with pytest.raises(ValueError, match="empty"):
            target.adopt_initial_display(prepared, request_key=KEY)
        assert target._slices is slices
    finally:
        target.shutdown()
        prepared.discard()


def test_real_bridge_uses_prepared_first_frame_without_gui_decode(source, monkeypatch):
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    app = QApplication.instance() or QApplication([])
    prepared = prepare(source)
    pipeline = lw.Lightweight2DPipeline(config=source[2])
    facts = pipeline.adopt_initial_display(prepared, request_key=KEY)
    expected = pipeline.get_rendered_frame(facts.slice_index).qimage.copy()
    # Isolate annotation persistence and background neighbours. The changed
    # boundary is real Qt bridge construction + presentation, not tool storage.
    monkeypatch.setattr(QtViewerBridge, "_init_tool_controller", lambda self: None)
    monkeypatch.setattr(pipeline, "_prefetch_around", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "_decode_slice",
                        lambda *a: pytest.fail("GUI pixel decode after preparation"))
    monkeypatch.setattr(pydicom, "dcmread",
                        lambda *a, **k: pytest.fail("GUI header read after preparation"))
    monkeypatch.setattr(pipeline, "_render_frame_uncached",
                        lambda *a, **k: pytest.fail("prepared QImage discarded"))
    viewer = QtSliceViewer()
    bridge = None
    try:
        bridge = QtViewerBridge(viewer, pipeline, metadata=source[1],
                                initial_display_facts=facts)
        with bridge.prepared_initial_presentation():
            bridge.set_slice(facts.slice_index)
            bridge.apply_default_window_level(facts.slice_index)
        assert bridge.GetSlice() == 4
        assert bridge.get_count_of_slices() == 8
        assert pipeline.get_rendered_frame(4).qimage == expected
    finally:
        if bridge is not None:
            bridge.cleanup()
        else:
            pipeline.shutdown()
        viewer.close()
        viewer.deleteLater()


def test_prepared_overlay_is_image_owned_without_stat_and_expires(source, monkeypatch):
    from pathlib import Path
    from PacsClient.utils import overlay_identity_source as ois
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    app = QApplication.instance() or QApplication([])
    path = Path(source[0]) / "cine.dcm"
    ds = pydicom.dcmread(path)
    ds.PatientName = "IMAGE^OWNER"
    ds.save_as(path, write_like_original=False)
    ois.clear_cache()
    prepared = prepare(source)
    pipeline = lw.Lightweight2DPipeline(config=source[2])
    facts = pipeline.adopt_initial_display(prepared, request_key=KEY)
    monkeypatch.setattr(QtViewerBridge, "_init_tool_controller", lambda self: None)
    viewer = QtSliceViewer()
    bridge = QtViewerBridge(viewer, pipeline, metadata=source[1],
                            metadata_fixed={"patient_name": "WRONG^DB"},
                            initial_display_facts=facts)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(ois.os.path, "getmtime",
                          lambda *a: pytest.fail("GUI identity stat"))
            patch.setattr(pydicom, "dcmread",
                          lambda *a, **k: pytest.fail("GUI identity read"))
            with bridge.prepared_initial_presentation():
                assert bridge._build_annotation_metadata()["patient"]["patient_name"] == "IMAGE OWNER"
        # The prepared snapshot is not a permanent demographic cache. The next
        # ordinary refresh must observe a local tag edit through the same reader.
        ds.PatientName = "EDITED^OWNER"
        ds.save_as(path, write_like_original=False)
        ois.clear_cache()
        assert bridge._build_annotation_metadata()["patient"]["patient_name"] == "EDITED OWNER"
        with pytest.raises(ValueError, match="consumed"):
            with bridge.prepared_initial_presentation():
                pass
    finally:
        bridge.cleanup()
        viewer.close()
        viewer.deleteLater()


@pytest.mark.parametrize("changed", ["study_uid", "series_uid", "instance_path"])
def test_prepared_bridge_rejects_changed_metadata_source(source, monkeypatch, changed):
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    app = QApplication.instance() or QApplication([])
    pipeline = lw.Lightweight2DPipeline(config=source[2])
    facts = pipeline.adopt_initial_display(prepare(source), request_key=KEY)
    metadata = deepcopy(source[1])
    if changed == "instance_path":
        metadata["instances"][0][changed] = "another-file.dcm"
    else:
        metadata["series"][changed] = "1.2.999"
    monkeypatch.setattr(QtViewerBridge, "_init_tool_controller", lambda self: None)
    viewer = QtSliceViewer()
    try:
        with pytest.raises(ValueError, match="identity|source"):
            QtViewerBridge(viewer, pipeline, metadata=metadata, initial_display_facts=facts)
    finally:
        pipeline.shutdown()
        viewer.close()
        viewer.deleteLater()


def test_prepared_overlay_accepts_sorted_multiframe_projection(source, monkeypatch):
    from pathlib import Path
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    app = QApplication.instance() or QApplication([])
    second = Path(source[0]) / "second.dcm"
    _make_multiframe_dicom(second, n_frames=4, rows=16, cols=12)
    ds = pydicom.dcmread(second)
    ds.PatientName = "SORTED^SOURCE"
    ds.save_as(second, write_like_original=False)
    source[1]["instances"][0]["instance_number"] = 2
    source[1]["instances"].append({"instance_path": str(second), "instance_number": 1})
    pipeline = lw.Lightweight2DPipeline(config=source[2])
    facts = pipeline.adopt_initial_display(prepare(source), request_key=KEY)
    metadata = dict(source[1], instances=pipeline.export_frame_instances())
    assert metadata["instances"][0]["instance_path"] == str(second)
    assert len(metadata["instances"]) == 12 and len(source[1]["instances"]) == 2
    monkeypatch.setattr(QtViewerBridge, "_init_tool_controller", lambda self: None)
    monkeypatch.setattr(pydicom, "dcmread", lambda *a, **k: pytest.fail("GUI read"))
    viewer = QtSliceViewer()
    bridge = QtViewerBridge(viewer, pipeline, metadata=metadata, initial_display_facts=facts)
    try:
        with bridge.prepared_initial_presentation():
            assert bridge._build_annotation_metadata()["patient"]["patient_name"] == "SORTED SOURCE"
    finally:
        bridge.cleanup()
        viewer.close()
        viewer.deleteLater()


@pytest.mark.parametrize("action", ["exception", "metadata_change", "empty_identity"])
def test_prepared_overlay_scope_is_bounded_and_does_not_retry_io(source, monkeypatch, action):
    from PacsClient.utils import overlay_identity_source as ois
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    app = QApplication.instance() or QApplication([])
    if action == "empty_identity":
        monkeypatch.setattr(ois, "read_identity_tags", lambda path: {})
    pipeline = lw.Lightweight2DPipeline(config=source[2])
    facts = pipeline.adopt_initial_display(prepare(source), request_key=KEY)
    monkeypatch.setattr(QtViewerBridge, "_init_tool_controller", lambda self: None)
    viewer = QtSliceViewer()
    bridge = QtViewerBridge(viewer, pipeline, metadata=deepcopy(source[1]),
                            metadata_fixed={"patient_name": "FALLBACK^DB"},
                            initial_display_facts=facts)
    calls = []
    monkeypatch.setattr(ois, "read_series_identity_from_instances",
                        lambda instances: calls.append(True) or {"patient_name": "FRESH^READ"})
    try:
        if action == "empty_identity":
            with bridge.prepared_initial_presentation():
                assert bridge._build_annotation_metadata()["patient"]["patient_name"] == "FALLBACK DB"
        else:
            with pytest.raises(ValueError):
                with bridge.prepared_initial_presentation():
                    if action == "metadata_change":
                        bridge.metadata["series"]["series_uid"] = "1.2.999"
                        bridge._build_annotation_metadata()
                    else:
                        raise ValueError("abort commit")
        assert not calls
        assert bridge._initial_identity_context is None
        assert bridge._initial_display_facts is None
        assert bridge._build_annotation_metadata()["patient"]["patient_name"] == "FRESH READ"
        assert calls == [True]
    finally:
        bridge.cleanup()
        viewer.close()
        viewer.deleteLater()


def test_preparation_rejected_on_gui(source):
    app = QApplication.instance() or QApplication([])
    with pytest.raises(RuntimeError, match="worker"):
        lw.Lightweight2DPipeline.prepare_initial_display(
            source[0], metadata=source[1], config=source[2], request_key=KEY)


def test_cancel_after_open_disposes_worker_pipeline(source, monkeypatch):
    cancelled = threading.Event()
    opened = lw.Lightweight2DPipeline.open_series
    closed = []
    shutdown = lw.Lightweight2DPipeline.shutdown

    def open_and_cancel(self, *a, **k):
        opened(self, *a, **k)
        cancelled.set()

    def close(self):
        shutdown(self)
        closed.append((self.slice_count, self._decode_executor._shutdown,
                       self._frame_executor._shutdown, self._grow_executor._shutdown))

    monkeypatch.setattr(lw.Lightweight2DPipeline, "open_series", open_and_cancel)
    monkeypatch.setattr(lw.Lightweight2DPipeline, "shutdown", close)
    with pytest.raises(CancelledError):
        prepare(source, cancelled=cancelled.is_set)
    assert closed == [(0, True, True, True)]


def test_adoption_does_not_share_native_or_executor_ownership(source):
    prepared = prepare(source)
    target = lw.Lightweight2DPipeline(config=source[2])
    before = (target.thread(), target._decode_executor, target._frame_executor,
              target._grow_executor, target._prefetch_lock, target._mf_ds_lock)
    try:
        target.adopt_initial_display(prepared, request_key=KEY)
        assert before == (target.thread(), target._decode_executor, target._frame_executor,
                          target._grow_executor, target._prefetch_lock, target._mf_ds_lock)
    finally:
        target.shutdown()


def test_shutdown_target_cannot_adopt(source):
    prepared = prepare(source)
    target = lw.Lightweight2DPipeline(config=source[2])
    target.shutdown()
    try:
        with pytest.raises(ValueError, match="empty|shutdown"):
            target.adopt_initial_display(prepared, request_key=KEY)
    finally:
        prepared.discard()


@pytest.mark.parametrize("photometric", ["MONOCHROME2", "MONOCHROME1", "RGB"])
@pytest.mark.parametrize("filtered", [False, True])
def test_prepared_and_legacy_bridge_present_identical_pixels(source, monkeypatch,
                                                           photometric, filtered):
    from pathlib import Path
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    app = QApplication.instance() or QApplication([])
    path = Path(source[0]) / "cine.dcm"
    ds = pydicom.dcmread(path)
    ds.PhotometricInterpretation = photometric
    ds.WindowWidth, ds.WindowCenter = 150, 75
    if photometric == "RGB":
        ds.SamplesPerPixel, ds.PlanarConfiguration = 3, 0
        ds.BitsAllocated, ds.BitsStored, ds.HighBit = 8, 8, 7
        pixels = np.arange(8 * 16 * 12 * 3, dtype=np.uint8).reshape(8, 16, 12, 3)
    else:
        pixels = np.arange(8 * 16 * 12, dtype=np.uint16).reshape(8, 16, 12) % 200
    ds.PixelData = pixels.tobytes()
    ds.save_as(path, write_like_original=False)
    source[2].opencv_filter_enabled = filtered
    monkeypatch.setattr(lw.Lightweight2DPipeline, "_prefetch_around", lambda *a, **k: None)
    monkeypatch.setattr(QtViewerBridge, "_init_tool_controller", lambda self: None)
    monkeypatch.setattr(QtViewerBridge, "_update_annotations", lambda *a, **k: None)
    images = []
    real_set = QtSliceViewer.set_image

    def capture(self, image):
        images.append(image.copy())
        return real_set(self, image)

    monkeypatch.setattr(QtSliceViewer, "set_image", capture)
    old = lw.Lightweight2DPipeline(config=source[2])
    new = lw.Lightweight2DPipeline(config=source[2])
    viewers, bridges = [], []
    try:
        old.open_series(source[0], metadata=source[1])
        facts = new.adopt_initial_display(prepare(source), request_key=KEY)
        for pipeline, extra in [(old, {}), (new, {"initial_display_facts": facts})]:
            viewer = QtSliceViewer()
            viewers.append(viewer)
            bridge = QtViewerBridge(viewer, pipeline, metadata=source[1], **extra)
            bridges.append(bridge)
            bridge.set_slice(pipeline.slice_count // 2)
            bridge.apply_default_window_level(pipeline.slice_count // 2)
        assert len(images) == 2 and images[0] == images[1]
        assert old.get_window_level() == new.get_window_level()
        assert old.get_geometry(4) == new.get_geometry(4)
    finally:
        for bridge in bridges:
            bridge.cleanup()
        old.shutdown()
        new.shutdown()
        for viewer in viewers:
            viewer.close()
            viewer.deleteLater()


def test_gui_heartbeat_continues_during_slow_preparation(source, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest

    app = QApplication.instance() or QApplication([])
    entered, release = threading.Event(), threading.Event()
    ticks = []
    original = pydicom.dcmread

    def slow_read(*a, **k):
        entered.set()
        if not release.wait(3):
            raise TimeoutError("synthetic preparation timeout")
        return original(*a, **k)

    monkeypatch.setattr(pydicom, "dcmread", slow_read)
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lw.Lightweight2DPipeline.prepare_initial_display,
                                 source[0], metadata=source[1], config=source[2],
                                 request_key=KEY)
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    QTest.qWait(10)
                assert entered.is_set()
                ticks.clear()
                QTest.qWait(80)
                assert len(ticks) >= 2
                assert not future.done()
            finally:
                release.set()
            future.result(timeout=10).discard()
    finally:
        release.set()
        timer.stop()


@pytest.mark.parametrize("middle_width", [410, 60])
@pytest.mark.parametrize("per_instance", [True, False])
def test_heterogeneous_middle_window_matches_existing_policy(source, monkeypatch,
                                                            middle_width, per_instance):
    from pathlib import Path
    from modules.viewer.fast import qt_viewer_bridge as qb
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer

    app = QApplication.instance() or QApplication([])
    instances = []
    for index, width in enumerate([400, middle_width, 400]):
        path = Path(source[0]) / f"still-{index}.dcm"
        _make_multiframe_dicom(path, n_frames=1, rows=16, cols=12)
        ds = pydicom.dcmread(path)
        ds.InstanceNumber = index + 1
        ds.WindowWidth, ds.WindowCenter = width, 80
        ds.PixelData = (np.arange(192, dtype=np.uint16).reshape(16, 12) + index).tobytes()
        ds.save_as(path, write_like_original=False)
        instances.append({"instance_path": str(path), "instance_number": index + 1})
    source[1]["instances"] = instances
    monkeypatch.setattr(qb, "_FAST_PER_INSTANCE_WINDOW", per_instance)
    monkeypatch.setattr(lw.Lightweight2DPipeline, "_prefetch_around", lambda *a, **k: None)
    monkeypatch.setattr(qb.QtViewerBridge, "_init_tool_controller", lambda self: None)
    monkeypatch.setattr(qb.QtViewerBridge, "_update_annotations", lambda *a, **k: None)
    presented = []
    original_set = QtSliceViewer.set_image

    def capture(self, image):
        presented.append(image.copy())
        return original_set(self, image)

    monkeypatch.setattr(QtSliceViewer, "set_image", capture)
    old = lw.Lightweight2DPipeline(config=source[2])
    new = lw.Lightweight2DPipeline(config=source[2])
    widgets, bridges = [], []
    try:
        old.open_series(source[0], metadata=source[1])
        facts = new.adopt_initial_display(prepare(source, per_instance_window=per_instance),
                                         request_key=KEY)
        for pipeline, extra in [(old, {}), (new, {"initial_display_facts": facts})]:
            widget = QtSliceViewer()
            widgets.append(widget)
            bridge = qb.QtViewerBridge(widget, pipeline, metadata=source[1], **extra)
            bridges.append(bridge)
            bridge.set_slice(1)
            bridge.apply_default_window_level(1)
        assert len(presented) == 2 and presented[0] == presented[1]
        assert old.get_window_level() == new.get_window_level()
        assert old.slice_count == new.slice_count == 3
    finally:
        for bridge in bridges:
            bridge.cleanup()
        old.shutdown()
        new.shutdown()
        for widget in widgets:
            widget.close()
            widget.deleteLater()


def test_multifile_cine_cache_survives_handoff_without_full_array_copy(source, monkeypatch):
    from pathlib import Path

    second = Path(source[0]) / "second.dcm"
    _make_multiframe_dicom(second, n_frames=12, rows=16, cols=12)
    source[1]["instances"][0]["instance_number"] = 1
    source[1]["instances"].append({"instance_path": str(second), "instance_number": 2})
    decoded_arrays = []
    original = lw.Lightweight2DPipeline._mf_ds_cache_put

    def record(self, path, ds):
        decoded_arrays.append(ds.pixel_array)
        return original(self, path, ds)

    monkeypatch.setattr(lw.Lightweight2DPipeline, "_mf_ds_cache_put", record)
    prepared = prepare(source)
    pipeline = lw.Lightweight2DPipeline(config=source[2])
    try:
        facts = pipeline.adopt_initial_display(prepared, request_key=KEY)
        assert facts.slice_index == 10
        assert pipeline.slice_count == 20
        assert len(source[1]["instances"]) == 2
        assert len(pipeline._mf_ds_cache) == 2
        for ds in pipeline._mf_ds_cache.values():
            assert any(ds.pixel_array is array for array in decoded_arrays)
        monkeypatch.setattr(pydicom, "dcmread",
                            lambda *a, **k: pytest.fail("cine dataset cache lost"))
        assert pipeline.get_pixel_array(19) is not None
    finally:
        pipeline.shutdown()


def test_changed_window_policy_rejects_prepared_bridge(source, monkeypatch):
    from modules.viewer.fast import qt_viewer_bridge as qb
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer

    app = QApplication.instance() or QApplication([])
    pipeline = lw.Lightweight2DPipeline(config=source[2])
    facts = pipeline.adopt_initial_display(prepare(source, per_instance_window=False),
                                         request_key=KEY)
    monkeypatch.setattr(qb, "_FAST_PER_INSTANCE_WINDOW", True)
    monkeypatch.setattr(qb.QtViewerBridge, "_init_tool_controller", lambda self: None)
    viewer = QtSliceViewer()
    try:
        with pytest.raises(ValueError, match="policy"):
            qb.QtViewerBridge(viewer, pipeline, metadata=source[1],
                              initial_display_facts=facts)
    finally:
        pipeline.shutdown()
        viewer.close()
        viewer.deleteLater()


def test_adoption_requires_target_owner_thread(source):
    prepared = prepare(source)
    target = lw.Lightweight2DPipeline(config=source[2])
    try:
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(target.adopt_initial_display, prepared, request_key=KEY)
            with pytest.raises(RuntimeError, match="owner thread"):
                future.result(timeout=10)
        target.adopt_initial_display(prepared, request_key=KEY)
        assert target.slice_count == 8
    finally:
        target.shutdown()
