"""Saved result discovery must be exact-study, complete and module-specific."""
import json


def test_report_reader_is_legible_under_dark_application_theme():
    from PySide6.QtWidgets import QApplication, QTextBrowser
    from PySide6.QtGui import QPalette, QColor
    from modules.ai_imaging import eagle_eye_result_tabs
    configure_report_reader = getattr(eagle_eye_result_tabs, "configure_report_reader", lambda browser: None)
    app = QApplication.instance() or QApplication([])
    browser = QTextBrowser()
    dark = browser.palette(); dark.setColor(QPalette.Base, QColor('#0d1520'))
    browser.setPalette(dark)
    browser.setHtml('<h1>Brainstem</h1><p style="font-size:8pt;color:#203e50">'
                    'Measured 23.290 cm3</p><p style="color:#ff0000">Flagged value</p>')
    before = browser.toPlainText()
    configure_report_reader(browser)
    assert browser.palette().color(QPalette.Base) == QColor('#ffffff')
    assert browser.toPlainText() == before
    assert browser.document().documentMargin() >= 20
    block = browser.document().begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            assert it.fragment().charFormat().fontPointSize() >= 11
            it += 1
        block = block.next()
    assert browser.find('Flagged value')
    assert browser.textCursor().charFormat().foreground().color() == QColor('#ff0000')
    browser.close()


def test_legacy_brain_results_restore_as_two_distinct_modules(tmp_path):
    from modules.ai_imaging.eagle_eye_saved_results import discover
    for name, fields in [('volume', {'posterior_rows': []}),
                         ('lesions', {'analysis_type': 'brain_lesions'})]:
        directory = tmp_path / name
        directory.mkdir()
        (directory / 'report.pdf').write_bytes(b'synthetic')
        (directory / 'result.json').write_text(json.dumps(dict(
            artifact_directory=str(directory), analysis_study_uid='1.2.3', **fields)))
    assert {row['module'] for row in discover(tmp_path, '1.2.3')} == {'brain', 'brain-lesions'}
    assert discover(tmp_path, '1.2.4') == []


def test_brain_tabs_activate_on_open_and_keep_correction_access(monkeypatch):
    from concurrent.futures import Future
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication, QWidget, QTabWidget, QPushButton
    from modules.ai_imaging import eagle_eye_saved_results as saved
    from modules.ai_imaging.eagle_eye_result_tabs import AnalysisResultTabs
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(saved, 'discover_workspace', lambda *a: [])
    opened = []
    host = QWidget(); host._study_uid = '1.2.3'
    host.tab_widget = QTabWidget(host)
    host.imaging_tab = QWidget(); host.tab_widget.addTab(host.imaging_tab, 'Imaging Tools')
    host.workspace_controller = SimpleNamespace(open_saved_brain_result=opened.append)
    tabs = AnalysisResultTabs(host)
    future = Future(); future.set_result([
        dict(module=module, result={'marker': module}, content='<h1>Global volumes</h1><h1>Brainstem</h1>', report='', pdf=None)
        for module in ('brain', 'brain-lesions')])
    tabs._saved_future = future
    tabs._restore_saved()
    assert host.tab_widget.count() == 3
    from PySide6.QtWidgets import QComboBox
    card = tabs.pages['saved-brain'].findChild(QWidget, 'savedReportCard')
    assert card is not None and card.maximumWidth() == 1120
    sections = card.findChild(QComboBox, 'reportSectionNavigation')
    assert [sections.itemText(i) for i in range(sections.count())] == ['Global volumes', 'Brainstem']
    assert host.tab_widget.currentWidget() is tabs.pages['saved-brain']
    for module in ('brain', 'brain-lesions'):
        button = tabs.pages['saved-' + module].findChild(QPushButton, 'savedBrainCorrection')
        assert button is not None
        button.click()
    assert opened == [{'marker': 'brain'}, {'marker': 'brain-lesions'}]
    host.tab_widget.setCurrentWidget(tabs.pages['saved-brain-lesions'])
    tabs._restore_saved()
    assert host.tab_widget.count() == 3
    assert host.tab_widget.currentWidget() is tabs.pages['saved-brain-lesions']
    tabs._saved_executor.shutdown(wait=True); host.close()


def test_discover_latest_complete_result_per_module(tmp_path):
    from modules.ai_imaging.eagle_eye_saved_results import discover
    for name, module, study in [('one','lumbar-marrow','1.2.3'),('two','alignment','1.2.3'),('other','lumbar-marrow','1.2.9')]:
        root = tmp_path/name; root.mkdir()
        (root/'report.html').write_text('<h1>Synthetic</h1>')
        (root/'result.json').write_text(json.dumps(dict(server_module=module,analysis_study_uid=study,
           artifact_directory=str(root),report_html=str(root/'report.html'))))
    rows = discover(tmp_path, '1.2.3')
    assert {row['module'] for row in rows} == {'lumbar-marrow','alignment'}
    assert all(row['result']['analysis_study_uid']=='1.2.3' for row in rows)
    (tmp_path/'one'/'report.html').unlink()
    assert [row['module'] for row in discover(tmp_path,'1.2.3')] == ['alignment']


def test_workspace_restores_named_tabs_without_loading_or_analysis(monkeypatch):
    from concurrent.futures import Future
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication, QWidget, QTabWidget
    from modules.ai_imaging import eagle_eye_saved_results as saved
    from modules.ai_imaging.lumbar_marrow_widget import LumbarMarrowWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_result_tabs import AnalysisResultTabs
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(saved, 'discover_workspace', lambda *a: [])
    monkeypatch.setattr(LumbarMarrowWidget, 'load_series', lambda *a: (_ for _ in ()).throw(AssertionError('Restoration cannot load new inputs')))
    host = QWidget(); host._study_uid = '1.2.3'; host.eagle_eye_mode = None
    host.tab_widget = QTabWidget(host); original = QWidget(); host.tab_widget.addTab(original,'Imaging Tools')
    host.imaging_tab = SimpleNamespace(patient_widget=None)
    host.workspace_controller = EagleEyeWorkspaceController(host)
    tabs = AnalysisResultTabs(host)
    future = Future(); future.set_result([
        dict(module='lumbar-marrow',result={'analysis_study_uid':'1.2.3'},content='',report='/synthetic/report.html',pdf=None),
        dict(module='alignment',result={},content='<h1>Saved alignment</h1>',report='/synthetic/report.html',pdf=None)])
    tabs._saved_future = future
    tabs._restore_saved(); tabs._restore_saved()
    assert host.tab_widget.count() == 3
    assert {host.tab_widget.tabText(i) for i in range(3)} == {'Imaging Tools','Lumbar Bone Marrow','Lower Limb Alignment'}
    assert host.tab_widget.currentWidget() is original
    assert host.workspace_controller._marrow_widget._future is None
    host.workspace_controller.teardown(); host.close()


import pytest


def test_completed_lumbar_session_is_discovered_for_the_exact_study(tmp_path):
    from modules.ai_imaging.eagle_eye_saved_results import discover_lumbar

    session = tmp_path / "synthetic-session"
    session.mkdir()
    (session / "session.json").write_text(json.dumps({
        "session_kind": "lumbar_mri",
        "study_instance_uid": "1.2.3",
    }))
    (session / "llm_result.json").write_text(json.dumps({
        "state": "complete",
        "pipeline_version": "8.7.0",
        "completed_at": "2026-10-10T17:28:18+00:00",
        "result_file": "llm_result.txt",
    }))
    (session / "llm_result.txt").write_text(
        "PATHOLOGICAL FINDINGS\n  Synthetic finding.", encoding="utf-8"
    )

    rows = discover_lumbar(tmp_path, "1.2.3")

    assert len(rows) == 1
    assert rows[0]["module"] == "lumbar"
    assert rows[0]["record"].has_result is True
    assert discover_lumbar(tmp_path, "1.2.4") == []


def test_incomplete_or_failed_lumbar_sessions_do_not_create_result_tabs(tmp_path):
    from modules.ai_imaging.eagle_eye_saved_results import discover_lumbar

    for name, state in (("running", "analyzing"), ("failed", "failed")):
        session = tmp_path / name
        session.mkdir()
        (session / "session.json").write_text(json.dumps({
            "session_kind": "lumbar_mri",
            "study_instance_uid": "1.2.3",
        }))
        (session / "llm_result.json").write_text(json.dumps({"state": state}))

    assert discover_lumbar(tmp_path, "1.2.3") == []


def test_workspace_retrieves_existing_server_result_without_submitting_analysis(
        tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication, QWidget, QTabWidget
    from modules.ai_imaging import eagle_eye_saved_results as saved
    from modules.ai_imaging.eagle_eye_result_tabs import AnalysisResultTabs

    QApplication.instance() or QApplication([])
    real_discover = saved.discover_workspace
    monkeypatch.setattr(saved, 'discover_workspace', lambda *args: [])
    calls = []

    class Connection:
        case_profile_id = None

        def saved_analysis(self, reference, job_id, destination, *, cancel=None):
            calls.append(('saved_analysis', dict(reference), job_id))
            session = tmp_path / 'downloaded-result'
            session.mkdir(exist_ok=True)
            (session / 'session.json').write_text(json.dumps({
                'session_kind': 'lumbar_mri',
                'study_instance_uid': reference['study_uid'],
            }))
            (session / 'llm_result.json').write_text(json.dumps({
                'state': 'complete',
                'result_file': 'llm_result.txt',
                'completed_at': '2026-10-10T17:28:18+00:00',
            }))
            (session / 'llm_result.txt').write_text('Synthetic server result')
            return {'artifact_directory': str(session), 'server_module': 'lumbar'}

    connection = Connection()
    host = QWidget()
    host._study_uid = '1.2.3'
    host.tab_widget = QTabWidget(host)
    patient = SimpleNamespace(_case_realtime=SimpleNamespace(
        snapshot={'eagle_eye': [{
            'job_id': 'a' * 32,
            'module': 'lumbar',
            'status': 'succeeded',
        }]},
        reference={'study_uid': '1.2.3', 'patient_id': 'synthetic-person'},
        receiver=SimpleNamespace(connection=connection),
    ))
    host.imaging_tab = QWidget()
    host.imaging_tab.patient_widget = patient
    host.tab_widget.addTab(host.imaging_tab, 'Imaging Tools')
    tabs = AnalysisResultTabs(host)
    tabs._attachment_root = tmp_path
    tabs._saved_future.result()
    monkeypatch.setattr(saved, 'discover_workspace', real_discover)

    tabs._poll_server_saved_result()
    tabs._server_future.result(timeout=3)
    tabs._poll_server_saved_result()

    assert calls == [('saved_analysis', {
        'study_uid': '1.2.3', 'patient_id': 'synthetic-person'}, 'a' * 32)]
    assert 'lumbar' in tabs.pages
    assert host.tab_widget.tabText(host.tab_widget.indexOf(tabs.pages['lumbar'])) == 'Eagle Eye Result'
    assert 'Synthetic server result' in tabs.pages['lumbar'].report.toPlainText()
    tabs._dispose()
    host.close()


@pytest.mark.parametrize('module,context,section', [
    ('brain', None, 'Global volumes'),
    ('brain-lesions', 'svd', 'White-matter lesion distribution'),
    ('brain-lesions', 'ms', 'MS lesion distribution'),
])
def test_all_brain_report_contexts_share_the_client_reader(monkeypatch, module, context, section):
    from concurrent.futures import Future
    from types import SimpleNamespace
    from PySide6.QtWidgets import QApplication, QWidget, QTabWidget, QTextBrowser, QComboBox, QPushButton
    from PySide6.QtGui import QPalette, QColor
    from modules.ai_imaging import eagle_eye_saved_results as saved
    from modules.ai_imaging.eagle_eye_result_tabs import AnalysisResultTabs
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(saved, 'discover_workspace', lambda *args: [])
    host = QWidget(); host._study_uid = '1.2.3'; host.tab_widget = QTabWidget(host)
    host.imaging_tab = QWidget(); host.tab_widget.addTab(host.imaging_tab, 'Imaging Tools')
    opened = []
    host.workspace_controller = SimpleNamespace(open_saved_brain_result=opened.append)
    tabs = AnalysisResultTabs(host)
    result = {'clinical_context': {'primary_disease': context}}
    future = Future(); future.set_result([dict(module=module, result=result,
        content='<h1>' + section + '</h1><p>Unchanged measurement: 12.345</p>',
        report='', pdf=None)])
    tabs._saved_future = future
    tabs._restore_saved()
    page = tabs.pages['saved-' + module]
    card = page.findChild(QWidget, 'savedReportCard')
    assert card.maximumWidth() == 1120
    browser = card.findChild(QTextBrowser)
    assert browser.palette().color(QPalette.Base) == QColor('#ffffff')
    assert 'Unchanged measurement: 12.345' in browser.toPlainText()
    assert card.findChild(QComboBox, 'reportSectionNavigation').itemText(0) == section
    assert {'A-', 'A+'}.issubset({button.text() for button in card.findChildren(QPushButton)})
    page.findChild(QPushButton, 'savedBrainCorrection').click()
    assert opened == [result]
    tabs._saved_executor.shutdown(wait=True)
    host.close()
