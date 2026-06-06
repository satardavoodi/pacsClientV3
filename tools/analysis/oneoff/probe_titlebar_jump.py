"""Offscreen probe: does the title bar / content origin move when patient
tabs are opened/closed? (UI flicker investigation, 2026-06-06)

Rebuilds the EXACT title-bar recipe from MainWindowWidget.setup_title_bar
(min 84 / max 110 / Fixed policy, margins (10,2,5,2), spacing 10) and wires
the REAL CustomTabManager + PatientTabWidget chips into it, with the real
hidden-tab-bar QTabWidget below. Prints geometry at every transition.

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\probe_titlebar_jump.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QFrame, QHBoxLayout, QLabel, QSizePolicy, QTabWidget,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import QPoint  # noqa: E402

app = QApplication(sys.argv)

from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import (  # noqa: E402
    CustomTabManager,
)

window = QWidget()
root = QVBoxLayout(window)
root.setContentsMargins(0, 0, 0, 0)
root.setSpacing(0)

# --- title bar exactly as MainWindowWidget.setup_title_bar ---
title_bar = QFrame()
title_bar.setObjectName("TitleBar")
title_bar.setMinimumHeight(84)
title_bar.setMaximumHeight(110)
title_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
title_layout = QHBoxLayout(title_bar)
title_layout.setContentsMargins(10, 2, 5, 2)
title_layout.setSpacing(10)
tab_area = QFrame()
tab_area.setObjectName("TabArea")
title_layout.addWidget(tab_area, 1)
right_tab_area = QFrame()
right_tab_area.setObjectName("RightTabArea")
title_layout.addWidget(right_tab_area)
# user info pill (setup_user_info): min 70 / max 74 / Fixed
user_container = QFrame()
user_container.setMinimumHeight(70)
user_container.setMinimumWidth(170)
user_container.setMaximumHeight(74)
user_container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
title_layout.addWidget(user_container)
root.addWidget(title_bar)

# --- central tab widget (home = tab 0, like add_AIPacs_tab) ---
tab_widget = QTabWidget()
home = QLabel("HOME")
tab_widget.addTab(home, "AIPacs")
root.addWidget(tab_widget)

mgr = CustomTabManager(tab_widget, title_bar_tab_area=tab_area,
                       right_tab_area=right_tab_area)

window.resize(1400, 900)
window.show()
app.processEvents()


def snap(label):
    app.processEvents()
    page = tab_widget.currentWidget()
    page_y = page.mapTo(window, QPoint(0, 0)).y() if page is not None else -1
    pane_y = tab_widget.mapTo(window, QPoint(0, 0)).y()
    bar = tab_widget.tabBar()
    print(
        f"{label:28s} title_bar_h={title_bar.height():3d} "
        f"hint={title_bar.sizeHint().height():3d} "
        f"tabwidget_y={pane_y:3d} page_y={page_y:3d} "
        f"qtabbar(visible={bar.isVisible()}, h={bar.height():3d}) "
        f"current={tab_widget.currentIndex()}"
    )


snap("startup (home)")

patient_page = QLabel("PATIENT")
idx = mgr.add_patient_tab("DOE^JOHN", "12345", widget=patient_page, study_uid="S1")
snap("after open patient")

# simulate the user looking at the patient tab, then closing it
mgr.close_patient_tab(idx)
snap("after close patient (home)")

idx2 = mgr.add_patient_tab("ROE^JANE", "67890", widget=QLabel("P2"), study_uid="S2")
snap("after open 2nd patient")
mgr.close_patient_tab(idx2)
snap("after close 2nd (home)")

print("\nDelta check: all title_bar_h and page_y values above should be identical "
      "per column; any difference = the reported jump.")
