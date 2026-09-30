"""Request-local configuration for the headless workstation core."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import json
import os

_settings = ContextVar("echomind_settings", default=None)
_references = ContextVar("echomind_template_references", default=None)
_company = ContextVar("echomind_company", default=None)
_directory = ContextVar("echomind_private_directory", default=None)


def private_dir():
    if _directory.get() is not None:
        return _directory.get()
    return Path(os.environ.get("ECHOMIND_CONFIG_DIR", Path(__file__).resolve().parents[2] / "data" / "echomind"))


@contextmanager
def configuration(directory):
    token = _directory.set(Path(directory))
    try:
        yield
    finally:
        _directory.reset(token)


def server_settings():
    path = private_dir() / "settings.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def current_settings():
    value = _settings.get()
    if value is None:
        raise RuntimeError("EchoMind requires a request context")
    return value


def template_references():
    value = _references.get()
    if value is None:
        raise RuntimeError("EchoMind requires a request context")
    return value


def company_identity():
    cached = _company.get()
    if cached is not None:
        return cached
    from .core.credential_envelope import access_code_lookup, open_provider_key, CredentialEnvelope
    code = str(current_settings().get("api_key") or "")
    lookup = access_code_lookup(code)
    path = private_dir() / "centers.json"
    records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    for record in records:
        for envelope in record.get("credentials", []):
            if envelope.get("lookup_digest") == lookup:
                key = open_provider_key(code, CredentialEnvelope(**envelope), record["center_code"])
                value = (record.get("center_display") or record["center_code"], key)
                _company.set(value)
                return value
    raise ValueError("Invalid EchoMind center access code")


@contextmanager
def request_context(overrides=None, *, base=None):
    config = dict(server_settings() if base is None else base)
    config.update(overrides or {})
    tokens = (_settings.set(config), _references.set({}), _company.set(None))
    try:
        yield config
    finally:
        _company.reset(tokens[2])
        _references.reset(tokens[1])
        _settings.reset(tokens[0])
