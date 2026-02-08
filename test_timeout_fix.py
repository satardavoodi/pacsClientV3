#!/usr/bin/env python
"""
Quick test to verify the socket timeout fix
"""
import sys
import os
import time

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PacsClient.components.socket_service import SocketService
from PacsClient.zeta_download_manager.network.socket_client import SocketDicomClient

def test_connection_speed():
    """Test that connection attempts fail quickly"""
    print("Testing connection speed with localhost...")
    
    # Test with a very short timeout to verify quick failure
    start_time = time.time()
    
    try:
        client = SocketDicomClient(
            host="localhost",
            port=50052,
            timeout=2.0  # Very short timeout
        )
        
        connect_result = client.connect()
        end_time = time.time()
        
        elapsed = end_time - start_time
        
        print(f"Connection attempt took: {elapsed:.2f} seconds")
        print(f"Connection result: {connect_result}")
        
        if elapsed < 3.0:  # Should be much less than the original 30 seconds
            print("[SUCCESS] Connection failed quickly as expected")
        else:
            print("[FAILURE] Connection took too long")
            
        # Clean up
        if client.is_connected():
            client.disconnect()
            
    except Exception as e:
        end_time = time.time()
        elapsed = end_time - start_time
        print(f"Exception occurred after {elapsed:.2f} seconds: {e}")
        if elapsed < 3.0:
            print("[SUCCESS] Failure happened quickly")
        else:
            print("[FAILURE] Took too long to fail")

def test_socket_service():
    """Test socket service with updated config"""
    print("\nTesting SocketService with updated config...")
    
    service = SocketService()
    
    print(f"Configured host: {service.config.get_socket_host()}")
    print(f"Configured port: {service.config.get_socket_port()}")
    print(f"Configured timeout: {service.config.get_connection_timeout()}")
    
    start_time = time.time()
    result = service.test_connection()
    end_time = time.time()
    
    elapsed = end_time - start_time
    print(f"Service test took: {elapsed:.2f} seconds")
    print(f"Service test result: {result}")
    
    if elapsed < 3.0:
        print("[SUCCESS] Service test completed quickly")
    else:
        print("[FAILURE] Service test took too long")

if __name__ == "__main__":
    print("Testing socket timeout fix...")
    test_connection_speed()
    test_socket_service()
    print("\nTest completed!")