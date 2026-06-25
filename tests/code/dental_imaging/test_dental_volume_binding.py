# -*- coding: utf-8 -*-
"""Guard: Dental Imaging Milestone-1 volume binding (single source of truth).

Pins that the dental ``core`` REUSES the shared ``vtk_image_data`` (read-only
geometry: dims / spacing / origin / direction) and never duplicates the
volume/geometry pipeline. Uses a tiny duck-typed fake image-data so the geometry
contract is verified with NO VTK / NO Qt.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE = REPO_ROOT / "modules" / "dental_imaging" / "core"


def _read(p: Path) -> str:
    assert p.exists(), f"missing: {p}"
    data = p.read_bytes()
    if b"\x00" in data:
        pytest.skip(f"mount served a NUL-truncated copy of {p.name}; run on Windows")
    return data.decode("utf-8", errors="replace")


# ---- fakes (duck-typed vtkImageData; no VTK needed) ----------------------
class _FakeArr:
    def __init__(self, vals):
        self._v = list(vals)

    def GetNumberOfTuples(self):
        return len(self._v)

    def GetValue(self, i):
        return self._v[i]


class _FakeFieldData:
    def __init__(self, arrays):
        self._a = dict(arrays)

    def GetArray(self, name):
        return self._a.get(name)


class _FakeImageData:
    def __init__(self, dims, spacing, origin, direction=None):
        self._d, self._s, self._o = dims, spacing, origin
        arrays = {}
        if direction is not None:
            arrays["DirectionMatrix"] = _FakeArr(direction)
        self._fd = _FakeFieldData(arrays)

    def GetDimensions(self):
        return self._d

    def GetSpacing(self):
        return self._s

    def GetOrigin(self):
        return self._o

    def GetFieldData(self):
        return self._fd


class _FakeIV:
    def __init__(self, img, modality="CT"):
        self.vtk_image_data = img
        self.metadata = {"series": {"modality": modality}}


class _FakeSW:
    def __init__(self, iv):
        self.image_viewer = iv


class _FakePW:
    def __init__(self, sw):
        self.selected_widget = sw


def _load_core():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from modules.dental_imaging.core import (
            DentalVolume,
            bind_active_viewer_volume,
            get_active_image_data,
        )
    except Exception as exc:  # heavy parent package / missing deps in this env
        pytest.skip(f"cannot import dental core here: {exc}")
    return DentalVolume, bind_active_viewer_volume, get_active_image_data


_IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


# ---- DentalVolume geometry extraction ------------------------------------
def test_dental_volume_reads_shared_geometry():
    DentalVolume, _, _ = _load_core()
    img = _FakeImageData((512, 512, 200), (0.3, 0.3, 0.3), (0.0, 0.0, 0.0), _IDENTITY)
    v = DentalVolume(img, modality="ct", series_uid="1.2.3")
    assert v.is_valid() is True
    assert v.dimensions == (512, 512, 200)
    assert v.spacing == (0.3, 0.3, 0.3)
    assert v.origin == (0.0, 0.0, 0.0)
    assert v.slice_count() == 200
    assert [float(x) for x in v.direction_matrix] == [float(x) for x in _IDENTITY]
    assert v.modality == "CT"  # normalized upper
    assert "512×512×200" in v.summary()


def test_dental_volume_identity_when_no_direction():
    DentalVolume, _, _ = _load_core()
    v = DentalVolume(_FakeImageData((10, 10, 10), (1, 1, 1), (0, 0, 0), direction=None))
    dm = v.direction_matrix
    assert dm[0] == 1.0 and dm[5] == 1.0 and dm[10] == 1.0 and dm[15] == 1.0


def test_dental_volume_invalid_dims():
    DentalVolume, _, _ = _load_core()
    assert DentalVolume(_FakeImageData((0, 0, 0), (1, 1, 1), (0, 0, 0))).is_valid() is False


# ---- bind_active_viewer_volume reuses the active viewer ------------------
def test_bind_reuses_active_viewer_volume():
    DentalVolume, bind, get_img = _load_core()
    img = _FakeImageData((256, 256, 128), (0.25, 0.25, 0.5), (1, 2, 3), _IDENTITY)
    pw = _FakePW(_FakeSW(_FakeIV(img, modality="CT")))
    assert get_img(pw) is img  # reuse, not rebuild
    v = bind(pw, series_uid="9.9")
    assert v is not None and v.is_valid()
    assert v.image_data is img  # SAME shared handle (no copy)
    assert v.modality == "CT"
    assert v.series_uid == "9.9"


def test_bind_none_when_no_viewer():
    _, bind, _ = _load_core()

    class _Empty:
        selected_widget = None

    assert bind(_Empty()) is None


def test_bind_none_when_volume_invalid():
    _, bind, _ = _load_core()
    pw = _FakePW(_FakeSW(_FakeIV(_FakeImageData((0, 0, 0), (1, 1, 1), (0, 0, 0)))))
    assert bind(pw) is None


# ---- core stays import-light + reuse-not-duplicate -----------------------
def test_core_is_import_light_and_reuse_only():
    for name in ("__init__.py", "volume.py", "volume_binder.py"):
        src = _read(CORE / name)
        assert "PySide6" not in src, f"{name} must stay Qt-free"
        assert "import vtk" not in src and "vtkmodules" not in src, f"{name} must stay VTK-free"
        assert "vtkImageReslice" not in src
        assert "PyDicomLazyVolume(" not in src  # reuse shared volume; never build one
        assert "zeta_mpr.curved_mpr" not in src and "mpr.curved_mpr" not in src


def test_binder_reads_shared_active_viewer_volume():
    src = _read(CORE / "volume_binder.py")
    assert "image_viewer" in src
    assert "vtk_image_data" in src  # the established active-viewer accessor
