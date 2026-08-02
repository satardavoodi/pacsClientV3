"""Guard: Settings ▸ EchoMind "Test Connection" must not freeze the GUI (F4).

THE DEFECT: both probe buttons ran their network call inline in the Qt slot.

  * `_on_test_stt_clicked` -> `VoiceTranscriptionService.test_connection()`,
    which walked THREE probe URLs SEQUENTIALLY at 8 s each = up to 24 s frozen;
  * `_on_test_openai_clicked` -> `test_openai_connection(timeout=<setting>)`.

`echomind_settings.py` contained no thread construct at all. This is the worst
possible moment for a freeze: the user clicks "Test Connection" precisely
BECAUSE they think the server is unreachable, so the slow path is the common
path — the button that diagnoses a hang was itself the hang.

Two fixes are pinned here:
  1. both probes run on a `_ProbeWorker` QThread and render on the GUI thread;
  2. the three STT probes run CONCURRENTLY, so the worst case is one probe's
     8 s rather than the sum. Priority order of the RESULT is unchanged.
"""
from __future__ import annotations

import ast
import importlib
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_SETTINGS = os.path.join(
    _ROOT, "PacsClient", "pacs", "workstation_ui", "settings_ui", "echomind_settings.py"
)
_VOICE = os.path.join(_ROOT, "modules", "EchoMind", "voice_transcription.py")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _function_source(path: str, name: str) -> str:
    src = _read(path)
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    pytest.fail(f"function {name!r} not found in {os.path.basename(path)}")


# ── 1. the probes are threaded ───────────────────────────────────────────────

def test_a_probe_worker_thread_exists():
    src = _read(_SETTINGS)
    assert "class _ProbeWorker(QThread):" in src, (
        "echomind_settings.py had NO thread construct at all — that was the defect"
    )
    assert "from PySide6.QtCore import Qt, QThread, Signal" in src


@pytest.mark.parametrize("slot", ["_on_test_stt_clicked", "_on_test_openai_clicked"])
def test_probe_slot_dispatches_to_the_worker(slot):
    body = _function_source(_SETTINGS, slot)
    assert "_start_probe(" in body, (
        f"{slot} still calls the network inline on the GUI thread"
    )
    assert "_settings_probe_async_enabled()" in body, (
        f"{slot} must respect the AIPACS_ECHOMIND_SETTINGS_ASYNC kill switch"
    )


def test_the_worker_never_touches_qt_widgets():
    """`_ProbeWorker.run` must only emit — rendering happens in the GUI slot."""
    body = _function_source(_SETTINGS, "run")
    for forbidden in ("QMessageBox", "setText(", "setProperty(", "setEnabled("):
        assert forbidden not in body, f"{forbidden!r} inside _ProbeWorker.run"
    assert "finishedWith.emit" in body


def test_start_probe_keeps_a_strong_reference_to_the_thread():
    """A running QThread that Qt frees aborts the process (cf. _ORPHANED_WORKERS)."""
    body = _function_source(_SETTINGS, "_start_probe")
    assert "self._probe_worker = worker" in body


def test_start_probe_always_re_enables_the_button():
    body = _function_source(_SETTINGS, "_start_probe")
    assert "button.setEnabled(False)" in body
    assert "button.setEnabled(True)" in body


def test_kill_switch_defaults_to_on():
    src = _read(_SETTINGS)
    assert '_ENV_SETTINGS_ASYNC = "AIPACS_ECHOMIND_SETTINGS_ASYNC"' in src
    assert "def _settings_probe_async_enabled()" in src


# ── 2. the STT probes are concurrent, and the ORDER of the verdict is kept ──

def test_stt_probes_run_concurrently():
    body = _function_source(_VOICE, "test_connection")
    assert "ThreadPoolExecutor" in body, (
        "the three 8 s probes still run sequentially — 24 s worst case"
    )


def test_stt_probe_priority_order_is_unchanged():
    body = _function_source(_VOICE, "test_connection")
    assert 'probes = (f"{base}/health", f"{base}/status", base)' in body


def test_stt_probe_has_a_sequential_fallback():
    body = _function_source(_VOICE, "test_connection")
    assert "fall back to sequential" in body.lower()


# ── 3. behavioural: the verdict still follows probe priority ────────────────

class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.fixture(scope="module")
def vt():
    return importlib.import_module("modules.EchoMind.voice_transcription")


def test_first_reachable_probe_wins_even_when_a_later_one_is_faster(vt, monkeypatch):
    """Concurrency must not change WHICH probe decides the verdict."""
    calls = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        # /health answers 200; /status would answer 200 too. /health must win.
        return _Resp(200 if url.endswith("/health") else 204)

    monkeypatch.setattr(vt.echomind_http, "get", _fake_get)
    monkeypatch.setattr(
        vt, "get_stt_settings",
        lambda: {
            "provider": vt.STT_PROVIDER_AIPACS_2,
            "custom_base_url": "", "custom_port": 0,
            "endpoint_path": "/generate_transcript",
            "timeout_seconds": 60, "auth_token": "t",
        },
    )
    out = vt.VoiceTranscriptionService().test_connection()
    assert out["ok"] is True
    assert "HTTP 200" in out["detail"]
    assert len(calls) == 3  # all three fired concurrently


def test_all_probes_failing_reports_not_reachable(vt, monkeypatch):
    def _boom(url, **kwargs):
        raise OSError("refused")

    monkeypatch.setattr(vt.echomind_http, "get", _boom)
    monkeypatch.setattr(
        vt, "get_stt_settings",
        lambda: {
            "provider": vt.STT_PROVIDER_AIPACS_2,
            "custom_base_url": "", "custom_port": 0,
            "endpoint_path": "/generate_transcript",
            "timeout_seconds": 60, "auth_token": "",
        },
    )
    out = vt.VoiceTranscriptionService().test_connection()
    assert out["ok"] is False
    assert "not reachable" in out["detail"].lower()


def test_test_connection_never_raises(vt, monkeypatch):
    monkeypatch.setattr(
        vt, "get_stt_settings", lambda: (_ for _ in ()).throw(RuntimeError("nope"))
    )
    try:
        vt.VoiceTranscriptionService(settings={"provider": "aipacs_2"}).test_connection()
    except Exception as exc:  # pragma: no cover
        pytest.fail(f"test_connection raised: {exc}")
