"""
Configuration system for DICOM download and processing
Replaces hardcoded values with configurable settings
"""
import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class InterpolationQuality(Enum):
    """Image interpolation quality levels"""
    NEAREST = "nearest"
    LINEAR = "linear"
    CUBIC = "cubic"
    LANCZOS = "lanczos"


class CompressionType(Enum):
    """Compression types for downloads"""
    NONE = "none"
    GZIP = "gzip"
    DEFLATE = "deflate"


@dataclass
class DownloadConfig:
    """Configuration for DICOM download"""
    # Timeouts
    max_wait_seconds: int = 300  # 5 minutes
    connection_timeout_seconds: int = 30
    read_timeout_seconds: int = 60
    
    # Polling
    poll_interval_seconds: float = 0.5
    use_file_watcher: bool = True  # Use file system watcher instead of polling
    
    # Retry
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    retry_backoff_multiplier: float = 2.0  # Exponential backoff
    
    # Batch processing
    batch_size: int = 10
    max_concurrent_downloads: int = 3
    
    # Compression
    compression: CompressionType = field(default=CompressionType.GZIP)
    
    # Resume
    enable_resume: bool = True
    resume_check_interval_seconds: float = 5.0
    
    # Validation
    verify_download: bool = True
    check_file_integrity: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        d = asdict(self)
        # Convert enums to strings
        if isinstance(d.get('compression'), CompressionType):
            d['compression'] = d['compression'].value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DownloadConfig':
        """Create from dictionary"""
        # Handle enum
        if 'compression' in data and isinstance(data['compression'], str):
            data['compression'] = CompressionType(data['compression'])
        return cls(**data)


@dataclass
class CacheConfig:
    """Configuration for caching"""
    # Thumbnail cache
    thumbnail_max_size: int = 1000
    thumbnail_ttl_seconds: float = 300  # 5 minutes
    
    # Metadata cache
    metadata_max_size: int = 500
    metadata_ttl_seconds: float = 600  # 10 minutes
    
    # Image cache
    image_max_size: int = 100
    image_ttl_seconds: float = 1800  # 30 minutes
    
    # VTK cache
    vtk_max_size: int = 50
    vtk_ttl_seconds: float = 3600  # 1 hour
    
    # Cleanup
    auto_cleanup: bool = True
    cleanup_interval_seconds: float = 60
    
    # Eviction
    eviction_policy: str = "lru"  # lru, fifo, lfu


@dataclass
class ImageProcessingConfig:
    """Configuration for image processing"""
    # Upsampling
    enable_upsampling: bool = True
    upsample_threshold: float = 1.0
    max_upsample_factor: float = 4.0
    
    # Interpolation
    interpolation_quality: InterpolationQuality = field(default=InterpolationQuality.LANCZOS)
    
    # Memory
    max_memory_mb: float = 4096  # 4GB
    enable_memory_monitoring: bool = True
    
    # Filters
    apply_default_filters: bool = True
    enable_antialiasing: bool = True
    
    # Performance
    use_gpu_acceleration: bool = False
    num_worker_threads: int = 4
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        d = asdict(self)
        if isinstance(d.get('interpolation_quality'), InterpolationQuality):
            d['interpolation_quality'] = d['interpolation_quality'].value
        return d
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ImageProcessingConfig':
        """Create from dictionary"""
        if 'interpolation_quality' in data and isinstance(data['interpolation_quality'], str):
            data['interpolation_quality'] = InterpolationQuality(data['interpolation_quality'])
        return cls(**data)


@dataclass
class DatabaseConfig:
    """Configuration for database"""
    # Connection pooling
    use_connection_pool: bool = True
    pool_size: int = 10
    max_overflow: int = 5
    pool_timeout_seconds: float = 30.0
    
    # Query optimization
    enable_query_cache: bool = True
    batch_insert_size: int = 100
    
    # Async
    use_async_queries: bool = True
    async_worker_threads: int = 4
    
    # Timeouts
    query_timeout_seconds: float = 30.0
    transaction_timeout_seconds: float = 60.0


@dataclass
class RenderConfig:
    """Configuration for VTK rendering"""
    # Quality
    enable_antialiasing: bool = True
    multisampling_level: int = 4
    
    # Performance
    use_lod: bool = True  # Level of detail
    frame_rate_target: float = 30.0
    
    # Rendering
    render_delay_ms: int = 100  # Delay for batching renders
    max_texture_size: int = 8192
    
    # Memory
    cleanup_on_close: bool = True
    aggressive_cleanup: bool = False


@dataclass
class LoggingConfig:
    """Configuration for logging"""
    # Level
    log_level: str = "INFO"
    
    # Output
    log_to_file: bool = True
    log_to_console: bool = True
    log_file_path: str = "logs/dicom_client.log"
    
    # Rotation
    max_log_size_mb: float = 10.0
    backup_count: int = 5
    
    # Format
    include_timestamp: bool = True
    include_thread_info: bool = True
    include_function_name: bool = True


@dataclass
class ApplicationConfig:
    """Main application configuration"""
    download: DownloadConfig = field(default_factory=DownloadConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    image_processing: ImageProcessingConfig = field(default_factory=ImageProcessingConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'download': self.download.to_dict() if hasattr(self.download, 'to_dict') else asdict(self.download),
            'cache': asdict(self.cache),
            'image_processing': self.image_processing.to_dict() if hasattr(self.image_processing, 'to_dict') else asdict(self.image_processing),
            'database': asdict(self.database),
            'render': asdict(self.render),
            'logging': asdict(self.logging)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ApplicationConfig':
        """Create from dictionary"""
        return cls(
            download=DownloadConfig.from_dict(data.get('download', {})) if 'download' in data else DownloadConfig(),
            cache=CacheConfig(**data.get('cache', {})) if 'cache' in data else CacheConfig(),
            image_processing=ImageProcessingConfig.from_dict(data.get('image_processing', {})) if 'image_processing' in data else ImageProcessingConfig(),
            database=DatabaseConfig(**data.get('database', {})) if 'database' in data else DatabaseConfig(),
            render=RenderConfig(**data.get('render', {})) if 'render' in data else RenderConfig(),
            logging=LoggingConfig(**data.get('logging', {})) if 'logging' in data else LoggingConfig()
        )
    
    def save_to_file(self, file_path: Path) -> None:
        """Save configuration to JSON file"""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info(f"Configuration saved to {file_path}")
    
    @classmethod
    def load_from_file(cls, file_path: Path) -> 'ApplicationConfig':
        """Load configuration from JSON file"""
        if not file_path.exists():
            logger.warning(f"Configuration file not found: {file_path}, using defaults")
            return cls()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            logger.info(f"Configuration loaded from {file_path}")
            return cls.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load configuration from {file_path}: {e}")
            logger.info("Using default configuration")
            return cls()
    
    @classmethod
    def from_env(cls) -> 'ApplicationConfig':
        """Load configuration from environment variables"""
        return cls(
            download=DownloadConfig(
                max_wait_seconds=int(os.getenv('DICOM_MAX_WAIT_SECONDS', 300)),
                connection_timeout_seconds=int(os.getenv('DICOM_CONN_TIMEOUT', 30)),
                poll_interval_seconds=float(os.getenv('DICOM_POLL_INTERVAL', 0.5)),
                use_file_watcher=os.getenv('DICOM_USE_FILE_WATCHER', 'true').lower() == 'true',
                max_retries=int(os.getenv('DICOM_MAX_RETRIES', 3)),
                batch_size=int(os.getenv('DICOM_BATCH_SIZE', 10)),
            ),
            cache=CacheConfig(
                thumbnail_max_size=int(os.getenv('CACHE_THUMBNAIL_MAX_SIZE', 1000)),
                thumbnail_ttl_seconds=float(os.getenv('CACHE_THUMBNAIL_TTL', 300)),
                auto_cleanup=os.getenv('CACHE_AUTO_CLEANUP', 'true').lower() == 'true',
            ),
            image_processing=ImageProcessingConfig(
                enable_upsampling=os.getenv('IMG_ENABLE_UPSAMPLING', 'true').lower() == 'true',
                max_memory_mb=float(os.getenv('IMG_MAX_MEMORY_MB', 4096)),
                num_worker_threads=int(os.getenv('IMG_WORKER_THREADS', 4)),
            ),
            logging=LoggingConfig(
                log_level=os.getenv('LOG_LEVEL', 'INFO'),
                log_to_file=os.getenv('LOG_TO_FILE', 'true').lower() == 'true',
            )
        )


# Global configuration instance
_config: Optional[ApplicationConfig] = None
try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH as _CONF_DIR
    _config_file_path = Path(_CONF_DIR) / "application_config.json"
except Exception:
    _config_file_path = Path(__file__).resolve().parents[4] / "config" / "application_config.json"


def get_config() -> ApplicationConfig:
    """Get global configuration instance"""
    global _config
    if _config is None:
        # Try to load from file
        if _config_file_path.exists():
            _config = ApplicationConfig.load_from_file(_config_file_path)
        # Try to load from environment
        elif os.getenv('DICOM_CONFIG_FROM_ENV', 'false').lower() == 'true':
            _config = ApplicationConfig.from_env()
        # Use defaults
        else:
            _config = ApplicationConfig()
            logger.info("Using default configuration")
    return _config


def set_config(config: ApplicationConfig) -> None:
    """Set global configuration instance"""
    global _config
    _config = config
    logger.info("Configuration updated")


def reload_config() -> ApplicationConfig:
    """Reload configuration from file"""
    global _config
    _config = None
    return get_config()


def save_config(config: Optional[ApplicationConfig] = None) -> None:
    """Save configuration to file"""
    if config is None:
        config = get_config()
    config.save_to_file(_config_file_path)


# Convenience functions for accessing specific configs
def get_download_config() -> DownloadConfig:
    """Get download configuration"""
    return get_config().download


def get_cache_config() -> CacheConfig:
    """Get cache configuration"""
    return get_config().cache


def get_image_processing_config() -> ImageProcessingConfig:
    """Get image processing configuration"""
    return get_config().image_processing


def get_database_config() -> DatabaseConfig:
    """Get database configuration"""
    return get_config().database


def get_render_config() -> RenderConfig:
    """Get render configuration"""
    return get_config().render


def get_logging_config() -> LoggingConfig:
    """Get logging configuration"""
    return get_config().logging

