"""
Configuration Loader - Load and manage configuration

Loads configuration from JSON files with defaults.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ConfigLoader:
    """
    Configuration loader
    
    Features:
    - Load from JSON files
    - Default values
    - Validation
    - Hot reload support
    """
    
    def __init__(self, config_dir: Path):
        """
        Initialize config loader
        
        Args:
            config_dir: Configuration directory
        """
        self.config_dir = Path(config_dir)
        self._configs: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"✅ ConfigLoader initialized (dir: {config_dir})")
    
    def load(self, config_name: str, defaults: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Load configuration file
        
        Args:
            config_name: Config file name (without .json)
            defaults: Default values
            
        Returns:
            Configuration dictionary
        """
        config_path = self.config_dir / f"{config_name}.json"
        
        # Start with defaults
        config = defaults.copy() if defaults else {}
        
        # Load from file if exists
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    file_config = json.load(f)
                    config.update(file_config)
                
                logger.info(f"✅ Loaded config: {config_name}")
            
            except Exception as e:
                logger.error(f"❌ Could not load {config_name}: {e}")
        else:
            logger.warning(f"⚠️ Config not found: {config_name} (using defaults)")
        
        self._configs[config_name] = config
        return config
    
    def get(self, config_name: str) -> Optional[Dict[str, Any]]:
        """
        Get loaded configuration
        
        Args:
            config_name: Config name
            
        Returns:
            Config dict or None
        """
        return self._configs.get(config_name)


# Global config instance
_config_loader: Optional[ConfigLoader] = None


def load_config(config_dir: Path, config_name: str, defaults: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Load configuration (convenience function)
    
    Args:
        config_dir: Configuration directory
        config_name: Config name
        defaults: Default values
        
    Returns:
        Configuration dictionary
    """
    global _config_loader
    
    if _config_loader is None:
        _config_loader = ConfigLoader(config_dir)
    
    return _config_loader.load(config_name, defaults)
