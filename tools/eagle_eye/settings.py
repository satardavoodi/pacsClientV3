"""Source-only server settings console; does not launch a viewer or a listener."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

if __name__ == '__main__':
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        raise SystemExit('Supply one absolute server configuration path.')
    from modules.ai_imaging.eagle_eye_remote.service_host import service_config
    config = service_config(sys.argv[1])
    if not config.get('service_managed'):
        raise SystemExit('This console requires an independently managed service configuration.')
    from modules.ai_imaging.eagle_eye_remote.launch import configure
    configure(['settings', '--eagle-eye-mode', 'server', '--eagle-eye-config', sys.argv[1]])
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.eagle_eye_settings import EagleEyeSettingsWidget
    app = QApplication(['Eagle Eye Server Settings'])
    widget = EagleEyeSettingsWidget()
    widget.setWindowTitle('AI-PACS Eagle Eye Server Settings')
    widget.resize(940, 850)
    widget.show()
    raise SystemExit(app.exec())
