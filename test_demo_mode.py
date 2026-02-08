#!/usr/bin/env python
"""
Test script to verify demo mode works without server
"""
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PacsClient.app_handler import AppHandler
from PySide6.QtWidgets import QApplication

def test_demo_authentication():
    """Test that demo mode authentication works"""
    app = QApplication(sys.argv)
    
    # Create an instance of AppHandler to test authentication methods
    handler = AppHandler()
    
    # Test various demo credentials
    test_cases = [
        ("", ""),  # Empty credentials
        ("admin", "admin"),  # Admin credentials  
        ("user", "user"),  # User credentials
        ("doctor", "doctor"),  # Doctor credentials
        ("radiologist", "password"),  # Radiologist credentials
        ("test", "test"),  # Test credentials
        ("invalid", "invalid"),  # Invalid credentials
    ]
    
    print("Testing demo authentication...")
    for username, password in test_cases:
        result = handler._authenticate_user(username, password)
        status = "[PASS]" if result else "[FAIL]"
        cred_desc = f"'{username}'/'{password}'" if username or password else "empty/empty"
        print(f"  {status}: {cred_desc} -> {result}")
    
    print("\nDemo authentication test completed!")
    
    # Test socket authentication fallback (should fail quickly now)
    print("\nTesting socket authentication fallback...")
    try:
        success, message = handler._authenticate_with_socket("test", "test")
        print(f"Socket auth result: success={success}, message='{message}'")
        
        # This should now fail quickly due to connection refusal (not timeout)
        if "timeout" not in message.lower() and ("refused" in message.lower() or "refused" in message or success == False):
            print("[PASS] Socket fallback working correctly - fails quickly without hanging")
        else:
            print("[WARN] Socket fallback may still have issues")
            
    except Exception as e:
        print(f"Socket auth error (expected): {e}")

if __name__ == "__main__":
    test_demo_authentication()