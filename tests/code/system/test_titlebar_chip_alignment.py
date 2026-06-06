"""Guard: patient chips, logo and user pill share one visual horizontal axis.

2026-06-06: the 70px patient chip anchored to the TOP of its 80px scroll
strip (QHBoxLayout default for constrained-height items) and rendered ~5px
higher than the logo and user pill. Fixed with explicit AlignVCenter at the
title-bar insertion points (custom_tab_manager). This test builds the real
title-bar recipe offscreen and asserts the vertical centers stay within 1px,
for one chip, several chips, and long patient names.
"""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QTabWidget,
    QVBoxLayout, QWidget,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _build(qapp):
    """Replicate MainWindowWidget.setup_title_bar + CustomTabManager wiring."""
    from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import (
        CustomTabManager,
    )

    window = QWidget()
    root = QVBoxLayout(window)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    title_bar = QFrame()
    title_bar.setMinimumHeight(84)
    title_bar.setMaximumHeight(110)
    title_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    title_layout = QHBoxLayout(title_bar)
    title_layout.setContentsMargins(10, 2, 5, 2)
    title_layout.setSpacing(10)
    tab_area = QFrame()
    title_layout.addWidget(tab_area, 1)
    right_tab_area = QFrame()
    title_layout.addWidget(right_tab_area)
    user_pill = QFrame()
    user_pill.setMinimumHeight(70)
    user_pill.setMinimumWidth(170)
    user_pill.setMaximumHeight(74)
    user_pill.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    title_layout.addWidget(user_pill)
    root.addWidget(title_bar)

    tab_widget = QTabWidget()
    tab_widget.addTab(QLabel("HOME"), "AIPacs")
    root.addWidget(tab_widget)

    mgr = CustomTabManager(tab_widget, title_bar_tab_area=tab_area,
                           right_tab_area=right_tab_area)
    window.resize(1600, 900)
    window.show()
    qapp.processEvents()
    return window, title_bar, mgr, user_pill


def _center_y(widget, ref):
    top = widget.mapTo(ref, QPoint(0, 0)).y()
    return top + widget.height() / 2.0


def _chip_centers(mgr, ref):
    return [
        _center_y(chip, ref)
        for chip in mgr.title_bar_tabs.values()
        if chip.isVisible()
    ]


def test_single_chip_centered_with_logo_and_pill(qapp):
    window, title_bar, mgr, user_pill = _build(qapp)
    mgr.add_patient_tab("DOE^JOHN", "12345", widget=QLabel("P1"), study_uid="A1")
    qapp.processEvents()

    logo_c = _center_y(mgr.logo_button, title_bar)
    pill_c = _center_y(user_pill, title_bar)
    chips = _chip_centers(mgr, title_bar)
    assert chips, "patient chip missing"
    for chip_c in chips:
        assert abs(chip_c - logo_c) <= 1.0, f"chip {chip_c} vs logo {logo_c}"
    assert abs(logo_c - pill_c) <= 3.0  # pill is 74 vs 70 — same axis, ±2px


def test_multiple_chips_and_long_names_share_axis(qapp):
    window, title_bar, mgr, user_pill = _build(qapp)
    mgr.add_patient_tab("A" * 60, "1", widget=QLabel("P1"), study_uid="B1")
    mgr.add_patient_tab("HASANZADA MARYAM-LONG-NAME", "44820",
                        widget=QLabel("P2"), study_uid="B2")
    mgr.add_patient_tab("X", "3", widget=QLabel("P3"), study_uid="B3")
    qapp.processEvents()

    logo_c = _center_y(mgr.logo_button, title_bar)
    chips = _chip_centers(mgr, title_bar)
    assert len(chips) == 3
    for chip_c in chips:
        assert abs(chip_c - logo_c) <= 1.0

    # closing one keeps the rest centered
    first_idx = sorted(mgr.title_bar_tabs.keys())[0]
    mgr.close_patient_tab(first_idx)
    qapp.processEvents()
    for chip_c in _chip_centers(mgr, title_bar):
        assert abs(chip_c - logo_c) <= 1.0
