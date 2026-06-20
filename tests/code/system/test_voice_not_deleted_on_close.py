"""Guard: closing the patient/app window must NEVER delete an approved voice.

Root cause (patient 46838/47183, 2026-06-20): `voice_tool_ui.py` installs an
event filter on `patient_widget.window()` and, on `QEvent.Close`, called
`self._on_delete_clicked()` unconditionally — which `os.remove()`s the saved
recording. Since approve/save never clears `self._file_path`, the approved voice
was deleted on patient/window close.

Fix: the Close branch passes `user_initiated=False`, and `_on_delete_clicked`
keeps the saved file unless the delete is an explicit user action. Only the
red-X on the active recording and the dropdown delete (both `user_initiated`
defaulting to True) may remove a voice.

These are source-pins read as plain text, so the test needs no PySide6 / audio
backend to run.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_SRC = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_toolbar" / "voice_tool_ui.py").read_text(encoding="utf-8")


def test_close_branch_does_not_unconditionally_delete():
    # The QEvent.Close handler must NOT call a bare self._on_delete_clicked();
    # it must pass user_initiated=False so the guard keeps the saved voice.
    assert "self._on_delete_clicked(user_initiated=False" in _SRC, (
        "window-close must call _on_delete_clicked(user_initiated=False, ...)"
    )
    # The exact legacy bug line (bare delete in the close branch) must be gone.
    assert not re.search(r"QEvent\.Close:\s*\n\s*#.*\n\s*self\._on_delete_clicked\(\)\s*\n", _SRC), (
        "the unconditional delete-on-close must not be reintroduced"
    )


def test_delete_handler_has_user_initiated_guard():
    assert "def _on_delete_clicked(self, inline_override" in _SRC
    assert "user_initiated: bool = True" in _SRC, (
        "_on_delete_clicked must distinguish explicit user deletes"
    )
    # The protective guard + its kill switch must be present.
    assert "AIPACS_VOICE_KEEP_ON_CLOSE" in _SRC
    assert "[VOICE-DELETE-GUARD]" in _SRC
    # A pre-delete audit log must exist for the allowed (user) delete path.
    assert "[VOICE-DELETE]" in _SRC


def test_explicit_user_delete_paths_still_delete():
    # The red-X button and dropdown/menu still call _on_delete_clicked with the
    # default user_initiated=True (i.e. they do NOT pass user_initiated=False).
    assert "self.btn_delete.clicked.connect(self._on_delete_clicked)" in _SRC
    assert "self._on_delete_clicked(inline_override=True)" in _SRC  # cancel_recording_inline
