"""Bounded issue dictation through the existing shared transcription service."""
from pathlib import Path
import tempfile
import threading
import time
import wave

_MICROPHONE = threading.Lock()


class IssueVoiceTake:
    SAMPLE_RATE = 16000
    MAX_SECONDS = 120

    def __init__(self, retain_audio=False):
        self.retain_audio = retain_audio
        self.stopped = threading.Event()
        self.cancelled = threading.Event()

    def stop(self):
        self.stopped.set()

    def cancel(self):
        self.cancelled.set()
        self.stopped.set()

    def run(self):
        """Worker only. No Qt callbacks, diagnostic logging or saved recording."""
        if not _MICROPHONE.acquire(blocking=False):
            return {'state':'voice_failed'}
        path = None
        try:
            import sounddevice
            import numpy as np
            audio = bytearray()
            maximum = self.SAMPLE_RATE * self.MAX_SECONDS * 2

            def capture(data, frames, timing, status):
                if self.stopped.is_set():
                    return
                remaining = maximum-len(audio)
                audio.extend(bytes(data)[:remaining])
                if len(audio) >= maximum:
                    self.stopped.set()

            started = time.monotonic()
            with sounddevice.RawInputStream(samplerate=self.SAMPLE_RATE, channels=1, dtype='int16', callback=capture):
                while not self.stopped.wait(0.05):
                    if time.monotonic()-started >= self.MAX_SECONDS:
                        self.stopped.set()
            if self.cancelled.is_set():
                return {'state':'voice_cancelled'}
            if len(audio) < self.SAMPLE_RATE//2 or np.max(np.abs(np.frombuffer(audio, dtype='<i2').astype('int32'))) < 300:
                return {'state':'voice_failed'}
            with tempfile.NamedTemporaryFile(prefix='aipacs_issue_voice_', suffix='.wav', delete=False) as temporary:
                path = Path(temporary.name)
            with wave.open(str(path), 'wb') as recording:
                recording.setnchannels(1)
                recording.setsampwidth(2)
                recording.setframerate(self.SAMPLE_RATE)
                recording.writeframes(audio)
            audio.clear()
            if self.cancelled.is_set():
                return {'state':'voice_cancelled'}
            from modules.EchoMind.voice_transcription import VoiceTranscriptionService
            result = VoiceTranscriptionService().transcribe([str(path)], quality_mode='clear', timeout=120)
            if self.cancelled.is_set():
                return {'state':'voice_cancelled'}
            text = result.get('transcript')
            if not result.get('ok') or result.get('accepted') is False or not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
                return {'state':'voice_failed'}
            response = {'state':'voice_transcribed', 'text':text.strip()}
            if self.retain_audio:
                response['recording'] = path.read_bytes()
            return response
        except Exception:
            return {'state':'voice_failed'}
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            _MICROPHONE.release()
