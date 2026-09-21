"""Home actions must carry UID identity, never a card position or foreign UI key."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from PacsClient.pacs.workstation_ui.home_ui.right_panel_widget import RightPanelWidget


REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def panel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    widget = RightPanelWidget()
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    monkeypatch.setattr(widget, "_build_pixmap_from_thumb", lambda *args: pixmap)
    emitted = []
    signal = getattr(widget, "seriesActionRequested", widget.thumbnailClicked)
    signal.connect(emitted.append)
    yield widget, emitted, app
    widget._cancel_thumbnail_timer()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def rows():
    return [dict(study_uid=study, series_uid=uid, series_number="4",
                 display_key=key, folder_key=folder, series_path=f"X:/synthetic/{study}/{folder}",
                 image_count=2, display_image_count=420, series_description="",
                 file_path="synthetic.png") for study, uid, key, folder in (
                     ("study-a", "series-a", "4", "4"),
                     ("study-a", "cine-a", "900001", "4__cine"),
                     ("study-b", "series-b", "4", "4"))]


def cards(widget):
    return [widget.content_grid.itemAt(i).widget() for i in range(widget.content_grid.count())
            if hasattr(widget.content_grid.itemAt(i).widget(), "image_button")]


@pytest.mark.parametrize("progressive", [False, True])
def test_card_double_click_emits_frozen_study_series_identity_not_ordinal(panel, progressive):
    widget, emitted, app = panel
    source = rows()
    if progressive:
        widget.display_thumbnails_progressively(source, widget._display_generation)
        widget._cancel_thumbnail_timer()
        for _ in widget.thumbnail_rows_to_display:
            widget.display_next_thumbnail()
    else:
        widget.display_thumbnails_immediately(source, widget._display_generation)
    built = cards(widget)
    assert len(built) == 3
    for index, card in enumerate(built):
        card.image_button.click()
        app.processEvents()
        assert len(emitted) == index
        QTest.mouseDClick(card.image_button, Qt.LeftButton)
        app.processEvents()
    assert len(emitted) == 3
    assert [(a.study_uid, a.series_uid, a.display_key, a.folder_key)
            for a in emitted] == [(r["study_uid"], r["series_uid"], r["display_key"], r["folder_key"])
                                  for r in source]
    with pytest.raises((AttributeError, TypeError)):
        emitted[0].study_uid = "changed"


def test_clear_rejects_already_queued_card_action(panel):
    widget, emitted, app = panel
    widget.display_thumbnails_immediately(rows(), widget._display_generation)
    QTest.mouseDClick(cards(widget)[0].image_button, Qt.LeftButton)
    widget.clear_content()
    app.processEvents()
    assert emitted == []


def test_home_handler_delegates_to_tab_service_without_legacy_download():
    path = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_on_right_panel_thumbnail_clicked")
    namespace = {"_print_logger": logging.getLogger(__name__), "print": lambda *a: None}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    seen = []
    action = action_for(rows()[2])
    async def route(a, opener, **kw):
        seen.append(a)
        await opener()
    opened = []
    async def open_patient(*args):
        opened.append(args)
    owner = SimpleNamespace(
        tab_service=SimpleNamespace(open_series_action=route),
        patient_table_widget=SimpleNamespace(results_table=SimpleNamespace(currentRow=lambda: 0),
            get_patient_data_by_row=lambda row: dict(patient_id='synthetic', patient_name='Synthetic', study_uid='study-b')),
        _is_active_patient_selection=lambda *a: True, source_of_patient_load='local',
        _schedule_ui_coro=lambda coro: asyncio.run(coro) or True,
        _on_patient_double_clicked_async=open_patient)
    namespace[method.name](owner, action)
    assert seen == [action]
    assert opened == [('synthetic', 'Synthetic', 'study-b', 'pending')]


def action_for(row):
    from PacsClient.utils.series_identity import SeriesActionIdentity
    return SeriesActionIdentity.from_metadata(row)


def make_service(entries):
    from PacsClient.pacs.workstation_ui.home_ui.home_tab_service import HomeTabService
    selected = []
    target = SimpleNamespace(study_uid="primary", _server_series_info=entries,
                             isVisible=lambda: True,
                             change_series_on_viewer=selected.append)
    tab = SimpleNamespace(count=lambda: 1, widget=lambda i: target,
                          indexOf=lambda w: 0 if w is target else -1, setCurrentIndex=lambda i: None)
    return HomeTabService(tab), target, selected


def test_destination_uses_own_key_and_keeps_exact_path():
    source = rows()[2]
    entry = dict(source, display_key="2000004", series_number="2000004")
    service, target, selected = make_service({"2000004": entry, "4": rows()[0]})
    assert service.show_series_action(action_for(source))
    assert selected == ["2000004"]
    assert target._server_series_info["2000004"] == entry


@pytest.mark.parametrize("entries", [
    {}, {"4": dict(rows()[2], study_uid="foreign")},
    {"4": dict(rows()[2], series_uid="foreign")},
    {"4": rows()[2], "5": rows()[2]}, {"4__cine": rows()[2]},
])
def test_missing_foreign_ambiguous_or_nonnumeric_target_fails_closed(entries):
    service, target, selected = make_service(entries)
    assert not service.show_series_action(action_for(rows()[2]))
    assert selected == []


def test_target_is_revalidated_after_tab_activation():
    service, target, selected = make_service({"4": rows()[2]})
    def activate(_):
        target._server_series_info = {"4": rows()[0]}
        return True
    service.activate_tab = activate
    assert not service.show_series_action(action_for(rows()[2]))
    assert selected == []


@pytest.mark.parametrize("changed", [
    {"series_uid": "replacement"}, {"display_key": "900009"},
    {"folder_key": "4__other"}, {"series_path": "X:/other"},
])
def test_same_png_cannot_coalesce_a_different_action_identity(changed):
    original = rows()[0]
    assert RightPanelWidget._thumbnail_render_signature([original]) != (
        RightPanelWidget._thumbnail_render_signature([dict(original, **changed)]))


def test_equivalent_metadata_still_coalesces():
    original = rows()[0]
    assert RightPanelWidget._thumbnail_render_signature([original]) == (
        RightPanelWidget._thumbnail_render_signature([dict(original, irrelevant="ignored")]))


@pytest.mark.parametrize('changed', [
    {'image_count': 25}, {'display_image_count': 421}, {'pixel_instance_count': 3},
    {'series_description': 'Updated description'}, {'modality': 'MR'},
    {'protocol_name': 'Updated protocol'}, {'body_part_examined': 'Updated anatomy'},
    {'study_label': 'Prior Study'},
])
def test_same_file_visual_metadata_refresh_is_not_coalesced(panel, changed):
    widget, _, app = panel
    original = rows()[0]
    widget.display_thumbnails([original], progressive=False)
    app.processEvents()
    generation = widget._display_generation
    widget.display_thumbnails([dict(original, **changed)], progressive=False)
    app.processEvents()
    assert widget._display_generation == generation + 1
    assert len(cards(widget)) == 1


def test_same_file_cine_count_refresh_changes_real_card_label(panel):
    from PySide6.QtWidgets import QLabel
    widget, _, app = panel
    original = dict(rows()[0], image_count=2, display_image_count=2)
    widget.display_thumbnails([original], progressive=False)
    app.processEvents()
    assert '2 images' in [label.text() for label in cards(widget)[0].findChildren(QLabel)]
    widget.display_thumbnails([dict(original, display_image_count=420)], progressive=False)
    app.processEvents()
    assert '420 images' in [label.text() for label in cards(widget)[0].findChildren(QLabel)]
    assert widget.extract_series_info_from_thumbnail(original)['image_count'] == 2


def test_equivalent_metadata_aliases_do_not_rebuild_cards(panel):
    widget, _, app = panel
    original = dict(rows()[0], modality='US', series_description='Description',
                    protocol_name='Protocol', body_part_examined='Anatomy')
    alias = dict(original)
    for canonical, alternate in [('image_count', 'ImageCount'), ('modality', 'Modality'),
                                  ('series_description', 'SeriesDescription'),
                                  ('protocol_name', 'ProtocolName'),
                                  ('body_part_examined', 'BodyPartExamined')]:
        alias[alternate] = alias.pop(canonical)
    widget.display_thumbnails([original], progressive=False)
    app.processEvents()
    generation = widget._display_generation
    card = cards(widget)[0]
    widget.display_thumbnails([alias], progressive=False)
    app.processEvents()
    assert widget._display_generation == generation
    assert cards(widget)[0] is card


def test_semantic_signature_never_reads_files_or_retains_pixel_payload(monkeypatch):
    import builtins
    import os
    def forbidden(*args, **kwargs):
        raise AssertionError('Signature must be metadata-only')
    row = dict(rows()[0], thumbnail_data=b'synthetic-pixel-payload', patient_name='Synthetic Patient')
    with monkeypatch.context() as scope:
        scope.setattr(builtins, 'open', forbidden)
        scope.setattr(os, 'stat', forbidden)
        signature = RightPanelWidget._thumbnail_render_signature([row])
    assert signature is not None
    assert 'synthetic-pixel-payload' not in repr(signature)
    assert 'Synthetic Patient' not in repr(signature)


def test_single_study_identity_does_not_add_a_raw_uid_header(panel):
    widget, _, _ = panel
    assert widget._build_grouped_thumbnail_rows([rows()[0]]) == [
        {'type': 'thumb', 'thumb': rows()[0]}]


def test_group_headers_use_labels_not_raw_uids(panel):
    widget, _, _ = panel
    grouped = widget._build_grouped_thumbnail_rows([rows()[0], rows()[2]])
    assert [row['title'] for row in grouped if row['type'] == 'header'] == ['Study 1', 'Study 2']
    explicit = widget._build_grouped_thumbnail_rows([dict(rows()[0], study_label='Prior Study')])
    assert explicit[0]['title'] == 'Prior Study'


def test_primary_bucket_fallback_and_leading_zero_key():
    entry = dict(rows()[0], series_number="02", display_key="02")
    service, target, selected = make_service({"02": {k: v for k, v in entry.items() if k != "study_uid"}})
    target.study_uid = "study-a"
    assert service.show_series_action(action_for(entry))
    assert selected == ["02"]


def test_duplicate_open_destinations_are_not_guessed():
    service, target, selected = make_service({"4": rows()[0]})
    other = SimpleNamespace(**vars(target))
    service.tab_widget.count = lambda: 2
    service.tab_widget.widget = lambda i: [target, other][i]
    assert not service.show_series_action(action_for(rows()[0]))
    assert selected == []


def test_incomplete_identity_does_not_emit_or_route(panel):
    widget, emitted, app = panel
    widget.display_thumbnails_immediately([dict(rows()[0], series_uid="")], widget._display_generation)
    QTest.mouseDClick(cards(widget)[0].image_button, Qt.LeftButton)
    app.processEvents()
    assert emitted == []
    service, target, selected = make_service({"4": rows()[0]})
    assert not service.show_series_action("4")
    assert selected == []


def test_superseded_render_cannot_dispatch_old_click(panel):
    widget, emitted, app = panel
    widget.display_thumbnails_immediately(rows(), widget._display_generation)
    QTest.mouseDClick(cards(widget)[0].image_button, Qt.LeftButton)
    widget.display_thumbnails([rows()[2]], progressive=False)
    app.processEvents()
    assert emitted == []


def test_closed_target_after_activation_is_not_used():
    service, target, selected = make_service({"4": rows()[0]})
    def activate(_):
        service.tab_widget.indexOf = lambda w: -1
        return True
    service.activate_tab = activate
    assert not service.show_series_action(action_for(rows()[0]))
    assert selected == []


def test_main_page_wires_only_the_identity_action_signal():
    source = (REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py").read_text(encoding="utf-8-sig")
    assert "seriesActionRequested.connect(self._on_right_panel_thumbnail_clicked)" in source
    assert "thumbnailClicked.connect(self._on_right_panel_thumbnail_clicked)" not in source
