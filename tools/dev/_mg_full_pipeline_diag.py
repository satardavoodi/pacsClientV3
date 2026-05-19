"""Full FAST pipeline simulation for MG series — saves PNG for visual comparison."""
import sys, os, numpy as np
sys.path.insert(0, ".")

# ── 1. Imports ──────────────────────────────────────────────────────────────
from PacsClient.pacs.patient_tab.utils.dicom_windowing import (
    should_invert_for_display, normalize_window_level,
    auto_window_level_for_mg_array, is_mg_full_range_window_placeholder,
)

# Use direct DICOM for ground truth
import pydicom
dcm_path = r"user_data\patients\dicom\2.16.840.1.113669.632.20.20260512.123757819.1.1\6\Instance_66895.dcm"
ds = pydicom.dcmread(dcm_path)

px_raw = ds.pixel_array
photo   = str(ds.PhotometricInterpretation).upper()
plut    = str(getattr(ds, "PresentationLUTShape", "") or "").upper()
slope   = float(getattr(ds, "RescaleSlope",    1.0) or 1.0)
intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
ww_tag  = float(ds.WindowWidth[0]  if hasattr(ds.WindowWidth,  "__iter__") else ds.WindowWidth)
wc_tag  = float(ds.WindowCenter[0] if hasattr(ds.WindowCenter, "__iter__") else ds.WindowCenter)

print(f"PhotometricInterpretation: {photo}")
print(f"PresentationLUTShape: {plut}")
print(f"slope={slope} intercept={intercept}")
print(f"DICOM WW={ww_tag} WC={wc_tag}")
print(f"raw: min={px_raw.min()} max={px_raw.max()} mean={px_raw.mean():.1f}")

# ── 2. Simulate decode path (what _get_pixel_array returns) ─────────────────
invert = should_invert_for_display(photo, plut)
print(f"should_invert_for_display = {invert}")

arr = px_raw.astype(np.float32, copy=True)
if not (np.isclose(slope, 1.0) and np.isclose(intercept, 0.0)):
    arr = arr * slope + intercept
if invert:
    arr = float(arr.max()) + float(arr.min()) - arr
    print(f"After inversion: min={arr.min():.1f} max={arr.max():.1f} mean={arr.mean():.1f}")
else:
    print("NO inversion applied!")
    print(f"Array: min={arr.min():.1f} max={arr.max():.1f} mean={arr.mean():.1f}")

# ── 3. Simulate _resolve_window_level ────────────────────────────────────────
# Path 1: resolve_cornerstone_like_window_level_from_dicom → (32768, 32768, "dicom_tag")
# Then _normalize_resolved_candidate with treat_mg_full_range_placeholder_as_missing=True
ww_cur, wc_cur = normalize_window_level(
    ww_tag, wc_tag,
    treat_legacy_placeholder_as_missing=True,
    treat_mg_full_range_placeholder_as_missing=True,   # current bug
    modality="MG",
    presentation_intent_type="FOR PRESENTATION",
)
print(f"\n[CURRENT] _normalize_resolved_candidate → ww={ww_cur} wc={wc_cur}")

# Falls through to pixel fallback
if ww_cur is None:
    ww_cur, wc_cur = auto_window_level_for_mg_array(arr)
    print(f"[CURRENT] auto_window_level_for_mg_array → ww={ww_cur:.1f} wc={wc_cur:.1f}")

ww_fix, wc_fix = normalize_window_level(
    ww_tag, wc_tag,
    treat_legacy_placeholder_as_missing=True,
    treat_mg_full_range_placeholder_as_missing=False,  # fix
    modality="MG",
    presentation_intent_type="FOR PRESENTATION",
)
print(f"\n[FIX]     normalize_window_level    → ww={ww_fix} wc={wc_fix}")

# ── 4. Apply W/L (simulate _window_level_to_uint8) ───────────────────────────
def apply_wl_uint8(arr_in, ww, wc):
    lo = wc - ww / 2.0
    hi = wc + ww / 2.0
    out = np.clip((arr_in - lo) / (hi - lo), 0.0, 1.0)
    return (out * 255.0).astype(np.uint8)

disp_cur = apply_wl_uint8(arr, ww_cur, wc_cur)
disp_fix = apply_wl_uint8(arr, ww_fix, wc_fix)

print(f"\n[CURRENT] disp: mean={disp_cur.mean():.1f}  %white={(disp_cur>=250).mean()*100:.1f}%  %black={(disp_cur<=5).mean()*100:.1f}%")
print(f"[FIX]     disp: mean={disp_fix.mean():.1f}  %white={(disp_fix>=250).mean()*100:.1f}%  %black={(disp_fix<=5).mean()*100:.1f}%")

# ── 5. Save PNG thumbnails for visual comparison ─────────────────────────────
try:
    from PIL import Image
    # Save 800px wide thumbnails (scale down from 2796×3584)
    scale = 800 / px_raw.shape[1]
    h = int(px_raw.shape[0] * scale)
    w = 800

    for label, disp in [("current_auto_wl", disp_cur), ("fixed_dicom_wl", disp_fix)]:
        img = Image.fromarray(disp, mode="L")
        img_resized = img.resize((w, h), Image.LANCZOS)
        out_path = f"generated-files/mg_fast_output_{label}.png"
        os.makedirs("generated-files", exist_ok=True)
        img_resized.save(out_path)
        print(f"Saved: {out_path}")
    
    # Also save non-inverted (as if inversion not applied) for comparison
    arr_raw = px_raw.astype(np.float32)
    disp_noninv = apply_wl_uint8(arr_raw, ww_cur, wc_cur)
    img_ni = Image.fromarray(disp_noninv, mode="L").resize((w, h), Image.LANCZOS)
    img_ni.save("generated-files/mg_fast_output_noninverted.png")
    print("Saved: generated-files/mg_fast_output_noninverted.png")
    
    print(f"\n[NO-INV]  disp: mean={disp_noninv.mean():.1f}  %white={(disp_noninv>=250).mean()*100:.1f}%  %black={(disp_noninv<=5).mean()*100:.1f}%")
    print("\nOpen generated-files/ to visually inspect outputs")
except ImportError:
    print("PIL not available - skipping PNG save")
except Exception as e:
    print(f"PNG save error: {e}")
