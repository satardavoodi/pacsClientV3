"""Functional guard: the loading overlay is a real CHILD of the viewport in FAST
mode (clipped + correctly layered, never floating above other apps), and only falls
back to a top-level window when the anchor hosts a native VTK/OpenGL surface
(2026-06-24, overlay layering fix).

Runs offscreen (QT_QPA_PLATFORM=offscreen); needs PySide6 (present in the project
venv / the sandbox Qt lane).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_overlay_is_child_of_viewport_in_fast_mode(qapp):
    from PySide6.QtWidgets import QWidget
    from PacsClient.components.loading_overlay import AiPacsLoadingOverlay

    viewport = QWidget()
    viewport.resize(320, 240)
    ov = AiPacsLoadingOverlay(viewport, minimal=True, pass_through=True)
    try:
        assert ov._child_mode is True, "FAST viewport (no VTK) must use a child overlay"
        assert ov.parent() is viewport, "overlay must be a real child of the viewport"
        assert not ov.isWindow(), "overlay must NOT be a separate top-level window"
    finally:
        ov.deleteLater()


def test_overlay_top_level_when_native_surface_present(qapp):
    from PySide6.QtWidgets import QWidget
    from PacsClient.components.loading_overlay import AiPacsLoadingOverlay

    viewport = QWidget()
    viewport.resize(320, 240)

    # A VTK render surface is detected by class name (QVTKRenderWindowInteractor).
    class QVTKRenderWindowInteractor(QWidget):
        pass

    _vtk = QVTKRenderWindowInteractor(viewport)
    ov = AiPacsLoadingOverlay(viewport, minimal=True, pass_through=True)
    try:
        assert ov._child_mode is False, "a native VTK surface must use the top-level overlay"
        assert ov.isWindow(), "VTK fallback overlay must be a top-level window"
    finally:
        ov.deleteLater()


def test_explicit_child_mode_override(qapp):
    from PySide6.QtWidgets import QWidget
    from PacsClient.components.loading_overlay import AiPacsLoadingOverlay

    viewport = QWidget()
    viewport.resize(320, 240)

    class QVTKRenderWindowInteractor(QWidget):
        pass

    QVTKRenderWindowInteractor(viewport)
    # Caller can force child mode even with a native surface present.
    ov = AiPacsLoadingOverlay(viewport, minimal=True, pass_through=True, child_mode=True)
    try:
        assert ov._child_mode is True
        assert ov.parent() is viewport
    finally:
        ov.deleteLater()
