"""credential_vault — encrypted website credentials for the Web Browser.

Security model (2026-06-11):

* Passwords are stored ONLY through ``modules.Identity.secure_store``
  (OS keychain / Windows DPAPI; Fernet-encrypted file fallback) under
  provider ``"web_browser"`` — the SAME audited store that protects
  consultation OAuth tokens. No plaintext, no base64, no hard-coding.
* A JSON index (``user_data/web_browser/credentials_index.json``) holds
  ONLY non-secret metadata: id, url, username, label, optional
  ``success_text`` (post-login marker for verification), created_at,
  last_used. The password never touches this file.
* The user stays in control: entries are created/edited through the
  browser UI (Favorites dialog) and can be deleted at any time.
* Legacy note: old bookmark entries kept base64-"encoded" passwords in
  bookmarks.json. New saves go through this vault; ``migrate_bookmark``
  lets the bookmark dialog move a legacy secret into the keychain.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PROVIDER = "web_browser"


def _index_file() -> Path:
    try:
        from PacsClient.utils.data_paths import USER_DATA_ROOT
        d = Path(USER_DATA_ROOT) / "web_browser"
    except Exception:
        d = Path.home() / ".aipacs_web_browser"
    d.mkdir(parents=True, exist_ok=True)
    return d / "credentials_index.json"


def _host(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        return (urlparse(raw).hostname or "").lower()
    except Exception:
        return ""


class CredentialVault:
    """Metadata index + keychain-backed secrets. Thread-safe."""

    def __init__(self, index_path: Optional[Path] = None):
        self._path = index_path or _index_file()
        self._lock = threading.Lock()

    # ── index I/O ─────────────────────────────────────────────────────
    def _load(self) -> list[dict]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
        except Exception:
            logger.exception("credential vault: index read failed")
        return []

    def _save(self, entries: list[dict]) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self._path)

    # ── CRUD ──────────────────────────────────────────────────────────
    def add(self, url: str, username: str, password: str,
            label: str = "", success_text: str = "") -> Optional[dict]:
        """Store a credential. Returns the metadata entry (no secret)."""
        if not url or not password:
            return None
        cred_id = uuid.uuid4().hex[:16]
        try:
            from modules.Identity.secure_store import save_secret
            if not save_secret(_PROVIDER, cred_id, {"password": password}):
                logger.error("credential vault: secure_store save failed")
                return None
        except Exception:
            logger.exception("credential vault: secure_store unavailable")
            return None
        entry = {
            "id": cred_id,
            "url": url if "://" in url else f"https://{url}",
            "host": _host(url),
            "username": username or "",
            "label": label or _host(url) or url,
            "success_text": success_text or "",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_used": "",
        }
        with self._lock:
            entries = self._load()
            entries.append(entry)
            self._save(entries)
        logger.info("credential vault: stored credentials for %s (id=%s)",
                    entry["host"] or entry["url"], cred_id)
        return dict(entry)

    def list_entries(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self._load()]

    def get(self, cred_id: str) -> Optional[dict]:
        for e in self.list_entries():
            if e.get("id") == cred_id:
                return e
        return None

    def find_for_site(self, site: str) -> Optional[dict]:
        """Best match for a spoken site name / URL / label."""
        needle = (site or "").strip().lower()
        if not needle:
            return None
        host = _host(needle)
        entries = self.list_entries()
        # 1) exact host match  2) host substring  3) label/url substring
        for e in entries:
            if host and e.get("host") == host:
                return e
        for e in entries:
            blob = f"{e.get('host','')} {e.get('url','')} {e.get('label','')}".lower()
            if needle in blob or (host and host in blob):
                return e
        return None

    def get_password(self, cred_id: str) -> str:
        try:
            from modules.Identity.secure_store import load_secret
            payload = load_secret(_PROVIDER, cred_id) or {}
            return str(payload.get("password") or "")
        except Exception:
            logger.exception("credential vault: secret load failed")
            return ""

    def touch_last_used(self, cred_id: str) -> None:
        with self._lock:
            entries = self._load()
            for e in entries:
                if e.get("id") == cred_id:
                    e["last_used"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    break
            self._save(entries)

    def delete(self, cred_id: str) -> bool:
        try:
            from modules.Identity.secure_store import delete_secret
            delete_secret(_PROVIDER, cred_id)
        except Exception:
            logger.exception("credential vault: secret delete failed")
        with self._lock:
            entries = self._load()
            kept = [e for e in entries if e.get("id") != cred_id]
            changed = len(kept) != len(entries)
            if changed:
                self._save(kept)
        return changed

    # ── legacy bookmark migration ─────────────────────────────────────
    def migrate_bookmark(self, url: str, username: str,
                         legacy_password: str, label: str = "") -> Optional[dict]:
        """Move a legacy (base64) bookmark password into the keychain."""
        import base64
        pwd = legacy_password or ""
        try:
            pwd = base64.b64decode(pwd).decode("utf-8")
        except Exception:
            pass  # already plaintext
        if not pwd:
            return None
        existing = self.find_for_site(url)
        if existing is not None:
            return existing
        return self.add(url, username, pwd, label=label)


_vault: Optional[CredentialVault] = None
_vault_lock = threading.Lock()


def get_vault() -> CredentialVault:
    global _vault
    with _vault_lock:
        if _vault is None:
            _vault = CredentialVault()
        return _vault


__all__ = ["CredentialVault", "get_vault"]
