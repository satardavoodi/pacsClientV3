# -*- coding: utf-8 -*-
"""Guard: Dental Imaging drop path force-decodes the lazy volume (2026-06-23).

Root cause it pins: a series DROPPED onto the Dental Imaging workspace is bound via
``PyDicomLazyVolume.from_series``, which returns a LAZY volume (zero-filled memmap,
slices decoded on demand). The dental previews read the middle slices immediately, so
without a full decode the Axial preview is blank / the volume is ~all zeros ("series
not imported correctly"). ``materialize_lazy_volume`` force-decodes every slice and
refreshes VTK; the active-viewer reuse path (already decoded) is untouched.

Pure unit test of the helper with a fake lazy object (no Qt/VTK/pydicom) + a source-pin
that the binder calls it behind the default-on flag.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BINDER = REPO / "modules" / "dental_imaging" / "core" / "volume_binder.py"
PW_ADVANCED = (
    REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_widget_core" / "_pw_advanced.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace")


def _load_binder():
    # Load volume_binder.py in isolation under a UNIQUE synthetic package so we do
    # NOT pollute the real ``modules.dental_imaging.core`` in sys.modules (that would
    # make sibling tests import a stub). Stub only the sibling ``.volume`` import.
    import sys
    import types

    pkg = "dental_binder_isolated_test"
    m = types.ModuleType(pkg)
    m.__path__ = []  # mark as package
    sys.modules[pkg] = m
    volmod = types.ModuleType(pkg + ".volume")
    volmod.DentalVolume = object
    sys.modules[pkg + ".volume"] = volmod
    spec = importlib.util.spec_from_file_location(pkg + ".volume_binder", BINDER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg + ".volume_binder"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeLazy:
    def __init__(self, n, fail_at=None):
        self.slice_count = n
        self.loaded = []
        self.refreshed = False
        self._fail_at = fail_at

    def _load_slice_blocking(self, idx, emit_signal=True):
        assert emit_signal is False  # dental must not emit UI signals
        if self._fail_at is not None and idx >= self._fail_at:
            raise RuntimeError("decode boom")
        self.loaded.append(idx)
        return True

    def mark_vtk_modified(self):
        self.refreshed = True


def test_materialize_decodes_all_slices_and_refreshes():
    b = _load_binder()
    lazy = _FakeLazy(111)
    n = b.materialize_lazy_volume(lazy)
    assert n == 111
    assert lazy.loaded == list(range(111))  # every slice, in order
    assert lazy.refreshed is True           # VTK scalars refreshed after decode


def test_materialize_is_guarded():
    b = _load_binder()
    assert b.materialize_lazy_volume(None) == 0
    assert b.materialize_lazy_volume(object()) == 0  # no _load_slice_blocking → 0
    # partial decode failure: stops, still refreshes, returns what loaded
    lazy = _FakeLazy(50, fail_at=10)
    n = b.materialize_lazy_volume(lazy)
    assert n == 10 and lazy.refreshed is True


def test_materialize_respects_max_slices_cap():
    b = _load_binder()
    lazy = _FakeLazy(10_000)
    n = b.materialize_lazy_volume(lazy, max_slices=64)
    assert n == 64


def test_binder_drop_path_calls_force_decode():
    s = _read(PW_ADVANCED)
    assert "materialize_lazy_volume" in s
    assert "AIPACS_DENTAL_FORCE_DECODE" in s
    # called on the from_series result, before wrapping in DentalVolume
    assert "PyDicomLazyVolume.from_series" in s
