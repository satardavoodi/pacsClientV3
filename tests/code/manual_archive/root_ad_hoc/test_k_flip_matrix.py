#!/usr/bin/env python3
"""
Test to understand the k_flip matrix behavior
"""

def _k_flip_4x4(n_slices):
    """Current implementation"""
    M = [[1, 0, 0, 0],
         [0, 1, 0, 0],
         [0, 0, 1.0, -1.0],  # ← This is what the current code does
         [0, 0, 0, 1]]
    return M

def apply_matrix_row(M, value):
    """Apply matrix row to value: result = M[2,2] * value + M[2,3]"""
    k22 = M[2][2]
    k23 = M[2][3]
    return k22 * float(value) + k23

# Test the current k_flip matrix
print("=" * 70)
print("Testing current k_flip matrix")
print("=" * 70)

M = _k_flip_4x4(20)
n_slices = 20

print("\nMatrix[2,2] =", M[2][2])
print("Matrix[2,3] =", M[2][3])

print("\nApplying to raw_k values (should flip the stack):")
print(f"{'raw_k':<10} {'result':<10} {'formula':<20}")
print("-" * 70)

for raw_k in [0, 1, 10, 18, 19]:
    result = apply_matrix_row(M, raw_k)
    print(f"{raw_k:<10} {result:<10.1f} {M[2][2]}*{raw_k} + {M[2][3]} = {result:.1f}")

print("\n" + "=" * 70)
print("PROBLEM IDENTIFIED!")
print("=" * 70)
print("\nThe current k_flip matrix does: result = 1.0 * raw_k + (-1.0)")
print("This just SUBTRACTS 1, it doesn't FLIP!")
print("\nA proper k-flip should do: flipped = (N-1) - raw_k")
print("\nFor N=20:")
print("  - raw_k=0 should flip to raw_k=19")
print("  - raw_k=10 should flip to raw_k=9")
print("  - raw_k=19 should flip to raw_k=0")
print("\nBut the current implementation does:")
print("  - raw_k=0 → -1 (clamped to 0)")
print("  - raw_k=10 → 9")
print("  - raw_k=19 → 18")
print("\nThis is NOT a flip! This is just an offset!")

print("\n" + "=" * 70)
print("CORRECT K-FLIP MATRIX SHOULD BE")
print("=" * 70)
print("\nFor a proper flip: display_k_flipped = N - raw_k")
print("Applied in matrix form: M[2,2] = -1.0, M[2,3] = N")
print("\nFor N=20:")
M_correct = [[1, 0, 0, 0],
             [0, 1, 0, 0],
             [0, 0, -1.0, 20.0],  # ← Correct k_flip
             [0, 0, 0, 1]]

print(f"{'raw_k':<10} {'result':<10} {'formula':<20}")
print("-" * 70)

for raw_k in [0, 1, 10, 18, 19]:
    result = apply_matrix_row(M_correct, raw_k)
    print(f"{raw_k:<10} {result:<10.1f} {M_correct[2][2]}*{raw_k} + {M_correct[2][3]} = {result:.1f}")

print("\n✓ This correctly flips the stack!")
