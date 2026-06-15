"""Secure storage for external-identity secrets (OAuth refresh tokens, etc.).

Primary backend: the OS keychain via :mod:`keyring` (Windows Credential Manager).
Fallback: an encrypted file using :class:`cryptography.fernet.Fernet`, with the key
stored beside it (user-readable only). The fallback is convenience for environments
without a keychain; **DPAPI-sealing of the fallback key is a planned hardening step**
(see the plan doc, §10).

Never stores passwords. Stores only opaque token payloads keyed by
``(provider, subject_id)``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SERVICE = "AIPacs-Identity"


# ── keyring backend ───────────────────────────────────────────────────────────
def _keyring():
    """Return the keyring module if a *usable* (non-fail) backend exists, else None."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as _FailKeyring

        backend = keyring.get_keyring()
        if isinstance(backend, _FailKeyring):
            return None
        return keyring
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.debug("keyring unavailable: %s", exc)
        return None


def _account(provider: str, subject_id: str) -> str:
    return f"{provider}:{subject_id}"


# ── public API ─────────────────────────────────────────────────────────────────
def save_secret(provider: str, subject_id: str, payload: dict[str, Any]) -> bool:
    blob = json.dumps(payload)
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(_SERVICE, _account(provider, subject_id), blob)
            return True
        except Exception as exc:
            logger.warning("keyring save failed; using encrypted-file fallback: %s", exc)
    return _fallback_save(provider, subject_id, blob)


def load_secret(provider: str, subject_id: str) -> dict[str, Any] | None:
    kr = _keyring()
    if kr is not None:
        try:
            blob = kr.get_password(_SERVICE, _account(provider, subject_id))
            if blob:
                return json.loads(blob)
        except Exception as exc:
            logger.warning("keyring load failed: %s", exc)
    return _fallback_load(provider, subject_id)


def delete_secret(provider: str, subject_id: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(_SERVICE, _account(provider, subject_id))
        except Exception as exc:
            logger.debug("keyring delete (ignored): %s", exc)
    _fallback_delete(provider, subject_id)


# ── encrypted-file fallback ─────────────────────────────────────────────────────
def _fallback_dir() -> Path:
    from modules.Identity.config import identity_config_dir

    d = identity_config_dir() / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(provider: str, subject_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", f"{provider}__{subject_id}")


def _fernet():
    from cryptography.fernet import Fernet

    keyfile = _fallback_dir() / "store.key"
    if keyfile.exists():
        key = keyfile.read_bytes()
    else:
        key = Fernet.generate_key()
        keyfile.write_bytes(key)
        _restrict_permissions(keyfile)
    return Fernet(key)


def _restrict_permissions(path: Path) -> None:
    try:
        import os
        import stat

        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 (best effort)
    except Exception as exc:  # pragma: no cover - platform dependent
        logger.debug("could not restrict permissions on %s: %s", path, exc)


def _fallback_save(provider: str, subject_id: str, blob: str) -> bool:
    try:
        enc = _fernet().encrypt(blob.encode("utf-8"))
        target = _fallback_dir() / (_safe_name(provider, subject_id) + ".enc")
        target.write_bytes(enc)
        _restrict_permissions(target)
        return True
    except Exception as exc:
        logger.error("secure fallback save failed: %s", exc)
        return False


def _fallback_load(provider: str, subject_id: str) -> dict[str, Any] | None:
    try:
        target = _fallback_dir() / (_safe_name(provider, subject_id) + ".enc")
        if not target.exists():
            return None
        dec = _fernet().decrypt(target.read_bytes())
        return json.loads(dec.decode("utf-8"))
    except Exception as exc:
        logger.error("secure fallback load failed: %s", exc)
        return None


def _fallback_delete(provider: str, subject_id: str) -> None:
    try:
        target = _fallback_dir() / (_safe_name(provider, subject_id) + ".enc")
        if target.exists():
            target.unlink()
    except Exception as exc:  # pragma: no cover
        logger.debug("secure fallback delete (ignored): %s", exc)
