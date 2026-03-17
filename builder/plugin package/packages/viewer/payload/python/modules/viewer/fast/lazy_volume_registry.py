from __future__ import annotations

import threading
import uuid
from typing import Dict, Optional


_LOCK = threading.Lock()
_REGISTRY: Dict[str, Dict[str, object]] = {}


def register_loader(loader: object) -> str:
    key = uuid.uuid4().hex
    with _LOCK:
        _REGISTRY[key] = {"loader": loader, "refs": 0}
    return key


def get_loader(key: Optional[str]) -> Optional[object]:
    if not key:
        return None
    with _LOCK:
        entry = _REGISTRY.get(str(key))
        if not entry:
            return None
        return entry.get("loader")


def acquire_loader(key: Optional[str]) -> Optional[object]:
    if not key:
        return None
    with _LOCK:
        entry = _REGISTRY.get(str(key))
        if not entry:
            return None
        entry["refs"] = int(entry.get("refs", 0) or 0) + 1
        return entry.get("loader")


def release_loader(key: Optional[str]) -> None:
    if not key:
        return
    loader = None
    should_close = False
    key_str = str(key)
    with _LOCK:
        entry = _REGISTRY.get(key_str)
        if not entry:
            return
        refs = int(entry.get("refs", 0) or 0) - 1
        entry["refs"] = refs
        if refs <= 0:
            loader = entry.get("loader")
            _REGISTRY.pop(key_str, None)
            should_close = True
    if should_close and loader is not None:
        try:
            close_fn = getattr(loader, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass


def unregister_loader(key: Optional[str]) -> None:
    if not key:
        return
    loader = None
    with _LOCK:
        entry = _REGISTRY.pop(str(key), None)
        if entry:
            loader = entry.get("loader")
    if loader is not None:
        try:
            close_fn = getattr(loader, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass
