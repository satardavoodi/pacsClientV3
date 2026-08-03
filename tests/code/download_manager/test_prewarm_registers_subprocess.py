"""Prewarm spare must be registered for shutdown termination (2026-08-01).

The download-manager prewarm pool spawns an idle spare subprocess to hide the
~2.3 s Windows ``spawn`` bootstrap. The real download worker registers a spare's
PID (via ``register_download_subprocess``) only when it ADOPTS one for a download
— so an idle spare that was never used was never registered, and
``terminate_all_download_subprocesses()`` on app shutdown could not kill it. It
leaked as an orphaned ``python.exe`` (observed: 5 orphaned ``--multiprocessing-
fork`` children from past sessions still running).

Fix: ``ensure_warm`` registers the spare's PID right after ``proc.start()`` (and
drops a previous dead spare's PID). Source-pinned (spawning a real mp subprocess
in a unit test is undesirable); the register/unregister helpers themselves are
covered elsewhere. Also verifies the plugin mirror carries the fix.
"""
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _prewarm_src(root: Path) -> str:
    return (root / "modules" / "download_manager" / "workers" / "prewarm.py").read_text(encoding="utf-8")


def test_ensure_warm_registers_spare_after_start():
    src = _prewarm_src(_repo_root())
    fn = src[src.find("def ensure_warm("):]
    fn = fn[:fn.find("\n    def ", 10)]
    # registration happens, keyed on the spawned process pid
    assert "register_download_subprocess(proc.pid)" in fn
    # it must come AFTER the spare is actually started
    i_start = fn.find("proc.start()")
    i_reg = fn.find("register_download_subprocess(proc.pid)")
    assert -1 < i_start < i_reg, "must register the spare AFTER proc.start()"
    # a replaced (dead) spare's pid is dropped so the terminator set can't grow stale
    assert "unregister_download_subprocess(_old[\"process\"].pid)" in fn
    # never let a registration failure break the prewarm path
    assert "except Exception:" in fn


def test_plugin_mirror_carries_the_fix():
    root = _repo_root()
    mirror = (root / "builder" / "plugin package" / "packages" / "download_manager"
              / "payload" / "python" / "modules" / "download_manager" / "workers" / "prewarm.py")
    if not mirror.exists():
        # environments without the built plugin payload just skip this
        import pytest
        pytest.skip("plugin mirror payload not present")
    assert "register_download_subprocess(proc.pid)" in mirror.read_text(encoding="utf-8"), \
        "run tools/dev/sync_plugin_mirrors.py — the mirror is stale"
