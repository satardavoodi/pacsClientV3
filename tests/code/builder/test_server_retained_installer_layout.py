"""Inno must retain the exact core-bound payload tree without Client changes."""
from pathlib import Path


def test_server_uses_identity_retained_tree_and_no_generic_launch():
    text = Path('builder/installer/AIPacs_Setup.iss').read_text(encoding='utf-8')
    files = text.split('[Files]', 1)[1].split('[Icons]', 1)[0]
    server = files.split('#if DistributionEdition == "eagle-eye"', 1)[1].split('#else', 1)[0]
    assert 'DestDir: "{#ServerReleaseRoot}\\core"' in server
    assert 'DestDir: "{#ServerReleaseRoot}\\plugin_packages"' in server
    assert 'Components: core' in server
    assert '#define ServerReleaseRoot "{app}\\releases\\" + EagleEyeReleaseId' in text
    run = text.split('[Run]', 1)[1].split('[Messages]', 1)[0]
    assert '#if DistributionEdition != "eagle-eye"' in run
    assert '--eagle-eye-setup-server' in text
    assert 'ewWaitUntilTerminated, SetupExit' in text
    setup = text.split('procedure CurStepChanged', 1)[1].split('#else', 1)[0]
    assert 'RaiseException' not in setup
    assert 'Installer completion does not certify Server activation.' in setup


def test_canonical_compiler_passes_exact_server_identity():
    source = Path('builder/distribution_profiles.py').read_text(encoding='utf-8')
    assert "release_id = read(stage / 'core')['release_id']" in source
    assert 'f"/DEagleEyeReleaseId={release_id}"' in source
