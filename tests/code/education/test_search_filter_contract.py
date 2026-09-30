"""Synthetic education filters; all database access is forbidden."""
from types import SimpleNamespace
import pytest
from modules.education import course_database as courses, case_of_day_database as cases


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Filter tests must not open a database')
    monkeypatch.setattr(courses, 'get_db_connection', forbidden)
    monkeypatch.setattr(cases, 'get_db_connection', forbidden)


@pytest.mark.parametrize('stored,selected', [
    ('MR', 'MRI'), ('MRI', 'MR'), ('DX', 'X-Ray'), ('CR', 'X-ray'),
    ('PX', 'X-Ray'), ('MG', 'Mammography'), ('PT', 'PET'),
    ('RF', 'Fluoroscopy'), ('MR,CT', 'MRI'),
])
def test_modality_aliases_across_courses_and_cases(monkeypatch, stored, selected):
    row = {'course_name': 'Synthetic knee', 'modality': stored}
    entry = SimpleNamespace(modality=stored, body_part='KNEE')
    monkeypatch.setattr(courses, 'get_all_courses', lambda: [row])
    monkeypatch.setattr(cases, 'get_all_cases', lambda: [entry])
    assert courses.search_and_filter_courses(modality=[selected]) == [row]
    assert cases.search_cases(modality=selected) == [entry]


def test_filters_intersect_and_text_is_trimmed(monkeypatch):
    row = dict(course_name='Knee lesson', modality='MR', body_regions=['MSK'],
               tags=['Trauma'], level='Intermediate', is_my_course=True)
    other = {**row, 'modality': 'CT'}
    monkeypatch.setattr(courses, 'get_all_courses', lambda: [row, other])
    assert courses.search_and_filter_courses(query=' trauma ', modality=['MRI'],
        body_regions=['msk'], tags=['trauma'], level='intermediate', is_my_course=True) == [row]
    assert courses.search_and_filter_courses(query='absent', modality=['MRI']) == []
    assert courses.search_and_filter_courses() == [row, other]


def test_case_body_part_case_and_whitespace(monkeypatch):
    entry = SimpleNamespace(modality='MR', body_part=' KNEE ')
    monkeypatch.setattr(cases, 'get_all_cases', lambda: [entry])
    assert cases.search_cases(modality='MRI', body_part='knee') == [entry]
    assert cases.search_cases(modality='CT') == []


@pytest.mark.parametrize('stored,selected', [('CT', 'MRI'), ('NM', 'SPECT'), ('MG', 'X-Ray'), ('', 'MRI')])
def test_unrelated_or_unknown_modalities_do_not_match(stored, selected):
    assert not courses.modality_matches(stored, selected)


def test_case_text_search_combines_with_modality_and_body(monkeypatch):
    fields = {key: '' for key in cases.CaseOfDayEntry.__dataclass_fields__}
    fields.update(case_pk=1, modality='MR', body_part='KNEE', diagnosis='Synthetic trauma')
    entry = cases.CaseOfDayEntry(**fields)
    monkeypatch.setattr(cases, 'get_all_cases', lambda: [entry])
    assert cases.search_cases(' trauma ', 'MRI', 'knee') == [entry]
    assert cases.search_cases('absent', 'MRI', 'knee') == []
    assert cases.search_cases('trauma', 'MRI', 'chest') == []


@pytest.mark.parametrize('view', ['imported', 'created', 'downloaded'])
def test_my_courses_search_preserves_view_and_finds_tags(monkeypatch, view):
    import ast
    from pathlib import Path
    from unittest.mock import Mock
    path = Path(courses.__file__).with_name('education_module_redesigned.py')
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == 'load_courses' and 'current_view' in ast.unparse(n))
    rows = [dict(course_name='Lesson', tags=['Trauma'], modality='MR',
                 is_my_course=True, is_downloaded=v == 'downloaded',
                 content_origin='imported' if v == 'imported' else 'local')
            for v in ('imported', 'created', 'downloaded')]
    monkeypatch.setattr(courses, 'get_all_courses', lambda: rows)
    ns = dict(get_all_courses=lambda: rows,
              search_and_filter_courses=courses.search_and_filter_courses,
              course_matches_query=courses.course_matches_query)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), ns)
    widget = SimpleNamespace(_ensure_my_courses_samples=lambda: None, current_view=view,
        current_search=' trauma ', downloaded_filters={'modality': ['MRI']},
        current_resource_filter=None, update_grid=Mock(), results_label=Mock())
    ns['load_courses'](widget)
    widget.update_grid.assert_called_once_with([rows[('imported', 'created', 'downloaded').index(view)]])
