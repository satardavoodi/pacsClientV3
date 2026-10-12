"""Server staging preserves baseline and refuses changed or unbounded patches."""
import hashlib
import json
import zipfile

import pytest

from tools.eagle_eye.stage_lumbar_marrow import CHANGED, NEW, stage


def bundle(tmp_path, *, changed_context=False):
    baseline = tmp_path / 'baseline'
    manifest = dict(format=1, feature='lumbar-marrow-t1-v1', edits={}, files={})
    for name in CHANGED:
        relative = 'modules/ai_imaging/eagle_eye_remote/' + name
        path = baseline / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('unchanged baseline\nold marker\nnewer server addition\n', encoding='utf-8')
        manifest['edits'][relative] = [dict(old='wrong marker\n' if changed_context else 'old marker\n', new='new marker\n')]
    for private in ['user_data', 'database', '.venv', 'generated-files']:
        path = baseline / private
        path.mkdir()
        (path / 'synthetic.txt').write_text('excluded synthetic sentinel')
    archive = tmp_path / 'bundle.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for relative in NEW:
            content = b'# Synthetic staging fixture\n'
            manifest['files'][relative] = hashlib.sha256(content).hexdigest()
            output.writestr(relative, content)
        output.writestr('manifest.json', json.dumps(manifest))
    return baseline, archive


def test_stage_preserves_newer_server_work_and_excludes_runtime_patient_storage(tmp_path):
    baseline, archive = bundle(tmp_path)
    candidate = tmp_path / 'revision' / 'source'
    receipt = stage(archive, baseline, candidate)
    assert not receipt['activated']
    for name in CHANGED:
        relative = 'modules/ai_imaging/eagle_eye_remote/' + name
        assert 'old marker' in (baseline / relative).read_text()
        assert 'new marker' in (candidate / relative).read_text()
        assert 'newer server addition' in (candidate / relative).read_text()
    for private in ['user_data', 'database', '.venv', 'generated-files']:
        assert not (candidate / private).exists()
    assert (candidate.parent / 'marrow-stage.json').is_file()


def test_stage_refuses_changed_baseline_before_creating_candidate(tmp_path):
    baseline, archive = bundle(tmp_path, changed_context=True)
    candidate = tmp_path / 'revision' / 'source'
    with pytest.raises(ValueError, match='context changed'):
        stage(archive, baseline, candidate)
    assert not candidate.exists()


def test_stage_refuses_in_place_or_existing_source(tmp_path):
    baseline, archive = bundle(tmp_path)
    with pytest.raises(ValueError, match='new candidate'):
        stage(archive, baseline, baseline)
