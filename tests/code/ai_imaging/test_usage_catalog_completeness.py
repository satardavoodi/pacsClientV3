"""Usage catalogs track registered imaging modules without private labels."""
from modules.ai_imaging.eagle_eye_remote import contracts, usage


def test_new_registered_imaging_module_is_visible_without_usage_code_edit(monkeypatch):
    monkeypatch.setattr(contracts, 'MODULES', (*contracts.MODULES, 'synthetic-new-module'))
    result = usage.job_summary([{'module': 'synthetic-new-module', 'status': 'succeeded'}])
    rows = {row['key']: row for row in result['groups']}
    assert rows['synthetic-new-module']['completed'] == 1
    assert rows['synthetic-new-module']['label'] == 'Synthetic New Module'


def test_unknown_job_text_is_never_exported_as_catalog_label():
    result = usage.job_summary([{'module': 'private arbitrary text', 'status': 'failed'}])
    assert 'private arbitrary text' not in str(result)
    assert next(row for row in result['groups'] if row['key'] == 'other')['failed'] == 1
