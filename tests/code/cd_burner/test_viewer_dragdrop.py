"""Series drag-and-drop onto a viewport pane (headless).

QDrag.exec() is modal, so the real OS drag loop can't run under pytest —
these tests drive the two ends directly: the list builds a correct MIME
payload, and a synthetic QDropEvent on a pane routes the series to THAT
pane via the wired callback.
"""

from pydicom.uid import generate_uid
from PySide6.QtCore import QMimeData, QPoint, Qt
from PySide6.QtGui import QDropEvent

from modules.cd_burner.portable_viewer.media_scan import scan_media
from modules.cd_burner.portable_viewer.viewer_app import _SERIES_MIME

from .conftest import write_ct_slice


def _two_series(tmp_path):
    study_uid = generate_uid()
    for series_number, name in ((1, "axial"), (2, "sagittal")):
        uid = generate_uid()
        for n in (1, 2):
            write_ct_slice(
                tmp_path, uid, study_uid, n,
                filename=f"{name}{n}.dcm",
                series_number=series_number, series_description=name,
            )


def _drop_series_on_pane(canvas, series_index: int):
    mime = QMimeData()
    mime.setData(_SERIES_MIME, str(series_index).encode("ascii"))
    event = QDropEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier
    )
    canvas.dropEvent(event)
    return event


def test_series_list_is_drag_source(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        lst = window.series_list
        assert lst.dragEnabled()
        assert _SERIES_MIME in lst.mimeTypes()

        # Header rows (no UserRole) must not be draggable; series rows are.
        series_rows = [
            lst.item(r) for r in range(lst.count())
            if lst.item(r).data(Qt.UserRole) is not None
        ]
        assert len(series_rows) == 2
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_drop_loads_series_into_that_pane(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        # Default 2-view auto-distributes: pane0=series0, pane1=series1
        assert window.pane_states[0].series_index == 0
        assert window.pane_states[1].series_index == 1

        # Drop series 0 onto pane 1 → pane 1 now shows series 0 (and activates)
        _drop_series_on_pane(window.canvases[1], 0)
        assert window.pane_states[1].series_index == 0
        assert window.active_pane == 1
        assert window.canvases[1]._image is not None

        # Drop series 1 onto pane 0
        _drop_series_on_pane(window.canvases[0], 1)
        assert window.pane_states[0].series_index == 1
        assert window.active_pane == 0
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_drop_accepts_and_clears_hover(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        canvas = window.canvases[0]
        canvas._drop_hover = True
        event = _drop_series_on_pane(canvas, 1)
        assert event.isAccepted()
        assert canvas._drop_hover is False  # cleared after drop
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_drop_with_bad_payload_is_ignored(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        before = window.pane_states[1].series_index
        mime = QMimeData()
        mime.setData(_SERIES_MIME, b"not-an-int")
        event = QDropEvent(QPoint(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        window.canvases[1].dropEvent(event)
        assert not event.isAccepted()
        assert window.pane_states[1].series_index == before  # unchanged

        # Out-of-range index is rejected by the window handler
        _drop_series_on_pane(window.canvases[1], 999)
        assert window.pane_states[1].series_index == before
    finally:
        window._pool.waitForDone(3000)
        window.close()
