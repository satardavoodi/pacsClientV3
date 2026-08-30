"""Regression guards for packaged EchoMind credential confidentiality.

The workstation intentionally performs company-center selection locally.  That does not
require shipping plaintext center access codes or plaintext upstream bearer credentials in
the Python sources copied into installer plugin payloads.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from modules.EchoMind import api_manager as api_manager_module
from modules.EchoMind.api_manager import APIKeyManager
from modules.EchoMind.credential_envelope import (
    CredentialEnvelope,
    CredentialEnvelopeError,
    open_provider_key,
    seal_provider_key,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TEXT_SUFFIXES = {".json", ".md", ".py", ".txt", ".toml", ".yaml", ".yml"}
PROVIDER_PATTERNS = (
    re.compile(re.escape("s" + "k-") + r"[0-9A-Za-z_-]{20,}"),
    re.compile(re.escape("AI" + "za") + r"[0-9A-Za-z_-]{20,}"),
)
ACCESS_CODE_PATTERN = re.compile(r"Ai[- ]?[Pp]acs/[A-Za-z0-9@#&*._-]{6,}")
PROTECTED_RUNTIME_PATHS = (
    "modules/EchoMind/api_manager.py",
    "modules/EchoMind/center_registry.py",
    "modules/EchoMind/credential_envelope.py",
    "modules/EchoMind/voice_transcription.py",
    "builder/plugin package/packages/echomind/payload/python/modules/EchoMind/api_manager.py",
    "builder/plugin package/packages/echomind/payload/python/modules/EchoMind/center_registry.py",
    "builder/plugin package/packages/echomind/payload/python/modules/EchoMind/credential_envelope.py",
    "builder/plugin package/packages/echomind/payload/python/modules/EchoMind/voice_transcription.py",
)


def _tracked_text_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    paths: set[Path] = set()
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        rel = Path(raw.decode("utf-8"))
        if rel.suffix.lower() in TEXT_SUFFIXES:
            paths.add(REPO_ROOT / rel)
    # New runtime files are guarded before their first commit as well as after it.
    paths.update(REPO_ROOT / rel for rel in PROTECTED_RUNTIME_PATHS)
    return sorted(path for path in paths if path.is_file())


def test_no_tracked_provider_credentials_remain_in_plaintext():
    findings: list[str] = []
    for path in _tracked_text_paths():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(text) for pattern in PROVIDER_PATTERNS):
            findings.append(path.relative_to(REPO_ROOT).as_posix())
    assert not findings, f"plaintext provider credentials remain in: {sorted(findings)}"


def test_center_access_codes_are_not_plaintext_in_packaged_registry_sources():
    paths = (
        REPO_ROOT / "modules/EchoMind/api_manager.py",
        REPO_ROOT
        / "builder/plugin package/packages/echomind/payload/python/modules/EchoMind/api_manager.py",
    )
    findings = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in paths
        if ACCESS_CODE_PATTERN.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not findings, f"plaintext center access codes remain in: {findings}"


def test_company_server_3_has_no_independent_embedded_bearer_key():
    source = (REPO_ROOT / "modules/EchoMind/voice_transcription.py").read_text(
        encoding="utf-8"
    )
    legacy_constant_present = "AIPACS_SERVER_3_KEY" in source
    assert not legacy_constant_present, "standalone Company Server 3 credential remains"


def test_access_code_opens_only_its_authenticated_provider_envelope():
    envelope = seal_provider_key(
        "center-access-code",
        "unit-provider-bearer",
        "UNIT",
        random_bytes=lambda size: bytes(range(size)),
    )
    assert open_provider_key("center-access-code", envelope, "UNIT") == (
        "unit-provider-bearer"
    )
    with pytest.raises(CredentialEnvelopeError):
        open_provider_key("another-center-code", envelope, "UNIT")


def test_tampered_provider_envelope_fails_closed():
    envelope = seal_provider_key(
        "center-access-code",
        "unit-provider-bearer",
        "UNIT",
        random_bytes=lambda size: bytes(range(size)),
    )
    tampered = CredentialEnvelope(
        lookup_digest=envelope.lookup_digest,
        kdf_salt_b64=envelope.kdf_salt_b64,
        nonce_b64=envelope.nonce_b64,
        ciphertext_b64=envelope.ciphertext_b64[:-2] + "AA",
    )
    with pytest.raises(CredentialEnvelopeError):
        open_provider_key("center-access-code", tampered, "UNIT")


def test_validation_fails_closed_without_logging_the_access_code(monkeypatch, caplog):
    manager = APIKeyManager()
    manager.reset()
    record = next(iter(api_manager_module._CENTERS_BY_CODE.values()))
    envelope = record.credentials[0]

    monkeypatch.setattr(
        api_manager_module,
        "access_code_lookup",
        lambda _access_code: envelope.lookup_digest,
    )

    def _unavailable_crypto(*_args, **_kwargs):
        raise RuntimeError("simulated crypto runtime failure")

    monkeypatch.setattr(api_manager_module, "open_provider_key", _unavailable_crypto)
    sensitive_input = "unit-access-code-must-not-be-logged"

    ok, center_code, _error = manager.validate_key(sensitive_input)

    assert not ok
    assert center_code is None
    assert manager.get_current_provider_key() is None
    assert sensitive_input not in caplog.text
