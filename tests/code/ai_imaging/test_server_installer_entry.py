"""Frozen installer dispatch distinguishes staged package from licensed service."""
import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def fixture_request(tmp_path, monkeypatch):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote.release_package import stamp

    from modules.ai_imaging.eagle_eye_remote.installed_layout import seal, selection
    core = tmp_path / 'core'
    core.mkdir()
    executable = core / 'AIPacs.exe'
    executable.write_bytes(b'synthetic frozen server')
    packages = tmp_path / 'plugin_packages'
    packages.mkdir()
    (packages / 'fixture.bin').write_bytes(b'synthetic-payload')
    seal(core, packages)
    stamp(core, 'test')
    private = tmp_path / 'private'
    private.mkdir()
    config = private / 'server.json'
    config.write_text('{}')
    monkeypatch.setattr(sys, 'executable', str(executable))
    monkeypatch.setattr(aipacs_runtime, 'is_frozen', lambda: True)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile', lambda: {'distribution_edition': 'eagle-eye'})
    return {'schema': 1, 'operation': 'stage', 'core_root': str(core),
            'private_root': str(private), 'config_path': str(config), 'payloads': selection(core),
            'shortcut': str(tmp_path / 'Eagle Eye Server.lnk')}


def test_staging_records_no_service_activation_and_never_constructs_scm_backend(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.installer_entry import execute

    request = fixture_request(tmp_path, monkeypatch)
    def forbidden(*args):
        raise AssertionError('Stage-only must not construct an SCM activation backend')
    receipt = execute(request, backend_factory=forbidden, protect=lambda path: None)
    assert receipt['service_activated'] is False
    assert receipt['installer_lifecycle_qualified'] is False
    assert json.loads((Path(request['private_root']) / 'setup-stage.json').read_bytes()) == receipt


def test_missing_server_license_stages_and_never_activates(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import installer_entry as entry

    request = fixture_request(tmp_path, monkeypatch)
    request['operation'] = 'install'
    monkeypatch.setattr(entry, 'official_provisioning', lambda *args: {'verified': False})
    receipt = entry.execute(request, protect=lambda path: None)
    assert receipt['phase'] == 'awaiting_official_server_provisioning'
    assert receipt['service_activated'] is False


def test_client_edition_and_unqualified_activation_driver_refuse(tmp_path, monkeypatch):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote import installer_entry as entry

    request = fixture_request(tmp_path, monkeypatch)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile', lambda: {'distribution_edition': 'standard'})
    with pytest.raises(ValueError, match='Server edition'):
        entry.execute(request, protect=lambda path: None)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile', lambda: {'distribution_edition': 'eagle-eye'})
    request['operation'] = 'install'
    monkeypatch.setattr(entry, 'official_provisioning', lambda *args: {'verified': True})
    with pytest.raises(RuntimeError, match='not qualified'):
        entry.execute(request, protect=lambda path: None)


@pytest.mark.parametrize('product,valid,legacy,accepted', [
    ('eagle-eye-server', True, False, True),
    ('client', True, False, False),
    ('eagle-eye-server', False, False, False),
    ('eagle-eye-server', True, True, False),
])
def test_provisioning_uses_existing_official_server_product_only(monkeypatch, product, valid, legacy, accepted):
    from modules.ai_imaging.eagle_eye_remote import installer_entry as entry, service_host
    from modules.LicenseGenerator import renewal

    monkeypatch.setattr(service_host, 'service_config', lambda path: {})
    manager = SimpleNamespace(product=product,
        status=lambda: {'product': product, 'valid': valid, 'legacy': legacy})
    monkeypatch.setattr(renewal, 'server_manager', lambda config: manager)
    assert entry.official_provisioning('synthetic-config', None)['verified'] is accepted


def test_installer_modules_are_explicitly_included_in_both_backends():
    root = Path(__file__).resolve().parents[3]
    required = {'modules.ai_imaging.eagle_eye_remote.installer_entry',
                'modules.ai_imaging.eagle_eye_remote.startup_barrier',
                'tools.eagle_eye.installed_release_host', 'tools.eagle_eye.fresh_server_install'}
    source = ast.parse((root / 'builder/spec/appA_workstation.spec').read_text(encoding='utf-8'))
    call = next(node for node in ast.walk(source) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == 'load_hiddenimports')
    extra = next(keyword.value for keyword in call.keywords if keyword.arg == 'extra')
    pyinstaller = {node.value for node in extra.elts if isinstance(node, ast.Constant)}
    source = ast.parse((root / 'builder nuitka/AIPacs_nuitka.spec.py').read_text(encoding='utf-8'))
    imports = next(node.value for node in source.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'FORCED_IMPORTS' for target in node.targets))
    assert required <= pyinstaller
    assert required <= set(ast.literal_eval(imports))
