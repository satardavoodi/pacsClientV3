from tests.code.builder.test_eagle_eye_brain_payload import brain_payload
from builder import eagle_eye_brain_payload
"""Offline payload staging must include weights and preserve dependency resources."""
import json
from pathlib import Path

import pytest

from builder import offline_lumbar_payload
from modules.ai_imaging.offline_lumbar.bundle import BundleError
from tests.code.ai_imaging.test_offline_lumbar import bundle


def add_current_startup_fixture(runtime):
    """Meet Slicer startup parity without copying a real native runtime."""
    import shutil
    from builder.slicer_runtime_payload import STARTUP_SOURCE, STARTUP_RUNTIME, PRESENTATION_COMPANIONS
    for relative in (STARTUP_SOURCE, *PRESENTATION_COMPANIONS):
        target = runtime / 'python' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(offline_lumbar_payload.REPO / relative, target)
    entry = runtime / STARTUP_RUNTIME
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text('# Synthetic startup entry point\n', encoding='utf-8')


@pytest.fixture(autouse=True)
def isolated_additional_model_payloads(tmp_path, monkeypatch):
    """Packaging tests must not discover private development model bundles."""
    from tests.code.builder.test_eagle_eye_alignment_payload import make_accepted_payload
    from tests.code.builder.test_eagle_eye_total_spine_payload import make_spine_payload, SYNTHETIC_HASH
    from modules.ai_imaging.eagle_eye_total_spine import service
    monkeypatch.setattr(service, 'WEIGHT_SHA256', SYNTHETIC_HASH)
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ALIGNMENT_SOURCE', str(make_accepted_payload(tmp_path / 'alignment')))
    monkeypatch.setenv('AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE', str(make_spine_payload(tmp_path / 'spine')))


def test_staging_fails_closed_when_model_bundle_is_missing(tmp_path):
    with pytest.raises(BundleError):
        offline_lumbar_payload.stage_offline_lumbar(tmp_path / "payload", tmp_path / "missing")
    assert not (tmp_path / "payload").exists()


def test_staging_preserves_resources_and_refreshes_adapter(bundle, tmp_path):
    dependency = bundle / "python/Lib/site-packages/example/tests/resource.dat"
    dependency.parent.mkdir(parents=True)
    dependency.write_bytes(b"required package data")
    staged = offline_lumbar_payload.stage_offline_lumbar(tmp_path / "payload", bundle)
    assert (staged / dependency.relative_to(bundle)).read_bytes() == dependency.read_bytes()
    canonical = Path(offline_lumbar_payload.REPO) / "modules/ai_imaging/offline_lumbar/worker.py"
    assert (staged / "app/offline_lumbar/worker.py").read_bytes() == canonical.read_bytes()
    assert json.loads((staged / "manifest.json").read_text())["network_required"] is False


def test_installer_copies_model_environment_without_pruning():
    text = (offline_lumbar_payload.REPO / "builder/installer/AIPacs_Setup.iss").read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("Source:") and
                "payload\\offline_lumbar\\*" in line.split(";")[0])
    assert "Excludes:" not in line
    assert "skipifsourcedoesntexist" not in line
    assert "AdvancedMprOfflineManifest" in text and "AdvancedMprOfflinePython" in text


def test_materializer_includes_bundle_in_same_advanced_package(bundle, tmp_path, monkeypatch, brain_payload):
    from tests.code.builder.test_eagle_eye_lesion_payload import make_lesion_payload
    monkeypatch.setenv('AIPACS_EAGLE_EYE_LESION_SOURCE', str(make_lesion_payload(tmp_path / 'lesions')))
    from builder import materialize_plugin_packages as materializer
    from builder.plugin_package_registry import plugin_package_definition_map
    runtime = tmp_path / "slicer"
    for name in materializer.ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
        file = runtime / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic runtime fixture")
    add_current_startup_fixture(runtime)
    monkeypatch.setattr(materializer, "PLUGIN_PACKAGES_DIR", tmp_path / "packages")
    monkeypatch.setattr(materializer, "_runtime_payload_source", lambda module_id: runtime)
    monkeypatch.setattr(materializer, "load_plugin_package_definitions",
                        lambda: [dict(plugin_package_definition_map()["advanced_mpr"], source_paths=[])])
    monkeypatch.setattr(offline_lumbar_payload, "bundle_source", lambda: bundle)
    monkeypatch.setattr(eagle_eye_brain_payload, "bundle_source", lambda: brain_payload)
    result = materializer.materialize_plugin_packages(include_runtime_payloads=True, build_lite_viewer=False)
    assert result[0]["materialized_payload"] is True
    payload = tmp_path / "packages/advanced_mpr/payload"
    assert (payload / "AIPacsAdvancedViewer.exe").exists()
    assert (payload / "offline_lumbar/manifest.json").exists()
    assert (payload / "offline_lumbar/python/python.exe").exists()
    assert (payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules/eagle_eye_remote/client.py").exists()


@pytest.mark.parametrize("reuse", [False, True])
def test_release_staging_includes_model_for_fresh_and_reused_payload(bundle, tmp_path, monkeypatch, reuse, brain_payload):
    from tests.code.builder.test_eagle_eye_lesion_payload import make_lesion_payload
    monkeypatch.setenv('AIPACS_EAGLE_EYE_LESION_SOURCE', str(make_lesion_payload(tmp_path / 'lesions')))
    from builder import build_release, materialize_plugin_packages
    from builder.plugin_package_registry import plugin_package_definition_map
    monkeypatch.setattr(materialize_plugin_packages, "_ensure_lite_viewer_built", lambda: None)
    monkeypatch.setattr(build_release, "PACKAGE_OUTPUT_DIR", tmp_path / "packages")
    staged = tmp_path / "stage"
    monkeypatch.setattr(build_release, "STAGED_PLUGIN_PACKAGE_DIR", staged)
    monkeypatch.setattr(build_release, "load_plugin_package_definitions",
                        lambda **kw: [dict(plugin_package_definition_map()["advanced_mpr"], source_paths=[])])
    monkeypatch.setattr(offline_lumbar_payload, "bundle_source", lambda: bundle)
    monkeypatch.setattr(eagle_eye_brain_payload, "bundle_source", lambda: brain_payload)
    runtime = staged / "advanced_mpr/payload" if reuse else tmp_path / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "AIPacsAdvancedViewer.exe").write_bytes(b"synthetic runtime fixture")
    add_current_startup_fixture(runtime)
    result = build_release.build_module_packages("9.9.9", {"staged": True, "source": str(runtime)},
                                                 reuse_staged_payload=reuse)
    assert result[0]["has_payload"] is True
    payload = staged / "advanced_mpr/payload"
    assert (payload / "AIPacsAdvancedViewer.exe").read_bytes() == b"synthetic runtime fixture"
    assert (payload / "offline_lumbar/manifest.json").exists()
    assert (payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules/eagle_eye_remote/client.py").exists()


def test_standard_package_staging_skips_eagle_eye_assets(tmp_path, monkeypatch):
    from builder import build_release, materialize_plugin_packages
    from builder.plugin_package_registry import plugin_package_definition_map

    monkeypatch.setattr(materialize_plugin_packages, "_ensure_lite_viewer_built", lambda: None)
    monkeypatch.setattr(build_release, "PACKAGE_OUTPUT_DIR", tmp_path / "packages")
    staged = tmp_path / "stage"
    monkeypatch.setattr(build_release, "STAGED_PLUGIN_PACKAGE_DIR", staged)
    monkeypatch.setattr(
        build_release,
        "load_plugin_package_definitions",
        lambda **kw: [dict(plugin_package_definition_map()["advanced_mpr"], source_paths=[])],
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "AIPacsAdvancedViewer.exe").write_bytes(b"synthetic runtime fixture")

    add_current_startup_fixture(runtime)
    result = build_release.build_module_packages(
        "9.9.9",
        {"staged": True, "source": str(runtime)},
        include_eagle_eye_assets=False,
    )

    payload_dir = staged / "advanced_mpr/payload"
    assert result[0]["has_payload"] is True
    assert (payload_dir / "AIPacsAdvancedViewer.exe").exists()
    assert not (payload_dir / "offline_lumbar").exists()
    assert not (payload_dir / "eagle_eye").exists()


def test_standard_post_stage_gate_does_not_require_pruned_eagle_eye_assets(tmp_path, monkeypatch):
    import aipacs_runtime as runtime
    from builder import plugin_package_registry, release_gate

    staged = tmp_path / "stage/plugin_packages/advanced_mpr"
    staged.mkdir(parents=True)
    (staged / runtime.MODULE_PACKAGE_MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    (staged.parent / runtime.MODULE_PACKAGE_FEED_FILENAME).write_text(
        json.dumps({"packages": [{"module_id": "advanced_mpr", "available": True}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        plugin_package_registry,
        "plugin_package_definition_map",
        lambda optional_only=True: {
            "advanced_mpr": {"module_id": "advanced_mpr", "build_strategy": "runtime_payload"}
        },
    )

    compact = release_gate.check_stage_plugin_packages(
        tmp_path / "stage", require_eagle_eye_assets=False
    )
    eagle_eye = release_gate.check_stage_plugin_packages(
        tmp_path / "stage", require_eagle_eye_assets=True
    )
    assert compact.ok
    assert not eagle_eye.ok
    assert "offline lumbar" in " ".join(eagle_eye.details).lower()
