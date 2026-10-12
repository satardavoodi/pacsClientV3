"""Synthetic exact-study reopening; never submit a replacement AI job."""
import json
from types import SimpleNamespace
import pytest
from test_eagle_eye_total_spine import qapp, view


def saved_candidate(image):
    from modules.ai_imaging.eagle_eye_total_spine.assist_service import image_binding
    return dict(server_module='total-spine', analysis_study_uid='1.2.3',
                server_job_id='synthetic-job', binding=image_binding(image),
                source_binding=[dict(image['identity'], sha256=image['source_sha256'])],
                region=[30, 30, 450, 900],
                candidates=[dict(corners=[[100, 100], [200, 100], [100, 150], [200, 150]])])


def test_detection_without_pdf_is_discovered_on_reopen(tmp_path):
    from modules.ai_imaging.eagle_eye_saved_results import discover
    result = saved_candidate(view()['image'])
    result['artifact_directory'] = str(tmp_path)
    (tmp_path / 'result.json').write_text(json.dumps(result))
    rows = discover(tmp_path, '1.2.3')
    assert len(rows) == 1
    assert rows[0]['module'] == 'total-spine'
    assert rows[0]['pdf'] is None
    assert discover(tmp_path, '1.2.9') == []


def test_saved_detection_opens_native_tab_without_function(monkeypatch, qapp):
    from PySide6.QtWidgets import QWidget, QTabWidget
    from modules.ai_imaging import eagle_eye_saved_results as saved
    from modules.ai_imaging.eagle_eye_result_tabs import AnalysisResultTabs
    monkeypatch.setattr(saved, 'discover_workspace', lambda *args: [])
    host = QWidget(); host._study_uid = '1.2.3'
    host.tab_widget = QTabWidget(host); host.imaging_tab = QWidget(host)
    host.tab_widget.addTab(host.imaging_tab, 'Imaging Tools')
    opened = []
    def open_spine(**kwargs):
        opened.append(kwargs)
        host.tab_widget.addTab(QWidget(host), 'Total Spine Alignment')
    host.workspace_controller = SimpleNamespace(open_total_spine=open_spine)
    manager = AnalysisResultTabs(host)
    result = saved_candidate(view()['image'])
    row = dict(module='total-spine', result=result, content='', report='', pdf=None)
    manager._add_saved_rows([row]); manager._add_saved_rows([row])
    assert opened == [dict(saved_result=result)]
    assert host.tab_widget.currentWidget() is host.imaging_tab
    manager._dispose(); host.close()


def test_restoration_checks_identity_before_reading_images(monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine import saved_review
    from modules.ai_imaging.eagle_eye_total_spine import service
    monkeypatch.setattr(service, 'study_images', lambda *_: pytest.fail('Wrong-study inventory read'))
    with pytest.raises(ValueError):
        saved_review.prepare(saved_candidate(view()['image']), '1.2.9')


def test_worker_restores_bound_candidates_without_inference(monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine import saved_review, service
    import pydicom
    image = view()['image']
    monkeypatch.setattr(service, 'study_images', lambda *_: [dict(path='synthetic.dcm', series_uid='1.2.3.1')])
    monkeypatch.setattr(pydicom, 'dcmread', lambda *a, **k: {'SOPInstanceUID':'1.2.3.1.1'})
    monkeypatch.setattr(service, 'load_view', lambda *args: image)
    monkeypatch.setattr(service, 'predict', lambda *a, **k: pytest.fail('Reopening submitted inference'))
    result = saved_candidate(image)
    restored = saved_review.prepare(result, '1.2.3')
    assert restored['views'][0]['image'] is image
    assert restored['views'][0]['candidates'] == result['candidates']
    result['source_binding'][0]['sha256'] = 'changed'
    with pytest.raises(ValueError):
        saved_review.prepare(result, '1.2.3')


def test_native_restoration_applies_in_worker_without_starting_ai(monkeypatch, qapp):
    import pydicom
    import threading
    from modules.ai_imaging.eagle_eye_total_spine import service
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    image = view()['image']; main_thread = threading.get_ident(); threads = []
    def inventory(study):
        threads.append(threading.get_ident())
        return [dict(path='synthetic.dcm', series_uid='1.2.3.1')]
    monkeypatch.setattr(service, 'study_images', inventory)
    monkeypatch.setattr(service, 'load_view', lambda *args: image)
    monkeypatch.setattr(pydicom, 'dcmread', lambda *a, **k: {'SOPInstanceUID':'1.2.3.1.1'})
    monkeypatch.setattr(service, 'predict', lambda *a, **k: pytest.fail('Reopening submitted inference'))
    widget = TotalSpineWidget(study_uid='1.2.3')
    widget.restore_saved_result(saved_candidate(image))
    widget._future.result(timeout=3); widget._poll()
    assert threads and main_thread not in threads
    assert widget.editors[0].image is image
    assert len(widget.editors[0].candidates) == 1
    assert widget.editors[0].region == [30, 30, 450, 900]
    assert widget._future is None and not widget._automatic
    assert 'No new analysis' in widget.status.text()
    widget.teardown(); widget.close()


def test_server_report_retains_editable_geometry(monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_remote import spine_review
    from modules.ai_imaging.eagle_eye_total_spine import service, report
    from test_remote_review_modules import spine_snapshot, request
    image = view()['image']
    image['radiograph_binding'] = {'version': 1, 'sha256': 'a'*64}
    snapshot = spine_snapshot()
    req = request('total-spine', dict(parent_job_id=None, views=[snapshot], reviewed=False, notes='Saved note'))
    image['identity'] = dict(image['identity'], study_uid=req['study_uid'], **req['series']['primary'])
    monkeypatch.setattr(service, 'load_view', lambda *args: image)
    monkeypatch.setattr(report, 'generate_report', lambda *a, **k: {'artifact_directory':str(tmp_path)})
    records = [dict(path='synthetic.dcm', **req['series']['primary'])]
    result = spine_review.calculate(req, records, tmp_path)
    assert result['review_views'][0]['points'] == snapshot['points']
    assert 'pixels' not in result['review_views'][0]['image']
    assert result['notes'] == 'Saved note'


def test_server_reopen_discovers_files_off_gui_thread(monkeypatch, tmp_path, qapp):
    import threading
    from PySide6.QtWidgets import QWidget, QTabWidget
    from modules.ai_imaging import eagle_eye_saved_results as saved
    from modules.ai_imaging.eagle_eye_result_tabs import AnalysisResultTabs
    from modules.ai_imaging.eagle_eye_remote import case_ui
    monkeypatch.setattr(case_ui, 'require_current_source', lambda *_: None)
    main_thread = threading.get_ident(); calls = []
    def discover(*args):
        calls.append(threading.get_ident())
        assert calls[-1] != main_thread, 'Saved-result filesystem work ran on the GUI thread'
        return []
    monkeypatch.setattr(saved, 'discover_workspace', discover)
    connection = SimpleNamespace(saved_analysis=lambda *a, **k: {'artifact_directory':str(tmp_path)})
    host = QWidget(); host._study_uid = '1.2.3'; host.tab_widget = QTabWidget(host)
    host.imaging_tab = QWidget(host)
    host.imaging_tab.patient_widget = SimpleNamespace(_case_realtime=SimpleNamespace(
        reference={'study_uid':'1.2.3'}, snapshot={'eagle_eye':[{'job_id':'synthetic-job'}]},
        receiver=SimpleNamespace(connection=connection)))
    manager = AnalysisResultTabs(host)
    manager._saved_future.result(timeout=3)
    manager._poll_server_saved_result()
    manager._server_future.result(timeout=3)
    manager._poll_server_saved_result()
    assert len(calls) == 2
    manager._dispose(); host.close()


def test_saved_report_restores_both_projections_and_measurements(monkeypatch, qapp):
    from copy import deepcopy
    import pydicom
    from modules.ai_imaging.eagle_eye_total_spine import saved_review, service
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    first, second = view(), view('lateral')
    second['image']['identity']['series_uid'] = '1.2.3.2'
    second['image']['identity']['sop_uid'] = '1.2.3.2.1'
    first['pedicles'] = {'T8': {'image_left':[290, 402], 'image_right':[310, 402]}}
    images = {'coronal.dcm':first['image'], 'lateral.dcm':second['image']}
    rows = [dict(path=path, series_uid=image['identity']['series_uid']) for path, image in images.items()]
    monkeypatch.setattr(service, 'study_images', lambda *_: rows)
    monkeypatch.setattr(service, 'load_view', lambda path, *a: images[path])
    monkeypatch.setattr(pydicom, 'dcmread', lambda path, **k: {'SOPInstanceUID':images[path]['identity']['sop_uid']})
    snapshots = []
    for original in (first, second):
        state = deepcopy({k:v for k,v in original.items() if k != 'image'})
        state['image'] = {k:v for k,v in original['image'].items() if k != 'pixels'}
        snapshots.append(state)
    result = dict(server_module='total-spine', analysis_study_uid='1.2.3', server_job_id='synthetic-report',
                  review_views=snapshots, notes='Saved impression',
                  source_binding=[dict(image['identity'], sha256=image['source_sha256']) for image in images.values()])
    prepared = saved_review.prepare(result, '1.2.3')
    widget = TotalSpineWidget(study_uid='1.2.3'); widget._apply_saved_review(prepared)
    assert [e.image['projection'] for e in widget.editors] == ['coronal', 'lateral']
    assert widget.editors[0].pedicles == first['pedicles']
    assert all(e.table.rowCount() == 1 for e in widget.editors)
    assert widget.notes.text() == 'Saved impression'
    assert widget.report_result['server_job_id'] == 'synthetic-report'
    assert all(not e.review.isChecked() for e in widget.editors)
    widget.teardown(); widget.close()


def test_missing_original_never_guesses_another_source(monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine import saved_review, service
    monkeypatch.setattr(service, 'study_images', lambda *_: [])
    with pytest.raises(ValueError, match='not available locally'):
        saved_review.prepare(saved_candidate(view()['image']), '1.2.3')


def test_workspace_recovery_never_opens_input_selector_or_steals_focus(monkeypatch, qapp):
    from PySide6.QtWidgets import QWidget, QTabWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_total_spine import saved_review
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    data = view(); data.update(pedicles={}, candidates=[], region=None)
    prepared = dict(views=[data], notes='', report_result=None,
                    provenance={}, parent_job_id='synthetic-job')
    monkeypatch.setattr(saved_review, 'prepare', lambda *a: prepared)
    monkeypatch.setattr(TotalSpineWidget, 'begin_automatic', lambda *a, **k: pytest.fail('Input selector opened'))
    host = QWidget(); host._study_uid = '1.2.3'; host.eagle_eye_mode = None
    host.imaging_tab = SimpleNamespace(patient_widget=None)
    host.tab_widget = QTabWidget(host); original = QWidget(host)
    host.tab_widget.addTab(original, 'Imaging Tools')
    controller = EagleEyeWorkspaceController(host)
    controller.open_total_spine(saved_result=saved_candidate(data['image']))
    widget = controller._total_spine_widget
    assert host.tab_widget.indexOf(widget) >= 0
    assert host.tab_widget.currentWidget() is original
    widget._future.result(timeout=3); widget._poll()
    assert host.tab_widget.currentWidget() is original
    assert widget.editors[0].table.rowCount() == 1
    controller.teardown(); host.close()
