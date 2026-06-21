"""Guards for the Patient-Tab keyboard shortcuts (2026-06-09).

F1–F4 = CT window presets (Lung/Abdomen/Bone/Refreshing), F9 = voice record
toggle (start→pause→resume), F10 = save/approve the voice recording, F11 =
total-layout screenshot. All are scoped to the active Patient Viewer and reuse
the toolbar's own button logic (no duplicated preset/recording/capture code).

The handlers are exec'd from source against stubs so we don't need a live
QApplication / QShortcut table or the heavy toolbar widget.
"""
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SC = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "shortcut_manager.py")
_TB = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
       / "patient_toolbar" / "toolbar_manager.py")


def _no_comments(text):
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _load_shortcut_handlers():
    """Exec the contiguous block of patient-shortcut helper methods as a class."""
    src = _SC.read_text(encoding="utf-8", errors="ignore")
    start = src.index("    def _active_patient_tab(self):")
    end = src.index("    def _on_arrow_up_pressed(self):", start)
    block = textwrap.dedent(src[start:end])
    ns = {}
    exec("class _H:\n" + textwrap.indent(block, "    "), ns)  # noqa: S102
    return ns["_H"]


def _load_apply_named_preset():
    src = _TB.read_text(encoding="utf-8", errors="ignore")
    start = src.index("    def apply_named_window_preset(self, name):")
    end = src.index("    def _show_wl_presets_dropdown(self, button):", start)
    method_src = textwrap.dedent(src[start:end])
    ns = {}
    exec("class _T:\n" + textwrap.indent(method_src, "    "), ns)  # noqa: S102
    return ns["_T"]


# ───────────────────────────── source guards ─────────────────────────────

def test_fkeys_registered_and_mapped():
    code = _no_comments(_SC.read_text(encoding="utf-8", errors="ignore"))
    for key in ("Key_F1", "Key_F2", "Key_F3", "Key_F4", "Key_F9", "Key_F10", "Key_F11"):
        assert key in code, key
    assert "_on_patient_window_preset('lung')" in code
    assert "_on_patient_window_preset('abdomen')" in code
    assert "_on_patient_window_preset('bone')" in code
    assert "_on_patient_window_preset('refreshing')" in code
    assert "self._on_patient_voice_toggle" in code
    assert "self._on_patient_voice_save" in code
    assert "self._on_patient_total_layout_capture" in code


def test_handlers_reuse_toolbar_callables():
    code = _no_comments(_SC.read_text(encoding="utf-8", errors="ignore"))
    assert "toolbar_manager.apply_named_window_preset(name)" in code
    # F9 must drive the CURRENT inline voice pipeline, not the legacy popup.
    assert "toolbar_manager.toggle_voice_recording()" in code
    assert "tb.toggle_microphone(selected_widget, mic_btn)" not in code
    assert "get_soundbox()" in code and "_on_save_clicked()" in code
    assert "_capture_all_layouts()" in code
    # scoping guard present
    assert "def _active_patient_tab" in code
    assert "getattr(cw, 'toolbar_manager', None) is not None" in code


def test_toolbar_window_presets_values_and_delegation():
    code = _no_comments(_TB.read_text(encoding="utf-8", errors="ignore"))
    assert "def apply_named_window_preset" in code
    assert "'lung': (1500, -600)" in code
    assert "'abdomen': (400, 40)" in code
    assert "'bone': (2000, 500)" in code
    # the dropdown buttons now delegate to the shared methods (one source)
    assert "self._apply_wl_preset(ww, wl)" in code
    assert "self._apply_default_wl_preset()" in code


# ─────────────────────────── behavioral guards ───────────────────────────

def test_apply_named_window_preset_maps_correctly():
    cls = _load_apply_named_preset()
    cls.WINDOW_PRESETS = {
        'lung': (1500, -600), 'abdomen': (400, 40),
        'brain': (80, 40), 'bone': (2000, 500),
    }

    class _T(cls):
        def __init__(self):
            self.applied = []
            self.default_called = 0

        def _apply_wl_preset(self, ww, wl):
            self.applied.append((ww, wl))

        def _apply_default_wl_preset(self):
            self.default_called += 1

    t = _T()
    assert t.apply_named_window_preset('lung') is True
    assert t.apply_named_window_preset('abdomen') is True
    assert t.apply_named_window_preset('bone') is True
    assert t.applied == [(1500, -600), (400, 40), (2000, 500)]
    assert t.apply_named_window_preset('default') is True
    assert t.default_called == 1
    # 'refreshing' is the F4 user-facing name; it aliases the DICOM reset.
    assert t.apply_named_window_preset('refreshing') is True
    assert t.default_called == 2
    # unknown preset → no-op, returns False
    assert t.apply_named_window_preset('not-a-modality') is False
    assert t.applied == [(1500, -600), (400, 40), (2000, 500)]


def _make_handler_stub(patient_tab):
    H = _load_shortcut_handlers()

    class _FakeTabWidget:
        def __init__(self, w):
            self._w = w

        def currentWidget(self):
            return self._w

    class _FakeHome:
        def __init__(self, w):
            self.tab_widget = _FakeTabWidget(w)

    inst = H()
    inst.home_widget = _FakeHome(patient_tab)
    return inst


class _FakeToolAccess:
    MICROPHONE = "MICROPHONE"


class _FakeToolbar:
    def __init__(self):
        self.preset_calls = []
        self.voice_toggles = 0
        self.captured = 0
        self.tool_access = _FakeToolAccess()
        self.tools_button = {"MICROPHONE": "MIC_BTN"}
        self._soundbox = self._SB()

    class _SB:
        def __init__(self):
            self.saved = 0

        def _on_save_clicked(self):
            self.saved += 1

    def apply_named_window_preset(self, name):
        self.preset_calls.append(name)

    def toggle_voice_recording(self):
        self.voice_toggles += 1

    def get_soundbox(self):
        return self._soundbox

    def _capture_all_layouts(self):
        self.captured += 1


class _FakePatientTab:
    def __init__(self, toolbar):
        self.toolbar_manager = toolbar
        self.selected_widget = "SELECTED"


def test_window_preset_handler_calls_toolbar_when_patient_active():
    tb = _FakeToolbar()
    inst = _make_handler_stub(_FakePatientTab(tb))
    inst._on_patient_window_preset('bone')
    assert tb.preset_calls == ['bone']


def test_voice_toggle_handler_uses_shared_inline_toggle():
    # F9 must call the shared inline voice controller, NOT the legacy popup.
    tb = _FakeToolbar()
    inst = _make_handler_stub(_FakePatientTab(tb))
    inst._on_patient_voice_toggle()
    assert tb.voice_toggles == 1


def test_voice_save_handler_calls_save():
    tb = _FakeToolbar()
    inst = _make_handler_stub(_FakePatientTab(tb))
    inst._on_patient_voice_save()
    assert tb.get_soundbox().saved == 1


def test_total_layout_handler_calls_capture_all():
    tb = _FakeToolbar()
    inst = _make_handler_stub(_FakePatientTab(tb))
    inst._on_patient_total_layout_capture()
    assert tb.captured == 1


def test_shortcuts_noop_when_not_a_patient_tab():
    # Active tab is NOT a patient viewer (no toolbar_manager) → every handler
    # must no-op (scoping: never disturb the Home page / other modules).
    class _HomePageTab:
        pass  # no toolbar_manager

    inst = _make_handler_stub(_HomePageTab())
    assert inst._active_patient_tab() is None
    # none of these should raise or do anything
    inst._on_patient_window_preset('lung')
    inst._on_patient_voice_toggle()
    inst._on_patient_voice_save()
    inst._on_patient_total_layout_capture()
