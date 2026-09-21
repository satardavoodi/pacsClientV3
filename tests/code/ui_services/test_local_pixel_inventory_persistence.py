"""Local-only synthetic guards for reusable, version-checked pixel facts."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import json
import os
import subprocess
import sys
from time import perf_counter, sleep

import pytest

from PacsClient.utils import dicom_displayability as inventory
from tests.code.ui_services.test_local_pixel_inventory_reuse import make_dicom, count_reads


@pytest.fixture
def local_store(monkeypatch, tmp_path):
    from PacsClient.utils import data_paths
    monkeypatch.setattr(data_paths, "DICOM_IMAGES_DIR", tmp_path / "dicom")
    monkeypatch.setattr(data_paths, "THUMBNAILS_DIR", tmp_path / "thumbnails")
    monkeypatch.setattr(data_paths, "CACHE_DIR", tmp_path / "cache")
    inventory._pixel_facts_cache.clear()
    yield tmp_path
    inventory._pixel_facts_cache.clear()


def test_reopen_after_memory_retirement_uses_verified_counts(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 210)
    make_dicom(root / "b.dcm", 214)
    calls = count_reads(monkeypatch)
    first = inventory.inspect_series_pixel_inventory(root)
    inventory._pixel_facts_cache.clear()  # same condition as a fresh process
    second = inventory.inspect_series_pixel_inventory(root)
    assert first == second == inventory.SeriesPixelInventory(2, 2, 424)
    assert len(calls) == 2, "Reopening unchanged Local data must not reparse every DICOM"


def test_only_changed_files_are_reprobed_after_memory_retirement(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 2)
    make_dicom(root / "b.dcm", 7)
    calls = count_reads(monkeypatch)
    inventory.inspect_series_pixel_inventory(root)
    inventory._pixel_facts_cache.clear()
    make_dicom(root / "b.dcm", 420)
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 422
    assert [p.name for p in calls] == ["a.dcm", "b.dcm", "b.dcm"]


def test_persisted_facts_are_not_shared_by_storage_number(monkeypatch, local_store):
    calls = count_reads(monkeypatch)
    roots = [local_store / "dicom" / study / folder
             for study, folder in (("study-a", "1"), ("study-a", "1__collision"), ("study-b", "1"))]
    for root, frames in zip(roots, (25, 420, 7)):
        make_dicom(root / "a.dcm", frames)
        inventory.inspect_series_pixel_inventory(root)
    inventory._pixel_facts_cache.clear()
    assert [inventory.inspect_series_pixel_inventory(root).frame_count for root in roots] == [25, 420, 7]
    assert len(calls) == 3


def test_persisted_artifact_has_no_raw_path_or_dicom_identity(local_store):
    root = local_store / "dicom" / "synthetic-private-study" / "1"
    source = make_dicom(root / "synthetic-private-instance.dcm", 420)
    before = source.read_bytes()
    inventory.inspect_series_pixel_inventory(root)
    artifacts = list((local_store / "cache").rglob("*.json"))
    assert len(artifacts) == 1, "Facts must survive process restart in the managed cache tree"
    payload = artifacts[0].read_text(encoding="utf-8")
    assert "synthetic-private" not in payload and "Synthetic" not in payload
    assert str(local_store) not in payload
    assert source.read_bytes() == before
    assert list(root.iterdir()) == [source], "Never write cache metadata into source DICOM folders"
    assert json.loads(payload)


def test_facts_never_create_a_thumbnail_presence_signal(local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 420)
    inventory.inspect_series_pixel_inventory(root)
    # Existing legacy consumers use folder existence as a thumbnail hint. A
    # metadata-only optimization must not turn that hint true without a PNG.
    assert not (local_store / "thumbnails" / "study-a").exists()


def artifact(local_store):
    return next((local_store / "cache").rglob("*.json"))


def rewrite(path, update, *, checksum=True):
    value = json.loads(path.read_bytes())
    update(value)
    if checksum:
        data = json.dumps(value["records"], separators=(",", ":"), sort_keys=True).encode()
        value["digest"] = hashlib.sha256(data).hexdigest()
    path.write_text(json.dumps(value), encoding="utf-8")


def test_new_process_reuses_only_managed_verified_facts(local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 420)
    inventory.inspect_series_pixel_inventory(root)
    script = """
import sys
from pathlib import Path
from PacsClient.utils import data_paths, dicom_displayability as inv
data_paths.DICOM_IMAGES_DIR = Path(sys.argv[1]) / 'dicom'
data_paths.THUMBNAILS_DIR = Path(sys.argv[1]) / 'thumbnails'
data_paths.CACHE_DIR = Path(sys.argv[1]) / 'cache'
def unexpected(path):
    raise AssertionError('Unchanged file was reprobed in a fresh process')
inv.dicom_file_pixel_facts = unexpected
assert inv.inspect_series_pixel_inventory(Path(sys.argv[2])) == inv.SeriesPixelInventory(1, 1, 420)
"""
    result = subprocess.run([sys.executable, "-c", script, str(local_store), str(root)],
                            capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr


def test_added_removed_and_same_size_replacement(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    first = make_dicom(root / "a.dcm", 2)
    make_dicom(root / "b.dcm", 7)
    calls = count_reads(monkeypatch)
    inventory.inspect_series_pixel_inventory(root)
    inventory._pixel_facts_cache.clear()
    stamp = first.stat()
    # New inode/file ID, same length and mtime: replacement must still miss.
    replacement = make_dicom(root / "new.part", 8)
    assert replacement.stat().st_size == stamp.st_size
    os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    os.replace(replacement, first)
    (root / "b.dcm").unlink()
    make_dicom(root / "c.dcm", 420)
    assert inventory.inspect_series_pixel_inventory(root) == inventory.SeriesPixelInventory(2, 2, 428)
    assert [p.name for p in calls] == ["a.dcm", "b.dcm", "a.dcm", "c.dcm"]
    assert len(json.loads(artifact(local_store).read_bytes())["records"]) == 2


def test_negative_and_transient_failure_results_are_never_persisted(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 2)
    make_dicom(root / "document.dcm", pixel_tag=None)
    make_dicom(root / "unreadable.dcm", 8)
    original = inventory.dicom_file_pixel_facts
    calls = []
    def probe(path):
        calls.append(path.name)
        if path.name == "unreadable.dcm" and calls.count(path.name) == 1:
            return False, 0
        return original(path)
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", probe)
    assert inventory.inspect_series_pixel_inventory(root) == inventory.SeriesPixelInventory(3, 1, 2)
    assert len(json.loads(artifact(local_store).read_bytes())["records"]) == 1
    inventory._pixel_facts_cache.clear()
    assert inventory.inspect_series_pixel_inventory(root) == inventory.SeriesPixelInventory(3, 2, 10)
    assert calls == ["a.dcm", "document.dcm", "unreadable.dcm", "document.dcm", "unreadable.dcm"]


def test_mutation_during_probe_not_persisted(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 2)
    original = inventory.dicom_file_pixel_facts
    mutated = False
    def probe(path):
        nonlocal mutated
        result = original(path)
        if not mutated:
            mutated = True
            make_dicom(path, 420)
        return result
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", probe)
    inventory.inspect_series_pixel_inventory(root)
    assert not list(local_store.rglob("*.json"))
    inventory._pixel_facts_cache.clear()
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 420


def test_stat_failure_evicts_positive_persisted_record(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 420)
    inventory.inspect_series_pixel_inventory(root)
    original = inventory._pixel_file_version
    def denied(path):
        raise PermissionError("synthetic")
    monkeypatch.setattr(inventory, "_pixel_file_version", denied)
    assert not inventory.inspect_series_pixel_inventory(root).has_pixel_data
    assert not json.loads(artifact(local_store).read_bytes())["records"]
    monkeypatch.setattr(inventory, "_pixel_file_version", original)
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 420


@pytest.mark.parametrize("defect", ["truncated", "schema", "root", "digest", "frames", "version", "future", "expired", "oversized", "nested"])
def test_bad_cache_falls_back_without_hiding_data(monkeypatch, local_store, defect):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 420)
    inventory.inspect_series_pixel_inventory(root)
    target = artifact(local_store)
    if defect == "truncated":
        target.write_bytes(b'{"schema":')
    elif defect == "nested":
        target.write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
    elif defect == "oversized":
        target.write_bytes(b" " * (inventory._PIXEL_FACTS_DISK_MAX_BYTES + 1))
    else:
        def change(payload):
            record = next(iter(payload["records"].values()))
            if defect == "schema":
                payload["schema"] = 900
            elif defect == "root":
                payload["root"] = "0" * 64
            elif defect in ("frames", "digest"):
                record[1] = -1 if defect == "frames" else 421
            elif defect == "version":
                record[0] = [True] * 5
            elif defect == "future":
                record[2] = inventory.time() + 1000
            elif defect == "expired":
                record[2] = inventory.time() - inventory._PIXEL_FACTS_DISK_TTL - 1
        rewrite(target, change, checksum=defect != "digest")
    inventory._pixel_facts_cache.clear()
    calls = count_reads(monkeypatch)
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 420
    assert len(calls) == 1


def test_warm_use_does_not_extend_verification_age_or_rewrite(monkeypatch, local_store):
    now = [1000000.0]
    monkeypatch.setattr(inventory, "time", lambda: now[0])
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 7)
    calls = count_reads(monkeypatch)
    inventory.inspect_series_pixel_inventory(root)
    target = artifact(local_store)
    data, stamp = target.read_bytes(), target.stat().st_mtime_ns
    for offset in (1, 1000, inventory._PIXEL_FACTS_DISK_TTL - 1):
        now[0] = 1000000.0 + offset
        inventory._pixel_facts_cache.clear()
        assert inventory.inspect_series_pixel_inventory(root).frame_count == 7
        assert target.read_bytes() == data and target.stat().st_mtime_ns == stamp
    now[0] += 2
    inventory._pixel_facts_cache.clear()
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 7
    assert len(calls) == 2


@pytest.mark.parametrize("failure", ["read", "write", "replace"])
def test_cache_io_failure_does_not_fail_inventory(monkeypatch, local_store, failure):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 7)
    inventory.inspect_series_pixel_inventory(root)
    target = artifact(local_store)
    original_bytes = target.read_bytes()
    if failure == "replace":
        monkeypatch.setattr(inventory.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("synthetic")))
    else:
        original = Path.open
        def guarded(path, mode="r", *args, **kwargs):
            if path.suffix == ".json" and failure == "read":
                raise PermissionError("synthetic")
            return original(path, mode, *args, **kwargs)
        monkeypatch.setattr(Path, "open", guarded)
        if failure == "write":
            monkeypatch.setattr(inventory.tempfile, "NamedTemporaryFile", lambda **kw: (_ for _ in ()).throw(PermissionError("synthetic")))
    make_dicom(root / "a.dcm", 420)
    inventory._pixel_facts_cache.clear()
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 420
    assert not list(local_store.rglob("*.tmp"))
    if failure in ("write", "replace"):
        assert target.read_bytes() == original_bytes


def test_public_probe_and_external_media_remain_uncached(monkeypatch, local_store):
    managed = local_store / "dicom" / "study-a" / "1"
    make_dicom(managed / "a.dcm", 420)
    inventory.inspect_series_pixel_inventory(managed)
    external = local_store / "external"
    make_dicom(external / "a.dcm", 7)
    calls = count_reads(monkeypatch)
    assert inventory.dicom_file_pixel_facts(managed / "a.dcm") == (True, 420)
    inventory.inspect_series_pixel_inventory(external)
    inventory._pixel_facts_cache.clear()
    inventory.inspect_series_pixel_inventory(external)
    assert len(calls) == 3
    assert len(list(local_store.rglob("*.json"))) == 1


def test_profile_relocation_does_not_reuse_another_source(monkeypatch, local_store):
    from PacsClient.utils import data_paths
    first = local_store / "dicom" / "study-a" / "1"
    second = local_store / "other-profile" / "study-a" / "1"
    make_dicom(first / "a.dcm", 420)
    inventory.inspect_series_pixel_inventory(first)
    make_dicom(second / "a.dcm", 25)
    monkeypatch.setattr(data_paths, "DICOM_IMAGES_DIR", local_store / "other-profile")
    calls = count_reads(monkeypatch)
    assert inventory.inspect_series_pixel_inventory(second).frame_count == 25
    assert len(calls) == 1


def test_concurrent_inventory_writes_are_atomic_and_reusable(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    for index in range(8):
        make_dicom(root / f"{index}.dcm", index + 1)
    calls = count_reads(monkeypatch)
    barrier = Barrier(4)
    def scan():
        barrier.wait(5)
        return inventory.inspect_series_pixel_inventory(root)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(lambda _: scan(), range(4))) == [inventory.SeriesPixelInventory(8, 8, 36)] * 4
    assert len(calls) == 8
    inventory._pixel_facts_cache.clear()
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 36
    assert len(calls) == 8
    assert not list(local_store.rglob("*.tmp"))


def test_manifest_file_count_and_size_are_bounded(monkeypatch, local_store):
    root = local_store / "dicom" / "study-a" / "1"
    for index in range(3):
        make_dicom(root / f"{index}.dcm", 2)
    monkeypatch.setattr(inventory, "_PIXEL_FACTS_DISK_MAX_FILES", 2)
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 6
    assert not list(local_store.rglob("*.json"))
    monkeypatch.setattr(inventory, "_PIXEL_FACTS_DISK_MAX_FILES", 8192)
    monkeypatch.setattr(inventory, "_PIXEL_FACTS_DISK_MAX_BYTES", 10)
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 6
    assert not list(local_store.rglob("*.json"))


def test_persisted_inventory_receipt(monkeypatch, local_store, caplog):
    root = local_store / "dicom" / "study-a" / "1"
    for index in range(64):
        make_dicom(root / f"{index}.dcm", 1)
    original = inventory.dicom_file_pixel_facts
    def slow(path):
        sleep(0.002)  # controlled I/O latency, not a clinical performance claim
        return original(path)
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", slow)
    with caplog.at_level("INFO", logger=inventory.__name__):
        begin = perf_counter()
        first = inventory.inspect_series_pixel_inventory(root)
        cold_ms = (perf_counter() - begin) * 1000
        inventory._pixel_facts_cache.clear()
        begin = perf_counter()
        second = inventory.inspect_series_pixel_inventory(root)
        reused_ms = (perf_counter() - begin) * 1000
    assert first == second == inventory.SeriesPixelInventory(64, 64, 64)
    assert "disk_hits=64" in caplog.messages[-1] and "probes=0" in caplog.messages[-1]
    assert all("study-a" not in line and "a.dcm" not in line for line in caplog.messages)
    print(f"SYNTHETIC_INVENTORY cold_ms={cold_ms:.2f} reused_ms={reused_ms:.2f} files=64")


@pytest.mark.parametrize("budget", ["count", "bytes"])
def test_cache_eviction_bounds_metadata_not_source_files(monkeypatch, local_store, budget):
    monkeypatch.setattr(inventory, "_PIXEL_FACTS_DISK_MAX_ENTRIES", 2)
    roots = [local_store / "dicom" / f"study-{i}" / "1" for i in range(3)]
    sources = [make_dicom(root / "a.dcm", 420) for root in roots]
    originals = [source.read_bytes() for source in sources]
    inventory.inspect_series_pixel_inventory(roots[0])
    if budget == "bytes":
        monkeypatch.setattr(inventory, "_PIXEL_FACTS_DISK_BUDGET", artifact(local_store).stat().st_size * 2 + 10)
        monkeypatch.setattr(inventory, "_PIXEL_FACTS_DISK_MAX_ENTRIES", 256)
    inventory.inspect_series_pixel_inventory(roots[1])
    inventory.inspect_series_pixel_inventory(roots[2])
    artifacts = list((local_store / "cache").rglob("*.json"))
    assert len(artifacts) <= 2
    assert sum(path.stat().st_size for path in artifacts) <= inventory._PIXEL_FACTS_DISK_BUDGET
    assert [source.read_bytes() for source in sources] == originals
    inventory._pixel_facts_cache.clear()
    assert inventory.inspect_series_pixel_inventory(roots[0]).frame_count == 420


def test_busy_cache_writer_does_not_block_a_reader(local_store):
    root = local_store / "dicom" / "study-a" / "1"
    make_dicom(root / "a.dcm", 420)
    with inventory._pixel_facts_disk_write_lock:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(inventory.inspect_series_pixel_inventory, root).result(timeout=2)
    assert result.frame_count == 420
    assert not list(local_store.rglob("*.json"))
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 420
    assert len(list(local_store.rglob("*.json"))) == 1
