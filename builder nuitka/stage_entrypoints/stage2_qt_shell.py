from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication(sys.argv)
label = QLabel("AIPacs Qt shell stage")
label.setWindowTitle("AIPacs Qt Shell")
label.resize(360, 80)
label.show()

QTimer.singleShot(250, app.quit)
raise SystemExit(app.exec())
