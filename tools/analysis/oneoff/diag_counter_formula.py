#!/usr/bin/env python3
"""
Diagnostic script to verify counter formula with/without k_flip
"""

def get_display_slice_no_flip(raw_k):
    """Get display_slice when NO k_flip is applied"""
    # With no k_flip, raw_k_to_display_k(raw_k) = raw_k (identity)
    display_k = raw_k  # Identity when no k_flip
    display_slice = max(0, int(display_k) - 1)
    return display_slice

def get_counter_no_flip(raw_k, skip_slices=0):
    """Get counter text when NO k_flip is applied"""
    display_slice = get_display_slice_no_flip(raw_k)
    counter = display_slice + skip_slices + 1
    return counter

def get_display_slice_with_flip(raw_k, n_slices=20):
    """Get display_slice when k_flip IS applied"""
    # With k_flip, raw_k_to_display_k(raw_k) = (n_slices - 1) - raw_k + 1 = n_slices - raw_k
    display_k = n_slices - raw_k
    display_slice = max(0, int(display_k) - 1)
    return display_slice

def get_counter_with_flip(raw_k, n_slices=20, skip_slices=0):
    """Get counter text when k_flip IS applied"""
    display_slice = get_display_slice_with_flip(raw_k, n_slices)
    counter = display_slice + skip_slices + 1
    return counter

# Test case: Series with 20 slices
n_slices = 20
print("=" * 70)
print(f"Counter Formula Test: {n_slices} slices")
print("=" * 70)

print("\n[NO K_FLIP] (Current state after R29 fix)")
print("-" * 70)
print(f"{'raw_k':<10} {'display_k':<12} {'display_slice':<14} {'counter':<10}")
print("-" * 70)
for raw_k in [0, 1, 5, 10, 15, 19]:
    display_k = raw_k
    display_slice = get_display_slice_no_flip(raw_k)
    counter = get_counter_no_flip(raw_k)
    print(f"{raw_k:<10} {display_k:<12} {display_slice:<14} {counter:<10}")

print("\n[WITH K_FLIP] (Previous behavior)")
print("-" * 70)
print(f"{'raw_k':<10} {'display_k':<12} {'display_slice':<14} {'counter':<10}")
print("-" * 70)
for raw_k in [0, 1, 5, 10, 15, 19]:
    display_k = n_slices - raw_k
    display_slice = get_display_slice_with_flip(raw_k, n_slices)
    counter = get_counter_with_flip(raw_k, n_slices)
    print(f"{raw_k:<10} {display_k:<12} {display_slice:<14} {counter:<10}")

print("\n" + "=" * 70)
print("QUESTION: Which behavior shows slice 1 as SUPERIOR?")
print("=" * 70)
print("\nFor a Superior-to-Inferior series (raw_k=0 is Superior):")
print("  - NO K_FLIP: raw_k=0 → counter=1 → SUPERIOR ✓ CORRECT")
print("  - WITH K_FLIP: raw_k=0 → counter=20 → INFERIOR ✗ WRONG")
print("\nSo our R29 fix (no K_FLIP for UNKNOWN planes) SHOULD BE CORRECT!")
print("\nBUT the user reports slices STILL show inverted numbering...")
print("\nPossible explanations:")
print("  1. The counter is being displayed from a different code path")
print("  2. The source geometry is reading slices in the WRONG order (I->S)")
print("  3. The matrix inversion is broken in some way")
print("  4. The skip_slices offset is wrong")
print("  5. There's a VTK-specific counter display that's different")
