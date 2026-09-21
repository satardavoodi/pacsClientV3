"""Exercise the production multi-study projection across historical contracts.

Synthetic metadata only. Execute the real controller method without importing
Qt, opening the clinical database, reading pixels or contacting a server.
The same expectations run before and after moving projection into the trunk.
"""
import ast
import copy
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
CONTROLLER = ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py"


def _load(monkeypatch, name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def harness(monkeypatch, tmp_path):
    identity = _load(monkeypatch, "_unify_identity", "PacsClient/utils/series_identity.py")
    allocator = _load(monkeypatch, "_unify_allocator", "PacsClient/utils/patient_study_set.py")
    normalize = _load(monkeypatch, "_unify_normalize", "modules/network/series_identity.py")
    refs = _load(monkeypatch, "_unify_refs", "PacsClient/utils/series_ref.py")
    config = ModuleType("PacsClient.utils.config")
    config.SOURCE_PATH = tmp_path
    monkeypatch.setitem(sys.modules, config.__name__, config)
    monkeypatch.setenv("AIPACS_SERIES_NUMBER_NORMALIZE", "1")
    monkeypatch.setenv("AIPACS_HISTORY_SERIES_FIRST", "1")
    tree = ast.parse(CONTROLLER.read_text(encoding="utf-8-sig"))
    names = {"_history_first_enabled", "series_is_clinical_history", "_rebuild_multistudy_series_index"}
    nodes = [node for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "os": os, "Path": Path, "_HISTORY_SERIES_NUMBER": 100000,
        "_get_series_number": identity.get_series_number,
        "_get_series_uid": identity.get_series_uid,
    }
    # The second run consumes the real shared helper after the extraction.
    if hasattr(identity, "build_multistudy_series_projection"):
        namespace["build_multistudy_series_projection"] = identity.build_multistudy_series_projection
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(CONTROLLER), "exec"), namespace)

    def prepare(groups):
        normalized = {}
        for study_uid, records in groups.items():
            rows = [dict(row, study_uid=study_uid) for row in records]
            normalize.normalize_series_entries(rows)
            normalized[study_uid] = allocator.allocate_series_display_keys(rows)
        return normalized

    return SimpleNamespace(
        run=namespace["_rebuild_multistudy_series_index"], prepare=prepare,
        refs=refs, root=tmp_path, identity=identity,
    )


def _series(uid, number, *, description="", folder=None, path=None, files=1, frames=1):
    row = {"series_uid": uid, "series_number": number,
           "series_description": description, "image_count": files,
           "display_image_count": frames}
    if folder is not None:
        row["folder_key"] = folder
    if path is not None:
        row["series_path"] = path
    return row


def _viewer(harness, groups):
    return SimpleNamespace(study_uid="primary", _studies_series=harness.prepare(groups))


@pytest.mark.parametrize("description", ["", None, "Untitled Series", "Same description"])
def test_repeated_numbers_and_labels_preserve_each_study(harness, description):
    viewer = _viewer(harness, {
        "primary": [_series("uid-p", "1", description=description)],
        "secondary": [_series("uid-s", "1", description=description)],
    })
    before = copy.deepcopy(viewer._studies_series)
    harness.run(viewer)
    table = harness.refs.build_series_ref_table(viewer._server_series_info, "primary")
    assert set(table) == {"1", "1000001"}
    assert (table["1"].study_uid, table["1"].series_uid) == ("primary", "uid-p")
    assert (table["1000001"].study_uid, table["1000001"].series_uid) == ("secondary", "uid-s")
    assert table["1000001"].series_path == str(harness.root / "secondary" / "1")
    assert viewer._studies_series == before


@pytest.mark.parametrize("missing", [None, "", "None", "null", "N/A"])
def test_missing_numbers_keep_canonical_synthetic_band(harness, missing):
    groups = {
        "primary": [_series("uid-z", missing), _series("uid-a", missing),
                    _series("uid-reserved", "900001")],
        "secondary": [_series("uid-secondary", missing)],
    }
    viewer = _viewer(harness, groups)
    harness.run(viewer)
    assert viewer._series_uid_to_number == {
        "uid-reserved": "900001", "uid-a": "900002", "uid-z": "900003",
        "uid-secondary": "1900001",
    }
    reversed_viewer = _viewer(harness, {su: list(reversed(rows)) for su, rows in groups.items()})
    harness.run(reversed_viewer)
    assert reversed_viewer._series_uid_to_number == viewer._series_uid_to_number


def test_same_study_duplicates_keep_cine_folder_and_frame_count(harness):
    exact = str(harness.root / "external-import" / "1_2")
    viewer = _viewer(harness, {
        "primary": [_series("uid-still", "1", folder="1", files=25, frames=25),
                    _series("uid-cine", "1", folder="1_2", path=exact, files=2, frames=420)],
        "secondary": [_series("uid-secondary", "1")],
    })
    harness.run(viewer)
    assert viewer._series_uid_to_number == {
        "uid-still": "1", "uid-cine": "900001", "uid-secondary": "1000001"}
    cine = viewer._server_series_info["900001"]
    assert (cine["image_count"], cine["display_image_count"]) == (2, 420)
    ref = harness.refs.build_series_ref_table(viewer._server_series_info, "primary")["900001"]
    assert (ref.series_number, ref.storage_key, ref.series_path) == ("1", "1_2", exact)


def test_leading_zero_raw_label_and_exact_path_survive_offset_projection(harness):
    viewer = _viewer(harness, {
        "primary": [_series("uid-p", "02", folder="02")],
        "secondary": [_series("uid-s", "02", folder="02")],
    })
    harness.run(viewer)
    table = harness.refs.build_series_ref_table(viewer._server_series_info, "primary")
    assert table["2"].series_number == table["1000002"].series_number == "02"
    assert table["1000002"].storage_key == "02"
    assert table["1000002"].series_path == str(harness.root / "secondary" / "02")


def test_late_study_does_not_reassign_existing_slots(harness):
    viewer = _viewer(harness, {
        "primary": [_series("uid-p", "1")], "z-study": [_series("uid-z", "1")],
    })
    harness.run(viewer)
    original_key = viewer._series_uid_to_number["uid-z"]
    viewer._studies_series.update(harness.prepare({"a-study": [_series("uid-a", "1")]}))
    harness.run(viewer)
    assert viewer._multistudy_slot_order == ["primary", "z-study", "a-study"]
    assert viewer._series_uid_to_number["uid-z"] == original_key == "1000001"
    assert viewer._series_uid_to_number["uid-a"] == "2000001"
    snapshot = copy.deepcopy(viewer._server_series_info)
    harness.run(viewer)
    assert viewer._server_series_info == snapshot


def test_numeric_order_and_exact_history_priority_survive(harness, monkeypatch):
    viewer = _viewer(harness, {
        "primary": [_series(f"uid-{n}", str(n)) for n in (10, 2, 100001, 1, 100000)],
        "secondary": [_series("uid-s", "1")],
    })
    harness.run(viewer)
    assert list(viewer._server_series_info)[:5] == ["100000", "1", "2", "10", "100001"]
    monkeypatch.setenv("AIPACS_HISTORY_SERIES_FIRST", "0")
    harness.run(viewer)
    assert list(viewer._server_series_info)[:5] == ["1", "2", "10", "100000", "100001"]


def test_single_study_keeps_its_existing_maps(harness):
    viewer = _viewer(harness, {"primary": [_series("uid-p", "02")]})
    original = {"02": {"synthetic_sentinel": True}}
    viewer._server_series_info = original
    harness.run(viewer)
    assert viewer._server_series_info is original
    assert not hasattr(viewer, "_multistudy_slot_order")


def test_shared_projection_does_not_mutate_prior_slot_history_or_input(harness):
    groups = harness.prepare({
        "primary": [_series("uid-p", "1")], "secondary": [_series("uid-s", "1")],
    })
    before = copy.deepcopy(groups)
    prior = ["primary"]
    result = harness.identity.build_multistudy_series_projection(
        groups, "primary", prior, None,
        series_sort_key=lambda row: int(row["series_number"]),
    )
    assert prior == ["primary"]
    assert result.slot_order == ["primary", "secondary"]
    assert groups == before
    assert all("series_path" not in row for row in result.series_info.values())
