"""Developer snapshots cannot silently omit the separate calcium engine."""
import hashlib
import json
from pathlib import Path

import pytest


def prepared(tmp_path, monkeypatch):
    from tools.eagle_eye import developer_model_bindings as bindings
    source=tmp_path/'source'
    for name in bindings.MODEL_BINDINGS:
        (source/name).mkdir(parents=True)
    calcium=source/'generated-files/eagle-eye/calcium-b95'
    files={'runner.py':b'synthetic runner','physical_peaks_fast.py':b'synthetic peaks','assets/weights.bin':b'synthetic weights'}
    for name,value in files.items():
        p=calcium/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
    manifest={'format':'breast_calcium_v1','revision':'fixture','threads':2,
              'sha256':{name:hashlib.sha256(value).hexdigest() for name,value in files.items()}}
    raw=json.dumps(manifest).encode();(calcium/'manifest.json').write_bytes(raw)
    monkeypatch.setattr(bindings,'CALCIUM_MANIFEST_SHA256',hashlib.sha256(raw).hexdigest())
    return bindings,source,calcium


def test_complete_developer_bindings_include_calcium(tmp_path,monkeypatch):
    bindings,source,calcium=prepared(tmp_path,monkeypatch)
    result=bindings.model_bindings(source)
    assert result['generated-files/eagle-eye/calcium-b95']==calcium.resolve()
    assert len(result)==8


def test_snapshot_without_calcium_is_rejected_before_activation(tmp_path,monkeypatch):
    bindings,source,calcium=prepared(tmp_path,monkeypatch)
    (calcium/'manifest.json').unlink()
    with pytest.raises(ValueError,match='calcium'):
        bindings.model_bindings(source)


def test_explicit_preserved_calcium_requires_approved_complete_bundle(tmp_path,monkeypatch):
    bindings,source,calcium=prepared(tmp_path,monkeypatch)
    preserved=tmp_path/'preserved'
    calcium.rename(preserved)
    assert bindings.model_bindings(source,calcium_source=preserved)['generated-files/eagle-eye/calcium-b95']==preserved.resolve()
    (preserved/'assets/weights.bin').write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='integrity'):
        bindings.model_bindings(source,calcium_source=preserved)


def test_changed_manifest_or_extra_payload_is_rejected(tmp_path,monkeypatch):
    bindings,source,calcium=prepared(tmp_path,monkeypatch)
    (calcium/'unexpected.py').write_text('fixture')
    with pytest.raises(ValueError,match='inventory'):
        bindings.model_bindings(source)
    (calcium/'unexpected.py').unlink()
    (calcium/'manifest.json').write_text('{}')
    with pytest.raises(ValueError,match='manifest'):
        bindings.model_bindings(source)
