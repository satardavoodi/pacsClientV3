"""Immutable Server core identity and host-adapted coordinated activation.

The activation adapter must hold admission closed for the complete context, drain
model/text/CRM work, retain old binaries, verify authenticated application health,
and persist its journal. This module never guesses credentials or kills processes.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

NAME = 'eagle-eye-release.json'


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _identity(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def stamp(root, version):
    root=Path(root).resolve()
    if not (root/'AIPacs.exe').is_file():
        raise ValueError('The Server package executable is missing.')
    if (root/NAME).exists():
        raise ValueError('A completed Server package is immutable.')
    files={}
    for path in sorted(root.rglob('*')):
        if path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Package files must remain inside the immutable core.')
            files[path.relative_to(root).as_posix()]=_digest(path)
    data={'schema':1,'edition':'eagle-eye','version':str(version),'files':files}
    data['release_id']=_identity(data)
    target=root/NAME
    with target.open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(data,indent=2)+'\n')
    return data


def read(root):
    root=Path(root).resolve()
    data=json.loads((root/NAME).read_text(encoding='utf-8'))
    if not isinstance(data,dict) or set(data)!={'schema','edition','version','files','release_id'}:
        raise ValueError('Invalid Server release manifest.')
    if data['schema']!=1 or data['edition']!='eagle-eye' or not isinstance(data['files'],dict) or 'AIPacs.exe' not in data['files']:
        raise ValueError('Invalid Server release manifest.')
    body={k:v for k,v in data.items() if k!='release_id'}
    if data['release_id']!=_identity(body):
        raise ValueError('Server release manifest digest does not match.')
    for name,digest in data['files'].items():
        p=PurePosixPath(name)
        if (not name or p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name
                or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)
                or not (root/name).resolve().is_relative_to(root)):
            raise ValueError('Invalid Server package file boundary.')
    return data


def verify(root, *, executable_only=False):
    root=Path(root).resolve();data=read(root)
    for name,digest in data['files'].items():
        if executable_only and name!='AIPacs.exe':
            continue
        path=root/name
        if not path.is_file() or path.is_symlink() or _digest(path)!=digest:
            raise ValueError('Server package is incomplete or contains mixed versions.')
    return data


def runtime_identity():
    from aipacs_runtime import is_frozen, install_root
    if not is_frozen():
        return {'qualified':False,'mode':'developer'}
    data=verify(install_root(),executable_only=True)
    return {'qualified':True,'release_id':data['release_id'],'version':data['version'],'edition':'eagle-eye'}


def require_same_release(expected, actual):
    if (not expected.get('qualified') or not actual.get('qualified')
            or expected.get('release_id')!=actual.get('release_id')):
        raise ValueError('Server desktop and active service belong to different packages. Complete the coordinated update first.')


def check_installed_service(config_path, client_settings):
    from .service_admin import inspect_service
    from .client import Client
    state=inspect_service(config_path)
    if not state.get('owned') or not state.get('running'):
        raise ValueError('This Server package does not own a running service. Complete Server setup or its coordinated update first.')
    expected=runtime_identity()
    with Client(client_settings).open('/v1/capabilities',timeout=10) as response:
        raw=response.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:
        raise ValueError('Server capability response exceeds the limit.')
    actual=json.loads(raw).get('deployment') or {}
    require_same_release(expected,actual)


def transition(host, candidate):
    """Publish the shared GUI/service selection only after verified application health.

    Adapter integration is explicit; no plain SCM RUNNING result counts as health.
    A failed rollback remains journaled for operator recovery instead of being hidden.
    """
    with host.quiesce():
        previous=host.snapshot()
        host.verify(candidate)
        host.verify(previous)
        host.drain()
        host.journal('prepared',previous=previous,candidate=candidate)
        changed=False
        try:
            changed=True
            host.stop()
            host.select_service(candidate)
            host.journal('service_selected',previous=previous,candidate=candidate)
            host.start()
            if not host.healthy(candidate):
                raise RuntimeError('New Server package failed authenticated health verification.')
            host.publish(candidate)
            host.journal('committed',previous=previous,candidate=candidate)
        except Exception:
            if changed:
                try:
                    host.stop()
                    host.select_service(previous)
                    host.start()
                    if not host.healthy(previous):
                        raise RuntimeError('Previous Server package did not recover.')
                    host.publish(previous)
                    host.journal('rolled_back',previous=previous,candidate=candidate)
                except Exception:
                    host.journal('recovery_required',previous=previous,candidate=candidate)
                    raise RuntimeError('Server update failed and requires operator recovery.') from None
            raise RuntimeError('Server update failed; previous package restored.') from None
