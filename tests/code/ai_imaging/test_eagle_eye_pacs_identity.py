"""PACS Study ID is not the DICOM Study Instance UID."""
import pytest

from modules.ai_imaging.eagle_eye_remote.source import PacsSource


@pytest.mark.parametrize('returned_uid', ['1.2.3', '1.2.4', None])
def test_storage_response_uses_dicom_study_instance_uid(tmp_path, monkeypatch, returned_uid):
    study = {'study_id': '1.2.3' if returned_uid != '1.2.3' else 'local-study-id'}
    if returned_uid is not None:
        study['study_instance_uid'] = returned_uid

    class Response:
        content = b'{}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def json(self):
            return {'study_info': study, 'storage_info': {'study_path': str(tmp_path)}}

    provider = PacsSource({'url': 'http://127.0.0.1:8000', 'allowed_roots': [str(tmp_path)]})
    monkeypatch.setattr(provider, 'get', lambda url: Response())
    if returned_uid == '1.2.3':
        assert provider.storage_files({'study_uid': '1.2.3'}) == []
    else:
        with pytest.raises(ValueError, match='identity does not match'):
            provider.storage_files({'study_uid': '1.2.3'})
