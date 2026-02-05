import gc
import time
from pathlib import Path
import numpy as np
import vtk
from PySide6.QtGui import QPixmap
import contextlib
import json
import pydicom
try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"

print("Import block works!")