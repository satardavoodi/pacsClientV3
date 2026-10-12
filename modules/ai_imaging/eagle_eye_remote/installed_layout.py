"""Server-only immutable sibling payload selection, bound by the core seal."""
import json
from pathlib import Path

from . import release_package

NAME = 'eagle-eye-payloads.json'


def release_tree(core):
    core = Path(core).resolve()
    if core.name != 'core':
        raise ValueError('Immutable Server layout requires a dedicated core directory.')
    return core.parent


def seal(core, packages):
    """Run before the core stamp; never alter a previously sealed release."""
    core = Path(core).resolve()
    packages = Path(packages).resolve()
    tree = release_tree(core)
    if packages != tree / 'plugin_packages' or not packages.is_dir():
        raise ValueError('Server payloads require the release-local plugin_packages directory.')
    if (core / release_package.NAME).exists():
        raise ValueError('A stamped Server core is immutable.')
    files = {}
    for path in sorted(packages.rglob('*')):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('Immutable Server payloads cannot contain reparse links.')
        if path.is_file():
            files[path.relative_to(packages).as_posix()] = release_package._digest(path)
    if not files:
        raise ValueError('Server payload inventory cannot be empty.')
    with (core / NAME).open('x', encoding='utf-8') as stream:
        json.dump({'schema': 1, 'root': 'plugin_packages', 'files': files}, stream, sort_keys=True)


def selection(core):
    """Verify the core-bound selector; payload bytes are checked by activation."""
    core = Path(core).resolve()
    tree = release_tree(core)
    manifest = release_package.read(core)
    if NAME not in manifest['files'] or release_package._digest(core / NAME) != manifest['files'][NAME]:
        raise ValueError('Immutable Server payload selector is absent or changed.')
    value = json.loads((core / NAME).read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or set(value) != {'schema', 'root', 'files'}
            or value['schema'] != 1 or value['root'] != 'plugin_packages'
            or not isinstance(value['files'], dict) or not value['files']):
        raise ValueError('Invalid immutable Server payload selector.')
    packages = tree / 'plugin_packages'
    for path in (tree, core, packages):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('Immutable Server release paths cannot contain reparse links.')
    return [{'root': str(packages), 'files': value['files']}]


def payload_scope(core, payloads):
    """Legacy synthetic layouts remain supported; sibling layouts require a seal."""
    core = Path(core).resolve()
    if (core / NAME).exists():
        selected = selection(core)
        if selected != payloads:
            raise ValueError('Server payload selection differs from its sealed core.')
        return release_tree(core)
    return core
