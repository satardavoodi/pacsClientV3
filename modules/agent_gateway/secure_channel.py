"""End-to-end encryption between the workstation and a paired device (P4).

This is what makes routing agent traffic through a cloud relay acceptable for a
clinical workstation: **the relay only ever forwards opaque ciphertext**. Patient
data is sealed on the workstation and opened on the phone (and vice versa); a
compromised — or merely curious — relay operator sees routing metadata and
nothing else. It is the same construction the comparable products use (X25519 at
pairing + an AEAD per frame); see
``docs/plans/architecture/REMOTE_CONNECTIVITY_ARCHITECTURE_2026-07-17.md`` §4.

Design
------
* **Key agreement:** X25519. Each side generates a keypair; the workstation's
  public key travels inside the pairing QR, the device's comes back in the
  ``/pair`` redeem call. Neither private key ever leaves its device.
* **Key derivation:** HKDF-SHA256 over the raw shared secret, with a per-session
  ``salt`` and distinct ``info`` strings, producing **two independent 32-byte
  keys** — one per direction. Using separate keys per direction means a frame can
  never be reflected back at its sender.
* **AEAD:** ChaCha20-Poly1305 (IETF, 12-byte nonce) from ``cryptography`` — which
  is ALREADY a project dependency, so this adds no new package and no libsodium
  build step. Nonce = 4-byte random-per-session prefix ‖ 8-byte big-endian
  counter, so a nonce can never repeat within a session.
* **Replay / reorder defence:** the receiver tracks the highest counter seen and
  rejects anything at or below it. Counters are monotonic per direction and are
  NOT wall-clock based (clocks on a clinical PC and a phone drift).

Everything here is deterministic and dependency-light, so it is fully unit
tested off-screen. No Qt, no network, no global state.
"""
from __future__ import annotations

import base64
import os
import struct
import threading
from dataclasses import dataclass
from typing import Optional, Tuple

# Direction labels — also the HKDF ``info`` values, so the two directional keys
# are cryptographically independent.
DIR_WORKSTATION_TO_DEVICE = b"aipacs-agent/ws->dev"
DIR_DEVICE_TO_WORKSTATION = b"aipacs-agent/dev->ws"

_KEY_LEN = 32
_NONCE_LEN = 12
_PREFIX_LEN = 4
_COUNTER_LEN = 8


class SecureChannelError(Exception):
    """Raised on a failed open (bad key, tampering, or a replayed frame)."""


# ── encoding helpers (base64url, no padding — QR/JSON friendly) ──────────────
def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64d(text: str) -> bytes:
    s = (text or "").strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ── key agreement ────────────────────────────────────────────────────────────
def generate_keypair() -> Tuple[bytes, bytes]:
    """Return ``(private_raw, public_raw)`` for a fresh X25519 keypair."""
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )

    priv = X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return priv_raw, pub_raw


def new_salt() -> bytes:
    """Per-pairing salt mixed into HKDF (16 bytes)."""
    return os.urandom(16)


def derive_keys(
    private_raw: bytes,
    peer_public_raw: bytes,
    salt: bytes,
) -> Tuple[bytes, bytes]:
    """X25519 + HKDF → ``(ws_to_dev_key, dev_to_ws_key)``.

    Both sides call this with their own private key and the peer's public key and
    obtain the SAME pair of keys; which one you send with depends on your role.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.x25519 import (
        X25519PrivateKey, X25519PublicKey,
    )
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    priv = X25519PrivateKey.from_private_bytes(private_raw)
    peer = X25519PublicKey.from_public_bytes(peer_public_raw)
    shared = priv.exchange(peer)

    def _hkdf(info: bytes) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(), length=_KEY_LEN, salt=salt, info=info
        ).derive(shared)

    return _hkdf(DIR_WORKSTATION_TO_DEVICE), _hkdf(DIR_DEVICE_TO_WORKSTATION)


# ── the channel ──────────────────────────────────────────────────────────────
@dataclass
class SealedFrame:
    """What actually crosses the relay. ``ct`` is opaque to everyone but the peer."""

    nonce: str      # base64url of the 12-byte nonce
    ct: str         # base64url ciphertext+tag
    counter: int    # plaintext counter, for relay-side ordering/debug only

    def to_dict(self) -> dict:
        return {"nonce": self.nonce, "ct": self.ct, "counter": self.counter}

    @classmethod
    def from_dict(cls, d: dict) -> "SealedFrame":
        return cls(
            nonce=str((d or {}).get("nonce") or ""),
            ct=str((d or {}).get("ct") or ""),
            counter=int((d or {}).get("counter") or 0),
        )


class SecureChannel:
    """Seals outgoing frames and opens incoming ones for ONE paired peer.

    ``role`` selects which derived key is used for sending vs receiving:
    ``"workstation"`` sends with the ws→dev key and receives with dev→ws;
    ``"device"`` is the mirror image.
    """

    def __init__(
        self,
        send_key: bytes,
        recv_key: bytes,
        *,
        send_prefix: Optional[bytes] = None,
    ) -> None:
        if len(send_key) != _KEY_LEN or len(recv_key) != _KEY_LEN:
            raise ValueError("keys must be 32 bytes")
        self._send_key = send_key
        self._recv_key = recv_key
        self._send_prefix = send_prefix or os.urandom(_PREFIX_LEN)
        self._send_counter = 0
        self._highest_recv_counter = -1
        # A channel is SESSION STATE (nonce counter + replay high-water mark), so
        # it must live as long as the pairing and be shared by every worker
        # thread. Rebuilding it per request would restart the counter at 1 and
        # the peer would (correctly) reject the second frame as a replay.
        self._lock = threading.RLock()

    @property
    def lock(self) -> "threading.RLock":
        """Hold this across *seal → send* so counter order == wire order.

        Both directions ride one WebSocket, and TCP preserves order, so sealing
        and sending atomically is what lets the receiver enforce strict
        monotonic counters even with a multi-threaded dispatcher.
        """
        return self._lock

    # ── construction from a completed handshake ──────────────────────
    @classmethod
    def for_role(
        cls,
        role: str,
        private_raw: bytes,
        peer_public_raw: bytes,
        salt: bytes,
    ) -> "SecureChannel":
        ws_to_dev, dev_to_ws = derive_keys(private_raw, peer_public_raw, salt)
        if str(role).strip().lower() == "workstation":
            return cls(send_key=ws_to_dev, recv_key=dev_to_ws)
        return cls(send_key=dev_to_ws, recv_key=ws_to_dev)

    # ── seal / open ──────────────────────────────────────────────────
    def seal(self, plaintext: bytes, aad: Optional[bytes] = None) -> SealedFrame:
        """Encrypt one frame. Nonce is prefix‖counter, so it never repeats."""
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        with self._lock:
            self._send_counter += 1
            counter = self._send_counter
        nonce = self._send_prefix + struct.pack(">Q", counter)
        ct = ChaCha20Poly1305(self._send_key).encrypt(nonce, plaintext, aad)
        return SealedFrame(nonce=b64e(nonce), ct=b64e(ct), counter=counter)

    def open(self, frame, aad: Optional[bytes] = None) -> bytes:
        """Decrypt + authenticate one frame, rejecting replays.

        Raises :class:`SecureChannelError` on tampering, a wrong key, or a
        counter we have already accepted (replay / reorder).
        """
        from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

        if isinstance(frame, dict):
            frame = SealedFrame.from_dict(frame)
        try:
            nonce = b64d(frame.nonce)
            ct = b64d(frame.ct)
        except Exception as exc:  # noqa: BLE001
            raise SecureChannelError(f"malformed frame: {exc}") from exc
        if len(nonce) != _NONCE_LEN:
            raise SecureChannelError("bad nonce length")

        counter = struct.unpack(">Q", nonce[_PREFIX_LEN:])[0]
        with self._lock:
            if counter <= self._highest_recv_counter:
                raise SecureChannelError(
                    f"replayed or out-of-order frame (counter={counter}, "
                    f"highest={self._highest_recv_counter})"
                )
            try:
                pt = ChaCha20Poly1305(self._recv_key).decrypt(nonce, ct, aad)
            except Exception as exc:  # noqa: BLE001
                raise SecureChannelError(
                    "decryption failed (bad key or tampered)"
                ) from exc
            # Only advance AFTER successful authentication, so a forged frame
            # with a high counter cannot wedge the channel.
            self._highest_recv_counter = counter
            return pt

    # ── introspection (tests / diagnostics; never logs key material) ──
    @property
    def send_counter(self) -> int:
        return self._send_counter

    @property
    def highest_recv_counter(self) -> int:
        return self._highest_recv_counter


__all__ = [
    "SecureChannel",
    "SealedFrame",
    "SecureChannelError",
    "generate_keypair",
    "derive_keys",
    "new_salt",
    "b64e",
    "b64d",
    "DIR_WORKSTATION_TO_DEVICE",
    "DIR_DEVICE_TO_WORKSTATION",
]
