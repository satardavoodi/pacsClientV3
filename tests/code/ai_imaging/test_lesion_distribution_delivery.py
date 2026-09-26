"""Synthetic distribution reporting and server-to-client artifact contract."""
import json
import zipfile

import pytest

from modules.ai_imaging.eagle_eye_brain.lesion_topography import topography_pages
from modules.ai_imaging.eagle_eye_remote.artifacts import publish


def distribution():
    return {'regions': [{'region': name, 'available': name != 'Corpus callosum',
                         'count': 2, 'volume_mm3': 12.5}
                        for name in ('Periventricular contact', 'Juxtacortical contact',
                                     'Infratentorial', 'Supratentorial', 'Corpus callosum')]}


@pytest.mark.parametrize('indication', ['other', 'svd'])
def test_non_ms_report_contains_distribution_without_ms_diagnosis(indication):
    pages = topography_pages({'clinical_context': {'primary_disease': indication},
                              'lesion_topography': distribution()})
    html = ''.join(pages)
    for row in distribution()['regions']:
        assert row['region'] in html
    assert 'Not assessed' in html and '12.5' in html
    assert 'McDonald' not in html and 'Potential two-region' not in html


def test_distribution_and_complete_pdf_survive_server_archive(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'report.pdf').write_bytes(b'%PDF-1.4 synthetic complete distribution report')
    result = {'artifact_directory': str(work), 'pdf_available': True,
              'lesion_topography': distribution(), 'patient_context': {'age_years': 42}}
    request = {'module': 'brain-lesions', 'protocol': 1, 'request_id': 'synthetic', 'study_uid': '1.2.3'}
    publish(tmp_path, request, [], result)
    with zipfile.ZipFile(tmp_path / 'artifacts.zip') as archive:
        packet = json.loads(archive.read('envelope.json'))
        assert packet['result']['lesion_topography'] == distribution()
        assert packet['result']['patient_context']['age_years'] == 42
        assert archive.read('report.pdf').startswith(b'%PDF-')
