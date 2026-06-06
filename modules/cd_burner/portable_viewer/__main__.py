"""Run the AI-PACS Lite Viewer: ``python -m modules.cd_burner.portable_viewer``."""

import sys

from .viewer_app import main

if __name__ == "__main__":
    sys.exit(main())
