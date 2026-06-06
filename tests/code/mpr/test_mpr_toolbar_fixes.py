"""Guard tests for the MPR toolbar fixes (2026-06-06).

Pins four behaviors:
  1. StandardMPRViewer exposes the public W/L API the main-toolbar preset
     dropdown calls (set_window_level / apply_default_window_level /
     get_window_level) — without it, CT presets silently no-op in MPR.
  2. apply_default_window_level restores the AS-OPENED (inherited) W/L.
  3. The oblique orthogonal-reset path restores the INITIAL W/L, not the
     range-based invented default (~400/40 ≈ Abdomen) that silently changed
     the user's preset.
  4. Per-viewport crosshair visibility: hiding one pane never touches the
     others; the global Crosshairs switch overrides per-pane hides.

Headless-safe: mixin methods run on plain fakes — no QApplication, no VTK
render windows (module import only).
"""
import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.mpr.zeta_mpr.mpr_viewer._mpr_orientation import _MprOrientationMixin  # noqa: E402
from modules.mpr.zeta_mpr.mpr_viewer._mpr_oblique import _MprObliqueMixin  # noqa: E402
from modules.mpr.zeta_mpr.mpr_viewer._mpr_crosshair_state import _MprCrosshairStateMixin  # noqa: E402


# ---------------------------------------------------------------- fakes ----

class _FakeProp:
    def __init__(self):
        self.window = None
        self.level = None

    def SetColorWindow(self, w):
        self.window = w

    def SetColorLevel(self, l):
        self.level = l

    def GetColorWindow(self):
        return self.window

    def GetColorLevel(self):
        return self.level


class _FakeActor:
    def __init__(self):
        self._prop = _FakeProp()
        self.visible = True

    def GetProperty(self):
        return self._prop

    def VisibilityOn(self):
        self.visible = True

    def VisibilityOff(self):
        self.visible = False


class _WLHost(_MprOrientationMixin):
    """Minimal host for the W/L API: three panes with fake actors."""

    def __init__(self, initial=(1500.0, -600.0)):
        self.viewers = {
            name: {'actor': _FakeActor()} for name in ('axial', 'sagittal', 'coronal')
        }
        self._initial_window_level = initial
        self.scalar_range = (-1024.0, 3071.0)  # CT-like → default would be 400/40
        self.rendered = []

    def _request_render(self, view_name):
        self.rendered.append(view_name)


class _CrosshairHost(_MprCrosshairStateMixin):
    """Minimal host for per-view crosshair visibility."""

    def __init__(self):
        self.crosshair_actors = {
            name: {
                'h_line_actor': _FakeActor(),
                'v_line_actor': _FakeActor(),
                'handles': [{'actor': _FakeActor()}],
            }
            for name in ('axial', 'sagittal', 'coronal')
        }
        self.crosshairs_enabled = True
        self.crosshair_interaction_enabled = True
        self._toolbar_active_tool = None
        self._crosshair_view_buttons = {}
        self.interaction_log = []

    def _enable_crosshair_interaction(self, view_name):
        self.interaction_log.append(('enable', view_name))

    def _disable_crosshair_interaction(self, view_name):
        self.interaction_log.append(('disable', view_name))

    def _request_render(self, view_name):
        pass

    def _visible(self, view):
        a = self.crosshair_actors[view]
        return a['h_line_actor'].visible and a['v_line_actor'].visible


# ------------------------------------------------------------- W/L API ----

def test_set_window_level_applies_to_all_2d_panes():
    host = _WLHost()
    host.set_window_level(2000, 500)  # toolbar "Bone" preset
    for name in ('axial', 'sagittal', 'coronal'):
        prop = host.viewers[name]['actor'].GetProperty()
        assert prop.GetColorWindow() == 2000.0
        assert prop.GetColorLevel() == 500.0
    assert set(host.rendered) == {'axial', 'sagittal', 'coronal'}


def test_set_window_level_ignores_invalid_values():
    host = _WLHost()
    host.set_window_level(None, 'x')
    assert host.viewers['axial']['actor'].GetProperty().GetColorWindow() is None


def test_apply_default_window_level_restores_inherited_wl():
    host = _WLHost(initial=(1500.0, -600.0))  # opened from a Lung viewer
    host.set_window_level(400, 40)            # user picked Abdomen
    host.apply_default_window_level()         # toolbar "Default Preset"
    prop = host.viewers['axial']['actor'].GetProperty()
    assert (prop.GetColorWindow(), prop.GetColorLevel()) == (1500.0, -600.0)


def test_get_window_level_reads_displayed_values():
    host = _WLHost()
    host.set_window_level(80, 40)
    assert host.get_window_level() == (80.0, 40.0)


def test_initial_wl_fallback_only_when_nothing_inherited():
    host = _WLHost(initial=None)
    # CT-like scalar range → legacy computed default (the 400/40 fallback)
    assert host._get_initial_window_level() == (400, 40)
    host._initial_window_level = (1500.0, -600.0)
    assert host._get_initial_window_level() == (1500.0, -600.0)


def test_oblique_orthogonal_reset_uses_initial_not_default_wl():
    src = inspect.getsource(_MprObliqueMixin._reset_all_to_orthogonal)
    code_lines = [
        line.split('#', 1)[0] for line in src.splitlines()
    ]  # strip comments — only real calls count
    code = '\n'.join(code_lines)
    assert 'self._get_initial_window_level()' in code, (
        "orthogonal reset must restore the inherited W/L"
    )
    assert 'self._get_default_window_level()' not in code, (
        "orthogonal reset must NOT re-apply the invented range-based default "
        "(~400/40) — that silently changed the user's preset (e.g. Lung→Abdomen)"
    )


# --------------------------------------------------- per-view crosshair ----

def test_hide_crosshair_in_one_pane_keeps_others_visible():
    host = _CrosshairHost()
    host.set_view_crosshair_visible('sagittal', False)
    assert not host._visible('sagittal')
    assert host._visible('axial')
    assert host._visible('coronal')
    assert ('disable', 'sagittal') in host.interaction_log


def test_toggle_view_crosshair_flips_state():
    host = _CrosshairHost()
    host.toggle_view_crosshair('axial')
    assert not host._visible('axial')
    host.toggle_view_crosshair('axial')
    assert host._visible('axial')
    assert ('enable', 'axial') in host.interaction_log


def test_global_toggle_overrides_per_view_hides():
    host = _CrosshairHost()
    host.set_view_crosshair_visible('coronal', False)
    assert host._crosshair_hidden_views == {'coronal'}
    host._toggle_crosshairs(True)  # global ON → show everywhere again
    assert host._crosshair_hidden_views == set()
    assert host._visible('coronal')


def test_global_off_keeps_all_panes_hidden_even_if_view_marked_visible():
    host = _CrosshairHost()
    host._toggle_crosshairs(False)
    host.set_view_crosshair_visible('axial', True)  # global wins
    assert not host._visible('axial')


def test_active_toolbar_tool_blocks_interaction_changes_but_not_visibility():
    host = _CrosshairHost()
    host._toolbar_active_tool = 'ZOOM'
    host.interaction_log.clear()
    host.set_view_crosshair_visible('axial', False)
    assert not host._visible('axial')
    assert host.interaction_log == []  # interactor untouched while a tool owns it


# ------------------------------------------- overlay / layering (2026-06-06) ----

def test_is_near_measurement_safe_defaults():
    """Non-destructive hit test: False on empty/unknown views, no renderer."""
    from modules.mpr.zeta_mpr.mpr_measurement_tools import MPRMeasurementTools

    class _FakeViewer:
        viewers = {}

    mt = MPRMeasurementTools(_FakeViewer())
    assert mt.is_near_measurement('axial', (10, 10), renderer=None) is False
    assert mt.is_near_measurement('nope', (10, 10), renderer=object()) is False
    assert mt.is_near_measurement('axial', (10, 10), renderer=object()) is False


def test_crosshair_style_yields_to_annotations_on_press():
    """The style must consult is_near_measurement BEFORE any crosshair grab."""
    from modules.mpr.zeta_mpr.mpr_viewer._mpr_crosshair_interact import (
        CrosshairInteractorStyle,
    )
    src = inspect.getsource(CrosshairInteractorStyle.on_left_button_press)
    code = '\n'.join(line.split('#', 1)[0] for line in src.splitlines())
    assert 'is_near_measurement' in code, (
        "annotation body clicks must not start crosshair/stack drags"
    )
    pos_guard = code.index('is_near_measurement')
    for grab in ('rotation_enabled', 'dragging_center', '_distance_to_line_segment'):
        assert grab in code and code.index(grab) > pos_guard, (
            f"annotation guard must run before crosshair grab logic ({grab})"
        )


def test_crosshair_toggle_button_is_native_child_of_pane():
    """Overlay button: native child of the GL pane, else it paints BEHIND
    the image (native HWND covers non-native siblings on Windows)."""
    from modules.mpr.zeta_mpr.mpr_viewer._mpr_layout import _MprLayoutMixin
    src = inspect.getsource(_MprLayoutMixin._add_view_crosshair_toggle)
    assert 'QPushButton("✛", pane_widget)' in src
    assert 'WA_NativeWindow' in src
    reg = inspect.getsource(_MprLayoutMixin._register_view)
    code = '\n'.join(line.split('#', 1)[0] for line in reg.splitlines())
    assert '_add_view_crosshair_toggle(view_name, vtk_widget)' in code
