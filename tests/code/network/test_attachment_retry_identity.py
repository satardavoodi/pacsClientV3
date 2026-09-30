"""Synthetic wire/manifest tests; no application imports or live SQLite access."""
import ast
from contextlib import nullcontext
import hashlib
import importlib.util
import json
import logging
from pathlib import Path
import socket
import threading
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Union
import base64
import os
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def isolated(tmp_path):
    spec = importlib.util.spec_from_file_location('isolated_pending', ROOT / 'modules/network/attachment_pending_sync.py')
    pending = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pending)
    pending._manifest_path = lambda uid: tmp_path / uid / '.pending_sync.json'
    tree = ast.parse((ROOT / 'modules/network/upload_download_attchments.py').read_text(encoding='utf-8'))
    ns = dict(globals(), ATTACHMENT_PATH=tmp_path,
              get_socket_config=lambda: SimpleNamespace(get_socket_host=lambda: 'localhost', get_socket_port=lambda: 1),
              get_socket_token_manager=lambda: SimpleNamespace(add_token_to_request=lambda r: r),
              append_attachments_uploaded=lambda **kw: None,
              list_files_in_folder=lambda p: [str(x) for x in p.glob('*.wav')],
              mark_pending=pending.mark_pending, mark_synced=pending.mark_synced,
              record_attempt=pending.record_attempt,
              get_upload_id=getattr(pending, 'get_upload_id', None))
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'isolated-upload', 'exec'), ns)
    return pending, ns


def test_persistent_identity_changes_only_when_content_changes(isolated):
    pending, _ = isolated
    a = pending.get_upload_id('1.2', 'voice.wav', 'abc')
    pending.record_attempt('1.2', 'voice.wav')
    pending._study_locks.clear()  # Simulate a new process reading the manifest.
    assert pending.get_upload_id('1.2', 'voice.wav', 'abc') == a
    pending.mark_synced('1.2', 'voice.wav')
    assert pending.get_upload_id('1.2', 'voice.wav', 'abc') == a
    assert pending.get_upload_id('1.2', 'voice.wav', 'changed') != a


def test_identity_write_failure_prevents_upload(isolated, monkeypatch):
    pending, _ = isolated
    monkeypatch.setattr(pending.os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('disk')))
    with pytest.raises(OSError):
        pending.get_upload_id('1.2', 'voice.wav', 'abc')


def test_corrupt_identity_is_preserved_on_failure(isolated):
    pending, _ = isolated
    path = pending._manifest_path('1.2')
    path.parent.mkdir()
    path.write_text('{broken')
    with pytest.raises(ValueError):
        pending.get_upload_id('1.2', 'voice.wav', 'abc')
    pending.mark_pending('1.2', 'voice.wav')
    assert path.read_text() == '{broken'


def test_bulk_pending_clear_preserves_corrupt_retry_identity(isolated):
    pending, _ = isolated
    path = pending._manifest_path('1.2')
    path.parent.mkdir()
    path.write_text('{broken')
    pending.clear_all_pending('1.2')
    assert path.read_text() == '{broken'


@pytest.mark.parametrize('damage', ['corrupt', 'missing', 'write_failure'])
def test_attempt_does_not_send_after_identity_corrupts(isolated, tmp_path, monkeypatch, damage):
    pending, ns = isolated
    folder = tmp_path / '1.2'; folder.mkdir()
    (folder / 'voice.wav').write_bytes(b'voice')
    sent = []
    class Client:
        def supports_idempotent_upload(self):
            if damage == 'corrupt':
                pending._manifest_path('1.2').write_text('{broken')
            elif damage == 'missing':
                pending._manifest_path('1.2').unlink()
            else:
                monkeypatch.setattr(pending, '_save_manifest', lambda *args: False)
            return True
        def send_request(self, *args):
            sent.append(args)
            return {'status': 'success'}
    result = ns['upload_attachments_for_study']('1.2', '', client=Client(), verbose=False)
    assert result['failed'] == 1
    assert sent == []


@pytest.mark.parametrize('response, supported', [
    ({'status': 'error', 'error': 'Unknown endpoint'}, False),
    ({'status': 'success', 'data': {'idempotency_version': 1}}, True),
])
def test_capability_negotiation_is_explicit(isolated, response, supported):
    _, ns = isolated
    client = ns['SocketClient']()
    calls = []
    client.send_request = lambda *args: (calls.append(args), response)[1]
    assert client.supports_idempotent_upload() is supported
    assert client.supports_idempotent_upload() is supported
    assert len(calls) == 1


def test_timeout_reconnects_and_reuses_identity(isolated, tmp_path):
    pending, ns = isolated
    folder = tmp_path / '1.2'; folder.mkdir()
    (folder / 'voice.wav').write_bytes(b'synthetic voice')
    events, identities = [], []
    class Client:
        def supports_idempotent_upload(self):
            return True
        def disconnect(self):
            events.append('disconnect')
        def connect(self):
            events.append('connect')
        def send_request(self, endpoint, params):
            events.append('send')
            identities.append(params.get('upload_id'))
            if len(identities) == 1:
                raise TimeoutError('lost acknowledgement')
            return {'status': 'success'}
    result = ns['upload_attachments_for_study']('1.2', '', client=Client(), verbose=False)
    assert result['success'] == 1
    assert events == ['send', 'disconnect', 'connect', 'send']
    assert identities[0] and identities[0] == identities[1]
    assert pending.get_pending_files('1.2') == []


def test_legacy_ambiguous_upload_is_not_blindly_retried(isolated, tmp_path):
    pending, ns = isolated
    folder = tmp_path / '1.2'; folder.mkdir()
    (folder / 'voice.wav').write_bytes(b'voice')
    calls = []
    class Legacy:
        def send_request(self, *args):
            calls.append(1)
            raise TimeoutError()
        def disconnect(self):
            pass
    result = ns['upload_attachments_for_study']('1.2', '', client=Legacy(), verbose=False)
    assert result['failed'] == 1 and len(calls) == 1
    assert pending.get_pending_files('1.2') == ['voice.wav']


def test_retry_bookkeeping_is_never_uploaded(isolated, tmp_path):
    pending, ns = isolated
    folder = tmp_path / '1.2'; folder.mkdir()
    (folder / 'voice.wav').write_bytes(b'voice')
    pending.get_upload_id('1.2', 'voice.wav', 'hash')
    (folder / '.psync_tmp_interrupted').write_text('{}')
    ns['list_files_in_folder'] = lambda p: [str(x) for x in p.iterdir()]
    names = []
    class Client:
        def send_request(self, endpoint, params):
            names.append(params['file_name'])
            return {'status': 'success'}
    result = ns['upload_attachments_for_study']('1.2', '', client=Client(), verbose=False)
    assert result['total'] == result['success'] == 1
    assert names == ['voice.wav']


def test_truncated_frame_and_wrong_correlation_rejected(isolated):
    _, ns = isolated
    client = ns['SocketClient']()
    class Wire:
        def shutdown(self, *args):
            pass
        def close(self):
            pass
        def sendall(self, data):
            pass
        def recv(self, size):
            return b''
    client.socket = Wire()
    with pytest.raises(ConnectionError):
        client._recvall(4)
    response = json.dumps({'status': 'success', 'request_id': 'unrelated'}).encode()
    data = iter([len(response).to_bytes(4, 'big'), response])
    client._recvall = lambda n: next(data)
    with pytest.raises(ConnectionError, match='correlation'):
        client.send_request('UploadAttachment', {})
