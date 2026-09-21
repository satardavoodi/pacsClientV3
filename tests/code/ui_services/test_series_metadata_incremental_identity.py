"""Exercise the real metadata sink without Qt, patient data, DB or network.

Only dependency-heavy imports/scheduling are substituted. The sink, allocator,
multi-study projection and SeriesRef resolver are production implementations.
"""
import ast
import copy
import importlib.util
import logging
import os
import sys
from pathlib import Path
from types import MethodType, ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SINK = ROOT / "PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py"


@pytest.fixture
def harness(monkeypatch, tmp_path):
    def load(name, relative):
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        return module

    identity = load("_incremental_identity", "PacsClient/utils/series_identity.py")
    allocator = load("PacsClient.utils.patient_study_set", "PacsClient/utils/patient_study_set.py")
    refs = load("_incremental_refs", "PacsClient/utils/series_ref.py")
    config = ModuleType("PacsClient.utils.config")
    config.SOURCE_PATH = tmp_path
    monkeypatch.setitem(sys.modules, config.__name__, config)
    names = {"set_server_series_info", "_rebuild_multistudy_series_index",
             "_history_first_enabled", "series_is_clinical_history"}
    nodes = [n for n in ast.walk(ast.parse(SINK.read_text(encoding="utf-8-sig")))
             if isinstance(n, ast.FunctionDef) and n.name in names]
    calls = []
    namespace = dict(
        os=os, Path=Path, _HISTORY_SERIES_NUMBER=100000,
        _PRIMARY_BUCKET_FALLBACK=True,
        _get_series_number=identity.get_series_number,
        _get_series_uid=identity.get_series_uid,
        build_multistudy_series_projection=identity.build_multistudy_series_projection,
        QMetaObject=SimpleNamespace(invokeMethod=lambda *args: calls.append(args[1])),
        Qt=SimpleNamespace(QueuedConnection=1),
    )
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SINK), "exec"), namespace)

    def viewer():
        widget = SimpleNamespace(
            study_uid="study-primary", logger=logging.getLogger(__name__),
            series_metadata_ready=SimpleNamespace(emit=lambda: None),
            _schedule_multistudy_thumbnail_prefetch=lambda: None,
        )
        for name in ("set_server_series_info", "_rebuild_multistudy_series_index"):
            setattr(widget, name, MethodType(namespace[name], widget))
        return widget

    return SimpleNamespace(viewer=viewer, allocator=allocator, refs=refs, calls=calls)


def row(uid, number="1", *, study="study-primary", folder=None, count=0):
    result = dict(study_uid=study, series_uid=uid, series_number=number,
                  image_count=count, series_description="")
    if folder is not None:
        result["folder_key"] = folder
    return result


def snapshot(harness, widget):
    return harness.refs.build_series_ref_table(widget._server_series_info, widget.study_uid)


def test_late_collision_cannot_reuse_an_admitted_series_handle(harness):
    widget = harness.viewer()
    widget.set_server_series_info([row("still", folder="1", count=25),
                                   row("cine-a", folder="1_2", count=2)])
    before = snapshot(harness, widget)
    widget.set_server_series_info([row("cine-b", folder="1_3", count=3)])
    after = snapshot(harness, widget)
    assert len(after) == 3
    assert all(after[key] == value for key, value in before.items())
    assert len(set(widget._series_uid_to_number.values())) == 3
    assert widget._server_series_info[widget._series_uid_to_number["cine-b"]]["image_count"] == 3


def test_subset_refresh_keeps_its_original_alias_and_exact_folder(harness):
    widget = harness.viewer()
    widget.set_server_series_info([row("still", folder="1"),
                                   row("cine-a", folder="1_2"),
                                   row("cine-b", folder="1_3")])
    before = snapshot(harness, widget)
    update = row("cine-b", count=3)
    update["series_description"] = "Updated description"
    widget.set_server_series_info([update])
    assert snapshot(harness, widget) == before
    assert widget._server_series_info["900002"]["series_description"] == "Updated description"
    assert widget._server_series_info["1"]["series_description"] == ""
    assert widget._server_series_info["900001"]["series_description"] == ""


def test_new_raw_number_cannot_steal_an_existing_alias(harness):
    widget = harness.viewer()
    widget.set_server_series_info([row("still", folder="1"), row("cine", folder="1_2")])
    before = snapshot(harness, widget)
    widget.set_server_series_info([row("late", number="900001", folder="900001")])
    after = snapshot(harness, widget)
    assert len(after) == 3
    assert all(after[key] == value for key, value in before.items())
    assert widget._series_uid_to_number["late"] != "900001"


@pytest.mark.parametrize("implicit_primary", [False, True])
def test_multi_study_late_alias_preserves_all_study_owned_routes(harness, implicit_primary):
    widget = harness.viewer()
    primary = row("primary", folder="1")
    if implicit_primary:
        primary.pop("study_uid")
    widget.set_server_series_info([primary, row("secondary", study="study-secondary", folder="1"),
                                   row("cine-a", study="study-secondary", folder="1_2")])
    before = snapshot(harness, widget)
    widget.set_server_series_info([row("cine-b", study="study-secondary", folder="1_3")])
    after = snapshot(harness, widget)
    assert len(after) == 4
    assert all(after[key] == value for key, value in before.items())
    assert after[widget._series_uid_to_number["cine-b"]].study_uid == "study-secondary"


def test_repeated_identical_payload_is_idempotent_and_does_not_reload(harness):
    widget = harness.viewer()
    payload = [row("still", folder="1", count=25), row("cine", folder="1_2", count=2)]
    original = copy.deepcopy(payload)
    widget.set_server_series_info(payload)
    before = copy.deepcopy(widget._server_series_info)
    calls = list(harness.calls)
    widget.set_server_series_info(payload)
    assert widget._server_series_info == before
    assert harness.calls == calls
    assert payload == original


def test_refresh_does_not_replace_known_server_counts_with_local_counts(harness):
    widget = harness.viewer()
    widget.set_server_series_info([row("still", folder="1", count=25)])
    widget.set_server_series_info([row("still", folder="1", count=2)])
    assert widget._server_series_info["1"]["image_count"] == 25


def test_collision_absent_uid_is_not_guessed_to_be_known_uid(harness):
    widget = harness.viewer()
    widget.set_server_series_info([row("known", folder="1", count=25)])
    widget.set_server_series_info([row("", folder="1_2", count=2)])
    assert widget._server_series_info["1"]["series_uid"] == "known"
    assert widget._server_series_info["1"]["image_count"] == 25


def test_repeated_legacy_missing_uid_does_not_create_more_handles(harness):
    widget = harness.viewer()
    payload = [row("", folder="1", count=4)]
    widget.set_server_series_info(payload)
    before = copy.deepcopy(widget._server_series_info)
    widget.set_server_series_info(payload)
    assert widget._server_series_info == before
    assert len(widget._studies_series["study-primary"]) == 1


def test_grouped_foreign_metadata_does_not_fill_primary_card(harness):
    widget = harness.viewer()
    widget.set_server_series_info([row("primary", folder="1", count=0)])
    secondary = row("secondary", study="study-secondary", folder="1", count=20)
    secondary["series_description"] = "Secondary description"
    widget.set_server_series_info([secondary])
    assert widget._server_series_info["1"]["series_description"] == ""
    assert widget._server_series_info["1"]["image_count"] == 0
    assert widget._server_series_info["1000001"]["image_count"] == 20


def test_cine_file_and_frame_counts_and_raw_labels_are_not_rewritten(harness):
    widget = harness.viewer()
    cine = row("cine", number="02", folder="02_2", count=2)
    cine["display_image_count"] = 420
    widget.set_server_series_info([row("still", number="02", folder="02", count=25), cine])
    before = copy.deepcopy(widget._server_series_info)
    widget.set_server_series_info([row("new", number="02", folder="02_3", count=5)])
    for key, old in before.items():
        assert widget._server_series_info[key] == old
    assert widget._server_series_info["900001"]["display_image_count"] == 420
    assert widget._server_series_info["900001"]["_orig_series_number"] == "02"


def test_full_refresh_in_reverse_order_keeps_admission_handles(harness):
    widget = harness.viewer()
    payload = [row("z", folder="1_2", count=1), row("still", folder="1", count=25)]
    widget.set_server_series_info(payload)
    widget.set_server_series_info([row("a", folder="1_3", count=2)])
    before = snapshot(harness, widget)
    widget.set_server_series_info([row("a", folder="1_3", count=200), *reversed(payload)])
    assert snapshot(harness, widget) == before


def test_fresh_owner_does_not_inherit_another_tabs_handles(harness):
    first, second = harness.viewer(), harness.viewer()
    first.set_server_series_info([row("z", folder="1_2")])
    first.set_server_series_info([row("a", folder="1_3")])
    second.set_server_series_info([row("a", folder="1_3")])
    assert first._series_uid_to_number["a"] == "900002"
    assert second._series_uid_to_number["a"] == "900001"


def test_allocator_refuses_corrupt_prior_mapping_before_mutating_input(harness):
    records = [row("new", folder="1_3")]
    previous = [dict(row("a", folder="1_2"), display_key="900001"),
                dict(row("b", folder="1_3"), display_key="900001")]
    before = copy.deepcopy((records, previous))
    with pytest.raises(ValueError, match="Conflicting prior"):
        harness.allocator.allocate_series_display_keys(records, existing_records=previous)
    assert (records, previous) == before


def test_new_series_batch_order_does_not_change_allocated_aliases(harness):
    first, second = harness.viewer(), harness.viewer()
    initial = [row("still", folder="1"), row("z", folder="1_2")]
    additions = [row("c", folder="1_3"), row("a", folder="1_4"), row("b", number="900001")]
    for widget in (first, second):
        widget.set_server_series_info(initial)
    first.set_server_series_info(additions)
    second.set_server_series_info(list(reversed(additions)))
    assert first._series_uid_to_number == second._series_uid_to_number


@pytest.mark.parametrize('number', ['999999', '1000000', '1000001', '2147483647'])
def test_large_raw_number_has_round_trip_safe_local_handle(harness, number):
    records = [dict(row('large', number=number, folder=number, count=2),
                    series_path=f'synthetic-root/{number}', display_image_count=420),
               row('reserved', number='900001', folder='900001')]
    before = copy.deepcopy(records)
    admitted = harness.allocator.allocate_series_display_keys(records)
    first = next(r for r in admitted if r['series_uid']=='large')
    assert 0 <= int(first['display_key']) < 1_000_000
    assert first['display_key'] != '900001'
    refreshed = harness.allocator.allocate_series_display_keys(records, existing_records=admitted)
    assert refreshed == admitted
    assert records == before
    assert (first['series_number'], first['_orig_series_number'], first['folder_key'],
            first['series_path'], first['image_count'], first['display_image_count']) == (
                number, number, number, f'synthetic-root/{number}', 2, 420)


def test_large_primary_number_cannot_collide_with_secondary_offset(harness):
    widget = harness.viewer()
    primary = row('primary-large', number='1000001', folder='1000001', count=25)
    secondary = row('secondary-one', study='study-secondary', number='1', folder='1', count=5)
    widget.set_server_series_info([primary])
    primary_key = widget._series_uid_to_number['primary-large']
    widget.set_server_series_info([secondary])
    for payload in ([primary], [secondary], [secondary, primary]):
        widget.set_server_series_info(payload)
        table = snapshot(harness, widget)
        assert len(table)==2
        assert table[primary_key].study_uid=='study-primary'
        assert table[primary_key].series_uid=='primary-large'
        assert table[primary_key].series_number=='1000001'
        assert table[primary_key].disk_series_number=='1000001'
        assert table['1000001'].series_uid=='secondary-one'


def test_already_offset_prior_keys_remain_rejected(harness):
    record = row('synthetic', number='1', folder='1')
    with pytest.raises(ValueError, match='study-local'):
        harness.allocator.allocate_series_display_keys([record], existing_records=[
            dict(record, display_key='1000001', _study_slot=1)])
