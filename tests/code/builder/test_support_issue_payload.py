"""Owned issue-reporting catalog and transport must ship in matching payloads."""
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_owned_issue_mirrors_match_source():
    files = {
        'echomind': [
            'modules/EchoMind/secretary/adapters/support_command_adapter.py',
            'modules/EchoMind/secretary/bus_factory.py',
            'modules/EchoMind/secretary/command_envelope.py',
            'modules/EchoMind/secretary/permissions.py',
            'modules/EchoMind/secretary/validator.py',
            'modules/EchoMind/secretary/catalog/catalog.yaml',
            'modules/EchoMind/secretary/catalog/modules/support_control.md'],
        'identity': ['modules/Identity/providers/aipacs_web.py',
                     'modules/Identity/providers/support_origin.py'],
    }
    for plugin, paths in files.items():
        for relative in paths:
            source = ROOT / relative
            payload = ROOT / 'builder/plugin package/packages' / plugin / 'payload/python' / relative
            assert payload.is_file(), relative
            assert sha256(source.read_bytes()).digest() == sha256(payload.read_bytes()).digest(), relative


def test_server_issue_snapshot_has_matching_receipt():
    root = ROOT / 'modules/ai_imaging/eagle_eye_remote/secretary'
    manifest = json.loads((root / 'snapshot_manifest.json').read_text(encoding='utf-8'))
    for relative in ('validation/validator.py', 'assets/catalog.yaml', 'assets/modules/support_control.md'):
        assert sha256((root / relative).read_bytes()).hexdigest() == manifest['files'][relative.replace('/', '\\')]
