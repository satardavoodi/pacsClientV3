#!/usr/bin/env python3
"""
Test the corrected k_flip matrix
"""

def test_k_flip_matrix():
    """Test the corrected k_flip matrix"""
    n_slices = 20
    
    # Corrected k_flip matrix
    M = [[1, 0, 0, 0],
         [0, 1, 0, 0],
         [0, 0, -1.0, float(n_slices)],  # ← Corrected
         [0, 0, 0, 1]]
    
    def apply_k_flip(raw_k):
        """Apply: raw_k = -1.0 * display_k + n_slices = n_slices - display_k"""
        # Actually wait, I need to think about this...
        # The matrix is applied LEFT-to-right: display_to_raw @ vector
        # But we want to get display_k FROM raw_k
        # So if the matrix transforms display→raw, we need the inverse for raw→display
        k22 = M[2][2]  # -1.0
        k23 = M[2][3]  # n_slices
        # raw_k = k22 * display_k + k23
        # raw_k = -1.0 * display_k + n_slices
        # raw_k = n_slices - display_k
        # So: display_k = n_slices - raw_k
        return n_slices - raw_k
    
    print("=" * 80)
    print("CORRECTED K-FLIP MATRIX TEST")
    print("=" * 80)
    print(f"\nFor a {n_slices}-slice series:")
    print(f"Matrix[2,2] = -1.0 (flip coefficient)")
    print(f"Matrix[2,3] = {n_slices} (offset)")
    print()
    print("Transformation: display_k = n_slices - raw_k = 20 - raw_k")
    print()
    
    print(f"{'raw_k':<10} {'display_k':<12} {'Anatomy':<20}")
    print("-" * 80)
    
    # Test cases
    test_cases = [
        (0, "Superior (should be 20)"),
        (1, "1 from Superior (should be 19)"),
        (9, "Middle-upper (should be 11)"),
        (10, "Middle (should be 10)"),
        (11, "Middle-lower (should be 9)"),
        (18, "1 from Inferior (should be 2)"),
        (19, "Inferior (should be 1)"),
    ]
    
    for raw_k, desc in test_cases:
        display_k = apply_k_flip(raw_k)
        print(f"{raw_k:<10} {display_k:<12.0f} {desc:<20}")
    
    print("\n" + "=" * 80)
    print("VERIFICATION")
    print("=" * 80)
    print("\n✓ Superior slice (raw_k=0) → display_k=20")
    print("✓ Inferior slice (raw_k=19) → display_k=1")
    print("\nWith the counter formula: counter = display_k + skip_slices")
    print("  - Superior → counter = 20")
    print("  - Inferior → counter = 1")
    print("\nBUT WAIT! The user wants:")
    print("  - Superior → counter = 1")
    print("  - Inferior → counter = 20")
    print("\nSo this transformation is BACKWARDS!")
    print("\nWe need the INVERSE:")
    print("  - display_k = raw_k + 1 (identity mapping)")
    print("\nNot a flip at all!")

test_k_flip_matrix()
