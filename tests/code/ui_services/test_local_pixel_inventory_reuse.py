"""Synthetic read-only inventory guards; no clinical database or Qt runtime."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock
import os
import time

import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    ExplicitVRLittleEndian, ImplicitVRLittleEndian, ExplicitVRBigEndian,
    DeflatedExplicitVRLittleEndian, JPEGBaseline8Bit,
    SecondaryCaptureImageStorage, generate_uid,
)

from PacsClient.utils import dicom_displayability as inventory


@pytest.fixture(autouse=True)
def isolated_cache():
    cache = getattr(inventory, "_pixel_facts_cache", {})
    cache.clear()
    yield
    cache.clear()


def make_dicom(path, frames=1, *, pixel_tag=0x7FE00010,
               syntax=ExplicitVRLittleEndian):
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = syntax
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.is_little_endian = syntax != ExplicitVRBigEndian
    ds.is_implicit_VR = syntax == ImplicitVRLittleEndian
    ds.PatientName = "Synthetic^Inventory"
    ds.NumberOfFrames = frames
    ds.add_new(0x00111010, "OB", b"x" * 10000)
    if pixel_tag:
        if syntax == JPEGBaseline8Bit:
            from pydicom.encaps import encapsulate
            ds.PixelData = encapsulate([b"synthetic-not-a-real-jpeg"])
            ds[0x7FE00010].is_undefined_length = True
        else:
            vr = {0x7FE00010: "OB", 0x7FE00008: "OF", 0x7FE00009: "OD"}[pixel_tag]
            ds.add_new(pixel_tag, vr, b"\0" * 16000)
    ds.save_as(str(path), write_like_original=False)
    return path


def count_reads(monkeypatch):
    calls = []
    original = inventory.dicom_file_pixel_facts
    def read(path):
        calls.append(Path(path))
        return original(path)
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", read)
    return calls


def test_two_local_consumers_reuse_positive_facts(monkeypatch, tmp_path):
    make_dicom(tmp_path / "a.dcm", 210)
    make_dicom(tmp_path / "b.dcm", 214)
    calls = count_reads(monkeypatch)
    first = inventory.inspect_series_pixel_inventory(tmp_path)
    second = inventory.inspect_series_pixel_inventory(tmp_path)
    assert first == second == inventory.SeriesPixelInventory(2, 2, 424)
    assert len(calls) == 2


def test_file_warm_prime_is_reused_by_inventory_without_second_header_read(
        monkeypatch, tmp_path):
    path = make_dicom(tmp_path / "a.dcm", 210)
    calls = count_reads(monkeypatch)

    assert inventory.prime_dicom_pixel_fact(path) == (True, 210)
    assert inventory.inspect_series_pixel_inventory(tmp_path) == (
        inventory.SeriesPixelInventory(1, 1, 210)
    )
    assert calls == [path]


def test_bounded_fact_warmer_and_inventory_share_one_header_read_per_file(
        monkeypatch, tmp_path):
    from PacsClient.pacs.patient_tab.utils import series_file_warm

    series = tmp_path / "study" / "1"
    paths = [make_dicom(series / f"{index}.dcm", index + 1)
             for index in range(8)]
    calls = count_reads(monkeypatch)

    stats = series_file_warm._warm_paths(
        [str(series.parent)], chunk_bytes=256 * 1024, max_files=100,
        max_seconds=10.0, workers=4,
        pixel_fact_series_paths=[str(series)],
    )
    result = inventory.inspect_series_pixel_inventory(series)

    assert stats["files"] == stats["fact_files"] == len(paths)
    assert result == inventory.SeriesPixelInventory(8, 8, sum(range(1, 9)))
    assert sorted(calls) == sorted(paths)


def test_ordered_catalog_inventory_parallelizes_files_and_yields_series_in_order(
        monkeypatch, tmp_path):
    """One Local owner uses a bounded file pool without reordering series."""
    first = tmp_path / "study" / "1"
    second = tmp_path / "study" / "2"
    for folder, frames in ((first, 2), (second, 3)):
        for index in range(6):
            make_dicom(folder / f"{index}.dcm", frames)
    make_dicom(first / "non-pixel.dcm", pixel_tag=0)

    original = inventory.dicom_file_pixel_facts
    lock = Lock()
    active = 0
    maximum = 0
    probed_parents = []

    def observed(path):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            probed_parents.append(Path(path).parent)
        try:
            time.sleep(.015)
            return original(path)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", observed)
    rows = [
        {"series_uid": "first", "series_path": str(first)},
        {"series_uid": "second", "series_path": str(second)},
    ]

    stream = inventory.resolve_series_pixel_inventories(rows, workers=4)
    first_result = next(stream)
    assert first_result[0]["series_uid"] == "first"
    assert first_result[1].instance_count == 7
    assert first_result[1].pixel_instance_count == 6
    assert first_result[1].frame_count == 12
    assert set(probed_parents) == {first}
    resolved = [first_result, *stream]

    assert [row[0]["series_uid"] for row in resolved] == ["first", "second"]
    assert [row[1].frame_count for row in resolved] == [12, 18]
    assert [row[2] for row in resolved] == ["scan", "scan"]
    assert maximum > 1


def test_ordered_catalog_inventory_rollback_is_sequential(monkeypatch, tmp_path):
    series = tmp_path / "study" / "1"
    for index in range(4):
        make_dicom(series / f"{index}.dcm", 1)
    monkeypatch.setenv("AIPACS_LOCAL_ORDERED_INVENTORY", "0")
    original = inventory.dicom_file_pixel_facts
    threads = []

    def observed(path):
        import threading
        threads.append(threading.get_ident())
        return original(path)

    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", observed)
    resolved = list(inventory.resolve_series_pixel_inventories([
        {"series_uid": "only", "series_path": str(series)},
    ], workers=4))

    assert resolved[0][1].frame_count == 4
    assert len(set(threads)) == 1


def test_ordered_probe_window_does_not_queue_an_entire_large_series():
    class FakeFuture:
        def __init__(self, owner, value):
            self.owner = owner
            self.value = value

        def result(self):
            self.owner.outstanding -= 1
            return self.value

    class FakeExecutor:
        def __init__(self):
            self.outstanding = 0
            self.maximum = 0

        def submit(self, function, value):
            self.outstanding += 1
            self.maximum = max(self.maximum, self.outstanding)
            return FakeFuture(self, function(value))

    executor = FakeExecutor()
    results = list(inventory._bounded_ordered_results(
        executor, lambda value: value * 2, range(1000), 6,
    ))

    assert results == [value * 2 for value in range(1000)]
    assert executor.maximum == 6
    assert executor.outstanding == 0


def test_concurrent_consumers_do_not_duplicate_header_reads(monkeypatch, tmp_path):
    make_dicom(tmp_path / "a.dcm", 3)
    calls = count_reads(monkeypatch)
    original = inventory.dicom_file_pixel_facts
    entered, release, both = Event(), Event(), Barrier(2)
    def blocked(path):
        entered.set()
        assert release.wait(5)
        return original(path)
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", blocked)
    def run():
        both.wait(5)
        return inventory.inspect_series_pixel_inventory(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        try:
            assert entered.wait(5)
        finally:
            release.set()
        assert [f.result(5).frame_count for f in futures] == [3, 3]
    assert len(calls) == 1


def test_changed_added_removed_and_replaced_files_are_recounted(monkeypatch, tmp_path):
    path = make_dicom(tmp_path / "a.dcm", 12)
    calls = count_reads(monkeypatch)
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 12
    old = path.stat()
    make_dicom(path, 13)
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns + 10000000))
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 13
    make_dicom(tmp_path / "b.dcm", 2)
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 15
    path.unlink()
    assert inventory.inspect_series_pixel_inventory(tmp_path) == inventory.SeriesPixelInventory(1, 1, 2)
    replacement = make_dicom(tmp_path / "replacement.tmp", 4)
    replacement.replace(tmp_path / "b.dcm")
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 4
    assert len(calls) == 4


def test_same_names_in_other_studies_or_collision_folders_do_not_alias(tmp_path):
    for folder, frames in (("study-a/1", 25), ("study-a/1__collision", 420), ("study-b/1", 7)):
        make_dicom(tmp_path / folder / "a.dcm", frames)
    for _ in range(2):
        assert [inventory.inspect_series_pixel_inventory(tmp_path / f).frame_count
                for f in ("study-a/1", "study-a/1__collision", "study-b/1")] == [25, 420, 7]


def test_failed_or_nonpixel_probe_is_never_sticky(monkeypatch, tmp_path):
    make_dicom(tmp_path / "a.dcm")
    results = iter([(False, 0), (True, 5)])
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", lambda _: next(results))
    assert inventory.inspect_series_pixel_inventory(tmp_path).pixel_instance_count == 0
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 5


def test_mutation_during_probe_is_not_published(monkeypatch, tmp_path):
    path = make_dicom(tmp_path / "a.dcm", 2)
    original = inventory.dicom_file_pixel_facts
    calls = []
    def mutate(file):
        calls.append(file)
        result = original(file)
        if len(calls) == 1:
            make_dicom(path, 5)
        return result
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", mutate)
    inventory.inspect_series_pixel_inventory(tmp_path)
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 5
    assert len(calls) == 2


def test_cache_expires_and_is_bounded(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "_PIXEL_FACTS_CACHE_LIMIT", 2, raising=False)
    now = [0.0]
    monkeypatch.setattr(inventory, "monotonic", lambda: now[0], raising=False)
    calls = count_reads(monkeypatch)
    for index in range(3):
        make_dicom(tmp_path / str(index) / "a.dcm", 2)
        inventory.inspect_series_pixel_inventory(tmp_path / str(index))
    assert len(getattr(inventory, "_pixel_facts_cache", {})) == 2
    inventory.inspect_series_pixel_inventory(tmp_path / "0")  # evicted
    now[0] = 1000.0
    inventory.inspect_series_pixel_inventory(tmp_path / "0")  # expired
    assert len(calls) == 5


def test_blank_path_never_scans_working_directory(monkeypatch, tmp_path):
    make_dicom(tmp_path / "a.dcm")
    monkeypatch.chdir(tmp_path)
    assert inventory.inspect_series_pixel_inventory("") == inventory.SeriesPixelInventory()


@pytest.mark.parametrize("syntax", [ExplicitVRLittleEndian, ImplicitVRLittleEndian,
                                  ExplicitVRBigEndian, DeflatedExplicitVRLittleEndian, JPEGBaseline8Bit])
def test_transfer_syntax_facts_unchanged_without_decoding(tmp_path, syntax):
    path = make_dicom(tmp_path / "a.dcm", 7, syntax=syntax)
    before = path.read_bytes()
    assert inventory.dicom_file_pixel_facts(path) == (True, 7)
    assert path.read_bytes() == before


@pytest.mark.parametrize("tag", [0x7FE00010, 0x7FE00008, 0x7FE00009, None])
def test_pixel_kinds_and_nonpixel_remain_distinct(tmp_path, tag):
    path = make_dicom(tmp_path / "a.dcm", 3, pixel_tag=tag)
    assert inventory.dicom_file_pixel_facts(path) == ((True, 3) if tag else (False, 0))


def test_probe_does_not_materialize_unneeded_defined_length_values(monkeypatch, tmp_path):
    path = make_dicom(tmp_path / "a.dcm", 9)
    original = inventory.read_partial
    keys = []
    def observe(*args, **kwargs):
        ds = original(*args, **kwargs)
        keys.extend(ds.keys())
        return ds
    monkeypatch.setattr(inventory, "read_partial", observe)
    assert inventory.dicom_file_pixel_facts(path) == (True, 9)
    assert 0x00111010 not in keys
    assert 0x00100010 not in keys
    assert 0x7FE00010 not in keys


def test_undefined_length_nested_sequence_does_not_hide_pixel_tag(tmp_path):
    from pydicom import dcmread
    from pydicom.dataset import Dataset
    from pydicom.sequence import Sequence
    path = make_dicom(tmp_path / "a.dcm", 4)
    ds = dcmread(path)
    item = Dataset()
    item.ReferencedSOPClassUID = SecondaryCaptureImageStorage
    item.is_undefined_length_sequence_item = True
    ds.ReferencedImageSequence = Sequence([item])
    ds[0x00081140].is_undefined_length = True
    ds.save_as(path, write_like_original=False)
    assert inventory.dicom_file_pixel_facts(path) == (True, 4)


def test_stat_failure_never_reuses_stale_positive_result(monkeypatch, tmp_path):
    make_dicom(tmp_path / "a.dcm", 7)
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 7
    original = inventory._pixel_file_version
    def denied(_):
        raise PermissionError("Synthetic inaccessible storage")
    monkeypatch.setattr(inventory, "_pixel_file_version", denied)
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 0
    assert not inventory._pixel_facts_cache
    monkeypatch.setattr(inventory, "_pixel_file_version", original)
    assert inventory.inspect_series_pixel_inventory(tmp_path).frame_count == 7


def test_log_records_only_aggregate_work(monkeypatch, tmp_path, caplog):
    import logging
    path = make_dicom(tmp_path / "private-folder" / "private-file.dcm", 7)
    with caplog.at_level(logging.INFO, logger=inventory.__name__):
        inventory.inspect_series_pixel_inventory(path.parent)
        inventory.inspect_series_pixel_inventory(path.parent)
    messages = [record.getMessage() for record in caplog.records
                if "LOCAL_PIXEL_INVENTORY" in record.getMessage()]
    assert len(messages) == 2
    assert "cache_hits=0 probes=1" in messages[0]
    assert "cache_hits=1 probes=0" in messages[1]
    assert all("private" not in message and "Synthetic" not in message for message in messages)


def test_real_home_and_patient_projections_share_facts_without_identity_changes(monkeypatch, tmp_path):
    import ast
    import logging
    import sys
    from types import ModuleType, SimpleNamespace
    # Compile the actual UI projection methods, injecting only DB and PNG I/O.
    # The real pixel helper and display-key allocator remain under test.
    from PacsClient.utils import patient_study_set  # load before isolated DB stub
    assert patient_study_set.allocate_series_display_keys
    rows = []
    for uid, folder, frames, pixel in (("still", "1", 25, True),
                                      ("cine", "1__collision", 420, True),
                                      ("document", "4", 1, False)):
        make_dicom(tmp_path / folder / "a.dcm", frames, pixel_tag=0x7FE00010 if pixel else None)
        rows.append({"series_uid": uid, "series_number": "1" if pixel else "4",
                     "series_path": str(tmp_path / folder), "series_description": ""})
    db = ModuleType("database.manager")
    db.get_study_info_with_series = lambda _: {"series": rows}
    utils = ModuleType("PacsClient.pacs.patient_tab.utils.utils")
    utils.canonical_thumbnail_path = lambda uid, key: tmp_path / "png" / f"{key}.png"
    utils.repair_local_series_thumbnail = lambda *args: ""
    monkeypatch.setitem(sys.modules, db.__name__, db)
    monkeypatch.setitem(sys.modules, utils.__name__, utils)
    repo = Path(__file__).resolve().parents[3]
    methods = []
    for relative, name in (
        ("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py", "_build_local_series_thumbnail_payload"),
        ("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py", "_build_local_thumbnail_entries"),
    ):
        tree = ast.parse((repo / relative).read_text(encoding="utf-8-sig"))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        namespace = {"Path": Path, "_logger": logging.getLogger(__name__)}
        exec(compile(ast.Module(body=[method], type_ignores=[]), relative, "exec"), namespace)
        methods.append(namespace[name])
    calls = count_reads(monkeypatch)
    owner = SimpleNamespace(logger=logging.getLogger(__name__))
    home = methods[0](owner, "synthetic-study")["thumbnails"]
    patient = methods[1](owner, "synthetic-study")
    keys = ("series_uid", "study_uid", "series_number", "folder_key", "series_path",
            "display_key", "image_count", "display_image_count")
    assert [{k: row[k] for k in keys} for row in home] == [{k: row[k] for k in keys} for row in patient]
    assert [row["display_image_count"] for row in patient] == [25, 420]
    assert len({row["display_key"] for row in patient}) == 2
    assert len(calls) == 4  # two positive reads once, non-pixel rechecked twice


def test_missing_frame_count_and_nested_pixels_keep_top_level_contract(tmp_path):
    from pydicom import dcmread
    from pydicom.dataset import Dataset
    from pydicom.sequence import Sequence
    path = make_dicom(tmp_path / "a.dcm")
    ds = dcmread(path)
    del ds.NumberOfFrames
    ds.save_as(path, write_like_original=False)
    assert inventory.dicom_file_pixel_facts(path) == (True, 1)
    del ds.PixelData
    item = Dataset()
    item.add_new(0x7FE00010, "OB", b"\0\0")
    item.NumberOfFrames = 8
    ds.ReferencedImageSequence = Sequence([item])
    ds[0x00081140].is_undefined_length = True
    ds.save_as(path, write_like_original=False)
    assert inventory.dicom_file_pixel_facts(path) == (False, 0)


def test_slow_file_does_not_hold_global_cache_lock(monkeypatch, tmp_path):
    slow = make_dicom(tmp_path / "slow" / "a.dcm")
    stripe_count = len(inventory._pixel_facts_stripes)
    slow_stripe = hash(os.path.normcase(os.path.abspath(slow))) % stripe_count
    for index in range(1000):
        fast = tmp_path / str(index) / "a.dcm"
        if hash(os.path.normcase(os.path.abspath(fast))) % stripe_count != slow_stripe:
            break
    else:
        pytest.fail("No independent lock stripe found")
    make_dicom(fast)
    entered, release = Event(), Event()
    original = inventory.dicom_file_pixel_facts
    def blocked(path):
        if Path(path) == slow:
            entered.set()
            assert release.wait(5)
        return original(path)
    monkeypatch.setattr(inventory, "dicom_file_pixel_facts", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        waiting = pool.submit(inventory.inspect_series_pixel_inventory, slow.parent)
        try:
            assert entered.wait(5)
            independent = pool.submit(inventory.inspect_series_pixel_inventory, fast.parent)
            assert independent.result(2).frame_count == 1
        finally:
            release.set()
        assert waiting.result(5).frame_count == 1
