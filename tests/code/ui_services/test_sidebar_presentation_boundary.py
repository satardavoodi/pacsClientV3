"""Synthetic sidebar ownership/layout guards; no live DB, network or images."""
import ast
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QLabel

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / 'PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core'


def method(file, name, **namespace):
    tree = ast.parse((CORE / file).read_text(encoding='utf-8-sig'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(Qt=Qt, Slot=Slot, Path=Path, **namespace)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(CORE/file), 'exec'), scope)
    return scope[name]


@pytest.mark.parametrize('kind', ['files', 'entries'])
@pytest.mark.parametrize('boundary', ['hint', 'grouped', 'retired', 'disposed'])
def test_late_single_study_delivery_cannot_rebuild_grouped_or_closed_sidebar(kind, boundary):
    calls = []
    owner = SimpleNamespace(_is_multistudy_hint=boundary == 'hint',
        _studies_series={'a': [], 'b': []} if boundary == 'grouped' else {},
        _pipeline_prepare_retired=boundary == 'retired',
        thumbnail_manager=SimpleNamespace(_disposed=boundary == 'disposed'),
        _log_open_thumbnail_trace=lambda *a, **k: None)
    setattr(owner, '_pending_thumbnails_'+kind, ['synthetic'])
    setattr(owner, '_render_thumbnails_from_'+kind, lambda items: calls.append(items))
    method('_pw_thumbnails.py', '_render_thumbnails_from_'+kind+'_slot')(owner)
    assert calls == []
    assert getattr(owner, '_pending_thumbnails_'+kind) is None


def test_single_study_delivery_still_reaches_existing_renderer():
    calls = []
    owner = SimpleNamespace(_pending_thumbnails_entries=['synthetic'],
        _log_open_thumbnail_trace=lambda *a, **k: None,
        _render_thumbnails_from_entries=lambda rows: calls.append(rows))
    method('_pw_thumbnails.py', '_render_thumbnails_from_entries_slot')(owner)
    assert calls == [['synthetic']]


@pytest.mark.parametrize('kind', ['files', 'entries'])
@pytest.mark.parametrize('retired', [False, True])
def test_explicit_grouped_failure_preserves_primary_fallback_unless_closed(kind, retired):
    calls = []
    owner = SimpleNamespace(_is_multistudy_hint=True,
        _studies_series={'a': [], 'b': []}, _pipeline_prepare_retired=retired,
        _multistudy_thumbnail_fallback=True,
        _log_open_thumbnail_trace=lambda *a, **k: None)
    setattr(owner, '_pending_thumbnails_'+kind, ['synthetic'])
    setattr(owner, '_render_thumbnails_from_'+kind, lambda rows: calls.append(rows))
    method('_pw_thumbnails.py', '_render_thumbnails_from_'+kind+'_slot')(owner)
    assert calls == ([] if retired else [['synthetic']])


def test_grouped_failure_handoff_is_explicit_and_success_reclaims_ownership():
    calls = []
    owner = SimpleNamespace(_sidebar_build_token=7, logger=logging.getLogger(__name__),
        _start_sidebar_build=lambda **kwargs: False)  # Explicit no-loop compatibility path.
    render = method('_pw_thumbnails.py', '_render_multistudy_grouped', os=__import__('os'),
        check_and_get_thumbnails=lambda *a: ['1.png'],
        QMetaObject=SimpleNamespace(invokeMethod=lambda *a: calls.append('fallback')))
    assert not render(owner)
    assert owner._multistudy_thumbnail_fallback is True
    owner._multistudy_viewer_groups = [('synthetic', 0, [('1', {'_orig_series_number':'1'})])]
    owner.import_folder_path = 'synthetic'
    owner.thumb_grid = SimpleNamespace(parentWidget=lambda: None, count=lambda: 0)
    owner._make_study_header_widget = lambda *a: None
    owner.add_thumbnail_to_thumbnail_layout = lambda **k: k['thumb_index']+1
    owner._log_open_thumbnail_trace = lambda *a, **k: None
    assert render(owner)
    assert owner._multistudy_thumbnail_fallback is False
    assert owner._sidebar_build_token > 7
    assert calls == ['fallback']


def test_local_terminal_does_not_move_already_visible_cards():
    from queue import Queue
    from time import perf_counter
    mailbox = Queue()
    mailbox.put(('done', None, None, None))
    moves = []
    owner = SimpleNamespace(study_uid='synthetic-study',
        _local_thumbnail_workflow=lambda: True,
        _server_series_info={'2': {'series_number': '2'}, '1': {'series_number': '1'}},
        thumbnail_manager=SimpleNamespace(series_widgets={'2': object(), '1': object()}),
        thumb_grid=SimpleNamespace(addWidget=lambda *a: moves.append(a), activate=lambda: None),
        logger=logging.getLogger(__name__),
        _log_open_thumbnail_trace=lambda *a, **k: None)
    owner._local_thumbnail_stream = dict(study_uid=owner.study_uid, mailbox=mailbox,
        started=perf_counter(), delivered=2)
    owner._retire_local_thumbnail_stream = lambda: setattr(owner, '_local_thumbnail_stream', None)
    method('_pw_thumbnails.py', '_drain_local_thumbnail_stream',
           _history_first_enabled=lambda: False, series_is_clinical_history=lambda s: False)(owner)
    assert moves == [], 'Terminal completion must not reorder visible cards'


def test_card_commit_positions_before_paint_and_counts_cards_not_header_rows():
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    grid = QGridLayout(container)
    grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    grid.setVerticalSpacing(6)
    header = QLabel('Synthetic study header')
    grid.addWidget(header, 0, 0, 1, 2)
    count = QLabel()
    observed = []
    manager = SimpleNamespace(lst_buttons_name=[], series_widgets={},
                             set_series_pending=lambda key: None, set_series_ready=lambda key: None)
    def create(**kwargs):
        observed.append(container.updatesEnabled())
        card = QWidget()
        card.setMinimumSize(190, 215)
        card.setMaximumSize(190, 215)
        key = kwargs['label_text']
        manager.series_widgets[key] = card
        manager.lst_buttons_name.append(key)
        return card
    manager.create_thumbnail_widget = create
    owner = SimpleNamespace(thumbnail_manager=manager, thumb_grid=grid, thumb_count_label=count,
        _thumbnail_image_source_service=SimpleNamespace(load_pixmap=lambda *a: QPixmap(8,8)))
    add = method('_pw_panels.py', 'add_thumbnail_to_thumbnail_layout')
    container.resize(240, 800)
    container.show()
    app.processEvents()
    try:
        for row in (1, 2):
            add(owner, row, 'synthetic.png', str(row), series_info={'series_number': str(row)})
            card = manager.series_widgets[str(row)]
            assert card.parentWidget() is container
            assert card.geometry().top() > header.geometry().bottom()
        first, second = manager.series_widgets.values()
        assert not first.geometry().intersects(second.geometry())
        assert first.height() == second.height() == 215
        assert observed == [False, False], 'Do not paint a partially placed card'
        assert count.text() == '2 series'
        assert container.updatesEnabled()
    finally:
        container.close()
        container.deleteLater()
        count.deleteLater()


@pytest.mark.parametrize('paint_enabled', [False, True])
@pytest.mark.parametrize('fail', [False, True])
def test_card_commit_preserves_outer_paint_suppression_even_on_failure(paint_enabled, fail):
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    grid = QGridLayout(container)
    count = QLabel()
    manager = SimpleNamespace(lst_buttons_name=[], series_widgets={},
        set_series_pending=lambda *a: None)
    def create(**kwargs):
        assert not container.updatesEnabled()
        if fail:
            raise RuntimeError('Synthetic constructor failure')
        card = QWidget()
        manager.series_widgets['1'] = card
        return card
    manager.create_thumbnail_widget = create
    owner = SimpleNamespace(thumbnail_manager=manager, thumb_grid=grid, thumb_count_label=count,
        _thumbnail_image_source_service=SimpleNamespace(load_pixmap=lambda *a: QPixmap(8,8)))
    container.setUpdatesEnabled(paint_enabled)
    add = method('_pw_panels.py', 'add_thumbnail_to_thumbnail_layout')
    try:
        if fail:
            with pytest.raises(RuntimeError, match='Synthetic'):
                add(owner, 0, 'synthetic.png', '1', series_info={'series_number':'1'})
        else:
            add(owner, 0, 'synthetic.png', '1', series_info={'series_number':'1'})
        assert container.updatesEnabled() == paint_enabled
    finally:
        container.deleteLater()
        count.deleteLater()


def test_grouped_clear_keeps_retiring_cards_parented_and_hidden():
    app = QApplication.instance() or QApplication([])
    container = QWidget()
    grid = QGridLayout(container)
    old = QWidget(container)
    grid.addWidget(old, 0, 0)
    container.show()
    app.processEvents()
    manager = SimpleNamespace(series_widgets={'1': old}, lst_buttons_name=['1'],
        ready_series=set(), buttons=[], _cancel_deferred_work=lambda: None,
        _retire_card_effects=lambda: None)
    owner = SimpleNamespace(thumb_grid=grid, thumbnail_manager=manager,
        _start_sidebar_build=lambda **kwargs: False,
        _multistudy_viewer_groups=[('a', 0, [])], import_folder_path='synthetic',
        _get_correct_study_path=lambda: '', logger=logging.getLogger(__name__))
    try:
        method('_pw_thumbnails.py', '_render_multistudy_grouped',
               os=__import__('os'), check_and_get_thumbnails=lambda *a: [],
               QMetaObject=SimpleNamespace(invokeMethod=lambda *a: None))(owner)
        assert old.parentWidget() is container, 'Do not create a retiring top-level card'
        assert old.isHidden()
    finally:
        container.close()
        container.deleteLater()


@pytest.mark.parametrize('retired,disposed', [(True,False), (False,True)])
def test_late_grouped_prefetch_does_not_touch_retired_sidebar(retired, disposed):
    calls = []
    manager = SimpleNamespace(_disposed=disposed,
        _cancel_deferred_work=lambda: calls.append('cancel'),
        _retire_card_effects=lambda: calls.append('effects'))
    owner = SimpleNamespace(_pipeline_prepare_retired=retired, thumbnail_manager=manager,
        _multistudy_viewer_groups=[('synthetic',0,[])], import_folder_path='synthetic',
        logger=logging.getLogger(__name__))
    method('_pw_thumbnails.py', '_render_multistudy_grouped', os=__import__('os'),
           check_and_get_thumbnails=lambda *a: calls.append('disk'),
           QMetaObject=SimpleNamespace(invokeMethod=lambda *a: calls.append('fallback')))(owner)
    assert calls == []


@pytest.mark.parametrize('boundary', ['hint', 'grouped', 'retired', 'disposed'])
def test_queued_file_chunk_stops_when_sidebar_ownership_changes(boundary):
    calls = []
    owner = SimpleNamespace(_sidebar_build_token=1,
        _is_multistudy_hint=boundary=='hint',
        _studies_series={'a': [], 'b': []} if boundary=='grouped' else {},
        _pipeline_prepare_retired=boundary=='retired',
        thumbnail_manager=SimpleNamespace(_disposed=boundary=='disposed'),
        _render_one_thumbnail_file=lambda *a: calls.append(a))
    method('_pw_thumbnails.py', '_render_files_chunked', os=__import__('os'))(
        owner, ['synthetic.png'], 0, 0, '', 1)
    assert calls == []


def test_explicit_primary_fallback_still_renders_file_chunks():
    calls = []
    owner = SimpleNamespace(_sidebar_build_token=2, _is_multistudy_hint=True,
        _multistudy_thumbnail_fallback=True, thumb_grid=SimpleNamespace(parentWidget=lambda: None),
        _render_one_thumbnail_file=lambda *a: calls.append(a) or 1)
    render = method('_pw_thumbnails.py', '_render_files_chunked', os=__import__('os'))
    render(owner, ['synthetic.png'], 0, 0, '', 1)
    assert calls == [], 'A previous fallback generation must remain cancelled'
    render(owner, ['synthetic.png'], 0, 0, '', 2)
    assert len(calls) == 1


def test_many_real_cards_keep_positions_labels_scroll_and_native_parent():
    from PySide6.QtWidgets import QScrollArea
    from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.resize(250, 700)
    container = QWidget()
    grid = QGridLayout(container)
    grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    grid.setVerticalSpacing(6)
    scroll.setWidget(container)
    count = QLabel()
    manager = ThumbnailManager(lambda *a: None)
    owner = SimpleNamespace(thumbnail_manager=manager, thumb_grid=grid, thumb_count_label=count,
        _thumbnail_image_source_service=SimpleNamespace(load_pixmap=lambda *a: QPixmap(8,8)))
    add = method('_pw_panels.py', 'add_thumbnail_to_thumbnail_layout')
    scroll.show()
    app.processEvents()
    positions, labels = {}, {}
    try:
        for row in range(32):
            before_scroll = scroll.verticalScrollBar().value()
            key = str(row+1)
            add(owner, row, 'synthetic.png', key, series_info={
                'series_number': key, 'series_uid': 'synthetic-'+key,
                'study_uid': 'synthetic-study', 'image_count': 2,
                'display_image_count': 420, 'series_description': 'Same description'})
            app.processEvents()
            for old_key, rect in positions.items():
                card = manager.series_widgets[old_key]
                assert card.geometry() == rect
                assert [label.text() for label in card.findChildren(QLabel)] == labels[old_key]
            card = manager.series_widgets[key]
            assert card.parentWidget() is container and not card.isWindow()
            assert (card.width(), card.height()) == (190,215)
            assert card.count_label.text() == '420 images'
            rect = card.geometry()
            assert all(not rect.intersects(old) for old in positions.values())
            positions[key] = rect
            labels[key] = [label.text() for label in card.findChildren(QLabel)]
            assert scroll.verticalScrollBar().value() == before_scroll
            assert count.text() == f'{row+1} series'
            if row == 12:
                scroll.verticalScrollBar().setValue(200)
    finally:
        manager.dispose()
        scroll.close()
        scroll.deleteLater()
        count.deleteLater()


@pytest.mark.parametrize('long_header', [False, True])
@pytest.mark.parametrize('study_count', [2, 4])
def test_grouped_headers_have_final_geometry_before_paint(long_header, study_count):
    from PySide6.QtWidgets import QScrollArea
    from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.resize(240, 700)
    container = QWidget()
    grid = QGridLayout(container)
    grid.setContentsMargins(8, 6, 14, 6)
    grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    grid.setVerticalSpacing(6)
    scroll.setWidget(container)
    count = QLabel()
    manager = ThumbnailManager(lambda *a: None)
    study_uids = ['synthetic-'+str(n) for n in range(study_count)]
    groups = [(su, slot, [(str(slot*1000000+1), {'_orig_series_number':'1',
               'series_number':str(slot*1000000+1), 'study_uid':su,
               'series_uid':'synthetic-series-'+su, 'image_count':25})])
              for slot, su in enumerate(study_uids)]
    owner = SimpleNamespace(study_uid=study_uids[0], _multistudy_viewer_groups=groups,
        _start_sidebar_build=lambda **kwargs: False,
        _studies_series={su:[{'body_part_examined':
            'Synthetic long multi-region examination label' if long_header else 'Synthetic'}]
            for su in study_uids},
        thumbnail_manager=manager, thumb_grid=grid, thumb_count_label=count,
        import_folder_path='synthetic', logger=logging.getLogger(__name__),
        _get_correct_study_path=lambda: '', _is_series_downloaded=lambda *a, **k: False,
        _is_sanctioned_previous_exam=lambda su: su!=study_uids[0],
        _previous_exam_set=SimpleNamespace(study=lambda su: SimpleNamespace(patient_id='SYNTHETIC ID')),
        _study_date_display=lambda su: '2020-01-01',
        _log_open_thumbnail_trace=lambda *a, **k: None,
        _thumbnail_image_source_service=SimpleNamespace(load_pixmap=lambda *a: QPixmap(8,8)))
    make_header = method('_pw_thumbnails.py', '_make_study_header_widget')
    owner._make_study_header_widget = lambda *a: make_header(owner,*a)
    add = method('_pw_panels.py', 'add_thumbnail_to_thumbnail_layout')
    owner.add_thumbnail_to_thumbnail_layout = lambda **k: add(owner,**k)
    render = method('_pw_thumbnails.py', '_render_multistudy_grouped', os=__import__('os'),
        check_and_get_thumbnails=lambda *a: ['1.png'])
    scroll.show()
    app.processEvents()
    try:
        assert render(owner)
        widgets = [grid.itemAt(i).widget() for i in range(grid.count())]
        positions = [w.geometry() for w in widgets]
        before_size = container.size()
        app.processEvents()
        assert [w.geometry() for w in widgets] == positions, {
            'before': [r.getRect() for r in positions],
            'after': [w.geometry().getRect() for w in widgets],
            'container_before': (before_size.width(),before_size.height()),
            'container_after': (container.width(),container.height()),
        }
        assert all(not w.isHidden() for w in widgets)
        for header, card in zip(widgets[::2], widgets[1::2]):
            assert header.geometry().bottom() < card.geometry().top()
            assert header.width() == card.width() == 190
        assert count.text() == f'{study_count} series'
    finally:
        manager.dispose()
        scroll.close()
        scroll.deleteLater()
        count.deleteLater()
