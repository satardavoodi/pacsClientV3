#!/usr/bin/env python3
"""
Clinical validation test for stack-order convention policy.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def validate_stack_order():
    """Run stack-order validation."""
    print("=" * 80)
    print("STACK-ORDER CONVENTION POLICY VALIDATION")
    print("=" * 80)
    
    # Test that DisplayGeometry K-flip method exists and works
    try:
        from modules.viewer.geometry.display_geometry import DisplayGeometry
        from modules.viewer.geometry.source_geometry import SourceGeometry
        
        print("[OK] DisplayGeometry and SourceGeometry imported successfully")
        
        # Verify K-flip method exists
        assert hasattr(DisplayGeometry, "apply_k_flip_for_stack_order"), \
            "DisplayGeometry missing apply_k_flip_for_stack_order method"
        print("[OK] DisplayGeometry.apply_k_flip_for_stack_order method exists")
        
        # Verify audit method exists
        assert hasattr(DisplayGeometry, "audit_stack_order_convention"), \
            "DisplayGeometry missing audit_stack_order_convention method"
        print("[OK] DisplayGeometry.audit_stack_order_convention method exists")
        
    except Exception as e:
        print(f"[FAIL] Import or method check failed: {e}")
        return False
    
    # Test K-flip matrix algebra
    try:
        import numpy as np
        from modules.viewer.geometry.display_geometry import _k_flip_4x4, _mat4_identity
        
        n_slices = 100
        T_flip = _k_flip_4x4(n_slices)
        
        # Verify the K-flip is correct: k_display = (n-1) - k_raw
        assert abs(T_flip[2, 2] - (-1.0)) < 1e-8, "K-flip diagonal should be -1"
        assert abs(T_flip[2, 3] - float(n_slices - 1)) < 1e-8, "K-flip offset should be n-1"
        print("[OK] K-flip transform matrix is correct")
        
        # Verify double-flip is identity
        T_flip2 = _k_flip_4x4(n_slices)
        T_double = T_flip @ T_flip2
        T_identity = _mat4_identity()
        assert np.allclose(T_double, T_identity, atol=1e-8), \
            "Double K-flip should equal identity"
        print("[OK] Double K-flip returns to identity (reversible)")
        
    except Exception as e:
        print(f"[FAIL] K-flip algebra test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test effective affine contract
    try:
        import numpy as np
        from modules.viewer.geometry.display_geometry import DisplayGeometry
        from modules.viewer.geometry.source_geometry import SourceGeometry
        
        # Create a minimal test SourceGeometry
        sg = SourceGeometry()
        sg.series_uid = "test_series_001"
        sg.n_slices = 50
        sg.raw_ijk_to_lps_4x4 = np.eye(4, dtype=float)
        sg.valid = True
        sg.ijk_to_lps_hash = "test_hash"
        sg.slice_normal = np.array([0.0, 0.0, 1.0])
        sg.origin_ipp = np.array([0.0, 0.0, 0.0])
        
        dg = DisplayGeometry(sg, viewport_id="test_vp")
        
        # Get effective affine before K-flip
        affine_before = dg.effective_display_ijk_to_lps_4x4.copy()
        
        # Apply K-flip
        dg.apply_k_flip_for_stack_order(50, reason="test")
        affine_after = dg.effective_display_ijk_to_lps_4x4.copy()
        
        # Verify the affine changed
        assert not np.allclose(affine_before, affine_after, atol=1e-8), \
            "Effective affine should change after K-flip"
        print("[OK] K-flip updates effective_display_ijk_to_lps correctly")
        
        # Verify operation was recorded
        assert "k_flip" in " ".join(dg._operations), \
            "K-flip operation should be recorded in _operations"
        print("[OK] K-flip operation recorded in operations list")
        
    except Exception as e:
        print(f"[FAIL] Effective affine test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test convention audit logic
    try:
        from modules.viewer.geometry.display_geometry import DisplayGeometry
        from modules.viewer.geometry.source_geometry import SourceGeometry
        import numpy as np
        
        # Create a sagittal series
        sg = SourceGeometry()
        sg.series_uid = "sagittal_test"
        sg.n_slices = 30
        sg.raw_ijk_to_lps_4x4 = np.eye(4, dtype=float)
        sg.valid = True
        sg.ijk_to_lps_hash = "test"
        sg.k_to_sop_uid = {i: f"sop_{i}" for i in range(30)}
        sg.per_frame_geometries = None
        sg.origin_ipp = np.array([0.0, 0.0, 0.0])
        sg.slice_normal = np.array([0.0, 0.0, 1.0])
        
        dg = DisplayGeometry(sg, viewport_id="test_sag")
        convention, matches, transform, reason, direction = dg.audit_stack_order_convention(
            plane="SAGITTAL", body_part="KNEE"
        )
        
        print(f"[OK] Convention audit for SAGITTAL: convention={convention}, matches={matches}, transform={transform}")
        
    except Exception as e:
        print(f"[FAIL] Convention audit test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("=" * 80)
    print("[OK] ALL STACK-ORDER POLICY TESTS PASSED")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = validate_stack_order()
    sys.exit(0 if success else 1)
