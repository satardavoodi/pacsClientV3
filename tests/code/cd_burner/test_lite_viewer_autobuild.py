"""Release builds auto-build the lite viewer before materializing run_cd."""

import sys

import pytest

from builder import materialize_plugin_packages as mpp


def test_ensure_lite_viewer_built_runs_build_script(monkeypatch):
    calls = {}

    class _Result:
        returncode = 0

    def fake_run(cmd, cwd=None):
        calls["cmd"] = cmd
        calls["cwd"] = cwd
        return _Result()

    monkeypatch.delenv(mpp._SKIP_LITE_VIEWER_BUILD_ENV, raising=False)
    monkeypatch.setattr("subprocess.run", fake_run)

    mpp._ensure_lite_viewer_built()

    assert calls["cmd"][0] == sys.executable
    assert calls["cmd"][1].endswith("build_lite_viewer.py")


def test_ensure_lite_viewer_skip_env(monkeypatch):
    monkeypatch.setenv(mpp._SKIP_LITE_VIEWER_BUILD_ENV, "1")

    def boom(*_a, **_k):
        raise AssertionError("build must not run when skipped")

    monkeypatch.setattr("subprocess.run", boom)
    mpp._ensure_lite_viewer_built()  # no exception → did not build


def test_ensure_lite_viewer_failure_raises(monkeypatch):
    class _Result:
        returncode = 3

    monkeypatch.delenv(mpp._SKIP_LITE_VIEWER_BUILD_ENV, raising=False)
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: _Result())
    with pytest.raises(RuntimeError, match="Lite viewer build failed"):
        mpp._ensure_lite_viewer_built()


def test_materialize_build_flag_triggers_build(monkeypatch):
    triggered = {"n": 0}
    monkeypatch.setattr(mpp, "_ensure_lite_viewer_built", lambda: triggered.__setitem__("n", triggered["n"] + 1))
    # Stop after the build step so we don't materialize every real plugin.
    monkeypatch.setattr(mpp, "load_plugin_package_definitions", lambda: [])
    monkeypatch.setattr(mpp, "load_version", lambda: "0.0.0-test")

    mpp.materialize_plugin_packages(build_lite_viewer=True)
    assert triggered["n"] == 1

    mpp.materialize_plugin_packages(build_lite_viewer=False)
    assert triggered["n"] == 1  # not called again


def test_build_lite_viewer_ensure_built_skips_when_present(monkeypatch, tmp_path):
    import tools.build.build_lite_viewer as blv

    target = tmp_path / "AIPacsLiteViewer"
    target.mkdir()
    (target / blv.EXE_NAME).write_bytes(b"MZ")
    monkeypatch.setattr(blv, "TARGET_DIR", target)

    def must_not_build(_version):
        raise AssertionError("should not rebuild when present and force=False")

    monkeypatch.setattr(blv, "build_pyinstaller", must_not_build)
    assert blv.ensure_built(force=False) == 0


def test_build_lite_viewer_ensure_built_force_rebuilds(monkeypatch, tmp_path):
    import tools.build.build_lite_viewer as blv

    target = tmp_path / "AIPacsLiteViewer"
    target.mkdir()
    (target / blv.EXE_NAME).write_bytes(b"MZ")
    monkeypatch.setattr(blv, "TARGET_DIR", target)

    built = {"n": 0}
    monkeypatch.setattr(blv, "build_pyinstaller", lambda _v: built.__setitem__("n", 1) or 0)
    assert blv.ensure_built(force=True) == 0
    assert built["n"] == 1
