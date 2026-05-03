# AIPacs v2.4.9 Release Notes

Date: 2026-05-03
Branch: matab-conservative

## Scope

This release introduces EchoMind OpenAI direct-connection support with full
proxy-aware transport, SOCKS5 proxy integration, and complete settings wiring
for all OpenAI model/parameter UI fields.

## Included Changes

### 1. EchoMind OpenAI SOCKS5 proxy support

The OpenAI direct-connection path now routes through a SOCKS5 proxy when the
user selects "SOCKS5 Proxy" in the EchoMind connection type settings.

- `modules/EchoMind/llm_client.py`: Added `_ensure_socks_proxy_support()` guard
  that raises a clear `LLMAPIError` when PySocks is unavailable instead of an
  opaque connection failure.
- `_get_requests_proxies()` returns the correctly formatted SOCKS5 proxy dict
  used by all `requests.post/get` calls including the connection test.
- `test_openai_connection()` function added — proxy-aware, called from the
  Settings UI test button. Previously the test button bypassed the shared proxy
  path entirely.
- Plugin mirror at `builder/plugin package/packages/echomind/payload/python/
  modules/EchoMind/llm_client.py` kept SHA-equal.

### 2. PySocks dependency added across all requirement files

- `requirements.txt` — runtime dependency `PySocks>=1.7.1`
- `requirements-core.txt` — same
- `builder/requirements/build_requirements.txt` — same (build venv)
- `builder/inventory/imports_summary.json` — `"socks"` and
  `"urllib3.contrib.socks"` added to `suggested_hiddenimports` so PyInstaller
  bundles both SOCKS modules in the frozen exe.

### 3. OpenAI settings fully wired end-to-end

Verified and confirmed complete wiring from UI to API call:

- **Load path**: `_load_openai_state()` populates all model combos
  (text, report, vision, secretary, transcription), reasoning effort combo,
  temperature, max tokens, and timeout from `get_openai_settings()` on widget
  init.
- **Save path**: `_on_save_openai_clicked()` → `_openai_form_patch()` →
  `save_openai_settings()` collects and persists all field values atomically.
- **API call path**: `openai_parallel_backend._call()` and
  `openai_reporter._openai_result()` both read `temperature`, `max_output_tokens`,
  `timeout_seconds`, and `reasoning_effort` from `get_openai_settings()` on
  every call. Per-feature model is resolved via
  `get_openai_model_for_feature(feature_name)` which maps chat/text/report/
  vision/secretary/transcription to the corresponding saved model field.
- No hardcoded model strings bypass user settings for the OpenAI path.

### 4. EchoMind Settings UI test button fix

`_on_test_openai_clicked()` now calls the shared `test_openai_connection()`
from `llm_client` instead of using a private inline requests call. This ensures
the connection test and the production path use identical proxy and header logic.

## Upgrade Notes

- Existing `echomind_settings.json` in `%APPDATA%\AIPacs\config\` is preserved
  on upgrade. New fields (`reasoning_effort`, `base_url`, `organization`,
  `project`) are seeded with safe defaults if absent.
- SOCKS5 proxy is opt-in via EchoMind Settings → Connection Type. Default
  remains Direct (no proxy).
- `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1` build flag still required when building
  without the Advanced MPR payload.

## Build

- PyInstaller builder: `.venv_build\Scripts\python.exe build.py`
- Installer output: `builder/output/installer/ai-pacs installer v2.4.9.exe`
- Env flags: `AIPACS_ALLOW_MISSING_ADVANCED_MPR=1 PYTHONUTF8=1`
