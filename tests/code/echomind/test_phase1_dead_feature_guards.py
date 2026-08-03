"""Phase-1 optimization audit (2026-07-31) — guards for FIVE dead-code defects.

Each of the five had the same shape: the feature was fully written, looked
present in review, and could not execute. Unit tests did not catch any of them
because nothing asserted the wiring. That is what this file is for.

  1. `_upload_voices_then` never issued the send  — the `cont(...)` call, which
     IS the send, was commented out on the success path (since the initial
     commit). Pressing Send with a voice chip queued transcribed the audio and
     stopped: no report, no error.
  2. The Retry chip could never appear — `_pending_retry["bubble"]` was seeded
     `None` and nothing ever wrote a bubble back, so `if bub:` was always false.
  3. Image paste / drag-and-drop was dead — `UnifiedComposer` defined
     `eventFilter` twice and Python bound the later, three-line version.
  4. Reception status could never change — the UPDATE wrote `updated_at`, a
     column `ai_reception_reports` does not have.
  5. `AIPACS_ECHOMIND_HTTP_TIMEOUT` was silently dead for every call that also
     passed an explicit `timeout=` — i.e. every voice upload and both Settings
     probes.

Where a defect is structural (a shadowed method, a column that does not exist)
the guard is structural too — a behavioural test would need a live GUI or a live
server and would be skipped in CI, which is how these survived in the first
place.
"""
from __future__ import annotations

import ast
import importlib
import os
import re

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(*parts: str) -> str:
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _src_pages() -> str:
    return _read("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _src_widgets() -> str:
    return _read("modules", "EchoMind", "viewer_chat", "ai_chat_widgets.py")


def _strip_comments(src: str) -> str:
    """Drop whole-line comments so a guard never matches its own documentation."""
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))


# ── 1. the voice send actually sends ─────────────────────────────────────────

def test_upload_voices_then_calls_the_continuation_on_success():
    """`cont` IS the send. Every call site passes a continuation that runs
    `_send_with_mode(...)` / `_on_send_chatgpt(...)`; without the call, Send
    with a voice attachment is a silent no-op."""
    body = _strip_comments(_src_pages())
    assert "cont(tr_text, server_sid)" in body, (
        "the continuation call is gone again — Send-with-a-voice-chip will "
        "transcribe and then do nothing at all"
    )


def test_the_continuation_call_is_not_commented_out():
    """The exact shape of the original defect: present in the file, but inert."""
    for ln in _src_pages().splitlines():
        s = ln.strip()
        if "cont(tr_text, server_sid)" in s:
            assert not s.startswith("#"), (
                "cont(tr_text, server_sid) is commented out again: %r" % ln
            )


def test_voice_send_continuation_has_a_kill_switch():
    body = _src_pages()
    assert "AIPACS_ECHOMIND_VOICE_SEND_CONT" in body
    assert "_voice_send_cont_enabled" in _strip_comments(body)


def test_error_path_still_calls_the_continuation():
    """It always did — the guard exists so a future 'cleanup' cannot drop it."""
    assert 'cont("", None)' in _strip_comments(_src_pages())


# ── 2. the Retry chip is reachable ───────────────────────────────────────────

def test_pending_retry_bubble_is_assigned_somewhere():
    """`_send_with_mode` seeds {"bubble": None}; something must write it back,
    or `_er_for`'s `if bub:` can never be true and btnRetry never shows."""
    body = _strip_comments(_src_pages())
    assert re.search(r'_pending_retry\[\s*["\']bubble["\']\s*\]\s*=\s*(?!None)', body), (
        "nothing assigns a real bubble into _pending_retry['bubble'] — the "
        "whole retry path (preserved text + preserved images) is unreachable"
    )


def test_retry_is_still_shown_from_the_error_handler():
    assert "show_retry(" in _strip_comments(_src_pages())


# ── 3. exactly one eventFilter on the composer ───────────────────────────────

def _class_node(src: str, name: str) -> ast.ClassDef:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError("class %s not found" % name)


def test_unified_composer_defines_event_filter_exactly_once():
    """Two definitions means Python binds the later one and silently discards
    the earlier. That killed Ctrl+V of an image, QEvent.Paste, DragEnter,
    DragMove and Drop — the entire image-attachment-by-paste feature."""
    cls = _class_node(_src_widgets(), "UnifiedComposer")
    names = [n.name for n in cls.body if isinstance(n, ast.FunctionDef)]
    assert names.count("eventFilter") == 1, (
        "UnifiedComposer defines eventFilter %d times; the later one shadows "
        "the earlier and silently disables every branch it does not implement"
        % names.count("eventFilter")
    )


def test_no_class_in_the_composer_module_defines_a_method_twice():
    """The general form of the same bug, which review does not catch.

    This is not hypothetical: when it was first run it found TWO more real
    shadowed methods that nobody knew about -- `MessageBubble._is_probably_html`
    and, more seriously, `MessageBubble._wrap_rtl_html`, whose two bodies were
    NOT identical. The copy Python bound was the pre-fix one, which returns
    early whenever the text already contains `dir=rtl` and therefore never
    applies `.rtl-wrap` or its CSS -- and Persian translate output carries
    `dir=rtl` itself, so the one case the wrapper exists for was the exact case
    it skipped. The fixed version sat above it, shadowed, and had never run.
    """
    tree = ast.parse(_src_widgets())
    dupes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen = {}
        for n in node.body:
            if isinstance(n, ast.FunctionDef):
                seen[n.name] = seen.get(n.name, 0) + 1
        dupes += ["%s.%s x%d" % (node.name, k, v) for k, v in seen.items() if v > 1]
    assert not dupes, "duplicate method definitions (later shadows earlier): %s" % dupes


def test_the_surviving_event_filter_still_handles_enter_and_paste():
    """Deleting the duplicate must not have cost the Enter binding it carried."""
    cls = _class_node(_src_widgets(), "UnifiedComposer")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "eventFilter")
    body = ast.get_source_segment(_src_widgets(), fn) or ""
    assert "_emit_send" in body, "Enter -> send was lost with the duplicate"
    assert "Key_Return" in body and "ShiftModifier" in body
    assert "_handle_clipboard_paste" in body, "Ctrl+V image paste is not handled"
    assert "Drop" in body, "drag-and-drop of an image is not handled"


# ── 4. every column the reception SQL writes actually exists ─────────────────

_SCHEMA_SRC = ("database", "ai_sessions_db.py")
_RECEPTION_SRC = ("database", "ai_reception_db.py")


def _reception_columns() -> set[str]:
    """Columns declared for ai_reception_reports in the ONE schema authority."""
    src = _read(*_SCHEMA_SRC)
    m = re.search(
        r"CREATE TABLE IF NOT EXISTS ai_reception_reports\s*\((.*?)\)\s*\"\"\"",
        src, re.S,
    )
    assert m, "could not locate the ai_reception_reports schema"
    cols = set()
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line or line.upper().startswith(("PRIMARY", "UNIQUE", "FOREIGN", "CHECK")):
            continue
        cols.add(line.split()[0].strip('"`[]'))
    assert "status" in cols and "created_at" in cols, cols
    return cols


def test_reception_sql_only_writes_columns_that_exist():
    """The defect: `SET status = ?, updated_at = ?` against a table with no
    `updated_at` and no ALTER TABLE for it — every call raised OperationalError,
    so a report could never leave 'pending'."""
    declared = _reception_columns()
    src = _read(*_RECEPTION_SRC)
    written = set()
    for stmt in re.findall(r"\bSET\b(.*?)\bWHERE\b", src, re.S | re.I):
        written |= {c.strip().strip('"`[]') for c in re.findall(r"(\w+)\s*=\s*\?", stmt)}
    missing = written - declared
    assert not missing, (
        "ai_reception_db writes column(s) %s that ai_reception_reports does not "
        "have (declared: %s)" % (sorted(missing), sorted(declared))
    )


def test_reception_sql_only_reads_columns_that_exist():
    declared = _reception_columns()
    src = _read(*_RECEPTION_SRC)
    read_cols: set[str] = set()
    for stmt in re.findall(
        r"SELECT\s+(.*?)\s+FROM\s+ai_reception_reports", src, re.S | re.I
    ):
        if "*" in stmt:
            continue
        for c in stmt.split(","):
            c = c.strip().split()[0].strip('"`[]')
            if c and c.isidentifier() and not c.upper() in ("COUNT", "MAX", "MIN"):
                read_cols.add(c)
    missing = read_cols - declared
    assert not missing, "ai_reception_db selects non-existent column(s): %s" % sorted(missing)


def test_updated_at_specifically_is_not_written_to_this_table():
    # comments stripped: this module documents the defect by name, and a guard
    # must never trip on its own explanation of what it guards.
    assert "updated_at" not in _strip_comments(_read(*_RECEPTION_SRC)), (
        "ai_reception_reports has no updated_at column; writing it raises "
        "OperationalError on every call"
    )


# ── 5. the documented timeout override is not dead ───────────────────────────

@pytest.fixture()
def H(monkeypatch):
    monkeypatch.delenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", raising=False)
    return importlib.import_module("modules.EchoMind.echomind_http")


def test_env_override_applies_even_when_the_caller_passes_a_timeout(H, monkeypatch):
    """The defect: `resolve_timeout` returned inside `if timeout is not None:`
    before the env override was consulted — so the documented support escape
    hatch had no effect on any voice upload or either Settings probe, since all
    of them pass an explicit timeout."""
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "600")
    connect, read = H.resolve_timeout(120)
    assert read == 600.0, "the env override is dead again for explicit timeouts"
    assert connect <= H.DEFAULT_CONNECT_TIMEOUT_S


def test_env_override_still_applies_with_no_caller_timeout(H, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "600")
    assert H.resolve_timeout()[1] == 600.0


def test_zero_still_means_wait_forever(H, monkeypatch):
    monkeypatch.setenv("AIPACS_ECHOMIND_HTTP_TIMEOUT", "0")
    assert H.resolve_timeout(120) is None
    assert H.resolve_timeout() is None


def test_an_explicit_caller_timeout_wins_over_read(H):
    """A deliberate product decision, pinned so it is not "fixed" by accident:
    the caller's value is the user's Settings choice (Voice to Text ▸ Timeout),
    and an admin who lowers it to fail fast must get what they asked for."""
    assert H.resolve_timeout(60, read=360.0) == (min(H.DEFAULT_CONNECT_TIMEOUT_S, 60.0), 60.0)


def test_read_applies_when_the_caller_gives_no_timeout(H):
    assert H.resolve_timeout(read=360.0) == (H.DEFAULT_CONNECT_TIMEOUT_S, 360.0)


def test_a_scalar_is_never_returned(H):
    """A scalar applies to the connect phase too, which is what made an
    unreachable host take minutes to report itself."""
    for value in (5, 60, 120, 360):
        out = H.resolve_timeout(value)
        assert isinstance(out, tuple) and len(out) == 2


def test_no_call_site_passes_both_timeout_and_read_timeout():
    """Passing both is contradictory — `read_timeout` can never take effect —
    and three upload sites did, which is how the dead override went unnoticed."""
    bad = []
    for rel in (
        ("modules", "EchoMind", "voice_transcription.py"),
        ("modules", "EchoMind", "llm_client.py"),
        ("modules", "EchoMind", "secretary", "stt", "providers", "openai_transcribe.py"),
    ):
        src = _read(*rel)
        for call in re.findall(r"echomind_http\.(?:post|get)\((.*?)\n\s*\)", src, re.S):
            if "read_timeout=" in call and re.search(r"(?<!read_)\btimeout=", call):
                bad.append(os.path.join(*rel))
    assert not bad, "these calls pass both timeout= and read_timeout=: %s" % sorted(set(bad))


# ── 6. the "atomic" JSON write is actually atomic ────────────────────────────

def test_atomic_write_json_uses_os_replace_not_shutil_move():
    """`shutil.move` falls back to `copy2 + unlink` on OSError, and on Windows
    `os.rename` raises FileExistsError whenever the destination exists — i.e.
    on every re-save. That turns a function docstring'd "atomically writes" into
    a truncate-then-refill copy, so a crash mid-write loses the previous good
    version of a report."""
    src = _src_pages()
    fn = re.search(r"def _atomic_write_json\(.*?\n(?=    def )", src, re.S)
    assert fn, "_atomic_write_json not found"
    body = fn.group(0)
    assert "os.replace(" in body, "_atomic_write_json is not using os.replace"
    assert "shutil.move(" not in _strip_comments(body), (
        "shutil.move is back in _atomic_write_json — it is not atomic on Windows"
    )


# ── 7. the RTL wrapper that actually binds is the fixed one ──────────────────

def test_wrap_rtl_html_is_defined_once_and_is_the_fixed_version():
    """`MessageBubble._wrap_rtl_html` existed twice with DIFFERENT bodies.
    Python bound the later, pre-fix copy, which bails out on any text that
    already carries `dir=rtl` -- i.e. on Persian translate output, the case the
    wrapper exists to handle. Persian reports were laid out LTR as a result."""
    cls = _class_node(_src_widgets(), "MessageBubble")
    fns = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_wrap_rtl_html"]
    assert len(fns) == 1, "_wrap_rtl_html is defined %d times again" % len(fns)
    body = ast.get_source_segment(_src_widgets(), fns[0]) or ""
    assert "rtl-wrap" in body, "the RTL wrapper no longer emits .rtl-wrap"
    assert "direction: rtl" in body, "the RTL css is gone"
    assert 'dir=\'rtl\'" in low' not in body and "\'dir=\"rtl\"\' in low" not in body, (
        "the pre-fix early-return is back: content that already declares "
        "dir=rtl will skip the wrapper and its CSS entirely"
    )


def test_rtl_wrapper_still_guards_against_double_wrapping():
    """The fix replaced 'already has dir=rtl' with the narrower, correct test
    'already went through THIS wrapper'. That guard must stay."""
    cls = _class_node(_src_widgets(), "MessageBubble")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_wrap_rtl_html")
    body = ast.get_source_segment(_src_widgets(), fn) or ""
    assert "in low" in body and "rtl-wrap" in body, "double-wrap guard lost"


# ── 8. every Qt enum member the composer names actually exists ───────────────
#
# HOW THIS ONE WAS FOUND: removing the shadowing `eventFilter` duplicate
# exposed `QEvent.Paste` in the surviving filter -- an event type Qt does not
# have. It raised `AttributeError` inside a Qt virtual for every event that
# reached it, which is almost certainly why the working three-line duplicate was
# written instead of the original being repaired. A typo'd enum member is
# invisible to review and to any test that does not actually construct the
# widget, so it is worth checking mechanically.

_QT_ENUM_HOSTS = ("QEvent", "Qt", "QSizePolicy", "QMessageBox", "QDialog")


def _qt_enum_references(src: str) -> set[tuple[str, str]]:
    """Every `Host.Member` referenced in real code (comments excluded)."""
    refs: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        if isinstance(base, ast.Name) and base.id in _QT_ENUM_HOSTS:
            if node.attr and node.attr[0].isupper():
                refs.add((base.id, node.attr))
    return refs


@pytest.mark.parametrize("module_rel", [
    ("modules", "EchoMind", "viewer_chat", "ai_chat_widgets.py"),
])
def test_every_qt_enum_member_referenced_actually_exists(module_rel):
    pytest.importorskip("PySide6")
    from PySide6 import QtCore, QtWidgets

    hosts = {
        "QEvent": QtCore.QEvent,
        "Qt": QtCore.Qt,
        "QSizePolicy": QtWidgets.QSizePolicy,
        "QMessageBox": QtWidgets.QMessageBox,
        "QDialog": QtWidgets.QDialog,
    }

    missing = []
    for host_name, member in sorted(_qt_enum_references(_read(*module_rel))):
        host = hosts.get(host_name)
        if host is None:
            continue
        if hasattr(host, member):
            continue
        # PySide6 also exposes scoped enums as Host.Type.Member
        scoped = getattr(host, "Type", None)
        if scoped is not None and hasattr(scoped, member):
            continue
        missing.append("%s.%s" % (host_name, member))

    assert not missing, (
        "these Qt members do not exist and will raise AttributeError at "
        "runtime -- inside a Qt virtual, where the traceback is easy to miss: "
        "%s" % missing
    )
