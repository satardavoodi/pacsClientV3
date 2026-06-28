import json
import tempfile
from pathlib import Path

from modules.cd_burner.cd_burn_manager import CDBurnWorker, inspect_viewer_portability
from modules.cd_burner.cd_writer import normalize_fileset_label, normalize_volume_label


def test_normalize_fileset_label_for_dicom_compatibility():
    assert normalize_fileset_label("Patient CD 2026/03/17") == "PATIENT_CD_2026"
    assert normalize_fileset_label("***") == "DICOM"
    assert len(normalize_fileset_label("averyveryverylonglabelvalue")) <= 16


def test_normalize_volume_label_for_windows_media_compatibility():
    label = normalize_volume_label("Patient CD 2026/03/17")

    assert label == "PATIENT CD 2026_03_17"
    assert len(label) <= 32


def test_write_portable_support_files_with_viewer_launcher():
    staging = Path(tempfile.mkdtemp(prefix="cd_media_test_"))
    worker = CDBurnWorker(studies=[], burn_to_disc=False)

    worker._write_portable_support_files(
        str(staging),
        fileset_label="PATIENT_CD_2026",
        volume_label="PATIENT CD 2026_03_17",
        viewer_launcher_relative_path=Path("VIEWER") / "Viewer.exe",
        viewer_display_name="Viewer",
    )

    assert (staging / "START_HERE.txt").exists()
    assert (staging / "RUN_VIEWER.cmd").exists()
    assert (staging / "OPEN_DICOM_FOLDER.cmd").exists()
    assert (staging / "autorun.inf").exists()

    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    assert manifest["fileset_id"] == "PATIENT_CD_2026"
    assert manifest["viewer_included"] is True
    assert manifest["viewer_launcher"] == "VIEWER/Viewer.exe"

    # No launcher exe was staged here → autorun falls back to RUN_VIEWER.cmd.
    autorun = (staging / "autorun.inf").read_text(encoding="utf-8")
    assert "open=RUN_VIEWER.cmd" in autorun
    assert "icon=VIEWER\\Viewer.exe,0" in autorun
    # We must NEVER ship a .hta launcher (it triggers a Windows 'open with' prompt).
    assert not (staging / "RUN_VIEWER.hta").exists()
    assert ".hta" not in autorun

    launch_script = (staging / "RUN_VIEWER.cmd").read_text(encoding="utf-8")
    assert "--import-folder \"%~dp0\"" in launch_script

    readme = (staging / "START_HERE.txt").read_text(encoding="utf-8")
    assert "RUN_VIEWER.cmd" in readme
    assert "DICOMDIR" in readme


def test_run_viewer_copies_onedir_bundle_to_local_disk():
    """A PyInstaller onedir bundle (has _internal) must be copied to local disk
    before running — launching it directly off optical media fails with
    'Could not load PyInstaller's embedded PKG archive from the executable'.
    The launcher copies VIEWER -> %TEMP% and runs from there, with an
    in-place fallback if the copy fails (and for single-exe viewers)."""
    staging = Path(tempfile.mkdtemp(prefix="cd_media_test_copy_"))
    worker = CDBurnWorker(studies=[], burn_to_disc=False)

    worker._write_portable_support_files(
        str(staging),
        fileset_label="DICOM",
        volume_label="DICOM",
        viewer_launcher_relative_path=Path("VIEWER") / "AIPacsLiteViewer.exe",
        viewer_display_name="AI-PACS Lite Viewer",
    )

    cmd = (staging / "RUN_VIEWER.cmd").read_text(encoding="utf-8")
    # only copy genuine onedir bundles (gated on the _internal folder)
    assert "_internal" in cmd
    assert "robocopy" in cmd
    assert "%TEMP%\\AIPacsLiteViewer" in cmd
    # runs the copied exe and points the import folder at the disc root
    assert "set \"VIEWER_EXE=AIPacsLiteViewer.exe\"" in cmd
    assert "%TEMP%\\AIPacsLiteViewer\\%VIEWER_EXE%" in cmd
    assert "--import-folder \"%~dp0\"" in cmd
    # graceful fallbacks remain
    assert ":runinplace" in cmd
    assert "requires 64-bit Windows" in cmd

    readme = (staging / "START_HERE.txt").read_text(encoding="utf-8")
    assert "copies the viewer to" in readme


def test_exe_launcher_is_primary_and_no_open_with_prompt():
    """The double-click launcher must be a GUI EXE (no console, no Windows
    'open with' prompt). When a launcher exe is staged, autorun launches it
    directly and we ship NO .hta (the .hta was what triggered the 'open with
    HTML' prompt)."""
    staging = Path(tempfile.mkdtemp(prefix="cd_media_test_exe_"))
    worker = CDBurnWorker(studies=[], burn_to_disc=False)

    worker._write_portable_support_files(
        str(staging),
        fileset_label="DICOM",
        volume_label="DICOM",
        viewer_launcher_relative_path=Path("VIEWER") / "AIPacsLiteViewer.exe",
        viewer_display_name="AI-PACS Lite Viewer",
        launcher_exe_name="AIPacsViewer.exe",
    )

    # No .hta anywhere — neither a file nor referenced by autorun.
    assert not (staging / "RUN_VIEWER.hta").exists()

    autorun = (staging / "autorun.inf").read_text(encoding="utf-8")
    assert "open=AIPacsViewer.exe" in autorun
    assert "shellexecute=AIPacsViewer.exe" in autorun
    assert "mshta" not in autorun
    assert ".hta" not in autorun

    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    assert manifest["viewer_launcher_primary"] == "AIPacsViewer.exe"
    assert "AIPacsViewer.exe" in manifest["portable_launchers"]

    readme = (staging / "START_HERE.txt").read_text(encoding="utf-8")
    assert "AIPacsViewer.exe" in readme
    # RUN_VIEWER.cmd remains as a fallback
    assert (staging / "RUN_VIEWER.cmd").exists()


def test_write_portable_support_files_without_viewer_launcher():
    staging = Path(tempfile.mkdtemp(prefix="cd_media_test_no_viewer_"))
    worker = CDBurnWorker(studies=[], burn_to_disc=False)

    worker._write_portable_support_files(
        str(staging),
        fileset_label="DICOM",
        volume_label="DICOM",
    )

    launch_script = (staging / "RUN_VIEWER.cmd").read_text(encoding="utf-8")
    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    autorun = (staging / "autorun.inf").read_text(encoding="utf-8")

    assert "No portable viewer was included" in launch_script
    assert manifest["viewer_included"] is False
    assert manifest["viewer_launcher"] is None
    assert "open=OPEN_DICOM_FOLDER.cmd" in autorun


def test_inspect_viewer_portability_detects_single_exe_warning():
    viewer_dir = Path(tempfile.mkdtemp(prefix="viewer_single_exe_"))
    viewer_exe = viewer_dir / "Viewer.exe"
    viewer_exe.write_text("binary", encoding="utf-8")

    analysis = inspect_viewer_portability(str(viewer_exe))

    assert analysis["ok"] is True
    assert analysis["bundle_mode"] == "single_exe"
    assert any("single EXE" in warning for warning in analysis["warnings"])


def test_inspect_viewer_portability_recognizes_bundle():
    viewer_dir = Path(tempfile.mkdtemp(prefix="viewer_bundle_"))
    viewer_exe = viewer_dir / "Viewer.exe"
    viewer_exe.write_text("binary", encoding="utf-8")
    (viewer_dir / "ViewerCore.dll").write_text("dll", encoding="utf-8")
    (viewer_dir / "plugins").mkdir(exist_ok=True)

    analysis = inspect_viewer_portability(str(viewer_exe))

    assert analysis["ok"] is True
    assert analysis["bundle_mode"] == "portable_bundle"


def test_verify_staging_output_passes_for_generated_media():
    staging = Path(tempfile.mkdtemp(prefix="verify_media_ok_"))
    worker = CDBurnWorker(studies=[], burn_to_disc=False)
    (staging / "DICOMDIR").write_text("dicomdir", encoding="utf-8")

    worker._write_portable_support_files(
        str(staging),
        fileset_label="PATIENT_CD_2026",
        volume_label="PATIENT CD 2026_03_17",
        viewer_launcher_relative_path=Path("VIEWER") / "Viewer.exe",
        viewer_display_name="Viewer",
    )
    (staging / "VIEWER").mkdir(exist_ok=True)
    (staging / "VIEWER" / "Viewer.exe").write_text("binary", encoding="utf-8")

    result = worker._verify_staging_output(str(staging))

    assert result["ok"] is True
    assert result["issues"] == []


def test_verify_staging_output_detects_missing_viewer_launcher():
    staging = Path(tempfile.mkdtemp(prefix="verify_media_bad_"))
    worker = CDBurnWorker(studies=[], burn_to_disc=False)
    (staging / "DICOMDIR").write_text("dicomdir", encoding="utf-8")

    worker._write_portable_support_files(
        str(staging),
        fileset_label="PATIENT_CD_2026",
        volume_label="PATIENT CD 2026_03_17",
        viewer_launcher_relative_path=Path("VIEWER") / "Viewer.exe",
        viewer_display_name="Viewer",
    )

    result = worker._verify_staging_output(str(staging))

    assert result["ok"] is False
    assert any("Viewer launcher is missing" in issue for issue in result["issues"])
