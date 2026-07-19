"""Paired-device registry — persistent, hashed, revocable.

Stores one record per paired device at ``<gateway data dir>/devices.json``:

    {
      "device_id": "dev_ab12..",
      "name": "Vahid's Pixel",
      "token_sha256": "<sha256 of the bearer token>",   # never the raw token
      "mode": "full" | "assistant" | "read_only",
      "created": <epoch>,
      "last_seen": <epoch>,
      "revoked": false
    }

Only the token *hash* is kept, so a leaked ``devices.json`` cannot be replayed.
Authentication is a hash lookup; revocation flips ``revoked`` (kept for the
audit trail) — the Settings tab can also hard-delete. The path is injectable so
the offscreen tests never touch the real profile.

Pure stdlib; thread-safe via a module-level lock (the HTTP server runs on a
background thread, so ``/pair`` writes and ``/mcp`` reads can race).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import pairing
from .config_store import normalize_device_mode

_LOCK = threading.RLock()


def _default_path() -> Path:
    from .config_store import gateway_data_dir

    return gateway_data_dir() / "devices.json"


class DeviceStore:
    """JSON-backed registry of paired devices (hashed tokens)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else _default_path()

    # ── persistence ───────────────────────────────────────────────────
    def _read(self) -> List[Dict[str, Any]]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
        return []

    def _write(self, rows: List[Dict[str, Any]]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self._path)

    # ── operations ────────────────────────────────────────────────────
    def add_device(
        self,
        name: str,
        token: str,
        mode: str,
        device_pubkey: str = "",
        key_salt: str = "",
    ) -> Dict[str, Any]:
        """Register a freshly paired device; returns the (public) record.

        The raw ``token`` is hashed here and then discarded — the caller must
        have already returned it to the device. ``device_pubkey``/``key_salt``
        are the E2E material (X25519 public key + HKDF salt) needed to rebuild
        this device's :class:`SecureChannel` after a restart; they are PUBLIC
        values, so storing them is safe (the private key never leaves the box).
        """
        record = {
            "device_id": pairing.new_device_id(),
            "name": (name or "device").strip()[:80] or "device",
            "token_sha256": pairing.hash_token(token),
            "mode": normalize_device_mode(mode),
            "created": int(time.time()),
            "last_seen": 0,
            "revoked": False,
            "device_pubkey": device_pubkey or "",
            "key_salt": key_salt or "",
        }
        with _LOCK:
            rows = self._read()
            rows.append(record)
            self._write(rows)
        return {k: v for k, v in record.items() if k != "token_sha256"}

    def authenticate(self, token: str) -> Optional[Dict[str, Any]]:
        """Return the active device record for ``token`` or ``None``.

        Touches ``last_seen`` on success. Revoked devices never authenticate.
        """
        if not token:
            return None
        target = pairing.hash_token(token)
        with _LOCK:
            rows = self._read()
            changed = False
            for r in rows:
                if r.get("revoked"):
                    continue
                if r.get("token_sha256") == target:
                    r["last_seen"] = int(time.time())
                    changed = True
                    if changed:
                        self._write(rows)
                    return {k: v for k, v in r.items() if k != "token_sha256"}
        return None

    def list_devices(self) -> List[Dict[str, Any]]:
        with _LOCK:
            rows = self._read()
        return [{k: v for k, v in r.items() if k != "token_sha256"} for r in rows]

    def channel_material(self, device_id: str) -> Optional[Dict[str, str]]:
        """``{device_pubkey, key_salt}`` for an active device, else ``None``.

        Used to rebuild the end-to-end :class:`SecureChannel` for a device —
        including after a workstation restart, so a paired phone keeps working
        without re-pairing.
        """
        with _LOCK:
            for r in self._read():
                if r.get("device_id") == device_id and not r.get("revoked"):
                    pub = str(r.get("device_pubkey") or "")
                    salt = str(r.get("key_salt") or "")
                    return {"device_pubkey": pub, "key_salt": salt} if pub and salt else None
        return None

    def set_mode(self, device_id: str, mode: str) -> bool:
        with _LOCK:
            rows = self._read()
            hit = False
            for r in rows:
                if r.get("device_id") == device_id:
                    r["mode"] = normalize_device_mode(mode)
                    hit = True
            if hit:
                self._write(rows)
            return hit

    def revoke(self, device_id: str) -> bool:
        with _LOCK:
            rows = self._read()
            hit = False
            for r in rows:
                if r.get("device_id") == device_id:
                    r["revoked"] = True
                    hit = True
            if hit:
                self._write(rows)
            return hit

    def remove(self, device_id: str) -> bool:
        with _LOCK:
            rows = self._read()
            new_rows = [r for r in rows if r.get("device_id") != device_id]
            if len(new_rows) != len(rows):
                self._write(new_rows)
                return True
            return False

    def clear(self) -> None:
        with _LOCK:
            self._write([])


__all__ = ["DeviceStore"]
