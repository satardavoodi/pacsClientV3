# -*- coding: utf-8 -*-

import json
import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)
from .config import SOCKET_CONFIG_PATH

class SocketConfig:
    """
    Configuration manager for Socket server settings
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize Socket configuration
        
        Args:
            config_path (str, optional): Path to configuration file
        """
        try:
            if config_path is None:
                # Default config path
                # config_dir = os.path.join(os.path.dirname(__file__), '..', 'config')
                config_dir = SOCKET_CONFIG_PATH
                os.makedirs(config_dir, exist_ok=True)
                config_path = os.path.join(config_dir, 'socket_config.json')
            
            self.config_path = config_path
            self.config = self._load_default_config()
            self._load_config()
            logger.info(f"✅ SocketConfig initialized with path: {config_path}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize SocketConfig: {e}")
            # Fallback to default config
            self.config = self._load_default_config()
    
    def _load_default_config(self) -> Dict[str, Any]:
        """
        Load default configuration
        
        Returns:
            dict: Default configuration
        """
        return {
            "socket_host": "localhost",
            "socket_port": 50052,
            "connection_timeout": 30,
            "max_retries": 3,
            "retry_delay": 2,
            "buffer_size": 8192,
            "enable_compression": True,
            "log_level": "INFO",
            "auto_reconnect": True,
            "connection_pool_size": 5,
            "request_timeout": 60,
            "keep_alive": True,
            "keep_alive_interval": 30
        }
    
    def _load_config(self):
        """
        Load configuration from file
        """
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                    self.config.update(file_config)
                    logger.info(f"✅ Loaded Socket config from {self.config_path}")
            else:
                # Create default config file (async to avoid blocking UI)
                logger.info(f"📝 Creating default Socket config at {self.config_path}")
                try:
                    self.save_config()
                    logger.info(f"✅ Created default Socket config at {self.config_path}")
                except Exception as save_error:
                    logger.warning(f"⚠️ Could not save default config: {save_error}")
        except Exception as e:
            logger.error(f"❌ Error loading config: {e}")
            logger.info("Using default configuration")
    
    def save_config(self):
        """
        Save current configuration to file
        """
        try:
            config_dir = os.path.dirname(self.config_path)
            logger.info(f"🔧 Creating config directory: {config_dir}")
            os.makedirs(config_dir, exist_ok=True)
            
            logger.info(f"💾 Writing config to: {self.config_path}")
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ Saved Socket config to {self.config_path}")
        except PermissionError:
            logger.warning(f"⚠️ Cannot save config - file is read-only: {self.config_path}")
        except Exception as e:
            logger.error(f"❌ Error saving config: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value
        
        Args:
            key (str): Configuration key
            default (Any): Default value if key not found
            
        Returns:
            Any: Configuration value
        """
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any):
        """
        Set configuration value
        
        Args:
            key (str): Configuration key
            value (Any): Configuration value
        """
        self.config[key] = value
    
    def get_socket_host(self) -> str:
        """Get Socket server host"""
        host = self.get("socket_host", "localhost")
        return host
    
    def get_socket_port(self) -> int:
        """Get Socket server port"""
        port = self.get("socket_port", 50052)
        return int(port) if isinstance(port, (str, int)) else 50052
    
    def get_connection_timeout(self) -> int:
        """Get connection timeout"""
        timeout = self.get("connection_timeout", 30)
        return int(timeout) if isinstance(timeout, (str, int)) else 30
    
    def get_max_retries(self) -> int:
        """Get maximum retry attempts"""
        return self.get("max_retries", 3)
    
    def get_retry_delay(self) -> int:
        """Get retry delay in seconds"""
        return self.get("retry_delay", 2)
    
    def get_buffer_size(self) -> int:
        """Get buffer size for data transfer"""
        return self.get("buffer_size", 8192)
    
    def is_compression_enabled(self) -> bool:
        """Check if compression is enabled"""
        return self.get("enable_compression", True)
    
    def get_log_level(self) -> str:
        """Get logging level"""
        return self.get("log_level", "INFO")
    
    def is_auto_reconnect_enabled(self) -> bool:
        """Check if auto-reconnect is enabled"""
        return self.get("auto_reconnect", True)
    
    def get_connection_pool_size(self) -> int:
        """Get connection pool size"""
        return self.get("connection_pool_size", 5)
    
    def get_request_timeout(self) -> int:
        """Get request timeout in seconds"""
        return self.get("request_timeout", 60)
    
    def is_keep_alive_enabled(self) -> bool:
        """Check if keep-alive is enabled"""
        return self.get("keep_alive", True)
    
    def get_keep_alive_interval(self) -> int:
        """Get keep-alive interval in seconds"""
        return self.get("keep_alive_interval", 30)
    
    def get_batch_timeout(self) -> int:
        """Get batch timeout in seconds"""
        return self.get("batch_timeout", 600)
    
    def get_chunk_size(self) -> int:
        """Get chunk size for data transfer"""
        return self.get("chunk_size", 65536)
    
    def get_max_consecutive_failures(self) -> int:
        """Get maximum consecutive failures before reducing batch size"""
        return self.get("max_consecutive_failures", 3)
    
    def is_adaptive_batch_size_enabled(self) -> bool:
        """Check if adaptive batch size is enabled"""
        return self.get("adaptive_batch_size", True)
    
    def is_parallel_downloads_enabled(self) -> bool:
        """Check if parallel downloads are enabled"""
        return self.get("parallel_downloads", False)
    
    def get_max_parallel_batches(self) -> int:
        """Get maximum number of parallel batches"""
        return self.get("max_parallel_batches", 4)
    
    def is_tcp_nodelay_enabled(self) -> bool:
        """Check if TCP_NODELAY is enabled"""
        return self.get("tcp_nodelay", True)
    
    def get_tcp_window_size(self) -> int:
        """Get TCP window size"""
        return self.get("tcp_window_size", 8388608)  # 8MB default
    
    def is_high_bandwidth_mode_enabled(self) -> bool:
        """Check if high bandwidth mode is enabled"""
        return self.get("high_bandwidth_mode", False)
    
    def get_prefetch_batches(self) -> int:
        """Get number of batches to prefetch"""
        return self.get("prefetch_batches", 2)
    
    def update_server_settings(self, host: str, port: int, save_to_file: bool = True):
        """
        Update server settings
        
        Args:
            host (str): Server host
            port (int): Server port
            save_to_file (bool): Whether to save changes to file
        """
        self.set("socket_host", host)
        self.set("socket_port", port)
        if save_to_file:
            self.save_config()
        logger.info(f"🔄 Updated server settings: {host}:{port}")
    
    def update_server_settings_temporary(self, host: str, port: int):
        """
        Update server settings temporarily without saving to file
        
        Args:
            host (str): Server host
            port (int): Server port
        """
        self.update_server_settings(host, port, save_to_file=False)
    
    def get_server_settings(self) -> Dict[str, Any]:
        """
        Get server settings
        
        Returns:
            dict: Server settings
        """
        return {
            "host": self.get_socket_host(),
            "port": self.get_socket_port(),
            "timeout": self.get_connection_timeout(),
            "max_retries": self.get_max_retries(),
            "retry_delay": self.get_retry_delay()
        }
    
    def validate_config(self) -> bool:
        """
        Validate configuration values
        
        Returns:
            bool: True if configuration is valid, False otherwise
        """
        errors = []
        
        # Validate port
        port = self.get_socket_port()
        if not isinstance(port, int) or port < 1 or port > 65535:
            errors.append(f"Invalid port: {port}")
        
        # Validate timeout
        timeout = self.get_connection_timeout()
        if not isinstance(timeout, int) or timeout < 1:
            errors.append(f"Invalid timeout: {timeout}")
        
        # Validate retry settings
        max_retries = self.get_max_retries()
        if not isinstance(max_retries, int) or max_retries < 0:
            errors.append(f"Invalid max_retries: {max_retries}")
        
        retry_delay = self.get_retry_delay()
        if not isinstance(retry_delay, int) or retry_delay < 0:
            errors.append(f"Invalid retry_delay: {retry_delay}")
        
        # Validate buffer size
        buffer_size = self.get_buffer_size()
        if not isinstance(buffer_size, int) or buffer_size < 1024:
            errors.append(f"Invalid buffer_size: {buffer_size}")
        
        if errors:
            logger.error(f"❌ Configuration validation errors: {errors}")
            return False
        
        logger.info("✅ Configuration validation passed")
        return True
    
    def reset_to_defaults(self):
        """Reset configuration to default values"""
        self.config = self._load_default_config()
        self.save_config()
        logger.info("🔄 Reset configuration to defaults")
    
    def get_all_config(self) -> Dict[str, Any]:
        """
        Get all configuration values
        
        Returns:
            dict: All configuration values
        """
        return self.config.copy()


# Global configuration instance
_socket_config = None


def get_socket_config() -> SocketConfig:
    """
    Get global Socket configuration instance
    
    Returns:
        SocketConfig: Global configuration instance
    """
    global _socket_config
    if _socket_config is None:
        logger.info("🔧 Creating new SocketConfig")
        _socket_config = SocketConfig()
        logger.info("✅ SocketConfig created successfully")
    return _socket_config


def update_socket_server_settings(host: str, port: int):
    """
    Update global Socket server settings
    
    Args:
        host (str): Server host
        port (int): Server port
    """
    config = get_socket_config()
    config.update_server_settings(host, port)


def get_socket_server_settings() -> Dict[str, Any]:
    """
    Get global Socket server settings
    
    Returns:
        dict: Server settings
    """
    config = get_socket_config()
    return config.get_server_settings()

#
# # Example usage
# if __name__ == "__main__":
#     # Test configuration
#     config = SocketConfig()
#
#     print("=== Socket Configuration ===")
#     print(f"Host: {config.get_socket_host()}")
#     print(f"Port: {config.get_socket_port()}")
#     print(f"Timeout: {config.get_connection_timeout()}")
#     print(f"Max Retries: {config.get_max_retries()}")
#     print(f"Buffer Size: {config.get_buffer_size()}")
#     print(f"Compression: {config.is_compression_enabled()}")
#     print(f"Auto Reconnect: {config.is_auto_reconnect_enabled()}")
#
#     # Validate configuration
#     if config.validate_config():
#         print("✅ Configuration is valid")
#     else:
#         print("❌ Configuration has errors")
#
#     # Test server settings update
#     config.update_server_settings("192.168.1.100", 50053)
#     print(f"Updated server: {config.get_socket_host()}:{config.get_socket_port()}")
