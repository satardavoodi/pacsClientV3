"""Native runtime staging must not overwrite an active Developer Run runtime."""

import hashlib
from pathlib import Path

import pytest

from tools.slicer import assemble_slicer_runtime as assembly


class _LegacyConsole:
    encoding = "cp1256"

    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_slicer_assembly_configures_utf8_console_for_status_output():
    console = _LegacyConsole()

    assembly.configure_console_output(console)

    assert console.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_slicer_assembly_writes_launcher_settings_for_root_and_inner_binary(tmp_path):
    assembly.write_runtime_launcher_settings(tmp_path)

    root_settings = tmp_path / "AIPacsAdvancedViewerLauncherSettings.ini"
    inner_settings = tmp_path / "bin" / "AIPacsAdvancedViewerLauncherSettings.ini"
    assert root_settings.read_bytes() == inner_settings.read_bytes()


def test_slicer_assembly_copies_current_startup_bridge(tmp_path):
    project = tmp_path / "project"
    source = project / "modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py"
    source.parent.mkdir(parents=True)
    source.write_text("CURRENT_STARTUP_BRIDGE", encoding="utf-8")
    runtime = tmp_path / "runtime"

    assembly.copy_runtime_startup_bridge(project, runtime)

    assert (runtime / "bin/Python/startup_script.py").read_text(encoding="utf-8") == "CURRENT_STARTUP_BRIDGE"


def test_explicit_slicer_assembly_output_must_be_new(tmp_path):
    assert assembly.select_output_target(None) == assembly.TARGET
    staged = tmp_path / "new-runtime"
    assert assembly.select_output_target(staged) == staged.resolve()

    staged.mkdir()
    with pytest.raises(ValueError, match="new, specific directory"):
        assembly.select_output_target(staged)

    with pytest.raises(ValueError, match="new, specific directory"):
        assembly.select_output_target(Path(staged.anchor))

    with pytest.raises(ValueError, match="new, specific directory"):
        assembly.select_output_target(assembly.TARGET / "nested-staging")


def test_slicer_assembly_stages_exact_app_local_vc_runtime(tmp_path):
    donor = tmp_path / "official-redist"
    donor.mkdir()
    (donor / "msvcp140.dll").write_bytes(b"matching compiler CRT")
    expected = {"msvcp140.dll": hashlib.sha256(b"matching compiler CRT").hexdigest()}
    runtime = tmp_path / "candidate"

    assembly.stage_vc_runtime(donor, runtime, expected_hashes=expected)

    assert (runtime / "bin/Release/msvcp140.dll").read_bytes() == b"matching compiler CRT"
    (donor / "msvcp140.dll").write_bytes(b"older system CRT")
    with pytest.raises(ValueError, match="hash mismatch"):
        assembly.stage_vc_runtime(donor, tmp_path / "rejected", expected_hashes=expected)
