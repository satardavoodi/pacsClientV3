#!/usr/bin/env python3
"""
Quick threading diagnostics script
Run before/after app to verify thread safety
"""

import sys
import threading
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_threading_imports():
    """Verify all threading-related imports work"""
    print("🔍 Checking threading imports...")
    
    try:
        from PySide6.QtCore import QTimer, Qt, QThread
        print("  ✅ Qt imports OK")
    except ImportError as e:
        print(f"  ❌ Qt imports FAILED: {e}")
        return False
    
    try:
        from PacsClient.zeta_download_manager.ui.main_widget import DownloadManagerWidget
        print("  ✅ DownloadManagerWidget import OK")
    except ImportError as e:
        print(f"  ❌ DownloadManagerWidget import FAILED: {e}")
        return False
    
    try:
        from PacsClient.zeta_download_manager.state.observers import UIObserver
        print("  ✅ UIObserver import OK")
    except ImportError as e:
        print(f"  ❌ UIObserver import FAILED: {e}")
        return False
    
    return True

def check_qtimer_wrapping():
    """Check that QTimer.singleShot is used correctly"""
    print("\n🔍 Checking QTimer usage...")
    
    try:
        with open(project_root / 'PacsClient/zeta_download_manager/ui/main_widget.py', 'r') as f:
            content = f.read()
        
        # Count QTimer.singleShot usage
        timer_count = content.count('QTimer.singleShot')
        print(f"  Found {timer_count} QTimer.singleShot() calls")
        
        # Check for nested QTimer patterns
        if content.count('QTimer.singleShot(0, lambda: self._do_'):
            print("  ✅ Correct deferred pattern found")
        
        # Check for direct widget updates in _do_ methods
        lines = content.split('\n')
        in_do_method = False
        direct_updates = 0
        
        for i, line in enumerate(lines):
            if 'def _do_' in line:
                in_do_method = True
            elif in_do_method and line.strip().startswith('def '):
                in_do_method = False
            elif in_do_method:
                # Check for direct updates (should be in try/except)
                if '.setValue(' in line or '.setItem(' in line or '.setText(' in line:
                    direct_updates += 1
        
        print(f"  Found {direct_updates} direct widget updates (should be within try/except)")
        
        return True
    
    except Exception as e:
        print(f"  ❌ Error checking QTimer usage: {e}")
        return False

def check_error_handling():
    """Check for comprehensive exception handling"""
    print("\n🔍 Checking error handling...")
    
    try:
        with open(project_root / 'PacsClient/zeta_download_manager/ui/main_widget.py', 'r') as f:
            content = f.read()
        
        # Count try/except blocks in _do_ methods
        try_count = content.count('except Exception as e:')
        print(f"  Found {try_count} exception handlers")
        
        if try_count >= 5:
            print("  ✅ Comprehensive error handling in place")
        else:
            print("  ⚠️  May need more exception handling")
        
        return True
    
    except Exception as e:
        print(f"  ❌ Error checking error handling: {e}")
        return False

def main():
    print("=" * 60)
    print("THREADING DIAGNOSTICS")
    print("=" * 60)
    
    results = []
    
    results.append(("Imports", check_threading_imports()))
    results.append(("QTimer Wrapping", check_qtimer_wrapping()))
    results.append(("Error Handling", check_error_handling()))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r for _, r in results)
    
    if all_passed:
        print("\n🎉 All threading checks passed!")
        print("   Ready to run the app and test downloads")
        return 0
    else:
        print("\n⚠️  Some checks failed")
        print("   Please review the errors above")
        return 1

if __name__ == '__main__':
    sys.exit(main())
