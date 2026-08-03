"""Advanced Search must follow the active Local/Server data source (2026-07-31).

Before the fix, ``_on_advanced_search_requested`` ignored the Local/Server tab
and ALWAYS routed to the PACS server (except an import-date carve-out), so a
Local-mode advanced search hit the server (or errored when no server was
selected). It now reads the DataAccessPanel tab (``get_result()``) — Server mode
→ the selected server; Local/Import mode → the local DB; an import-date filter is
always local (``studies.imported_at`` has no server equivalent).

``_hp_search.py`` imports Qt at module scope, so the routing is source-pinned and
the pure mapping helper is behaviourally tested by extracting just its function
from source (no Qt import).
"""
import ast
from pathlib import Path


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found")


def _hp_search_src() -> str:
    return (_repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
            / "home_panel" / "_hp_search.py").read_text(encoding="utf-8")


def _extract_func(src: str, name: str):
    """Compile+exec a single top-level-or-nested function by name (no imports)."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            node.decorator_list = []  # drop @staticmethod
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns: dict = {}
            exec(compile(mod, "<extracted>", "exec"), ns)
            return ns[name]
    raise AssertionError(f"function {name} not found")


# ── behavioural: the pure advanced-query -> local-criteria mapping ───────────

def test_local_criteria_mapping_maps_supported_fields():
    fn = _extract_func(_hp_search_src(), "_advanced_query_to_local_criteria")
    out = fn({
        'patient_ids': ['52658'],
        'date_from': '20260101', 'date_to': '20260131',
        'modalities': ['CT', 'MR'],
        'import_date_from': '2026-07-01', 'import_date_to': '2026-07-31',
        'body_part': 'HEAD', 'age_min': 10, 'age_max': 90, 'physician': 'dr x',
    })
    assert out['patient_id'] == '52658'
    assert out['modality'] == 'CT,MR'
    assert out['date_from'] == '20260101' and out['date_to'] == '20260131'
    assert out['import_date_from'] == '2026-07-01' and out['import_date_to'] == '2026-07-31'
    # server-only client-refinement fields are NOT mapped to the local query
    assert 'body_part' not in out
    assert 'age_min' not in out and 'age_max' not in out
    assert 'physician' not in out


def test_local_criteria_mapping_multiple_ids_not_mapped_as_single():
    fn = _extract_func(_hp_search_src(), "_advanced_query_to_local_criteria")
    # more than one ID cannot map to the single-value local patient_id filter
    out = fn({'patient_ids': ['1', '2']})
    assert 'patient_id' not in out


def test_local_criteria_mapping_empty_query_is_empty():
    fn = _extract_func(_hp_search_src(), "_advanced_query_to_local_criteria")
    assert fn({}) == {}


# ── source-pins: routing honours the mode, never crosses over ────────────────

def test_advanced_search_reads_the_active_tab():
    src = _hp_search_src()
    body = src[src.find("def _on_advanced_search_requested"):]
    body = body[:body.find("def _advanced_query_to_local_criteria")]
    # reads the DataAccessPanel tab as the mode authority
    assert "self.data_access_panel_widget.get_result()" in body
    assert '_is_server_mode = (_tab == "server")' in body
    # kill switch, default ON
    assert 'os.getenv("AIPACS_ADVANCED_SEARCH_HONORS_MODE", "1") != "0"' in body


def test_server_route_only_in_server_mode_without_import_date():
    src = _hp_search_src()
    body = src[src.find("def _on_advanced_search_requested"):]
    body = body[:body.find("def _advanced_query_to_local_criteria")]
    # the server route is gated on server-mode AND not-import-date
    assert "_route_to_server = (not _has_import_date) and (" in body
    assert "(_honor_mode and _is_server_mode) or (not _honor_mode)" in body
    # server branch calls the server advanced search; local branch the local DB
    assert "self.search_service.search_server_advanced(query)" in body
    assert "self.search_service.search_local(extra_criteria=extra)" in body
    # import date is treated as a local-only field
    assert "_has_import_date = bool(query.get('import_date_from') or query.get('import_date_to'))" in body


def test_mode_switch_clears_stale_results_when_leaving_local():
    src = _hp_search_src()
    fn = src[src.find("def _on_server_tab_changed"):]
    fn = fn[:fn.find("\n    def ", 10)]
    assert "self.patient_list_function_identifier('local')" in fn   # to-Local auto-search
    assert 'os.getenv("AIPACS_SEARCH_CLEAR_ON_MODE_SWITCH", "1") != "0"' in fn
    assert "self.patient_table_widget.clear_table()" in fn
