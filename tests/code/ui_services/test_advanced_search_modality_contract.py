"""Advanced queries use the same scalar modality socket contract as basic search."""
import pytest
import ast
from pathlib import Path

# These pure methods do not require Home's Qt/database/runtime initialization.
_source = Path(__file__).resolve().parents[3] / 'PacsClient/pacs/workstation_ui/home_ui/home_search_service.py'
_tree = ast.parse(_source.read_text(encoding='utf-8-sig'))
_methods = [n for n in ast.walk(_tree) if isinstance(n, ast.FunctionDef) and n.name in {
    '_advanced_query_to_param_sets', '_row_passes_advanced_client_filters', '_parse_dicom_age_years'}]
_class = ast.ClassDef(name='HomeSearchService', bases=[], keywords=[], body=_methods, decorator_list=[])
_namespace = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=[_class], type_ignores=[])), str(_source), 'exec'), _namespace)
HomeSearchService = _namespace['HomeSearchService']


@pytest.mark.parametrize('modalities,expected', [(['MR'], 'MR'), (['MR', 'CT'], 'MR,CT')])
def test_advanced_modalities_are_accepted_by_scalar_server_contract(modalities, expected):
    query = {'modalities': modalities, 'date_from': '20260829',
             'date_to': '20260928', 'body_part': 'knee'}
    params, = HomeSearchService._advanced_query_to_param_sets(query)
    # GetPatientList consumes a scalar, splitting comma-separated selections.
    assert isinstance(params['modality'], str)
    assert params['modality'] == expected
    assert params['modality'].strip().upper().split(',') == modalities
    assert params['date_from'] == query['date_from']
    assert params['date_to'] == query['date_to']
    assert HomeSearchService._row_passes_advanced_client_filters({'body_part': 'KNEE'}, query)
    assert not HomeSearchService._row_passes_advanced_client_filters({'body_part': 'CHEST'}, query)


def test_multi_patient_queries_keep_scalar_modalities_without_mutating_query():
    query = {'modalities': ['MR', 'CT'], 'patient_ids': ['synthetic-a', 'synthetic-b']}
    params = HomeSearchService._advanced_query_to_param_sets(query)
    assert [p['modality'] for p in params] == ['MR,CT', 'MR,CT']
    assert [p['patient_id'] for p in params] == query['patient_ids']
    assert query['modalities'] == ['MR', 'CT']


def test_unselected_modality_stays_unrestricted():
    params, = HomeSearchService._advanced_query_to_param_sets({'modalities': []})
    assert 'modality' not in params


@pytest.mark.parametrize('row,expected', [
    ({'body_parts': ['BRAIN', 'SPINE']}, False),
    ({'body_parts': ['KNEE']}, True),
    ({'body_parts': ['BRAIN', 'LEFT KNEE']}, True),
    ({'body_parts': []}, False),
    ({}, False),
    ({'body_parts': [None, '', '  ']}, False),
    ({'body_part_examined': 'KNEE'}, True),
    ({'body_parts': [], 'BodyPartExamined': 'KNEE'}, True),
])
def test_body_part_filter_consumes_server_array_and_requires_a_match(row, expected):
    assert HomeSearchService._row_passes_advanced_client_filters(row, {'body_part': 'knee'}) is expected


def test_no_body_part_query_keeps_unclassified_rows():
    assert HomeSearchService._row_passes_advanced_client_filters({}, {})
