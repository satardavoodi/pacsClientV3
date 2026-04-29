"""
Core Constants - Configuration values and limits
"""
import os as _os

# Network Configuration
# Host/port come from environment or socket_config.json at runtime.
# These defaults are used only when config is unavailable.
DEFAULT_SOCKET_HOST = _os.environ.get("AIPACS_SOCKET_HOST", "localhost")
DEFAULT_SOCKET_PORT = int(_os.environ.get("AIPACS_SOCKET_PORT", "50052"))
DEFAULT_GRPC_PORT = int(_os.environ.get("AIPACS_GRPC_PORT", "50051"))
CONNECTION_TIMEOUT = 30.0  # seconds
SOCKET_CHUNK_SIZE = 65536  # 64 KB

# Download Configuration
BATCH_SIZE = 10  # instances per batch (cap to reduce server load)
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds (base delay for exponential backoff)
MAX_CONSECUTIVE_FAILURES = 5

# Reconnection Configuration (exponential backoff)
RECONNECT_MAX_RETRIES = 5          # max reconnect attempts before giving up
RECONNECT_BASE_DELAY = 1.0        # seconds, first retry delay
RECONNECT_MAX_DELAY = 30.0        # seconds, cap on backoff delay
RECONNECT_BACKOFF_FACTOR = 2.0    # exponential multiplier
RECONNECT_JITTER_MAX = 1.0        # max random jitter added to delay (seconds)

# Series-level retry (retry failed series within a study download)
MAX_SERIES_RETRIES = 3             # max retry attempts per failed series
SERIES_RETRY_BASE_DELAY = 3.0     # seconds, base delay between series retries

# Request-level retry (for individual send_request calls)
REQUEST_MAX_RETRIES = 3            # max retries for a single request
REQUEST_RETRY_BASE_DELAY = 1.0    # seconds, base delay for request retry

# Concurrency Configuration
MAX_CONCURRENT_STUDIES = 1  # Only 1 study at a time (R11)
MAX_PARALLEL_SERIES_CRITICAL = 1  # Critical priority: sequential
MAX_PARALLEL_SERIES_HIGH = 1       # High priority: sequential
MAX_PARALLEL_SERIES_NORMAL = 2     # Normal priority: up to 2 parallel
MAX_PARALLEL_SERIES_LOW = 3        # Low priority: up to 3 parallel

# Performance Configuration
PROGRESS_UPDATE_INTERVAL_MS = 100  # 10 Hz (R35)
PRIORITY_CHANGE_DEBOUNCE_MS = 150  # 150ms debounce (R36)
DATABASE_BATCH_INSERT_SIZE = 50    # Batch insert size (R37)
UI_UPDATE_THROTTLE_MS = 100        # UI update throttling

# F3.5.2 — Priority handoff wall-clock retry (V2; default-off)
# Replaces the legacy 90 attempts × 200 ms primary + 3 × 3000 ms recovery
# split with a single wall-clock budget. Default-off via
# AIPACS_INTENT_HANDOFF_V2 env var; will flip to default-on in F3.5.4 after
# cross-PC baseline confirms.
INTENT_HANDOFF_V2_DEFAULT = False
INTENT_HANDOFF_HARD_TIMEOUT_MS = 60000   # 60 s wall-clock budget
INTENT_HANDOFF_V2_INTERVAL_MS = 250      # tick cadence for V2 retry

# File System Configuration
DICOM_FILE_EXTENSION = '.dcm'
THUMBNAIL_FORMAT = 'JPEG'
THUMBNAIL_SIZE = (256, 256)
MIN_VALID_DICOM_SIZE = 128  # bytes, for validation

# Database Configuration
try:
    from PacsClient.utils.data_paths import DATABASE_FILE as _DB_FILE
    DATABASE_NAME = str(_DB_FILE)
except Exception:
    DATABASE_NAME = 'dicom.db'
WAL_MODE = True
BUSY_TIMEOUT_MS = 120000  # 120 seconds

# UI Configuration
MAX_VISIBLE_DOWNLOADS_PER_GROUP = 5  # Show first 5, rest hidden
TABLE_ROW_HEIGHT = 70  # pixels
ANIMATION_DURATION_MS = 300  # Progress bar, state changes
EXPAND_ANIMATION_DURATION_MS = 200  # Group expand/collapse

# Priority Group Colors (Modern Material Design 3)
PRIORITY_COLORS = {
    'CRITICAL': {
        'gradient_start': '#ef4444',  # Red 500
        'gradient_end': '#dc2626',    # Red 600
        'border': '#b91c1c',          # Red 700
        'text': '#ffffff'             # White
    },
    'HIGH': {
        'gradient_start': '#f97316',  # Orange 500
        'gradient_end': '#ea580c',    # Orange 600
        'border': '#c2410c',          # Orange 700
        'text': '#ffffff'
    },
    'NORMAL': {
        'gradient_start': '#06b6d4',  # Cyan 500
        'gradient_end': '#0891b2',    # Cyan 600
        'border': '#0e7490',          # Cyan 700
        'text': '#ffffff'
    },
    'LOW': {
        'gradient_start': '#64748b',  # Slate 500
        'gradient_end': '#475569',    # Slate 600
        'border': '#334155',          # Slate 700
        'text': '#ffffff'
    }
}

# Status Badge Colors
STATUS_COLORS = {
    'PENDING': '#94a3b8',      # Slate 400
    'DOWNLOADING': '#3b82f6',  # Blue 500
    'PAUSED': '#f59e0b',       # Amber 500
    'COMPLETED': '#10b981',    # Emerald 500
    'FAILED': '#ef4444',       # Red 500
    'CANCELLED': '#6b7280',    # Gray 500
    'VALIDATING': '#8b5cf6',   # Violet 500
}

# Typography
FONT_FAMILY_SANS = 'Segoe UI, Roboto, sans-serif'
FONT_FAMILY_MONO = 'Consolas, Monaco, monospace'
FONT_SIZE_HEADER = 18
FONT_SIZE_BODY = 14
FONT_SIZE_SMALL = 12
FONT_SIZE_CAPTION = 11

# Logging
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5
