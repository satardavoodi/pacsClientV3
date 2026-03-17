"""
BoostViewer settings persistence.

Stores a single toggle that controls automatic ZetaBoost warmup behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

from aipacs_runtime import roaming_config_root

_CONFIG_KEY = "BoostViewer"
_DEFAULT_ENABLED = True


def _config_path() -> Path:
    cfg_dir = roaming_config_root()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "boostviewer_settings.json"


def load_boost_viewer_enabled(default: bool = _DEFAULT_ENABLED) -> bool:
    path = _config_path()
    try:
        if not path.exists():
            return bool(default)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get(_CONFIG_KEY, default))
    except Exception:
        return bool(default)


def save_boost_viewer_enabled(enabled: bool) -> bool:
    path = _config_path()
    try:
        payload = {_CONFIG_KEY: bool(enabled)}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


def get_boost_viewer_setting_key() -> str:
    return _CONFIG_KEY
