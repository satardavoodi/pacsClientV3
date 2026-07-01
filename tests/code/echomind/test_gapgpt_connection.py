"""
test_gapgpt_connection.py
=========================
Live and structural tests for the EchoMind / GapGPT backend connection.

Tests are split into two classes:

  TestGapGptConfigConstants   — pure source-pin / constant checks (always run)
  TestGapGptLiveConnection    — real HTTP calls (run in sandbox & CI where
                                internet is available; skipped otherwise)
  TestAiBackendLiveConnection — real HTTP calls to the local AI backend
                                (port 8085); skipped when unreachable

Run:
  python -m pytest tests/code/echomind/test_gapgpt_connection.py -p no:debugging -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_ROOT = os.path.normpath(os.path.join(_HERE, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ---------------------------------------------------------------------------
# Constants extracted directly from source (no PySide6 chain needed)
# ---------------------------------------------------------------------------
import importlib.util, types

_CFG_PATH = os.path.join(_ROOT, "modules", "EchoMind", "ai_chat_config.py")
_MGR_PATH = os.path.join(_ROOT, "modules", "EchoMind", "api_manager.py")

def _read_src(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()

_CFG_SRC = _read_src(_CFG_PATH)
_MGR_SRC = _read_src(_MGR_PATH)

def _load_module_stub(path: str, modname: str):
    """Exec a module with PySide6/Qt stubs — returns the module object."""
    for name in ("PySide6", "PySide6.QtCore", "PySide6.QtWidgets", "PySide6.QtGui"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    # Stub QObject / Signal so the PySide6 import in api_manager.py doesn't crash
    qt_core = sys.modules["PySide6.QtCore"]
    if not hasattr(qt_core, "QObject"):
        class _QObject:
            def __init__(self, *a, **kw): pass
        class _Signal:
            def __init__(self, *a, **kw): pass
            def emit(self, *a): pass
            def connect(self, *a): pass
        qt_core.QObject = _QObject
        qt_core.Signal = _Signal
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod  # required: dataclasses looks up cls.__module__ in sys.modules
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    return mod

_CFG_MOD = _load_module_stub(_CFG_PATH, "_aichat_cfg_test")
_MGR_MOD = _load_module_stub(_MGR_PATH, "_api_mgr_test")

GAPGPT_API_URL    = getattr(_CFG_MOD, "GAPGPT_API_URL",    None)
GAPGPT_MODEL      = getattr(_CFG_MOD, "GAPGPT_DEFAULT_MODEL", None)
GAPGPT_TIMEOUT    = getattr(_CFG_MOD, "GAPGPT_TIMEOUT",    None)
AI_BASE           = getattr(_CFG_MOD, "AI_BASE",            None)
URL_HEALTH        = getattr(_CFG_MOD, "URL_HEALTH",         None)
URL_STATUS        = getattr(_CFG_MOD, "URL_STATUS",         None)
CENTERS           = getattr(_MGR_MOD,  "CENTERS",           None)

# ---------------------------------------------------------------------------
# Network availability probes (run once at import time)
# ---------------------------------------------------------------------------
def _probe_url(url: str, *, method: str = "GET", timeout: int = 5) -> bool:
    try:
        import requests
        fn = requests.get if method == "GET" else requests.head
        r = fn(url, timeout=timeout)
        return r.status_code < 500
    except Exception:
        return False

_GAPGPT_REACHABLE    = _probe_url("https://api.gapgpt.app", timeout=6)
_AI_BACKEND_REACHABLE = _probe_url(URL_HEALTH or "http://80.210.31.214:8085/health", timeout=4)


# ===========================================================================
# 1. Config constants — always run (no network needed)
# ===========================================================================

class TestGapGptConfigConstants(unittest.TestCase):
    """Verify that all config constants are present and sane."""

    def test_gapgpt_api_url_constant_present(self):
        self.assertIsNotNone(GAPGPT_API_URL, "GAPGPT_API_URL missing from ai_chat_config.py")

    def test_gapgpt_api_url_is_https(self):
        self.assertTrue(
            (GAPGPT_API_URL or "").startswith("https://"),
            f"GAPGPT_API_URL must be HTTPS, got: {GAPGPT_API_URL!r}",
        )

    def test_gapgpt_api_url_contains_chat_completions(self):
        self.assertIn("chat/completions", GAPGPT_API_URL or "")

    def test_gapgpt_default_model_present(self):
        self.assertIsNotNone(GAPGPT_MODEL, "GAPGPT_DEFAULT_MODEL missing")
        self.assertTrue(len(GAPGPT_MODEL or "") > 0)

    def test_gapgpt_timeout_positive(self):
        self.assertIsNotNone(GAPGPT_TIMEOUT, "GAPGPT_TIMEOUT missing")
        self.assertGreater(int(GAPGPT_TIMEOUT), 0)

    def test_ai_base_url_present(self):
        self.assertIsNotNone(AI_BASE, "AI_BASE missing from ai_chat_config.py")
        self.assertTrue((AI_BASE or "").startswith("http"))

    def test_health_url_derived_from_base(self):
        self.assertIsNotNone(URL_HEALTH)
        self.assertIn(AI_BASE or "", URL_HEALTH or "")

    def test_status_url_derived_from_base(self):
        self.assertIsNotNone(URL_STATUS)
        self.assertIn(AI_BASE or "", URL_STATUS or "")


# ===========================================================================
# 2. Center key registry — always run
# ===========================================================================

class TestCenterKeyRegistry(unittest.TestCase):
    """Verify the CENTERS registry in api_manager.py is well-formed."""

    def test_centers_list_not_empty(self):
        self.assertIsNotNone(CENTERS)
        self.assertGreater(len(CENTERS), 0, "CENTERS registry is empty")

    def test_every_center_has_gapgpt_key(self):
        for c in (CENTERS or []):
            self.assertTrue(
                (c.gapgpt_key or "").strip(),
                f"Center {c.center_code!r} has no gapgpt_key",
            )

    def test_every_center_has_irannobat_key(self):
        for c in (CENTERS or []):
            self.assertTrue(
                c.irannobat_keys and any(k.strip() for k in c.irannobat_keys),
                f"Center {c.center_code!r} has no irannobat_keys",
            )

    def test_gapgpt_keys_start_with_sk(self):
        for c in (CENTERS or []):
            self.assertTrue(
                c.gapgpt_key.startswith("sk-"),
                f"Center {c.center_code!r} gapgpt_key doesn't start with 'sk-'",
            )

    def test_no_duplicate_gapgpt_keys(self):
        keys = [c.gapgpt_key for c in (CENTERS or [])]
        self.assertEqual(len(keys), len(set(keys)), "Duplicate gapgpt_key values in CENTERS")

    def test_no_duplicate_irannobat_keys(self):
        all_keys: list[str] = []
        for c in (CENTERS or []):
            all_keys.extend(c.irannobat_keys or [])
        self.assertEqual(len(all_keys), len(set(all_keys)), "Duplicate irannobat_keys across centers")

    def test_center_codes_are_uppercase(self):
        for c in (CENTERS or []):
            self.assertEqual(
                c.center_code, c.center_code.upper(),
                f"center_code {c.center_code!r} should be uppercase",
            )

    def test_known_centers_present(self):
        """Guard that the expected centers haven't been accidentally removed."""
        codes = {c.center_code for c in (CENTERS or [])}
        for expected in ("RAZI", "IMA", "ROOHANI", "HASANPOUR", "ASSARZADEGAN", "BRAKE", "FAZEL"):
            self.assertIn(expected, codes, f"Center {expected!r} missing from registry")


# ===========================================================================
# 3. LLM client source-pin — always run
# ===========================================================================

class TestLlmClientSourcePin(unittest.TestCase):
    """Verify llm_client.py imports the right constants and exposes the right API."""

    _LLM_PATH = os.path.join(_ROOT, "modules", "EchoMind", "llm_client.py")

    @classmethod
    def setUpClass(cls):
        with open(cls._LLM_PATH, encoding="utf-8") as f:
            cls._src = f.read()

    def test_gapgpt_api_url_imported(self):
        self.assertIn("GAPGPT_API_URL", self._src)

    def test_chat_completion_function_present(self):
        self.assertIn("def chat_completion(", self._src)

    def test_gapgpt_chat_function_present(self):
        self.assertIn("def gapgpt_chat(", self._src)

    def test_test_active_backend_connection_function_present(self):
        self.assertIn("def test_active_backend_connection(", self._src)

    def test_auth_error_class_present(self):
        self.assertIn("class LLMAuthError", self._src)

    def test_no_key_error_class_present(self):
        self.assertIn("class LLMNoKeyError", self._src)

    def test_bearer_auth_header_used(self):
        self.assertIn("Bearer", self._src)

    def test_socks5_proxy_support_present(self):
        self.assertIn("socks5", self._src)

    def test_trim_incomplete_sentence_present(self):
        self.assertIn("_trim_incomplete_sentence", self._src)


# ===========================================================================
# 4. Live GapGPT connection — skipped when unreachable
# ===========================================================================

@unittest.skipUnless(_GAPGPT_REACHABLE, "GapGPT API not reachable from this environment")
class TestGapGptLiveConnection(unittest.TestCase):
    """Real HTTP calls to https://api.gapgpt.app/v1/chat/completions."""

    _URL   = "https://api.gapgpt.app/v1/chat/completions"
    _MODEL = "gpt-5.2"
    # Use the RAZI key for the generic ping test
    _KEY   = "sk-97OrEW0kPBVNqMsH0JOBIOHvCHAo3RsZKxpaEABzheRp42M0"

    def _post(self, key: str, content: str = "Reply: OK", max_tokens: int = 8) -> dict:
        import requests
        resp = requests.post(
            self._URL,
            json={
                "model": self._MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": max_tokens,
                "temperature": 0.0,
            },
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            timeout=20,
        )
        return resp

    def test_razi_key_returns_200(self):
        resp = self._post(self._KEY)
        self.assertEqual(resp.status_code, 200, f"Unexpected HTTP {resp.status_code}: {resp.text[:200]}")

    def test_response_is_valid_json(self):
        resp = self._post(self._KEY)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, dict)

    def test_response_has_choices(self):
        resp = self._post(self._KEY)
        body = resp.json()
        self.assertIn("choices", body)
        self.assertGreater(len(body["choices"]), 0)

    def test_response_content_is_string(self):
        resp = self._post(self._KEY)
        content = resp.json()["choices"][0]["message"]["content"]
        self.assertIsInstance(content, str)
        self.assertGreater(len(content.strip()), 0)

    def test_response_model_matches(self):
        resp = self._post(self._KEY)
        reported_model = resp.json().get("model", "")
        self.assertEqual(reported_model, self._MODEL,
                         f"Server returned model={reported_model!r}, expected {self._MODEL!r}")

    def test_response_has_usage_tokens(self):
        resp = self._post(self._KEY)
        usage = resp.json().get("usage", {})
        self.assertIn("prompt_tokens", usage)
        self.assertIn("completion_tokens", usage)
        self.assertGreater(int(usage.get("total_tokens", 0)), 0)

    def test_finish_reason_is_stop(self):
        resp = self._post(self._KEY)
        reason = resp.json()["choices"][0].get("finish_reason")
        self.assertEqual(reason, "stop",
                         f"Expected finish_reason='stop', got {reason!r}")

    def test_invalid_key_returns_401_or_403(self):
        import requests
        resp = requests.post(
            self._URL,
            json={"model": self._MODEL, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4},
            headers={"Authorization": "Bearer sk-INVALID_KEY_00000000000000000000000000000000000"},
            timeout=10,
        )
        self.assertIn(resp.status_code, (401, 403),
                      f"Expected 401/403 for bad key, got {resp.status_code}")

    def test_all_center_keys_authenticate(self):
        """Every registered gapgpt_key must return HTTP 200."""
        import requests
        failures = []
        for c in (CENTERS or []):
            resp = requests.post(
                self._URL,
                json={"model": self._MODEL,
                      "messages": [{"role": "user", "content": "OK"}],
                      "max_tokens": 4, "temperature": 0.0},
                headers={"Authorization": f"Bearer {c.gapgpt_key}",
                         "Content-Type": "application/json"},
                timeout=20,
            )
            if resp.status_code != 200:
                failures.append(f"{c.center_code}: HTTP {resp.status_code}")
        self.assertFalse(failures,
                         "The following center keys failed:\n" + "\n".join(failures))


# ===========================================================================
# 5. Live AI backend (port 8085) — skipped when unreachable
# ===========================================================================

@unittest.skipUnless(_AI_BACKEND_REACHABLE, "AI backend (port 8085) not reachable")
class TestAiBackendLiveConnection(unittest.TestCase):
    """Real HTTP calls to the local AI backend server."""

    _BASE   = "http://80.210.31.214:8085"
    _HEALTH = f"{_BASE}/health"
    _STATUS = f"{_BASE}/status"

    def test_health_endpoint_returns_200(self):
        import requests
        resp = requests.get(self._HEALTH, timeout=6)
        self.assertEqual(resp.status_code, 200)

    def test_health_response_has_status_field(self):
        import requests
        body = requests.get(self._HEALTH, timeout=6).json()
        self.assertIn("status", body)

    def test_health_reports_loaded_gpus(self):
        import requests
        body = requests.get(self._HEALTH, timeout=6).json()
        self.assertIn("loaded_gpus", body)
        self.assertIsInstance(body["loaded_gpus"], list)

    def test_status_endpoint_returns_200(self):
        import requests
        resp = requests.get(self._STATUS, timeout=6)
        self.assertEqual(resp.status_code, 200)

    def test_status_response_has_ok_status(self):
        import requests
        body = requests.get(self._STATUS, timeout=6).json()
        self.assertEqual(body.get("status"), "ok",
                         f"Backend status is not 'ok': {body.get('status')!r}")

    def test_status_reports_active_sessions(self):
        import requests
        body = requests.get(self._STATUS, timeout=6).json()
        self.assertIn("active_sessions", body)
        self.assertGreaterEqual(int(body["active_sessions"]), 0)

    def test_gpu_utilization_present(self):
        import requests
        body = requests.get(self._STATUS, timeout=6).json()
        self.assertIn("gpu_utilization", body)
        gpu_info = body["gpu_utilization"]
        self.assertIsInstance(gpu_info, dict)
