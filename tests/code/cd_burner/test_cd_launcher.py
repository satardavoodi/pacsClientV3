"""Tests for the CD launcher: manifest resolution + the local cache strategy.

The launcher is a standalone, stdlib-only module (tkinter is imported lazily
only when showing the splash), so it imports cleanly headless. The cache copy
uses robocopy with a pure-python fallback, so these run on a normal Windows venv.
"""

import json
from pathlib import Path

from modules.cd_burner.portable_viewer import cd_launcher


# ---------------------------------------------------------------------------
# manifest-driven viewer resolution
# ---------------------------------------------------------------------------

def test_viewer_rel_from_manifest_reads_launcher(tmp_path):
    (tmp_path / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({"viewer_launcher": "VIEWER/AIPacsLiteViewer.exe"}), encoding="utf-8"
    )
    assert cd_launcher._viewer_rel_from_manifest(str(tmp_path)) == "VIEWER\\AIPacsLiteViewer.exe"


def test_viewer_rel_from_manifest_falls_back_without_manifest(tmp_path):
    assert cd_launcher._viewer_rel_from_manifest(str(tmp_path)) == "VIEWER\\AIPacsLiteViewer.exe"


# ---------------------------------------------------------------------------
# cache signature / validity / prune (pure helpers)
# ---------------------------------------------------------------------------

def _fake_cd(tmp_path, with_internal=True, images=3):
    root = tmp_path / "cd"
    viewer = root / "VIEWER"
    viewer.mkdir(parents=True)
    (viewer / "AIPacsLiteViewer.exe").write_bytes(b"MZ viewer")
    if with_internal:
        (viewer / "_internal").mkdir()
        (viewer / "_internal" / "base_library.zip").write_bytes(b"PK runtime")
    # launcher infra at root (must be EXCLUDED from the study signature/cache)
    (root / "AIPacsViewer.exe").write_bytes(b"MZ launcher")
    (root / "RUN_VIEWER.cmd").write_text("@echo off", encoding="utf-8")
    (root / "autorun.inf").write_text("[autorun]", encoding="utf-8")
    (root / "AIPACS_MEDIA_INFO.json").write_text(
        json.dumps({"viewer_launcher": "VIEWER/AIPacsLiteViewer.exe"}), encoding="utf-8"
    )
    # study data
    (root / "DICOMDIR").write_bytes(b"DICM" + b"\x00" * 200)
    pt = root / "PT000000" / "ST000000" / "SE000000"
    pt.mkdir(parents=True)
    for i in range(images):
        (pt / f"IM{i:06d}").write_bytes(b"DICM" + bytes([i]) * 64)
    return root


def test_signature_excludes_viewer_and_launcher_and_is_deterministic(tmp_path):
    root = _fake_cd(tmp_path, images=3)
    key1, count1, bytes1 = cd_launcher.compute_study_signature(str(root))
    key2, count2, bytes2 = cd_launcher.compute_study_signature(str(root))
    assert key1 == key2 and count1 == count2 and bytes1 == bytes2  # deterministic
    # study files = DICOMDIR + manifest + START_HERE(none here) + 3 images
    # but NOT the viewer bundle or launcher infra
    rels = {rel for rel, _ in cd_launcher.iter_study_files(str(root))}
    assert "dicomdir" in rels
    assert not any("viewer/" in r for r in rels)         # VIEWER dir excluded
    assert "aipacsviewer.exe" not in rels                # launcher exe excluded
    assert "run_viewer.cmd" not in rels
    assert "autorun.inf" not in rels


def test_signature_changes_when_study_changes(tmp_path):
    root = _fake_cd(tmp_path, images=2)
    k1, _, _ = cd_launcher.compute_study_signature(str(root))
    (root / "PT000000" / "ST000000" / "SE000000" / "IM000099").write_bytes(b"DICM new")
    k2, _, _ = cd_launcher.compute_study_signature(str(root))
    assert k1 != k2


def test_cache_marker_validity(tmp_path):
    study = tmp_path / "study"
    study.mkdir()
    (study / "DICOMDIR").write_bytes(b"x" * 100)
    count, total = cd_launcher.dir_stats(str(study))
    cd_launcher.write_cache_marker(str(study), "KEY1", count, total)
    assert cd_launcher.is_study_cache_valid(str(study), "KEY1")
    assert not cd_launcher.is_study_cache_valid(str(study), "OTHERKEY")  # wrong key
    # tampering (extra file) invalidates the cache
    (study / "DICOMDIR2").write_bytes(b"y" * 50)
    assert not cd_launcher.is_study_cache_valid(str(study), "KEY1")


def test_prune_keeps_newest_and_never_deletes_current(tmp_path):
    studies = tmp_path / "studies"
    studies.mkdir()
    dirs = []
    for i in range(5):
        d = studies / f"s{i}"
        d.mkdir()
        (d / "f.bin").write_bytes(b"z" * 10)
        cd_launcher.write_cache_marker(str(d), f"K{i}", 1, 10)
        import os as _os
        _os.utime(cd_launcher._marker_path(str(d)), (1000 + i, 1000 + i))  # s4 newest
        dirs.append(d)

    current = dirs[0]  # oldest, but in use → must survive
    cd_launcher.prune_studies(str(studies), str(current), keep=2, max_bytes=10 ** 12)

    assert current.is_dir()          # current never deleted
    assert dirs[4].is_dir()          # newest kept
    assert not dirs[1].is_dir()      # old ones pruned
    assert not dirs[2].is_dir()


# ---------------------------------------------------------------------------
# _prepare orchestration (cache-first, CD fallback)
# ---------------------------------------------------------------------------

def _patch_common(monkeypatch, cache_dir):
    monkeypatch.setattr(cd_launcher, "cache_root", lambda: str(cache_dir))
    monkeypatch.setattr(cd_launcher, "_is_32bit_windows", lambda: False)
    monkeypatch.setattr(cd_launcher, "_open_folder", lambda p: None)
    launched = {}
    monkeypatch.setattr(
        cd_launcher, "_launch",
        lambda exe, folder: launched.update(exe=exe, folder=folder) or True,
    )
    return launched


def test_prepare_caches_study_and_launches_from_local_cache(tmp_path, monkeypatch):
    """Core perf fix: viewer + study are copied to the LOCAL cache and the viewer
    is launched from the cache with --import-folder pointed at the cached study —
    so runtime reads never hit the CD."""
    root = _fake_cd(tmp_path, with_internal=True, images=4)
    cache = tmp_path / "cache"
    launched = _patch_common(monkeypatch, cache)

    state = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
    cd_launcher._prepare(str(root), state)

    assert state["ok"] is True
    assert state["mode"] == "cache"
    key, _c, _b = cd_launcher.compute_study_signature(str(root))
    study_dir = cache / "studies" / key
    # launched the CACHED viewer, import folder is the CACHED study (not the CD)
    assert launched["exe"] == str(cache / "viewer" / "AIPacsLiteViewer.exe")
    assert launched["folder"] == str(study_dir)
    # study data copied locally; viewer bundle NOT mixed into the study cache
    assert (study_dir / "DICOMDIR").is_file()
    assert (study_dir / "PT000000" / "ST000000" / "SE000000" / "IM000000").is_file()
    assert not (study_dir / "VIEWER").exists()
    assert not (study_dir / "AIPacsViewer.exe").exists()
    # marker written + valid → reopening will reuse
    assert cd_launcher.is_study_cache_valid(str(study_dir), key)


def test_prepare_reuses_valid_cache_on_reopen(tmp_path, monkeypatch):
    root = _fake_cd(tmp_path, with_internal=True, images=3)
    cache = tmp_path / "cache"
    _patch_common(monkeypatch, cache)

    s1 = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
    cd_launcher._prepare(str(root), s1)
    assert s1["ok"]

    # second run must reuse (status reflects cache hit, still launches from cache)
    s2 = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
    cd_launcher._prepare(str(root), s2)
    assert s2["ok"] and s2["mode"] == "cache"


def test_prepare_single_exe_runs_from_cd_but_study_is_cached(tmp_path, monkeypatch):
    """A single-exe viewer (no _internal) runs from the CD, but the study is
    still cached locally so image viewing is smooth."""
    root = _fake_cd(tmp_path, with_internal=False, images=2)
    cache = tmp_path / "cache"
    launched = _patch_common(monkeypatch, cache)

    state = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
    cd_launcher._prepare(str(root), state)

    assert state["ok"] is True
    key, _c, _b = cd_launcher.compute_study_signature(str(root))
    study_dir = cache / "studies" / key
    assert launched["exe"] == str(root / "VIEWER" / "AIPacsLiteViewer.exe")  # from CD
    assert launched["folder"] == str(study_dir)                              # cached study


def test_prepare_falls_back_to_cd_when_cache_unavailable(tmp_path, monkeypatch):
    """If the local cache can't be prepared, the viewer still opens straight from
    the CD (graceful — never blocks)."""
    root = _fake_cd(tmp_path, with_internal=True, images=2)
    cache = tmp_path / "cache"
    launched = _patch_common(monkeypatch, cache)
    # force the cache step to fail
    monkeypatch.setattr(cd_launcher, "compute_study_signature",
                        lambda r: (_ for _ in ()).throw(RuntimeError("boom")))

    state = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
    cd_launcher._prepare(str(root), state)

    assert state["ok"] is True
    assert state["mode"] == "cd"
    # viewer from CD, import folder = the CD root (fallback)
    assert launched["exe"] == str(root / "VIEWER" / "AIPacsLiteViewer.exe")
    assert launched["folder"] == str(root)


def test_prepare_32bit_opens_folder_without_launching(tmp_path, monkeypatch):
    root = _fake_cd(tmp_path, with_internal=True)
    monkeypatch.setattr(cd_launcher, "_is_32bit_windows", lambda: True)
    opened = {}
    monkeypatch.setattr(cd_launcher, "_open_folder", lambda p: opened.update(p=p))
    monkeypatch.setattr(cd_launcher, "_launch",
                        lambda *a: (_ for _ in ()).throw(AssertionError("must not launch")))

    state = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
    cd_launcher._prepare(str(root), state)

    assert state["ok"] is False
    assert "64-bit" in state["error"]
    assert opened["p"] == str(root)


def test_launcher_constants_and_no_workstation_imports():
    assert cd_launcher.PREPARING_MESSAGE == "Preparing viewer, please wait."
    for line in Path(cd_launcher.__file__).read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(("import ", "from ")):
            assert "modules" not in s, f"unexpected workstation import: {line}"
