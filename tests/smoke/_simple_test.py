import os
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_simple_check.txt")
with open(path, "w") as f:
    f.write("Python works!\n")
    try:
        from modules.download_manager.core.enums import DownloadStatus
        f.write(f"Import OK: {DownloadStatus.PENDING}\n")
    except Exception as e:
        f.write(f"Import FAILED: {e}\n")
    try:
        from modules.download_manager.state.state_store import DownloadStateStore
        f.write(f"StateStore OK\n")
    except Exception as e:
        f.write(f"StateStore FAILED: {e}\n")
