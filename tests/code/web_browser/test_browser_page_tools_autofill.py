"""Unit tests for the pure browser agent-tool + autofill helpers (2026-06-27).

``modules.web_browser.page_tools`` and ``modules.web_browser.autofill`` are
intentionally Qt-free (the package ``__init__`` is lazy), so these run headless
in any environment — no PySide6/QtWebEngine needed. They lock in the security
contract: selectors/values are JSON-encoded into the JS (no breakout) and the
fill offer is domain-EXACT.
"""
import json
from pathlib import Path

from modules.web_browser import autofill as AF
from modules.web_browser import page_tools as PT

_ROOT = Path(__file__).resolve().parents[3]


def test_whole_page_read_snippets_are_nonempty_js():
    for js in (PT.JS_PAGE_TEXT, PT.JS_PAGE_HTML, PT.JS_SELECTED_TEXT,
               PT.JS_PAGE_TITLE, PT.JS_DOM_SUMMARY, PT.JS_SCROLL_STATE,
               PT.JS_SELECTED_ELEMENT, PT.JS_NETWORK_ENTRIES,
               PT.JS_NETWORK_CAPTURE_INSTALL, PT.JS_CLEAR_NETWORK_CAPTURE,
               PT.JS_STRUCTURED_PAGE_DATA):
        assert isinstance(js, str) and js.strip()
        assert "catch" in js  # every snippet is guarded


def test_selector_is_json_encoded_no_breakout():
    hostile = "a'); alert(1); //"
    js = PT.js_find_element(hostile)
    # The selector appears ONLY as its JSON-encoded literal, never raw.
    assert json.dumps(hostile) in js
    assert "a'); alert(1)" not in js.replace(json.dumps(hostile), "")


def test_fill_field_encodes_both_selector_and_value():
    js = PT.js_fill_field("#user", 'p"a"ss')
    assert json.dumps("#user") in js
    assert json.dumps('p"a"ss') in js


def test_click_submit_table_links_builders():
    assert json.dumps("#go") in PT.js_click("#go")
    assert "querySelector" in PT.js_submit_form()           # default: password form
    assert json.dumps("form#login") in PT.js_submit_form("form#login")
    assert "document.links" in PT.js_get_links(50)
    table_js = PT.js_extract_table("table.x", max_rows=5, max_cols=3)
    assert json.dumps("table.x") in table_js and "5" in table_js


def test_snapshot_accessibility_inputs_buttons_scroll_and_type_builders():
    assert "elements" in PT.js_dom_snapshot(10)
    assert "nodes" in PT.js_accessibility_tree(10)
    assert "input,select,textarea" in PT.js_get_inputs(10)
    assert "role=button" in PT.js_get_buttons(10)
    assert json.dumps("#field") in PT.js_type_text("#field", "abc")
    assert json.dumps("abc") in PT.js_type_text("#field", "abc")
    assert "scrollBy" in PT.js_scroll_page(delta_y=100)
    assert "scrollTo" in PT.js_scroll_page(x=0, y=200)


def test_network_capture_injection_wraps_fetch_and_xhr():
    js = PT.JS_NETWORK_CAPTURE_INSTALL
    assert "__aipacsNetworkCapture" in js
    assert "window.fetch" in js
    assert "XMLHttpRequest" in js
    assert "captured_at" in js
    assert "MAX_BODY" in js
    assert "getResponses" in js
    assert "clear:function" in js
    assert "captured_responses" in PT.JS_NETWORK_ENTRIES


def test_network_capture_is_default_on_in_browser_widget():
    src = (_ROOT / "modules" / "web_browser" / "widget.py").read_text(encoding="utf-8")
    assert 'NETWORK_CAPTURE_ENV = "AIPACS_BROWSER_NETWORK_CAPTURE"' in src
    assert 'NETWORK_CAPTURE_DEFAULT = "1"' in src
    assert "os.environ.get(NETWORK_CAPTURE_ENV, NETWORK_CAPTURE_DEFAULT) == \"0\"" in src


def test_autofill_host_helpers():
    assert AF.host_of("https://Example.com/login") == "example.com"
    assert AF.host_of("example.com") == "example.com"
    assert AF.host_of("") == ""
    assert AF.same_host("https://a.com/x", "http://a.com/y") is True
    assert AF.same_host("https://a.com", "https://b.com") is False


def test_should_offer_fill_is_domain_exact():
    assert AF.should_offer_fill("example.com", "https://example.com/login") is True
    # different host / subdomain / spoofed path must NOT match
    assert AF.should_offer_fill("example.com", "https://evil.com/example.com") is False
    assert AF.should_offer_fill("example.com", "https://sub.example.com") is False
    assert AF.should_offer_fill("", "https://example.com") is False


def test_connector_js_contract():
    assert "QWebChannel" in AF.AUTOFILL_CONNECTOR_JS
    assert "credentialSubmitted" in AF.AUTOFILL_CONNECTOR_JS
    assert "input[type=password]" in AF.AUTOFILL_CONNECTOR_JS
    assert AF.JS_HAS_LOGIN_FORM.strip()


def test_connector_js_wires_focus_and_dismiss():
    js = AF.AUTOFILL_CONNECTOR_JS
    # field-focus → show suggestion; scroll/resize → dismiss
    assert "loginFieldFocused" in js
    assert "dismissSuggestions" in js
    assert "focusin" in js
    assert "getBoundingClientRect" in js
    assert "isLoginField" in js


def test_compute_anchor_places_below_by_default():
    # field near the top → popup sits just below it; no flip
    x, y, above = AF.compute_anchor(
        field_left=0, field_top=100, field_height=20,
        view_global_x=500, view_global_y=300, zoom=1.0,
        popup_w=280, popup_h=120,
        screen_left=0, screen_top=0, screen_right=1920, screen_bottom=1080)
    assert (x, y, above) == (500, 424, False)
    assert isinstance(x, int) and isinstance(y, int)


def test_compute_anchor_flips_above_near_bottom_edge():
    # field near the bottom → popup flips ABOVE the field
    x, y, above = AF.compute_anchor(
        field_left=0, field_top=1000, field_height=20,
        view_global_x=0, view_global_y=0, zoom=1.0,
        popup_w=280, popup_h=120,
        screen_left=0, screen_top=0, screen_right=1920, screen_bottom=1080)
    assert above is True
    assert y == 1000 - 4 - 120  # above the field top, minus the gap


def test_compute_anchor_clamps_horizontally_and_honors_zoom():
    # far-right field is clamped so the popup stays on-screen
    x, _y, _above = AF.compute_anchor(
        field_left=1800, field_top=100, field_height=20,
        view_global_x=0, view_global_y=0, zoom=1.0,
        popup_w=280, popup_h=80,
        screen_left=0, screen_top=0, screen_right=1920, screen_bottom=1080)
    assert x == 1920 - 280
    # zoom scales the CSS-pixel field offset into widget pixels
    x2, _y2, _a2 = AF.compute_anchor(
        field_left=100, field_top=0, field_height=10,
        view_global_x=0, view_global_y=0, zoom=2.0,
        popup_w=100, popup_h=50,
        screen_left=0, screen_top=0, screen_right=1920, screen_bottom=1080)
    assert x2 == 200
