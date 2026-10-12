"""Release-input guards: customer builds verify but cannot issue entitlements."""
import ast
from pathlib import Path

from builder.spec import spec_utils
from modules.LicenseGenerator import license_manager, signing_trust
from modules.LicenseGenerator.signed_license import key_id

ROOT = Path(__file__).resolve().parents[3]


def test_runtime_has_no_signing_or_company_tool_imports():
    assert not hasattr(license_manager.LicenseManager, 'generate_license_key')
    for path in (ROOT / 'modules/LicenseGenerator').glob('*.py'):
        if path.name in ('license_generator.py', 'license_generator_gui.py'):
            continue  # Company-only entrypoints, explicitly excluded by both customer builders.
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith('tools.licensing')
                assert all(alias.name != 'Ed25519PrivateKey' for alias in node.names)
            elif isinstance(node, ast.Import):
                assert all(not alias.name.startswith('tools.licensing') for alias in node.names)


def test_only_valid_public_roots_are_pinned():
    assert signing_trust.TRUSTED_KEYS
    for identifier, value in signing_trust.TRUSTED_KEYS.items():
        public = bytes.fromhex(value)
        assert len(public) == 32 and key_id(public) == identifier


def test_both_backends_exclude_company_issuer():
    paths = [ROOT / 'AIPacs.spec', ROOT / 'builder/spec/appA_workstation.spec',
             ROOT / 'builder nuitka/AIPacs_nuitka.spec.py']
    for path in paths:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        lists = [node.value for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id in ('excludes', 'EXCLUDES')
                         for target in node.targets)]
        assert any('tools.licensing' in ast.literal_eval(value) for value in lists)
    assert spec_utils.is_excluded('tools/licensing/issuer.py')
    assert spec_utils.is_excluded('private/issuer-2026-10.key')
    assert spec_utils.is_excluded('private/issuer-2026-10.sqlite')
