from PySide6.QtWidgets import QApplication, QWidget
from modules.education.slide_content import SlideContentFrame


def test_composed_text_zoom_preserves_hierarchy_and_media_geometry():
    app = QApplication.instance() or QApplication([])
    media = QWidget()
    frame = SlideContentFrame(media)
    payload = {'name': 'Synthetic title', 'text': 'Heading Body',
               'rich_text': '<p><span style="font-size:30pt">Heading</span></p><p>Body</p>',
               'path': 'synthetic.png', 'layout': 'right'}
    frame.present(payload)
    frame.resize(1000, 700)
    frame.show()
    app.processEvents()
    original = frame.text.toHtml()
    title_size = frame.title.font().pixelSize()
    media_width = media.width()
    assert frame.can_zoom_text()
    frame.zoom_text(1)
    app.processEvents()
    assert frame.title.font().pixelSize() > title_size
    assert frame.text.toHtml() != original
    assert 'Heading' in frame.text.toPlainText()
    assert media.width() == media_width
    frame.zoom_text(-1)
    assert frame.text.toHtml() == original
    assert payload['rich_text'].startswith('<p>')
    frame.reset()
    assert not frame.can_zoom_text()
    frame.close()


def test_image_slide_exposes_independent_text_controls_and_routes_to_composition():
    import ast
    from pathlib import Path
    from PySide6.QtWidgets import QToolButton
    app = QApplication.instance() or QApplication([])
    tree = ast.parse(Path('modules/education/educational_patient_viewer_widget.py').read_text(encoding='utf-8-sig'))
    methods = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name in {'_set_media_controls', '_font_zoom'}]
    cls = ast.ClassDef(name='Host', bases=[ast.Name(id='QWidget', ctx=ast.Load())],
                       keywords=[], body=methods, decorator_list=[])
    ns = {'QWidget': QWidget}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), '<controls>', 'exec'), ns)
    host = ns['Host']()
    host.slide_content_frame = SlideContentFrame(QWidget(), host)
    for name in ('btn_zoom_out', 'btn_zoom_in', 'btn_fit', 'btn_reset',
                 'btn_prev_page', 'btn_next_page', 'btn_font_dec', 'btn_font_inc'):
        setattr(host, name, QToolButton(host))
    host.media_controls = QWidget(host)
    host.slide_content_frame.present({'name': 'Title', 'text': 'Body', 'path': 'image.png'})
    host._set_media_controls('image')
    assert not host.btn_zoom_in.isHidden()
    assert not host.btn_font_inc.isHidden()
    before = host.slide_content_frame.text.toHtml()
    host._font_zoom(1)
    assert host.slide_content_frame.text.toHtml() != before
    host.slide_content_frame.reset()
    host._set_media_controls('image')
    assert host.btn_font_inc.isHidden()
    host.close()
