"""Behavioural tests for modules.storage.content_version_store.

The store persists the per-study server ``contentVersion`` at which the local copy
was last confirmed complete. It must: round-trip get/set, persist atomically,
fail open (return None / start empty) on a corrupt or unwritable file, and clear a
single study or all studies. The path is monkeypatched to a temp file so the live
``user_data`` store is never touched.
"""
import importlib
from pathlib import Path

import pytest

cvs = importlib.import_module("modules.storage.content_version_store")


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """Point the store at a temp file and reset its in-memory cache."""
    p = tmp_path / "content_versions.json"
    monkeypatch.setattr(cvs, "_store_path", lambda: p, raising=True)
    cvs._reset_cache_for_tests()
    yield cvs, p
    cvs._reset_cache_for_tests()


def test_get_unknown_returns_none(store):
    mod, _ = store
    assert mod.get_synced_version("1.2.3") is None


def test_set_then_get_roundtrip(store):
    mod, _ = store
    mod.set_synced_version("1.2.3", 7)
    assert mod.get_synced_version("1.2.3") == 7


def test_set_persists_to_disk_atomically(store):
    mod, p = store
    mod.set_synced_version("study-A", 4)
    assert p.exists(), "store file should be written"
    # No leftover *.part temp file after an atomic replace.
    assert not p.with_name(p.name + ".part").exists()
    # A fresh process (cache reset) reads the persisted value.
    mod._reset_cache_for_tests()
    assert mod.get_synced_version("study-A") == 4


def test_set_accepts_stringy_int(store):
    mod, _ = store
    mod.set_synced_version("s", "12")
    assert mod.get_synced_version("s") == 12


def test_set_none_or_garbage_is_noop(store):
    mod, _ = store
    mod.set_synced_version("s", None)
    mod.set_synced_version("s", "not-a-number")
    mod.set_synced_version("", 5)
    assert mod.get_synced_version("s") is None


def test_clear_single_study(store):
    mod, _ = store
    mod.set_synced_version("a", 1)
    mod.set_synced_version("b", 2)
    mod.clear("a")
    assert mod.get_synced_version("a") is None
    assert mod.get_synced_version("b") == 2


def test_clear_all(store):
    mod, _ = store
    mod.set_synced_version("a", 1)
    mod.set_synced_version("b", 2)
    mod.clear(None)
    assert mod.get_synced_version("a") is None
    assert mod.get_synced_version("b") is None


def test_clear_after_set_makes_study_resync_again(store):
    """The clear-on-delete contract: a cleared study reports unknown so the resync
    can no longer cheap-skip it."""
    mod, _ = store
    mod.set_synced_version("cleared", 9)
    assert mod.get_synced_version("cleared") == 9
    mod.clear("cleared")
    # Persisted clear survives a cache reset (simulates next session).
    mod._reset_cache_for_tests()
    assert mod.get_synced_version("cleared") is None


def test_corrupt_file_fails_open(store):
    mod, p = store
    p.write_text("{ this is not json", encoding="utf-8")
    mod._reset_cache_for_tests()
    # Corrupt store => empty (None), never raises.
    assert mod.get_synced_version("anything") is None
    # And a subsequent set still works (overwrites the corrupt file).
    mod.set_synced_version("x", 3)
    assert mod.get_synced_version("x") == 3


def test_unwritable_path_does_not_raise(tmp_path, monkeypatch):
    """A persist failure must be swallowed (best-effort) — the in-memory value is
    still served for the session."""
    bad = tmp_path / "nonexistent_dir" / "sub" / "cv.json"

    def _boom_persist(cache):
        raise OSError("disk full")

    monkeypatch.setattr(cvs, "_store_path", lambda: bad, raising=True)
    monkeypatch.setattr(cvs, "_persist", _boom_persist, raising=True)
    cvs._reset_cache_for_tests()
    # Should not raise despite the persist blowing up.
    cvs.set_synced_version("s", 5)
    assert cvs.get_synced_version("s") == 5
    cvs._reset_cache_for_tests()


def test_idempotent_set_same_value(store):
    """Setting the same value twice is a no-op (no spurious rewrite churn)."""
    mod, p = store
    mod.set_synced_version("s", 5)
    mtime1 = p.stat().st_mtime_ns
    mod.set_synced_version("s", 5)  # same value
    mtime2 = p.stat().st_mtime_ns
    assert mtime1 == mtime2, "unchanged value should not rewrite the file"
