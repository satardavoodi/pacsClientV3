from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def _config_path() -> Path:
    app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    cfg_dir = app_data / "PacsClient" / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    return cfg_dir / "echomind_settings.json"


def _defaults() -> Dict[str, Any]:
    return {
        "api_key": "",
        "secretary_stt_provider": "native",  # native | v2t
        "secretary_stt_fallback": True,
    }


def load_settings() -> Dict[str, Any]:
    out = _defaults()
    fp = _config_path()
    try:
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            if isinstance(data, dict):
                out.update(data)
    except Exception:
        pass
    return out


def save_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = load_settings()
    cur.update(patch or {})
    fp = _config_path()
    tmp = fp.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, indent=2, ensure_ascii=False)
    os.replace(tmp, fp)
    return cur


def get_echomind_api_key() -> str:
    return str(load_settings().get("api_key") or "").strip()


def set_echomind_api_key(api_key: str) -> Dict[str, Any]:
    return save_settings({"api_key": (api_key or "").strip()})


def get_secretary_stt_route() -> str:
    route = str(load_settings().get("secretary_stt_provider") or "native").strip().lower()
    return "v2t" if route == "v2t" else "native"


def set_secretary_stt_route(route: str) -> Dict[str, Any]:
    normalized = "v2t" if str(route).strip().lower() == "v2t" else "native"
    return save_settings({"secretary_stt_provider": normalized})
