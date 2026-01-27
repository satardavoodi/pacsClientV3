"""
File System Watcher for monitoring DICOM downloads
Replaces busy-wait polling with event-driven approach
"""
import logging
from pathlib import Path
from typing import Callable, Optional, Set
from threading import Lock
import time

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logging.warning("watchdog not available, falling back to polling")

logger = logging.getLogger(__name__)


class DicomFileHandler(FileSystemEventHandler):
    """Handler for DICOM file system events"""
    
    def __init__(self, callback: Callable[[Path], None], file_extension: str = '.dcm'):
        super().__init__()
        self.callback = callback
        self.file_extension = file_extension
        self._processed_files: Set[str] = set()
        self._lock = Lock()
        
    def on_created(self, event):
        """Called when a file or directory is created"""
        if event.is_directory:
            return
            
        file_path = Path(event.src_path)
        
        # Only process DICOM files
        if not file_path.suffix.lower() == self.file_extension:
            return
        
        # Avoid processing the same file twice
        with self._lock:
            file_key = str(file_path)
            if file_key in self._processed_files:
                return
            self._processed_files.add(file_key)
        
        # Wait a bit to ensure file is fully written
        time.sleep(0.1)
        
        try:
            # Verify file is readable
            if file_path.exists() and file_path.stat().st_size > 0:
                logger.debug(f"New DICOM file detected: {file_path}")
                self.callback(file_path)
        except Exception as e:
            logger.error(f"Error processing file {file_path}: {e}")
            with self._lock:
                self._processed_files.discard(str(file_path))


class DicomDirectoryWatcher:
    """
    Watch a directory for new DICOM files
    Replacement for busy-wait polling in load_images_from_server
    """
    
    def __init__(self, watch_path: Path, callback: Callable[[Path], None]):
        """
        Args:
            watch_path: Directory to watch
            callback: Function to call when new DICOM file is detected
        """
        self.watch_path = Path(watch_path)
        self.callback = callback
        self.observer: Optional[Observer] = None
        self.handler: Optional[DicomFileHandler] = None
        self._is_watching = False
        
        if not WATCHDOG_AVAILABLE:
            logger.warning("Watchdog not available, watcher will not function")
    
    def start(self) -> bool:
        """Start watching the directory"""
        if not WATCHDOG_AVAILABLE:
            logger.error("Cannot start watcher: watchdog not available")
            return False
        
        if self._is_watching:
            logger.warning("Watcher already started")
            return True
        
        if not self.watch_path.exists():
            logger.error(f"Watch path does not exist: {self.watch_path}")
            return False
        
        try:
            self.handler = DicomFileHandler(self.callback)
            self.observer = Observer()
            self.observer.schedule(
                self.handler, 
                str(self.watch_path), 
                recursive=True
            )
            self.observer.start()
            self._is_watching = True
            logger.info(f"Started watching directory: {self.watch_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to start watcher: {e}")
            return False
    
    def stop(self):
        """Stop watching the directory"""
        if not self._is_watching or not self.observer:
            return
        
        try:
            self.observer.stop()
            self.observer.join(timeout=5.0)
            self._is_watching = False
            logger.info("Stopped directory watcher")
        except Exception as e:
            logger.error(f"Error stopping watcher: {e}")
    
    def is_watching(self) -> bool:
        """Check if currently watching"""
        return self._is_watching
    
    def __enter__(self):
        """Context manager entry"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop()


class FallbackPoller:
    """
    Fallback polling mechanism when watchdog is not available
    More efficient than original implementation
    """
    
    def __init__(
        self, 
        watch_path: Path, 
        callback: Callable[[Path], None],
        poll_interval: float = 1.0
    ):
        """
        Args:
            watch_path: Directory to poll
            callback: Function to call when new files detected
            poll_interval: Seconds between polls
        """
        self.watch_path = Path(watch_path)
        self.callback = callback
        self.poll_interval = poll_interval
        self._known_files: Set[Path] = set()
        self._is_running = False
        self._lock = Lock()
    
    def start(self) -> bool:
        """Start polling (non-blocking)"""
        if not self.watch_path.exists():
            logger.error(f"Watch path does not exist: {self.watch_path}")
            return False
        
        with self._lock:
            if self._is_running:
                return True
            self._is_running = True
        
        # Initial scan
        self._scan_directory()
        logger.info(f"Started fallback polling: {self.watch_path}")
        return True
    
    def stop(self):
        """Stop polling"""
        with self._lock:
            self._is_running = False
        logger.info("Stopped fallback polling")
    
    def poll_once(self) -> int:
        """
        Poll once for new files
        Returns: Number of new files found
        """
        if not self._is_running:
            return 0
        
        return self._scan_directory()
    
    def _scan_directory(self) -> int:
        """Scan directory for new DICOM files"""
        new_files_count = 0
        
        try:
            # Find all .dcm files recursively
            current_files = set(
                self.watch_path.rglob('*.dcm')
            )
            
            # Find new files
            new_files = current_files - self._known_files
            
            # Process new files
            for file_path in sorted(new_files):
                if file_path.exists() and file_path.stat().st_size > 0:
                    try:
                        self.callback(file_path)
                        new_files_count += 1
                    except Exception as e:
                        logger.error(f"Error processing file {file_path}: {e}")
            
            # Update known files
            self._known_files = current_files
            
        except Exception as e:
            logger.error(f"Error scanning directory: {e}")
        
        return new_files_count
    
    def is_running(self) -> bool:
        """Check if currently polling"""
        with self._lock:
            return self._is_running


def create_watcher(
    watch_path: Path, 
    callback: Callable[[Path], None],
    use_watchdog: bool = True
) -> 'DicomDirectoryWatcher | FallbackPoller':
    """
    Factory function to create appropriate watcher
    
    Args:
        watch_path: Directory to watch
        callback: Function to call when new files detected
        use_watchdog: Try to use watchdog if available
    
    Returns:
        Watcher instance (either DicomDirectoryWatcher or FallbackPoller)
    """
    if use_watchdog and WATCHDOG_AVAILABLE:
        return DicomDirectoryWatcher(watch_path, callback)
    else:
        return FallbackPoller(watch_path, callback)

