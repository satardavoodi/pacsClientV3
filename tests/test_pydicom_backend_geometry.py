import math
import unittest
import sys
from pathlib import Path
import types
import importlib.util
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Minimal PySide6 stubs for headless test environments.
if "PySide6" not in sys.modules:
    pyside6 = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _Signal:
        def __init__(self, *args, **kwargs):
            pass

        def emit(self, *args, **kwargs):
            pass

    class _QImage:
        pass

    qtcore.QObject = _QObject
    qtcore.Signal = _Signal
    qtgui.QImage = _QImage
    pyside6.QtCore = qtcore
    pyside6.QtGui = qtgui
    sys.modules["PySide6"] = pyside6
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui

# Build a minimal package tree so we can import backend modules without
# executing PacsClient/__init__.py in headless CI.
for pkg_name in [
    "PacsClient",
    "PacsClient.pacs",
    "PacsClient.pacs.patient_tab",
    "modules.viewer",
    "modules.viewer.backends",
]:
    if pkg_name not in sys.modules:
        pkg_mod = types.ModuleType(pkg_name)
        pkg_mod.__path__ = []  # mark as package
        sys.modules[pkg_name] = pkg_mod

contracts_name = "modules.viewer.backends.contracts"
contracts_path = ROOT_DIR / "modules" / "viewer" / "backends" / "contracts.py"
contracts_spec = importlib.util.spec_from_file_location(contracts_name, contracts_path)
contracts_mod = importlib.util.module_from_spec(contracts_spec)
sys.modules[contracts_name] = contracts_mod
contracts_spec.loader.exec_module(contracts_mod)

backend_name = "modules.viewer.backends.pydicom_2d_backend"
backend_path = ROOT_DIR / "modules" / "viewer" / "backends" / "pydicom_2d_backend.py"
backend_spec = importlib.util.spec_from_file_location(backend_name, backend_path)
backend_mod = importlib.util.module_from_spec(backend_spec)
sys.modules[backend_name] = backend_mod
backend_spec.loader.exec_module(backend_mod)

PyDicom2DBackend = backend_mod.PyDicom2DBackend
_SliceMeta = backend_mod._SliceMeta
_window_level_to_uint8 = backend_mod._window_level_to_uint8

stale_guard_name = "modules.viewer.backends.stale_frame_guard"
stale_guard_path = ROOT_DIR / "modules" / "viewer" / "backends" / "stale_frame_guard.py"
stale_guard_spec = importlib.util.spec_from_file_location(stale_guard_name, stale_guard_path)
stale_guard_mod = importlib.util.module_from_spec(stale_guard_spec)
sys.modules[stale_guard_name] = stale_guard_mod
stale_guard_spec.loader.exec_module(stale_guard_mod)
should_render_ready_slice = stale_guard_mod.should_render_ready_slice


def _slice_meta(path: str, ipp_z: float, pixel_spacing=(0.5, 0.8)) -> _SliceMeta:
    return _SliceMeta(
        path=path,
        rows=512,
        cols=512,
        pixel_spacing=pixel_spacing,  # (row_spacing_mm, col_spacing_mm)
        iop=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        ipp=(10.0, 20.0, float(ipp_z)),
        slice_thickness=1.5,
        spacing_between_slices=1.5,
        photometric="MONOCHROME2",
        bits_allocated=16,
        pixel_representation=1,
        samples_per_pixel=1,
        window_width=400.0,
        window_center=40.0,
        slope=1.0,
        intercept=0.0,
        instance_number=None,
    )


class TestPyDicom2DBackendGeometry(unittest.TestCase):
    def test_image_patient_roundtrip(self):
        backend = PyDicom2DBackend()
        backend._slices = [_slice_meta("a.dcm", ipp_z=30.0)]

        x_img = 12.0
        y_img = 7.0
        xyz = backend.image_xy_to_patient_xyz(x_img, y_img, 0)
        x_back, y_back = backend.patient_xyz_to_image_xy(xyz, 0)

        self.assertAlmostEqual(x_img, x_back, places=5)
        self.assertAlmostEqual(y_img, y_back, places=5)

    def test_spacing_driven_distance(self):
        backend = PyDicom2DBackend()
        backend._slices = [_slice_meta("a.dcm", ipp_z=30.0)]

        p0 = backend.image_xy_to_patient_xyz(0.0, 0.0, 0)
        p1 = backend.image_xy_to_patient_xyz(10.0, 20.0, 0)
        dist = math.dist(p0, p1)

        # x uses col spacing=0.8, y uses row spacing=0.5
        expected = math.sqrt((10.0 * 0.8) ** 2 + (20.0 * 0.5) ** 2)
        self.assertAlmostEqual(dist, expected, places=5)

    def test_slice_sort_uses_geometry_normal(self):
        backend = PyDicom2DBackend()
        slices = [
            _slice_meta("z5.dcm", ipp_z=5.0),
            _slice_meta("z1.dcm", ipp_z=1.0),
            _slice_meta("z3.dcm", ipp_z=3.0),
        ]

        sorted_slices = backend._sort_slices(slices)
        z_values = [s.ipp[2] for s in sorted_slices]
        self.assertEqual(z_values, [1.0, 3.0, 5.0])

    def test_spacing_100px_x_axis(self):
        backend = PyDicom2DBackend()
        spacing = (0.7, 0.7)
        backend._slices = [_slice_meta("a.dcm", ipp_z=30.0, pixel_spacing=spacing)]

        p0 = backend.image_xy_to_patient_xyz(0.0, 0.0, 0)
        p1 = backend.image_xy_to_patient_xyz(100.0, 0.0, 0)
        dist = math.dist(p0, p1)

        expected = 100.0 * float(spacing[0])
        self.assertAlmostEqual(dist, expected, places=5)

    def test_window_level_uint8_smoke(self):
        arr = np.array([-1500.0, -200.0, 0.0, 200.0, 1600.0], dtype=np.float32)
        out = _window_level_to_uint8(arr, window=400.0, level=40.0)

        self.assertEqual(out.dtype, np.uint8)
        self.assertGreaterEqual(int(out.min()), 0)
        self.assertLessEqual(int(out.max()), 255)

    def test_stale_frame_dropping_keeps_latest_slice(self):
        rendered = []
        for ready_slice in [10, 11, 12, 13]:
            if should_render_ready_slice(
                ready_slice=ready_slice,
                requested_slice=13,
                current_slice=13,
                ready_generation=5,
                current_generation=5,
            ):
                rendered.append(ready_slice)

        self.assertEqual(rendered, [13])
        self.assertFalse(
            should_render_ready_slice(
                ready_slice=13,
                requested_slice=13,
                current_slice=13,
                ready_generation=4,
                current_generation=5,
            )
        )


if __name__ == "__main__":
    unittest.main()
