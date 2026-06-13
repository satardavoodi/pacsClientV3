"""Tests for modules/education/docx_render.py (inline Word rendering)."""

import zipfile

import pytest

from modules.education.docx_render import docx_to_html

_DOC_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:body>"
    '<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t>My Title</w:t></w:r></w:p>'
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Section A</w:t></w:r></w:p>'
    "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>bold</w:t></w:r>"
    '<w:r><w:t xml:space="preserve"> and </w:t></w:r>'
    "<w:r><w:rPr><w:i/></w:rPr><w:t>italic</w:t></w:r></w:p>"
    "<w:p><w:pPr><w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr></w:pPr>"
    "<w:r><w:t>bullet one</w:t></w:r></w:p>"
    "<w:p><w:pPr><w:numPr><w:numId w:val=\"1\"/></w:numPr></w:pPr>"
    "<w:r><w:t>bullet two</w:t></w:r></w:p>"
    "</w:body></w:document>"
)


def _make_docx(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", _DOC_XML)


def test_docx_to_html_structure(tmp_path):
    p = tmp_path / "sample.docx"
    _make_docx(p)
    html = docx_to_html(str(p))
    assert "<h1>My Title</h1>" in html          # Title style
    assert "<h2>Section A</h2>" in html          # Heading1 style
    assert "<b>bold</b>" in html
    assert "<i>italic</i>" in html
    assert "<ul>" in html and "</ul>" in html    # consecutive list items grouped
    assert "<li>bullet one</li>" in html
    assert "<li>bullet two</li>" in html
    assert html.startswith("<html>") and "</html>" in html


def test_docx_to_html_title_override(tmp_path):
    p = tmp_path / "s.docx"
    _make_docx(p)
    html = docx_to_html(str(p), title="Override")
    assert "<h1>Override</h1>" in html


def test_docx_to_html_rejects_non_docx(tmp_path):
    bad = tmp_path / "not.docx"
    bad.write_bytes(b"\xd0\xcf\x11\xe0 legacy ole2 doc")  # OLE2, not a zip
    with pytest.raises(ValueError):
        docx_to_html(str(bad))


def test_docx_to_html_escapes_text(tmp_path):
    # A valid document.xml whose text node contains characters that MUST be
    # re-escaped in the HTML output (the run text decodes to: a<b>&x).
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>a&lt;b&gt;&amp;x</w:t></w:r></w:p></w:body></w:document>"
    )
    p = tmp_path / "esc.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)
    html = docx_to_html(str(p))
    assert "a&lt;b&gt;&amp;x" in html
