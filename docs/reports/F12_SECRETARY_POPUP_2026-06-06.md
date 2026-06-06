# Global F12 — EchoMind Secretary Popup (2026-06-06)

Pressing **F12 anywhere in the app** toggles the EchoMind Secretary as a
floating, non-blocking overlay — the same widget that lives under the
home-page patient search (orb, Ready/status area, memory/cycle bar, New).

## How it works

| Piece | File | Notes |
|---|---|---|
| Shortcut | `PacsClient/pacs/workstation_ui/shortcut_manager.py` | `QShortcut(Qt.Key_F12)` with `Qt.ApplicationShortcut` — exactly the pattern of the existing F5–F8 (which are untouched). F12 was unused anywhere in the app. Handler is fail-safe and lazily imports the popup (audio deps don't load at startup). |
| Popup | `PacsClient/pacs/workstation_ui/home_ui/secretary_popup.py` (new) | `SecretaryPopup` — frameless `Qt.Tool + WindowStaysOnTopHint` window. **Non-modal, no input grab**: the UI underneath keeps working. Hosts its **own `SecretaryButtonWidget` instance** (full panel structure reused; separate orchestrator session) — the home-page widget is never touched or reparented. Created once, toggled thereafter (session/memory state survives close). Title bar with brand + **✕**, draggable, theme-token styled, positioned over the lower-left of the main window (mirrors its home placement; remembers a user-dragged position). |
| Safe cancel | `secretary_button_widget.py` → new public `cancel_recording()` | ✕ (and OS-level close) first cancels an in-flight recording: stops the capture thread (bounded join), **discards** the frames — never sends them to STT — resets the orb/status, then hides the popup. Closing while idle is a plain hide. |

## Conservative-by-design

- Additive only: no existing shortcut, the home-page secretary, EchoMind chat,
  or any module code path changed (the only widget edit is the new
  `cancel_recording()` method).
- Every layer is wrapped fail-safe — a popup failure prints and leaves the
  shortcut table and home widget intact.
- Auto-close on completion was deliberately NOT added: the popup shows the
  command result/status, and auto-hiding would discard what the user asked
  for. Easy to add later if wanted.
- Mic note: the popup instance and the home orb are separate recorders — only
  one is used at a time in practice; both honor the same stop/cancel paths.

## Verification

| Check | Result |
|---|---|
| `tests/code/test_secretary_f12_popup.py` (9: singleton toggle ×3 states, non-modal/on-top flags, ✕ cancels recording + hides, OS-close cancels, idle close safe, F12 app-wide + lazy + fail-safe, F5–F8/arrows untouched, `cancel_recording` discards & never routes to STT) | **9/9 passed** |
| `tests/code/echomind` regression | **102 passed** |
| `py_compile` (3 files) | OK |
| `verify_plugin_mirrors` (PacsClient not mirrored — no payload change) | **290/290** |

## Live QA (next launch)

1. From the home page, a patient tab, MPR, Eagle Eye, settings: press **F12** → the Secretary appears above the UI; click around the app behind it — everything stays interactive.
2. Press F12 again → it hides; again → it returns with the same memory/cycle state.
3. Start listening (orb), then click **✕** mid-recording → popup closes, nothing is transcribed, home-page orb unaffected; reopen → status "Ready".
4. Drag it by the title bar; F12-toggle → it reopens where you left it.
5. Sanity: F5/F6/F7/F8 and arrow keys behave exactly as before.
