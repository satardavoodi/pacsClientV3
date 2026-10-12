"""Co-installed Client and Server cannot share role profiles or model state."""
from pathlib import Path
import sys

import pytest


@pytest.mark.parametrize('server',[False,True])
def test_installed_roles_have_separate_state_and_payloads(tmp_path,monkeypatch,server):
    import aipacs_runtime as runtime
    install=tmp_path/('server/core' if server else 'client');install.mkdir(parents=True)
    if server:
        from modules.ai_imaging.eagle_eye_remote.installed_layout import seal
        from modules.ai_imaging.eagle_eye_remote.release_package import stamp
        (install/'AIPacs.exe').write_bytes(b'synthetic')
        packages=install.parent/'plugin_packages';packages.mkdir()
        (packages/'fixture.bin').write_bytes(b'synthetic')
        seal(install,packages);stamp(install,'test')
    monkeypatch.setattr(runtime,'is_frozen',lambda:True)
    monkeypatch.setattr(runtime,'install_root',lambda:install)
    monkeypatch.setattr(runtime,'bundle_root',lambda:install)
    monkeypatch.setattr(sys,'platform','win32')
    for name in ('PROGRAMDATA','LOCALAPPDATA','APPDATA'):monkeypatch.setenv(name,str(tmp_path/name))
    namespace=Path('AIPacs/EagleEyeServer' if server else 'AIPacs')
    assert runtime.program_data_config_root()==tmp_path/'PROGRAMDATA'/namespace/'config'
    assert runtime.roaming_config_root()==tmp_path/'APPDATA'/namespace/'config'
    assert runtime.local_state_root()==tmp_path/'LOCALAPPDATA'/namespace
    expected=install.parent/'plugin_packages' if server else tmp_path/'PROGRAMDATA'/namespace/'module_packages'
    assert runtime.bundled_module_packages_search_roots()[0]==expected


def test_server_installer_uses_separate_app_id_and_data_namespace():
    source=Path('builder/installer/AIPacs_Setup.iss').read_text(encoding='utf-8')
    assert '#define ProductDataRoot "{commonappdata}\\AIPacs\\EagleEyeServer"' in source
    assert '#define ProductAppId "' in source
    assert 'AppId={{{#ProductAppId}}' in source
    assert "'{{#ProductAppId}}_is1'" in source
    assert 'DestDir: "{#ProductDataRoot}\\module_packages' in source
    assert "ExpandConstant('{#ProductDataRoot}\\config')" in source


def test_server_installer_cannot_uninstall_or_close_live_clinical_applications():
    source=Path('builder/installer/AIPacs_Setup.iss').read_text(encoding='utf-8')
    body=source.split('function PrepareToInstall(var NeedsRestart: Boolean): String;',1)[1].split('procedure CurStepChanged',1)[0]
    assert '#if DistributionEdition == "eagle-eye"' in body
    server_branch=body.split('#if DistributionEdition == "eagle-eye"',1)[1].split('#else',1)[0]
    assert 'RunPreviousUninstaller' not in server_branch
    assert 'coordinated Server updater' in server_branch
    assert '#if DistributionEdition == "eagle-eye"\nCloseApplications=no' in source
