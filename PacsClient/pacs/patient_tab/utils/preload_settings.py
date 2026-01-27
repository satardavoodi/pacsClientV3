"""
Pre-load tools settings at startup to avoid database locks during progressive download
Call this early in application initialization
"""

def preload_tools_settings():
    """
    Pre-load tools settings into cache during application startup.
    This prevents database locking issues during progressive download.
    
    Should be called once during application initialization in the main thread.
    """
    try:
        from PacsClient.pacs.patient_tab.utils.tools_settings import get_tools_settings
        
        # Get instance and trigger lazy load
        manager = get_tools_settings()
        settings = manager.get_settings()
        
        print("✅ Tools settings pre-loaded into cache")
        return True
    except Exception as e:
        print(f"⚠️ Failed to pre-load tools settings: {e}")
        return False


if __name__ == "__main__":
    # Test preload
    preload_tools_settings()

