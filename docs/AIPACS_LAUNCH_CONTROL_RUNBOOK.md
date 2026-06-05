# AI-PACS — Launch & Control Runbook (agent standard procedure)

Standard, repeatable procedure for an agent (or human) to launch, position, log in,
search, and control the AI-PACS workstation — so the steps don't have to be re-explained
each session. Complements the **human-assisted bootstrap** section in `CLAUDE.md`.

## 0. Quick protocol (fast path — verified live 2026-06-03)

The fastest reliable sequence. Details are in the sections below.

1. **Launch (close + open in one):** run `run_app_canon_fresh.bat` — it kills any stale
   instance and launches the `.venv` source build. (Agent: File Explorer is usually on
   Monitor B; focus it, `Ctrl+L`, type the full `.bat` path, Enter. Human: double-click it.)
2. **Login:** when the login card appears, click **Sign In** (credentials are saved).
3. **Home Page:** wait for it (server "razi", Patient Search panel).
4. **Put it on Monitor A:** `Win+Shift+Right` (and `Win+Shift+Left` sends it back to B).
   Window must be focused. *Not* the maximize button.
5. **Work:** tick **MR**/**CT**, set the date (Last 2/3 days), **Search Patients**, open a patient.

One launcher, two clicks (Sign In + one keyboard shortcut), and you're working on Monitor A.

---

## 1. Launch (SOURCE build only)
- **Never** launch the frozen build (`d:\ai-pacs\aipacs\aipacs.exe`), the desktop AI-PACS
  icon, or the black AI-PACS taskbar icon. Those run pre-compiled code and ignore source edits.
- Launch from the repo (`E:\ai-pacs\ai-pacs codes\ai-pacs beta version`) with the **.venv**
  interpreter. Any of:
  - `.venv\Scripts\python.exe main.py` (explicit interpreter — most reliable)
  - `run_app.ps1` (PowerShell; tees terminal output to `log\`)
  - VS Code task **"AIPacs: Run App (logged)"**
  - `run_app_canon_fresh.bat` (kills stale instances, then launches the .venv build)
- **Single-instance guard:** a second launch detects a running instance and just raises its
  window, then exits — so the new code never loads. **Fully close / kill any running instance
  first** (`taskkill /F /IM python.exe /T`, `pythonw.exe`, `aipacs.exe`).
- **Interpreter matters:** the system `python` (python313) and the project `.venv` can resolve
  different copies of the `modules` package. Use the explicit `.venv\Scripts\python.exe` to be
  sure you're running the repo source.

### Agent limitation (why the user usually launches)
The agent's shell tool is a **Linux sandbox** (cannot launch or kill Windows processes), and
Windows **terminals / VS Code are computer-use tier "click"** (no keyboard input). So the agent
cannot type a launch command into a terminal. It can only launch by **double-clicking a `.bat`
in File Explorer** (full tier). If that is unreliable, ask the user to run the launch command —
do not spend cycles fighting window management.

## 2. Startup
- The app usually opens on **Monitor B**, sometimes **Monitor A**.
- If it opens on Monitor B, a **low disk-space warning** may appear at startup. It is not
  important — click **OK** to dismiss it.

## 3. Login
- After the warning, the **login page** appears.
- Username and password are usually already saved → click **Sign In**.

## 4. Monitor placement — mechanism & deterministic switching

### What the middle window button actually is (investigated 2026-06-03)
The middle title-bar button is `PacsClient/pacs/workstation_ui/mainwindow_ui.py::_toggle_max_restore`
— a **custom Qt frameless MAXIMIZE/RESTORE toggle**, *not* a monitor switcher:
- Not maximized → saves `_normal_geometry`, `showMaximized()`, then (10 ms later) snaps to
  `self.screen().availableGeometry()` (the screen the window is **already** on).
- Maximized → `showNormal()` and restore `_normal_geometry`.
There is **no "move to the other monitor" code** anywhere in the window logic (the related
`_maybe_snap_maximize`, `_restore_and_start_move_from_titlebar`, `nativeEvent`/`WM_EXITSIZEMOVE`,
`startSystemMove` all implement Windows-style drag/snap on the *current* screen).

**Why it seemed to move B→A but not A→B:** the button never moves monitors deliberately. Maximizing
a *frameless* window can incidentally land it on the **primary** monitor (A) via Qt/Windows
placement, so B→A appears to "work"; from A it just re-maximizes on A. This is a Windows/Qt
window-management **side effect**, non-deterministic — do **not** rely on it for switching.

### Deterministic methods (use these instead)
1. **Interactive / agent (no code change) — Windows shortcut:**
   `Win+Shift+Right` or `Win+Shift+Left` moves the **active window to the adjacent monitor**. With
   two monitors, either arrow toggles A↔B. Requirements: the AI-PACS window must be focused; an
   agent using computer-use needs the `systemKeyCombos` grant to send the combo.
2. **Automation / GUI tests (most robust) — explicit geometry move:** move the window's HWND to the
   target monitor's **work area**:
   - Win32: `user32.EnumDisplayMonitors` → target monitor `MONITORINFO.rcWork` →
     `SetWindowPos(hwnd, 0, x, y, w, h, SWP_NOZORDER)` (or `MoveWindow`).
   - pywinauto: `app.window(title_re="AI-?Pacs").move_window(x, y, width, height)` using the target
     monitor rect from `win32api.EnumDisplayMonitors()`.
   This is fully repeatable and independent of focus/shortcuts.
3. **Optional in-app feature (deterministic A↔B button)** — add to the main window:
   ```python
   def move_to_other_monitor(self):
       from PySide6.QtWidgets import QApplication
       from PySide6.QtCore import QTimer
       screens = QApplication.screens()
       cur = self.screen()
       target = next((s for s in screens if s is not cur), cur)
       was_max = self.isMaximized()
       if was_max:
           self.showNormal()
       wh = self.windowHandle()
       if wh:
           wh.setScreen(target)
       self.setGeometry(target.availableGeometry())
       if was_max:
           self.showMaximized()
           QTimer.singleShot(10, lambda: self.setGeometry(target.availableGeometry()))
   ```
   Bind it to a dedicated button/shortcut. It always targets the *non-current* screen → reliable
   both directions. (Proposed, not yet implemented.)

### Recommendation
- Agent / interactive: **`Win+Shift+Right`/`Left`**.
- Tests / automation: **Win32 `MoveWindow` to the target monitor's `rcWork`** (or pywinauto `move_window`).
- The maximize button is **not** a switch — leave it for maximize/restore only.

Monitor A ≈ primary `DELL S2421HN`; Monitor B ≈ `LCD1970NXp`. Agent note: `screenshot` captures the
primary display — use `switch_display` to view the other monitor.

**LIVE-VERIFIED 2026-06-03 (the deterministic method):** `Win+Shift+Right` moved the app **B→A** and
`Win+Shift+Left` moved it **A→B**, both reliably (A is physically to the right of B; window must be
focused). The maximize button was *not* used for switching. The full **close → relaunch → login →
position-on-A** cycle was confirmed end-to-end: close = click the window `×`; relaunch = in File
Explorer, `Ctrl+L` → type `E:\ai-pacs\ai-pacs codes\ai-pacs beta version\run_app_canon_fresh.bat`
→ Enter (it kills stale instances and launches the `.venv` source build, which opens on Monitor B);
then Sign In; then `Win+Shift+Right` to bring it to Monitor A.

## 5. Normal workflow (Home Page)
- Apply filters as needed — typically: date **Last 2 days** or **Last 3 days**; modality
  **MRI** and/or **CT**.
- Click **Search**.
- Open the required patient: **single-click** loads thumbnails; **double-click** opens the
  patient (see the single/double-click debounce in `patient_table_widget.py`).

## 6. Automation
- Prefer the project's GUI test / automation framework where it covers a step:
  `tests/gui/pywinauto/`, `tests/gui/echomind_driven/`, `tests/gui/live_walkthroughs/`.
- For computer-use: `request_access` for the running app window (granted by exe path; the
  source build's taskbar icon is the **Python** icon). The app window is full tier (clicks +
  typing allowed); terminals/VS Code are click-only.

## 7. Validation checklist (run once to confirm)
- [ ] Launch produces the source build (Python taskbar icon).
- [ ] Disk-space warning dismissed with OK (if shown).
- [ ] Sign In logs in with saved credentials.
- [ ] Middle window button toggles the app between Monitor A and Monitor B.
- [ ] Home Page filters (date + MRI/CT) + Search return a patient list.
- [ ] Single-click loads thumbnails; double-click opens the patient.
