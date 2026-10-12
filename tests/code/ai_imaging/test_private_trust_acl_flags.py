"""INHERIT_ONLY is not effective permission on the inspected Windows object."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def install_security(monkeypatch, *, users_flags=11, service_flags=0, users_mask=0x10000000):
    entries = [((0, 0), 0x10000000, 'S-1-5-32-544'),
               ((0, service_flags), 0x80000001, 'S-1-5-19'),
               ((0, users_flags), users_mask, 'S-1-5-32-545')]
    acl = SimpleNamespace(GetAceCount=lambda: len(entries), GetAce=lambda n: entries[n])
    sd = SimpleNamespace(GetSecurityDescriptorOwner=lambda: 'S-1-5-32-544',
                         GetSecurityDescriptorDacl=lambda: acl)
    security = SimpleNamespace(SE_FILE_OBJECT=1, OWNER_SECURITY_INFORMATION=1,
        DACL_SECURITY_INFORMATION=4, GetNamedSecurityInfo=lambda *args: sd,
        ConvertSidToStringSid=lambda sid: sid)
    monkeypatch.setitem(sys.modules, 'win32security', security)


def validator(name):
    if name == 'control':
        from modules.ai_imaging.eagle_eye_remote.service_control import protected
        return protected
    if name == 'native':
        from modules.ai_imaging.eagle_eye_remote.secretary_native_connector import _protected_target
        return _protected_target
    path = Path(__file__).resolve().parents[3] / 'generated-files/eagle-eye/native-secretary-20261010/provision-targets-reviewed.py'
    spec = importlib.util.spec_from_file_location('generated_plan_acl', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bootstrap_plan_acl


@pytest.mark.parametrize('name', ['control', 'native', 'generated_plan'])
def test_inherit_only_users_full_control_is_not_effective(monkeypatch, tmp_path, name):
    install_security(monkeypatch, users_flags=11)
    validator(name)(tmp_path)


@pytest.mark.parametrize('name', ['control', 'native', 'generated_plan'])
def test_effective_users_full_control_remains_rejected(monkeypatch, tmp_path, name):
    install_security(monkeypatch, users_flags=3)
    with pytest.raises(ValueError):
        validator(name)(tmp_path)


def test_inherit_only_localservice_read_is_not_leaf_read(monkeypatch, tmp_path):
    install_security(monkeypatch, users_flags=11, service_flags=11, users_mask=0)
    with pytest.raises(ValueError, match='not protected'):
        validator('native')(tmp_path)


@pytest.mark.parametrize('name', ['control', 'native', 'generated_plan'])
@pytest.mark.parametrize('position', ['ancestor', 'leaf', 'parent', 'unknown_ancestor'])
def test_trusted_installer_exception_is_higher_ancestor_only(monkeypatch, tmp_path, name, position):
    installer = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
    path = tmp_path / 'private' / 'target.json'
    path.parent.mkdir()
    path.write_text('{}')
    selected = {'leaf': path, 'parent': path.parent,
                'ancestor': path.parent.parent, 'unknown_ancestor': path.parent.parent}[position]
    sid = 'S-1-5-80-123' if position == 'unknown_ancestor' else installer
    def descriptor(item, *args):
        owner = sid if Path(item) == selected else 'S-1-5-32-544'
        entries = [((0, 0), 0x10000000, owner), ((0, 0), 0x80000001, 'S-1-5-19')]
        acl = SimpleNamespace(GetAceCount=lambda: len(entries), GetAce=lambda n: entries[n])
        return SimpleNamespace(GetSecurityDescriptorOwner=lambda: owner,
                               GetSecurityDescriptorDacl=lambda: acl)
    security = SimpleNamespace(SE_FILE_OBJECT=1, OWNER_SECURITY_INFORMATION=1,
        DACL_SECURITY_INFORMATION=4, GetNamedSecurityInfo=descriptor,
        ConvertSidToStringSid=lambda value: value,
        LookupAccountName=lambda system, account: (installer, 'NT SERVICE', 5))
    monkeypatch.setitem(sys.modules, 'win32security', security)
    if position == 'ancestor':
        validator(name)(path)
    else:
        with pytest.raises(ValueError):
            validator(name)(path)


@pytest.mark.parametrize('name', ['control', 'native', 'generated_plan'])
def test_os_trusted_installer_lookup_must_match_exact_sid(monkeypatch, tmp_path, name):
    installer = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
    install_security(monkeypatch, users_mask=0)
    security = sys.modules['win32security']
    original = security.GetNamedSecurityInfo
    path = tmp_path / 'private' / 'target.json'
    path.parent.mkdir()
    path.write_text('{}')
    def descriptor(item, *args):
        sd = original(item, *args)
        if Path(item) == tmp_path:
            sd.GetSecurityDescriptorOwner = lambda: installer
        return sd
    security.GetNamedSecurityInfo = descriptor
    security.LookupAccountName = lambda *args: ('S-1-5-80-123', 'NT SERVICE', 5)
    with pytest.raises(ValueError, match='identity differs'):
        validator(name)(path)


@pytest.mark.parametrize('name', ['control', 'native', 'generated_plan'])
@pytest.mark.parametrize('ancestor_only', [True, False])
def test_create_files_and_directories_do_not_replace_protected_ancestor_child(monkeypatch, tmp_path, name, ancestor_only):
    install_security(monkeypatch, users_flags=0, users_mask=6)
    security = sys.modules['win32security']
    original = security.GetNamedSecurityInfo
    path = tmp_path / 'private' / 'target.json'
    path.parent.mkdir()
    path.write_text('{}')
    def descriptor(item, *args):
        sd = original(item, *args)
        acl = sd.GetSecurityDescriptorDacl()
        entries = [acl.GetAce(n) for n in range(acl.GetAceCount())]
        if ancestor_only and Path(item) in (path, path.parent):
            entries = [entry for entry in entries if entry[2] != 'S-1-5-32-545']
        sd.GetSecurityDescriptorDacl = lambda: SimpleNamespace(
            GetAceCount=lambda: len(entries), GetAce=lambda n: entries[n])
        return sd
    security.GetNamedSecurityInfo = descriptor
    if ancestor_only:
        validator(name)(path)
    else:
        with pytest.raises(ValueError):
            validator(name)(path)
