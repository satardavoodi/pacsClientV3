"""Synthetic message receipt-time, content-isolation and storage compatibility checks."""
import ast
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_received_time_is_fixed_and_separate_from_export(app, monkeypatch):
    from modules.EchoMind.viewer_chat import ai_chat_widgets as widgets
    monkeypatch.setattr(widgets.time, 'time', lambda: 1800000000)
    bubble = widgets.MessageBubble('AI ChatBot', '<p>Synthetic answer</p>')
    expected = datetime.fromtimestamp(1800000000).astimezone().strftime('%Y-%m-%d  %H:%M')
    assert bubble.created_at == 1800000000
    assert bubble.timestamp_label.text() == expected
    monkeypatch.setattr(widgets.time, 'time', lambda: 1800003600)
    bubble.set_html('<p>Edited synthetic answer</p>')
    bubble.set_font_size(20)
    assert bubble.timestamp_label.text() == expected
    assert expected not in bubble.get_html()
    assert expected not in bubble.get_export_html()
    bubble.deleteLater()


def test_history_uses_recorded_time_and_never_fabricates_missing_time(app):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import ChatHistory
    history = ChatHistory()
    saved = history.add_bubble('You', 'Synthetic request', created_at=1800000000)
    assert saved.created_at == 1800000000
    restored = history.add_bubble('AI ChatBot', 'Synthetic old response', created_at=None)
    assert restored.created_at is None
    assert restored.timestamp_label.text() == 'Time unavailable'
    history.clear()
    history.deleteLater()


def test_timestamp_read_preserves_legacy_four_field_api():
    # Execute the repository's pure query function against in-memory synthetic
    # SQLite only; never import the application database or its clinical pool.
    tree = ast.parse(Path('database/ai_sessions_db.py').read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'ai_fetch_messages_full')
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute('CREATE TABLE ai_messages(id INTEGER, sid TEXT, who TEXT, html TEXT, origin TEXT, created_at INTEGER)')
        connection.execute('INSERT INTO ai_messages VALUES(1, ?, ?, ?, ?, ?)',
                           ('synthetic-session', 'AI ChatBot', 'Synthetic response', 'report', 1800000000))
        scope = {'get_db_connection': lambda: connection}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<timestamp-query>', 'exec'), scope)
        fetch = scope['ai_fetch_messages_full']
        assert fetch('synthetic-session') == [(1, 'AI ChatBot', 'Synthetic response', 'report')]
        assert fetch('synthetic-session', include_created_at=True) == [(1, 'AI ChatBot', 'Synthetic response', 'report', 1800000000)]
        assert fetch('different-session', include_created_at=True) == []
    finally:
        connection.close()
