# -*- coding: utf-8 -*-
"""Guard tests for the server-bound report HTML export.

Covers the BIDI guide (BIDI_RTL_LTR_IMPLEMENTATION_GUIDE.md) test matrix
(§14) as applied to the OUTGOING server payload built by
``PacsClient.utils.report_server_html.prepare_report_html_for_server``:

* per-block content-detected RTL/LTR (dir attribute + inline styles)
* inline-only output (no <html>/<head>/<style>/<body> chrome)
* neutral-symbol LRM fix in RTL blocks
* preservation of existing inline formatting (colors, fonts, alignment)
* idempotency (re-exporting an export is stable)
"""

import re

import pytest

from PacsClient.utils.report_server_html import (
    LRM,
    detect_text_direction,
    detect_dominant_direction,
    insert_lrm_before_neutrals,
    prepare_report_html_for_server,
)

PERSIAN_SENTENCE = "اندازه کبد طبیعی است."
ENGLISH_SENTENCE = "Patient name: John, CT scan normal."


# ──────────────────────────────────────────────────────────────────────
# Direction detection
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    (PERSIAN_SENTENCE, "rtl"),
    ("hello world", "ltr"),
    ("سلام CT scan", "rtl"),      # mixed → first strong char (Persian)
    ("CT scan سلام", "ltr"),      # mixed → first strong char (Latin)
    ("25*45", None),               # neutral/digits only
    ("", None),
])
def test_detect_text_direction(text, expected):
    assert detect_text_direction(text) == expected


def test_dominant_direction_is_rtl_first():
    # Any Persian content → RTL document root, even with more Latin letters.
    assert detect_dominant_direction("<p>گزارش</p><p>Patient name John CT scan</p>") == "rtl"
    assert detect_dominant_direction("<p>English only</p>") == "ltr"
    assert detect_dominant_direction("<p>25*45</p>") == "rtl"  # neutral → default RTL


# ──────────────────────────────────────────────────────────────────────
# Neutral Symbol Fix (guide §6 / §14 cases 10-11)
# ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("25*45", "25" + LRM + "*45"),
    ("اندازه =", "اندازه ="),               # RTL context → no LRM
    ("(start", "(start"),                    # start of line → no LRM
    ("width =", "width " + LRM + "="),
])
def test_insert_lrm_before_neutrals(text, expected):
    assert insert_lrm_before_neutrals(text) == expected


# ──────────────────────────────────────────────────────────────────────
# Server payload export
# ──────────────────────────────────────────────────────────────────────

QT_DOC = (
    "<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.0//EN\">"
    "<html><head><meta name=\"qrichtext\" content=\"1\" />"
    "<style type=\"text/css\">p, li { white-space: pre-wrap; }</style></head>"
    "<body style=\" font-family:'Tahoma'; font-size:12pt;\">"
    "<p style=\" margin-top:0px;\"><span style=\" color:#aa0000;\">"
    "اندازه کبد 25*45mm طبیعی است.</span></p>"
    "<p>" + ENGLISH_SENTENCE + "</p>"
    "<p align=\"center\">عنوان وسط</p>"
    "</body></html>"
)


def test_empty_input_returns_empty():
    assert prepare_report_html_for_server("") == ""
    assert prepare_report_html_for_server(None) == ""


def test_export_strips_document_chrome():
    out = prepare_report_html_for_server(QT_DOC)
    low = out.lower()
    for forbidden in ("<html", "<head", "<body", "<style", "<!doctype", "<meta"):
        assert forbidden not in low, f"{forbidden} must not reach the server payload"


def test_export_root_contract():
    out = prepare_report_html_for_server(QT_DOC)
    root = out[:out.index(">") + 1]
    assert 'dir="rtl"' in root                      # Persian present → RTL root
    assert "unicode-bidi: plaintext" in root
    assert "direction: rtl" in root
    assert "text-align: right" in root
    # Qt body default font carried inline onto the wrapper.
    assert "font-family: 'Tahoma'" in root
    assert "font-size: 12pt" in root


def test_export_per_block_directions():
    out = prepare_report_html_for_server(QT_DOC)
    paragraphs = re.findall(r"<p\b[^>]*>", out)
    assert len(paragraphs) == 3
    persian_p, english_p, centered_p = paragraphs

    assert 'dir="rtl"' in persian_p
    assert "direction: rtl" in persian_p
    assert "text-align: right" in persian_p
    assert "unicode-bidi: isolate" in persian_p

    assert 'dir="ltr"' in english_p
    assert "direction: ltr" in english_p
    assert "text-align: left" in english_p

    # Explicit center alignment preserved; never overridden by direction.
    assert 'align="center"' in centered_p
    assert "text-align" not in centered_p
    assert 'dir="rtl"' in centered_p


def test_export_preserves_inline_formatting():
    out = prepare_report_html_for_server(QT_DOC)
    assert "color:#aa0000" in out.replace(" ", "") or "color: #aa0000" in out


def test_export_applies_lrm_in_rtl_blocks():
    out = prepare_report_html_for_server(QT_DOC)
    assert "25" + LRM + "*45mm" in out


def test_export_no_lrm_in_ltr_blocks():
    out = prepare_report_html_for_server("<p>width = 100 mm</p>")
    # Pure-LTR paragraph needs no LRM injection.
    assert LRM not in out


def test_export_entities_stay_intact():
    out = prepare_report_html_for_server("<p>سایز&nbsp;25*45 &amp; بیشتر</p>")
    assert "&nbsp;" in out
    assert "&amp;" in out
    # No LRM may be injected inside an entity.
    assert LRM + ";" not in out
    assert "&nbsp" + LRM not in out


def test_export_pre_blocks_forced_ltr():
    out = prepare_report_html_for_server("<p>گزارش</p><pre>L4-L5 code</pre>")
    pre_tag = re.search(r"<pre\b[^>]*>", out).group()
    assert 'dir="ltr"' in pre_tag


def test_export_list_blocks():
    out = prepare_report_html_for_server("<ul><li>سایز 10*20</li><li>CT scan</li></ul>")
    items = re.findall(r"<li\b[^>]*>", out)
    assert 'dir="rtl"' in items[0]
    assert 'dir="ltr"' in items[1]
    ul = re.search(r"<ul\b[^>]*>", out).group()
    assert "dir=" in ul


def test_export_neutral_block_inherits_root():
    out = prepare_report_html_for_server("<p>گزارش فارسی</p><p>25*45</p>")
    paragraphs = re.findall(r"<p\b[^>]*>", out)
    # Neutral-only paragraph inherits the (RTL) root direction.
    assert 'dir="rtl"' in paragraphs[1]


def test_export_is_idempotent():
    once = prepare_report_html_for_server(QT_DOC)
    twice = prepare_report_html_for_server(once)
    assert twice == once


def test_export_english_only_root_is_ltr():
    out = prepare_report_html_for_server("<p>Normal CT scan of the brain.</p>")
    root = out[:out.index(">") + 1]
    assert 'dir="ltr"' in root
    assert "text-align: left" in root


def test_export_merges_duplicate_li_style_attributes():
    # Qt's toHtml emits TWO style attributes on <li> (char + block format);
    # both must survive (browsers would keep only the first).
    out = prepare_report_html_for_server(
        '<ul><li style=" font-family:\'Segoe UI\'; font-size:9pt;" '
        'style=" margin-top:0px;">Item one</li></ul>'
    )
    li = re.search(r"<li\b[^>]*>", out).group()
    assert li.count("style=") == 1
    assert "font-family: 'Segoe UI'" in li
    assert "font-size: 9pt" in li
    assert "margin-top: 0px" in li


def test_export_drops_empty_qt_body_font():
    # QTextDocument may emit font-family:'' on <body>; the wrapper must fall
    # back to the default Persian-capable font stack instead of an empty one.
    out = prepare_report_html_for_server(
        "<html><head></head><body style=\" font-family:''; font-weight:400;\">"
        "<p>گزارش</p></body></html>"
    )
    root = out[:out.index(">") + 1]
    assert "font-family: ;" not in root
    assert "IRANYekan" in root


def test_export_plain_text_without_tags():
    out = prepare_report_html_for_server("گزارش ساده بدون تگ")
    assert out.startswith("<div")
    assert 'dir="rtl"' in out
    assert "گزارش ساده بدون تگ" in out
