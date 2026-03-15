"""
api_manager.py
Centralized API Key management for AI Chat system
- Hardcoded centers registry (NO external JSON)
- Scalable validation for many keys
- Minimal usage logging (NO prompts / NO history)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List
from pathlib import Path
from datetime import datetime
import os
import json
import hashlib

from PySide6.QtCore import QObject, Signal


# ============================================================
# ✅ 1) HARD-CODED CENTERS REGISTRY (single source of truth)
#    Add as many centers/keys as you want here.
# ============================================================

@dataclass(frozen=True)
class CenterRecord:
    center_code: str
    center_display: str
    gapgpt_key: str
    irannobat_keys: List[str]


CENTERS: List[CenterRecord] = [


    # ---------- RAZI ----------
    CenterRecord(
        center_code="RAZI",
        center_display="RAZI",
        gapgpt_key="sk-97OrEW0kPBVNqMsH0JOBIOHvCHAo3RsZKxpaEABzheRp42M0",
        irannobat_keys=[
            "Ai-pacs/razi245608",
        ],
    ),
    # ---------- IMA ----------
    CenterRecord(
        center_code="IMA",
        center_display="Ima Center (Dr. Somayeh Karimi)",
        gapgpt_key="sk-wZi7MgxTzepbXEEn3dIXuvAfJLmbgPKtOm8td1nZcrTSY8JX",
        irannobat_keys=[
            "Ai-pacs/lma25106",
        ],
    ),

    # ---------- ROOHANI ----------
    CenterRecord(
        center_code="ROOHANI",
        center_display="Dr. Mohammad Mojtaba Roohani Center",
        gapgpt_key="sk-m1SzlAt5EObPWzsL16HJ6LJ7uT1I9ghus9kWcwJmv5tvLkKc",
        irannobat_keys=[
            "Ai-Pacs/#Mojtabaro1028",
        ],
    ),

    # ---------- HASANPOUR ----------
    CenterRecord(
        center_code="HASANPOUR",
        center_display="Dr. Hasanpour Center",
        gapgpt_key="sk-73j1VOTkU9T0RXj9bGPxSQgN7pjcCi7Uaz8CgMnC7JMoryBt",
        irannobat_keys=[
            "Ai-Pacs/Ctmrisono53&",
        ],
    ),  
      
    # ---------- ASSARZADEGAN ----------
    CenterRecord(
        center_code="ASSARZADEGAN",
        center_display="Dr. Assarzadegan Center",
        gapgpt_key="sk-qv9AOqM7AN0z4jUF4Ajo2DhlBuaGi2PiZecpsdWP8t23iwJf",
        irannobat_keys=[
            "Ai-Pacs/Assar@1394",
        ],
    ),    

    # ---------- BRAKE ----------
    CenterRecord(
        center_code="BRAKE",
        center_display="Dr. Somayeh Brake Center",
        gapgpt_key="sk-SKMmphBGVb0OeEw7HtA8Fk7bWH9OGOpTnDaMa3lnatDbfQBY",
        irannobat_keys=[
            "Ai-Pacs/Brake@3161",
        ],
    ),    
]

def _normalize_key(k: str) -> str:
    return (k or "").strip()


def _build_registry_maps(centers: List[CenterRecord]) -> tuple[Dict[str, CenterRecord], Dict[str, str]]:
    """
    Build:
      - centers_by_code[CODE] -> CenterRecord
      - key_to_center_code[IRANNOBAT_KEY] -> CODE

    This ensures O(1) validation for large number of keys.
    """
    centers_by_code: Dict[str, CenterRecord] = {}
    key_to_center_code: Dict[str, str] = {}

    for c in centers:
        code = (c.center_code or "").strip().upper()
        if not code:
            continue

        centers_by_code[code] = CenterRecord(
            center_code=code,
            center_display=(c.center_display or code).strip(),
            gapgpt_key=_normalize_key(c.gapgpt_key),
            irannobat_keys=[_normalize_key(x) for x in (c.irannobat_keys or []) if _normalize_key(x)],
        )

        for k in centers_by_code[code].irannobat_keys:
            key_to_center_code[k] = code

    return centers_by_code, key_to_center_code


_CENTERS_BY_CODE, _KEY_TO_CENTER_CODE = _build_registry_maps(CENTERS)


def register_center(center: CenterRecord) -> None:
    """
    Optional: allow runtime registration (still "hardcoded", but usable).
    """
    global _CENTERS_BY_CODE, _KEY_TO_CENTER_CODE, CENTERS
    CENTERS.append(center)
    _CENTERS_BY_CODE, _KEY_TO_CENTER_CODE = _build_registry_maps(CENTERS)



class APIKeyManager(QObject):
    """
    Singleton manager for API keys and validation.
    """

    keyValidated = Signal(str, str)  # (center_code, api_key)
    keyInvalid = Signal(str)         # (error_message)

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        super().__init__()
        self._initialized = True

        self._current_api_key: Optional[str] = None
        self._current_center_code: Optional[str] = None
        self._is_validated: bool = False

    @classmethod
    def instance(cls) -> "APIKeyManager":
        return cls()

    def validate_key(self, api_key: str) -> tuple[bool, Optional[str], Optional[str]]:
        if not api_key or not isinstance(api_key, str):
            return False, None, "API Key cannot be empty"

        api_key = api_key.strip()
        center_code = _KEY_TO_CENTER_CODE.get(api_key)

        if center_code:
            self._current_api_key = api_key
            self._current_center_code = center_code
            self._is_validated = True
            self.keyValidated.emit(center_code, api_key)
            return True, center_code, None

        self._is_validated = False
        error_msg = "❌ Invalid API Key. Please contact administrator."
        self.keyInvalid.emit(error_msg)
        return False, None, error_msg

    def get_current_key(self) -> Optional[str]:
        return self._current_api_key if self._is_validated else None

    def get_current_center(self) -> Optional[str]:
        return self._current_center_code if self._is_validated else None

    def is_validated(self) -> bool:
        return self._is_validated

    def reset(self):
        self._current_api_key = None
        self._current_center_code = None
        self._is_validated = False



@dataclass(frozen=True)
class CenterInfo:
    center_code: str
    center_display: str
    irannobat_key: str
    gapgpt_key: str

class Manage:
    _instance: Optional["Manage"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._mgr = APIKeyManager.instance()
            cls._instance._detected: Optional[CenterInfo] = None
            cls._instance._last_api_key: Optional[str] = None
        return cls._instance

    @classmethod
    def instance(cls) -> "Manage":
        return cls()


    def is_validated(self) -> bool:
        return bool(self._mgr.is_validated())

    def get_irannobat_key(self) -> str:
        key = self._mgr.get_current_key()
        if not self._mgr.is_validated() or not key:
            raise ValueError("❌ No validated IRANNOBAT API key.")
        return key.strip()

    def get_center_code(self) -> str:
        c = self._mgr.get_current_center()
        if not self._mgr.is_validated() or not c:
            raise ValueError("❌ No validated center.")
        return c.strip().upper()

    def detect_center(self, irannobat_key: Optional[str] = None) -> CenterInfo:
        if irannobat_key is None:
            irannobat_key = self.get_irannobat_key()

        k = (irannobat_key or "").strip()
        if not k:
            raise ValueError("❌ Empty IRANNOBAT key.")

        self._last_api_key = k 

        center_code = _KEY_TO_CENTER_CODE.get(k)
        if not center_code:
            raise ValueError("❌ Invalid Center API key. Contact provider.")

        rec = _CENTERS_BY_CODE.get(center_code)
        if not rec:
            raise ValueError(f"❌ Center '{center_code}' not found in hardcoded registry.")

        info = CenterInfo(
            center_code=rec.center_code,
            center_display=rec.center_display,
            irannobat_key=k,
            gapgpt_key=rec.gapgpt_key,
        )
        self._detected = info
        return info

    def get_last_api_key(self) -> Optional[str]:
        return self._last_api_key

    def ensure_detected(self) -> CenterInfo:
        current_key = self.get_irannobat_key()
        if self._detected is None or self._detected.irannobat_key != current_key:
            return self.detect_center(current_key)
        return self._detected

    def get_center_and_gapgpt_key(self) -> Tuple[str, str]:
        info = self.ensure_detected()
        return info.center_display, info.gapgpt_key

    def get_detected_center_display(self) -> str:
        try:
            return self.ensure_detected().center_display
        except Exception:
            c = self._mgr.get_current_center()
            return (c or "Unknown").title()


    def _get_usage_file(self) -> Path:
        try:
            from PacsClient.utils.data_paths import ECHOMIND_DIR
            base = Path(ECHOMIND_DIR)
        except Exception:
            base = Path.cwd() / "data"
        base.mkdir(parents=True, exist_ok=True)
        return base / "api_usage.json"

    def _now_iso(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _key_id(self, api_key: str) -> str:
        digest = hashlib.sha256((api_key or "").strip().encode("utf-8")).hexdigest()
        return f"sha256:{digest[:16]}"

    def _load_usage(self) -> dict:
        fp = self._get_usage_file()
        if not fp.exists():
            return {"schema": 2, "updated_at": None, "keys": {}}
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or data.get("schema") != 2:
                return {"schema": 2, "updated_at": None, "keys": {}}
            data.setdefault("keys", {})
            return data
        except Exception:
            return {"schema": 2, "updated_at": None, "keys": {}}

    def _save_usage(self, data: dict) -> None:
        fp = self._get_usage_file()
        data["schema"] = 2
        data["updated_at"] = self._now_iso()
        tmp = fp.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, fp)

    def _ensure_nodes(self, data: dict, key_id: str, info: CenterInfo, model: str) -> dict:
        keys = data.setdefault("keys", {})
        if key_id not in keys:
            keys[key_id] = {
                "center_code": info.center_code,
                "center_display": info.center_display,
                "models": {}
            }

        keys[key_id]["center_code"] = info.center_code
        keys[key_id]["center_display"] = info.center_display

        models = keys[key_id].setdefault("models", {})
        if model not in models:
            models[model] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "last_used": None
            }
        return models[model]

    # اگر split prompt/completion داری:
    def update_usage(self, *args, **kwargs) -> None:
        """
        Backward-compatible usage logger.

        Supports calls:
          - update_usage(model, prompt_tokens, completion_tokens)
          - update_usage(center_name, model, prompt_tokens, completion_tokens)
          - update_usage(center_name, model, prompt_tokens, completion_tokens, user_msg)

        NOTE: user_msg is intentionally ignored (NOT stored).
        """
        if not self.is_validated():
            return

        # Extract from kwargs if present
        user_msg = kwargs.pop("user_msg", None)  # ignored
        center_name = kwargs.pop("center_name", None)
        model = kwargs.pop("model", None)
        prompt_tokens = kwargs.pop("prompt_tokens", None)
        completion_tokens = kwargs.pop("completion_tokens", None)

        # If kwargs didn't provide, parse positional
        if model is None and prompt_tokens is None and completion_tokens is None:
            if len(args) == 3:
                # (model, p, c)
                model, prompt_tokens, completion_tokens = args
            elif len(args) == 4:
                # (center, model, p, c)
                center_name, model, prompt_tokens, completion_tokens = args
            elif len(args) >= 5:
                # (center, model, p, c, user_msg, ...)
                center_name, model, prompt_tokens, completion_tokens = args[:4]
                # user_msg = args[4]  # ignored
            else:
                raise TypeError("update_usage expected (model,p,c) or (center,model,p,c[,user_msg])")

        # Normalize
        model = str(model)
        p = int(prompt_tokens or 0)
        c = int(completion_tokens or 0)

        info = self.ensure_detected()
        api_key = self.get_irannobat_key()
        key_id = self._key_id(api_key)

        data = self._load_usage()
        node = self._ensure_nodes(data, key_id, info, model)

        node["requests"] += 1
        node["prompt_tokens"] += p
        node["completion_tokens"] += c
        node["total_tokens"] += (p + c)
        node["last_used"] = self._now_iso()

        self._save_usage(data)

                # --- ALSO persist to SQLite DB (for Welcome UI) ---
        try:
            from PacsClient.utils.database import add_api_token_usage_delta, add_token_usage_delta
            # total delta for this request:
            delta = int(p + c)
            if delta > 0:
                add_api_token_usage_delta(
                    api_key=api_key,
                    center_name=info.center_display,
                    model_name=model,
                    tokens_delta=delta,
                )
                # (Optional) per-center aggregate table as well:
                add_token_usage_delta(
                    center=info.center_display,
                    model=model,
                    tokens_delta=delta,
                )
        except Exception:
            # don't break main app if DB unavailable
            pass

    # اگر فقط total داری:
    def update_usage_total(self, *args, **kwargs) -> None:
        """
        Backward-compatible total logger.

        Supports calls:
          - update_usage_total(model, total_tokens)
          - update_usage_total(center_name, model, total_tokens)
        """
        if not self.is_validated():
            return

        center_name = kwargs.pop("center_name", None)  # ignored (we use detected info)
        model = kwargs.pop("model", None)
        total_tokens = kwargs.pop("total_tokens", None)

        if model is None and total_tokens is None:
            if len(args) == 2:
                model, total_tokens = args
            elif len(args) >= 3:
                # (center, model, total, ...)
                _, model, total_tokens = args[:3]
            else:
                raise TypeError("update_usage_total expected (model,total) or (center,model,total)")

        model = str(model)
        t = int(total_tokens or 0)

        info = self.ensure_detected()
        api_key = self.get_irannobat_key()
        key_id = self._key_id(api_key)

        data = self._load_usage()
        node = self._ensure_nodes(data, key_id, info, model)

        node["requests"] += 1
        node["total_tokens"] += t
        node["last_used"] = self._now_iso()

        self._save_usage(data)

                # --- ALSO persist to SQLite DB (for Welcome UI) ---
        try:
            from PacsClient.utils.database import add_api_token_usage_delta, add_token_usage_delta
            delta = int(t or 0)
            if delta > 0:
                add_api_token_usage_delta(
                    api_key=api_key,
                    center_name=info.center_display,
                    model_name=model,
                    tokens_delta=delta,
                )
                add_token_usage_delta(
                    center=info.center_display,
                    model=model,
                    tokens_delta=delta,
                )
        except Exception:
            pass



    def get_usage_summary_text_current_key(self) -> str:
        if not self.is_validated():
            return "No validated API key."

        api_key = self.get_irannobat_key()
        key_id = self._key_id(api_key)

        data = self._load_usage()
        k = data.get("keys", {}).get(key_id)
        if not k:
            return f"Key: {key_id}\nNo usage yet."

        models = (k.get("models") or {})
        total = sum(int(m.get("total_tokens", 0)) for m in models.values())

        lines = [
            f"Center: {k.get('center_display','Unknown')} ({k.get('center_code','?')})",
            f"Key: {key_id}",
            f"Total: {total:,} tokens"
        ]
        for name, m in sorted(models.items(), key=lambda kv: kv[0]):
            lines.append(f"  - {name}: {int(m.get('total_tokens',0)):,} tokens ({int(m.get('requests',0))} req)")
        return "\n".join(lines)
