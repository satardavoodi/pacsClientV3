"""Execute the real metadata-route gate without importing the clinical Home UI.

This is a pure branch/evaluation-order guard, not a whole-viewer acceptance test.
The manifest probe is synthetic: no live database, filesystem or Qt is accessed.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


SOURCE = (Path(__file__).resolve().parents[3]
          / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py")


@pytest.fixture
def route_gate():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_load_and_display_series_info")
    # Locate the DB-route condition by its existing authoritative dependencies,
    # not a line number or the desired short-circuit order.
    matches = [n.test for n in ast.walk(method) if isinstance(n, ast.If)
               and any(isinstance(x, ast.Name) and x.id == "check_study_complete"
                       for x in ast.walk(n.test))
               and any(isinstance(x, ast.Name) and x.id == "_server_grew"
                       for x in ast.walk(n.test))]
    assert len(matches) == 1
    code = compile(ast.Expression(matches[0]), str(SOURCE), "eval")

    def evaluate(source, grew, probe):
        return eval(code, {
            "self": SimpleNamespace(source_of_patient_load=source),
            "SourceOfPatientLoad": SimpleNamespace(DB="db"),
            "study_uid": "synthetic-study", "_server_grew": grew,
            "check_study_complete": probe,
        })

    return evaluate


@pytest.mark.parametrize("source", ["db", "server", "import", None])
@pytest.mark.parametrize("complete", [False, True])
@pytest.mark.parametrize("grew", [False, True])
def test_route_verdict_preserved_without_local_manifest_scan(route_gate, source, complete, grew):
    calls = []

    def probe(uid):
        calls.append(uid)
        return complete

    result = route_gate(source, grew, probe)
    assert result == ((complete or source == "db") and not grew)
    assert calls == ([] if source == "db" else ["synthetic-study"])


def test_local_metadata_route_does_not_depend_on_readable_dicom_storage(route_gate):
    def unavailable(_uid):
        raise OSError("Synthetic inaccessible storage")

    assert route_gate("db", False, unavailable) is True


def test_server_storage_failure_is_not_converted_to_downloaded(route_gate):
    def unavailable(_uid):
        raise OSError("Synthetic inaccessible storage")

    with pytest.raises(OSError, match="Synthetic"):
        route_gate("server", False, unavailable)
