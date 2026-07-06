from __future__ import annotations

import ast
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SERVER = REPO / "tools" / "testing" / "aipacs_control_mcp" / "server.py"


def _mcp_tool_names() -> set[str]:
    mod = ast.parse(SERVER.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in mod.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "tool"
            ):
                names.add(node.name)
    return names


def test_browser_tools_are_first_class_mcp_tools():
    names = _mcp_tool_names()
    expected = {
        "browser_open",
        "web_search",
        "browser_open_url",
        "browser_get_url",
        "browser_get_title",
        "browser_get_text",
        "browser_get_html",
        "browser_get_links",
        "browser_dom_summary",
        "browser_dom_snapshot",
        "browser_accessibility_tree",
        "browser_get_buttons",
        "browser_get_inputs",
        "browser_find_element",
        "browser_extract_table",
        "browser_screenshot",
        "browser_selected_text",
        "browser_selected_element",
        "browser_scroll_state",
        "browser_network",
        "browser_clear_network",
        "browser_structured_data",
        "browser_fill_field",
        "browser_type_text",
        "browser_click",
        "browser_scroll",
        "browser_submit_form",
    }
    assert expected <= names


def test_viewport_vision_and_measurement_tools_are_first_class_mcp_tools():
    names = _mcp_tool_names()
    expected = {
        "get_viewport_context",
        "capture_viewport",
        "activate_tool",
        "measure_distance",
        "get_measurements",
    }
    assert expected <= names


def test_raw_command_accepts_mode_parameter():
    mod = ast.parse(SERVER.read_text(encoding="utf-8"))
    raw = next(
        node for node in mod.body
        if isinstance(node, ast.FunctionDef) and node.name == "raw_command"
    )
    args = {arg.arg for arg in raw.args.args}
    assert "mode" in args
