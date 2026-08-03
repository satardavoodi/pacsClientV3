"""Guards for the last of the Phase-1 work (2026-07-31): storage and logging.

* `_ai_chat_dir` wrote to `os.getcwd()/attachment/...` — the exact tree
  `data_paths.migrate_legacy_data()` RELOCATES on every startup, so EchoMind
  re-created it every session and then could not find its own files. Under
  PyInstaller the CWD is `sys._MEIPASS`, deleted on exit: silent total loss.
* `_persist_transcribe` wrote `<sid>-transcribe.json` and had ZERO call sites,
  while both session-restore paths READ that file. The only copy of a completed
  dictation lived in a QTextEdit that the voice adapter can `deleteLater()`.
* `rec_*.wav` / `secretary_*.wav` / `pacs_clip_*.png` were written to %TEMP%
  and never deleted — ~10.6 MB per two-minute dictation, 0.6-1 GB per shift.
* `echomind_http` logged only on retry: no status, no elapsed, no connect/read
  split. With `modules.EchoMind.viewer_chat.*` logging nothing at all, "why was
  that report slow, and was it us or the server" was unanswerable.
"""
from __future__ import annotations

import ast
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_PAGES = ("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
_WIDG = ("modules", "EchoMind", "viewer_chat", "ai_chat_widgets.py")
_HTTP = ("modules", "EchoMind", "echomind_http.py")


def _read(*p: str) -> str:
    with open(os.path.join(_ROOT, *p), encoding="utf-8") as fh:
        return fh.read()


def _code(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def _fn(src: str, name: str, cls: str | None = None) -> str:
    tree = ast.parse(src)
    scope = tree
    if cls is not None:
        scope = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls)
    for n in ast.walk(scope):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError("%s not found" % name)


def _body_no_doc(src: str, name: str, cls: str | None = None) -> str:
    node = ast.parse(_fn(src, name, cls).lstrip()).body[0]
    stmts = node.body
    if stmts and isinstance(stmts[0], ast.Expr) and isinstance(stmts[0].value, ast.Constant):
        stmts = stmts[1:]
    return "\n".join(ast.unparse(s) for s in stmts)


# ── 1. clinical artifacts go where data_paths says ───────────────────────────

def test_ai_chat_dir_uses_the_data_paths_authority():
    body = _body_no_doc(_read(*_PAGES), "_ai_chat_dir", cls="OneChatPage")
    assert "ATTACHMENTS_DIR" in body, (
        "_ai_chat_dir is CWD-relative again — it will re-create the tree the "
        "startup migration relocates, and write into a deleted temp dir under "
        "PyInstaller"
    )


def test_ai_chat_dir_still_reaches_already_saved_files():
    """Changing where we WRITE must not orphan what a radiologist already saved."""
    body = _body_no_doc(_read(*_PAGES), "_ai_chat_dir", cls="OneChatPage")
    assert "legacy" in body, "the legacy-folder fallback is gone; saved work becomes invisible"
    assert "getcwd" in body, "nothing looks at the old location any more"


def test_ai_chat_dir_warns_when_it_falls_back():
    """A silent fallback would hide the fact that the migration is still needed."""
    body = _body_no_doc(_read(*_PAGES), "_ai_chat_dir", cls="OneChatPage")
    assert "warning" in body.lower(), "the legacy fallback is silent"


# ── 2. the transcript is persisted ───────────────────────────────────────────

def test_persist_transcribe_has_a_call_site():
    """It existed with ZERO callers while both restore paths read its output."""
    src = _code(_read(*_PAGES))
    calls = [l for l in src.splitlines() if "_persist_transcribe(" in l and "def " not in l]
    assert calls, (
        "_persist_transcribe is orphaned again — a completed dictation lives "
        "only in a QTextEdit that the voice adapter can destroy"
    )


def test_the_transcript_is_saved_right_where_it_is_accepted():
    body = _code(_fn(_read(*_PAGES), "_transcribe_now", cls="OneChatPage"))
    assert "_persist_transcribe(" in body, "the save does not happen on the accept path"
    assert body.index("set_tab_text(target_tab") < body.index("_persist_transcribe("), (
        "the transcript is saved before it is committed to the tab"
    )


def test_saving_the_transcript_can_never_break_transcription():
    body = _code(_fn(_read(*_PAGES), "_transcribe_now", cls="OneChatPage"))
    after = body.split("_persist_transcribe(", 1)[1]
    assert "except" in body.split("_persist_transcribe(")[0][-400:] or "except" in after[:200], (
        "the persist call is not guarded — a disk error would lose the "
        "transcription that just succeeded"
    )


# ── 3. temp captures are swept ───────────────────────────────────────────────

def test_a_temp_sweeper_exists_and_runs():
    src = _read(*_WIDG)
    assert "def _sweep_stale_temp_captures" in src, (
        "%TEMP% captures are never deleted again — ~10.6 MB per two-minute "
        "dictation, 0.6-1 GB per shift"
    )
    init = _code(_fn(src, "__init__", cls="UnifiedComposer"))
    assert "_sweep_stale_temp_captures()" in init, "the sweeper is never called"


def test_the_sweeper_covers_all_three_capture_kinds():
    src = _read(*_WIDG)
    for pattern in ("rec_*.wav", "secretary_*.wav", "pacs_clip_*.png"):
        assert pattern in src, "the sweeper no longer covers %s" % pattern


def test_the_sweeper_cannot_race_a_live_upload():
    """The STT read budget is 360 s, so anything in flight is minutes old. A
    cutoff shorter than that could delete a file mid-transcription."""
    src = _read(*_WIDG)
    assert "_TEMP_SWEEP_MAX_AGE_S" in src
    ns: dict = {}
    for line in src.splitlines():
        if line.startswith("_TEMP_SWEEP_MAX_AGE_S"):
            exec(line, ns)  # noqa: S102 - test-only, a literal arithmetic expression
    assert ns["_TEMP_SWEEP_MAX_AGE_S"] >= 3600, "the sweep cutoff is dangerously short"


def test_the_sweeper_has_a_kill_switch():
    assert "AIPACS_ECHOMIND_TEMP_SWEEP" in _read(*_WIDG)


# ── 4. the transport records what it did ─────────────────────────────────────

def test_every_request_is_logged_with_status_and_elapsed():
    body = _body_no_doc(_read(*_HTTP), "_send")
    assert "elapsed_ms" in body, "requests are no longer timed — slow-report triage is blind again"
    assert "status" in body


def test_failures_record_which_phase_they_failed_in():
    """A slow LLM and a slow SOCKS5 tunnel are indistinguishable without it —
    and `resolve_timeout` already knows the split."""
    body = _body_no_doc(_read(*_HTTP), "_send")
    assert "phase=" in body, "connect-vs-read is not recorded on failure"


def test_the_log_never_carries_a_query_string_or_a_body():
    """Same rule as F8: sizes and timings, never clinical content — and an
    endpoint's query string can carry identifiers."""
    src = _read(*_HTTP)
    body = _body_no_doc(src, "_send")
    for leak in ("kwargs['json']", 'kwargs["json"]', "resp.text", ".content", "headers=",):
        assert leak not in body, "_send logs request/response content (%s)" % leak
    ep = _body_no_doc(src, "_endpoint")
    assert "query" not in ep.lower() or "parts.query" not in ep, "the query string is being logged"
    assert "hostname" in ep and "path" in ep


def test_endpoint_helper_never_raises():
    """It runs on every request, including the failure path."""
    import importlib
    H = importlib.import_module("modules.EchoMind.echomind_http")
    for bad in ("", "not a url", "http://", None):
        try:
            out = H._endpoint(bad)  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover
            raise AssertionError("_endpoint(%r) raised %r" % (bad, exc))
        assert isinstance(out, str)


def test_endpoint_helper_strips_credentials_and_query():
    import importlib
    H = importlib.import_module("modules.EchoMind.echomind_http")
    out = H._endpoint("https://user:secret@api.example.com/v1/chat?token=abc123&pid=52679")
    assert "secret" not in out and "abc123" not in out and "52679" not in out, out
    assert out == "api.example.com/v1/chat"
