"""Series drag-and-drop onto a viewport pane (headless).

QDrag.exec() is modal, so the real OS drag loop can't run under pytest —
these tests drive the two ends directly: the list builds a correct MIME
payload, and a synthetic QDropEvent on a pane routes the series to THAT
pane via the wired callback.
"""

from pydicom.uid import generate_uid
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDropEvent, QMouseEvent

from modules.cd_burner.portable_viewer.media_scan import scan_media
from modules.cd_burner.portable_viewer.viewer_app import _SERIES_MIME

from .conftest import write_ct_slice


def _mouse(kind, pos, button=Qt.LeftButton, buttons=Qt.LeftButton):
    return QMouseEvent(kind, QPointF(*pos), button, buttons, Qt.NoModifier)


def _row_center(lst, series_index):
    for row in range(lst.count()):
        if lst.item(row).data(Qt.UserRole) == series_index:
            rect = lst.visualItemRect(lst.item(row))
            return (rect.center().x(), rect.center().y())
    raise AssertionError(f"series {series_index} not in list")


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


def test_series_list_mime_and_rows(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        lst = window.series_list
        assert _SERIES_MIME in lst.mimeTypes()
        series_rows = [
            lst.item(r) for r in range(lst.count())
            if lst.item(r).data(Qt.UserRole) is not None
        ]
        assert len(series_rows) == 2
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_single_click_does_not_load_until_release(tmp_path, qapp):
    """The press that could start a drag must NOT load the series. Loading
    happens only on a release with no drag (the reported bug)."""
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        window._set_active_pane(0)
        # Put a known series in pane 0 first, then click a different one.
        window._select_series_for_pane(0, 1)
        assert window.pane_states[0].series_index == 1

        lst = window.series_list
        clicked = []
        lst.seriesClicked.connect(clicked.append)
        pos = _row_center(lst, 0)

        lst.mousePressEvent(_mouse(QEvent.MouseButtonPress, pos))
        # No load on press
        assert clicked == []
        assert window.pane_states[0].series_index == 1

        lst.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, pos, buttons=Qt.NoButton))
        # Genuine click → loads series 0 into active pane 0
        assert clicked == [0]
        assert window.pane_states[0].series_index == 0
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_drag_suppresses_click_load(tmp_path, qapp, monkeypatch):
    """Moving past the threshold starts a drag and must NOT emit a click —
    so Layout 1 never receives a load while dragging toward Layout 2."""
    from PySide6.QtWidgets import QApplication
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        lst = window.series_list
        # Make the drag non-modal for the test.
        started = []
        monkeypatch.setattr(lst, "_exec_drag", lambda drag: started.append(drag))

        clicked = []
        lst.seriesClicked.connect(clicked.append)

        start = _row_center(lst, 0)
        far = (start[0] + QApplication.startDragDistance() + 40, start[1] + 60)

        lst.mousePressEvent(_mouse(QEvent.MouseButtonPress, start))
        lst.mouseMoveEvent(_mouse(QEvent.MouseMove, far))
        # Drag was started, with a real MIME payload and a preview pixmap
        assert len(started) == 1
        drag = started[0]
        assert drag.mimeData().hasFormat(_SERIES_MIME)
        assert not drag.pixmap().isNull()

        lst.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, far, buttons=Qt.NoButton))
        # Crucial: NO click-load fired because a drag happened
        assert clicked == []
    finally:
        window._pool.waitForDone(3000)
        window.close()


def test_click_on_header_row_does_nothing(tmp_path, qapp):
    from modules.cd_burner.portable_viewer.viewer_app import LiteViewerWindow

    _two_series(tmp_path)
    window = LiteViewerWindow(media_root=None, show_welcome=False)
    try:
        window._on_scan_done(scan_media(str(tmp_path)))
        lst = window.series_list
        # Find a header row (no UserRole)
        header_row = next(
            r for r in range(lst.count()) if lst.item(r).data(Qt.UserRole) is None
        )
        rect = lst.visualItemRect(lst.item(header_row))
        pos = (rect.center().x(), rect.center().y())
        clicked = []
        lst.seriesClicked.connect(clicked.append)
        lst.mousePressEvent(_mouse(QEvent.MouseButtonPress, pos))
        lst.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, pos, buttons=Qt.NoButton))
        assert clicked == []  # headers are inert
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
