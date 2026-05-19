"""Diagnostic: trace FAST pipeline W/L resolution for MONOCHROME1 MG image."""
import sys, numpy as np, math
sys.path.insert(0, ".")

import pydicom
dcm_path = r"user_data\patients\dicom\2.16.840.1.113669.632.20.20260512.123757819.1.1\6\Instance_66895.dcm"
ds = pydicom.dcmread(dcm_path)
px_raw = ds.pixel_array
print("--- Raw DICOM pixel stats ---")
print("PhotometricInterpretation:", ds.PhotometricInterpretation)
plut_val = getattr(ds, "PresentationLUTShape", "MISSING")
print("PresentationLUTShape:", plut_val)
print(f"raw min={px_raw.min()} max={px_raw.max()} mean={px_raw.mean():.1f}")

ww_tag = float(ds.WindowWidth[0] if hasattr(ds.WindowWidth, "__iter__") else ds.WindowWidth)
wc_tag = float(ds.WindowCenter[0] if hasattr(ds.WindowCenter, "__iter__") else ds.WindowCenter)
print(f"DICOM WW={ww_tag} WC={wc_tag}")

# 2. Simulate what _get_pixel_array does for MONOCHROME1
from PacsClient.pacs.patient_tab.utils.dicom_windowing import should_invert_for_display
photometric = str(ds.PhotometricInterpretation).upper()
plut = str(getattr(ds, "PresentationLUTShape", "") or "").upper()
invert = should_invert_for_display(photometric, plut)
print(f"\nshould_invert_for_display({photometric!r}, {plut!r}) = {invert}")

arr = px_raw.astype(np.float32, copy=True)
slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
print(f"slope={slope} intercept={intercept}")

if invert:
    arr = float(arr.max()) + float(arr.min()) - arr
    print(f"AFTER inversion: min={arr.min():.1f} max={arr.max():.1f} mean={arr.mean():.1f}")
else:
    print("NO inversion applied")

# 3. Simulate _resolve_window_level: current (placeholder flag=True) vs fix (=False)
from PacsClient.pacs.patient_tab.utils.dicom_windowing import (
    normalize_window_level, auto_window_level_for_mg_array
)

ww_cur, wc_cur = normalize_window_level(
    ww_tag, wc_tag,
    treat_legacy_placeholder_as_missing=True,
    treat_mg_full_range_placeholder_as_missing=True,   # current bug
    modality="MG",
    presentation_intent_type="FOR PRESENTATION",
)
print("\n--- W/L with treat_mg_full_range_placeholder_as_missing=True (CURRENT) ---")
print(f"normalize_window_level -> ww={ww_cur} wc={wc_cur}")
if ww_cur is None:
    ww_auto, wc_auto = auto_window_level_for_mg_array(arr)
    print(f"auto_window_level_for_mg_array(inverted arr) -> ww={ww_auto:.1f} wc={wc_auto:.1f}")
    ww_use, wc_use = ww_auto, wc_auto
else:
    ww_use, wc_use = ww_cur, wc_cur

ww_fix, wc_fix = normalize_window_level(
    ww_tag, wc_tag,
    treat_legacy_placeholder_as_missing=True,
    treat_mg_full_range_placeholder_as_missing=False,  # fix
    modality="MG",
    presentation_intent_type="FOR PRESENTATION",
)
print("\n--- W/L with treat_mg_full_range_placeholder_as_missing=False (FIX) ---")
print(f"normalize_window_level -> ww={ww_fix} wc={wc_fix}")

# 4. Apply both W/Ls to the inverted array and compare outputs
def apply_wl(arr_in, ww, wc):
    lo = wc - ww / 2.0
    hi = wc + ww / 2.0
    out = np.clip((arr_in - lo) / (hi - lo), 0, 1) * 255
    return out.astype(np.uint8)

img_current = apply_wl(arr, ww_use, wc_use)
img_fixed   = apply_wl(arr, ww_fix, wc_fix)

print("\n=== OUTPUT PIXEL COMPARISON (applied to inverted arr) ===")
print(f"CURRENT (auto W/L {ww_use:.0f}/{wc_use:.0f}): mean={img_current.mean():.1f}  %white={(img_current>=250).mean()*100:.1f}%  %black={(img_current<=5).mean()*100:.1f}%")
print(f"FIX     (DICOM W/L {ww_fix:.0f}/{wc_fix:.0f}): mean={img_fixed.mean():.1f}  %white={(img_fixed>=250).mean()*100:.1f}%  %black={(img_fixed<=5).mean()*100:.1f}%")
print()
print("Expected for correct MG: mostly dark (mean<128, high %black) = correct mammogram")
print("Brighter output = WORSE")
