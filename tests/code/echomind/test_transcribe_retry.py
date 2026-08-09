"""Guard: a transcription failure is reported as what it actually was (2026-08-09).

OBSERVED. Company Server 3 returned HTTP 500. The chat said "Voice quality seems low —
automatically retrying in noisy-voice mode", retried, got 500 again, and only then
surfaced the real error. Two things were wrong:

  1. A server outage was reported to the physician as a quiet microphone. He will
     re-record, speak louder and check his input device; none of it can help.
  2. Server 3 is an OpenAI-compatible Whisper endpoint that takes no `quality_mode`,
     so the "noisy" retry was a byte-identical request — a duplicate failure.

`err()` routed EVERY worker failure through the same helper that handles a genuine
quality rejection, and that helper always said the same sentence.
"""

import io
import os
import re
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import voice_transcription as vt                     # noqa: E402

_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _pages_src():
    return io.open(_PAGES, encoding="utf-8-sig").read()


# ── the capability flag ──────────────────────────────────────────────────────

@pytest.mark.parametrize("provider,expected", [
    (vt.STT_PROVIDER_AIPACS_2, True),
    (vt.STT_PROVIDER_GOOGLE, False),
    (vt.STT_PROVIDER_AIPACS_3, False),
    (vt.STT_PROVIDER_OPENAI, False),
])
def test_quality_mode_is_only_supported_where_the_server_acts_on_it(provider, expected):
    """Servers 1 and 2 send quality_mode with the upload and the server changes its
    thresholds. Server 3 and the OpenAI provider take a file and a model name."""
    assert vt.quality_mode_supported({"provider": provider}) is expected


def test_an_unknown_provider_keeps_the_old_behaviour():
    """Defaulting to False would silently lose a retry that might have worked."""
    assert vt.quality_mode_supported({"provider": "something_new"}) is True
    assert vt.quality_mode_supported({}) is True


def test_the_google_route_really_does_ignore_quality_mode():
    """Added 2026-08-09 when the route was activated for testing.

    `V2tGoogleProvider.transcribe_files` opens with `del quality_mode, timeout` - it
    accepts the argument and throws it away, so a "noisy" resend on this route is the
    same request twice, exactly as on Server 3. The flag claimed True until the route
    was switched on and the claim was checked against the code.
    """
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "secretary", "stt",
                               "providers", "v2t_google.py"),
                  encoding="utf-8-sig").read()
    assert "del quality_mode" in src, (
        "v2t now uses quality_mode - quality_mode_supported() must be updated")


def test_server_3_really_does_ignore_quality_mode():
    """The flag has to match the code it describes, or it is just a comment."""
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "voice_transcription.py"),
                  encoding="utf-8-sig").read()
    body = src[src.index("def _post_openai_compatible"):src.index("def _error")]
    assert "quality_mode" not in body.split('"""')[2], \
        "Server 3 now uses quality_mode — quality_mode_supported() must be updated"
    native = src[src.index("def _post_audio"):src.index("def _post_openai_compatible")]
    assert 'data={"quality_mode": quality_mode}' in native, \
        "the native path stopped sending quality_mode; the flag is now wrong"


# ── the message matches the cause ────────────────────────────────────────────

def test_the_two_failure_messages_are_separate_constants():
    src = _pages_src()
    assert "_VOICE_RETRY_LOW_QUALITY" in src and "_VOICE_RETRY_SERVER" in src


def test_the_server_message_never_blames_the_microphone():
    src = _pages_src()
    m = re.search(r"_VOICE_RETRY_SERVER = \(\s*\n?\s*\"([^\"]+)\"", src)
    assert m, "the transport retry message is missing"
    msg = m.group(1).lower()
    for blame in ("voice", "quality", "microphone", "mic ", "noisy", "louder"):
        assert blame not in msg, f"the server-failure message says {blame!r}: {msg!r}"
    assert "server" in msg


def test_the_voice_quality_sentence_exists_exactly_once():
    """It used to be reachable from three call sites including the error handler."""
    src = _pages_src()
    assert src.count("Voice quality seems low") == 1


def test_the_error_handler_reports_a_transport_failure_not_a_quality_one():
    src = _pages_src()
    err = src[src.index("        def err(e):"):]
    err = err[:err.index("worker = ApiWorker")]
    assert '_retry_once("transport")' in err, \
        "the worker error handler must not claim a voice-quality problem"
    assert '"quality"' not in err


def test_the_quality_call_sites_still_say_quality():
    """A genuine rejection (accepted=False) and a silent recording are quality events
    and must keep the noisy retry where the provider supports it."""
    src = _pages_src()
    assert src.count('_retry_once("quality")') == 2
    assert "_retry_with_noisy" not in src, "the old undifferentiated helper survived"


# ── the retry itself ─────────────────────────────────────────────────────────

def test_a_quality_retry_is_skipped_where_it_cannot_change_anything():
    src = _pages_src()
    fn = src[src.index("        def _retry_once("):src.index("        # -----------------------------\n        # Worker: network request")]
    assert 'if reason == "quality" and not noisy_helps:' in fn
    assert "return False" in fn
    assert 'next_mode = "noisy" if (reason == "quality" and noisy_helps) else "clear"' in fn


def test_a_transport_retry_never_switches_to_noisy_mode():
    """A 5xx is not a quality problem, so the resend must be a plain one — but it must
    still happen, because a 5xx is often transient."""
    src = _pages_src()
    fn = src[src.index("        def _retry_once("):src.index("        # -----------------------------\n        # Worker: network request")]
    assert 'quality_mode=next_mode' in fn
    assert '_is_retry=True' in fn


def test_only_one_retry_is_ever_scheduled():
    src = _pages_src()
    fn = src[src.index("        def _retry_once("):src.index("        # -----------------------------\n        # Worker: network request")]
    assert 'if _is_retry or quality_mode != "clear":' in fn


def test_a_cancelled_request_is_not_retried():
    src = _pages_src()
    fn = src[src.index("        def _retry_once("):src.index("        # -----------------------------\n        # Worker: network request")]
    assert '_tr_token["cancelled"]' in fn


def test_the_observed_failure_is_recorded_where_the_fix_lives():
    """The next person to read this function should know what it is defending."""
    src = _pages_src()
    fn = src[src.index("        def _retry_once("):src.index("        # -----------------------------\n        # Worker: network request")]
    assert "500" in fn and "Server 3" in fn


# ── the route has to be observable (2026-08-09) ──────────────────────────────
# Server 1/2/3 leave two lines in app.log per transcription ("[STT] upload ..." from
# _post_audio, then the response line from echomind_http). Google and OpenAI went
# through _delegate, which logged NOTHING. After switching the provider to Google we
# went to app.log to see how the test had gone and found no trace of it at all — not
# a success, not a failure, not an attempt. A route nobody can observe is a route
# nobody can verify.


def test_the_google_route_is_not_silent(monkeypatch, caplog):
    """Behavioural: run _delegate with a stubbed provider and read the log."""
    from modules.EchoMind.secretary.stt.providers import v2t_google

    class _Stub:
        def transcribe_files(self, paths, *, quality_mode=None, timeout=None):
            return {"ok": True, "transcript": "\u0633\u0644\u0627\u0645 \u062f\u06a9\u062a\u0631", "files": []}

    monkeypatch.setattr(v2t_google, "V2tGoogleProvider", _Stub)
    svc = vt.VoiceTranscriptionService({"provider": vt.STT_PROVIDER_GOOGLE})
    with caplog.at_level("INFO", logger="modules.EchoMind.voice_transcription"):
        out = svc.transcribe(["a.wav"])

    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "[STT] upload provider=v2t route=v2t files=1" in blob, \
        "the delegated route logged no attempt"
    assert "[STT] result route=v2t ok=True chars=9" in blob, \
        "the delegated route logged no outcome"

    # ...and the contract it already had is untouched.
    assert out["ok"] is True
    assert out["route_used"] == "v2t"
    assert out["stt_provider"] == vt.STT_PROVIDER_GOOGLE
    assert out["quality_report"] == []
    assert out["endpoint"] == ""


def test_the_route_log_never_carries_the_dictation(monkeypatch, caplog):
    """The transcript is a patient's clinical dictation. Its LENGTH is diagnostic;
    its CONTENT must never be written to app.log."""
    from modules.EchoMind.secretary.stt.providers import v2t_google
    secret = "\u0633\u0644\u0627\u0645 \u062f\u06a9\u062a\u0631"

    class _Stub:
        def transcribe_files(self, paths, *, quality_mode=None, timeout=None):
            return {"ok": True, "transcript": secret, "files": []}

    monkeypatch.setattr(v2t_google, "V2tGoogleProvider", _Stub)
    svc = vt.VoiceTranscriptionService({"provider": vt.STT_PROVIDER_GOOGLE})
    with caplog.at_level("INFO", logger="modules.EchoMind.voice_transcription"):
        svc.transcribe(["a.wav"])
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert secret not in blob, "the dictation reached app.log"


def test_a_failing_route_says_so_rather_than_vanishing(monkeypatch, caplog):
    from modules.EchoMind.secretary.stt.providers import v2t_google

    class _Boom:
        def transcribe_files(self, paths, *, quality_mode=None, timeout=None):
            raise RuntimeError("microphone on fire")

    monkeypatch.setattr(v2t_google, "V2tGoogleProvider", _Boom)
    svc = vt.VoiceTranscriptionService({"provider": vt.STT_PROVIDER_GOOGLE})
    with caplog.at_level("INFO", logger="modules.EchoMind.voice_transcription"):
        out = svc.transcribe(["a.wav"])
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "[STT] route=v2t raised: microphone on fire" in blob
    assert out["ok"] is False


def test_no_speech_is_distinguishable_from_never_ran(monkeypatch, caplog):
    """The exact pair we could not tell apart while reading app.log for the Google
    test: chars=0 with a result line means it ran and heard nothing; no line at all
    means it never ran."""
    from modules.EchoMind.secretary.stt.providers import v2t_google

    class _Quiet:
        def transcribe_files(self, paths, *, quality_mode=None, timeout=None):
            return {"ok": False, "transcript": "", "error": "No speech recognized.",
                    "files": []}

    monkeypatch.setattr(v2t_google, "V2tGoogleProvider", _Quiet)
    svc = vt.VoiceTranscriptionService({"provider": vt.STT_PROVIDER_GOOGLE})
    with caplog.at_level("INFO", logger="modules.EchoMind.voice_transcription"):
        svc.transcribe(["a.wav"])
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "chars=0" in blob and "No speech recognized." in blob


def test_the_http_routes_kept_their_own_log_line():
    """_post_audio's line is what the delegated one was modelled on; it must survive."""
    src = io.open(os.path.join(_ROOT, "modules", "EchoMind", "voice_transcription.py"),
                  encoding="utf-8-sig").read()
    assert '"[STT] upload provider=%s files=%d quality=%s"' in src
