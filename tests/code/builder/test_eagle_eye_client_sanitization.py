"""Never distribute a developer's paired Eagle Eye connection or file paths."""
import json

from builder.config_sanitizer import build_clean_config_tree, sanitize_obj


def test_eagle_eye_pairing_template_is_sanitized_without_mutating_input():
    fields = ('url', 'token_file', 'ca_file', 'client_certificate', 'client_private_key')
    original = {'schema_version': 1, **{field: 'synthetic-local-value' for field in fields},
                'token_env': 'SYNTHETIC_CENTER_TOKEN', 'token': 'synthetic-inline-token',
                'unknown_deployment_field': 'synthetic-private-value'}
    clean = sanitize_obj('eagle_eye_client.json', original)
    assert clean['schema_version'] == 1
    assert all(clean[field] == '' for field in fields)
    assert clean['token_env'] == 'AIPACS_EAGLE_EYE_TOKEN'
    assert 'token' not in clean and 'unknown_deployment_field' not in clean
    assert all(original[field] == 'synthetic-local-value' for field in fields)


def test_packaged_client_config_contains_no_pairing_locations(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'package'
    source.mkdir()
    original = {'schema_version': 1, 'url': 'https://synthetic.example.invalid:8002',
                'token_file': 'C:/synthetic-local/token.txt',
                'ca_file': 'C:/synthetic-local/ca.pem',
                'client_certificate': 'C:/synthetic-local/client.pem',
                'client_private_key': 'C:/synthetic-local/client.key'}
    config = source / 'eagle_eye_client.json'
    config.write_text(json.dumps(original), encoding='utf-8')
    build_clean_config_tree(source, destination)
    clean = json.loads((destination / config.name).read_text(encoding='utf-8'))
    assert clean == {'schema_version': 1, 'url': '', 'token_file': '',
                     'token_env': 'AIPACS_EAGLE_EYE_TOKEN',
                     'ca_file': '', 'client_certificate': '', 'client_private_key': ''}
    assert json.loads(config.read_text(encoding='utf-8')) == original
