"""Generated preview labels must not activate VTK's MathText dependency."""
import os
import subprocess
import sys

import pytest
import vtk

from modules.viewer.advanced.slice_progress import slice_counter_text


@pytest.mark.parametrize("total", [104, 0])
def test_preview_counter_uses_plain_text_backend(total):
    renderer = vtk.vtkTextRenderer.GetInstance()
    original = renderer.GetDefaultBackend()
    text = slice_counter_text(
        {"preview_only": True, "preview_total_instances": total}, 8, 1)
    assert renderer.DetectBackend(text) == renderer.FreeType
    assert renderer.GetDefaultBackend() == original


def test_cold_preview_text_render_does_not_import_matplotlib():
    code = '''
import sys
import vtk
from modules.viewer.advanced.slice_progress import slice_counter_text
assert 'matplotlib' not in sys.modules
actor = vtk.vtkTextActor()
actor.SetInput(slice_counter_text({'preview_only': True, 'preview_total_instances': 104}, 8, 1))
renderer = vtk.vtkRenderer()
renderer.AddActor(actor)
window = vtk.vtkRenderWindow()
window.SetOffScreenRendering(1)
window.SetSize(300, 80)
window.AddRenderer(renderer)
try:
    window.Render()
    assert 'matplotlib' not in sys.modules, 'preview counter activated MathText'
finally:
    window.Finalize()
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, timeout=60, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
