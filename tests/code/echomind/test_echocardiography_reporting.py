"""Dedicated cardiac dictation must survive the client/server boundary."""
import ast
import json
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parents[3]
CLIENT = ROOT / 'modules/EchoMind'
SERVER = ROOT / 'modules/ai_imaging/eagle_eye_remote/echomind'


def prompt(root, template=''):
    path = root / 'viewer_chat/openai_reporter.py'
    tree = ast.parse(path.read_text('utf-8'))
    function = next(x for x in tree.body if isinstance(x, ast.FunctionDef)
                    and x.name == 'build_report_system_prompt')
    ns = {'Optional': Optional, '_to_str': lambda v: str(v or '')}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), ns)
    return ns['build_report_system_prompt']('ECHOCARDIOGRAPHY', template)


def test_echo_is_selectable_and_has_its_own_template_category():
    from modules.EchoMind.ai_chat_config import REPORT_MODALITIES
    from modules.EchoMind.normal_templates import canonical_modality
    assert 'ECHOCARDIOGRAPHY' in REPORT_MODALITIES
    for alias in ['ECHOCARDIOGRAPHY', 'echo', 'echocardiogram', 'tte', 'tee']:
        assert canonical_modality(alias) == 'ECHOCARDIOGRAPHY'
    assert canonical_modality('US') == 'SONOGRAPHY'


@pytest.mark.parametrize('root', [CLIENT, SERVER / 'core'])
def test_echo_prompt_preserves_measurements_and_does_not_invent_normals(root):
    p = prompt(root, 'CARDIAC_TEMPLATE_SENTINEL')
    for term in ['ECHOCARDIOGRAPHY', 'LVEF', 'TAPSE', 'MR means mitral regurgitation',
                 'Do not invent', 'diastolic', 'TTE', 'TEE', 'stress',
                 'CARDIAC_TEMPLATE_SENTINEL', 'FINAL TEMPLATE PRECEDENCE',
                 'OUTPUT FORMAT (STRICT)', 'one numbered finding per paragraph']:
        assert term in p
    assert 'BI-RADS' not in p


def test_server_request_accepts_echo_and_rejects_unknown_modality():
    from modules.ai_imaging.eagle_eye_remote.echomind.service import ProcessRequest
    assert ProcessRequest(text='Synthetic cardiac dictation', modality='ECHOCARDIOGRAPHY').modality == 'ECHOCARDIOGRAPHY'
    with pytest.raises(ValueError):
        ProcessRequest(text='Synthetic dictation', modality='UNKNOWN')


def test_client_and_server_echo_prompt_are_identical():
    assert prompt(CLIENT) == prompt(SERVER / 'core')


def test_echo_empty_pathology_does_not_assert_a_normal_exam():
    from modules.ai_imaging.eagle_eye_remote.echomind.core.viewer_chat.openai_reporter import _validate_report_json
    raw = json.dumps({'Report Title': 'Echocardiography', 'Pathological Findings': '', 'Normal Findings': ''})
    result = _validate_report_json(raw, 'ECHOCARDIOGRAPHY')
    parsed = json.loads(result) if isinstance(result, str) else result
    assert parsed['Pathological Findings'] == 'No pathological findings were provided.'


@pytest.mark.parametrize('workflow', ['report', 'turbo'])
def test_remote_transport_builds_echo_prompt_only_on_server(monkeypatch, workflow):
    from modules.EchoMind import remote_backend, normal_templates
    from modules.ai_imaging.eagle_eye_remote.echomind import service
    seen = {}

    def fake_provider(text, modality, normal_template, **kwargs):
        seen['prompt'] = kwargs.get('system_prompt_override') or service.company.build_report_system_prompt(modality, normal_template)
        return {'content': {'Report Title': 'Echocardiography',
                            'Pathological Findings': 'Left ventricle:\n1. LVEF 40%.',
                            'Normal Findings': '', 'Impression': None,
                            'Recommendations': None}, 'usage': {}}

    def transport(kind, text, **fields):
        assert 'system_prompt_override' not in fields
        assert 'system_prompt' not in fields
        seen['modality'] = fields['modality']
        return service._process(service.ProcessRequest(text=text, workflow=kind, **fields))

    monkeypatch.setattr(service.company, 'reporter', fake_provider)
    monkeypatch.setattr(remote_backend, '_request', transport)
    monkeypatch.setattr(normal_templates, 'remember_report_template', lambda *args: None)
    result = remote_backend.reporter('Synthetic dictation: LVEF 40%.',
                                     'ECHOCARDIOGRAPHY', workflow=workflow)
    assert result['content']['Report Title'] == 'Echocardiography'
    assert seen['modality'] == 'ECHOCARDIOGRAPHY'
    assert 'dedicated cardiac reporting contract' in seen['prompt']
