"""Guard: seed the user config once per (src, dst), not once per caller (A0, 2026-08-23).

Five ``_config_root()`` helpers call ``seed_user_config_defaults()`` on EVERY
call -- ``server_profiles``, ``offline_cloud``, ``Identity/config``,
``cloud_consultation.feature_flags`` and ``aipacs_chat.feature_flags`` -- plus
three module-import call sites. So merely READING a feature flag re-scans the
roaming config directory: ``iterdir()`` plus a ``stat()`` per file.

The end-user log for the 2026-08-23 00:47 hang shows EIGHT ``[SEED_CONFIG]``
lines inside one second, during patient-tab teardown, on the GUI thread.

Seeding is create-if-missing and the roots cannot change inside a process, so
repeating it can never produce a different result -- only the same walk again.
The memo is keyed on the resolved ``(src, dst)`` pair rather than a bare bool so
tests seeding into different tmp dirs still exercise a real pass.

Kill switch ``AIPACS_SEED_CONFIG_ONCE=0`` restores seeding on every call.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import aipacs_runtime as runtime  # noqa: E402


def _make_src(tmp_path: Path, name: str = "bundled") -> Path:
    src = tmp_path / name
    src.mkdir(parents=True, exist_ok=True)
    (src / "servers.json").write_text(json.dumps({"servers": []}), encoding="utf-8")
    return src


@pytest.fixture()
def frozen(monkeypatch):
    """Pretend to be a frozen install with a clean seed memo."""
    monkeypatch.setattr(runtime, "is_frozen", lambda: True)
    monkeypatch.setattr(runtime, "_CONFIG_MIGRATION_RAN", True)  # isolate the top-level pass
    monkeypatch.delenv("AIPACS_SEED_CONFIG_ONCE", raising=False)
    runtime.reset_seed_memo_for_tests()
    yield
    runtime.reset_seed_memo_for_tests()


def _seed_lines(caplog) -> int:
    return sum(1 for r in caplog.records if "[SEED_CONFIG] dst=" in r.getMessage())


def _point_at(monkeypatch, src: Path, dst: Path) -> None:
    monkeypatch.setattr(runtime, "bundled_config_root", lambda: src)
    monkeypatch.setattr(runtime, "roaming_config_root", lambda: dst)


def test_repeat_calls_do_not_rescan(frozen, monkeypatch, tmp_path, caplog):
    src, dst = _make_src(tmp_path), tmp_path / "roaming"
    _point_at(monkeypatch, src, dst)
    caplog.set_level(logging.INFO)

    for _ in range(8):  # the eight the end-user log actually recorded
        runtime.seed_user_config_defaults()

    assert _seed_lines(caplog) == 1, "eight callers must produce one directory walk"
    assert (dst / "servers.json").exists(), "the one pass must still seed"


def test_memo_is_keyed_not_global(frozen, monkeypatch, tmp_path, caplog):
    """A different destination is a different question and must be answered."""
    src = _make_src(tmp_path)
    caplog.set_level(logging.INFO)

    _point_at(monkeypatch, src, tmp_path / "roaming_a")
    runtime.seed_user_config_defaults()
    _point_at(monkeypatch, src, tmp_path / "roaming_b")
    runtime.seed_user_config_defaults()

    assert _seed_lines(caplog) == 2
    assert (tmp_path / "roaming_a" / "servers.json").exists()
    assert (tmp_path / "roaming_b" / "servers.json").exists()


def test_kill_switch_restores_seeding_every_call(frozen, monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("AIPACS_SEED_CONFIG_ONCE", "0")
    src, dst = _make_src(tmp_path), tmp_path / "roaming"
    _point_at(monkeypatch, src, dst)
    caplog.set_level(logging.INFO)

    runtime.seed_user_config_defaults()
    runtime.seed_user_config_defaults()

    assert _seed_lines(caplog) == 2


def test_a_failed_pass_is_not_memoised(frozen, monkeypatch, tmp_path, caplog):
    """A missing bundled root is an install fault, not a settled answer -- if it
    appears later (module install completing) the next call must still seed."""
    src, dst = tmp_path / "not_there_yet", tmp_path / "roaming"
    _point_at(monkeypatch, src, dst)
    caplog.set_level(logging.INFO)

    runtime.seed_user_config_defaults()
    assert _seed_lines(caplog) == 0
    assert not dst.exists()

    src.mkdir(parents=True)
    (src / "servers.json").write_text("{}", encoding="utf-8")
    runtime.seed_user_config_defaults()

    assert _seed_lines(caplog) == 1
    assert (dst / "servers.json").exists()


def test_dev_runs_are_untouched(monkeypatch, tmp_path):
    """Not frozen -> early return, before the memo is even consulted."""
    monkeypatch.setattr(runtime, "is_frozen", lambda: False)
    runtime.reset_seed_memo_for_tests()
    runtime.seed_user_config_defaults()
    assert runtime._SEED_DONE == set()


def test_flag_default_on():
    monkeypatch_free = runtime.seed_config_once_enabled
    assert callable(monkeypatch_free)
    src = (ROOT / "aipacs_runtime.py").read_text(encoding="utf-8")
    assert 'os.getenv("AIPACS_SEED_CONFIG_ONCE", "1")' in src


@pytest.mark.parametrize("raw,expected", [
    ("0", False), ("false", False), ("OFF", False), ("no", False),
    ("1", True), ("yes", True), ("", True),
])
def test_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("AIPACS_SEED_CONFIG_ONCE", raw)
    assert runtime.seed_config_once_enabled() is expected
