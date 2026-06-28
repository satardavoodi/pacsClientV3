"""AI-PACS CD viewer launcher — double-clickable, console-free, no prompts.

Built as a standalone **onefile EXE** (``AIPacsViewer.exe``) and placed at the
media ROOT. Double-clicking it opens the viewer DIRECTLY:

* No console window  — a ``.cmd`` always opens a black console; this is a GUI exe.
* No "open with" prompt — a ``.hta``/``.vbs`` triggers Windows file-association
  prompts on some PCs; an ``.exe`` never does.
* No extra Windows questions — it just runs.

While it works it shows an AI-PACS-branded "Preparing viewer, please wait."
window (tkinter, styled to match the viewer's welcome page), copies the onedir
viewer bundle to local disk — optical *random* reads of a PyInstaller bundle are
unreliable ("could not load PKG archive"), so we copy with retries and run from
the copy — then launches the viewer and closes. The DICOM images stay on the
disc and are read via ``--import-folder``.

stdlib only (tkinter for the splash) so the launcher stays tiny and dependency
free, which also makes its own onefile extraction fast and reliable from CD.
Never import ``modules.cd_burner...`` here (freeze tools would drag the whole
workstation chain into the bundle).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

PREPARING_MESSAGE = "Preparing viewer, please wait."
TEMP_DIRNAME = "AIPacsLiteViewer"
_DEFAULT_VIEWER_REL = "VIEWER\\AIPacsLiteViewer.exe"
_CREATE_NO_WINDOW = 0x08000000  # hide robocopy's console

# Brand palette (matches portable_viewer/welcome.py)
_BG = "#0d1320"
_CARD = "#172133"
_BORDER = "#2b3b58"
_TITLE = "#e8eef7"
_SUBTLE = "#7fa3d4"
_TEXT = "#e2e8f0"
_ACCENT = "#3b82f6"
_TROUGH = "#24304a"
_ERROR = "#f87171"


def _media_root() -> str:
    """Folder that holds this launcher exe (the media root)."""
    base = sys.executable if getattr(sys, "frozen", False) else __file__
    return os.path.dirname(os.path.abspath(base))


def _is_32bit_windows() -> bool:
    return (
        os.environ.get("PROCESSOR_ARCHITECTURE", "").lower() == "x86"
        and "PROCESSOR_ARCHITEW6432" not in os.environ
    )


def _viewer_rel_from_manifest(root: str) -> str:
    """Read the viewer launcher path from AIPACS_MEDIA_INFO.json; fall back to
    the default VIEWER\\AIPacsLiteViewer.exe layout."""
    try:
        with open(os.path.join(root, "AIPACS_MEDIA_INFO.json"), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        rel = data.get("viewer_launcher")
        if rel:
            return str(rel).replace("/", "\\")
    except Exception:
        pass
    return _DEFAULT_VIEWER_REL


def _copy_viewer_to_temp(viewer_dir: str, dest: str, exe_name: str) -> bool:
    """Copy the onedir bundle to local disk with retries (robocopy rides out
    flaky optical reads). Returns True when the copied exe exists."""
    try:
        os.makedirs(dest, exist_ok=True)
    except Exception:
        pass
    try:
        subprocess.run(
            ["robocopy", viewer_dir, dest, "/E", "/R:3", "/W:1",
             "/NFL", "/NDL", "/NJH", "/NJS", "/NP"],
            creationflags=_CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=900,
        )
    except Exception:
        pass
    return os.path.isfile(os.path.join(dest, exe_name))


def _launch(exe: str, import_folder: str) -> bool:
    try:
        subprocess.Popen([exe, "--import-folder", import_folder], close_fds=True)
        return True
    except Exception:
        return False


def _open_folder(path: str) -> None:
    try:
        os.startfile(path)  # noqa: P204 — Windows-only, intentional
    except Exception:
        pass


def _prepare(root: str, state: dict) -> None:
    """Background worker: 32-bit guard, copy-to-temp, launch the viewer."""
    try:
        if _is_32bit_windows():
            _open_folder(root)
            state["error"] = (
                "This PC runs 32-bit Windows; the viewer needs 64-bit Windows.\n"
                "The images folder was opened — open DICOMDIR with any DICOM viewer."
            )
            state["done"] = True
            return

        viewer_rel = _viewer_rel_from_manifest(root)
        src_exe = os.path.join(root, viewer_rel)
        viewer_dir = os.path.dirname(src_exe)
        exe_name = os.path.basename(viewer_rel)

        if not os.path.isfile(src_exe):
            _open_folder(root)
            state["error"] = "Viewer was not found on this disc."
            state["done"] = True
            return

        run_exe = src_exe
        # A PyInstaller onedir bundle (has _internal) must run from local disk;
        # a single-exe viewer runs in place.
        if os.path.isdir(os.path.join(viewer_dir, "_internal")):
            temp_base = os.environ.get("TEMP") or os.environ.get("TMP") or root
            dest = os.path.join(temp_base, TEMP_DIRNAME)
            if _copy_viewer_to_temp(viewer_dir, dest, exe_name):
                run_exe = os.path.join(dest, exe_name)
            # else: fall back to running from the disc

        if _launch(run_exe, root):
            state["ok"] = True
        else:
            _open_folder(root)
            state["error"] = (
                "Could not start the viewer.\n"
                "Open DICOMDIR on the disc with any DICOM viewer."
            )
        state["done"] = True
    except Exception as exc:  # pragma: no cover - defensive
        state["error"] = "Preparation error:\n%s" % exc
        state["done"] = True


# ---------------------------------------------------------------------------
# Branded splash (tkinter)
# ---------------------------------------------------------------------------

def _run_with_splash(root: str) -> int:
    import tkinter as tk
    from tkinter import ttk

    win = tk.Tk()
    win.title("AI-PACS Viewer")
    win.overrideredirect(True)        # borderless
    win.configure(bg=_BG)
    w, h = 460, 240
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass

    card = tk.Frame(win, bg=_CARD, highlightbackground=_BORDER, highlightthickness=1)
    card.place(relx=0.5, rely=0.5, anchor="center", width=w - 40, height=h - 40)
    tk.Label(card, text="AI-PACS", bg=_CARD, fg=_TITLE,
             font=("Segoe UI", 26, "bold")).pack(pady=(28, 0))
    tk.Label(card, text="DICOM VIEWER", bg=_CARD, fg=_SUBTLE,
             font=("Segoe UI", 9, "bold")).pack()
    msg = tk.Label(card, text=PREPARING_MESSAGE, bg=_CARD, fg=_TEXT,
                   font=("Segoe UI", 12))
    msg.pack(pady=(24, 12))

    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("AIP.Horizontal.TProgressbar", troughcolor=_TROUGH,
                    background=_ACCENT, bordercolor=_CARD, lightcolor=_ACCENT,
                    darkcolor=_ACCENT)
    bar = ttk.Progressbar(card, mode="indeterminate", length=300,
                          style="AIP.Horizontal.TProgressbar")
    bar.pack()
    bar.start(12)

    state: dict = {"done": False, "ok": False, "error": ""}
    threading.Thread(target=_prepare, args=(root, state), daemon=True).start()

    def _show_error(text: str) -> None:
        try:
            bar.stop()
            bar.pack_forget()
        except Exception:
            pass
        msg.configure(text=text, fg=_ERROR, justify="center")
        tk.Button(card, text="Close", command=win.destroy, bg=_ACCENT, fg="white",
                  activebackground="#1e40af", activeforeground="white", relief="flat",
                  bd=0, padx=20, pady=5, font=("Segoe UI", 10, "bold")).pack(pady=(4, 0))

    def _tick() -> None:
        if state["done"]:
            if state["ok"]:
                win.destroy()           # viewer launched → close splash
            elif state["error"]:
                _show_error(state["error"])
            else:
                win.destroy()
            return
        win.after(120, _tick)

    win.after(150, _tick)
    win.mainloop()
    return 0


def main() -> int:
    root = _media_root()
    try:
        return _run_with_splash(root)
    except Exception:
        # No GUI available — do the work headless so the viewer still opens.
        state: dict = {"done": False, "ok": False, "error": ""}
        _prepare(root, state)
        return 0 if state.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
