"""Guards for the F9 voice-recording rewire (2026-06-09).

F9 used to call the legacy ``toggle_microphone`` → ``VoiceWidget.show_under``
(the old bottom popup). It must now drive the CURRENT inline voice pipeline via
the shared ``ToolbarManager.toggle_voice_recording``:
  • not recording → start  (inline, == clicking the mic button → _on_mic_clicked)
  • recording      → pause  (inline pause control → _on_mic_pause_toggle)
  • paused         → resume (inline pause control)
"""
import logging
import sys
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_TB = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
       / "patient_toolbar" / "toolbar_manager.py")
_SC = (_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "shortcut_manager.py")


def _no_comments(text):
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def _load_toggle():
    src = _TB.read_text(encoding="utf-8", errors="ignore")
    start = src.index("    def toggle_voice_recording(self):")
    end = src.index("    def toggle_microphone(self", start)
    method = textwrap.dedent(src[start:end])
    ns = {"logger": logging.getLogger("test")}
    exec("class _T:\n" + textwrap.indent(method, "    "), ns)  # noqa: S102
    return ns["_T"]


class _SB:
    def __init__(self, recording):
        self._rec = recording

    def is_recording(self):
        return self._rec


class _Stub:
    def __init__(self, recording):
        self._sb = _SB(recording)
        self.tool_access = type("TA", (), {"MICROPHONE": "MIC"})()
        self.tools_button = {"MIC": "MICBTN"}
        self.clicked = []
        self.paused = 0

    def get_soundbox(self):
        return self._sb

    def _on_mic_clicked(self, btn):
        self.clicked.append(btn)

    def _on_mic_pause_toggle(self):
        self.paused += 1


# ─────────────────────────── behavioral guards ───────────────────────────

def test_toggle_starts_inline_when_not_recording():
    T = _load_toggle()
    stub = _Stub(recording=False)
    T.toggle_voice_recording(stub)
    # started via the inline mic-button handler, NOT a pause
    assert stub.clicked == ["MICBTN"]
    assert stub.paused == 0


def test_toggle_pauses_resumes_when_recording():
    T = _load_toggle()
    stub = _Stub(recording=True)   # is_recording() stays True while paused too
    T.toggle_voice_recording(stub)
    # routed through the inline pause/resume control, NOT a new start
    assert stub.paused == 1
    assert stub.clicked == []


# ─────────────────────────── source-wiring guards ────────────────────────

def test_toggle_uses_inline_path_not_legacy_popup():
    src = _TB.read_text(encoding="utf-8", errors="ignore")
    start = src.index("def toggle_voice_recording")
    body = _no_comments(src[start:start + 1400])
    assert "_on_mic_clicked(mic_btn)" in body
    assert "_on_mic_pause_toggle()" in body
    # must NOT use the obsolete bottom-popup entry points
    assert "show_under" not in body
    assert "toggle_microphone" not in body


def test_f9_handler_calls_shared_inline_toggle():
    body = _no_comments(_SC.read_text(encoding="utf-8", errors="ignore"))
    start = body.index("def _on_patient_voice_toggle")
    fn = body[start:start + 700]
    assert "toolbar_manager.toggle_voice_recording()" in fn
    # the old popup entry point must no longer be CALLED from the F9 handler
    # (the docstring may still name it to explain the change — match the call).
    assert ".toggle_microphone(" not in fn
