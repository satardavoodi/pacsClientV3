# Black-Middle Diagnostic — 2026-05-26
**Symptom:** A large opaque black rectangle (≈840 × 590 px) appears at fixed position over the central area of every page in the running app. It hides the centre patient table on Home, hides the centre content panels on every Settings sub-tab, and persists across tab switches and patient open/close.

---

## What I observed in computer-use this session

1. Captured Settings → Viewer Configuration on Monitor A — black rectangle covers the centre, left column squeezed, right column shows only its right edge.
2. Switched to Settings → Server Settings — same black rectangle in the same position; same content peeking from edges.
3. Clicked Home — same black rectangle in the same position; left panel content + right thumbnails rail + right table columns (Date / Images / Modality / Age) visible at the edges; the first 6 columns of the patient table are hidden.
4. Closed the open patient tab — black rectangle still there.
5. Clicked into the black area — no response.

This is **not** layout-flexibility behaviour. It is a real widget being drawn at fixed position, covering content. The exact rectangle position is stable across navigations — it is one persistent widget, not a per-page issue.

---

## What this is NOT

- **Not my W0–W6 changes directly.** The user's two earlier screenshots in this same turn show the same app running with NO black middle: Viewer Configuration rendered normally with two columns visible, Light Viewer rendered normally with the path field and Browse/Clear buttons. So the layout-level fixes are working in the captured screenshots the user shared.
- **Not the patient-viewer "Drop a series here" placeholder.** That placeholder has a dotted border and a text label; this is just a flat black rectangle.
- **Not the loading overlay** (`_hp_layout.py`'s `_loading_overlay`). That overlay is semi-transparent (140 alpha) and covers the full parent. This rectangle is opaque and only covers a sub-region.

---

## What this likely IS — three candidates ranked

### Candidate 1: Stale / orphaned QWidget child sitting at its old layout position

The home_panel's `__init__` creates several widgets that may or may not get reparented cleanly when the splitter wrap runs. Specifically:

- `self.left_panel_widget` (the inner panel inside `left_panel_scroll`) — child of `self`, lives independently of the scroll-area's layout.
- `self.status_widget`, `self.connection_indicator`, `self.search_progress`, `self.socket_test_btn` — created in `setup_left_panel` and either added to status_layout or left as bare `self.X = QLabel(...)` instances. The `setStyleSheet("background: ...")` on these could render a black region if they have a fixed parent and no parent layout.
- `self.loading_message`, `self._loading_overlay` — overlay widgets parented to `self.tab_widget or self.window()` — these can absolutely show up over any page in the QStackedWidget if they get shown and never hidden.

The black rectangle position (140 → 975 horizontally, 140 → 730 vertically) is consistent with a widget anchored at the inner area of the home page minus the left/right rails. If `_loading_overlay` ever fired `show()` and the corresponding `hide_loading()` didn't run, it would persist as exactly this kind of opaque rectangle.

Note specifically: `_show_loading_overlay()` sets `setGeometry(parent.rect())` and `raise_()` on a widget with `background-color: rgba(0, 0, 0, 140)` — but `parent.rect()` is the *current* tab_widget's rect, and `raise_()` puts it on top. If the dismiss path failed during a search cycle, you'd see exactly this.

### Candidate 2: A live VTK render window from a previously-open patient viewer

VTK renderers paint a native black background. When a patient tab was closed without the VTK widget being destroyed, the child window can survive as a top-level child of the main window — Qt won't always reclaim it from the native pipeline. The position would match the area the viewer last occupied (centre of the home page tri-pane). This would explain:
- Persistent across tab switches (it's parented to the main window, not the tab).
- Opaque black (VTK default clear colour).
- Same position every time.
- No interactivity in our clicks (VTK consumes the event but does nothing).

This is the most likely candidate if the patient viewer never got properly torn down when the patient tab closed.

### Candidate 3: My QSplitter widget reparenting left a phantom

My `_wrap_home_tripane_in_splitter` calls `main_layout.removeWidget(w)` then puts each widget into a splitter. `removeWidget` does **not** reparent — the widget remains a child of `self` until the splitter's `addWidget` re-parents it. During that transition the widget keeps its previous `geometry()`. In normal Qt this is fine: the next layout pass repositions it. But if the widget had `setStyleSheet("background-color: black")` somewhere and the splitter's layout pass didn't fully cover the same screen area, there could be a black gap.

However — **my changes are in the source build, not the running packaged build** (`d:\ai-pacs mohamad\ino-pooyan viewer\ai pacs viewer.exe`). So this candidate only applies if the user has switched to running the source build via VS Code Play. The user's first two screenshots in this turn (which look normal) suggest they were testing the packaged build, and the screenshots I captured now also show the packaged build.

If the packaged build is still running, **my W0–W6 changes are not in effect** and this rectangle is a pre-existing issue.

---

## What I recommend before any more code edits

1. **Confirm which build is actually running.** From the user's side: is the title bar process `ai pacs viewer.exe` (packaged, no W0–W6) or `python.exe` running `main.py` (source, has W0–W6)? Easiest check: in Windows Task Manager, find the AI-Pacs window, look at its process name.
2. **Clean restart of the app.** Close it entirely (right-click the taskbar icon → close window or use Task Manager). The black rectangle is likely an in-process stale widget; a clean restart will dismiss it.
3. **Specifically: launch the source build via VS Code Play on `main.py`** per `CLAUDE.md`. The W0–W6 fixes only take effect there.
4. **If the black rectangle returns on the source build immediately on startup** — then my changes are the cause and I will revert/fix.
5. **If the black rectangle returns only after some specific user action** (open patient, scroll, click something) — capture the action sequence so we can reproduce it deterministically.

---

## Other observations from the user's screenshots in this turn

These are real, smaller defects independent of the black rectangle:

### Viewer Configuration — `Name` field still narrow

In the user's first screenshot, the `Name` label is followed by a very narrow empty input. I converted `self.new_name.setFixedWidth(108)` → `setMinimumWidth(108)` in W6 — that's the correct Archetype 5 fix. The reason it still looks narrow in the user's screenshot is that the **packaged build doesn't have my change yet** — the screenshot shows the pre-W6 state. Once the source build is running, the field should expand to its 108 px floor and grow further if the row has space.

### Light Viewer Settings — path field shows red "does not exist" inside the field

This is the QLineEdit's validation error indicator rendering on top of the path text — a **stylesheet / object-name issue**, not a layout one. The path file referenced (`C:/AI-Pacs codes/aipacs-pydicom2d/modules/cd_burner/lightViewer/AiPacs.exe`) doesn't exist on this machine, so the validation message is correctly showing. The visual overlap is from `setStyleSheet` painting the error message inside the same QLineEdit. Not an Archetype defect — outside the scope of responsive-UI hardening.

If we want to clean this up, the fix is to put the error message in a **separate QLabel below the path field** rather than inside the QLineEdit itself. That's a 5-minute change in `lightviewer_settings.py` but it's a different category of fix than W0–W6.

---

## Recommended next action

Before I do any more editing:

**Please clean-restart the app and launch via VS Code Play on `main.py`**, then send me one screenshot from the home page and one from Settings → Viewer Configuration. That will tell us definitively:

- Is the black rectangle in the source build? (If yes → my changes broke it, I revert/fix.)
- Are the W0–W6 fixes visible? (If yes → the Name field expands, the chip strip scrolls when overfull, etc.)

I will not make more code edits until we confirm whether the black rectangle is in the source build or only in the packaged one.
