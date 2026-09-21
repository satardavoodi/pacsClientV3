"""Edition packages must retain Slicer while isolating Eagle Eye model bytes."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from builder import distribution_profiles as profiles
from tests.code.ai_imaging.test_offline_lumbar import bundle
from tests.code.builder.test_eagle_eye_brain_payload import brain_payload
from tests.code.builder.test_eagle_eye_lesion_payload import make_lesion_payload
from tests.code.builder.test_eagle_eye_alignment_payload import make_accepted_payload
from tests.code.builder.test_eagle_eye_total_spine_payload import make_spine_payload, SYNTHETIC_HASH


@pytest.fixture(autouse=True)
def synthetic_spine_checkpoint_pin(monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine import service
    monkeypatch.setattr(service, 'WEIGHT_SHA256', SYNTHETIC_HASH)


def source_stage(tmp_path):
    source = tmp_path / "shared"
    (source / "core").mkdir(parents=True)
    (source / "core/AIPacs.exe").write_bytes(b"synthetic executable fixture")
    (source / "plugin_packages/advanced_mpr/payload").mkdir(parents=True)
    (source / "plugin_packages/advanced_mpr/payload/weights.bin").write_bytes(b"synthetic model fixture")
    (source / "plugin_packages/echomind/payload").mkdir(parents=True)
    (source / "plugin_packages/echomind/payload/code.py").write_text("value = 1\n")
    (source / "plugin_packages/module_package_feed.json").write_text(json.dumps({"packages": [
        {"module_id": "advanced_mpr", "available": True, "has_payload": True},
        {"module_id": "echomind", "available": True, "has_payload": True}]}))
    return source


@pytest.mark.parametrize("edition", list(profiles.EDITIONS))
def test_every_edition_retains_current_echomind_report_renderers(tmp_path, edition, bundle, brain_payload):
    """The next edition stage must carry the reviewed report source bytes."""
    import shutil

    source = source_stage(tmp_path)
    payload = add_complete_slicer_runtime(source)
    shutil.copytree(bundle, payload / "offline_lumbar", dirs_exist_ok=True)
    shutil.copytree(brain_payload, payload / "eagle_eye/brain")
    make_lesion_payload(payload / 'eagle_eye/brain-lesions')
    make_accepted_payload(payload / 'eagle_eye/alignment')
    make_spine_payload(payload / 'eagle_eye/total-spine')
    root = Path(__file__).resolve().parents[3]
    relative = Path("plugin_packages/echomind/payload/python/modules/EchoMind")
    (source / relative).mkdir(parents=True)
    expected = {}
    for name in ("viewer_chat/ai_chat_pages.py", "viewer_chat/ai_chat_widgets.py",
                 "normal_templates.py", "reception_templates.py",
                 "viewer_chat/normal_template_dialog.py", "viewer_chat/reception_template_dialog.py",
                 "viewer_chat/openai_reporter.py"):
        canonical = root / "modules/EchoMind" / name
        mirror = root / "builder/plugin package/packages/echomind/payload/python/modules/EchoMind" / name
        expected[name] = canonical.read_bytes()
        assert mirror.read_bytes() == expected[name]
        (source / relative / name).parent.mkdir(parents=True, exist_ok=True)
        (source / relative / name).write_bytes(mirror.read_bytes())
    target = profiles.stage_edition(source, tmp_path / edition, profiles.EDITIONS[edition])
    for name, content in expected.items():
        assert (target / relative / name).read_bytes() == content


def add_complete_slicer_runtime(source):
    from builder.build_release import ADVANCED_MPR_REQUIRED_RUNTIME_FILES

    payload = source / "plugin_packages/advanced_mpr/payload"
    for relative in ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
        file = payload / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic Slicer runtime fixture")
    module_path = payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules"
    module_path.mkdir(parents=True, exist_ok=True)
    (module_path / "AIPacsBackgroundRuntime.py").write_text(
        "# Synthetic resident integration fixture\n"
    )
    (module_path / "AIPacsOfflineLumbar.py").write_text(
        "# Synthetic Eagle Eye integration fixture\n"
    )
    offline = payload / "offline_lumbar"
    offline.mkdir()
    (offline / "manifest.json").write_text("{}\n")
    return payload


@pytest.mark.parametrize("name", ["standard", "arm"])
def test_compact_stage_keeps_slicer_but_excludes_eagle_eye_model(tmp_path, name):
    source = source_stage(tmp_path)
    source_payload = add_complete_slicer_runtime(source)
    target = profiles.stage_edition(source, tmp_path / name, profiles.EDITIONS[name])
    payload = target / "plugin_packages/advanced_mpr/payload"
    assert (payload / "AIPacsAdvancedViewer.exe").is_file()
    assert (payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsBackgroundRuntime.py").is_file()
    assert not (payload / "offline_lumbar").exists()
    assert not (payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules/AIPacsOfflineLumbar.py").exists()
    assert (target / "plugin_packages/echomind/payload/code.py").is_file()
    feed = json.loads((target / "plugin_packages/module_package_feed.json").read_text())
    assert feed["packages"][0]["available"] is True
    assert feed["packages"][0]["has_payload"] is True
    assert json.loads((source / "plugin_packages/module_package_feed.json").read_text())["packages"][0]["available"] is True
    assert (source_payload / "offline_lumbar/manifest.json").is_file()


def test_compact_stage_never_copies_excluded_offline_model_bytes(tmp_path, monkeypatch):
    source = source_stage(tmp_path)
    add_complete_slicer_runtime(source)
    copied_sources = []
    original = profiles._link_or_copy

    def record_copy(source_path, destination_path):
        copied_sources.append(Path(source_path))
        return original(source_path, destination_path)

    monkeypatch.setattr(profiles, "_link_or_copy", record_copy)
    profiles.stage_edition(source, tmp_path / "standard", profiles.EDITIONS["standard"])

    copied_names = {path.name for path in copied_sources}
    assert "AIPacsOfflineLumbar.py" not in copied_names
    assert not any("offline_lumbar" in path.parts for path in copied_sources)


def test_eagle_eye_cannot_claim_success_with_incomplete_runtime(tmp_path):
    with pytest.raises(RuntimeError, match="complete Slicer"):
        profiles.stage_edition(source_stage(tmp_path), tmp_path / "eagle", profiles.EDITIONS["eagle-eye"])


def test_old_installer_is_not_reused_when_compiler_produces_nothing(tmp_path):
    source = source_stage(tmp_path)
    add_complete_slicer_runtime(source)
    (tmp_path / "old-installer.exe").write_bytes(b"stale installer fixture")
    installer_dir = tmp_path / "installer"
    builder = SimpleNamespace(OUTPUT_DIR=tmp_path, INSTALLER_OUTPUT_DIR=installer_dir,
                              STAGE_DIR=source, BUILDER_DIR=tmp_path,
                              INSTALLER_SCRIPT=Path("standard.iss"), find_iscc=lambda: Path("iscc.exe"),
                              run_command=lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="did not produce"):
        profiles.compile_editions(builder, "9.9.9", "standard")
    assert not (installer_dir / "distributions.json").exists()
    assert not (tmp_path / "distributions").exists()


def test_isolated_candidate_accepts_only_explicit_canonical_repo_output(tmp_path):
    source = source_stage(tmp_path)
    add_complete_slicer_runtime(source)
    snapshot_output = tmp_path / "snapshot/builder/output"
    canonical = tmp_path / "final-repo/builder/output/installer"

    def compile_fixture(command, **kwargs):
        values = dict(arg[2:].split("=", 1) for arg in command if arg.startswith("/D"))
        compiled = Path(values["InstallerOutputDir"]) / (values["InstallerBaseName"] + ".exe")
        compiled.write_bytes(b"synthetic installer")

    builder = SimpleNamespace(
        OUTPUT_DIR=snapshot_output,
        INSTALLER_OUTPUT_DIR=canonical,
        EXPECTED_INSTALLER_OUTPUT_DIR=canonical,
        STAGE_DIR=source,
        BUILDER_DIR=tmp_path,
        INSTALLER_SCRIPT=Path("standard.iss"),
        find_iscc=lambda: Path("iscc.exe"),
        run_command=compile_fixture,
    )

    result = profiles.compile_editions(builder, "9.9.9", "standard")

    assert Path(result["outputs"][0]["installer"]).parent == canonical
    builder.INSTALLER_OUTPUT_DIR = tmp_path / "lookalike/builder/output/installer"
    with pytest.raises(ValueError, match="existing output/installer"):
        profiles.compile_editions(builder, "9.9.9", "standard")


def test_oversized_standard_installer_is_a_failure(tmp_path):
    def compile_fixture(command, **kwargs):
        values = dict(arg[2:].split("=", 1) for arg in command if arg.startswith("/D"))
        (Path(values["InstallerOutputDir"]) / (values["InstallerBaseName"] + ".exe")).write_bytes(b"too large")
    source = source_stage(tmp_path)
    add_complete_slicer_runtime(source)
    builder = SimpleNamespace(OUTPUT_DIR=tmp_path, INSTALLER_OUTPUT_DIR=tmp_path / "installer",
                              STAGE_DIR=source, BUILDER_DIR=tmp_path,
                              INSTALLER_SCRIPT=Path("standard.iss"), find_iscc=lambda: Path("iscc.exe"),
                              run_command=compile_fixture)
    with pytest.raises(RuntimeError, match="size budget"):
        profiles.compile_editions(builder, "9.9.9", "standard", compact_max_bytes=3)


def test_slicer_installer_preserves_required_python_example_resources():
    source = (Path(__file__).resolve().parents[3] / "builder/installer/AIPacs_Setup.iss").read_text(encoding="utf-8")
    line = next(line for line in source.splitlines() if line.startswith("Source:") and
                "plugin_packages\\advanced_mpr\\*" in line.split(";")[0])
    assert "*\\examples\\*" not in line and "*\\tests\\*" not in line


def test_installer_separates_slicer_runtime_from_eagle_eye_model_and_shows_version():
    source = (Path(__file__).resolve().parents[3] / "builder/installer/AIPacs_Setup.iss").read_text(encoding="utf-8")
    assert "AdvancedMprRuntimeAvailable" in source
    assert "OfflineLumbarAvailable" in source
    assert "SetupWindowTitle={#MyAppName} {#MyAppVersion} Setup" in source
    assert "AppVersion={#MyAppVersion}" in source
    assert "VersionInfoVersion={#MyAppVersion}" in source
    assert "RequireDistributionApproval" in source
    assert "EagleEyeBrainRuntimeAvailable" in source
    assert 'DistributionEdition == "eagle-eye" && !EagleEyeBrainRuntimeAvailable' in source


def test_individual_standard_and_arm_builds_stage_slicer_sources():
    root = Path(__file__).resolve().parents[3]
    python_builder = (root / "builder/build_release.py").read_text(encoding="utf-8")
    nuitka_builder = (root / "builder nuitka/build_nuitka_release.py").read_text(encoding="utf-8")
    assert 'if args.edition != "legacy":' in python_builder
    assert "advanced_payload = stage_advanced_mpr_payload()" in python_builder
    assert "include_slicer = True" in nuitka_builder
    assert 'if args.edition in {"all", "standard", "eagle-eye", "arm"}:' in nuitka_builder


def test_three_output_contract_and_arm_identity(tmp_path, bundle, brain_payload):
    import shutil
    from builder.build_release import ADVANCED_MPR_REQUIRED_RUNTIME_FILES
    source = source_stage(tmp_path)
    payload = source / "plugin_packages/advanced_mpr/payload"
    for relative in ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
        file = payload / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic fixture")
    module_path = payload / "python/modules/mpr/advanced_3d_slicer/slicer_modules"
    module_path.mkdir(parents=True)
    for name in ("AIPacsBackgroundRuntime.py", "AIPacsOfflineLumbar.py"):
        (module_path / name).write_text("# Synthetic integration fixture\n")
    shutil.copytree(bundle, payload / "offline_lumbar")
    shutil.copytree(brain_payload, payload / 'eagle_eye/brain')
    make_lesion_payload(payload / 'eagle_eye/brain-lesions')
    make_accepted_payload(payload / 'eagle_eye/alignment')
    make_spine_payload(payload / 'eagle_eye/total-spine')
    commands = []
    def compile_fixture(command, **kwargs):
        commands.append(command)
        values = dict(arg[2:].split("=", 1) for arg in command if arg.startswith("/D"))
        (Path(values["InstallerOutputDir"]) / (values["InstallerBaseName"] + ".exe")).write_bytes(b"fixture")
    installer_dir = tmp_path / "installer"
    builder = SimpleNamespace(OUTPUT_DIR=tmp_path, INSTALLER_OUTPUT_DIR=installer_dir,
                              STAGE_DIR=source, BUILDER_DIR=tmp_path,
                              INSTALLER_SCRIPT=Path("standard.iss"), INSTALLER_SCRIPT_WOA=Path("arm.iss"),
                              find_iscc=lambda: Path("iscc.exe"), run_command=compile_fixture)
    result = profiles.compile_editions(builder, "9.9.9")
    assert len(result["outputs"]) == len(commands) == 3 and result["published"] is False
    expected_names = {
        "ai-pacs eagle-eye v9.9.9.exe",
        "ai-pacs standard v9.9.9.exe",
        "ai-pacs arm64-emulated v9.9.9.exe",
    }
    assert {Path(row["installer"]).name for row in result["outputs"]} == expected_names
    assert all(Path(row["installer"]).parent == installer_dir for row in result["outputs"])
    assert expected_names <= {path.name for path in installer_dir.glob("*.exe")}
    assert (installer_dir / "distributions.json").is_file()
    assert (installer_dir / "INSTALL_NOTES.txt").is_file()
    assert (installer_dir / "SHA256.txt").is_file()
    assert not (tmp_path / "distributions").exists()
    by_edition = {row["edition"]: Path(row["stage"]) for row in result["outputs"]}
    assert (by_edition["eagle-eye"] / "plugin_packages/advanced_mpr/payload/offline_lumbar/manifest.json").exists()
    assert (by_edition['eagle-eye'] / 'plugin_packages/advanced_mpr/payload/eagle_eye/brain/model/manifest.json').exists()
    for name in ("standard", "arm"):
        payload = by_edition[name] / "plugin_packages/advanced_mpr/payload"
        assert (payload / "AIPacsAdvancedViewer.exe").is_file()
        assert not (payload / "offline_lumbar").exists()
        assert not (payload / 'eagle_eye').exists()
    identity = json.loads((by_edition["arm"] / "manifest/distribution.json").read_text())
    assert identity["install_package"] == "x64_on_arm64"
    assert identity["slicer_included"] is True
    assert identity["offline_lumbar_included"] is False
    definitions = [
        {arg[2:].split("=", 1)[0]: arg[2:].split("=", 1)[1]
         for arg in command if arg.startswith("/D")}
        for command in commands
    ]
    assert definitions[0]["IncludeAdvancedMpr"] == "1"
    assert definitions[0]["IncludeOfflineLumbar"] == "1"
    assert definitions[1]["IncludeAdvancedMpr"] == "1"
    assert definitions[1]["IncludeOfflineLumbar"] == "0"
    assert definitions[2]["IncludeAdvancedMpr"] == "1"
    assert definitions[2]["IncludeOfflineLumbar"] == "0"
    assert commands[-1][-1] == "arm.iss"


def test_internal_eagle_eye_stage_does_not_require_distribution_receipt(
    tmp_path, bundle, brain_payload
):
    import shutil
    from builder.build_release import ADVANCED_MPR_REQUIRED_RUNTIME_FILES

    source = source_stage(tmp_path)
    payload_root = source / "plugin_packages/advanced_mpr/payload"
    for relative in ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
        file = payload_root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic fixture")
    module_path = payload_root / "python/modules/mpr/advanced_3d_slicer/slicer_modules"
    module_path.mkdir(parents=True)
    for name in ("AIPacsBackgroundRuntime.py", "AIPacsOfflineLumbar.py"):
        (module_path / name).write_text("# Synthetic integration fixture\n")
    shutil.copytree(bundle, payload_root / "offline_lumbar")
    shutil.copytree(brain_payload, payload_root / "eagle_eye/brain")
    make_lesion_payload(payload_root / 'eagle_eye/brain-lesions')
    make_accepted_payload(payload_root / 'eagle_eye/alignment')
    make_spine_payload(payload_root / 'eagle_eye/total-spine')
    (payload_root / "eagle_eye/brain/distribution-approval.json").unlink()

    staged = profiles.stage_edition(
        source,
        tmp_path / "eagle-eye",
        profiles.EDITIONS["eagle-eye"],
        for_distribution=False,
    )

    assert (staged / "plugin_packages/advanced_mpr/payload/eagle_eye/brain/model/manifest.json").is_file()


def test_internal_installer_compile_explicitly_disables_distribution_receipt_gate(
    tmp_path, bundle, brain_payload
):
    import shutil
    from builder.build_release import ADVANCED_MPR_REQUIRED_RUNTIME_FILES

    source = source_stage(tmp_path)
    payload_root = source / "plugin_packages/advanced_mpr/payload"
    for relative in ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
        file = payload_root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"synthetic fixture")
    module_path = payload_root / "python/modules/mpr/advanced_3d_slicer/slicer_modules"
    module_path.mkdir(parents=True)
    for name in ("AIPacsBackgroundRuntime.py", "AIPacsOfflineLumbar.py"):
        (module_path / name).write_text("# Synthetic integration fixture\n")
    shutil.copytree(bundle, payload_root / "offline_lumbar")
    shutil.copytree(brain_payload, payload_root / "eagle_eye/brain")
    make_lesion_payload(payload_root / 'eagle_eye/brain-lesions')
    make_accepted_payload(payload_root / 'eagle_eye/alignment')
    make_spine_payload(payload_root / 'eagle_eye/total-spine')
    (payload_root / "eagle_eye/brain/distribution-approval.json").unlink()
    commands = []

    def compile_fixture(command, **kwargs):
        commands.append(command)
        values = dict(arg[2:].split("=", 1) for arg in command if arg.startswith("/D"))
        (Path(values["InstallerOutputDir"]) / (values["InstallerBaseName"] + ".exe")).write_bytes(
            b"synthetic installer"
        )

    installer_dir = tmp_path / "installer"
    builder = SimpleNamespace(
        OUTPUT_DIR=tmp_path,
        INSTALLER_OUTPUT_DIR=installer_dir,
        STAGE_DIR=source,
        BUILDER_DIR=tmp_path,
        INSTALLER_SCRIPT=Path("standard.iss"),
        INSTALLER_SCRIPT_WOA=Path("arm.iss"),
        find_iscc=lambda: Path("iscc.exe"),
        run_command=compile_fixture,
    )

    profiles.compile_editions(
        builder,
        "9.9.9",
        "eagle-eye",
        for_distribution=False,
    )

    definitions = {
        arg[2:].split("=", 1)[0]: arg[2:].split("=", 1)[1]
        for arg in commands[0]
        if arg.startswith("/D")
    }
    assert definitions["RequireDistributionApproval"] == "0"


def test_new_build_defaults_to_all_three_editions(monkeypatch):
    import sys
    from builder.build_release import parse_args
    monkeypatch.setattr(sys, "argv", ["build.py"])
    assert parse_args().edition == "all"


def test_asset_cache_tampering_is_detected(tmp_path):
    import hashlib
    from tools.build.prepare_distribution_assets import verify
    names = ("slicer-runtime/AIPacsAdvancedViewer.exe", "offline_lumbar/manifest.json",
             "offline_lumbar/python/python.exe", "inno-setup/ISCC.exe",
             "downloads/python-3.13.5-amd64.exe", "build-environment.lock")
    records = []
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        records.append({"path": name, "size": 7, "sha256": hashlib.sha256(b"fixture").hexdigest()})
    (tmp_path / "manifest.json").write_text(json.dumps({"format_version": 1, "platform": "win_amd64", "files": records}))
    assert len(verify(tmp_path)["files"]) == 6
    (tmp_path / names[0]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify(tmp_path)


def test_asset_cache_verification_avoids_windows_file_digest_einval(tmp_path, monkeypatch):
    import hashlib
    from tools.build.prepare_distribution_assets import verify

    names = ("slicer-runtime/AIPacsAdvancedViewer.exe", "offline_lumbar/manifest.json",
             "offline_lumbar/python/python.exe", "inno-setup/ISCC.exe",
             "downloads/python-3.13.5-amd64.exe", "build-environment.lock")
    records = []
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"large-release-asset-fixture")
        records.append({
            "path": name,
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (tmp_path / "manifest.json").write_text(json.dumps({
        "format_version": 1,
        "platform": "win_amd64",
        "files": records,
    }))

    def fail_like_windows_large_file(*_args, **_kwargs):
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(hashlib, "file_digest", fail_like_windows_large_file)
    assert len(verify(tmp_path)["files"]) == len(names)
