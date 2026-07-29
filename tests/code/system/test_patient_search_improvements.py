"""Guards for the Patient Search improvements (2026-06-06).

Pins four behaviors:
  1. Patient-ID search is GLOBAL — socket params contain ONLY the ID
     (no modality, no dates, no name). Previously modality leaked in and an
     ID search missed patients whose modality wasn't ticked.
  2. Date presets re-apply on RE-click (LoginComboField.activated wiring) —
     manually-edited dates snap back when the same preset is picked again.
  3. Start/End date fields show a VISIBLE calendar dropdown button and the
     calendar opens with a Saturday-first weekday header.
  4. The advanced filter popup builds a structured, versioned query;
     multi-ID fan-out and conservative client-side refinement behave.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def stub_qta(monkeypatch):
    """qtawesome's font loading breaks under QT_QPA_PLATFORM=offscreen
    (font dir resolves to None). Widgets only need *an* icon here."""
    from PySide6.QtGui import QIcon
    import qtawesome
    monkeypatch.setattr(qtawesome, "icon", lambda *a, **k: QIcon())
    yield


# ------------------------------------------------- 1: global ID search ----

def test_socket_params_id_search_ignores_all_filters():
    from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService

    params = HomeSearchService._convert_search_data_to_socket_params({
        'patient_id': ' 44820 ',
        'patient_name': 'DOE',
        'modality': ['MR', 'CT'],
        'date_from': '20260601',
        'date_to': '20260606',
    })
    assert params['patient_id'] == '44820'
    for forbidden in ('modality', 'date_from', 'date_to', 'patient_name'):
        assert forbidden not in params, f"{forbidden} must be ignored for ID search"


def test_socket_params_non_id_search_keeps_filters():
    from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService

    params = HomeSearchService._convert_search_data_to_socket_params({
        'patient_id': '',
        'patient_name': 'DOE',
        'modality': ['MR'],
        'date_from': '20260601',
        'date_to': '20260606',
    })
    assert params.get('modality') == ['MR']
    assert params.get('date_from') == '20260601'
    assert params.get('date_to') == '20260606'
    assert params.get('patient_name') == 'DOE'


# ------------------------------------------- 2: preset re-click (widget) ----

def test_preset_reclick_reapplies_dates(qapp, stub_qta):
    from PySide6.QtCore import QDate
    from PacsClient.pacs.workstation_ui.home_ui.patient_search_widget import PatientSearchWidget

    w = PatientSearchWidget()
    # pick "Yesterday"
    idx = w.date_selector.findData("yesterday")
    assert idx >= 0
    w.date_selector.setCurrentIndex(idx)
    yesterday = QDate.currentDate().addDays(-1)
    assert w.date_from_edit.date() == yesterday

    # user manually changes the date...
    w.date_from_edit.setDate(QDate.currentDate().addDays(-30))
    assert w.date_from_edit.date() != yesterday

    # ...re-picking the SAME preset must reset it (activated fires even
    # when the index is unchanged; currentTextChanged does not)
    w.date_selector.activated.emit(idx)
    assert w.date_from_edit.date() == yesterday
    assert w.date_to_edit.date() == yesterday


# --------------------------------------- 3: visible calendar dropdowns ----

def test_date_fields_have_visible_calendar_button_and_saturday_first(qapp, stub_qta):
    from PySide6.QtCore import Qt
    from PacsClient.pacs.workstation_ui.home_ui.patient_search_widget import PatientSearchWidget
    from PacsClient.utils.login_form_styles import LoginComboField, LoginDateField, LoginLineField

    w = PatientSearchWidget()
    assert isinstance(w.patient_id_edit, LoginLineField)
    assert w.patient_id_edit.actionButton() is not None
    assert "border:" in w.patient_id_edit.styleSheet()
    assert isinstance(w.patient_name_edit, LoginLineField)
    assert w.patient_name_edit.actionButton() is not None
    assert w.patient_name_edit.trailingActionEnabled() is False
    assert isinstance(w.study_id, LoginLineField)
    for field in (w.date_from_edit, w.date_to_edit):
        assert isinstance(field, LoginDateField)
        assert field.calendarPopup() is True
        assert "border:" in field.styleSheet()
        cal = field.calendarWidget()
        assert cal is not None
        assert cal.firstDayOfWeek() == Qt.DayOfWeek.Saturday
    assert isinstance(w.date_selector, LoginComboField)


# --------------------------------------------- 4: advanced filter popup ----

def test_parse_patient_ids_handles_separators_and_dupes():
    from PacsClient.pacs.workstation_ui.home_ui.advanced_search_dialog import parse_patient_ids

    assert parse_patient_ids("1,2 3\n4;5,1") == ['1', '2', '3', '4', '5']
    assert parse_patient_ids("") == []
    assert parse_patient_ids("  44820  ") == ['44820']


def test_advanced_dialog_builds_versioned_query(qapp, stub_qta):
    from PacsClient.pacs.workstation_ui.home_ui.advanced_search_dialog import (
        AdvancedSearchDialog, QUERY_VERSION,
    )

    dlg = AdvancedSearchDialog()
    dlg.ids_edit.setPlainText("44820 44534")
    dlg.modality_checks['MR'].setChecked(True)
    dlg.body_part_edit.setText("CHEST")
    dlg.physician_edit.setText("Alizadeh")
    # preset: Last month
    i = dlg.date_preset.findText("Last month")
    dlg.date_preset.setCurrentIndex(i)

    q = dlg.get_query()
    assert q['version'] == QUERY_VERSION
    assert q['patient_ids'] == ['44820', '44534']
    assert q['modalities'] == ['MR']
    assert q['body_part'] == 'CHEST'
    assert q['physician'] == 'Alizadeh'
    assert q['date_from'] and q['date_to'] and q['date_from'] <= q['date_to']
    assert q['age_min'] is None and q['age_max'] is None  # spinboxes at "Any"


def test_advanced_param_sets_fan_out_and_cap():
    from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService

    sets = HomeSearchService._advanced_query_to_param_sets({
        'patient_ids': ['1', '2'],
        'date_from': '20260501',
        'date_to': '20260606',
        'modalities': ['CT'],
    })
    assert len(sets) == 2
    assert {s['patient_id'] for s in sets} == {'1', '2'}
    assert all(s['date_from'] == '20260501' and s['modality'] == ['CT'] for s in sets)

    no_ids = HomeSearchService._advanced_query_to_param_sets({'patient_ids': []})
    assert len(no_ids) == 1 and 'patient_id' not in no_ids[0]

    capped = HomeSearchService._advanced_query_to_param_sets(
        {'patient_ids': [str(i) for i in range(50)]}
    )
    assert len(capped) == 20  # bounded fan-out


def test_advanced_client_filters_conservative():
    from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService

    passes = HomeSearchService._row_passes_advanced_client_filters

    row = {'patient_id': '1', 'body_part': 'CHEST', 'patient_age': '042Y',
           'radiologist_name': 'Dr. Vahid Alizadeh'}
    assert passes(row, {'body_part': 'chest'})
    assert not passes(row, {'body_part': 'knee'})
    assert passes(row, {'age_min': 40, 'age_max': 45})
    assert not passes(row, {'age_min': 50})
    assert passes(row, {'physician': 'alizadeh'})
    assert not passes(row, {'physician': 'someone else'})

    # Missing fields must KEEP the row (server stays authoritative)
    bare = {'patient_id': '2'}
    assert passes(bare, {'body_part': 'chest', 'age_min': 10, 'physician': 'x'})


def test_dicom_age_parsing():
    from PacsClient.pacs.workstation_ui.home_ui.home_search_service import HomeSearchService

    p = HomeSearchService._parse_dicom_age_years
    assert p('042Y') == 42.0
    assert p('42') == 42.0
    assert p('006M') == 0.5
    assert p('') is None
    assert p('N/A') is None
