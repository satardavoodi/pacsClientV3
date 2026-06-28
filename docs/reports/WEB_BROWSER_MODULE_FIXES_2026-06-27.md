# Web Browser module — startup, agent control, autofill, context menu (2026-06-27)

**Scope:** `modules/web_browser/*`, `modules/EchoMind/secretary/*` (browser adapter, validator,
permissions), `main.py`, and the home-panel launch path. All changes are **flag-gated default-on
with a legacy kill switch**, mirrored to the plugin payloads, and offscreen-verified. Items needing
the **Windows source build** for final sign-off are listed in §6.

## 1. Startup lag (~20 s) — root cause + fix

**Root cause.** The whole Chromium engine boots **synchronously on the GUI thread** the first time
`WebBrowserWidget` is constructed (lazy, on first open): importing `widget.py` loads the big
QtWebEngine DLLs, `setup_ui()` builds the first `QWebEngineView()` (cold Chromium init +
`QtWebEngineProcess.exe` spawn), and `setup_profile()` immediately loads the home page. Compounding
it, `main.py` never set `Qt.AA_ShareOpenGLContexts` (the documented QtWebEngine requirement), forcing
slow GL fallback paths. The page load itself is async — the first-init is the blocker.

**Fix.**
- `main.py`: set `Qt.AA_ShareOpenGLContexts` **before** `QApplication` (kill switch
  `AIPACS_WEBENGINE_SHARE_GL=0`).
- `modules/web_browser/__init__.py`: `WebBrowserWidget` is now a **lazy** PEP-562 export — importing
  the package no longer pulls QtWebEngine, so the engine loads only on real use.
- `modules/web_browser/prewarm.py` (NEW): **adaptive idle pre-warm**. In sessions *after* the user
  has opened the browser before (marker file), it warms QtWebEngine **at idle on a background
  thread** (DLL load off the GUI thread; a throwaway hidden view constructed at idle), so the next
  open is near-instant. A workstation that never uses the browser never loads Chromium. Hooks:
  `mark_browser_used()` on open (`_hp_modules.open_web_browser`), `schedule_prewarm()` from the home
  panel. Kill switch `AIPACS_BROWSER_PREWARM=0`.

First-ever open still pays a one-time engine boot (Qt requires widget construction on the GUI
thread) — but it no longer freezes from the GL fallback, and every subsequent session is fast.

## 2. Secretary e Command ↔ browser control tools (MCP-like)

The CommandBus → `BrowserCommandAdapter` → `WebBrowserWidget` spine already existed (navigate /
search / back / forward / reload). Added the full structured surface so the agent can **read,
inspect, and drive** the page through tools, not synthetic input:

`browser_get_url`, `browser_get_text`, `browser_get_html`, `browser_dom_summary`,
`browser_find_element`, `browser_fill_field`, `browser_click`, `browser_submit_form`,
`browser_selected_text`, `browser_extract_table`, `browser_get_links`, `browser_screenshot`,
`browser_navigate`, `browser_go_back/go_forward/reload`.

- Page reads run sandboxed JS (`modules/web_browser/page_tools.py`, pure/Qt-free) via a **bounded
  synchronous helper** (`_run_js_sync`, hard timeout) so a tool can never hang the bus/UI.
- Selectors/values are **JSON-encoded into the JS** (no breakout).
- Classified in `permissions.py` (reads = READ_ONLY; fill/click = LOCAL_WRITE; navigate/submit =
  SERVER_WRITE, matching `open_url`); allow-listed in `validator.py` so the voice/text Secretary can
  invoke them; auto-registered on the bus via `BROWSER_ACTIONS`.
- Documented in `docs/agent_control/browser_tools.md` (per-tool inputs/outputs/side-effects +
  examples). Reachable on every transport (Secretary, bus, Test Control Server, FastMCP via
  `list_actions`/`raw_command`).

## 3. Credential save & autofill (secure) — `modules/web_browser/autofill.py` (NEW)

Built on the existing encrypted vault (`credential_vault.py` → OS keychain/DPAPI; never plaintext).
- **Fill (field-anchored floating popup — revised 2026-06-28):** focusing/clicking a login field
  whose page host **exactly** matches a saved credential shows a small **floating suggestion popup
  anchored to the field** — a top-level `Qt.Popup` window, NOT part of the browser layout, so the
  page **never shifts or resizes**. The injected connector reports the field's
  `getBoundingClientRect` over QWebChannel; `autofill.compute_anchor` maps it to screen coordinates,
  placing the popup just below the field and **flipping above** when near the bottom edge (clamped to
  screen). Multiple saved logins render as a small list with **masked** passwords; choosing one fills
  username + password (no auto-submit) and hides the popup. Closes on outside click, navigation, or
  page scroll. (This replaced the earlier top offer-bar, which pushed page content down.)
- **Save:** a `QWebChannel` bridge + a connector script injected into an **isolated JS world**
  captures a login-form submit and **offers to save** (user confirms) into the vault.
- Security: domain-exact match, password JSON-encoded into JS, **never logged** (host+username only),
  user confirmation before save. Kill switch `AIPACS_BROWSER_AUTOFILL=0`.

## 4. Right-click context-menu contrast

There was no custom menu — the default QtWebEngine menu inherited a dark palette (dark-on-dark).
Added `_ThemedWebEngineView` (rebuilds the standard actions into a fully **theme-styled** `QMenu`
via `styles.menu_qss`) so text is high-contrast and readable in **every** theme. Falls back to a
minimal hand-built menu if the standard menu is unavailable.

## 5. Verification (offscreen / Windows venv)

- `py_compile`: all 11 changed files OK.
- Plugin-mirror parity: 393/393 (new files added to the `web_browser` payload; `permissions.py` is
  canonical-only by design).
- `tests/code/echomind` + `tests/code/web_browser`: **176 passed**. New guard
  `tests/code/web_browser/test_browser_page_tools_autofill.py` (JSON-encoding/no-breakout +
  domain-exact offer). Validator test updated to accept the new actions.
- Live offscreen build: `WebBrowserWidget` constructs with `_ThemedWebEngineView`, `_autofill_enabled
  True`, all 15 controller methods present.

## 6. Needs live source-build verification (human-assisted)

1. Cold-open timing improvement and the 2nd-session pre-warm (watch for the ~20 s → fast change).
2. Right-click menu readability in dark + light themes.
3. Autofill **offer bar** on a real login page and the **save** prompt on submit (full QWebChannel
   round-trip), then re-fill on return.
4. A Secretary/agent round-trip calling `browser_get_text` / `browser_fill_field` /
   `browser_submit_form` on a live page.

## 7. Flags (all default-on; `=0` restores legacy)

`AIPACS_WEBENGINE_SHARE_GL`, `AIPACS_BROWSER_PREWARM`, `AIPACS_BROWSER_AUTOFILL`,
`AIPACS_AGENT_PERMISSIONS` (existing).
