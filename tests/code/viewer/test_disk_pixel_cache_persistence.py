"""Guards for the L2 disk pixel cache SURVIVING shutdown (2026-08-16).

Live evidence for the bug these pin:

    18 x "[B3.12] Disk pixel cache cleared"   (2026-08-08 .. 2026-08-16)
     2 x "[B3.12] Disk pixel cache indexed: 0 entries"

`MainWindowWidget._shutdown_caches()` called `get_disk_pixel_cache().clear()`
unconditionally, and `clear()` is a `shutil.rmtree`. So the "L2 PERSISTENT
cache for decoded DICOM pixel arrays" whose stated purpose is to "eliminate
the need to re-decode slices when reopening a previously-viewed series" was
wiped on every exit and had never once served a cross-session hit.

The fix is `clear_on_exit()`: keep by default, wipe only when the site sets
`AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT=1`.

What must stay true, and why each has a test here:

  * persistence is the DEFAULT                       -> the cache does its job
  * the kill switch really restores the wipe         -> PHI-at-rest is a site
                                                        policy choice
  * `clear()` itself stays UNCONDITIONAL             -> an explicit user
                                                        "clear cache" must
                                                        always clear
  * the shutdown path calls `clear_on_exit`, not
    `clear`                                          -> the wiring is the bug
  * the 2 GB cap + LRU still bound the cache, and
    the LRU order survives a restart                 -> with persistence on,
                                                        eviction is now the
                                                        ONLY thing bounding
                                                        disk growth
  * `clear_on_exit()` never raises                   -> it runs inside a
                                                        shutdown step
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import numpy as np
import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.viewer.fast import disk_pixel_cache as DPC          # noqa: E402
from modules.viewer.fast.disk_pixel_cache import DiskPixelCache  # noqa: E402

ENV = "AIPACS_PIXEL_CACHE_CLEAR_ON_EXIT"
STUDY = "study_persist"


def _seed(cache: DiskPixelCache, sops: list[str]) -> list[str]:
    """Write one real cache entry per sop; return their index keys in order."""
    keys = []
    for i, sop in enumerate(sops):
        cache.put(sop, STUDY, np.full((16, 16), i + 1, dtype=np.int16))
        keys.append(DPC._uid_hash(sop))
    cache._write_queue.join()
    return keys


def _apc_files(root: Path) -> list[Path]:
    return sorted((root / "cache" / "pixel_cache").rglob("*.apc"))


def _stamp_access_order(cache: DiskPixelCache, keys: list[str]) -> None:
    """Give the files strictly increasing mtimes.

    `_scan_index` uses `st_mtime` as the last-access proxy. On a fast NTFS
    write loop several files can land on the same mtime, which would make the
    restored LRU order arbitrary and this test flaky. Stamp them explicitly.
    """
    for i, key in enumerate(keys):
        path = cache._index[key][0]
        os.utime(path, (1_000_000 + i, 1_000_000 + i))


# ---------------------------------------------------------------------------
# 1. Persistence is the default
# ---------------------------------------------------------------------------
def test_cache_survives_shutdown_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()
    _seed(cache, ["sop_a", "sop_b", "sop_c"])
    assert len(_apc_files(tmp_path)) == 3

    cache.clear_on_exit()

    # files still on disk...
    assert len(_apc_files(tmp_path)) == 3
    # ...and the NEXT process actually picks them up. This is the whole point:
    # before the fix every startup scan reported "0 entries".
    nxt = DiskPixelCache(tmp_path, max_size_mb=64)
    nxt.initialize()
    assert nxt.stats()["entries"] == 3
    assert nxt.get("sop_b", STUDY) is not None


def test_surviving_entries_are_real_hits_not_just_files(tmp_path, monkeypatch):
    """A restored entry must round-trip the actual pixels, not a stub."""
    monkeypatch.delenv(ENV, raising=False)
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()
    payload = np.arange(256, dtype=np.int16).reshape(16, 16)
    cache.put("sop_round", STUDY, payload)
    cache._write_queue.join()
    cache.clear_on_exit()

    nxt = DiskPixelCache(tmp_path, max_size_mb=64)
    nxt.initialize()
    got = nxt.get("sop_round", STUDY)
    assert got is not None
    np.testing.assert_array_equal(got, payload)


# ---------------------------------------------------------------------------
# 2. The kill switch really restores the old behaviour
# ---------------------------------------------------------------------------
def test_kill_switch_restores_the_wipe(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, "1")
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()
    _seed(cache, ["sop_a", "sop_b"])
    assert len(_apc_files(tmp_path)) == 2

    cache.clear_on_exit()

    assert _apc_files(tmp_path) == []
    assert cache.stats()["entries"] == 0
    nxt = DiskPixelCache(tmp_path, max_size_mb=64)
    nxt.initialize()
    assert nxt.stats()["entries"] == 0


@pytest.mark.parametrize(
    "val,wipes",
    [
        ("1", True),
        (" 1 ", True),
        ("0", False),
        ("", False),
        ("true", False),
        ("TRUE", False),
        ("yes", False),
        ("on", False),
        ("2", False),
        ("01", False),
    ],
)
def test_only_a_literal_1_wipes(tmp_path, monkeypatch, val, wipes):
    """Same parsing rule as every other switch in this project.

    Deliberately strict: an ambiguous value must fall to the SAFE side, and
    for a cache the safe side is 'keep the data and stay fast'. A site that
    wants the wipe has to say so unambiguously.
    """
    monkeypatch.setenv(ENV, val)
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()
    _seed(cache, ["sop_a"])

    cache.clear_on_exit()

    assert (_apc_files(tmp_path) == []) is wipes


# ---------------------------------------------------------------------------
# 3. An EXPLICIT clear must always clear
# ---------------------------------------------------------------------------
def test_explicit_clear_is_unconditional(tmp_path, monkeypatch):
    """`clear()` must NOT learn about the env var.

    If someone later wires a "Clear cache" button to `clear()`, it has to
    work regardless of the shutdown policy. That is exactly why the policy
    lives in a separate `clear_on_exit()` method.
    """
    monkeypatch.delenv(ENV, raising=False)      # persistence ON
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()
    _seed(cache, ["sop_a", "sop_b"])

    cache.clear()                                # explicit

    assert _apc_files(tmp_path) == []
    assert cache.stats()["entries"] == 0


def test_clear_source_does_not_consult_the_env_var():
    """Structural companion to the test above: keep the seam clean."""
    src = Path(DPC.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    clear_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "clear"
    )
    assert ENV not in ast.unparse(clear_fn)


# ---------------------------------------------------------------------------
# 4. The shutdown path must call clear_on_exit, not clear
# ---------------------------------------------------------------------------
def test_shutdown_path_calls_clear_on_exit():
    """AST-based, so the explanatory comment at the call site (which names
    `.clear()` on purpose) cannot satisfy or break this pin."""
    mw = REPO_ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py"
    tree = ast.parse(mw.read_text(encoding="utf-8"))
    shutdown_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_shutdown_caches"
    )
    body = ast.unparse(shutdown_fn)             # comments are dropped by unparse
    assert "get_disk_pixel_cache().clear_on_exit()" in body
    assert "get_disk_pixel_cache().clear()" not in body


# ---------------------------------------------------------------------------
# 5. Persistence must stay BOUNDED — eviction is now the only limit
# ---------------------------------------------------------------------------
def test_persisted_cache_is_still_capped(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()
    keys = _seed(cache, ["sop_a", "sop_b", "sop_c"])
    entry = cache._index[keys[0]][1]            # real on-disk size incl. header

    cache._max_size_bytes = entry * 3           # room for exactly 3
    _seed(cache, ["sop_d", "sop_e"])            # two more -> two evictions

    assert cache.stats()["entries"] == 3
    assert cache._total_bytes <= cache._max_size_bytes
    assert len(_apc_files(tmp_path)) == 3       # evicted files really unlinked


def test_lru_order_survives_a_restart(tmp_path, monkeypatch):
    """The property that makes persistence safe.

    `_scan_index` restores the index sorted by mtime, and the OrderedDict's
    ORDER *is* the eviction order. If that sort were dropped, the entry the
    user touched most recently before closing would become the first one
    evicted in the next session — a cache that actively works against itself.
    """
    monkeypatch.delenv(ENV, raising=False)
    seed = DiskPixelCache(tmp_path, max_size_mb=64)
    seed.initialize()
    keys = _seed(seed, ["sop_a", "sop_b", "sop_c"])
    _stamp_access_order(seed, keys)             # a oldest ... c newest
    seed.clear_on_exit()

    nxt = DiskPixelCache(tmp_path, max_size_mb=64)
    nxt.initialize()
    assert list(nxt._index.keys()) == keys      # oldest-first restored

    # touch A: it becomes the most-recently-used and must move to the back
    assert nxt.get("sop_a", STUDY) is not None
    assert list(nxt._index.keys()) == [keys[1], keys[2], keys[0]]

    # now force exactly one eviction; it must be B, not the just-read A
    entry = nxt._index[keys[1]][1]
    nxt._max_size_bytes = entry * 3
    _seed(nxt, ["sop_d"])

    surviving = set(nxt._index.keys())
    assert keys[1] not in surviving             # B evicted (oldest)
    assert keys[0] in surviving                 # A kept (just read)
    assert keys[2] in surviving


# ---------------------------------------------------------------------------
# 6. It runs inside a shutdown step — it must never raise
# ---------------------------------------------------------------------------
def test_clear_on_exit_never_raises(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()

    class _Exploding(dict):
        def __len__(self):                       # bookkeeping for the log line
            raise RuntimeError("boom")

    cache._index = _Exploding()
    cache.clear_on_exit()                        # must not propagate


def test_clear_on_exit_logs_what_it_kept(tmp_path, monkeypatch, caplog):
    """The next live run has to be verifiable from app.log alone — that is how
    every other change in this series was confirmed."""
    monkeypatch.delenv(ENV, raising=False)
    cache = DiskPixelCache(tmp_path, max_size_mb=64)
    cache.initialize()
    _seed(cache, ["sop_a", "sop_b"])

    with caplog.at_level("INFO", logger=DPC.logger.name):
        cache.clear_on_exit()

    assert any("kept across shutdown" in r.message for r in caplog.records)
