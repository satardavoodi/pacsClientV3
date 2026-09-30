"""Regression guard for mixed numeric/text series numbers in grouped Home cards."""

import ast
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py"


def _load_series_sort_value():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    outer = next(
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_show_grouped_patient_studies"
    )
    helper = next(
        node for node in ast.walk(outer)
        if isinstance(node, ast.FunctionDef) and node.name == "_series_sort_value"
    )
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace[helper.name]


def test_mixed_numeric_and_text_series_numbers_have_total_order():
    key = _load_series_sort_value()
    thumbnails = [
        {"series_number": "Screening"},
        {"series_number": "10"},
        {"series_number": 2},
        {"series_number": "02"},
        {"series_number": "Document"},
    ]

    thumbnails.sort(key=key)

    assert [item["series_number"] for item in thumbnails] == [2, "02", "10", "Document", "Screening"]
