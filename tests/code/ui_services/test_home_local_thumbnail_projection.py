"""Execute the real Local projection with synthetic, isolated I/O boundaries.

The method is compiled from its AST to avoid importing the full Home UI and
its runtime services. No live database, PACS socket or DICOM bytes are opened.
"""
import ast
import importlib.util
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py"


@pytest.fixture
def projection(monkeypatch, tmp_path):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef)
                  and node.name == "_build_local_series_thumbnail_payload")
    namespace = {"_logger": logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(SOURCE), "exec"), namespace)

    rows = []
    inventories = {}
    inventory_sources = {}
    calls = []
    backfills = []

    def query(study_uid):
        calls.append(study_uid)
        return {"series": rows}

    db = ModuleType("database.manager")
    db.get_study_info_with_series = query
    db_writer = ModuleType("database.dicom_db")
    db_writer.mark_series_pixel_inventories = lambda records: backfills.append(list(records))
    utils = ModuleType("PacsClient.pacs.patient_tab.utils.utils")
    utils.canonical_thumbnail_path = lambda uid, key: tmp_path / uid / f"{key}.png"
    pixels = ModuleType("PacsClient.utils.dicom_displayability")

    def inspect(path):
        result = inventories[path]
        if isinstance(result, Exception):
            raise result
        return result

    pixels.inspect_series_pixel_inventory = inspect
    pixels.resolve_series_pixel_inventory = lambda series: (
        inspect(series.get("series_path") or ""),
        inventory_sources.get(series.get("series_path") or "", "scan"),
    )
    def resolve_many(series_items, **_kwargs):
        for series in series_items:
            inventory_value, source = pixels.resolve_series_pixel_inventory(series)
            yield series, inventory_value, source
    pixels.resolve_series_pixel_inventories = resolve_many
    for module in (db, db_writer, utils, pixels):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    # Load the real pure allocator without PacsClient.utils.__init__, whose
    # service imports otherwise bind to the intentionally fake database module.
    module_name = "PacsClient.utils.patient_study_set"
    spec = importlib.util.spec_from_file_location(module_name, REPO / "PacsClient/utils/patient_study_set.py")
    identities = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, identities)
    spec.loader.exec_module(identities)

    def add(uid, number, folder, instances, frames, *, has_pixels=True):
        path = str(tmp_path / "study-a" / folder)
        row = {"series_uid": uid, "series_number": number, "series_path": path,
               "series_pk": len(rows) + 1,
               "modality": "US", "series_description": "Synthetic series"}
        rows.append(row)
        inventories[path] = SimpleNamespace(
            has_pixel_data=has_pixels, instance_count=max(instances, 1),
            pixel_instance_count=instances, frame_count=frames,
            display_image_count=frames, directory_mtime_ns=123)
        return row

    return SimpleNamespace(
        run=lambda: namespace[method.name](object(), "study-a"),
        add=add, rows=rows, inventories=inventories, calls=calls, db=db,
        backfills=backfills, inventory_sources=inventory_sources,
    )


def test_success_allocates_collision_keys_and_preserves_counts_and_paths(projection):
    still = projection.add("uid-still", "1", "1", 25, 25)
    cine = projection.add("uid-cine", "1", "1_2", 2, 420)
    projection.add("uid-document", "4", "4", 0, 0, has_pixels=False)
    original = [dict(row) for row in projection.rows]

    payload = projection.run()
    by_uid = {row["series_uid"]: row for row in payload["thumbnails"]}

    assert set(by_uid) == {"uid-still", "uid-cine"}
    assert by_uid["uid-still"]["display_key"] == "1"
    assert by_uid["uid-cine"]["display_key"] == "900001"
    for uid, source, files, frames in (("uid-still", still, 25, 25),
                                      ("uid-cine", cine, 2, 420)):
        row = by_uid[uid]
        assert row["study_uid"] == "study-a"
        assert row["series_number"] == row["_orig_series_number"] == "1"
        assert row["series_path"] == source["series_path"]
        assert row["folder_key"] == Path(source["series_path"]).name
        assert (row["image_count"], row["display_image_count"]) == (files, frames)
    assert projection.rows == original
    assert projection.calls == ["study-a"]


def test_unique_series_preserves_leading_zero_text(projection):
    projection.add("uid-leading-zero", "02", "02", 3, 3)
    row = projection.run()["thumbnails"][0]
    assert row["display_key"] == row["series_number"] == row["folder_key"] == "02"


def test_legacy_scans_use_one_shared_batch_backfill(projection):
    first = projection.add("uid-still", "1", "1", 25, 25)
    second = projection.add("uid-cine", "2", "2", 2, 420)

    projection.run()

    assert projection.backfills == [[
        (first["series_pk"], 25, 25, 25, first["series_path"], 123),
        (second["series_pk"], 2, 2, 420, second["series_path"], 123),
    ]]


def test_verified_inventory_emits_one_aggregate_fast_path_marker(projection, caplog):
    first = projection.add("uid-still", "1", "1", 25, 25)
    second = projection.add("uid-cine", "2", "2", 2, 420)
    projection.inventory_sources[first["series_path"]] = "index"
    projection.inventory_sources[second["series_path"]] = "index"

    with caplog.at_level(logging.INFO):
        projection.run()

    messages = [record.getMessage() for record in caplog.records]
    markers = [message for message in messages
               if "[LOCAL_PIXEL_INVENTORY]" in message]
    assert markers == [
        "[LOCAL_PIXEL_INVENTORY] source=producer_index owner=home_local "
        "series=2 files=27 frames=445"
    ]
    assert projection.backfills == []


def test_partial_projection_still_assigns_keys_to_completed_rows(projection):
    projection.add("uid-cine", "1", "1_2", 2, 420)
    broken = projection.add("uid-broken", "4", "4", 1, 1)
    projection.inventories[broken["series_path"]] = OSError("Synthetic inventory failure")
    rows = projection.run()["thumbnails"]
    assert len(rows) == 1
    assert rows[0]["display_key"] == "900001"


def test_empty_and_failed_query_keep_empty_payload(projection):
    expected = {"study_uid": "study-a", "thumbnails": []}
    assert projection.run() == expected

    def failed_query(_uid):
        raise OSError("Synthetic query failure")

    projection.db.get_study_info_with_series = failed_query
    assert projection.run() == expected


def test_dependency_import_failure_returns_empty_payload(projection, monkeypatch):
    # The error handler must not call an allocator whose import was never reached.
    monkeypatch.setitem(sys.modules, "database.manager", None)
    assert projection.run() == {"study_uid": "study-a", "thumbnails": []}
