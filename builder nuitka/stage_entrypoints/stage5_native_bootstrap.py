from __future__ import annotations

import os

import SimpleITK
import vtkmodules.all
import vtkmodules.qt.QVTKRenderWindowInteractor
import vtkmodules.util.numpy_support

if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
    print("AIPacs stage5 native bootstrap OK")
    raise SystemExit(0)
