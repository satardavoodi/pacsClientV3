from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.enums import ToolState
from modules.viewer.tools.models import RulerModel
from modules.viewer.tools.renderers.base import AbstractToolRenderer
from modules.viewer.tools.store import ToolStore


class _NoopRenderer(AbstractToolRenderer):
    def render_tool(self, ctx, painter, model):
        return None

    def render_preview(self, ctx, painter, tool_type, points_image, cursor_image):
        return None


def test_set_store_rebinds_target_store():
    store_a = ToolStore()
    store_b = ToolStore()
    ctrl = ToolController(store_a, _NoopRenderer())

    store_a.add(RulerModel(slice_index=0, points_image=[(1.0, 1.0), (2.0, 2.0)]))
    store_b.add(RulerModel(slice_index=1, points_image=[(3.0, 3.0), (4.0, 4.0)]))

    ctrl.set_store(store_b)

    assert ctrl.store is store_b
    assert ctrl.store.count() == 1
    assert store_a.count() == 1


def test_set_store_resets_interaction_state():
    ctrl = ToolController(ToolStore(), _NoopRenderer())
    ctrl._state = ToolState.DRAGGING
    ctrl._hovered_handle_idx = 5
    ctrl._drag_handle_idx = 6
    ctrl._drag_start_img = (10.0, 10.0)
    ctrl._drag_start_points = [(1.0, 1.0)]

    ctrl.set_store(ToolStore())

    assert ctrl._state == ToolState.IDLE
    assert ctrl._hovered_handle_idx == -2
    assert ctrl._drag_handle_idx == -2
    assert ctrl._drag_start_img is None
    assert ctrl._drag_start_points is None
