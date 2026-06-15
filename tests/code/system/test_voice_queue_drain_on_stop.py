"""Guard for the voice-recording drain-on-stop fix (client PC 'pc user 3 vahid').

Bug: the sounddevice callback (_callback_capture) puts audio frames into a queue
(_audio_q); a 60 ms QTimer (_on_timer) is the ONLY thing that moves them into
_audio_frames, which is what gets written to the .wav. On stop, _on_stop_internal
stopped the timer and then saved — WITHOUT draining the queue first. So every
recording lost its tail, and a SHORT recording lost ALL of it (queue never drained),
leaving _audio_frames empty -> `if self._audio_frames:` False -> the save was a
SILENT no-op. Result on the client: "the voice didn't save, I had to record 2-3
times". Fix: drain _audio_q into _audio_frames on stop, before saving (+ logging).
"""
import ast
import queue
from pathlib import Path
from types import SimpleNamespace

import numpy as np

REPO = Path(__file__).resolve().parents[3]
VOICE = REPO / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/voice_tool_ui.py"


def _make_fake_self(wav_path, q, frames):
    return SimpleNamespace(
        _is_recording=True, _stream=None, _is_paused=False, _player_offset_ms=0,
        _stop_stream=lambda: None,
        _timer=SimpleNamespace(stop=lambda: None),
        _audio_q=q,
        _audio_frames=frames,
        _file_path=wav_path,
        _sample_rate=16000,
        method_update_audio_counter=lambda: None,
        _update_record_pause_label=lambda: None,
        _refresh_buttons=lambda: None,
    )


def test_stop_drains_queue_so_short_recording_is_saved(tmp_path):
    """The exact bug condition: frames are ONLY in the queue (_audio_frames empty,
    as if the timer never drained). After the fix they must be saved, not lost."""
    import soundfile as sf
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.voice_tool_ui import VoiceWidget

    wav = tmp_path / "REC_short.wav"
    q = queue.Queue()
    q.put(np.zeros((100, 1), dtype=np.float32))
    q.put(np.ones((50, 1), dtype=np.float32) * 0.1)
    fake = _make_fake_self(wav, q, [])  # _audio_frames empty -> old code saved NOTHING

    VoiceWidget._on_stop_internal(fake)

    assert wav.exists(), "drain-on-stop must save audio that was only in the queue"
    data, sr = sf.read(str(wav))
    assert sr == 16000
    assert len(data) == 150, "both queued frames (100+50) must be saved, none lost"


def test_stop_includes_queue_tail_after_timer_drained_some(tmp_path):
    """Normal recording: timer already moved some frames; the tail still in the queue
    must also be included (previously the tail was dropped)."""
    import soundfile as sf
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.voice_tool_ui import VoiceWidget

    wav = tmp_path / "REC_tail.wav"
    already = [np.zeros((200, 1), dtype=np.float32)]          # drained by timer
    q = queue.Queue()
    q.put(np.ones((80, 1), dtype=np.float32) * 0.2)           # tail still queued
    fake = _make_fake_self(wav, q, list(already))

    VoiceWidget._on_stop_internal(fake)

    data, _ = sf.read(str(wav))
    assert len(data) == 280, "tail frames in the queue must be appended, not lost"


def test_empty_take_is_logged_not_silent(tmp_path, caplog):
    """No audio at all -> a WARNING is logged (was a silent no-op)."""
    import logging
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.voice_tool_ui import VoiceWidget

    wav = tmp_path / "REC_empty.wav"
    fake = _make_fake_self(wav, queue.Queue(), [])
    with caplog.at_level(logging.WARNING):
        VoiceWidget._on_stop_internal(fake)
    assert not wav.exists()
    assert any("VOICE" in r.message for r in caplog.records), "empty take must be logged"


# ── source guard: drain happens BEFORE the save ──────────────────────────────

def test_drain_precedes_save_in_source():
    src = VOICE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_on_stop_internal"), None)
    assert fn is not None
    body = ast.get_source_segment(src, fn)
    drain_idx = body.index("_audio_q.get_nowait()")
    save_idx = body.index("sf.write(")
    assert drain_idx < save_idx, "queue must be drained BEFORE sf.write"
    assert "logger.info" in body and "[VOICE]" in body
