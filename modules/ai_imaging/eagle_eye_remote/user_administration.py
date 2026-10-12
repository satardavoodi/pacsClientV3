"""Local console-only user management; no remote administrator bypass."""
import json
import os
from pathlib import Path

from .administration import settings_role
from .admin_auth import valid_session
from .contracts import MODULES
from .user_access import AccessStore


def console_store(session):
    if settings_role() != 'server' or not valid_session(session):
        raise PermissionError('An authenticated local Server administrator is required.')
    config_path = os.environ.get('AIPACS_EAGLE_EYE_SERVER_CONFIG')
    if not config_path or not Path(config_path).is_absolute():
        raise ValueError('Select the Server deployment configuration.')
    config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    path = (config.get('user_access') or {}).get('database') or str(Path(config['job_root']).parent/'user-access.sqlite3')
    return AccessStore(path, config.get('center_id','configured-pacs')), config


def snapshot(session):
    store, _ = console_store(session)
    return {'users':store.users(), 'modules':list(MODULES)}


def save(session, principal, changes):
    store, _ = console_store(session)
    store.grant(principal, changes, 'local-superadministrator')
    return snapshot(session)


def history(session, principal):
    store, _ = console_store(session)
    return store.audit(principal)


def import_pacs(session, username, password):
    from .pacs_identity import PacsIdentity
    store, config = console_store(session)
    configured = (config.get('user_access') or {}).get('providers')
    pacs = configured.get('pacs') if configured is not None else config.get('pacs')
    if not pacs:
        raise ValueError('No PACS identity source is configured.')
    adapter = PacsIdentity(pacs)
    token, _ = adapter.login(username, password)
    for user in adapter.roster(token):
        store.identify(user)
    return snapshot(session)


def import_reception(session, username, password):
    from .reception_identity import ReceptionIdentity
    store, config = console_store(session)
    configured = (config.get('user_access') or {}).get('providers') or {}
    reception = configured.get('reception')
    if not reception:
        raise ValueError('No Reception identity source is configured.')
    adapter = ReceptionIdentity(reception)
    token, _ = adapter._login(username, password, console=True)
    users = adapter.roster(token)
    for user in users:
        store.identify(user)
    return snapshot(session)
