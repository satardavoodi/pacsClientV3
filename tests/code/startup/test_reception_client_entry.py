"""Ordinary Windows login stays independent of Eagle Eye provider resolution."""
from pathlib import Path
import ast


def test_login_has_no_eagle_eye_provider_selector_or_reception_entry():
    source=Path('PacsClient/app_handler.py').read_text(encoding='utf-8-sig')
    ast.parse(source)
    for removed in ('login_authority', '_reception_login_ready', '_reception_auth_operation', 'valid_reception_admission'):
        assert removed not in source
    assert 'self._server_auth_operation.start' in source
    assert 'self._complete_login(username, password)' in source
