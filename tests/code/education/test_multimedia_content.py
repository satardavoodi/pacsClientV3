"""Synthetic contracts for composed teaching content and document import."""
from tests.code.education.test_build_course_items import app, dialog_factory
from tests.code.education.test_course_importer import temp_env


def test_new_item_has_four_primary_choices(dialog_factory):
    dialog, _ = dialog_factory()
    assert [dialog.type_combo.itemData(i) for i in range(dialog.type_combo.count())] == [
        'multimedia', 'pdf', 'presentation', 'dicom_reference']


def test_multimedia_text_roundtrip_without_media(dialog_factory):
    dialog, messages = dialog_factory()
    dialog.name_input.setText('Synthetic teaching')
    dialog.text_input.setHtml('<p><b>Important</b></p><ul><li>First</li></ul>')
    dialog._save()
    saved = dialog.get_payload()
    assert saved['content_type'] == 'multimedia'
    assert 'Important' in saved['content_data']['text']
    reopened, _ = dialog_factory('multimedia', saved['content_data'])
    assert reopened.text_input.toPlainText() == dialog.text_input.toPlainText()
    assert reopened.text_input.document().toHtml().find('font-weight:700') >= 0
    messages.warning.assert_not_called()


def test_rich_content_cannot_load_embedded_files():
    from modules.education.slide_content import safe_rich_text
    safe = safe_rich_text('<p onclick="bad()">Okay<img src="file:///private.png"><script>bad()</script></p>')
    assert 'src=' not in safe and '<script' not in safe and 'onclick' not in safe


def test_slide_background_survives_workstation_parent_theme(app):
    from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
    from modules.education.slide_content import SlideContentFrame
    owner=QWidget()
    owner.setStyleSheet('QWidget{background:#000000;border:none;margin:0px;padding:0px;}')
    page=QWidget();layout=QVBoxLayout(owner);layout.addWidget(page)
    frame=SlideContentFrame(QLabel('Media'),page)
    QVBoxLayout(page).addWidget(frame)
    owner.resize(600,400);owner.show()
    frame.present({'text':'Teaching','background':'#103d42'})
    app.processEvents()
    from PySide6.QtCore import QPoint
    point=frame.mapTo(owner,QPoint(2,2))
    assert owner.grab().toImage().pixelColor(point).name() == '#103d42'
    assert frame.grab().toImage().pixelColor(2,2).name() == '#103d42'
    assert frame.grab().toImage().pixelColor(frame.host.x()+2,frame.host.y()+2).name() == '#103d42'
    owner.close()


def test_document_conversion_is_a_worker_operation():
    from modules.education.authoring_tasks import CourseDocumentImportTask
    assert issubclass(CourseDocumentImportTask, __import__('PySide6.QtCore', fromlist=['QThread']).QThread)


def test_frame_composes_media_and_text_and_documents_use_full_width(app):
    from PySide6.QtWidgets import QLabel
    from modules.education.slide_content import SlideContentFrame
    media = QLabel('Synthetic media')
    frame = SlideContentFrame(media)
    frame.resize(960,540)
    frame.show()
    data = {'name':'Teaching','text':'Explanation','path':'synthetic.png','layout':'right'}
    frame.present(data)
    app.processEvents()
    assert frame.text.isVisible() and media.isVisible()
    assert frame.text.x() < media.x()
    frame.present(dict(data,layout='left'))
    app.processEvents()
    assert media.x() < frame.text.x()
    frame.present(dict(data,layout='below'))
    app.processEvents()
    assert frame.text.y() < media.y()
    frame.present(dict(data,title_position='below'),document=True)
    app.processEvents()
    assert not frame.text.isVisible() and media.width() > frame.width()*.9
    assert frame.title.y() > frame.host.y()
    frame.present({'text':'Only text','layout':'right'})
    app.processEvents()
    assert frame.text.isVisible() and not media.isVisible()
    assert frame.text.width()>frame.width()*.9
    frame.close()


def test_presentation_import_retains_original_and_pdf_off_gui(app, temp_env, tmp_path, monkeypatch):
    from PySide6.QtCore import QThread
    from modules.education.authoring_tasks import CourseDocumentImportTask
    from modules.education import presentation_conversion, course_database
    source = tmp_path/'synthetic.pptx'
    source.write_bytes(b'Synthetic presentation')
    pdf = tmp_path/'synthetic.pdf'
    pdf.write_bytes(b'%PDF-1.4 synthetic')
    threads=[]
    def convert(*args):
        threads.append(QThread.currentThread()==app.thread())
        return str(pdf)
    monkeypatch.setattr(presentation_conversion,'presentation_pdf',convert)
    monkeypatch.setattr(course_database,'save_course_asset',lambda path,pk:str(path))
    worker=CourseDocumentImportTask(str(source),7)
    worker.start()
    assert worker.wait(5000)
    assert not worker.error and threads==[False]
    assert worker.result['path']==str(pdf)
    assert worker.result['original']['path']==str(source)


def test_failed_presentation_import_has_no_accepted_payload(app, monkeypatch):
    from modules.education.authoring_tasks import CourseDocumentImportTask
    from modules.education import presentation_conversion
    def fail(*args): raise ValueError('Synthetic converter failure')
    monkeypatch.setattr(presentation_conversion,'presentation_pdf',fail)
    worker=CourseDocumentImportTask('synthetic.pptx',7)
    worker.start()
    assert worker.wait(5000)
    assert worker.error and worker.result is None


def test_template_changes_retain_rich_text_and_clear_media_keeps_text(dialog_factory):
    dialog, _=dialog_factory('multimedia',{'name':'Teaching','text':'Text','path':'synthetic.png','media_type':'image'})
    dialog.text_input.setHtml('<b>Formatted teaching</b>')
    before=dialog.text_input.toHtml()
    for index in range(dialog.content_editor.layout_choice.count()):
        dialog.content_editor.layout_choice.setCurrentIndex(index)
        assert dialog.text_input.toHtml()==before
    dialog._clear_media()
    dialog._save()
    assert 'path' not in dialog.content_data and dialog.content_data['text']=='Formatted teaching'


def test_actual_viewer_dispatches_converted_presentation_as_pdf(app, tmp_path):
    import ast
    import logging
    from pathlib import Path
    from types import SimpleNamespace
    from typing import Dict, Any
    from unittest.mock import Mock
    from PySide6.QtWidgets import QLabel, QStackedWidget
    from modules.education.slide_content import SlideContentFrame
    path = Path('modules/education/educational_patient_viewer_widget.py')
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_load_media_content_impl')
    ns = dict(Dict=Dict, Any=Any, Path=Path, logger=logging.getLogger('synthetic-viewer-test'))
    exec(compile(ast.Module(body=[method],type_ignores=[]),str(path),'exec'),ns)
    media=QLabel('Document viewport')
    frame=SlideContentFrame(media)
    stack=QStackedWidget()
    stack.addWidget(QLabel('DICOM'))
    stack.addWidget(frame)
    pdf=tmp_path/'converted.pdf'
    pdf.write_bytes(b'%PDF-1.4 synthetic')
    viewer=SimpleNamespace(slide_content_frame=frame,education_content_stack=stack,
        _set_content_header=Mock(),_show_pdf=Mock(),_show_external_resource=Mock())
    ns['_load_media_content_impl'](viewer,'presentation',{'path':str(pdf),'name':'Teaching','title_position':'below'})
    viewer._show_pdf.assert_called_once_with(str(pdf))
    viewer._show_external_resource.assert_not_called()
    assert not frame.text.isVisible()
    stack.close()


def test_secretary_text_correction_retains_composed_media(temp_env):
    from modules.education import course_database as db
    from modules.education.course_authoring import CourseAuthoringService
    from tests.code.education.test_command_authoring import ready
    pk=db.insert_course('Synthetic composed course',author='Teacher')
    slide=db.insert_slide(pk,1,'Teaching')
    original={'name':'Teaching','text':'Old','rich_text':'<b>Old</b>','path':'synthetic.png','media_type':'image','layout':'left','background':'#103d42'}
    db.insert_slide_content(slide,'multimedia',1,original)
    service=CourseAuthoringService()
    try:
        loaded=ready(service,service.load(pk))
        handle=loaded['draft_id']
        service.update(handle,1,{},[{'slide_order':1,'text':'Corrected'}])
        assert ready(service,service.save(handle,2))['state']=='succeeded'
        content=db.get_course_with_slides(pk)['slides'][0]['content']
        assert len(content)==1
        saved=content[0]['content_data']
        assert saved['text']=='Corrected' and 'rich_text' not in saved
        for key in ('path','media_type','layout','background'):
            assert saved[key]==original[key]
    finally:
        service.close()
