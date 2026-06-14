"""Regression guard: every production switch_series override must accept the
``force_reload`` kwarg (Eagle Eye, 2026-06-14).

The "manual drag-drop always wins" change (commit 535732e) added a ``force_reload``
keyword that the shared switch pipeline
(``_vc_switch._perform_series_switch_optimized``) passes to ``switch_series`` on
the active viewport. Two overrides were updated (QtFastContainer, base VTKWidget)
but **AIVTKWidget** (the Eagle Eye / AI-imaging viewport) was not — so every
series load into the Eagle Eye viewport raised

    AIVTKWidget.switch_series() got an unexpected keyword argument 'force_reload'

and the image never appeared ("can't import the series into the viewport").

This guard pins the kwarg on EVERY production ``switch_series`` override so the
same regression cannot recur on another viewport (FAST, VTK, legacy, the
NodeViewer wrapper, or the AI override).
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

# Every production switch_series override reachable from the shared switch
# pipeline (directly, or via the NodeViewer wrapper that forwards to it).
FILES = [
    "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py",
    "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_series.py",
    "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_legacy_widget.py",
    "PacsClient/pacs/patient_tab/utils/node_viewer.py",
    "modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py",
]


def _switch_series_sigs(src):
    # Capture each 'def switch_series(...)':  the signature may span lines.
    return re.findall(r"def switch_series\s*\((.*?)\)\s*:", src, re.DOTALL)


@pytest.mark.parametrize("rel", FILES)
def test_switch_series_accepts_force_reload(rel):
    src = (REPO / rel).read_text(encoding="utf-8", errors="ignore")
    sigs = _switch_series_sigs(src)
    assert sigs, f"no switch_series def found in {rel}"
    for sig in sigs:
        assert "force_reload" in sig, (
            f"{rel}: a switch_series override is missing the force_reload kwarg the "
            f"shared switch pipeline passes -> TypeError at runtime (the series never "
            f"loads). Signature captured: {sig!r}"
        )


def test_ai_override_forwards_force_reload_to_super():
    """AIVTKWidget delegates to super().switch_series — it must FORWARD
    force_reload, not just accept it, or the base no-op gate is bypassed."""
    src = (REPO / "modules/ai_imaging/ai_module_ui/overrides/vtk_widget.py").read_text(encoding="utf-8")
    assert "super().switch_series(" in src
    assert "force_reload=force_reload" in src


def test_node_viewer_forwards_force_reload():
    """The NodeViewer wrapper must forward force_reload to the concrete viewer."""
    src = (REPO / "PacsClient/pacs/patient_tab/utils/node_viewer.py").read_text(encoding="utf-8")
    assert "force_reload=force_reload" in src
