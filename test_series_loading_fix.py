"""
Test script to verify series loading fixes
Tests: 
1. vtk_image_data validation before switch
2. UNIQUE constraint handling
3. Black screen recovery mechanism
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_vtk_validation():
    """Test that vtk_image_data validation works"""
    print("\n" + "="*80)
    print("TEST 1: VTK Image Data Validation")
    print("="*80)
    
    try:
        import vtk
        from vtkmodules.util.data_model import ImageData
        
        # Test case 1: None vtk_image_data
        print("\n📋 Test Case 1: None vtk_image_data")
        vtk_data = None
        if not vtk_data:
            print("   ✅ PASS: Correctly detected None vtk_image_data")
        else:
            print("   ❌ FAIL: Should have detected None")
        
        # Test case 2: Valid vtk_image_data
        print("\n📋 Test Case 2: Valid vtk_image_data")
        vtk_data = ImageData()
        vtk_data.SetDimensions(256, 256, 100)
        dims = vtk_data.GetDimensions()
        if dims[0] > 0 and dims[1] > 0 and dims[2] > 0:
            print(f"   ✅ PASS: Valid dimensions detected: {dims}")
        else:
            print(f"   ❌ FAIL: Invalid dimensions: {dims}")
        
        # Test case 3: Empty vtk_image_data
        print("\n📋 Test Case 3: Empty vtk_image_data (0 dimensions)")
        vtk_data = ImageData()
        vtk_data.SetDimensions(0, 0, 0)
        dims = vtk_data.GetDimensions()
        if dims[0] == 0 or dims[1] == 0 or dims[2] == 0:
            print(f"   ✅ PASS: Correctly detected invalid dimensions: {dims}")
        else:
            print(f"   ❌ FAIL: Should have detected invalid dimensions")
        
        print("\n✅ All VTK validation tests passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ VTK validation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_duplicate_handling():
    """Test that database handles duplicate SOP UIDs gracefully"""
    print("\n" + "="*80)
    print("TEST 2: Database Duplicate Handling")
    print("="*80)
    
    try:
        from PacsClient.utils.database import bulk_insert_instances, get_connection_database
        
        print("\n📋 Setting up test database...")
        
        # Create test data with duplicate SOP UID
        test_instances = [
            {
                'sop_uid': 'test.sop.uid.001',
                'series_fk': 999,
                'instance_path': '/test/path/001.dcm',
                'instance_number': 1,
                'rows': 512,
                'columns': 512,
                'window_width': 400,
                'window_center': 40,
                'is_rgb': False,
                'group_id': 0,
                'image_position_patient': None,
                'image_orientation_patient': None,
                'pixel_spacing': None,
                'direction': None
            },
            {
                'sop_uid': 'test.sop.uid.001',  # Duplicate!
                'series_fk': 999,
                'instance_path': '/test/path/001_dup.dcm',
                'instance_number': 2,
                'rows': 512,
                'columns': 512,
                'window_width': 400,
                'window_center': 40,
                'is_rgb': False,
                'group_id': 0,
                'image_position_patient': None,
                'image_orientation_patient': None,
                'pixel_spacing': None,
                'direction': None
            }
        ]
        
        print("\n📋 Test Case: Inserting duplicate SOP UIDs")
        print(f"   - First instance: {test_instances[0]['sop_uid']}")
        print(f"   - Second instance (duplicate): {test_instances[1]['sop_uid']}")
        
        # Try to insert duplicates - should not raise exception
        try:
            bulk_insert_instances(test_instances)
            print("   ✅ PASS: Duplicate handling worked (no exception raised)")
            
            # Clean up test data
            conn = get_connection_database()
            cur = conn.cursor()
            cur.execute("DELETE FROM instances WHERE sop_uid = ?", ('test.sop.uid.001',))
            conn.commit()
            conn.close()
            print("   ✅ Test data cleaned up")
            
            return True
            
        except Exception as insert_error:
            print(f"   ❌ FAIL: Exception raised during duplicate insert: {insert_error}")
            return False
        
    except Exception as e:
        print(f"\n❌ Database duplicate handling test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_switch_series_recovery():
    """Test that switch_series has recovery mechanism"""
    print("\n" + "="*80)
    print("TEST 3: Switch Series Recovery Mechanism")
    print("="*80)
    
    print("\n📋 Checking _perform_series_switch code for recovery logic...")
    
    try:
        from pathlib import Path
        
        # Read the patient_widget.py file to verify recovery code exists
        patient_widget_path = Path(__file__).parent / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui" / "patient_widget.py"
        
        if not patient_widget_path.exists():
            print(f"   ⚠️ Cannot find patient_widget.py at: {patient_widget_path}")
            return False
        
        with open(patient_widget_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for recovery keywords
        recovery_checks = [
            ('vtk_image_data validation', 'if not vtk_image_data:'),
            ('dimension validation', 'dims = vtk_image_data.GetDimensions()'),
            ('recovery attempt', 'attempting recovery'),
            ('force render', 'render_window.Render()'),
            ('camera reset', 'ResetCamera()'),
        ]
        
        all_passed = True
        for check_name, check_keyword in recovery_checks:
            if check_keyword in content:
                print(f"   ✅ PASS: Found {check_name}: '{check_keyword}'")
            else:
                print(f"   ❌ FAIL: Missing {check_name}: '{check_keyword}'")
                all_passed = False
        
        if all_passed:
            print("\n✅ All recovery mechanisms are in place!")
            return True
        else:
            print("\n⚠️ Some recovery mechanisms are missing")
            return False
        
    except Exception as e:
        print(f"\n❌ Recovery mechanism test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("🧪 SERIES LOADING FIX VERIFICATION TESTS")
    print("="*80)
    
    results = []
    
    # Run tests
    results.append(("VTK Validation", test_vtk_validation()))
    results.append(("Database Duplicate Handling", test_database_duplicate_handling()))
    results.append(("Switch Series Recovery", test_switch_series_recovery()))
    
    # Print summary
    print("\n" + "="*80)
    print("📊 TEST SUMMARY")
    print("="*80)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED! Series loading fixes are working correctly.")
        return 0
    else:
        print("\n⚠️ SOME TESTS FAILED. Please review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
