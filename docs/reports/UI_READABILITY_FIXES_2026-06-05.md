# UI Readability Fixes — MPR Dropdown, Voice Popup, EchoMind (2026-06-05)

Three reported readability problems, all fixed inside the V2 design-system
gating (V1 stays byte-identical when pinned via `AIPACS_UI_VARIANT=v1`).

## 1. MPR/NPR dropdown — selected state unreadable

**Cause:** the Mode (Standard/MIP/MinIP/Thick Slab) and View (Axial/Sagittal/
Coronal) pickers used default Qt radio/checkbox indicators — dark-on-dark on
the popup's near-black gradient, so the *checked* state was nearly invisible.
The panel and header also predated the V2 dropdown language.

**Fix** (`toolbar_manager.py::_show_mpr_dropdown` + new `v2_style` helpers):
- New `option_control_qss` / `apply_option_controls_v2`: explicit 15px
  indicators — 2px token border at rest, accent border on hover, **solid
  accent fill when checked**; the checked label brightens to `text_primary`
  and bolds; hover rows get the `accent_soft` tint.
- `apply_dropdown_panel_v2` (flat token panel replaces the gradient) and
  `apply_dropdown_header_v2` (quiet caption replaces the purple bar) — the
  same gated pattern the sync/layout dropdowns already use.

## 2. Voice popup — old design style

**Cause:** `VoiceWidget` (the popup for patients with voice data) still used
the legacy glass style: rgba near-black panel + six per-color bordered
buttons, never migrated to V2.

**Fix** (`voice_tool_ui.py::_build_ui` + new `v2_style` helpers):
- Panel: `apply_dropdown_panel_v2(self)` — flat `card_bg` surface, token
  border, 12px radius (consistent with every other V2 popup).
- Buttons: new `voice_button_qss` / `apply_voice_button_v2` — the flat ghost
  language of the V2 mic controls, sized for labelled buttons: quiet
  semantic-tinted rest, soft tint + semantic border + white text on hover,
  solid semantic fill when pressed; proper disabled state. Roles: Play/Save =
  success, Pause = warning, Delete = danger, Report/Sync = accent.

## 3. EchoMind — black backgrounds, unclear states

**Cause (one root):** the entire EchoMind chat UI derives from seven
hard-coded tokens in `modules/EchoMind/ai_chat_config.py`:
`#222 / #1b1b1b` backgrounds, `#2b2b2b / #333` bubbles, `#dddddd` text and —
key to "states are not clear" — a **gray accent `#8a8a8a`**, so active/
selected/processing states never stood out. The "Generating…" bubble,
transcription-state bubbles, translated/processed output bubbles, composer +
send-button states, and the reception dialog all consume these tokens.

**Fix:** when the `echomind` module is on V2 (the build default), the seven
tokens re-point at the live AI-PACS theme at import:

| Token | Legacy | V2 (default theme) |
|---|---|---|
| `CLR_BG` | `#222` | `panel_bg` `#111927` |
| `CLR_BG_PANEL` | `#1b1b1b` | `card_bg` |
| `CLR_TEXT` | `#dddddd` | `text_primary` `#f8fafc` |
| `CLR_BORDER` | `#444` | `border` |
| `CLR_ACCENT` | `#8a8a8a` (gray!) | `accent` `#3182ce` |
| `CLR_BUBBLE_USER` | `#333` | `accent_soft` |
| `CLR_BUBBLE_BOT` | `#2b2b2b` | `panel_alt_bg` |

Verified live: importing the module resolves `#111927 / #f8fafc / #3182ce /
#162134`. The block never raises (any error → legacy palette), and pinning V1
restores the old look exactly. One systematic change recolors every listed
surface consistently with the rest of the workstation.

**Note on "Prescription section":** no UI element named *prescription* exists
in the EchoMind code (reception report flows do, and are covered by the token
re-point). If a specific prescription area still reads poorly after you see
this build live, point me at it and I'll style that widget directly.

## 4. Audio Recordings / Captured Images dropdown (follow-up, same day)

The screenshot the user provided showed the **attachments dropdown**
(`attachments_dropdown.py` — a different widget from the recorder popup in
§2): filled green header bar, gradient cards, saturated filled squares
(green/red/purple/red), and stray frames around "#1" and the date — a QSS
cascade bug (the popup's bare `QWidget{…}` selector leaks its border onto
child labels).

**Redesign (V2-gated, V1 byte-identical):**
- Popup → flat token panel; headers → quiet captions; scrollbars → token.
- Item cards → flat `panel_alt_bg` + 1px border, accent border on hover; the
  card QSS explicitly resets `QLabel` background/border — **fixes the stray
  label frames**.
- Mic box → quiet `success_subtle` chip (keeps the audio-green identity).
- Action buttons → icon ghosts in the V2 mic-control language: Play=success,
  **Stop=warning** (transport, not destructive), Report=accent,
  Delete=danger — exactly one red, the destructive one (the old design had
  two adjacent reds).
- Seek slider → token groove + success handle/progress; times → success/muted.
- **UX: popup height now sizes to content** (`preferred_height()`, clamped
  200–500px) instead of the fixed 500px well that left a large dead area
  under a single recording. Applied at both openers in `toolbar_manager.py`.
- Image panel got the same treatment (accent identity, view=accent ghost).

## Verification

| Check | Result |
|---|---|
| `tests/code/test_ui_readability_v2.py` (9 new: QSS tokens, role colors, safe defaults, source contracts) | passed |
| `test_v2_style_scaffold.py` + `test_ui_variant_scaffold.py` (V2 invariants) | passed — 64 total in combined run |
| `py_compile` all 4 edited files | OK |
| `tools/dev/verify_plugin_mirrors.py` (echomind payload re-synced) | **287/287** |
| Live token resolution (`ai_chat_config` import under default variant) | `#111927 / #f8fafc / #3182ce` ✓ |

V2 invariants kept: styles applied at the source style sites (survive
re-styling), token-only colors, every helper gated + never-raises, V1
untouched. Files: `v2_style.py`, `toolbar_manager.py`, `voice_tool_ui.py`,
`ai_chat_config.py` (+ echomind plugin payload mirror).

**Live QA checklist (next launch):** open the MPR dropdown → checked
Mode/View shows a solid blue indicator + bright bold label; open the voice
popup on a patient with voice data → flat panel + ghost buttons; EchoMind →
"Generating…" bubble, transcription/translated outputs and reception dialog
on navy panels with bright text and blue (not gray) active states.
