#!/usr/bin/env python3
"""
Debug script to trace and identify freezing during downloads
This script monitors the event loop and logs threading violations
"""

import sys
import os
import threading
import time
import logging
from pathlib import Path
from datetime import datetime

# Add project root
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(levelname)s] [%(threadName)-10s] %(message)s',
    handlers=[
        logging.FileHandler('debug_freeze.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import Qt
try:
    from PySide6.QtCore import QTimer, Qt, QThread, QEvent, QCoreApplication
    from PySide6.QtWidgets import QApplication, QMessageBox
    logger.info("✅ Qt imports successful")
except ImportError as e:
    logger.error(f"❌ Failed to import Qt: {e}")
    sys.exit(1)

# Create custom event filter to monitor event loop
class EventLoopMonitor(QCoreApplication):
    """Custom QApplication that monitors event loop"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event_count = 0
        self.slow_events = []
        self.last_event_time = time.time()
        self.freeze_detected = False
        
        # Start monitoring timer
        monitor_timer = QTimer()
        monitor_timer.timeout.connect(self._check_responsiveness)
        monitor_timer.start(1000)  # Check every second
    
    def _check_responsiveness(self):
        """Check if event loop is responsive"""
        current_time = time.time()
        delta = current_time - self.last_event_time
        
        if delta > 0.5:
            logger.warning(f"⚠️  Event loop unresponsive for {delta:.2f}s")
            if delta > 2.0:
                logger.error(f"❌ FREEZE DETECTED! Event loop blocked for {delta:.2f}s")
                self.freeze_detected = True
        
        self.last_event_time = current_time
    
    def notify(self, obj, event):
        """Override event notification to monitor events"""
        try:
            self.event_count += 1
            
            # Log specific event types
            if event.type() in [QEvent.Timer, QEvent.Paint, QEvent.Repaint]:
                thread_name = threading.current_thread().name
                if thread_name != 'MainThread':
                    logger.error(f"❌ THREADING VIOLATION: {event.type()} in thread {thread_name}")
            
            # Track timing
            start = time.time()
            result = super().notify(obj, event)
            elapsed = time.time() - start
            
            if elapsed > 0.1:
                logger.warning(f"⚠️  Slow event: {event.type()} took {elapsed:.3f}s")
                self.slow_events.append((event.type(), elapsed))
            
            self.last_event_time = time.time()
            return result
        
        except Exception as e:
            logger.error(f"❌ Error in event monitor: {e}")
            return super().notify(obj, event)

def main():
    logger.info("=" * 80)
    logger.info("FREEZE DEBUGGING SESSION STARTED")
    logger.info("=" * 80)
    logger.info(f"Main thread: {threading.current_thread().name}")
    logger.info(f"Python version: {sys.version}")
    
    try:
        # Create monitored application
        app = EventLoopMonitor(sys.argv)
        logger.info("✅ EventLoopMonitor created")
        
        # Import and create main window
        from PacsClient import AppHandler
        logger.info("✅ AppHandler imported")
        
        # Create login window
        window = AppHandler()
        logger.info("✅ AppHandler window created")
        
        window.show()
        logger.info("✅ Window shown")
        
        # Log startup complete
        logger.info("-" * 80)
        logger.info("APP READY FOR TESTING")
        logger.info("-" * 80)
        logger.info("Instructions:")
        logger.info("1. Login with test credentials")
        logger.info("2. Select a patient and click Download")
        logger.info("3. Watch the console for freeze detection")
        logger.info("4. Check debug_freeze.log for detailed timing")
        logger.info("-" * 80)
        
        # Run application
        sys.exit(app.exec())
    
    except Exception as e:
        logger.error(f"❌ FATAL ERROR: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()
