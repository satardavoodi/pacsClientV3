# -*- coding: utf-8 -*-

import json
import os
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)
from PacsClient.utils.config import SOCKET_CONFIG_PATH

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
            "buffer_size": 262144,  # OPTIMIZED: 256KB for DICOM files (was 8KB)
            "enable_compression": True,
            "log_level": "INFO",
            "auto_reconnect": True,
            "connection_pool_size": 5,
            "request_timeout": 60,
            "keep_alive": True,
            "keep_alive_interval": 30,
            # === PERFORMANCE OPTIMIZATIONS ===
            # NOTE: parallel_downloads is for SERIES-LEVEL parallelism within ONE patient
            # Multiple patients are ALWAYS downloaded sequentially (one at a time)
            "parallel_downloads": False,  # Series-level parallelism (disabled by default for safety)
            "high_bandwidth_mode": False,  # DISABLED: Conservative buffer settings for stability
            "tcp_nodelay": True,           # Low latency mode
            "tcp_window_size": 1048576,    # 1MB TCP window (conservative)
            "chunk_size": 65536,           # 64KB chunks (standard)
            "adaptive_batch_size": True,   # Adjust batch size based on network conditions
            "max_parallel_batches": 3,     # Max 3 series in parallel (within same patient)
            "prefetch_batches": 2,         # Prefetch 2 batches ahead
            "batch_timeout": 120           # 2 min batch timeout (was 10 min)
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

    def get_patient_list_fallback_mode(self):
        """MongoDB $sortArray compatibility (incident 2026-06-15): pin the
        GetPatientList query mode for a known-legacy server.
        None (default) -> automatic: normal first, fall back only on the
        $sortArray error. 'compatibility' / 'simple' -> always use that mode."""
        mode = self.get("patient_list_fallback_mode", None)
        if isinstance(mode, str) and mode.strip().lower() in ("compatibility", "simple"):
            return mode.strip().lower()
        return None

    def is_force_compatibility_mode(self) -> bool:
        """Start GetPatientList in compatibility mode immediately (skip the
        normal attempt) for servers known to run MongoDB < 5.2."""
        return bool(self.get("force_compatibility_mode", False))
    
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

    def is_poor_connectivity_enabled(self, host: Optional[str] = None) -> bool:
        """Per-server "Poor Connectivity" / unstable-internet download mode.

        When enabled for the active download server, the download pipeline fetches
        ONE image per batch and disables adaptive batch growth
        (see ``SocketDicomClient.download_series``). On a flaky link this makes the
        downloader retry at the single-image level and keep every image already on
        disk, instead of failing/re-fetching a whole multi-image batch.

        This is a *server-specific* setting persisted in ``config/servers.json``
        (key ``"poor_connectivity": true``). It is resolved against the host the
        download subprocess actually connects to — ``socket_host`` from
        ``socket_config.json`` — which is the same host the server's DICOM record
        uses, so the flag follows whichever server is active.

        Resolution order (first decisive wins):
          1. Env ``AIPACS_POOR_CONNECTIVITY``: ``1``/``true`` forces it ON (manual
             override for a bad link right now), ``0``/``false`` forces it OFF
             (master kill switch / legacy adaptive batching).
          2. The ``poor_connectivity`` flag on the ``servers.json`` record whose
             ``host`` matches the active socket host.
          3. Default: ``False`` (normal adaptive batching).

        Any unexpected error resolves to ``False`` so a config/import problem can
        never break downloading.
        """
        env = os.environ.get("AIPACS_POOR_CONNECTIVITY")
        if env is not None:
            return str(env).strip().lower() in ("1", "true", "yes", "on")
        try:
            active_host = str(
                host if host is not None else (self.get_socket_host() or "")
            ).strip()
            if not active_host:
                return False
            # Lazy import: avoids an import-time cycle and keeps this resolvable
            # from the download subprocess (which already imports modules.network).
            from PacsClient.utils.utils import get_all_servers
            for rec in (get_all_servers() or []):
                try:
                    if (str(rec.get("host", "")).strip() == active_host
                            and bool(rec.get("poor_connectivity", False))):
                        return True
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"poor-connectivity resolve skipped: {e}")
            return False
        return False

    def is_poor_network_progressive_load_enabled(self, host: Optional[str] = None) -> bool:
        """Umbrella switch for the slow-link "first usable image as early as
        possible" optimizations (2026-06-24): auto-load the first series into the
        viewport on open, representative/middle-slice-first download ordering, and
        the richer progressive UI feedback. It is intentionally a SUPERSET signal —
        it never changes the batch-size / single-image behaviour (that stays owned by
        ``is_poor_connectivity_enabled``); it only gates the *perception* layers.

        Resolution order (first decisive wins):
          1. Env ``AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD``: ``1``/``true`` forces it
             ON (turn the whole progressive-first-image mode on for a bad link now),
             ``0``/``false`` forces it OFF (kill switch, restores legacy behaviour).
          2. Otherwise it MIRRORS the per-server poor-connectivity flag, so a server
             already flagged ``poor_connectivity`` (e.g. mehr) gets the progressive
             optimizations automatically with no extra config.

        Any unexpected error resolves to ``False`` so it can never break the open /
        download path.
        """
        env = os.environ.get("AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD")
        if env is not None:
            return str(env).strip().lower() in ("1", "true", "yes", "on")
        try:
            return self.is_poor_connectivity_enabled(host)
        except Exception:
            return False

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

        OPT-24a (2026-07-11): skip the DISK WRITE when nothing actually changed.
        `home_search_service.search_server()` calls this before EVERY patient
        search, and `save_config()` rewrote the config file unconditionally —
        111 disk writes in one observed session with host/port never changing.
        Writing an identical file is pure I/O waste (and it also churns the
        socket connection pool downstream). The in-memory `set()` calls are kept
        unconditionally so nothing else changes.
        Kill switch: AIPACS_SOCKET_CFG_SKIP_UNCHANGED_SAVE=0 -> always save (legacy).
        """
        import os as _os
        _skip_unchanged = (
            _os.environ.get("AIPACS_SOCKET_CFG_SKIP_UNCHANGED_SAVE", "1") or "1"
        ).strip() != "0"

        _unchanged = (
            str(self.get("socket_host", "")) == str(host)
            and str(self.get("socket_port", "")) == str(port)
        )

        self.set("socket_host", host)
        self.set("socket_port", port)

        if save_to_file and not (_skip_unchanged and _unchanged):
            self.save_config()
        elif save_to_file:
            logger.debug(
                "⏭️ Socket server settings unchanged (%s:%s) — skipping config write",
                host, port,
            )
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


def _seed_from_active_profile(config: "SocketConfig") -> None:
    """Point the socket layer at the ACTIVE server profile at startup.

    When multi-server profiles are enabled, the active profile is the single
    source of truth for which center the app talks to — so login, patient
    search, and downloads all start from the active profile's host + per-server
    socket port.  No-op (byte-identical legacy behaviour, uses socket_config.json
    only) when the feature is off.  Never raises — a seeding failure must not
    break socket creation.
    """
    try:
        from PacsClient.utils.server_profiles import (
            server_profiles_enabled,
            get_active_profile,
        )

        if not server_profiles_enabled():
            return
        prof = get_active_profile()
        if not prof or not prof.host:
            return
        # save_to_file=False: the profile is authoritative; don't overwrite the
        # socket_config.json fallback with the seeded value.
        config.update_server_settings(prof.host, int(prof.socket_port), save_to_file=False)
        logger.info(
            "🔧 Socket seeded from active server profile: %s (%s:%s)",
            prof.display_name, prof.host, prof.socket_port,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Socket profile seeding skipped: %s", exc)


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
        _seed_from_active_profile(_socket_config)
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


def is_poor_connectivity_enabled() -> bool:
    """Module-level convenience: is the active download server flagged for
    "Poor Connectivity" / unstable-internet single-image download mode?

    See ``SocketConfig.is_poor_connectivity_enabled()``. Resolves to ``False`` on
    any error so it can never break the download path.
    """
    try:
        return get_socket_config().is_poor_connectivity_enabled()
    except Exception:
        return False


def is_poor_network_progressive_load_enabled() -> bool:
    """Module-level convenience: is the slow-link progressive-first-image mode
    active for the current server? See
    ``SocketConfig.is_poor_network_progressive_load_enabled()``. Resolves to
    ``False`` on any error so it can never break the open / download path.
    """
    try:
        return get_socket_config().is_poor_network_progressive_load_enabled()
    except Exception:
        return False


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
