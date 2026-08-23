"""One-off: render the new Consultation & Education settings tab to a PNG.

Offscreen visual smoke — builds the REAL SettingsTabWidget, activates the new
tab (lazy builder runs), and saves a screenshot for layout review. Reads live
machine config; writes nothing.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import (  # noqa: E402
    SettingsTabWidget,
)

tabs = SettingsTabWidget()
tabs.resize(1280, 900)
target = None
for i in range(tabs.count()):
    if tabs.tabText(i) == "Consultation & Education":
        target = i
        break
assert target is not None, "tab not registered"
tabs.setCurrentIndex(target)
tabs._ensure_tab_initialized(target)
app.processEvents()
tabs.show()
app.processEvents()
out = ROOT / "consult_edu_settings_preview.png"
tabs.grab().save(str(out))
print("saved", out)
print("widget built:", tabs.consultation_education_settings is not None)
