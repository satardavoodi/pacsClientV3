"""Guards for the Phase-1 responsiveness and storage work (2026-07-31).

Each of these was measured or read off a live install, not guessed:

* The Secretary voice command ran its whole LLM pipeline inside the STT
  worker's `done` callback — which Qt delivers on the GUI THREAD. Phase-1
  routing (20 s) + Phase-2 planning (30 s) + repair (2 x 25 s) blocked the
  event loop: 60-95 s of frozen workstation on a degraded link.
* Opening the panel called `ai_fetch_messages_full(sid)` for EVERY session — no
  LIMIT — to display ONE.
* `_dbg_request` built a multi-megabyte JSON string of base64 image
  attachments on every request even with debug logging off.
* `row_factory` leaked between pooled connections: five call sites set
  `sqlite3.Row` and none reset it.
"""
from __future__ import annotations

import ast
import os

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

_ORB = ("PacsClient", "pacs", "workstation_ui", "home_ui", "secretary_button_widget.py")
_ORCH = ("modules", "EchoMind", "secretary", "orchestrator.py")
_PAGES = ("modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
_POOL = ("database", "_pool.py")


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


# ── 1. the Secretary pipeline plans off the GUI thread ───────────────────────

def test_orchestrator_exposes_a_planning_only_entry_point():
    """Only the PLANNING half can move off the GUI thread — execution reaches
    adapters that legitimately touch widgets, so moving it would turn a freeze
    into an access violation."""
    src = _read(*_ORCH)
    assert "def preplan(" in src, (
        "preplan() is gone — the Secretary pipeline is back to doing its LLM "
        "work on the GUI thread"
    )


def test_parse_plan_uses_a_precomputed_plan_instead_of_re_running_the_llm():
    body = _code(_fn(_read(*_ORCH), "_parse_plan", cls="SecretaryOrchestrator"))
    assert "_preplanned" in body, "_parse_plan ignores a pre-computed plan"


def test_a_failed_preplan_does_not_re_run_the_llm_on_the_gui_thread():
    """The three-state contract: absent = plan here; a plan = use it; falsy =
    planning already ran and found nothing, so do NOT pay for it twice."""
    body = _code(_fn(_read(*_ORCH), "_parse_plan", cls="SecretaryOrchestrator"))
    assert 'if "_preplanned" in cmd:' in body, "the absent/falsy distinction is gone"
    assert "return None" in body


def test_preplan_touches_no_qt_object():
    """It runs on a worker thread. Anything Qt in here is an access violation."""
    body = _fn(_read(*_ORCH), "preplan", cls="SecretaryOrchestrator")
    for bad in ("QTimer", "QWidget", "QApplication", "setText", "setVisible", "QMessageBox"):
        assert bad not in body, "preplan touches Qt (%s) — it runs off the GUI thread" % bad


def test_the_orb_dispatches_planning_to_a_worker():
    src = _read(*_ORB)
    assert "preplan(" in src, "the orb no longer pre-plans off-thread"
    assert "_run_worker(" in src, "the planning worker helper is gone"
    assert "_secretary_async_enabled" in src, "the kill switch is gone"
    assert "AIPACS_ECHOMIND_SECRETARY_ASYNC" in src


def test_execution_and_the_modal_dialog_stay_on_the_gui_thread():
    """`_secretary_execute_and_render` must be the GUI-thread half. If the
    confirm dialog ever moved onto a worker it would deadlock or crash."""
    body = _fn(_read(*_ORB), "_secretary_execute_and_render", cls="SecretaryButtonWidget")
    assert "_show_secretary_confirm_dialog" in body
    assert "handle(" in body


def test_the_whole_pipeline_holds_a_busy_lock():
    """The old guard only checked the STT worker, so once THAT finished a second
    command could start on top of an in-flight execution — and
    `home_widget_adapter.search` pumps `processEvents` for up to 45 s, which is
    exactly what delivers the orb click that starts it."""
    src = _read(*_ORB)
    assert "_secretary_busy" in src, "the pipeline-wide re-entrancy lock is gone"
    guard = _code(_fn(src, "_stop_recording_and_process", cls="SecretaryButtonWidget"))
    assert "self._secretary_busy" in guard, "the guard no longer checks the pipeline lock"


def test_every_exit_path_releases_the_busy_lock():
    """A lock that leaks on an error path wedges the orb for the session."""
    body = _code(_fn(_read(*_ORB), "_stop_recording_and_process", cls="SecretaryButtonWidget"))
    # one release per early return after the lock is taken, plus the worker paths
    assert body.count("_finish_secretary_cycle()") >= 3, (
        "not every early exit releases the pipeline lock — the orb will wedge"
    )


def test_progress_callback_marshals_with_a_context_object():
    """`progress_cb` is now invoked from the PLANNING thread. Two-arg
    `QTimer.singleShot(0, fn)` creates the timer on the calling thread, which
    has no event loop, so the stage label would never update."""
    body = _code(_fn(_read(*_ORB), "_stop_recording_and_process", cls="SecretaryButtonWidget"))
    assert "_call_on_gui" in body, "the progress callback does not marshal safely"


# ── 2. panel open is not an N+1 ──────────────────────────────────────────────

def test_panel_open_does_not_fetch_every_message_of_every_session():
    body = _code(_fn(_read(*_PAGES), "_load_from_db_and_render", cls="OneChatPage"))
    assert "ai_count_messages_by_session" in body, "the counts query is gone"
    # Fetching the ONE session that is about to be rendered is correct and
    # necessary. What must never come back is a fetch per session in the
    # sidebar loop, so pin the count at one.
    assert body.count("ai_fetch_messages_full") <= 1, (
        "the N+1 is back: opening the panel reads the full HTML body of every "
        "message of every session in order to display one (%d fetch sites)"
        % body.count("ai_fetch_messages_full")
    )
    # AST, not text slicing: the ONE legitimate fetch (the session being
    # rendered) sits after the loop, and a substring cut cannot tell them apart.
    fn_src = _fn(_read(*_PAGES), "_load_from_db_and_render", cls="OneChatPage")
    fn_node = ast.parse(fn_src.lstrip()).body[0]
    loops = [
        n for n in ast.walk(fn_node)
        if isinstance(n, ast.For) and "ordered" in ast.unparse(n.iter)
    ]
    assert loops, "the sidebar loop moved — re-anchor this guard"
    for loop in loops:
        inner = "\n".join(ast.unparse(s) for s in loop.body)
        assert "ai_fetch_messages_full" not in inner, (
            "the per-session fetch is back INSIDE the sidebar loop — that is "
            "the N+1: one full-message read per session, to display one"
        )


def test_the_counts_helper_is_one_query():
    src = _read("database", "ai_sessions_db.py")
    node = ast.parse(_fn(src, "ai_count_messages_by_session").lstrip()).body[0]
    # drop the docstring: it explains the OLD query it replaced, by quoting it
    stmts = node.body[1:] if (
        node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    ) else node.body
    body = "\n".join(ast.unparse(n) for n in stmts).upper()
    assert "GROUP BY" in body
    assert body.count("SELECT") == 1, "the counts helper is doing more than one query"


def test_the_counts_helper_is_reachable_through_the_facade():
    """`ai_chat_pages` calls it as `U.ai_count_messages_by_session`."""
    import importlib
    utils = importlib.import_module("PacsClient.utils")
    assert hasattr(utils, "ai_count_messages_by_session"), (
        "the panel-open path will AttributeError at runtime"
    )


# ── 3. the debug helpers are free when debug logging is off ──────────────────

@pytest.mark.parametrize("name", ["_dbg_request", "_dbg_response"])
def test_debug_helpers_check_the_level_before_doing_work(name):
    body = _code(_fn(_read(*_PAGES), name))
    lines = [l for l in body.splitlines() if l.strip() and not l.strip().startswith(('"""', "'''"))]
    joined = "\n".join(lines)
    assert "isEnabledFor" in joined, "%s does its work before checking the level" % name
    # the guard must come before the expensive call
    if "json.dumps" in joined:
        assert joined.index("isEnabledFor") < joined.index("json.dumps"), (
            "the payload is still serialised before the level check"
        )


def test_dbg_response_does_not_touch_resp_text_first():
    """`requests` does not cache `.text`: each access re-decodes the whole body,
    and with no charset header it runs full charset detection over a 100-500 KB
    report."""
    body = _code(_fn(_read(*_PAGES), "_dbg_response"))
    assert "Content-Length" in body, "the cheap header path is gone"


def test_debug_helpers_do_not_need_the_logging_name():
    """`test_no_clinical_content_on_stdout` extracts these two with ast and
    execs them in a bare namespace that has `_log` but not `logging`."""
    for name in ("_dbg_request", "_dbg_response"):
        body = _fn(_read(*_PAGES), name)
        assert "import logging" in body, (
            "%s references the logging module without importing it locally — "
            "the extracted-helper test will NameError" % name
        )


# ── 4. row_factory does not leak between pooled connections ──────────────────

def test_pool_resets_row_factory_before_reuse():
    body = _code(_fn(_read(*_POOL), "_return_to_pool"))
    assert "row_factory" in body, (
        "a connection can go back into the pool still set to sqlite3.Row, so "
        "the next borrower silently gets Row objects instead of tuples"
    )


# ── 5. the two growing tables have an index on their lookup column ───────────

@pytest.mark.parametrize("path,table,column", [
    (("database", "consultation_db.py"), "consultation_events", "consultation_id"),
    (("database", "notifications_db.py"), "notifications", "status"),
])
def test_growing_tables_are_indexed_on_the_column_they_are_queried_by(path, table, column):
    src = _read(*path)
    assert "CREATE INDEX" in src and table in src and column in src, (
        "%s has no index on %s — every lookup is a full scan of a table that "
        "is never pruned" % (table, column)
    )
