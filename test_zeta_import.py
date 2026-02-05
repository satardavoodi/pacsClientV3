#!/usr/bin/env python3
"""Test Zeta Download Manager imports"""

import sys
sys.path.insert(0, 'c:/AI-Pacs codes/PacsClientV2')

print("\n" + "="*60)
print("ZETA DOWNLOAD MANAGER - IMPORT TEST")
print("="*60 + "\n")

try:
    from PacsClient.zeta_download_manager import (
        DownloadPriority, DownloadStatus, DownloadTask,
        DownloadState, SeriesInfo, get_state_store,
        DownloadRuleEngine, DownloadExecutor
    )
    
    print("✅ Core imports successful\n")
    
    print("Available Priority Levels:")
    for p in DownloadPriority:
        print(f"   - {p.name}: {p.value}")
    
    print("\nAvailable Status Types:")
    for s in DownloadStatus:
        print(f"   - {s.name}")
    
    print("\n" + "-"*60)
    
    # Test adapter
    from PacsClient.components.zeta_adapter import (
        start_zeta_download, pause_zeta_download,
        resume_zeta_download, cancel_zeta_download,
        create_download_task_from_study
    )
    
    print("✅ Adapter imports successful")
    
    print("\n" + "-"*60)
    
    # Test network components
    from PacsClient.zeta_download_manager.network.socket_client import SocketDicomClient
    from PacsClient.zeta_download_manager.network.grpc_client import GrpcMetadataClient
    
    print("✅ Network clients loaded")
    
    print("\n" + "-"*60)
    
    # Test storage components
    from PacsClient.zeta_download_manager.storage.database_manager import DatabaseManager
    
    print("✅ Database manager loaded")
    
    print("\n" + "="*60)
    print("SUCCESS: ALL TESTS PASSED - MIGRATION SUCCESSFUL!")
    print("="*60 + "\n")
    
except Exception as e:
    print(f"\nERROR: Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
