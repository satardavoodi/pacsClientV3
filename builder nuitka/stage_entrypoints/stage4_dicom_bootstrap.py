from __future__ import annotations

import os

import numpy
import pydicom
import pydicom.encoders
import pydicom.pixel_data_handlers
import pydicom.pixel_data_handlers.numpy_handler

if os.environ.get("AIPACS_STAGE_SMOKE") == "1":
    print("AIPacs stage4 DICOM bootstrap OK")
    raise SystemExit(0)
