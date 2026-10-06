"""Headless runtime negotiation without workstation registry dependencies."""
import hashlib
import json
from uuid import uuid4

import pytest


def snapshot():
    value = {'version': 1, 'workflow_binding_version': 1, 'actions': [
        {'action': 'read_patients', 'entities_schema': {'type': 'object'},
         'typed_entities': True, 'assistant_allowed': True,
         'side_effect': 'read_only', 'confirmation_required': False}]}
    value['digest'] = hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return value


def test_paired_server_accepts_and_acknowledges_runtime_contract(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary
    (tmp_path / 'settings.json').write_text('{}')
    echo = EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'echo')}, ['client'])
    service = Secretary({'history_dir': str(tmp_path / 'secretary')}, echo)
    monkeypatch.setattr(service, '_completion', lambda *args:
                        {'modules': ['homepage'], 'reason': 'Synthetic routing.'})
    caps = snapshot()
    response = service.process('client', dict(
        protocol=1, request_id=str(uuid4()), phase='route', text='Synthetic routing.',
        language='en', client_time='2026-10-02T12:00:00+03:30', runtime_capabilities=caps))
    assert response['capability_digest'] == caps['digest']
    assert response['plan'] is None


def test_runtime_contract_rejects_tampering():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import RuntimeCapabilities
    caps = snapshot()
    caps['actions'][0]['assistant_allowed'] = False
    with pytest.raises(ValueError):
        RuntimeCapabilities.model_validate(caps)


def test_bound_ordinal_open_is_not_rejected_as_missing_list():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import _ordinal_clarification
    assert _ordinal_clarification([
        {'action':'read_patients','entities':{}},
        {'action':'open_patient','entities':{'row_index':1,'list_id':'$list_id'}}]) is None
    assert _ordinal_clarification([
        {'action':'open_patient','entities':{'row_index':1,'list_id':'synthetic-receipt'}}]) is None
    assert _ordinal_clarification([
        {'action':'open_patient','entities':{'row_index':1}}]) is not None
