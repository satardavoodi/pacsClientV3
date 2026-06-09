"""Guard: turning crosshairs OFF in MPR must keep the LEFT mouse button on STACK
(its prior function) — it must NOT switch to window/level (2026-06-09).

Root cause was `_disable_crosshair_interaction` installing a fresh
`vtkInteractorStyleImage`, whose DEFAULT left button is window/level. The fix
keeps the view's `CrosshairInteractorStyle` (left=stack, right=WL, middle=zoom,
wheel=scroll) and gates crosshair GRABBING off via `_crosshair_grab_active`, so
left-drag routes to stack while crosshairs are hidden/disabled.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_CROSSHAIR = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
              / "_mpr_crosshair_interact.py")
_STATE = (_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer"
          / "_mpr_crosshair_state.py")


def _method_slice(src: str, name: str) -> str:
    start = src.index(f"def {name}")
    nxt = src.index("\n    def ", start + 1)
    return src[start:nxt]


def _load_method(path, name):
    block = _method_slice(path.read_text(encoding="utf-8", errors="ignore"), name)
    fn_src = "    " + block.rstrip() + "\n"
    ns = {}
    exec("class _H:\n" + fn_src, ns)  # noqa: S102 — test-local exec of repo source
    return ns["_H"]


class _Parent:
    pass


class _Stub:
    def __init__(self, **kw):
        self.parent = _Parent()
        for k, v in kw.items():
            setattr(self.parent, k, v)
        self.view_name = "axial"


def test_grab_active_true_only_when_crosshairs_on_and_visible():
    H = _load_method(_CROSSHAIR, "_crosshair_grab_active")
    s = _Stub(crosshairs_enabled=True, crosshair_interaction_enabled=True,
              _crosshair_hidden_views=set())
    assert H._crosshair_grab_active(s) is True


def test_grab_inactive_when_crosshairs_globally_off():
    """The reported case: crosshairs toggled OFF → left must STACK, not WW/WL."""
    H = _load_method(_CROSSHAIR, "_crosshair_grab_active")
    s = _Stub(crosshairs_enabled=False, crosshair_interaction_enabled=False,
              _crosshair_hidden_views=set())
    assert H._crosshair_grab_active(s) is False


def test_grab_inactive_when_interaction_disabled_or_pane_hidden():
    H = _load_method(_CROSSHAIR, "_crosshair_grab_active")
    s1 = _Stub(crosshairs_enabled=True, crosshair_interaction_enabled=False,
               _crosshair_hidden_views=set())
    assert H._crosshair_grab_active(s1) is False
    s2 = _Stub(crosshairs_enabled=True, crosshair_interaction_enabled=True,
               _crosshair_hidden_views={"axial"})
    assert H._crosshair_grab_active(s2) is False


def test_disable_crosshair_keeps_style_not_window_level_default():
    dis = _method_slice(_STATE.read_text(encoding="utf-8", errors="ignore"),
                        "_disable_crosshair_interaction")
    # must NOT revert to a fresh window/level default image style
    assert "vtkInteractorStyleImage()" not in dis
    assert "default_style" not in dis
    # keeps the view's crosshair style instead
    assert "self.crosshair_styles.get(view_name)" in dis
    assert "SetInteractorStyle(style)" in dis


def test_left_press_routes_to_stack_when_grab_inactive():
    press = _method_slice(_CROSSHAIR.read_text(encoding="utf-8", errors="ignore"),
                          "on_left_button_press")
    assert "_crosshair_grab_active()" in press
    idx = press.index("not self._crosshair_grab_active()")
    seg = press[idx:idx + 220]
    # the gate sets stack mode (NOT window/level) and starts the drag
    assert "self.stack_dragging = True" in seg
    assert "self.OnLeftButtonDown()" in seg
