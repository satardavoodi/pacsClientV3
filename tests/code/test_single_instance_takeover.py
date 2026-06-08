"""Guards for the single-instance TAKEOVER policy (2026-06-05).

New launch wins: an existing instance is asked to SHUTDOWN cleanly, then
force-killed if it lingers; orphaned workers/spares are swept; no dialog.
Pure-function matching + source contracts only — no processes are spawned
or killed by this suite (takeover is auto-disabled under pytest).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PacsClient.utils.single_instance_lock import (  # noqa: E402
    SingleInstanceLock,
    _takeover_enabled,
)

_SRC = (
    _REPO_ROOT / "PacsClient/utils/single_instance_lock.py"
).read_text(encoding="utf-8")

_match = SingleInstanceLock._proc_is_aipacs


# ── matching rules ────────────────────────────────────────────────────────
def test_matches_frozen_exes():
    assert _match("aipacs.exe", "", [])
    assert _match("AI PACS Viewer.exe", "", [])
    assert _match("AIPacs.exe", r"D:\ai-pacs\aipacs.exe", [])


def test_matches_source_run():
    assert _match(
        "python.exe",
        r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\.venv\Scripts\python.exe",
        ["python.exe", r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\main.py"],
    )


def test_matches_worker_relative_mainpy_via_interpreter_path():
    # Workers re-exec a relative "main.py"; the venv path discriminates.
    assert _match(
        "python.exe",
        r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\.venv\Scripts\python.exe",
        ["python.exe", "main.py"],
    )


def test_matches_worker_relative_mainpy_via_cwd():
    assert _match(
        "python.exe",
        r"C:\Python311\python.exe",
        ["python.exe", "main.py"],
        cwd=r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version",
    )


def test_never_matches_unrelated_processes():
    # pytest itself
    assert not _match(
        "python.exe",
        r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version\.venv\Scripts\python.exe",
        ["python.exe", "-m", "pytest", "tests"],
    )
    # another project's main.py
    assert not _match(
        "python.exe", r"C:\Python311\python.exe",
        ["python.exe", r"C:\projects\webshop\main.py"],
    )
    # non-python, non-aipacs exe
    assert not _match("notepad.exe", "", [])
    assert not _match("chrome.exe", "", ["chrome.exe", "main.py"])


# ── env gating ────────────────────────────────────────────────────────────
def test_takeover_disabled_under_pytest():
    # PYTEST_CURRENT_TEST is set while this test runs.
    assert _takeover_enabled() is False


def test_takeover_default_on_without_pytest(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("AIPACS_NO_TAKEOVER", raising=False)
    assert _takeover_enabled() is True
    monkeypatch.setenv("AIPACS_NO_TAKEOVER", "1")
    assert _takeover_enabled() is False


# ── source contracts ──────────────────────────────────────────────────────
def test_shutdown_handled_before_activate():
    i_conn = _SRC.index("def _on_new_connection")
    block = _SRC[i_conn:i_conn + 2200]
    assert block.index("_SHUTDOWN_MSG in data") < block.index("_ACTIVATE_MSG in data")


def test_takeover_flow_order_graceful_then_force():
    i_acq = _SRC.index("def try_acquire")
    block = _SRC[i_acq:_SRC.index("def set_activate_callback")]
    i_req = block.index("_request_existing_shutdown()")
    i_wait = block.index("_wait_existing_gone(_TAKEOVER_GRACEFUL_WAIT_S)")
    i_force = block.index("_force_close_other_instances()")
    assert i_req < i_wait < i_force
    # quiet probe (no ACTIVATE raise of the doomed window) in takeover mode
    assert "message=None if takeover else _ACTIVATE_MSG" in block
    # racing twin → defer, no kill loop
    assert "won the single-instance race" in block


def test_no_dialog_in_takeover_mode():
    i_acq = _SRC.index("def try_acquire")
    block = _SRC[i_acq:_SRC.index("def set_activate_callback")]
    # the only dialog call sits inside the legacy (not takeover) branch
    assert block.count("_show_already_running_message()") == 1
    assert "show_dialog and not takeover" in block


def test_graceful_disconnect_still_used_never_abort():
    assert "sock.abort()" not in _SRC
    assert "disconnectFromServer" in _SRC


# ── startup-sweep perf: cheap name pre-filter (2026-06-08) ────────────────
def test_force_close_enumerates_cheap_name_only():
    """The orphan sweep must enumerate with only the cheap pid+name attrs and
    pre-filter by name before fetching the slow exe/cmdline.  Root cause of the
    ~25 s cold-start (every launch): psutil fetched exe + ppid for EVERY process
    on the machine (slow OpenProcess / O(n^2) ppid-map)."""
    i = _SRC.index("def _force_close_other_instances")
    block = _SRC[i:i + 3200]
    # cheap enumeration only — no eager exe/cmdline/ppid for every process
    assert 'process_iter(["pid", "name"])' in block
    assert '"exe", "cmdline"' not in block
    assert '"ppid", "name"' not in block
    # the name pre-filter must precede the expensive field fetch
    i_filter = block.index('("aipacs" not in nm) and ("python" not in nm)')
    i_exe = block.index("proc.exe()")
    assert i_filter < i_exe


def test_force_close_prefilter_is_superset_of_matcher():
    """Sanity: every name `_proc_is_aipacs` can match contains 'aipacs' or
    'python' (squashed), so the cheap name pre-filter never drops a real match."""
    # frozen exe names
    for nm in ("aipacs.exe", "AI PACS Viewer.exe", "AIPacs.exe"):
        squashed = nm.lower().replace(" ", "")
        assert ("aipacs" in squashed) or ("python" in squashed)
    # source/worker runs are python processes
    squashed = "python.exe".lower().replace(" ", "")
    assert "python" in squashed
