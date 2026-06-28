"""Tests for the CD launcher's pure logic (manifest-driven viewer resolution).

The launcher is a standalone, stdlib-only module (tkinter is imported lazily
only when showing the splash), so it imports cleanly headless.
"""

import json
from pathlib import Path

from modules.cd_burner.portable_viewer import cd_launcher


def test_viewer_rel_from_manifest_reads_launcher(tmp_path):
    (tmp_path / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({"viewer_launcher": "VIEWER/AIPacsLiteViewer.exe"}),
        encoding="utf-8",
    )
    rel = cd_launcher._viewer_rel_from_manifest(str(tmp_path))
    # normalized to Windows separators so os.path.join works on the media
    assert rel == "VIEWER\\AIPacsLiteViewer.exe"


def test_viewer_rel_from_manifest_handles_custom_name(tmp_path):
    (tmp_path / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({"viewer_launcher": "VIEWER/CustomViewer.exe"}),
        encoding="utf-8",
    )
    assert cd_launcher._viewer_rel_from_manifest(str(tmp_path)).endswith("CustomViewer.exe")


def test_viewer_rel_from_manifest_falls_back_without_manifest(tmp_path):
    # no manifest → default VIEWER\AIPacsLiteViewer.exe layout
    assert cd_launcher._viewer_rel_from_manifest(str(tmp_path)) == "VIEWER\\AIPacsLiteViewer.exe"


def _fake_cd(tmp_path, with_internal=True):
    root = tmp_path / "cd"
    viewer = root / "VIEWER"
    viewer.mkdir(parents=True)
    (viewer / "AIPacsLiteViewer.exe").write_bytes(b"MZ")
    if with_internal:
        (viewer / "_internal").mkdir()
        (viewer / "_internal" / "base_library.zip").write_bytes(b"PK")
    (root / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({"viewer_launcher": "VIEWER/AIPacsLiteViewer.exe"}), encoding="utf-8"
    )
    return root


def test_prepare_copies_onedir_to_temp_and_launches_from_there(tmp_path, monkeypatch):
    """The core fix: a onedir bundle (has _internal) is copied to local disk and
    the viewer is launched FROM THE COPY (running off optical media fails)."""
    root = _fake_cd(tmp_path, with_internal=True)
    temp = tmp_path / "temp"
    monkeypatch.setenv("TEMP", str(temp))
    monkeypatch.setenv("TMP", str(temp))
    monkeypatch.setattr(cd_launcher, "_is_32bit_windows", lambda: False)
    monkeypatch.setattr(cd_launcher, "_open_folder", lambda p: None)
    launched = {}
    monkeypatch.setattr(
        cd_launcher, "_launch",
        lambda exe, folder: launched.update(exe=exe, folder=folder) or True,
    )

    state = {"done": False, "ok": False, "error": ""}
    cd_launcher._prepare(str(root), state)

    assert state["ok"] is True
    copied = temp / "AIPacsLiteViewer" / "AIPacsLiteViewer.exe"
    assert copied.is_file()                      # copied to local disk
    assert launched["exe"] == str(copied)        # launched the COPY, not the disc
    assert launched["folder"] == str(root)       # images read from the disc root


def test_prepare_runs_single_exe_in_place(tmp_path, monkeypatch):
    """A single-exe viewer (no _internal) runs in place — no copy needed."""
    root = _fake_cd(tmp_path, with_internal=False)
    monkeypatch.setattr(cd_launcher, "_is_32bit_windows", lambda: False)
    monkeypatch.setattr(cd_launcher, "_open_folder", lambda p: None)
    launched = {}
    monkeypatch.setattr(
        cd_launcher, "_launch",
        lambda exe, folder: launched.update(exe=exe, folder=folder) or True,
    )

    state = {"done": False, "ok": False, "error": ""}
    cd_launcher._prepare(str(root), state)

    assert state["ok"] is True
    assert launched["exe"] == str(root / "VIEWER" / "AIPacsLiteViewer.exe")


def test_prepare_32bit_opens_folder_without_launching(tmp_path, monkeypatch):
    root = _fake_cd(tmp_path, with_internal=True)
    monkeypatch.setattr(cd_launcher, "_is_32bit_windows", lambda: True)
    opened = {}
    monkeypatch.setattr(cd_launcher, "_open_folder", lambda p: opened.update(p=p))
    monkeypatch.setattr(cd_launcher, "_launch", lambda *a: (_ for _ in ()).throw(AssertionError("must not launch")))

    state = {"done": False, "ok": False, "error": ""}
    cd_launcher._prepare(str(root), state)

    assert state["ok"] is False
    assert "64-bit" in state["error"]
    assert opened["p"] == str(root)


def test_launcher_constants_are_branded_and_exact():
    # the splash text must be the exact requested message
    assert cd_launcher.PREPARING_MESSAGE == "Preparing viewer, please wait."
    # never IMPORT the workstation chain into the standalone launcher (freeze
    # tools would drag qtawesome/comtypes/etc. into the tiny launcher exe)
    for line in Path(cd_launcher.__file__).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "modules" not in stripped, f"unexpected workstation import: {line}"
