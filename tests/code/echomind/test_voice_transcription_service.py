"""Voice-to-Text is centralized in Settings — one endpoint for BOTH modules.

Guard for the 2026-07-13 change. Before it:

* EchoMind chat (``ai_chat_pages._transcribe_now``) POSTed straight to
  ``URL_GEN_TRANSCRIPT`` = ``{AI_BASE}/generate_transcript`` — a constant frozen at
  IMPORT time — so the destination could only change by editing code, and the chat
  ignored the Voice-to-Text setting entirely;
* Secretary EchoMind reached the SAME hard-coded constant through
  ``NativeIrannobatProvider`` (and sent no auth header).

Both now go through ``VoiceTranscriptionService``, which resolves the endpoint from
``Settings ▸ EchoMind ▸ Voice to Text`` on EVERY call.

Pure/offline — no Qt, no network (requests is monkeypatched).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from modules.EchoMind import settings_store as ss
from modules.EchoMind import voice_transcription as vt


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """Redirect echomind_settings.json to a temp file."""
    monkeypatch.setattr(ss, "_config_path", lambda: tmp_path / "echomind_settings.json")
    monkeypatch.delenv("AIPACS_ECHOMIND_STT_ENDPOINT", raising=False)
    # No GapGPT fallback token in tests unless a test asks for one.
    monkeypatch.setattr(vt, "resolve_auth_token", lambda cfg=None: str(
        (cfg or {}).get("auth_token") or ""
    ))
    return tmp_path


class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._body


@pytest.fixture()
def captured(monkeypatch):
    """Capture the outgoing POST instead of performing it."""
    calls = []

    def fake_post(url, files=None, data=None, headers=None, timeout=None, **kw):
        calls.append({
            "url": url,
            "fields": [name for name, _fh in (files or [])],
            "data": dict(data or {}),
            "headers": dict(headers or {}),
            "timeout": timeout,
        })
        return _Resp({
            "transcript": "hello world",
            "quality_report": [{"accepted": True, "criteria": {}}],
            "session_id": "sid-1",
        })

    monkeypatch.setattr(vt.requests, "post", fake_post)
    return calls


# ── endpoint resolution (PURE) ───────────────────────────────────────────────
def test_the_two_builtin_servers_resolve_to_their_addresses():
    assert vt.base_url_for("aipacs_1") == vt.AIPACS_SERVER_1_BASE   # A100
    assert vt.base_url_for("aipacs_2") == vt.AIPACS_SERVER_2_BASE   # Windows
    assert vt.build_endpoint(vt.AIPACS_SERVER_1_BASE) == (
        vt.AIPACS_SERVER_1_BASE + "/generate_transcript"
    )


def test_builtin_servers_are_labelled_by_name_only():
    labels = dict(vt.STT_PROVIDER_CHOICES)
    assert labels["aipacs_1"] == "AI-PACS Server 1"
    assert labels["aipacs_2"] == "AI-PACS Server 2"
    # The raw addresses must never leak into the UI label.
    for label in labels.values():
        assert "81.16" not in label and "80.210" not in label


def test_custom_server_url_and_port():
    assert vt.base_url_for("custom", "http://10.0.0.5", 9000) == "http://10.0.0.5:9000"
    # a port already in the URL wins
    assert vt.base_url_for("custom", "http://10.0.0.5:1234", 9000) == "http://10.0.0.5:1234"
    # bare host gets a scheme
    assert vt.base_url_for("custom", "10.0.0.5", 8000) == "http://10.0.0.5:8000"
    # nothing entered -> no endpoint
    assert vt.base_url_for("custom", "", 0) == ""


def test_google_and_openai_have_no_endpoint():
    assert vt.base_url_for("v2t") == ""
    assert vt.base_url_for("openai") == ""


# ── THE CORE REQUIREMENT: settings drive the destination, live ───────────────
def test_switching_server_in_settings_changes_the_upload_target(cfg, captured):
    ss.save_stt_settings({"provider": "aipacs_1"})
    vt.VoiceTranscriptionService().transcribe([__file__])
    assert captured[-1]["url"].startswith(vt.AIPACS_SERVER_1_BASE)

    ss.save_stt_settings({"provider": "aipacs_2"})
    vt.VoiceTranscriptionService().transcribe([__file__])
    assert captured[-1]["url"].startswith(vt.AIPACS_SERVER_2_BASE)

    ss.save_stt_settings({"provider": "custom", "custom_base_url": "http://10.1.2.3",
                          "custom_port": 7000})
    vt.VoiceTranscriptionService().transcribe([__file__])
    assert captured[-1]["url"] == "http://10.1.2.3:7000/generate_transcript"


def test_no_restart_needed_endpoint_is_resolved_per_call(cfg, captured):
    """The old bug: URL_GEN_TRANSCRIPT was bound at import, so a settings change
    could not take effect. Nothing may cache the resolved URL."""
    svc = vt.VoiceTranscriptionService()          # constructed ONCE
    ss.save_stt_settings({"provider": "aipacs_1"})
    svc.transcribe([__file__])
    first = captured[-1]["url"]
    ss.save_stt_settings({"provider": "aipacs_2"})
    svc.transcribe([__file__])                    # same instance
    assert captured[-1]["url"] != first


def test_both_modules_hit_the_same_configured_endpoint(cfg, captured):
    """EchoMind chat and Secretary must not be able to disagree."""
    from modules.EchoMind.secretary.stt.providers.native_irannobat import (
        NativeIrannobatProvider,
    )
    ss.save_stt_settings({"provider": "aipacs_1"})

    vt.VoiceTranscriptionService().transcribe([__file__])      # chat path
    chat_url = captured[-1]["url"]
    NativeIrannobatProvider().transcribe_files([__file__])     # secretary path
    secretary_url = captured[-1]["url"]

    assert chat_url == secretary_url == vt.AIPACS_SERVER_1_BASE + "/generate_transcript"


# ── the upload format the Whisper server expects is unchanged ────────────────
def test_upload_format_and_timeout_and_auth(cfg, captured):
    ss.save_stt_settings({"provider": "aipacs_2", "timeout_seconds": 120,
                          "auth_token": "tok-123"})
    vt.VoiceTranscriptionService().transcribe([__file__], quality_mode="noisy")
    call = captured[-1]
    assert call["fields"] == ["audio_files"]              # multipart field name
    assert call["data"] == {"quality_mode": "noisy"}
    assert call["headers"]["Authorization"] == "Bearer tok-123"
    assert call["timeout"] == 120


# ── the response contract both callers depend on ────────────────────────────
def test_quality_report_survives_the_service(cfg, captured):
    """The chat's rejection UI + auto "noisy" retry read quality_report. The old
    NativeIrannobatProvider threw it away — it must not be dropped again."""
    ss.save_stt_settings({"provider": "aipacs_2"})
    out = vt.VoiceTranscriptionService().transcribe([__file__])
    assert out["ok"] is True
    assert out["transcript"] == "hello world"
    assert out["quality_report"] == [{"accepted": True, "criteria": {}}]
    assert out["session_id"] == "sid-1"      # raw body merged through
    assert out["raw"]["transcript"] == "hello world"


def test_missing_file_and_unconfigured_server_report_errors(cfg, captured):
    ss.save_stt_settings({"provider": "aipacs_2"})
    out = vt.VoiceTranscriptionService().transcribe(["/nope/missing.wav"])
    assert out["ok"] is False and out["transcript"] == ""

    ss.save_stt_settings({"provider": "custom", "custom_base_url": ""})
    out = vt.VoiceTranscriptionService().transcribe([__file__])
    assert out["ok"] is False
    assert "Voice to Text" in out["error"]


# ── back-compat: an install that never touched the setting is unchanged ─────
def test_legacy_native_route_maps_to_the_windows_server(cfg):
    """`secretary_stt_provider: "native"` meant the hard-coded AI_BASE = the
    WINDOWS server. It must map to Server 2, or existing installs would silently
    move to a different server on upgrade."""
    ss.save_settings({"secretary_stt_provider": "native"})   # no stt_provider yet
    assert ss.get_stt_provider() == "aipacs_2"
    assert vt.base_url_for(ss.get_stt_provider()) == vt.AIPACS_SERVER_2_BASE


def test_legacy_v2t_and_openai_routes_are_preserved(cfg):
    ss.save_settings({"secretary_stt_provider": "v2t"})
    assert ss.get_stt_provider() == "v2t"
    ss.save_settings({"secretary_stt_provider": "openai"})
    assert ss.get_stt_provider() == "openai"


def test_sttrouter_route_stays_three_way(cfg):
    """SttRouter only understands native|v2t|openai. Every HTTP provider must map
    to "native" or Secretary would fall back to the wrong provider."""
    for provider, expected in (
        ("aipacs_1", "native"),
        ("aipacs_2", "native"),
        ("aipacs_3", "native"),   # OpenAI-compatible, but delegated via the service
        ("custom", "native"),
        ("v2t", "v2t"),
        ("openai", "openai"),
    ):
        ss.save_stt_settings({"provider": provider, "custom_base_url": "http://x"})
        assert ss.get_secretary_stt_route() == expected


# ── AI-PACS Server 3 — OpenAI-compatible Whisper (GapGPT) ────────────────────
@pytest.fixture()
def captured_openai(monkeypatch):
    """Capture a Server-3 style POST (files is a DICT with a single 'file')."""
    calls = []

    def fake_post(url, files=None, data=None, headers=None, timeout=None, **kw):
        calls.append({
            "url": url,
            "file_fields": sorted((files or {}).keys()),
            "data": dict(data or {}),
            "headers": dict(headers or {}),
            "timeout": timeout,
        })
        return _Resp({"text": "salaam donya"})

    monkeypatch.setattr(vt.requests, "post", fake_post)
    return calls


def test_server3_is_a_named_choice_no_address_shown():
    labels = dict(vt.STT_PROVIDER_CHOICES)
    assert labels["aipacs_3"] == "AI-PACS Server 3"
    # the GapGPT host / key must never appear in a UI label
    for label in labels.values():
        assert "gapgpt" not in label.lower() and "sk-" not in label


def test_server3_is_a_valid_provider():
    assert "aipacs_3" in ss.STT_PROVIDERS
    assert ss.normalize_stt_provider("aipacs_3") == "aipacs_3"


def test_server3_posts_openai_transcriptions_format(cfg, captured_openai, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF....WAVE")
    ss.save_stt_settings({"provider": "aipacs_3"})
    out = vt.VoiceTranscriptionService().transcribe([str(wav)])

    call = captured_openai[-1]
    assert call["url"] == vt.AIPACS_SERVER_3_BASE + "/audio/transcriptions"
    assert call["file_fields"] == ["file"]                       # OpenAI format
    assert call["data"] == {"model": vt.AIPACS_SERVER_3_MODEL}   # gapgpt/whisper-1
    assert call["headers"]["Authorization"] == f"Bearer {vt.AIPACS_SERVER_3_KEY}"

    # response contract both callers depend on
    assert out["ok"] is True
    assert out["transcript"] == "salaam donya"
    assert out["quality_report"] == []          # no low-quality signal for Whisper
    assert out["stt_provider"] == "aipacs_3"
    assert out["route_used"] == "native"
    assert out["endpoint"] == ""                # Server 3 address never surfaced


def test_server3_configured_token_overrides_builtin_key(cfg, captured_openai, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    ss.save_stt_settings({"provider": "aipacs_3", "auth_token": "sk-override"})
    vt.VoiceTranscriptionService().transcribe([str(wav)])
    assert captured_openai[-1]["headers"]["Authorization"] == "Bearer sk-override"


def test_server3_upload_failure_is_reported_not_raised(cfg, monkeypatch, tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(vt.requests, "post", boom)
    ss.save_stt_settings({"provider": "aipacs_3"})
    out = vt.VoiceTranscriptionService().transcribe([str(wav)])
    assert out["ok"] is False and out["transcript"] == ""
    assert "Server 3" in out["error"]


def test_server3_never_surfaces_address_in_resolve_endpoint(cfg):
    """resolve_endpoint is used by describe(); it must not leak the GapGPT host."""
    ss.save_stt_settings({"provider": "aipacs_3"})
    assert vt.resolve_endpoint() == ""


def test_kill_switch_restores_the_legacy_hardcoded_endpoint(cfg, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_STT_ENDPOINT", "0")
    ss.save_stt_settings({"provider": "aipacs_1"})   # would normally be the A100
    assert vt.resolve_endpoint().endswith("/generate_transcript")
    assert vt.AIPACS_SERVER_1_BASE not in vt.resolve_endpoint()


# ── no hard-coded endpoint may remain in either module ──────────────────────
def _src(*parts) -> str:
    return (Path(__file__).resolve().parents[3].joinpath(*parts)).read_text(
        encoding="utf-8", errors="replace"
    )


def test_chat_no_longer_posts_to_the_hardcoded_url():
    src = _src("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
    assert "requests.post(URL_GEN_TRANSCRIPT" not in src
    assert "requests.post(\n                    URL_GEN_TRANSCRIPT" not in src
    assert "VoiceTranscriptionService" in src


def test_secretary_native_provider_no_longer_posts_to_the_hardcoded_url():
    src = _src("modules", "EchoMind", "secretary", "stt", "providers",
               "native_irannobat.py")
    # It must no longer IMPORT or POST the frozen constant (mentioning it in a
    # comment explaining the history is fine).
    assert "import URL_GEN_TRANSCRIPT" not in src
    assert "requests.post" not in src
    assert "VoiceTranscriptionService" in src


def test_settings_page_exposes_the_required_fields():
    src = _src("PacsClient", "pacs", "workstation_ui", "settings_ui",
               "echomind_settings.py")
    for needle in (
        'QGroupBox("Voice to Text")',
        "stt_url_input",
        "stt_port_input",
        "stt_path_input",
        "stt_timeout_input",
        "stt_token_input",
        "Test Connection",
        "save_stt_settings",
    ):
        assert needle in src, f"Voice-to-Text settings missing: {needle}"
