#!/usr/bin/env python3
"""
Final diagnostic: Trace through the exact counter calculation with R29 fix applied
"""

print("=" * 80)
print("EXACT COUNTER CALCULATION TRACE (R29 FIX APPLIED)")
print("=" * 80)

print("\n[SETUP]")
print("-" * 80)
print("Data: Series 3 (20 slices, UNKNOWN/SHOULDER anatomy)")
print("DICOM order: Superior→Inferior (raw_k=0 is Superior, raw_k=19 is Inferior)")
print("  First slice IPP z-coordinate: +31.5 (SUPERIOR)")
print("  Last slice IPP z-coordinate: -55.7 (INFERIOR)")

print("\n[R29 FIX APPLIED]")
print("-" * 80)
print("R29 prevented k_flip for UNKNOWN planes")
print("Therefore: recommended_transform=NONE (per latest logs)")
print("Therefore: _display_to_raw_ijk = identity matrix")
print("Therefore: raw_k_to_display_k(raw_k) = raw_k (identity transformation)")

print("\n[COUNTER CALCULATION (viewer_2d.py:963)]")
print("-" * 80)
print("Formula: counter = display_slice + skip_slices + 1")
print("where: display_slice = get_display_slice()")
print("where: get_display_slice() = max(0, raw_k_to_display_k(raw_k) - 1)")
print()

skip_slices = 0
print(f"Assuming skip_slices = {skip_slices}")
print()

for raw_k in [0, 1, 10, 19]:
    # Step 1: Apply identity transformation
    display_k_intermediate = raw_k  # raw_k_to_display_k returns raw_k
    
    # Step 2: Apply get_display_slice logic
    display_slice = max(0, int(display_k_intermediate) - 1)
    
    # Step 3: Apply counter formula
    counter = display_slice + skip_slices + 1
    
    anatomy = ""
    if raw_k == 0:
        anatomy = "SUPERIOR"
    elif raw_k == 19:
        anatomy = "INFERIOR"
    elif raw_k == 10:
        anatomy = "MIDDLE"
    
    print(f"raw_k={raw_k:2d} → display_k={display_k_intermediate:2d} → display_slice={display_slice:2d} → counter={counter:2d}  [{anatomy}]")

print("\n" + "=" * 80)
print("VALIDATION")
print("=" * 80)
print("\n✓ raw_k=0 (SUPERIOR) → counter=1 → CORRECT!")
print("✗ raw_k=1  → counter=1 → DUPLICATE! BUG!")
print("✓ raw_k=19 (INFERIOR) → counter=19 → CORRECT!")
print()

print("ISSUE FOUND:")
print("-" * 80)
print("The get_display_slice() formula max(0, raw_k - 1) has a flaw:")
print("  - raw_k=0 → max(0, -1) = 0 → counter = 0 + 0 + 1 = 1")
print("  - raw_k=1 → max(0, 0) = 0 → counter = 0 + 0 + 1 = 1")
print()
print("BOTH raw_k=0 and raw_k=1 produce counter=1!")
print("This suggests the formula was designed for a DIFFERENT transformation.")
print()

print("=" * 80)
print("HYPOTHESIS")
print("=" * 80)
print("\nMaybe raw_k_to_display_k() is supposed to return 1-based values?")
print("If raw_k_to_display_k(raw_k) = raw_k + 1:")
print("  - raw_k=0 → display_k=1 → display_slice=max(0,0)=0 → counter=1 ✓")
print("  - raw_k=1 → display_k=2 → display_slice=max(0,1)=1 → counter=2 ✓")
print("  - raw_k=19 → display_k=20 → display_slice=max(0,19)=19 → counter=20 ✓")
print()
print("This would be CORRECT!")
print("\nSo maybe the real issue is that raw_k_to_display_k() with identity matrix")
print("returns 0-based values when it should return 1-based values?")
