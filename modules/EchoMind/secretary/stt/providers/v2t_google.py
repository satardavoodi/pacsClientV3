from __future__ import annotations

from typing import Any


class V2tGoogleProvider:
    """
    Additional STT route adapted from the v2t workflow:
    - uses SpeechRecognition + Google Web Speech
    - Persian language (fa-IR)
    - chunked transcription for long files
    """

    name = "v2t"

    def __init__(self, language: str = "fa-IR", chunk_seconds: int = 25):
        self.language = language
        self.chunk_seconds = max(5, int(chunk_seconds))

    def _duration_seconds(self, path: str) -> float:
        try:
            import soundfile as sf

            with sf.SoundFile(path) as audio_file:
                return float(len(audio_file)) / float(audio_file.samplerate or 1)
        except Exception:
            return 0.0

    def _transcribe_single(self, recognizer, sr, path: str) -> tuple[str, str | None]:
        chunks: list[str] = []
        duration = self._duration_seconds(path)
        if duration <= 0:
            duration = float(self.chunk_seconds)
        consumed = 0.0

        with sr.AudioFile(path) as source:
            while consumed < duration + 0.01:
                window = min(self.chunk_seconds, max(0.1, duration - consumed))
                try:
                    audio_data = recognizer.record(source, duration=window)
                except Exception:
                    break
                consumed += window
                try:
                    text = recognizer.recognize_google(audio_data, language=self.language)
                    if text:
                        chunks.append(text.strip())
                except sr.UnknownValueError:
                    continue
                except Exception as exc:
                    return "", str(exc)

        return " ".join(chunks).strip(), None

    def transcribe_files(self, paths: list[str], quality_mode: str = "clear", timeout: int = 360) -> dict[str, Any]:
        del quality_mode, timeout
        try:
            import speech_recognition as sr
        except Exception:
            return {
                "ok": False,
                "provider": self.name,
                "error": "SpeechRecognition is not installed.",
                "transcript": "",
                "files": [],
            }

        recognizer = sr.Recognizer()
        file_results: list[dict[str, Any]] = []
        all_text: list[str] = []

        for path in paths:
            if not path:
                file_results.append({"path": path, "ok": False, "error": "missing_path"})
                continue
            try:
                text, err = self._transcribe_single(recognizer, sr, path)
                if err:
                    file_results.append({"path": path, "ok": False, "error": err})
                    continue
                file_results.append({"path": path, "ok": True, "text": text})
                if text:
                    all_text.append(text)
            except FileNotFoundError:
                file_results.append({"path": path, "ok": False, "error": "missing_file"})
            except Exception as exc:
                file_results.append({"path": path, "ok": False, "error": str(exc)})

        transcript = "\n".join(x for x in all_text if x).strip()
        ok = bool(transcript)
        return {
            "ok": ok,
            "provider": self.name,
            "transcript": transcript,
            "files": file_results,
            "error": None if ok else "No speech recognized.",
        }

