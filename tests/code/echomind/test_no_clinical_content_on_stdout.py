"""Guard: EchoMind must not print dictation or reports to stdout (F8).

THE DEFECT: each of the four chat modes did

    print(f"[CHAT] Payload:", json.dumps(payload, ensure_ascii=False))   # dictation
    print(f"[CHAT] Response text:\\n{r.text}")                            # the report

on EVERY request, plus `print(f"[PAYLOAD] text=...")` and a full JSON dump of the
reception server's echoed report. That is patient content on stdout:
unconditional, not gated by a log level, impossible to switch off, and captured
by any shell transcript or console log. Serialising a large report to stdout on
every request also costs measurable time on the worker thread.

The useful diagnostics — endpoint, status, size — are kept via
`_dbg_request` / `_dbg_response` at DEBUG level on the `echomind.chat` logger.
The bodies are not logged at any level.
"""
from __future__ import annotations

import ast
import logging
import os
import re

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
_PAGES = os.path.join(_ROOT, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")


def _src() -> str:
    with open(_PAGES, encoding="utf-8") as fh:
        return fh.read()


# ── 1. the specific body dumps are gone ─────────────────────────────────────

@pytest.mark.parametrize("tag", ["CHAT", "REPORT", "ASSISTANT", "SEARCH"])
def test_no_response_body_is_printed(tag):
    src = _src()
    assert f"[{tag}] Response text" not in src, (
        f"the {tag} response body (the generated report) is printed to stdout"
    )


@pytest.mark.parametrize("tag", ["CHAT", "REPORT", "ASSISTANT", "SEARCH"])
def test_no_request_payload_is_printed(tag):
    src = _src()
    assert f"[{tag}] Payload" not in src, (
        f"the {tag} request payload (the physician's dictation) is printed to stdout"
    )


@pytest.mark.parametrize("tag", ["CHAT", "REPORT", "ASSISTANT", "SEARCH"])
def test_no_parsed_response_is_printed(tag):
    src = _src()
    assert f'print("[{tag}] Parsed JSON' not in src


def test_dictated_text_is_not_printed():
    src = _src()
    assert "[PAYLOAD] text=" not in src, (
        "the first 120 chars of the dictation were printed on every send"
    )


def test_reception_response_body_is_not_dumped():
    src = _src()
    assert "Full Server Response JSON" not in src
    assert "body={response_text[:2000]}" not in src


# ── 2. diagnostics are preserved, just without bodies ───────────────────────

def test_the_redacted_helpers_exist_and_are_used():
    src = _src()
    assert "def _dbg_request(" in src
    assert "def _dbg_response(" in src
    for tag in ("CHAT", "REPORT", "ASSISTANT", "SEARCH"):
        assert f'_dbg_request("{tag}"' in src
        assert f'_dbg_response("{tag}"' in src


def test_helpers_log_size_not_content(caplog):
    """Behavioural: feed real clinical-looking text, assert it never appears."""
    import importlib.util
    import types

    # Load just the two helpers, without importing the whole page module.
    src = _src()
    tree = ast.parse(src)
    wanted = {"_dbg_request", "_dbg_response"}
    picked = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in wanted
    ]
    assert len(picked) == 2, "helpers not found at module level"

    ns: dict = {"json": __import__("json"), "_log": logging.getLogger("echomind.chat")}
    module = ast.Module(body=picked, type_ignores=[])
    exec(compile(module, "<helpers>", "exec"), ns)  # noqa: S102 - test-only

    secret = "Patient has a 3 cm spiculated mass in the left upper lobe"

    class _Resp:
        status_code = 200
        text = secret

    with caplog.at_level(logging.DEBUG, logger="echomind.chat"):
        ns["_dbg_request"]("CHAT", "http://server/chat", {"user_message": secret})
        ns["_dbg_response"]("CHAT", _Resp())

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in logged, f"clinical text leaked into the log: {logged!r}"
    assert "payload_bytes=" in logged
    assert "body_bytes=" in logged


def test_helpers_never_raise_on_bad_input():
    src = _src()
    tree = ast.parse(src)
    picked = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in {"_dbg_request", "_dbg_response"}
    ]
    ns: dict = {"json": __import__("json"), "_log": logging.getLogger("echomind.chat")}
    exec(compile(ast.Module(body=picked, type_ignores=[]), "<helpers>", "exec"), ns)  # noqa: S102
    ns["_dbg_request"]("X", "url", None)
    ns["_dbg_request"]("X", "url", object())
    ns["_dbg_response"]("X", None)
    ns["_dbg_response"]("X", object())


# ── 3. the overall print volume came down ───────────────────────────────────

def test_print_count_did_not_grow_back():
    """A ratchet, not a target: this file had 126 bare prints."""
    prints = len(re.findall(r"^\s*print\(", _src(), re.M))
    assert prints <= 120, (
        f"{prints} bare print() calls in ai_chat_pages.py — prefer the module "
        "logger so output is level-gated and body-free"
    )
