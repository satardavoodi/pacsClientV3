import ast
from pathlib import Path
from unittest.mock import Mock
from PySide6 import QtCore, QtGui, QtWidgets


def test_presenter_and_collapse_reclaim_height_without_losing_selection():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    path=Path('modules/education/educational_patient_viewer_widget.py')
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    names={'center_layout_ui','_build_footer','_set_dock_collapsed'}
    methods=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in names]
    class Host(QtWidgets.QWidget):
        course_data={'author_name':'Dr. Synthetic Teacher, MD'}
        def _build_media_page(self):return QtWidgets.QWidget()
        def noop(self, *args): pass
        _show_course_overview=noop;_show_slide_review=noop;_previous_slide=noop;_next_slide=noop
        _toggle_session_timer=noop;_reset_session_timer=noop;_on_slide_selected=noop;_on_item_clicked=noop
    ns={'Host':Host}
    for module in (QtCore,QtGui,QtWidgets):ns.update({k:getattr(module,k) for k in dir(module) if not k.startswith('__')})
    cls=ast.ClassDef(name='TestHost',bases=[ast.Name(id='Host',ctx=ast.Load())],keywords=[],body=methods,decorator_list=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),str(path),'exec'),ns)
    host=ns['TestHost']();layout=QtWidgets.QVBoxLayout(host);layout.addWidget(host.center_layout_ui())
    host.slides_list.addItems(['First','Second']);host.slides_list.setCurrentRow(1)
    host.resize(1500,850);host.show()
    for _ in range(3):app.processEvents()
    expanded=host.education_content_stack.height()
    assert 'Dr. Synthetic Teacher, MD' in host.presenter_label.text()
    host.dock_toggle_btn.click()
    for _ in range(3):app.processEvents()
    assert host.dock_body.isHidden()
    assert host.education_content_stack.height()>expanded+100
    assert host.slides_list.currentRow()==1
    assert host.dock_toggle_btn.text()=='Show slides'
    host.dock_toggle_btn.click()
    for _ in range(3):app.processEvents()
    assert not host.dock_body.isHidden() and host.slides_list.currentRow()==1
    host.close()


def test_video_error_keeps_sink_and_reuses_single_error_label(tmp_path):
    from modules.education.video_slide_widget import VideoSlideWidget
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget=VideoSlideWidget(str(tmp_path/'absent.mp4'))
    sink=widget.video_widget
    assert widget.layout().indexOf(sink)>=0
    widget.show_error('Second failure')
    assert widget.layout().indexOf(sink)>=0
    assert len([w for w in widget.findChildren(QtWidgets.QLabel) if w.objectName()=='videoPlaybackError'])==1
    widget.cleanup();widget.close()


def test_real_video_frames_recover_after_error_and_pause(tmp_path):
    import time
    import cv2
    import numpy as np
    from modules.education.video_slide_widget import VideoSlideWidget
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtTest import QTest
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    path = tmp_path / "synthetic.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 64))
    assert writer.isOpened()
    for i in range(30):
        writer.write(np.full((64, 64, 3), i * 8, dtype=np.uint8))
    writer.release()
    widget = VideoSlideWidget(str(tmp_path / "missing.mp4"))
    frames = []
    widget.video_widget.videoSink().videoFrameChanged.connect(lambda frame: frames.append(frame.isValid()))
    widget.resize(640, 480)
    widget.show()
    def wait_for(predicate):
        deadline = time.monotonic() + 10
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(25)
        assert predicate()
    try:
        widget.set_video(str(path), autoplay=True)
        wait_for(lambda: any(frames))
        assert widget.error_label.isHidden()
        widget.pause_only()
        assert widget.player.playbackState() == QMediaPlayer.PausedState
        widget.show_error("Synthetic failure")
        frames.clear()
        widget.set_video(str(path), autoplay=True)
        wait_for(lambda: any(frames))
        assert not widget.video_widget.isHidden()
        assert widget.error_label.isHidden()
    finally:
        widget.cleanup()
        widget.close()
