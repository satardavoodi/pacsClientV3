"""
Test script for Storage Monitoring & Cleanup Feature

This script tests the basic functionality of the storage monitoring and cleanup modules.
"""

import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add PacsClient to path
pacs_client_dir = Path(__file__).parent
if str(pacs_client_dir) not in sys.path:
    sys.path.insert(0, str(pacs_client_dir))


def test_storage_calculator():
    """Test storage calculator module"""
    print("\n" + "="*60)
    print("TEST 1: Storage Calculator Module")
    print("="*60)
    
    try:
        from PacsClient.utils.storage_calculator import (
            get_drive_info,
            get_total_storage_metrics,
            StorageMetrics
        )
        
        # Test drive info
        print("\n1. Testing drive info...")
        from PacsClient.utils.config import SOURCE_PATH
        total, used, free = get_drive_info(SOURCE_PATH)
        print(f"   [OK] Drive info retrieved")
        print(f"     Total: {total / (1024**3):.2f} GB")
        print(f"     Used: {used / (1024**3):.2f} GB")
        print(f"     Free: {free / (1024**3):.2f} GB")
        
        # Test full metrics calculation
        print("\n2. Testing full metrics calculation...")
        metrics = get_total_storage_metrics(use_cache=False)
        print(f"   [OK] Metrics calculated")
        print(f"     DICOM Files: {metrics.format_size(metrics.source_size)}")
        print(f"     Thumbnails: {metrics.format_size(metrics.thumbnails_size)}")
        print(f"     Attachments: {metrics.format_size(metrics.attachments_size)}")
        print(f"     Total PACS: {metrics.format_size(metrics.total_pacs_size)}")
        print(f"     Free Space: {metrics.free_percent:.1f}%")
        
        # Test warning thresholds
        print("\n3. Testing warning thresholds...")
        if metrics.free_percent < 10:
            print(f"   [WARNING] CRITICAL: Disk space is very low!")
        elif metrics.free_percent < 20:
            print(f"   [WARNING] Disk space is getting low")
        else:
            print(f"   [OK] Disk space is OK")
        
        print("\n   [PASSED] Storage Calculator")
        return True
        
    except Exception as e:
        print(f"\n   [FAILED] Storage Calculator - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_functions():
    """Test database query functions"""
    print("\n" + "="*60)
    print("TEST 2: Database Query Functions")
    print("="*60)
    
    try:
        from PacsClient.utils.database import (
            get_patients_ordered_by_date,
            get_patient_storage_info,
            init_database
        )
        
        # Initialize database
        print("\n1. Initializing database...")
        init_database()
        print(f"   [OK] Database initialized")
        
        # Test getting patients
        print("\n2. Testing patient query (oldest first)...")
        patients = get_patients_ordered_by_date(limit=5, oldest_first=True)
        print(f"   [OK] Found {len(patients)} patients")
        
        if patients:
            print(f"\n   First patient:")
            p = patients[0]
            print(f"     Name: {p['patient_name']}")
            print(f"     ID: {p['patient_id']}")
            print(f"     Studies: {p['study_count']}")
            print(f"     Earliest: {p['earliest_study']}")
            
            # Test storage info for first patient
            print(f"\n3. Testing storage info retrieval...")
            storage_info = get_patient_storage_info(p['patient_pk'])
            print(f"   [OK] Storage info retrieved")
            print(f"     Study UIDs: {len(storage_info['study_uids'])}")
            print(f"     Study paths: {len(storage_info['study_paths'])}")
            print(f"     Series paths: {len(storage_info['series_paths'])}")
            print(f"     Instance paths: {len(storage_info['instance_paths'])}")
        else:
            print(f"   [INFO] No patients in database yet")
        
        print("\n   [PASSED] Database Functions")
        return True
        
    except Exception as e:
        print(f"\n   [FAILED] Database Functions - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cleanup_manager():
    """Test patient cleanup manager (without actually deleting)"""
    print("\n" + "="*60)
    print("TEST 3: Patient Cleanup Manager")
    print("="*60)
    
    try:
        from PacsClient.utils.patient_cleanup_manager import (
            get_patients_for_deletion,
            estimate_patient_size
        )
        from PacsClient.utils.database import get_patients_ordered_by_date
        
        # Test deletion strategy - count
        print("\n1. Testing deletion strategy (by count)...")
        patients = get_patients_for_deletion(strategy='count', count=5)
        print(f"   [OK] Strategy 'count': Found {len(patients)} patients")
        
        # Test deletion strategy - date
        print("\n2. Testing deletion strategy (by date)...")
        patients_date = get_patients_for_deletion(strategy='date', date_threshold='20250101')
        print(f"   [OK] Strategy 'date': Found {len(patients_date)} patients")
        
        # Test size estimation (if patients exist)
        if patients:
            print("\n3. Testing patient size estimation...")
            patient_pk = patients[0]['patient_pk']
            estimated_size = estimate_patient_size(patient_pk)
            print(f"   [OK] Estimated size: {estimated_size / (1024**2):.2f} MB")
        
        print("\n   [PASSED] Cleanup Manager")
        print("\n   [INFO] NOTE: Actual deletion NOT tested (requires manual verification)")
        return True
        
    except Exception as e:
        print(f"\n   [FAILED] Cleanup Manager - {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ui_widget():
    """Test UI widget can be imported and instantiated"""
    print("\n" + "="*60)
    print("TEST 4: UI Widget Import")
    print("="*60)
    
    try:
        # Try to import (but not display) the UI widget
        print("\n1. Testing widget import...")
        from PacsClient.pacs.workstation_ui.storage_monitor_widget import (
            StorageMonitorWidget,
            PatientDeletionDialog
        )
        print(f"   [OK] StorageMonitorWidget imported successfully")
        print(f"   [OK] PatientDeletionDialog imported successfully")
        
        print("\n   [PASSED] UI Widget Import")
        print("\n   [INFO] NOTE: UI display NOT tested (requires GUI environment)")
        return True
        
    except Exception as e:
        print(f"\n   [FAILED] UI Widget Import - {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all tests and report results"""
    print("\n" + "="*60)
    print("STORAGE MONITORING & CLEANUP FEATURE - TEST SUITE")
    print("="*60)
    
    results = []
    
    # Run tests
    results.append(("Storage Calculator", test_storage_calculator()))
    results.append(("Database Functions", test_database_functions()))
    results.append(("Cleanup Manager", test_cleanup_manager()))
    results.append(("UI Widget Import", test_ui_widget()))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASSED]" if result else "[FAILED]"
        print(f"  {test_name}: {status}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  All tests PASSED!")
    else:
        print(f"\n  {total - passed} test(s) FAILED")
    
    print("="*60)
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
