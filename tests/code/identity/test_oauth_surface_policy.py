"""OAuth-surface policy guard (owner directive 2026-06-12, pipeline doc §11.6).

The owner wants the Google sign-in / consent to open inside the embedded Web
Browser module (docked QtWebEngine tab) by DEFAULT; the system browser is the
fallback + kill-switch. The earlier 0x8001010d COM crash is prevented by
crash-hardening (queued open + clean-turn navigate + generation guard), not by
disabling the embedded path. These tests pin the policy so it cannot silently
regress:

* the embedded surface is the DEFAULT for ``run_installed_app_flow`` when it is
  usable (no flag set);
* the KILL-SWITCH (env ``AIPACS_OAUTH_EMBEDDED=0``/off/false/no, OR config
  ``oauth_embedded: false`` — env wins) forces the system browser;
* embedded NOT usable (headless/CLI/module off) → system browser;
* an explicit caller-supplied ``open_url_cb`` is always honoured (it is the
  caller's own surface choice, not the auto-selection);
* the consent URL is opened EXACTLY ONCE per flow (no double-open).

All of Google's network/loopback machinery is mocked — these are Qt-free unit
tests.
"""

import pytest

from modules.Identity.providers.google import oauth_flow


@pytest.fixture
def spy(monkeypatch):
    """Record which surface ``run_installed_app_flow`` chose, and how many times
    the consent URL was opened, without touching Google/Qt/network."""
    state = {"embedded_calls": 0, "system_calls": 0, "opens": []}

    # Embedded path: count it, return a sentinel; record each URL open via the
    # caller-supplied opener when present.
    def _fake_embedded(client_config, scopes, *, auth_url_kwargs=None, open_url=None):
        state["embedded_calls"] += 1
        # Emulate the real flow opening the consent URL exactly once.
        (open_url or (lambda u: state["opens"].append(u)))(
            "https://accounts.google.com/o/oauth2/auth?fake=1"
        )
        return object()

    monkeypatch.setattr(oauth_flow, "_run_flow_embedded", _fake_embedded)

    # System path: stub InstalledAppFlow so no real browser/loopback happens.
    class _FakeFlow:
        credentials = object()

        @classmethod
        def from_client_config(cls, client_config, scopes=None):
            return cls()

        def run_local_server(self, **kwargs):
            state["system_calls"] += 1
            state["system_kwargs"] = kwargs
            return self.credentials

    import google_auth_oauthlib.flow as gflow

    monkeypatch.setattr(gflow, "InstalledAppFlow", _FakeFlow)
    return state


@pytest.fixture(autouse=True)
def _no_config_killswitch(monkeypatch):
    """Default the config kill-switch to ABSENT so tests assert the env/usable
    policy in isolation. Tests that exercise the config kill-switch override
    this explicitly."""
    monkeypatch.setattr(oauth_flow, "_config_oauth_embedded", lambda: None)


def test_default_surface_is_embedded_when_usable(spy, monkeypatch):
    # Embedded is usable and NO flag set → embedded is the DEFAULT surface.
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.delenv("AIPACS_OAUTH_EMBEDDED", raising=False)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["embedded_calls"] == 1, "embedded surface not used by default"
    assert spy["system_calls"] == 0, "system browser used despite embedded default"


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "disabled"])
def test_env_kill_switch_forces_system(spy, monkeypatch, value):
    # Embedded "usable" but the env kill-switch forces the system browser.
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.setenv("AIPACS_OAUTH_EMBEDDED", value)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["embedded_calls"] == 0
    assert spy["system_calls"] == 1


@pytest.mark.parametrize("value", ["1", "true", "on", "yes", "enabled"])
def test_env_truthy_keeps_embedded_default(spy, monkeypatch, value):
    # Explicit truthy env re-asserts embedded (and overrides any config off).
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.setattr(oauth_flow, "_config_oauth_embedded", lambda: False)
    monkeypatch.setenv("AIPACS_OAUTH_EMBEDDED", value)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["embedded_calls"] == 1, "env truthy did not override config kill-switch"
    assert spy["system_calls"] == 0


def test_config_kill_switch_forces_system(spy, monkeypatch):
    # No env directive; config oauth_embedded:false forces the system browser.
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.setattr(oauth_flow, "_config_oauth_embedded", lambda: False)
    monkeypatch.delenv("AIPACS_OAUTH_EMBEDDED", raising=False)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["embedded_calls"] == 0
    assert spy["system_calls"] == 1


def test_config_embedded_true_keeps_embedded(spy, monkeypatch):
    # config oauth_embedded:true is not a kill-switch → embedded default.
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.setattr(oauth_flow, "_config_oauth_embedded", lambda: True)
    monkeypatch.delenv("AIPACS_OAUTH_EMBEDDED", raising=False)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["embedded_calls"] == 1
    assert spy["system_calls"] == 0


def test_not_usable_falls_back_to_system(spy, monkeypatch):
    # Embedded not usable (headless/CLI/module off) → system browser.
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: False)
    monkeypatch.delenv("AIPACS_OAUTH_EMBEDDED", raising=False)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["embedded_calls"] == 0
    assert spy["system_calls"] == 1


def test_embedded_failure_falls_back_to_system(spy, monkeypatch):
    # Embedded is the default + usable, but the embedded path raises a
    # Python-level error → automatic system-browser fallback.
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.delenv("AIPACS_OAUTH_EMBEDDED", raising=False)

    def _boom(*a, **k):
        raise RuntimeError("embedded blew up")

    monkeypatch.setattr(oauth_flow, "_run_flow_embedded", _boom)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["system_calls"] == 1, "no system-browser fallback after embedded failure"


def test_explicit_open_url_cb_is_always_honoured(spy, monkeypatch):
    # Even with the kill-switch ON, an explicit opener wins (the caller is
    # choosing the surface deliberately).
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.setenv("AIPACS_OAUTH_EMBEDDED", "0")
    opened = []

    oauth_flow.run_installed_app_flow(
        {"installed": {"client_id": "x"}},
        open_url_cb=lambda u: opened.append(u),
    )

    assert spy["embedded_calls"] == 1
    assert spy["system_calls"] == 0
    # The consent URL was opened EXACTLY once, through the supplied opener.
    assert len(opened) == 1


def test_consent_url_opened_exactly_once_in_embedded_path(spy, monkeypatch):
    """The embedded path must open the consent URL exactly once (no double-open
    — the open/reset/open race that preceded the 0x8001010d crash)."""
    monkeypatch.setattr(oauth_flow, "_embedded_browser_usable", lambda: True)
    monkeypatch.delenv("AIPACS_OAUTH_EMBEDDED", raising=False)

    oauth_flow.run_installed_app_flow({"installed": {"client_id": "x"}})

    assert spy["embedded_calls"] == 1
    assert len(spy["opens"]) == 1
