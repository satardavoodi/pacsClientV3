"""Attach a private CRM configuration through the existing server settings owner."""
import json
import os
from pathlib import Path
from ..administration import read_connection, _save, settings_role


def snapshot():
    path = os.environ.get('AIPACS_EAGLE_EYE_SERVER_CONFIG')
    if settings_role() != 'server' or not path:
        return {'editable': False}
    value = read_connection(path)
    crm = value['value'].get('crm', {})
    return {'editable': True, 'path': path, 'revision': value['revision'],
            'config_dir': crm.get('config_dir', ''), 'enabled': bool(crm)}


def attach(path, revision, directory, enabled):
    if settings_role() != 'server' or path != os.environ.get('AIPACS_EAGLE_EYE_SERVER_CONFIG'):
        raise ValueError('Only the local Server settings owner can configure CRM.')
    if enabled:
        root = Path(directory)
        if not root.is_absolute() or not (root / 'roles.json').is_file():
            raise ValueError('Select the private CRM directory with a roles policy.')
        config = json.loads((root / 'server.json').read_text(encoding='utf-8-sig'))
        if (not config.get('center') or not Path(config.get('data_root', '')).is_absolute()
                or not config.get('session_secret')):
            raise ValueError('CRM needs an explicit center, data directory and session secret.')
    def update(previous):
        if enabled and not previous.get('echomind'):
            raise ValueError('Configure the shared Eagle Eye AI gateway first.')
        result = dict(previous)
        if enabled:
            result['crm'] = {'config_dir': str(root), 'max_requests': 1}
        else:
            result.pop('crm', None)
        return result
    _save(path, revision, update)
    return snapshot()


def test_connection():
    value=snapshot()
    if not value.get('editable') or not value.get('config_dir'):
        raise ValueError('Configure the private Server CRM directory first.')
    from .diagnostics import run
    return run(value['config_dir'])
