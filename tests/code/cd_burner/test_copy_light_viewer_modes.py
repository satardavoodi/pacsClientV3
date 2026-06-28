"""Viewer staging: single bare exe vs portable bundle, archive exclusion."""

import json
from pathlib import Path

from modules.cd_burner.cd_burn_manager import CDBurnWorker


def _make_worker(viewer_exe: Path, display_name=None) -> CDBurnWorker:
    return CDBurnWorker(
        studies=[],
        light_viewer_path=str(viewer_exe),
        disc_label="PATIENT_CD",
        burn_to_disc=False,
        viewer_display_name=display_name,
    )


def test_single_bare_exe_copies_only_the_exe(tmp_path):
    src = tmp_path / "downloads"
    src.mkdir()
    exe = src / "SomeViewer.exe"
    exe.write_bytes(b"MZ viewer")
    (src / "unrelated.exe").write_bytes(b"MZ other")
    (src / "notes.txt").write_text("junk", encoding="utf-8")

    staging = tmp_path / "staging"
    staging.mkdir()
    worker = _make_worker(exe)
    worker._copy_light_viewer(str(staging))

    viewer_dir = staging / "VIEWER"
    copied = sorted(p.name for p in viewer_dir.iterdir())
    assert copied == ["SomeViewer.exe"]

    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    assert manifest["viewer_included"] is True
    assert manifest["viewer_launcher"] == "VIEWER/SomeViewer.exe"

    run_cmd = (staging / "RUN_VIEWER.cmd").read_text(encoding="utf-8")
    assert "VIEWER\\SomeViewer.exe" in run_cmd


def test_bundle_copies_tree_but_never_junk_archives(tmp_path):
    src = tmp_path / "AIPacsLiteViewer"
    (src / "resources").mkdir(parents=True)
    (src / "_internal").mkdir()
    exe = src / "AIPacsLiteViewer.exe"
    exe.write_bytes(b"MZ lite")
    (src / "Qt6Core.dll").write_bytes(b"DLL")
    (src / "resources" / "icon.png").write_bytes(b"PNG")
    (src / "lightViewer.rar").write_bytes(b"RAR" * 1000)
    (src / "archive.7z").write_bytes(b"7Z")
    # PyInstaller runtime: a ZIP that MUST be staged (2026-06-07 incident —
    # excluding *.zip stripped base_library.zip and bricked the viewer).
    (src / "_internal" / "base_library.zip").write_bytes(b"PK runtime")

    staging = tmp_path / "staging"
    staging.mkdir()
    worker = _make_worker(exe, display_name="AI-PACS Lite Viewer")
    worker._copy_light_viewer(str(staging))

    viewer_dir = staging / "VIEWER"
    assert (viewer_dir / "AIPacsLiteViewer.exe").exists()
    assert (viewer_dir / "Qt6Core.dll").exists()
    assert (viewer_dir / "resources" / "icon.png").exists()
    assert (viewer_dir / "_internal" / "base_library.zip").exists()
    assert not (viewer_dir / "lightViewer.rar").exists()
    assert not (viewer_dir / "archive.7z").exists()

    manifest = json.loads((staging / "AIPACS_MEDIA_INFO.json").read_text(encoding="utf-8"))
    assert manifest["viewer_display_name"] == "AI-PACS Lite Viewer"
    autorun = (staging / "autorun.inf").read_text(encoding="utf-8")
    assert "action=Open AI-PACS Lite Viewer" in autorun
    assert "icon=AIPACS.ico" in autorun           # AI-PACS icon on the CD drive


def test_launcher_has_32bit_guard_and_autorun_uses_cmd(tmp_path):
    """RUN_VIEWER.cmd must degrade gracefully on 32-bit Windows, and autorun
    must route through it so the guard runs on autorun too."""
    src = tmp_path / "viewerdir"
    src.mkdir()
    exe = src / "v.exe"
    exe.write_bytes(b"MZ")
    staging = tmp_path / "staging"
    staging.mkdir()
    worker = _make_worker(exe, display_name="AI-PACS Lite Viewer")
    worker._copy_light_viewer(str(staging))

    run_cmd = (staging / "RUN_VIEWER.cmd").read_text(encoding="utf-8")
    assert 'PROCESSOR_ARCHITECTURE' in run_cmd and 'PROCESSOR_ARCHITEW6432' in run_cmd
    assert "requires 64-bit Windows" in run_cmd
    assert "explorer.exe" in run_cmd  # opens the DICOM folder as fallback

    # No launcher exe alongside this fake viewer → autorun falls back to the
    # .cmd, and we never ship a .hta (no 'open with' prompt).
    autorun = (staging / "autorun.inf").read_text(encoding="utf-8")
    assert "open=RUN_VIEWER.cmd" in autorun
    assert ".hta" not in autorun
    assert not (staging / "RUN_VIEWER.hta").exists()

    readme = (staging / "START_HERE.txt").read_text(encoding="utf-8")
    assert "64-bit Windows" in readme


def test_launcher_exe_staged_at_root_and_used_by_autorun(tmp_path):
    """When the launcher exe sits next to the viewer dist
    (lightViewer_dist/AIPacsViewer.exe), the burn copies it to the media ROOT
    and autorun launches it directly — a GUI exe → no console, no 'open with'."""
    dist = tmp_path / "lightViewer_dist"
    viewer = dist / "AIPacsLiteViewer"
    (viewer / "_internal").mkdir(parents=True)
    exe = viewer / "AIPacsLiteViewer.exe"
    exe.write_bytes(b"MZ viewer")
    (viewer / "_internal" / "base_library.zip").write_bytes(b"PK")
    # the branded launcher, two levels up from the viewer exe
    (dist / "AIPacsViewer.exe").write_bytes(b"MZ launcher")

    staging = tmp_path / "staging"
    staging.mkdir()
    worker = _make_worker(exe, display_name="AI-PACS Lite Viewer")
    worker._copy_light_viewer(str(staging))

    # launcher copied to the media root, viewer bundle under VIEWER/
    assert (staging / "AIPacsViewer.exe").exists()
    assert (staging / "VIEWER" / "AIPacsLiteViewer.exe").exists()

    autorun = (staging / "autorun.inf").read_text(encoding="utf-8")
    assert "open=AIPacsViewer.exe" in autorun
    assert ".hta" not in autorun
    assert not (staging / "RUN_VIEWER.hta").exists()


def test_staging_verification_passes_after_viewer_copy(tmp_path):
    src = tmp_path / "bundle"
    src.mkdir()
    exe = src / "Viewer.exe"
    exe.write_bytes(b"MZ")
    (src / "dep.dll").write_bytes(b"DLL")

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "DICOMDIR").write_bytes(b"DICM dummy")

    worker = _make_worker(exe)
    worker._copy_light_viewer(str(staging))

    verification = worker._verify_staging_output(str(staging))
    assert verification["ok"], verification["issues"]
