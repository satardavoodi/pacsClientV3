"""Synthetic filesystem-cost and freshness guards for Local inventory."""
from contextlib import contextmanager
from pathlib import Path
import os

import pytest

from PacsClient.utils import dicom_displayability as inventory
from tests.code.ui_services.test_local_pixel_inventory_persistence import local_store
from tests.code.ui_services.test_local_pixel_inventory_reuse import make_dicom, count_reads


@pytest.mark.parametrize('warm', [False, True])
def test_enumeration_does_not_restat_each_candidate_for_type(monkeypatch, local_store, warm):
    root = local_store / 'dicom' / 'study-a' / '1'
    source = make_dicom(root / 'one.dcm', 420)
    if warm:
        inventory.inspect_series_pixel_inventory(root)
    calls = []
    real_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == source:
            calls.append(path)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat)
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 420
    # Preserve fresh version-before-use and post-probe mutation validation;
    # only the redundant classification stat is removed.
    assert len(calls) == (1 if warm else 2)


def test_selection_matches_existing_platform_glob_and_order(monkeypatch, local_store):
    root = local_store / 'dicom' / 'study-a' / '1'
    for name in ('z.dcm', 'A.DCM', 'b.dcm', '.dcm', 'ignore.dicom', 'part.dcm.part'):
        make_dicom(root / name, 2)
    make_dicom(root / 'nested.dcm' / 'inside.dcm', 9)
    expected = sorted(p for p in root.glob('*.dcm') if p.is_file())
    calls = count_reads(monkeypatch)
    result = inventory.inspect_series_pixel_inventory(root)
    assert calls == expected
    assert result == inventory.SeriesPixelInventory(len(expected), len(expected), 2 * len(expected))


def instrument_scan(monkeypatch, root, *, after=None, entry_stat_forbidden=False):
    real_scan = os.scandir
    closed = []

    class Entry:
        def __init__(self, entry):
            self._entry = entry
        def __getattr__(self, name):
            return getattr(self._entry, name)
        def stat(self, *args, **kwargs):
            if entry_stat_forbidden:
                pytest.fail('Cached DirEntry stat cannot replace fresh file-version stat')
            return self._entry.stat(*args, **kwargs)

    @contextmanager
    def scan(path):
        if Path(path) != root:
            with real_scan(path) as entries:
                yield entries
            return
        try:
            with real_scan(path) as entries:
                yield iter([Entry(entry) for entry in entries])
        finally:
            closed.append(True)
            if after:
                after()

    monkeypatch.setattr(os, 'scandir', scan)
    return closed


def test_directory_handle_closes_before_pixel_probes(monkeypatch, local_store):
    root = local_store / 'dicom' / 'study-a' / '1'
    make_dicom(root / 'a.dcm', 7)
    closed = instrument_scan(monkeypatch, root, entry_stat_forbidden=True)
    real_probe = inventory.dicom_file_pixel_facts
    def probe(path):
        assert closed == [True], 'Do not hold enumeration handles during classification'
        return real_probe(path)
    monkeypatch.setattr(inventory, 'dicom_file_pixel_facts', probe)
    assert inventory.inspect_series_pixel_inventory(root).frame_count == 7


@pytest.mark.parametrize('change', ['replace', 'delete'])
def test_cached_entry_never_bypasses_fresh_version_after_enumeration(monkeypatch, local_store, change):
    root = local_store / 'dicom' / 'study-a' / '1'
    source = make_dicom(root / 'a.dcm', 2)
    inventory.inspect_series_pixel_inventory(root)
    replacement = make_dicom(local_store / 'replacement.tmp', 420)

    def mutate():
        if change == 'replace':
            replacement.replace(source)
        else:
            source.unlink()

    closed = instrument_scan(monkeypatch, root, after=mutate, entry_stat_forbidden=True)
    result = inventory.inspect_series_pixel_inventory(root)
    assert closed == [True]
    assert result.instance_count == 1
    assert result.frame_count == (420 if change == 'replace' else 0)


def test_symlink_file_and_directory_match_previous_membership(monkeypatch, local_store):
    root = local_store / 'dicom' / 'study-a' / '1'
    root.mkdir(parents=True)
    target = make_dicom(local_store / 'target.tmp', 7)
    try:
        (root / 'link.dcm').symlink_to(target)
        (root / 'directory.dcm').symlink_to(target.parent, target_is_directory=True)
        (root / 'broken.dcm').symlink_to(local_store / 'missing.tmp')
    except OSError as exc:
        pytest.skip(f'Synthetic symlink creation unavailable: {type(exc).__name__}')
    assert inventory.inspect_series_pixel_inventory(root) == inventory.SeriesPixelInventory(1, 1, 7)


def test_missing_or_non_directory_input_stays_empty(local_store):
    file = make_dicom(local_store / 'not-directory.dcm')
    for path in ('', '  ', local_store / 'missing', file):
        assert inventory.inspect_series_pixel_inventory(path) == inventory.SeriesPixelInventory()


def test_large_series_removes_type_stat_cost_without_changing_membership(monkeypatch, local_store):
    root = local_store / 'dicom' / 'study-a' / '1'
    root.mkdir(parents=True)
    for number in range(192):
        (root / f'instance-{number:04d}.dcm').touch()
    calls = []
    real_stat = Path.stat
    def stat(path, *args, **kwargs):
        if path.parent == root:
            calls.append(path)
        return real_stat(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', stat)
    legacy = sorted(path for path in root.glob('*.dcm') if path.is_file())
    assert len(calls) == 192
    calls.clear()
    assert inventory._inventory_dicom_paths(root) == legacy
    assert calls == [], 'Enumeration must retain type facts rather than re-open 192 paths'


@pytest.mark.parametrize('error', [PermissionError, FileNotFoundError, NotADirectoryError])
def test_unavailable_enumeration_preserves_glob_empty_result(monkeypatch, local_store, error):
    root = local_store / 'dicom' / 'study-a' / '1'
    root.mkdir(parents=True)
    def scan(_path):
        raise error('synthetic enumeration unavailable')
    monkeypatch.setattr(os, 'scandir', scan)
    assert inventory._inventory_dicom_paths(root) == []


def test_mid_enumeration_error_closes_handle_and_discards_partial_listing(monkeypatch, local_store):
    root = local_store / 'dicom' / 'study-a' / '1'
    root.mkdir(parents=True)
    from types import SimpleNamespace
    closed = []
    def entries():
        yield SimpleNamespace(name='a.dcm', path=str(root / 'a.dcm'), is_file=lambda: True)
        raise OSError('synthetic scan interrupted')
    @contextmanager
    def scan(_path):
        try:
            yield entries()
        finally:
            closed.append(True)
    monkeypatch.setattr(os, 'scandir', scan)
    assert inventory._inventory_dicom_paths(root) == []
    assert closed == [True]


def test_new_cache_timing_fields_are_numeric_and_have_no_path(monkeypatch, local_store, caplog):
    root = local_store / 'dicom' / 'study-a' / '1'
    make_dicom(root / 'a.dcm')
    import logging
    import re
    with caplog.at_level(logging.INFO, logger=inventory.__name__):
        inventory.inspect_series_pixel_inventory(root)
    messages = [r.getMessage() for r in caplog.records if 'files=' in r.getMessage()]
    assert len(messages) == 1 and str(local_store) not in messages[0]
    fields = dict(re.findall(r'(cache_read_ms|cache_path_ms|cache_load_ms)=([\d.]+)', messages[0]))
    assert fields.keys() == {'cache_read_ms', 'cache_path_ms', 'cache_load_ms'}
    assert abs(float(fields['cache_read_ms']) - float(fields['cache_path_ms'])
               - float(fields['cache_load_ms'])) <= .021
