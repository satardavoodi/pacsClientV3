"""Alignment stays an Eagle Eye feature with sealed, edition-specific assets."""
import hashlib
import json
from pathlib import Path
import pytest


def make_payload(root):
    from modules.ai_imaging.eagle_eye_alignment.inference import WEIGHTS
    from modules.ai_imaging.eagle_eye_alignment.service import SOURCE_REVISION,WEIGHT_REVISION
    names=[*WEIGHTS.values(),'runtime/python.exe','inference.py','vendor/BaseModels.py',
           'vendor/SGRModel.py','vendor/LICENSE','vendor/NOTICE']
    hashes={}
    for name in names:
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'synthetic')
        hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    (root/'manifest.json').write_text(json.dumps(dict(source_revision=SOURCE_REVISION,weight_revision=WEIGHT_REVISION,sha256=hashes)))
    return root


def make_accepted_payload(root):
    """Synthetic acceptance fixture; never a receipt for the real bundle."""
    make_payload(root)
    (root/'acceptance.json').write_text(json.dumps(dict(
        manifest_sha256=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
        offline_inference='passed',live_gui='passed',distribution_rights_review='approved')))
    return root


def test_runtime_allows_local_use_but_distribution_requires_receipt(tmp_path):
    from builder.eagle_eye_alignment_payload import validate_payload
    source=make_payload(tmp_path)
    validate_payload(source,for_distribution=False)
    with pytest.raises(RuntimeError,match='acceptance'):validate_payload(source)
    (source/'inference.py').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):validate_payload(source,for_distribution=False)


def test_stager_uses_only_manifest_files(tmp_path,monkeypatch):
    from builder.eagle_eye_alignment_payload import stage_eagle_eye_alignment
    source=make_payload(tmp_path/'source');(source/'private.txt').write_text('never package')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ALIGNMENT_SOURCE',str(source))
    target=stage_eagle_eye_alignment(tmp_path/'out',for_distribution=False)
    assert (target/'runtime/python.exe').is_file() and not (target/'private.txt').exists()


def test_manifest_path_escape_rejected(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.service import validate_bundle
    source=make_payload(tmp_path/'source');p=source/'manifest.json';m=json.loads(p.read_text())
    m['sha256']['../outside']=hashlib.sha256(b'').hexdigest();p.write_text(json.dumps(m))
    with pytest.raises(ValueError):validate_bundle(source)


def test_no_weight_download_or_tls_override_in_inference_sources():
    root=Path(__file__).resolve().parents[3]/'modules/ai_imaging/eagle_eye_alignment'
    for file in (root/'vendor').glob('*.py'):
        text=file.read_text()
        assert '_create_unverified_context' not in text
        assert 'weights=vgg16_weights.IMAGENET1K_V1' not in text


def test_feature_does_not_create_a_second_installer_module():
    from modules.ai_imaging.eagle_eye.assets import FEATURE_ASSETS
    assert FEATURE_ASSETS['alignment']=='eagle_eye/alignment'
    source=Path(__file__).resolve().parents[3]/'builder/distribution_profiles.py'
    assert "validate_alignment(payload / 'eagle_eye/alignment'" in source.read_text()
