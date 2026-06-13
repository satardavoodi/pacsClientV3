"""Lightweight, dependency-free ``.docx`` -> HTML renderer.

Used by the Education viewer to show Word documents *inside* the layout (in a
QTextBrowser/QTextEdit) instead of opening them in an external application.

A ``.docx`` is just a ZIP of OOXML parts, so this converter uses only the Python
standard library (``zipfile`` + ``xml.etree``). That keeps it working in frozen
/ installed builds with no extra packages to bundle. It handles the common
teaching-document constructs: headings, paragraphs, bold/italic/underline runs,
bullet/numbered lists, tables, and inline images (embedded as data URIs).

Legacy binary ``.doc`` (OLE2) is *not* supported here -- callers should fall back
to opening those externally.
"""

from __future__ import annotations

import base64
import html
import os
import zipfile
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

_IMG_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
             ".tif": "image/tiff", ".tiff": "image/tiff", ".emf": "image/emf"}

_PAGE_CSS = (
    "body{background:#ffffff;color:#1b2430;font-family:'Segoe UI',Arial,sans-serif;"
    "font-size:15px;line-height:1.55;}"
    "h1{font-size:1.5em;color:#0b3a66;margin:0 0 .4em;}"
    "h2{font-size:1.3em;color:#0b3a66;margin:.6em 0 .3em;}"
    "h3{font-size:1.13em;color:#13507f;margin:.6em 0 .3em;}"
    "h4{font-size:1.02em;color:#13507f;margin:.5em 0 .25em;}"
    "p{margin:.35em 0;} li{margin:.2em 0;}"
    "table{border-collapse:collapse;margin:.5em 0;}"
    "td,th{border:1px solid #b9c4d1;padding:4px 8px;vertical-align:top;}"
    "img{max-width:100%;height:auto;}"
)


def _toggle(rpr: Optional[ET.Element], name: str) -> bool:
    """A boolean run property (``<w:b/>``) is on unless explicitly val=false."""
    if rpr is None:
        return False
    el = rpr.find(W + name)
    if el is None:
        return False
    return (el.get(W + "val") or "true").lower() not in ("0", "false", "off", "none")


def _run_html(run: ET.Element) -> str:
    parts: List[str] = []
    for child in run:
        if child.tag == W + "t":
            parts.append(child.text or "")
        elif child.tag == W + "tab":
            parts.append("\t")
        elif child.tag in (W + "br", W + "cr"):
            parts.append("\n")
    text = "".join(parts)
    if not text:
        return ""
    esc = (html.escape(text)
           .replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
           .replace("\n", "<br>"))
    rpr = run.find(W + "rPr")
    if _toggle(rpr, "b"):
        esc = f"<b>{esc}</b>"
    if _toggle(rpr, "i"):
        esc = f"<i>{esc}</i>"
    if _toggle(rpr, "u"):
        esc = f"<u>{esc}</u>"
    return esc


def _para_tag(p: ET.Element) -> str:
    ppr = p.find(W + "pPr")
    if ppr is not None:
        st = ppr.find(W + "pStyle")
        if st is not None:
            v = (st.get(W + "val") or "").lower()
            if "title" in v:
                return "h1"
            if "heading1" in v or v == "1":
                return "h2"
            if "heading2" in v or v == "2":
                return "h3"
            if "heading" in v:
                return "h4"
    return "p"


def _is_list_item(p: ET.Element) -> bool:
    ppr = p.find(W + "pPr")
    return ppr is not None and ppr.find(W + "numPr") is not None


def _para_images(p: ET.Element, rels: Dict[str, str], zf: zipfile.ZipFile) -> str:
    """Return ``<img>`` tags for any embedded drawings in the paragraph."""
    out: List[str] = []
    for blip in p.iter(A + "blip"):
        rid = blip.get(R + "embed")
        target = rels.get(rid or "")
        if not target:
            continue
        part = target if target.startswith("word/") else "word/" + target.lstrip("/")
        part = os.path.normpath(part).replace(os.sep, "/")
        try:
            data = zf.read(part)
        except KeyError:
            continue
        mime = _IMG_MIME.get(os.path.splitext(part)[1].lower(), "image/png")
        b64 = base64.b64encode(data).decode("ascii")
        out.append(f'<div><img src="data:{mime};base64,{b64}"/></div>')
    return "".join(out)


def _table_html(tbl: ET.Element, rels: Dict[str, str], zf: zipfile.ZipFile) -> str:
    rows: List[str] = []
    for tr in tbl.findall(W + "tr"):
        cells: List[str] = []
        for tc in tr.findall(W + "tc"):
            inner = "".join(_para_html(p, rels, zf) for p in tc.findall(W + "p"))
            cells.append(f"<td>{inner or '&nbsp;'}</td>")
        if cells:
            rows.append("<tr>" + "".join(cells) + "</tr>")
    return "<table>" + "".join(rows) + "</table>" if rows else ""


def _para_html(p: ET.Element, rels: Dict[str, str], zf: zipfile.ZipFile) -> str:
    body = "".join(_run_html(r) for r in p.findall(W + "r"))
    body += _para_images(p, rels, zf)
    if not body.strip():
        return ""
    tag = _para_tag(p)
    return f"<{tag}>{body}</{tag}>"


def _load_rels(zf: zipfile.ZipFile) -> Dict[str, str]:
    rels: Dict[str, str] = {}
    try:
        root = ET.fromstring(zf.read("word/_rels/document.xml.rels"))
    except (KeyError, ET.ParseError):
        return rels
    for rel in root:
        rid = rel.get("Id")
        tgt = rel.get("Target")
        if rid and tgt:
            rels[rid] = tgt
    return rels


def docx_to_html(path: str, *, title: Optional[str] = None) -> str:
    """Convert a ``.docx`` file to a self-contained HTML string.

    Raises ``ValueError`` if the file is not a readable OOXML ``.docx``.
    """
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"not a readable .docx: {exc}") from exc
    with zf:
        try:
            doc_xml = zf.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("missing word/document.xml (not a .docx?)") from exc
        rels = _load_rels(zf)
        try:
            root = ET.fromstring(doc_xml)
        except ET.ParseError as exc:
            raise ValueError(f"corrupt document.xml: {exc}") from exc

        body = root.find(W + "body")
        blocks: List[str] = []
        open_list = False
        for el in (list(body) if body is not None else []):
            if el.tag == W + "p":
                if _is_list_item(el):
                    inner = "".join(_run_html(r) for r in el.findall(W + "r"))
                    if inner.strip():
                        if not open_list:
                            blocks.append("<ul>")
                            open_list = True
                        blocks.append(f"<li>{inner}</li>")
                    continue
                if open_list:
                    blocks.append("</ul>")
                    open_list = False
                html_p = _para_html(el, rels, zf)
                if html_p:
                    blocks.append(html_p)
            elif el.tag == W + "tbl":
                if open_list:
                    blocks.append("</ul>")
                    open_list = False
                blocks.append(_table_html(el, rels, zf))
        if open_list:
            blocks.append("</ul>")

    head = f"<h1>{html.escape(title)}</h1>" if title else ""
    return (f"<html><head><style>{_PAGE_CSS}</style></head>"
            f"<body>{head}{''.join(blocks)}</body></html>")
