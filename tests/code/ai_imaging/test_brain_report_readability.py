from modules.ai_imaging.eagle_eye_brain.organized_report import readable_prose

def test_prose_sentences_break_without_changing_numbers_or_tables():
    html='<p>Volume is 0.5 cm3. Review the mask. No diagnosis is inferred.</p><table><tr><td>One. Two.</td></tr></table>'
    out=readable_prose(html)
    assert '0.5 cm3.<br' in out
    assert 'mask.<br' in out
    assert '<td>One. Two.</td>' in out

def test_citations_images_and_inline_emphasis_are_preserved():
    source='<p>Smith et al. Study. doi:10.1000/test.123</p><p><img src="data:image/png;base64,AA=="></p>'
    assert readable_prose(source)==source
    assert '<b>Review required.</b>' in readable_prose('<p><b>Review required.</b> Check coverage. Check motion.</p>')

def test_single_section_brain_pdf_uses_shared_layout(monkeypatch,tmp_path):
    from modules.ai_imaging.eagle_eye_brain import organized_report,report
    calls=[]
    monkeypatch.setattr(organized_report,'write_paged_pdf',lambda html,path: calls.append((html,path)))
    # Intercept the legacy writer too: a missing delegation is the assertion failure.
    from PySide6.QtGui import QTextDocument
    monkeypatch.setattr(QTextDocument,'print_',lambda *args: None)
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    html='<html><head></head><body><p>First sentence. Second sentence.</p></body></html>'
    report.write_pdf(html,tmp_path/'single.pdf')
    assert calls==[(html,tmp_path/'single.pdf')]
