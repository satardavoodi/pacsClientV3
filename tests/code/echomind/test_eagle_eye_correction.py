"""Saved AI reports are read-only, exact-study Correction sources."""
import json
import base64
from modules.EchoMind.correction_source import unpack
import pytest
from modules.EchoMind.eagle_eye_correction import load_from_roots, _report_text


def save(root, job, study, **extra):
    directory = root / job
    directory.mkdir(parents=True)
    value = dict(server_module='breast', analysis_study_uid=study,
                 artifact_directory=str(directory.resolve()), findings={'summary': 'Synthetic finding'}, **extra)
    (directory / 'result.json').write_text(json.dumps(value), encoding='utf-8')
    return directory


def test_json_only_exact_study_and_no_analysis_submission(tmp_path):
    root = tmp_path / 'ai'
    save(root, 'job-a', '1.2.3')
    save(root, 'job-b', '1.2.4')
    items = load_from_roots(root, tmp_path / 'attachments', '1.2.3')
    assert len(items) == 1
    raw, label = items[0]
    assert label == 'Eagle Eye — Mammography'
    source = unpack(raw)
    raw = base64.b64decode(source['data']).decode()
    assert source['name'].endswith('.json')
    assert 'Synthetic finding' in raw
    assert 'artifact_directory' not in raw
    assert load_from_roots(root, tmp_path / 'attachments', '') == []


def test_html_source_preserves_measurement_and_negation():
    assert _report_text({'content': '<p>Size: 24 mm</p><p>No suspicious nodes.</p>'}) == 'Size: 24 mm\nNo suspicious nodes.'


def test_scanned_pdf_not_silently_empty(tmp_path):
    from pypdf import PdfWriter
    path = tmp_path / 'report.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    with pytest.raises(ValueError, match='OCR'):
        _report_text({'pdf': str(path)})
