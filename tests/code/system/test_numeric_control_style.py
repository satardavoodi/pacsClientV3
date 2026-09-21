"""Shared numeric controls retain native stepping and visible arrow targets."""
import pytest
from PySide6 import QtCore, QtWidgets, QtTest


@pytest.mark.parametrize('kind', [QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox])
def test_arrows_are_visible_clickable_and_respect_limits(kind):
    from Qss.numeric_controls import numeric_control_style
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    spin = kind()
    spin.setRange(0, 10)
    spin.setValue(5)
    spin.setStyleSheet(numeric_control_style())
    spin.resize(160, 36)
    spin.show()
    app.processEvents()
    option = QtWidgets.QStyleOptionSpinBox()
    spin.initStyleOption(option)
    style = spin.style()
    up = style.subControlRect(QtWidgets.QStyle.CC_SpinBox, option, QtWidgets.QStyle.SC_SpinBoxUp, spin)
    down = style.subControlRect(QtWidgets.QStyle.CC_SpinBox, option, QtWidgets.QStyle.SC_SpinBoxDown, spin)
    edit = style.subControlRect(QtWidgets.QStyle.CC_SpinBox, option, QtWidgets.QStyle.SC_SpinBoxEditField, spin)
    assert up.width() >= 24 and down.width() >= 24
    assert not up.intersects(down) and not up.intersects(edit)
    picture = spin.grab().toImage()
    for rect in (up, down):
        colors = [picture.pixelColor(x, y).lightnessF()
                  for x in range(rect.center().x()-5, rect.center().x()+6)
                  for y in range(rect.center().y()-4, rect.center().y()+5)]
        assert max(colors) - min(colors) > .45, 'Arrow must contrast with its button'
    QtTest.QTest.mouseClick(spin, QtCore.Qt.LeftButton, pos=up.center())
    assert spin.value() == 6
    QtTest.QTest.mouseClick(spin, QtCore.Qt.LeftButton, pos=down.center())
    assert spin.value() == 5
    spin.setValue(10)
    QtTest.QTest.mouseClick(spin, QtCore.Qt.LeftButton, pos=up.center())
    assert spin.value() == 10
    spin.setEnabled(False)
    QtTest.QTest.mouseClick(spin, QtCore.Qt.LeftButton, pos=down.center())
    assert spin.value() == 10
    spin.close()


def test_shared_svg_assets_are_valid_and_mirrored():
    from pathlib import Path
    from PySide6.QtSvg import QSvgRenderer
    root = Path(__file__).resolve().parents[3]
    mirror = root / 'builder/plugin package/packages/advanced_mpr/payload/python'
    for name in ('up', 'down', 'up-disabled', 'down-disabled'):
        relative = Path('Qss/icons') / ('numeric-' + name + '.svg')
        assert QSvgRenderer(str(root / relative)).isValid()
        assert (root / relative).read_bytes() == (mirror / relative).read_bytes()


def test_no_buttons_and_fractional_step_contract_is_preserved():
    from Qss.numeric_controls import numeric_control_style
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    spin = QtWidgets.QDoubleSpinBox()
    spin.setRange(-2, 2)
    spin.setSingleStep(.25)
    spin.setValue(-.5)
    spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
    spin.setStyleSheet(numeric_control_style())
    spin.stepUp()
    assert spin.value() == -.25
    assert spin.buttonSymbols() == QtWidgets.QAbstractSpinBox.NoButtons
    assert spin.minimum() == -2 and spin.maximum() == 2
    spin.deleteLater()
    app.processEvents()
