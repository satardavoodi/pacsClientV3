"""Synthetic Assist review, context selection and session isolation checks."""
import json
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QPlainTextEdit


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def conversation(app):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import ChatHistory
    from modules.EchoMind.viewer_chat.assist_context import AssistContext
    history = ChatHistory()
    box = QPlainTextEdit()
    sent = []
    composer = SimpleNamespace(box=box, set_tab_text=lambda key, text: box.setPlainText(text),
                               switch_tab=lambda key: None)
    context = AssistContext(history, composer, lambda *a, **k: sent.append((a, k)), lambda: False)
    yield history, context, box, sent
    history.clear()
    history.close()
    context.deleteLater()
    box.deleteLater()


def test_original_request_review_uses_original_not_answer(conversation):
    history, context, _, sent = conversation
    user = history.add_bubble('You (Web Search)', 'Synthetic initial question')
    answer = history.add_bubble('AI ChatBot', '<p>Synthetic answer</p>')
    history.add_bubble('You (Search)', 'A different question')
    next(action for action in answer.btnAssistReview.menu().actions() if action.text() == 'Radiopaedia').trigger()
    assert sent == [(('Synthetic initial question', 'Assistant'), {'assist_context': ()})]
    assert answer._assist_request is user


def test_selected_messages_current_html_in_chronological_order(conversation):
    history, context, _, _ = conversation
    first = history.add_bubble('You (Assistant)', 'First question')
    answer = history.add_bubble('AI ChatBot', '<p>Old answer</p>')
    history.add_bubble('You (Search)', 'Unselected question')
    answer.btnAssistSelect.click()
    first.btnAssistSelect.click()
    answer.set_html('<p>Edited answer</p>')
    payload = json.loads(context.prepare('Explain staging'))
    assert payload['request'] == 'Explain staging'
    assert [m['text'] for m in payload['reference_messages']] == ['First question', 'Edited answer']
    assert payload['reference_messages'][1]['role'] == 'assistant'


def test_memory_is_bounded_and_cleared_on_session_switch(conversation):
    history, context, _, _ = conversation
    for i in range(10):
        history.add_bubble('You (Search)' if i % 2 == 0 else 'AI ChatBot', f'Message {i}')
    assert len(json.loads(context.prepare('Continue'))['reference_messages']) == 6
    history.clear()
    assert context.prepare('New conversation') == 'New conversation'
    assert not context.entries


def test_pair_selection_includes_question_and_answer(conversation):
    history, context, box, sent = conversation
    user = history.add_bubble('You (Search)', 'Synthetic question')
    answer = history.add_bubble('AI ChatBot', '<p>Synthetic answer</p>')
    next(action for action in answer.btnAssistReview.menu().actions()
         if action.text() == 'Use request + answer for a follow-up').trigger()
    assert user.btnAssistSelect.isChecked() and answer.btnAssistSelect.isChecked()
    box.setPlainText('What is the staging?')
    context.send_followup('Web Search')
    assert sent[0][0] == ('What is the staging?', 'Web Search')
    assert 'reference_messages' not in sent[0][0][0]


def test_busy_review_does_not_send_or_replace_context(conversation):
    history, context, box, sent = conversation
    history.add_bubble('You (Search)', 'Question')
    answer = history.add_bubble('AI ChatBot', 'Answer')
    context.busy = lambda: True
    box.setPlainText('Follow up')
    context.review_original(answer, 'Search')
    context.send_followup('Search')
    assert not sent


def test_oversized_selected_context_is_rejected_without_truncation(conversation):
    history, context, _, _ = conversation
    bubble = history.add_bubble('You (Search)', 'x' * 180001)
    bubble.btnAssistSelect.click()
    with pytest.raises(ValueError, match='too large'):
        context.prepare('Follow up')


def test_welcome_and_non_assist_history_have_no_review_controls(conversation):
    history, _, _, _ = conversation
    welcome = history.add_bubble('AI ChatBot', 'Ready. Type and press Send.')
    assert not hasattr(welcome, 'btnAssistSelect')
    from modules.EchoMind.viewer_chat.ai_chat_widgets import ChatHistory
    report = ChatHistory()
    bubble = report.add_bubble('AI ChatBot', 'Report content')
    assert not hasattr(bubble, 'btnAssistSelect')
    report.close()


@pytest.mark.parametrize('mode,method', [('Web Search', 'web_search'), ('Assistant', 'assistant'), ('Search', 'search')])
def test_selected_context_reaches_worker_without_polluting_visible_question(conversation, monkeypatch, mode, method):
    import ast
    from pathlib import Path
    from modules.EchoMind import remote_backend
    history, context, box, _ = conversation
    question = history.add_bubble('You (Search)', 'Original synthetic question')
    answer = history.add_bubble('AI ChatBot', '<p>Synthetic prior answer</p>')
    context.select_pair(answer)
    sent, jobs, callbacks = [], [], []
    monkeypatch.setattr(remote_backend, 'selected', lambda: True)
    monkeypatch.setattr(remote_backend, method, lambda text: sent.append(text) or {'content': 'Synthetic result'})
    tree = ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    method_node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_send_with_mode')
    scope = {'is_active_backend_configured': lambda: True,
             '_log': SimpleNamespace(debug=lambda *a: None)}
    exec(compile(ast.Module(body=[method_node], type_ignores=[]), '<assist-send>', 'exec'), scope)
    def run(work, ok, err, **kwargs):
        jobs.append(work())
        callbacks.append((ok, err))
    page = SimpleNamespace(_assist_context=context, _busy_count=0,
                           _collect_request_images_base64=lambda: [],
                           composer=SimpleNamespace(box=box),
                           controller=SimpleNamespace(session_id=None, bubble=history.add_bubble),
                           _run_async=run)
    scope['_send_with_mode'](page, 'Explain the anatomy', mode)
    assert json.loads(sent[0])['request'] == 'Explain the anatomy'
    assert [m['text'] for m in json.loads(sent[0])['reference_messages']] == ['Original synthetic question', 'Synthetic prior answer']
    assert visible_question(history) == 'Explain the anatomy'
    snapshot = page._pending_retry['reference_text']
    answer.set_html('<p>Changed after request</p>')
    context.clear_selection()
    assert context.prepare('Explain the anatomy', snapshot) == snapshot
    assert len(jobs) == 1
    history.clear()
    for callback in callbacks[0]:
        callback({'content': 'Late response'} if callback is callbacks[0][0] else 'Late error')
    assert not context.entries


def visible_question(history):
    from modules.EchoMind.viewer_chat.assist_context import visible_text
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble
    return visible_text(history.findChildren(MessageBubble)[-1])
