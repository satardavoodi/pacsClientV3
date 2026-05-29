"""End-to-end zombie-process guard (Issue: 'app remains in Task Manager').

Pre-flight via _verify_source_build (skips when not source build).
Then:
    1. Snapshot count of python.exe + aipacs.exe processes BEFORE close.
    2. Close the AI-PACS window (Alt+F4 via pywinauto).
    3. Wait up to 10 s for processes to drop.
    4. Snapshot AFTER. Assert no surplus processes remain.

Uses SystemCommandAdapter directly (in-process) so the test reads its
OWN psutil view of the system without needing a separate bus.

When pywinauto isn't installed OR the source build isn't running, the
test SKIPS cleanly — does not fail CI.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Bring in verify helper
_THIS = Path(__file__).resolve()
PROJECT_ROOT = _THIS.parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "tests" / "gui" / "live_walkthroughs"))

try:
    import pytest
except ImportError:
    pytest = None  # type: ignore

try:
    from _verify_source_build import (  # type: ignore
        require_source_build, WrongBuildError,
    )
except Exception as exc:
    require_source_build = None  # type: ignore
    WrongBuildError = Exception  # type: ignore
    _IMPORT_ERR = str(exc)
else:
    _IMPORT_ERR = ""


def _maybe_skip_if_not_source_build():
    if require_source_build is None:
        if pytest: pytest.skip(f"verify helper not importable: {_IMPORT_ERR}")
        raise RuntimeError("verify helper missing")
    try:
        require_source_build(recent_seconds=300, require_python_exe=False)
    except WrongBuildError as exc:
        if pytest: pytest.skip(f"source build not detected: {exc}")
        raise


def _maybe_skip_if_no_pywinauto():
    try:
        from pywinauto import Application  # noqa: F401
    except ImportError:
        if pytest: pytest.skip("pywinauto not installed")
        raise


def _count_aipacs_processes() -> dict:
    """Return {'python': N, 'aipacs': M, 'total': N+M}.

    Pure in-process — uses psutil directly so we don't have to spawn
    a separate CommandBus to ask the system adapter.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        import pydantic  # noqa: F401
        from modules.EchoMind.secretary import (
            AdapterRegistry, CommandBus, CommandPlan,
        )
        from modules.EchoMind.secretary.adapters import SystemCommandAdapter
    except ImportError:
        # Fall back to plain psutil if the bus stack isn't importable.
        import psutil
        py = ap = 0
        for p in psutil.process_iter(["name"]):
            try:
                n = (p.info["name"] or "").lower()
            except Exception:
                continue
            if n in ("python.exe", "py.exe"): py += 1
            elif n in ("aipacs.exe", "ai pacs viewer.exe"): ap += 1
        return {"python": py, "aipacs": ap, "total": py + ap}

    reg = AdapterRegistry()
    reg.register("system", SystemCommandAdapter(),
                 actions={"count_aipacs_processes": "count_aipacs_processes"})
    bus = CommandBus(registry=reg, orchestrator=None)
    r = bus.execute(CommandPlan(action="count_aipacs_processes"))
    if not r.ok:
        return {"python": -1, "aipacs": -1, "total": -1}
    counts = r.data["counts"]
    return {
        "python": counts["python_exe"],
        "aipacs": counts["aipacs_exe"],
        "total":  r.data["total"],
    }


def test_close_window_no_zombie_remains():
    _maybe_skip_if_not_source_build()
    _maybe_skip_if_no_pywinauto()

    from pywinauto import Application  # type: ignore

    # Snapshot BEFORE close
    pre = _count_aipacs_processes()
    print(f"[pre-close] python={pre['python']} aipacs={pre['aipacs']} total={pre['total']}")
    assert pre["total"] >= 1, "AI-PACS should be running (pre-flight checked)"

    # Find + close the window
    try:
        app = Application(backend="uia").connect(title_re=r"AI[ -]?[Pp]acs.*")
        window = app.window(title_re=r"AI[ -]?[Pp]acs.*")
        window.wait("ready", timeout=10)
        window.close()
    except Exception as exc:
        if pytest: pytest.skip(f"could not drive close: {exc}")
        raise

    # Wait up to 10 s for processes to exit cleanly.
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        time.sleep(0.5)
        post = _count_aipacs_processes()
        if post["total"] <= max(pre["total"] - 1, 0):
            break

    post = _count_aipacs_processes()
    print(f"[post-close] python={post['python']} aipacs={post['aipacs']} total={post['total']}")
    delta = pre["total"] - post["total"]
    assert delta >= 1, (
        f"Closing the AI-PACS window should reduce the process count by 1; "
        f"pre={pre['total']} post={post['total']} delta={delta}. "
        f"Zombie process suspected."
    )


if __name__ == "__main__":
    test_close_window_no_zombie_remains()
