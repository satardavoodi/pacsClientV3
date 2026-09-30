"""Synthetic Qt checks; no clinical database or assets are opened."""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest


@pytest.fixture
def case_page():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    path = Path('modules/education/case_of_day_widget.py')
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name in ('CaseOfDayCard', 'CaseOfDayPage')]
    ns = {}
    for module in (QtCore, QtGui, QtWidgets):
        ns.update({key: getattr(module, key) for key in dir(module) if not key.startswith('__')})
    theme = dict.fromkeys(['panel_bg', 'panel_alt_bg', 'panel_deep_bg'], '#182333')
    theme.update(dict.fromkeys(['text_primary','text_secondary','text_muted','button_text'], '#e0e8ef'))
    theme.update(dict.fromkeys(['border','accent','accent_hover'], '#5588aa'))
    manager = SimpleNamespace(current_theme=lambda: theme, themeChanged=Mock())
    entries = [SimpleNamespace(case_pk=i+1, diagnosis=f'Synthetic teaching diagnosis {i+1}',
        modality='MR', body_part='Knee', patient_name='Synthetic^Example', patient_id='TEST',
        study_date='20260929', saved_by='Teacher', study_description='Example',
        anatomical_classification='Musculoskeletal', created_at='', updated_at='') for i in range(7)]
    search = Mock(return_value=entries)
    ns.update(Any=Any, Dict=Dict, List=List, Optional=Optional, CaseOfDayEntry=SimpleNamespace,
        get_theme_manager=lambda: manager, search_cases=search, list_body_parts=lambda: ['Knee'],
        _modality_color=lambda _: '#66aadd', _format_relative_time=lambda _: '')
    exec(compile(ast.Module(body=nodes, type_ignores=[]),str(path),'exec'),ns)
    page=ns['CaseOfDayPage']();page.resize(1500,800);page.show()
    for _ in range(5):app.processEvents()
    yield page, search
    page.close();page.deleteLater();app.processEvents()


def settle():
    for _ in range(5):QtWidgets.QApplication.processEvents()


def test_modes_reflow_and_open_same_case_without_search_reload(case_page):
    page, search = case_page
    opened=[];page.case_opened.connect(opened.append)
    assert len(page.view_mode_buttons)==3
    assert page.view_mode_buttons["large"].isChecked()
    large = page._cards[0].size()
    calls=search.call_count
    for mode in ['small','list','large']:
        old_cards = list(page._cards)
        QTest.mouseClick(page.view_mode_buttons[mode], QtCore.Qt.LeftButton)
        assert [key for key, button in page.view_mode_buttons.items() if button.isChecked()] == [mode]
        assert all(card.isHidden() for card in old_cards)
        settle()
        assert len(page._cards)==7 and page.results.text()=='7 cases'
        assert search.call_count==calls
        card=page._cards[2]
        QTest.mouseClick(card,QtCore.Qt.LeftButton)
        assert opened[-1]=={'case_pk':3}
        if mode=='small':
            assert card.width()<large.width() and card.height()<large.height()
        if mode=='list':
            assert len({c.x() for c in page._cards})==1
            assert card.width() >= page.scroll.viewport().width()-10
            assert card.height()<large.height()
        QTest.keyClick(card,QtCore.Qt.Key_Return)
        assert opened[-1]=={'case_pk':3}


def test_resize_and_filtered_empty_results_keep_mode(case_page):
    page, search=case_page
    page.view_mode_buttons["small"].click();settle()
    wide_columns=len({c.x() for c in page._cards})
    page.resize(950,700);settle()
    assert len({c.x() for c in page._cards})<wide_columns
    search.return_value=[]
    page.search.setText('no match');settle()
    assert page._view_mode=='small' and not page._cards
    assert page.results.text()=='0 cases'
    assert search.call_args.kwargs['query']=='no match'
