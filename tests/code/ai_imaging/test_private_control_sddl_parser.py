"""Parse complete private-control ACL literals with the actual Windows parser."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize('relative', [
    'modules/ai_imaging/eagle_eye_remote/service_control.py',
    'generated-files/eagle-eye/native-secretary-20261010/provision-targets-reviewed.py',
])
def test_private_control_complete_sddl_literals_parse_with_windows(relative):
    security = pytest.importorskip('win32security')
    root = Path(__file__).resolve().parents[3]
    tree = ast.parse((root / relative).read_text())
    literals = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                and isinstance(node.value, str) and node.value.startswith('O:BAG:BAD:P')
                and node.value.endswith(')')]
    assert literals, 'Each scoped implementation must expose its complete file ACL.'
    for value in literals:
        descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(value, 1)
        assert security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) == 'S-1-5-32-544'
        acl = descriptor.GetSecurityDescriptorDacl()
        assert acl is not None and acl.GetAceCount() >= 2
        assert descriptor.GetSecurityDescriptorControl()[0] & 0x1000
