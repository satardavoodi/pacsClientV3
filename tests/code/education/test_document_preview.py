"""Document previews use synthetic files only."""
import ast
import codecs
import html
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QTextBrowser
from PySide6.QtCore import QThreadPool
from modules.education.document_preview import read_text_preview, start_text_preview, MAX_TEXT_BYTES
from modules.education.authoring_tasks import presentation_issues


def test_text_file_encodings_and_limit(tmp_path):
    p=tmp_path/'notes.txt'
    for encoding in ['utf-8-sig','utf-16']:
        p.write_text('Teaching example\nSecond line',encoding=encoding)
        assert read_text_preview(p)=='Teaching example\nSecond line'
    p.write_bytes(b'a'*(MAX_TEXT_BYTES+100))
    assert 'Preview limited' in read_text_preview(p)
    p.write_bytes(b'\x00\x01\x02')
    with pytest.raises(ValueError):read_text_preview(p)


def methods():
    source=Path('modules/education/educational_patient_viewer_widget.py')
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    names={'_load_media_content_impl','_show_text','_on_text_preview_ready','_on_presentation_ready'}
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in names]
    ns=dict(Path=Path,Any=Any,Dict=Dict,_html=html,logger=Mock())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
    return ns


def test_attachment_suffix_routes_to_inline_preview_even_with_old_text_placeholder():
    ns=methods()
    for suffix,method in [('.txt','_show_file_text'),('.pptx','_show_presentation'),('.ppx','_show_presentation')]:
        viewer=SimpleNamespace(_show_file_text=Mock(),_show_presentation=Mock())
        ns['_load_media_content_impl'](viewer,'text',{'path':'example'+suffix,'text':'Legacy placeholder'})
        getattr(viewer,method).assert_called_once_with('example'+suffix)


def test_stale_document_completion_does_not_replace_active_item():
    ns=methods()
    for name,result in [('_on_text_preview_ready',{'path':'notes.txt','text':'Example'}),('_on_presentation_ready',{'path':'slides.pptx','pdf':'preview.pdf'})]:
        viewer=SimpleNamespace(_item_generation=2,_show_text=Mock(),_show_pdf=Mock())
        ns[name](viewer,1,result)
        viewer._show_text.assert_not_called();viewer._show_pdf.assert_not_called()


def test_file_text_preflight_and_actual_queued_delivery(tmp_path):
    app=QApplication.instance() or QApplication([])
    path=tmp_path/'notes.txt';path.write_text('<script>synthetic</script>\nTeaching note',encoding='utf-8')
    course={'slides':[{'content':[{'content_type':'text','content_data':{'path':str(path)}}]}]}
    assert presentation_issues(course)==[]
    class Receiver(QWidget):
        def receive(self,generation,result):
            self.result=result
    receiver=Receiver();receiver.result=None
    start_text_preview(str(path),1,receiver.receive)
    assert QThreadPool.globalInstance().waitForDone(5000)
    for _ in range(5):app.processEvents()
    assert receiver.result['text'].endswith('Teaching note')
    browser=QTextBrowser()
    viewer=SimpleNamespace(_stop_media_playback=Mock(),media_text=browser,media_stack=Mock(),media_text_page=object(),_set_media_controls=Mock())
    methods()['_show_text'](viewer,receiver.result)
    assert '<script>synthetic</script>' in browser.toPlainText()
    browser.close();receiver.close()


def test_conversion_missing_engine_and_bad_alias(tmp_path,monkeypatch):
    from modules.education import presentation_conversion as pc
    source=tmp_path/'slides.pptx';source.write_bytes(b'synthetic')
    monkeypatch.setattr(pc,'find_libreoffice',lambda:None)
    with pytest.raises(ValueError,match='Install LibreOffice'):pc.presentation_pdf(source,tmp_path/'cache')
    source=tmp_path/'slides.ppx';source.write_bytes(b'not a deck')
    monkeypatch.setattr(pc,'find_libreoffice',lambda:'synthetic-engine')
    with pytest.raises(ValueError,match='not a recognized'):pc.presentation_pdf(source,tmp_path/'cache')

def test_conversion_cache_tracks_file_contents_and_preserves_source(tmp_path,monkeypatch):
    from modules.education import presentation_conversion as pc
    source=tmp_path/'deck.pptx';source.write_bytes(b'first synthetic deck')
    monkeypatch.setattr(pc,'find_libreoffice',lambda:'synthetic-office')
    calls=[]
    def launch(command,**kwargs):
        calls.append(command)
        staged=Path(command[-1])
        assert staged!=source and staged.read_bytes()==source.read_bytes()
        (staged.parent/'slides.pdf').write_bytes(b'%PDF-synthetic')
        return SimpleNamespace(wait=lambda timeout:0)
    monkeypatch.setattr(pc.subprocess,'Popen',launch)
    first=pc.presentation_pdf(source,tmp_path/'cache')
    assert pc.presentation_pdf(source,tmp_path/'cache')==first and len(calls)==1
    source.write_bytes(b'changed synthetic deck')
    assert pc.presentation_pdf(source,tmp_path/'cache')!=first and len(calls)==2
    assert source.read_bytes()==b'changed synthetic deck'
    assert not list((tmp_path/'cache').glob('conversion-*'))
