from types import SimpleNamespace

from PySide6.QtCore import Qt

from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
from PacsClient.pacs.patient_tab.ui.patient_ui._vc_layout import _VCLayoutMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_pipeline import _PWPipelineMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_backend import _VWBackendMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import _SPINNER_HIDE_DELAY_MS
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor import _VWInteractorMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_overlay import _VWOverlayMixin
from modules.viewer.widgets import loading_spinner as loading_spinner_mod
from modules.viewer.widgets.loading_spinner import ViewportSpinner
from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT, BACKEND_VTK


class _BadgeStub:
    def __init__(self):
        self.text = None
        self.position = None

    def setText(self, text):
        self.text = text

    def adjustSize(self):
        return None

    def width(self):
        return len(self.text or "") * 8

    def move(self, x, y):
        self.position = (x, y)

    def raise_(self):
        return None


class _VisibleStub:
    def __init__(self, visible=False):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _HintLabelStub:
    def __init__(self):
        self.visible = False
        self.raised = False

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def raise_(self):
        self.raised = True


class _MouseEventStub:
    def __init__(self, button):
        self._button = button

    def button(self):
        return self._button

    def buttons(self):
        return self._button

    def accept(self):
        return None


class _MousePressBase:
    def __init__(self, calls):
        self._calls = calls

    def mousePressEvent(self, event):
        self._calls.append("super")


class _MousePressHarness(_VWInteractorMixin, _MousePressBase):
    def __init__(self, calls, *, qt_bridge_active=False, sync_enabled=False, image_viewer=None):
        _MousePressBase.__init__(self, calls)
        self._qt_bridge_active = qt_bridge_active
        self._sync_enabled = sync_enabled
        self.image_viewer = image_viewer
        self._sync_dragging = False
        self._sync_last_move_time = 0.0
        self.change_container_border = lambda: calls.append("select")


class _ContainerStub:
    def __init__(self):
        self.properties = {}
        self.frame_style = None
        self.line_width = None
        self.stylesheet = None

    def setProperty(self, key, value):
        self.properties[key] = value

    def setFrameStyle(self, value):
        self.frame_style = value

    def setLineWidth(self, value):
        self.line_width = value

    def setStyleSheet(self, value):
        self.stylesheet = value


def test_backend_badge_uses_fast_label_for_empty_fast_viewer():
    badge = _BadgeStub()
    backend = SimpleNamespace(
        _active_backend=BACKEND_VTK,
        _selected_backend=BACKEND_PYDICOM_QT,
        _bound_backend_metadata=None,
        _backend_badge=badge,
        width=lambda: 320,
    )

    _VWBackendMixin._update_backend_badge(backend)

    assert badge.text == "Fast"
    assert badge.position is not None


def test_backend_badge_keeps_advanced_for_non_fast_viewer():
    badge = _BadgeStub()
    backend = SimpleNamespace(
        _active_backend=BACKEND_VTK,
        _selected_backend=BACKEND_VTK,
        _bound_backend_metadata=None,
        _backend_badge=badge,
        width=lambda: 320,
    )

    _VWBackendMixin._update_backend_badge(backend)

    assert badge.text == "advance"


def test_create_init_overlay_uses_minimal_ai_pacs_loader(monkeypatch):
    calls = []
    overlay = object()

    def _fake_show(anchor, **kwargs):
        calls.append((anchor, kwargs))
        return overlay

    monkeypatch.setattr(AiPacsLoadingOverlay, "show_overlay", staticmethod(_fake_show))

    obj = SimpleNamespace(center_widget="center-anchor", _init_overlay=None)

    created = _PWPipelineMixin._create_init_overlay(obj)

    assert created is overlay
    assert obj._init_overlay is overlay
    assert calls == [
        (
            "center-anchor",
            {
                "title": "",
                "status": "",
                "subtitle": "",
                "minimal": True,
                "pass_through": True,
            },
        )
    ]


def test_hide_init_overlay_clears_reference(monkeypatch):
    hide_calls = []
    overlay = object()

    def _fake_hide(instance, fade_ms=500, delay_ms=0):
        hide_calls.append((instance, fade_ms, delay_ms))

    monkeypatch.setattr(AiPacsLoadingOverlay, "hide_overlay", staticmethod(_fake_hide))

    obj = SimpleNamespace(_init_overlay=overlay)

    _PWPipelineMixin._hide_init_overlay(obj)

    assert hide_calls == [(overlay, 0, 0)]
    assert obj._init_overlay is None


def test_settle_empty_layout_idle_state_hides_overlay_and_viewer_loading():
    calls = []
    emitted = []

    obj = SimpleNamespace(
        _first_series_displayed=False,
        _hide_init_overlay=lambda: calls.append("overlay"),
        _hide_viewer_loading_all=lambda: calls.append("viewer-loading"),
        loading_complete=SimpleNamespace(emit=lambda: emitted.append(True)),
    )

    _PWPipelineMixin._settle_empty_layout_idle_state(obj)

    assert calls == ["overlay", "viewer-loading"]
    assert emitted == [True]


def test_settle_empty_layout_idle_state_skips_when_first_series_visible():
    calls = []
    emitted = []

    obj = SimpleNamespace(
        _first_series_displayed=True,
        _hide_init_overlay=lambda: calls.append("overlay"),
        _hide_viewer_loading_all=lambda: calls.append("viewer-loading"),
        loading_complete=SimpleNamespace(emit=lambda: emitted.append(True)),
    )

    _PWPipelineMixin._settle_empty_layout_idle_state(obj)

    assert calls == []
    assert emitted == []


def test_empty_drop_hint_shows_for_idle_empty_viewer():
    label = _HintLabelStub()
    calls = []

    viewer = SimpleNamespace(
        last_series_show=None,
        _drop_overlay=None,
        viewport_spinner=SimpleNamespace(overlay=None, spinner=None),
        _ensure_empty_drop_hint_label=lambda: label,
        _layout_empty_drop_hint_label=lambda: calls.append("layout"),
        _should_show_empty_drop_hint=lambda: True,
    )

    _VWOverlayMixin._update_empty_drop_hint_visibility(viewer)

    assert calls == ["layout"]
    assert label.visible is True
    assert label.raised is True


def test_empty_drop_hint_hides_when_viewer_is_busy_or_populated():
    label = _HintLabelStub()

    viewer = SimpleNamespace(
        last_series_show=3,
        _drop_overlay=_VisibleStub(True),
        viewport_spinner=SimpleNamespace(
            overlay=_VisibleStub(True),
            spinner=_VisibleStub(False),
        ),
        _ensure_empty_drop_hint_label=lambda: label,
        _layout_empty_drop_hint_label=lambda: (_ for _ in ()).throw(AssertionError("should not relayout hidden hint")),
        _should_show_empty_drop_hint=lambda: False,
    )

    _VWOverlayMixin._update_empty_drop_hint_visibility(viewer)

    assert label.visible is False


def test_should_show_empty_drop_hint_requires_idle_empty_viewer():
    idle_viewer = SimpleNamespace(
        last_series_show=None,
        _drop_overlay=None,
        viewport_spinner=SimpleNamespace(overlay=None, spinner=None),
    )
    busy_viewer = SimpleNamespace(
        last_series_show=None,
        _drop_overlay=None,
        viewport_spinner=SimpleNamespace(overlay=_VisibleStub(True), spinner=None),
    )
    populated_viewer = SimpleNamespace(
        last_series_show=1,
        _drop_overlay=None,
        viewport_spinner=SimpleNamespace(overlay=None, spinner=None),
    )

    assert _VWOverlayMixin._should_show_empty_drop_hint(idle_viewer) is True
    assert _VWOverlayMixin._should_show_empty_drop_hint(busy_viewer) is False
    assert _VWOverlayMixin._should_show_empty_drop_hint(populated_viewer) is False


def test_spinner_hide_delay_allows_loading_gif_to_linger():
    assert _SPINNER_HIDE_DELAY_MS == 180


def test_mouse_press_selects_viewer_before_forwarding_to_super(monkeypatch):
    calls = []

    viewer = _MousePressHarness(calls, qt_bridge_active=False, sync_enabled=False, image_viewer=None)

    viewer.mousePressEvent(_MouseEventStub(Qt.MouseButton.LeftButton))

    assert calls == ["select", "super"]


def test_mouse_press_selects_qt_viewer_before_sync_handling():
    calls = []

    viewer = _MousePressHarness(calls, qt_bridge_active=True, sync_enabled=False, image_viewer=None)

    viewer.mousePressEvent(_MouseEventStub(Qt.MouseButton.LeftButton))

    assert calls == ["select", "super"]


def test_viewport_container_styles_emphasize_active_selection():
    active = _VCLayoutMixin._viewport_container_styles(active=True)
    inactive = _VCLayoutMixin._viewport_container_styles(active=False)

    assert "#60a5fa" in active
    assert "rgba(96, 165, 250, 0.08)" in active
    assert "rgba(156, 163, 175, 0.72)" in inactive
    assert "rgba(15, 23, 42, 0.03)" in inactive


def test_change_container_border_applies_active_and_inactive_styles():
    active_container = _ContainerStub()
    inactive_container = _ContainerStub()
    selected_nodes = []
    refline_calls = []

    selected_node = SimpleNamespace(widget=active_container)
    inactive_node = SimpleNamespace(widget=inactive_container)
    controller = SimpleNamespace(
        lst_nodes_viewer=[selected_node, inactive_node],
        set_viewer_to_main_viewer=lambda node: selected_nodes.append(node),
        parent_widget=SimpleNamespace(manage_reference_line=lambda: refline_calls.append(True)),
        _viewport_container_styles=_VCLayoutMixin._viewport_container_styles,
    )

    _VCLayoutMixin.change_container_border(controller, 0)

    assert active_container.properties["active"] is True
    assert inactive_container.properties["active"] is False
    assert "#60a5fa" in active_container.stylesheet
    assert "rgba(156, 163, 175, 0.72)" in inactive_container.stylesheet
    assert selected_nodes == [selected_node]
    assert refline_calls == [True]


def test_viewport_spinner_branded_overlay_is_mouse_transparent(monkeypatch):
    attr_calls = []
    calls = []

    class _OverlayStub:
        def setAttribute(self, attr, value):
            attr_calls.append((attr, value))

        def show(self):
            return None

        def raise_(self):
            return None

        def _sync_geometry(self):
            return None

    overlay = _OverlayStub()
    monkeypatch.setattr(
        AiPacsLoadingOverlay,
        "show_overlay",
        staticmethod(lambda *args, **kwargs: calls.append((args, kwargs)) or overlay),
    )

    spinner = ViewportSpinner(SimpleNamespace())
    spinner.show_loading("Loading series...")

    assert spinner.overlay is overlay
    assert calls == [
        (
            (spinner.viewport_widget,),
            {
                "title": "",
                "status": "",
                "subtitle": "",
                "minimal": True,
                "pass_through": True,
            },
        )
    ]
    assert (Qt.WA_TransparentForMouseEvents, True) in attr_calls


def test_viewport_spinner_fallback_spinner_is_mouse_transparent(monkeypatch):
    spinner = ViewportSpinner(SimpleNamespace())

    class _SpinnerStub:
        def __init__(self, parent, message):
            self.parent = parent
            self.message = message
            self.attrs = {}

        def set_message(self, message):
            self.message = message

        def setAttribute(self, attr, value):
            self.attrs[attr] = value

        def start_spinning(self):
            return None

        def center_in_parent(self):
            return None

        def testAttribute(self, attr):
            return bool(self.attrs.get(attr, False))

    monkeypatch.setattr(
        AiPacsLoadingOverlay,
        "show_overlay",
        staticmethod(lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("overlay unavailable"))),
    )
    monkeypatch.setattr(loading_spinner_mod, "LoadingSpinner", _SpinnerStub)

    spinner.show_loading("Loading series...")

    assert spinner.spinner is not None
    assert spinner.spinner.testAttribute(Qt.WA_TransparentForMouseEvents)