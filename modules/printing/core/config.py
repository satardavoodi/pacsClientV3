"""Configuration helpers for the printing module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any


def _default_config_path() -> Path:
    try:
        from PacsClient.utils.config import BASE_PATH
        return BASE_PATH / "config" / "printing_config.json"
    except Exception:
        return Path("config") / "printing_config.json"


def load_printing_config(path: Path | None = None) -> Dict[str, Any]:
    config_path = path or _default_config_path()
    defaults = {
        "printers": [],
        "default_film_sizes": [
            {"name": "14x17", "width_in": 14.0, "height_in": 17.0},
            {"name": "11x14", "width_in": 11.0, "height_in": 14.0},
            {"name": "8x10", "width_in": 8.0, "height_in": 10.0},
        ],
        "default_layouts": [
            {"rows": 4, "cols": 5},
            {"rows": 4, "cols": 4},
            {"rows": 3, "cols": 4},
        ],
    }
    if not config_path.exists():
        return defaults
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
            merged = defaults | data
            return merged
    except Exception:
        return defaults


def save_printing_config(data: Dict[str, Any], path: Path | None = None) -> Path:
    config_path = path or _default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    return config_path
