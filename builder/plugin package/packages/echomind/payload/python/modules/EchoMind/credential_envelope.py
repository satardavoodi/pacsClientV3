"""Client-side protection for EchoMind center credentials.

This module intentionally raises the cost of extracting another center's credentials from a
packaged workstation without pretending that a client-only secret is impossible to recover.
The center access code derives an AES-GCM key; only an authenticated decrypt reveals the
upstream provider credential for that center.

The GapGPT endpoint is not secret and remains ordinary configuration. Plaintext access codes
and provider bearer credentials must never be committed or copied into installer payloads.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Callable


_CONTEXT = b"aipacs-echomind-center-envelope-v1"
_LOOKUP_CONTEXT = b"aipacs-echomind-center-lookup-v1\0"
_KDF_N = 1 << 14
_KDF_R = 8
_KDF_P = 1
_KDF_LENGTH = 32
_SALT_LENGTH = 16
_NONCE_LENGTH = 12
_MAX_ACCESS_CODE_LENGTH = 512


class CredentialEnvelopeError(ValueError):
    """The supplied access code cannot open the selected credential envelope."""


@dataclass(frozen=True)
class CredentialEnvelope:
    lookup_digest: str
    kdf_salt_b64: str
    nonce_b64: str
    ciphertext_b64: str


def normalize_access_code(value: str) -> str:
    code = str(value or "").strip()
    if not code or len(code) > _MAX_ACCESS_CODE_LENGTH:
        raise CredentialEnvelopeError("Invalid EchoMind access code.")
    return code


def access_code_lookup(value: str) -> str:
    code = normalize_access_code(value)
    return hashlib.blake2s(
        _LOOKUP_CONTEXT + code.encode("utf-8"), digest_size=16
    ).hexdigest()


def _decode(value: str, *, expected_length: int | None = None) -> bytes:
    try:
        raw = base64.b64decode(str(value or ""), validate=True)
    except Exception as exc:
        raise CredentialEnvelopeError("Invalid credential envelope encoding.") from exc
    if expected_length is not None and len(raw) != expected_length:
        raise CredentialEnvelopeError("Invalid credential envelope length.")
    return raw


def _derive_key(access_code: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        normalize_access_code(access_code).encode("utf-8"),
        salt=salt,
        n=_KDF_N,
        r=_KDF_R,
        p=_KDF_P,
        dklen=_KDF_LENGTH,
    )


def _aad(center_code: str, lookup_digest: str) -> bytes:
    code = str(center_code or "").strip().upper()
    if not code:
        raise CredentialEnvelopeError("Invalid center code.")
    return _CONTEXT + b"\0" + code.encode("utf-8") + b"\0" + lookup_digest.encode("ascii")


def seal_provider_key(
    access_code: str,
    provider_key: str,
    center_code: str,
    *,
    random_bytes: Callable[[int], bytes] = os.urandom,
) -> CredentialEnvelope:
    """Create an authenticated envelope for registry generation.

    This function belongs in the offline registry-generation path. Runtime code only needs
    :func:`open_provider_key`.
    """

    provider = str(provider_key or "").strip()
    if not provider:
        raise CredentialEnvelopeError("Provider credential is empty.")
    lookup = access_code_lookup(access_code)
    salt = random_bytes(_SALT_LENGTH)
    nonce = random_bytes(_NONCE_LENGTH)
    if len(salt) != _SALT_LENGTH or len(nonce) != _NONCE_LENGTH:
        raise CredentialEnvelopeError("Credential envelope random source returned wrong length.")
    key = _derive_key(access_code, salt)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    ciphertext = AESGCM(key).encrypt(
        nonce,
        provider.encode("utf-8"),
        _aad(center_code, lookup),
    )
    return CredentialEnvelope(
        lookup_digest=lookup,
        kdf_salt_b64=base64.b64encode(salt).decode("ascii"),
        nonce_b64=base64.b64encode(nonce).decode("ascii"),
        ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
    )


def open_provider_key(
    access_code: str,
    envelope: CredentialEnvelope,
    center_code: str,
) -> str:
    """Open one center credential, failing closed on a wrong code or tampering."""

    lookup = access_code_lookup(access_code)
    if not hmac.compare_digest(lookup, str(envelope.lookup_digest or "")):
        raise CredentialEnvelopeError("Invalid EchoMind access code.")
    salt = _decode(envelope.kdf_salt_b64, expected_length=_SALT_LENGTH)
    nonce = _decode(envelope.nonce_b64, expected_length=_NONCE_LENGTH)
    ciphertext = _decode(envelope.ciphertext_b64)
    key = _derive_key(access_code, salt)
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        plaintext = AESGCM(key).decrypt(
            nonce,
            ciphertext,
            _aad(center_code, lookup),
        )
        provider = plaintext.decode("utf-8").strip()
    except (InvalidTag, UnicodeError, ValueError) as exc:
        raise CredentialEnvelopeError("Invalid EchoMind access code.") from exc
    if not provider:
        raise CredentialEnvelopeError("Credential envelope is empty.")
    return provider
