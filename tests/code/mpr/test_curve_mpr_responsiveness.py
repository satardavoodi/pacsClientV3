"""Non-dental Curve MPR: worker ownership, stale results and sampling parity."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
import vtkmodules.all as vtk
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_core import CurveMPRCore
from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_ui import CurveMPRWidget


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class HeadlessCurve(CurveMPRWidget):
    def _setup_main_viewer_visuals(self):
        pass

    def _update_main_viewer_visuals(self):
        pass

    def _setup_ui(self):
        self.lbl_info = QLabel(self)

    def _setup_vtk(self):
        self.presented = []
        for name in ('curved', 'ortho', 'mip'):
            setattr(self, 'image_actor_' + name, SimpleNamespace(
                SetInputData=lambda image: self.presented.append(image), SetVisibility=lambda visible: None))
            setattr(self, 'ren_' + name, SimpleNamespace(ResetCamera=lambda: None))
            setattr(self, 'vtkWidget_' + name, SimpleNamespace(
                GetRenderWindow=lambda: SimpleNamespace(Render=lambda: None)))


def pump(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()


def test_sampling_runs_off_gui_thread(app, monkeypatch):
    threads = []
    def sample(*args, **kwargs):
        threads.append(threading.get_ident())
        return None
    for method in ('generate_curved_image', 'generate_orthogonal_slice', 'generate_mip_image'):
        monkeypatch.setattr(CurveMPRCore, method, sample)
    widget = HeadlessCurve(vtk.vtkImageData())
    widget.add_point((0, 0, 0))
    widget.add_point((10, 0, 0))
    pump(app, lambda: len(threads) == 2)
    assert all(thread != threading.get_ident() for thread in threads)
    widget.close()


def test_clear_discards_inflight_result(app, monkeypatch):
    started, release = threading.Event(), threading.Event()
    def sample(*args, **kwargs):
        started.set()
        release.wait(3)
        return vtk.vtkImageData()
    monkeypatch.setattr(CurveMPRCore, 'generate_curved_image', sample)
    widget = HeadlessCurve(vtk.vtkImageData())
    try:
        widget.add_point((0, 0, 0))
        widget.add_point((10, 0, 0))
        pump(app, started.is_set)
        widget.clear_points()
        release.set()
        pump(app, lambda: getattr(widget, '_job', None) is None)
        assert all(image is None for image in widget.presented)
    finally:
        release.set()
        widget.close()


@pytest.mark.parametrize('close', [False, True])
def test_latest_path_only_and_close_during_work(app, monkeypatch, close):
    started, release = threading.Event(), threading.Event()
    calls = []
    def curved(core, **kwargs):
        if not kwargs.get('angle_degrees'):
            calls.append(len(core.control_points))
        started.set()
        release.wait(3)
        return vtk.vtkImageData()
    monkeypatch.setattr(CurveMPRCore, 'generate_curved_image', curved)
    monkeypatch.setattr(CurveMPRCore, 'generate_orthogonal_slice', lambda *a: vtk.vtkImageData())
    monkeypatch.setattr(CurveMPRCore, 'generate_mip_image', lambda *a, **kw: vtk.vtkImageData())
    widget = HeadlessCurve(vtk.vtkImageData())
    try:
        widget.add_point((0, 0, 0))
        widget.add_point((10, 0, 0))
        pump(app, started.is_set)
        widget.add_point((12, 1, 0))
        widget.add_point((14, 2, 0))
        if close:
            widget.close()
        release.set()
        pump(app, lambda: widget._job is None)
        assert calls == ([2] if close else [2, 4])
        assert len(widget.presented) == (0 if close else 2)
    finally:
        release.set()
        widget.close()


def test_worker_failure_allows_retry(app, monkeypatch):
    def fail(*args):
        raise ValueError('Synthetic failure')
    monkeypatch.setattr(CurveMPRCore, 'generate_curved_image', fail)
    widget = HeadlessCurve(vtk.vtkImageData())
    widget.add_point((0, 0, 0))
    widget.add_point((10, 0, 0))
    pump(app, lambda: widget._job is None)
    assert 'failed' in widget.lbl_info.text()
    assert not widget.presented
    for method in ('generate_curved_image', 'generate_orthogonal_slice', 'generate_mip_image'):
        monkeypatch.setattr(CurveMPRCore, method, lambda *a, **kw: vtk.vtkImageData())
    widget.update_views()
    pump(app, lambda: widget._job is None)
    assert len(widget.presented) == 2
    widget.close()


def test_deletion_cancels_worker_without_deleted_qt_access(app, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    started, release = threading.Event(), threading.Event()
    def sample(*args, **kwargs):
        started.set()
        release.wait(3)
        return None
    monkeypatch.setattr(CurveMPRCore, 'generate_curved_image', sample)
    widget = HeadlessCurve(vtk.vtkImageData())
    try:
        widget.add_point((0, 0, 0))
        widget.add_point((10, 0, 0))
        pump(app, started.is_set)
        job = widget._job
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        assert job.cancelled.is_set()
    finally:
        release.set()
        assert QThreadPool.globalInstance().waitForDone(5000)


def test_duplicate_click_does_not_make_zero_spacing_image(app):
    widget = HeadlessCurve(vtk.vtkImageData())
    widget.add_point((1, 2, 3))
    widget.add_point((1, 2, 3))
    assert len(widget.core.control_points) == 1
    assert widget._job is None
    widget.close()
    widget.add_point((10, 2, 3))
    assert len(widget.core.control_points) == 1


def test_toolbar_uses_display_volume_without_unused_vrt():
    """Guard the assembly boundary; geometry itself remains owned by Standard MPR."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path('PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py').read_text(encoding='utf-8'))
    route = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'toggle_new_curve_mpr')
    calls = [node for node in ast.walk(route) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    viewer = next(node for node in calls if node.func.id == 'StandardMPRViewer')
    assert ast.literal_eval(next(kw.value for kw in viewer.keywords if kw.arg == 'layout_views')) == ['axial', 'sagittal', 'coronal']
    curve = next(node for node in calls if node.func.id == 'CurveMPRWidget')
    assert ast.unparse(curve.args[0]) == 'zeta_widget.image_data'


def reference_points(core, width, height, physical_width, z_offset=0):
    """Legacy scalar-loop coordinates, including vtkPoints float32 storage."""
    points = []
    for j in range(height):
        offset = j * physical_width / max(1, height - 1) - physical_width / 2
        for i in range(width):
            s = i * core.total_length / max(1, width - 1)
            idx = 0
            while idx < len(core.arc_lengths) - 1 and core.arc_lengths[idx + 1] < s:
                idx += 1
            a, b = core.frames[idx], core.frames[min(idx + 1, len(core.frames) - 1)]
            delta = core.arc_lengths[min(idx + 1, len(core.frames) - 1)] - core.arc_lengths[idx]
            t = (s - core.arc_lengths[idx]) / delta if delta > 0 else 0
            origin = a[0] + t * (b[0] - a[0])
            normal = a[2] + t * (b[2] - a[2])
            normal /= np.linalg.norm(normal)
            binormal = a[3] + t * (b[3] - a[3])
            binormal /= np.linalg.norm(binormal)
            points.append(origin + offset * normal + z_offset * binormal)
    return np.asarray(points, dtype=np.float32)


@pytest.mark.parametrize('width,height', [(1, 1), (17, 13)])
def test_vector_sampling_preserves_legacy_pixels(width, height):
    volume = vtk.vtkImageData()
    volume.SetDimensions(40, 40, 40)
    volume.SetOrigin(-20, -20, -20)
    values = np.arange(40 ** 3, dtype=np.float32)
    volume.GetPointData().SetScalars(numpy_to_vtk(values, deep=True))
    core = CurveMPRCore(volume)
    for point in ((-5, -2, 0), (0, 3, 1), (5, -1, 2)):
        core.add_control_point(point)
    def probe(offset):
        points = vtk.vtkPoints()
        points.SetData(numpy_to_vtk(reference_points(core, width, height, 6, offset), deep=True))
        poly = vtk.vtkPolyData()
        poly.SetPoints(points)
        sampler = vtk.vtkProbeFilter()
        sampler.SetInputData(poly)
        sampler.SetSourceData(volume)
        sampler.Update()
        return vtk_to_numpy(sampler.GetOutput().GetPointData().GetScalars()).copy()
    curved = core.generate_curved_image(width, height, 6)
    mip = core.generate_mip_image(width, height, 6, 4, 3)
    np.testing.assert_array_equal(vtk_to_numpy(curved.GetPointData().GetScalars()), probe(0))
    np.testing.assert_array_equal(vtk_to_numpy(mip.GetPointData().GetScalars()), np.maximum.reduce([probe(s) for s in (-2, 0, 2)]))
    assert curved.GetOrigin() == (0, -3, 0)
    assert curved.GetSpacing() == (core.total_length / max(1, width - 1), 6 / max(1, height - 1), 1)


def test_source_plane_selection_reuses_views_and_clears_previous_path():
    from PySide6.QtWidgets import QApplication, QWidget, QGridLayout
    from PySide6.QtCore import QEvent
    from types import SimpleNamespace
    app = QApplication.instance() or QApplication([])
    class SourcePane(QWidget):
        def __init__(self, parent):
            super().__init__(parent)
            self.style = vtk.vtkInteractorStyleImage()
        def GetInteractorStyle(self):
            return self.style
        def GetRenderWindow(self):
            return SimpleNamespace(Render=lambda: None)
    host = QWidget()
    host._views_layout = QGridLayout(host)
    host._view_containers, host.viewers = {}, {}
    for i, (name, normal) in enumerate(zip(('axial', 'sagittal', 'coronal'), ((0,0,1),(1,0,0),(0,1,0)))):
        pane = SourcePane(host)
        renderer = vtk.vtkRenderer()
        renderer.GetActiveCamera().SetPosition(normal)
        renderer.GetActiveCamera().SetFocalPoint(0,0,0)
        host._view_containers[name] = pane
        host.viewers[name] = {'widget': pane, 'renderer': renderer}
        host._views_layout.addWidget(pane, 0, i)
    widget = HeadlessCurve(vtk.vtkImageData(), main_viewer=host)
    widget.install_source_views()
    assert widget.source_stack.count() == 3
    for i, name in enumerate(('axial', 'sagittal', 'coronal')):
        widget.add_point((1,2,3))
        widget._set_source_view(name)
        assert widget.source_stack.currentIndex() == i
        assert not widget.core.control_points
        np.testing.assert_allclose(widget._reference_normal(), ((0,0,1),(1,0,0),(0,1,0))[i])
        assert widget.eventFilter(host.viewers[name]['widget'], QEvent(QEvent.MouseButtonDblClick))
    helpers = list(widget._source_helpers)
    widget.cleanup()
    assert all(not hasattr(helper, 'observer_id') for helper in helpers)
    host.close()


def test_orbit_keeps_presenting_completed_frames_while_more_input_arrives(app, monkeypatch):
    started, release, finish = threading.Event(), threading.Event(), threading.Event()
    calls = []
    def sample(*args, **kwargs):
        calls.append(kwargs.get('angle_degrees'))
        started.set()
        (release if len(calls) <= 2 else finish).wait(3)
        return vtk.vtkImageData()
    monkeypatch.setattr(CurveMPRCore, 'generate_curved_image', sample)
    widget = HeadlessCurve(vtk.vtkImageData())
    try:
        widget.add_point((0, 0, 0)); widget.add_point((10, 0, 0))
        pump(app, started.is_set)
        job = widget._job
        revision = widget._revision
        widget._set_orbit_angle(5)
        widget._set_orbit_angle(10)
        assert not job.cancelled.is_set()
        assert widget._revision == revision
        assert widget._pending
        release.set()
        pump(app, lambda: len(widget.presented) == 2 and len(calls) >= 3)
        assert widget._job is not None  # Next angle is still running, yet a pair is visible.
        assert calls[:3] == [0, 90, 10]
    finally:
        release.set(); finish.set()
        pump(app, lambda: widget._job is None)
        widget.close()


def test_curve_input_requests_standard_anatomical_preparation():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py').read_text(encoding='utf-8'))
    route = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'toggle_new_curve_mpr')
    preparation = next(n for n in ast.walk(route) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == '_prepare_mpr_flip_offthread')
    assert any(k.arg == 'canonicalize_source' and ast.literal_eval(k.value) is True for k in preparation.keywords)


def test_curve_preparation_matches_standard_on_worker_and_keeps_source(app, monkeypatch):
    import ast
    import logging
    from pathlib import Path
    from modules.mpr.zeta_mpr import _mpr_canonicalize as canonical
    from modules.mpr.zeta_mpr.mpr_viewer.widget import StandardMPRViewer
    source = vtk.vtkImageData()
    source.SetDimensions(4, 5, 6)
    values = np.arange(120, dtype=np.int16)
    source.GetPointData().SetScalars(numpy_to_vtk(values, deep=True))
    direction = numpy_to_vtk(np.eye(4).ravel(), deep=True)
    direction.SetName('DirectionMatrix')
    source.GetFieldData().AddArray(direction)
    threads = []
    monkeypatch.setattr(canonical, 'canonicalize_enabled', lambda: True)
    monkeypatch.setattr(canonical, 'probe', lambda *a: None)
    def slice_axis(*args):
        threads.append(threading.get_ident())
        return [0, 0, 1]
    monkeypatch.setattr(canonical, '_read_dicom_slice_axis_sign', slice_axis)
    expected = StandardMPRViewer.build_lr_flipped_volume(canonical.canonicalize_volume(source))
    threads.clear()
    path = Path('PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_prepare_mpr_flip_offthread')
    ns = {'logger': logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
    parent = QWidget()
    actual = ns[fn.name](SimpleNamespace(patient_widget=parent), source, canonicalize_source=True)
    assert actual is not None
    assert threads and all(t != threading.get_ident() for t in threads)
    np.testing.assert_array_equal(vtk_to_numpy(actual.GetPointData().GetScalars()), vtk_to_numpy(expected.GetPointData().GetScalars()))
    np.testing.assert_array_equal(vtk_to_numpy(actual.GetFieldData().GetArray('ZetaAnatA')), vtk_to_numpy(expected.GetFieldData().GetArray('ZetaAnatA')))
    assert source.GetFieldData().GetArray('ZetaAnatA') is None
    np.testing.assert_array_equal(vtk_to_numpy(source.GetPointData().GetScalars()), values)
    parent.close()
