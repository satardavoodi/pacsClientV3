"""Synthetic model seals and staging gates, never receipts for real models."""
import hashlib
import json
import pytest

SYNTHETIC_HASH = hashlib.sha256(b'synthetic-test-only').hexdigest()


def make_spine_payload(root, accepted=True):
    from modules.ai_imaging.eagle_eye_total_spine.service import SOURCE_REVISION
    names = ('inference.py', 'model_last.pth', 'LICENSE', 'NOTICE', 'decoder.py',
             'models/__init__.py', 'models/spinal_net.py', 'models/dec_net.py',
             'models/model_parts.py', 'models/resnet.py')
    for name in names:
        p = root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'synthetic-test-only')
    manifest = dict(source_revision=SOURCE_REVISION, weight_sha256=SYNTHETIC_HASH,
                    runtime_provider='alignment', sha256={name: SYNTHETIC_HASH for name in names})
    (root/'manifest.json').write_text(json.dumps(manifest))
    if accepted:
        (root/'acceptance.json').write_text(json.dumps(dict(
            manifest_sha256=hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),
            offline_inference='passed', live_gui='passed', distribution_rights_review='approved')))
    return root


@pytest.fixture(autouse=True)
def synthetic_weight_pin(monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine import service
    monkeypatch.setattr(service, 'WEIGHT_SHA256', SYNTHETIC_HASH)


def test_seal_and_acceptance_are_independent(tmp_path):
    from builder.eagle_eye_total_spine_payload import validate_payload
    source = make_spine_payload(tmp_path, accepted=False)
    validate_payload(source, for_distribution=False)
    with pytest.raises(RuntimeError, match='acceptance'): validate_payload(source)
    (source/'decoder.py').write_text('changed')
    with pytest.raises(ValueError, match='changed'): validate_payload(source, for_distribution=False)


def test_pinned_checkpoint_rejects_resealed_wrong_weight(tmp_path):
    from modules.ai_imaging.eagle_eye_total_spine.service import validate_bundle
    source = make_spine_payload(tmp_path)
    (source/'model_last.pth').write_bytes(b'wrong')
    manifest = json.loads((source/'manifest.json').read_text())
    manifest['sha256']['model_last.pth'] = hashlib.sha256(b'wrong').hexdigest()
    (source/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError): validate_bundle(source)


def test_stager_excludes_unlisted_files_and_requires_runtime(tmp_path, monkeypatch):
    from builder.eagle_eye_total_spine_payload import stage_eagle_eye_total_spine
    source = make_spine_payload(tmp_path/'source')
    (source/'private.txt').write_text('do not copy')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE', str(source))
    with pytest.raises(RuntimeError, match='runtime'): stage_eagle_eye_total_spine(tmp_path/'out')
    runtime = tmp_path/'out/eagle_eye/alignment/runtime/python.exe'
    runtime.parent.mkdir(parents=True); runtime.write_bytes(b'synthetic-runtime')
    target = stage_eagle_eye_total_spine(tmp_path/'out')
    assert (target/'model_last.pth').is_file() and not (target/'private.txt').exists()


def test_no_new_installer_module_identity():
    from modules.ai_imaging.eagle_eye.assets import FEATURE_ASSETS
    assert FEATURE_ASSETS['total_spine'] == 'eagle_eye/total-spine'


def test_optional_assist_is_staged_by_seal_and_needs_own_acceptance(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine import assist_assets
    from builder.eagle_eye_total_spine_payload import stage_eagle_eye_total_spine, validate_payload
    source = make_spine_payload(tmp_path/'source')
    assist = source/'assist'
    monkeypatch.setattr(assist_assets, 'WEIGHTS', {name: ('synthetic', SYNTHETIC_HASH)
                                               for name in assist_assets.WEIGHTS})
    for name in assist_assets.REQUIRED:
        item = assist/name; item.parent.mkdir(parents=True, exist_ok=True); item.write_bytes(b'synthetic-test-only')
    (assist/'manifest.json').write_text(json.dumps(dict(format_version=1,
        sam_revision=assist_assets.SAM_REVISION, scoliovis_revision=assist_assets.SCOLIOVIS_REVISION,
        sha256={name: SYNTHETIC_HASH for name in assist_assets.REQUIRED})))
    (assist/'private.txt').write_text('must not be staged')
    with pytest.raises(RuntimeError, match='separate'): validate_payload(source)
    monkeypatch.setenv('AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE', str(source))
    runtime = tmp_path/'out/eagle_eye/alignment/runtime/python.exe'
    runtime.parent.mkdir(parents=True); runtime.write_bytes(b'synthetic-runtime')
    target = stage_eagle_eye_total_spine(tmp_path/'out', for_distribution=False)
    assert (target/'assist/sam_vit_b.pth').is_file()
    assert (target/'assist/scoliovis.pt').is_file()
    assert not (target/'assist/private.txt').exists()
    with pytest.raises(RuntimeError, match='separate'): validate_payload(target)
