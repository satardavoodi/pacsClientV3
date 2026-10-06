"""Reception sends must obtain consent before replacing another dictation."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace
import time
from datetime import datetime
import pytest

from PySide6.QtWidgets import QMessageBox


def worker(monkeypatch, record, **state):
    import modules.network.reception_api_config as config
    monkeypatch.setattr(config, "get_reception_api_base_url", lambda: "http://test.invalid")
    source = Path("modules/EchoMind/viewer_chat/ai_chat_pages.py").read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == "_send_with_patient_id")
    writes = []
    def save(**kwargs):
        writes.append(kwargs)
        raise RuntimeError("Stop before any real persistence")
    env = dict(logger=logging.getLogger(__name__), time=time, QMessageBox=QMessageBox,
               requests=SimpleNamespace(get=lambda *a, **k: SimpleNamespace(
                   ok=True, status_code=200, headers={}, json=lambda: record)),
               ai_save_reception_report=save, self=SimpleNamespace(study_uid="synthetic"),
               bubble=SimpleNamespace(), html_content="new", send_mode="current",
               selected_status="pending", server_source="new", datetime=datetime,
               report_choice=None, report_snapshot=None)
    env.update(state)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 "<isolated-send-worker>", "exec"), env)
    return env["_send_with_patient_id"]("synthetic"), writes


def test_existing_report_requires_consent_before_any_write(monkeypatch):
    result, writes = worker(monkeypatch, {"success": True, "data": {
        "report": {"content": "<p>First synthetic report</p>"}}})
    assert result.get("needs_report_choice") is True
    assert writes == []


def test_changed_report_requires_fresh_consent(monkeypatch):
    result, writes = worker(monkeypatch, {"data": {"report": {"content": "Changed"}}},
                            report_choice="append", report_snapshot="Previous")
    assert result.get("needs_report_choice") is True
    assert writes == []


def test_invalid_response_never_writes(monkeypatch):
    result, writes = worker(monkeypatch, {"success": False, "data": None})
    assert not result["ok"]
    assert writes == []


@pytest.mark.parametrize("record", [{"message": "unexpected"}, {"data": []},
                                     {"report": {"content": {"unknown": "format"}}}])
def test_unknown_shapes_fail_closed(record):
    from PacsClient.utils.reception_report_merge import existing_report_html
    with pytest.raises(ValueError):
        existing_report_html(record)


@pytest.mark.parametrize("choice,previous", [(None, ""), ("append", "<p>First</p>"),
                                             ("replace", "<p>First</p>")])
def test_actual_outgoing_payload(monkeypatch, choice, previous):
    import modules.network.socket_token_manager as tokens
    import modules.network.ino_report_workflow as workflow
    monkeypatch.setattr(tokens, "get_socket_token_manager", lambda: SimpleNamespace(get_token=lambda: "synthetic"))
    monkeypatch.setattr(workflow, "sync_report_approval_for_status_async", lambda *a: None)
    posts = []
    def post(url, **kwargs):
        posts.append(kwargs["json"])
        return SimpleNamespace(ok=True, status_code=200, text="{}", headers={}, json=lambda: {})
    record = {"data": {"report": {"content": previous}}}
    result, _ = worker(monkeypatch, record, report_choice=choice, report_snapshot=previous,
                       ai_save_reception_report=lambda **k: 1,
                       requests=SimpleNamespace(post=post, get=lambda *a, **k: SimpleNamespace(
                           ok=True, status_code=200, headers={}, json=lambda: record)))
    assert result["ok"]
    assert len(posts) == 1
    assert posts[0]["receptionId"] == "synthetic"
    assert posts[0]["content"] == posts[0]["findings"]
    assert "new" in posts[0]["content"]
    assert ("First" in posts[0]["content"]) == (choice == "append")


@pytest.mark.parametrize("content", ["", "<p><br/></p>", "<p>&nbsp;</p>", "<html><head><style>p{color:red}</style></head><body></body></html>"])
def test_empty_markup_is_not_a_report(content):
    from PacsClient.utils.reception_report_merge import existing_report_html
    assert existing_report_html({"data": {"report": {"content": content}}}) == ""


def test_append_preserves_inline_formatting_and_document_order():
    from PacsClient.utils.reception_report_merge import append_report_html
    old = '<p dir="rtl" style="color:red">First</p>'
    result = append_report_html(old, '<html><body dir="ltr"><p>Second</p></body></html>')
    assert result.startswith(old + '\n<hr />')
    assert '<div dir="ltr"><p>Second</p></div>' in result
    assert '<html>' not in result


def test_cancel_dialog_never_dispatches_send():
    source = Path("modules/EchoMind/viewer_chat/ai_chat_pages.py").read_text(encoding="utf-8")
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == "_deliver_reception_result")
    node.body = [n for n in node.body if not isinstance(n, ast.Nonlocal)]
    class Box:
        Icon = QMessageBox.Icon
        ButtonRole = QMessageBox.ButtonRole
        StandardButton = QMessageBox.StandardButton
        def __init__(self, *a): pass
        def __getattr__(self, name): return lambda *a: None
        def addButton(self, *a): return object()
        def clickedButton(self): return None
    calls = []
    env = dict(QMessageBox=Box, self=SimpleNamespace(_run_async=lambda *a, **k: calls.append(1)),
               _set_bubble_status=lambda *a: None)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), "<consumer>", "exec"), env)
    env["_deliver_reception_result"]({"needs_report_choice": True, "existing_html": "First"})
    assert calls == []
