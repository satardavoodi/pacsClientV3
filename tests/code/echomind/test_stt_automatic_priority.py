from modules.EchoMind import voice_transcription as vt
from modules.EchoMind import settings_store as ss


def test_default_is_automatic(monkeypatch):
    monkeypatch.setattr(ss, "load_settings", lambda: {"secretary_stt_provider": "native"})
    assert ss.get_stt_provider() == "auto"


def test_manual_selection_preserved(monkeypatch):
    monkeypatch.setattr(ss, "load_settings", lambda: {"stt_provider": "custom"})
    assert ss.get_stt_provider() == "custom"


def test_automatic_order_and_budget(monkeypatch):
    calls = []
    def failed(self, *args):
        cfg = args[-1]
        calls.append((cfg["provider"], args[-2]))
        return {"ok": False, "transcript": ""}
    monkeypatch.setattr(vt.VoiceTranscriptionService, "_delegate", failed)
    monkeypatch.setattr(vt.VoiceTranscriptionService, "_post_openai_compatible", failed)
    monkeypatch.setattr(vt.VoiceTranscriptionService, "_post_audio", failed)
    out = vt.VoiceTranscriptionService({"provider": "auto"}).transcribe(["synthetic.wav"])
    assert [x[0] for x in calls] == ["v2t", "aipacs_3", "aipacs_1", "aipacs_2"]
    assert all(x[1] == 45 for x in calls)
    assert not out["ok"]


def test_success_stops_fallback(monkeypatch):
    monkeypatch.setattr(vt.VoiceTranscriptionService, "_delegate", lambda *a: {"ok": True, "transcript": "synthetic"})
    monkeypatch.setattr(vt.VoiceTranscriptionService, "_post_openai_compatible", lambda *a: (_ for _ in ()).throw(AssertionError("unexpected fallback")))
    assert vt.VoiceTranscriptionService({"provider": "auto"}).transcribe(["synthetic.wav"])["ok"]
