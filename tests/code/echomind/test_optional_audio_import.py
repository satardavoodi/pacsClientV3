"""EchoMind text UI must import without a working PortAudio device/session."""
import os
from pathlib import Path
import subprocess
import sys


def test_text_widgets_import_without_portaudio_initialization():
    root = Path(__file__).resolve().parents[3]
    code = """
import importlib.abc
import sys
class NoAudio(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'sounddevice':
            raise RuntimeError('Synthetic PortAudio initialization failure')
sys.modules.pop('sounddevice', None)
sys.meta_path.insert(0, NoAudio())
from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble, UnifiedComposer, sd
assert 'sounddevice' not in sys.modules
try:
    sd.query_devices()
except RuntimeError as exc:
    assert 'Synthetic PortAudio' in str(exc)
else:
    raise AssertionError('Unavailable recording backend must report its error')
"""
    run = subprocess.run([sys.executable, '-c', code], cwd=root,
                         env=dict(os.environ, QT_QPA_PLATFORM='offscreen'),
                         capture_output=True, text=True, timeout=45)
    assert run.returncode == 0, run.stderr
