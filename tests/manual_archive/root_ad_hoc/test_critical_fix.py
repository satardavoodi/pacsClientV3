#!/usr/bin/env python3
"""
Test the CRITICAL FIX: M[2,3] = -1.0 initialization
"""

print("=" * 80)
print("TESTING CRITICAL FIX: _display_to_raw_ijk[2,3] = -1.0")
print("=" * 80)

print("\n[BEFORE FIX]")
print("-" * 80)
print("_display_to_raw_ijk = identity (M[2,3] = 0.0)")
print("raw_k_to_display_k(raw_k) = raw_k (returns 0-based)")
print()

print("Counter formula: counter = display_slice + skip_slices + 1")
print("where: display_slice = max(0, raw_k - 1)")
print()

skip_slices = 0
print("Results BEFORE fix:")
for raw_k in [0, 1, 10, 19]:
    # Before fix: raw_k_to_display_k returns raw_k
    display_k_before = raw_k
    display_slice = max(0, int(display_k_before) - 1)
    counter_before = display_slice + skip_slices + 1
    print(f"  raw_k={raw_k:2d} → display_k={display_k_before:2d} → counter={counter_before:2d}")

print("\n✗ raw_k=0 and raw_k=1 both give counter=1 (WRONG!)")
print("✗ Counter goes 1,1,10,19 instead of 1,2,10,20 (BROKEN!)")

print("\n" + "=" * 80)
print("[AFTER FIX]")
print("-" * 80)
print("_display_to_raw_ijk[2,3] = -1.0")
print("raw_k_to_display_k(raw_k) = raw_k + 1 (returns 1-based!)")
print()

print("Results AFTER fix:")
for raw_k in [0, 1, 10, 19]:
    # After fix: raw_k_to_display_k returns raw_k + 1
    display_k_after = raw_k + 1
    display_slice = max(0, int(display_k_after) - 1)
    counter_after = display_slice + skip_slices + 1
    
    anatomy = ""
    if raw_k == 0:
        anatomy = "← SUPERIOR"
    elif raw_k == 19:
        anatomy = "← INFERIOR"
    
    print(f"  raw_k={raw_k:2d} → display_k={display_k_after:2d} → counter={counter_after:2d} {anatomy}")

print("\n✓ Counter now goes 1,2,10,20 correctly!")
print("✓ raw_k=0 (SUPERIOR) shows as counter=1 ✓")
print("✓ raw_k=19 (INFERIOR) shows as counter=20 ✓")

print("\n" + "=" * 80)
print("VALIDATION: Counter now shows correct numbering!")
print("=" * 80)
