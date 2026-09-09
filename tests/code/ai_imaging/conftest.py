"""Explicit synthetic provider choices for tests with injected transports."""
import pytest


@pytest.fixture
def configured_direct_eagle_models(monkeypatch):
    from modules.EchoMind import settings_store
    monkeypatch.setattr(settings_store, "get_openai_settings", lambda: {
        "eagle_eye_model": "synthetic-diagnosis-model",
        "eagle_eye_screening_model": "synthetic-screening-model",
    })
