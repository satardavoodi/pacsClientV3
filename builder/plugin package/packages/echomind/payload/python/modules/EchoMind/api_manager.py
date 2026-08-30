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
import hmac
import logging
import threading

from PySide6.QtCore import QObject, Signal

from modules.EchoMind.center_registry import ENCRYPTED_CENTERS
from modules.EchoMind.credential_envelope import (
    CredentialEnvelope,
    CredentialEnvelopeError,
    access_code_lookup,
    open_provider_key,
)


logger = logging.getLogger(__name__)


# ── F10 (2026-07-28): the usage file is a read-modify-write with no lock ─────
# `update_usage` / `update_usage_total` run on whatever ApiWorker thread just
# received a response: they `_load_usage()` (full JSON read), increment in
# memory, then `_save_usage()` (full rewrite). Concurrent workers are entirely
# possible — `ai_chat_pages._run_async` tracks workers in a LIST with a
# `_busy_count` that can exceed 1, and `_ORPHANED_WORKERS` holds detached
# in-flight workers from closed pages. Two overlapping responses therefore raced
# and one increment was silently lost (last writer wins).
#
# `os.replace` in `_save_usage` already makes each WRITE atomic, so the file was
# never torn — the defect is lost counts, i.e. under-reported token usage. This
# lock closes the read-modify-write window. It is process-local, which is the
# right scope: the usage file is per-user and only this process writes it.
_USAGE_LOCK = threading.Lock()


# ============================================================
# 1) PROTECTED CENTERS REGISTRY (single source of truth)
# ============================================================

@dataclass(frozen=True)
class CenterRecord:
    center_code: str
    center_display: str
    credentials: tuple[CredentialEnvelope, ...]


def _load_center_records(raw_centers) -> List[CenterRecord]:
    records: List[CenterRecord] = []
    for raw in raw_centers or ():
        credentials = tuple(
            CredentialEnvelope(
                lookup_digest=str(item.get("lookup_digest") or ""),
                kdf_salt_b64=str(item.get("kdf_salt_b64") or ""),
                nonce_b64=str(item.get("nonce_b64") or ""),
                ciphertext_b64=str(item.get("ciphertext_b64") or ""),
            )
            for item in raw.get("credentials", ())
        )
        records.append(
            CenterRecord(
                center_code=str(raw.get("center_code") or "").strip().upper(),
                center_display=str(raw.get("center_display") or "").strip(),
                credentials=credentials,
            )
        )
    return records


CENTERS: List[CenterRecord] = _load_center_records(ENCRYPTED_CENTERS)

#: Development-only records remain encrypted and are omitted from both runtime maps unless
#: explicitly enabled. No shipped build sets this environment variable.
_DEV_ONLY_CENTER_CODES = ("TEST",)
_ENV_ALLOW_TEST_CENTER = "AIPACS_ALLOW_TEST_CENTER"


def test_center_enabled() -> bool:
    """Whether development-only centers are part of the runtime registry."""
    raw = os.environ.get(_ENV_ALLOW_TEST_CENTER)
    return bool(raw) and str(raw).strip().lower() not in ("0", "false", "no", "off")


def _build_registry_maps(
    centers: List[CenterRecord],
) -> tuple[Dict[str, CenterRecord], Dict[str, str]]:
    """Build center and access-code lookup maps without retaining plaintext secrets."""
    centers_by_code: Dict[str, CenterRecord] = {}
    lookup_to_center_code: Dict[str, str] = {}
    allow_dev = test_center_enabled()
    for center in centers:
        code = str(center.center_code or "").strip().upper()
        if not code or (code in _DEV_ONLY_CENTER_CODES and not allow_dev):
            continue
        credentials = tuple(center.credentials or ())
        if not credentials:
            continue
        record = CenterRecord(
            center_code=code,
            center_display=str(center.center_display or code).strip(),
            credentials=credentials,
        )
        centers_by_code[code] = record
        for credential in credentials:
            lookup = str(credential.lookup_digest or "").strip().lower()
            if not lookup:
                continue
            if lookup in lookup_to_center_code:
                raise ValueError("Duplicate protected EchoMind access-code lookup.")
            lookup_to_center_code[lookup] = code
    return centers_by_code, lookup_to_center_code


_CENTERS_BY_CODE, _KEY_TO_CENTER_CODE = _build_registry_maps(CENTERS)


def register_center(center: CenterRecord) -> None:
    """Register an already-protected center record for this process."""
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
        self._current_provider_key: Optional[str] = None
        self._is_validated: bool = False

    @classmethod
    def instance(cls) -> "APIKeyManager":
        return cls()

    def validate_key(self, api_key: str) -> tuple[bool, Optional[str], Optional[str]]:
        if not api_key or not isinstance(api_key, str):
            return False, None, "API Key cannot be empty"

        api_key = api_key.strip()
        try:
            lookup = access_code_lookup(api_key)
            center_code = _KEY_TO_CENTER_CODE.get(lookup)
            record = _CENTERS_BY_CODE.get(center_code or "")
            envelope = next(
                (
                    item
                    for item in (record.credentials if record else ())
                    if hmac.compare_digest(item.lookup_digest, lookup)
                ),
                None,
            )
            if not center_code or record is None or envelope is None:
                raise CredentialEnvelopeError("Invalid EchoMind access code.")
            provider_key = open_provider_key(api_key, envelope, center_code)
        except (CredentialEnvelopeError, ValueError):
            center_code = None
            provider_key = ""
        except Exception as exc:
            # Credential validation is a fail-closed boundary. Missing crypto
            # support or an unexpected registry/runtime failure must deny access
            # without leaking credential details to the UI or logs.
            logger.error(
                "EchoMind credential validation failed closed (%s).",
                type(exc).__name__,
            )
            center_code = None
            provider_key = ""

        if center_code and provider_key:
            self._current_api_key = api_key
            self._current_center_code = center_code
            self._current_provider_key = provider_key
            self._is_validated = True
            self.keyValidated.emit(center_code, api_key)
            return True, center_code, None

        self._current_api_key = None
        self._current_center_code = None
        self._current_provider_key = None
        self._is_validated = False
        error_msg = "❌ Invalid API Key. Please contact administrator."
        self.keyInvalid.emit(error_msg)
        return False, None, error_msg

    def get_current_key(self) -> Optional[str]:
        return self._current_api_key if self._is_validated else None

    def get_current_center(self) -> Optional[str]:
        return self._current_center_code if self._is_validated else None

    def get_current_provider_key(self) -> Optional[str]:
        return self._current_provider_key if self._is_validated else None

    def is_validated(self) -> bool:
        return self._is_validated

    def reset(self):
        self._current_api_key = None
        self._current_center_code = None
        self._current_provider_key = None
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

        try:
            lookup = access_code_lookup(k)
        except CredentialEnvelopeError as exc:
            raise ValueError("❌ Invalid Center API key. Contact provider.") from exc
        center_code = _KEY_TO_CENTER_CODE.get(lookup)
        if not center_code:
            raise ValueError("❌ Invalid Center API key. Contact provider.")

        rec = _CENTERS_BY_CODE.get(center_code)
        if not rec:
            raise ValueError(f"❌ Center '{center_code}' not found in protected registry.")

        current_key = self._mgr.get_current_key()
        if not self._mgr.is_validated() or current_key != k:
            ok, _validated_center, error = self._mgr.validate_key(k)
            if not ok:
                raise ValueError(error or "❌ Invalid Center API key. Contact provider.")
        provider_key = self._mgr.get_current_provider_key()
        if not provider_key:
            raise ValueError("❌ Center provider credential could not be opened.")

        info = CenterInfo(
            center_code=rec.center_code,
            center_display=rec.center_display,
            irannobat_key=k,
            gapgpt_key=provider_key,
        )
        self._last_api_key = k
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

        # F10: read-modify-write must be atomic across ApiWorker threads.
        with _USAGE_LOCK:
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

        # F10: read-modify-write must be atomic across ApiWorker threads.
        with _USAGE_LOCK:
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
