"""AI-PACS CD viewer launcher — double-clickable, console-free, no prompts.

Built as a standalone **onefile EXE** (``AIPacsViewer.exe``) and placed at the
media ROOT. Double-clicking it opens the viewer DIRECTLY:

* No console window  — a ``.cmd`` always opens a black console; this is a GUI exe.
* No "open with" prompt — a ``.hta``/``.vbs`` triggers Windows file-association
  prompts on some PCs; an ``.exe`` never does.
* No extra Windows questions — it just runs.

PERFORMANCE: optical media is slow for the random, repeated reads a DICOM viewer
makes while the user scrolls. So the launcher COPIES the study to a managed
LOCAL cache during the branded "Preparing viewer, please wait." popup and points
the viewer at the cache — the CD is the source, never the runtime read path.

Local cache (per user, no admin):
``%LOCALAPPDATA%\\AI-PACS\\CDViewerCache`` (fallback ``%TEMP%\\AIPacsCDViewerCache``)
  ├── viewer/                 the onedir viewer runtime (shared across discs)
  └── studies/<key>/          one folder per study (DICOMDIR + image tree + manifest)

Behaviour:
  * Reuse a valid cached study on reopen (fast — no copy).
  * Prune old studies (keep newest N, cap total size) so the cache never grows
    without bound; never delete the study in use.
  * Free-space check; if the cache can't be prepared (low disk / read-only target
    / any error) fall back to opening straight from the CD (slower but works).

stdlib only (tkinter for the splash) so the launcher stays tiny and dependency
free, which also makes its own onefile extraction fast and reliable from CD.
Never import ``modules.cd_burner...`` here (freeze tools would drag the whole
workstation chain into the bundle).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time

PREPARING_MESSAGE = "Preparing viewer, please wait."
_DEFAULT_VIEWER_REL = "VIEWER\\AIPacsLiteViewer.exe"
_CREATE_NO_WINDOW = 0x08000000  # hide robocopy's console

# Cache layout / policy
_CACHE_APP_DIR = "AI-PACS"
_CACHE_NAME = "CDViewerCache"
_VIEWER_CACHE_DIRNAME = "viewer"
_STUDIES_DIRNAME = "studies"
_MARKER_NAME = ".aipacs_cache.json"
_KEEP_STUDIES = 6                       # keep this many most-recent studies
_MAX_CACHE_BYTES = 8 * 1024 * 1024 * 1024   # ...and stay under 8 GB total
_FREE_MARGIN_BYTES = 300 * 1024 * 1024      # leave 300 MB headroom

# Files/dirs at the media root that are launcher infrastructure, NOT study data.
_STUDY_EXCLUDE_DIRS = ("VIEWER",)
_STUDY_EXCLUDE_FILES = (
    "AIPacsViewer.exe", "RUN_VIEWER.cmd", "OPEN_DICOM_FOLDER.cmd", "autorun.inf",
)

# Brand palette (matches portable_viewer/welcome.py)
_BG = "#0d1320"
_CARD = "#172133"
_BORDER = "#2b3b58"
_TITLE = "#e8eef7"
_SUBTLE = "#7fa3d4"
_TEXT = "#e2e8f0"
_MUTED = "#9aa6b2"
_ACCENT = "#3b82f6"
_TROUGH = "#24304a"
_ERROR = "#f87171"


# ---------------------------------------------------------------------------
# Media / environment helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Cache (pure-ish, unit-testable) helpers
# ---------------------------------------------------------------------------

def cache_root() -> str:
    """Per-user cache root (no admin needed). Prefer LOCALAPPDATA, else TEMP."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base and os.path.isdir(base):
        return os.path.join(base, _CACHE_APP_DIR, _CACHE_NAME)
    tmp = os.environ.get("TEMP") or os.environ.get("TMP") or os.getcwd()
    return os.path.join(tmp, "AIPacsCDViewerCache")


def _is_excluded_dir(name: str) -> bool:
    return name.lower() in {d.lower() for d in _STUDY_EXCLUDE_DIRS}


def _is_excluded_file(name: str) -> bool:
    return name.lower() in {f.lower() for f in _STUDY_EXCLUDE_FILES}


def iter_study_files(media_root: str):
    """Yield (relpath, size) for every study-data file under ``media_root``
    (i.e. everything except the viewer bundle and launcher infrastructure)."""
    for dirpath, dirnames, filenames in os.walk(media_root):
        # prune excluded top-level dirs
        rel_dir = os.path.relpath(dirpath, media_root)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if not _is_excluded_dir(d)]
        for fn in filenames:
            if rel_dir == "." and _is_excluded_file(fn):
                continue
            full = os.path.join(dirpath, fn)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            rel = os.path.relpath(full, media_root).replace("\\", "/").lower()
            yield rel, size


def compute_study_signature(media_root: str):
    """Deterministic (key, file_count, total_bytes) for the study data.

    The key is a hash of the (relpath, size) set — same disc content → same key
    (so reopening reuses the cache), without reading file *contents*.
    """
    entries = sorted(iter_study_files(media_root))
    h = hashlib.sha1()
    total = 0
    for rel, size in entries:
        h.update(("%s|%d\n" % (rel, size)).encode("utf-8", "replace"))
        total += size
    key = h.hexdigest()[:16] or "empty"
    return key, len(entries), total


def _marker_path(study_dir: str) -> str:
    return os.path.join(study_dir, _MARKER_NAME)


def dir_stats(path: str):
    """(file_count, total_bytes) of real files under ``path`` (markers excluded)."""
    count = 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for fn in files:
            if fn == _MARKER_NAME:
                continue
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
                count += 1
            except OSError:
                continue
    return count, total


def is_study_cache_valid(study_dir: str, key: str) -> bool:
    """A cache is valid only if its completion marker matches the key AND the
    files on disk still match the recorded count + size (catches partial /
    interrupted copies)."""
    marker = _marker_path(study_dir)
    if not os.path.isfile(marker):
        return False
    try:
        with open(marker, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return False
    if data.get("key") != key or not data.get("complete"):
        return False
    count, total = dir_stats(study_dir)
    return count == data.get("file_count") and total == data.get("total_bytes")


def write_cache_marker(study_dir: str, key: str, file_count: int, total_bytes: int) -> None:
    payload = {
        "key": key,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "complete": True,
        "completed_at": time.time(),
    }
    with open(_marker_path(study_dir), "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def touch_cache(study_dir: str) -> None:
    """Mark a study cache as most-recently-used (drives LRU pruning)."""
    try:
        os.utime(_marker_path(study_dir), None)
    except OSError:
        pass


def free_bytes(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except Exception:
        return 0


def prune_studies(studies_root: str, current_dir: str,
                  keep: int = _KEEP_STUDIES, max_bytes: int = _MAX_CACHE_BYTES) -> list:
    """Keep the newest ``keep`` study caches and stay under ``max_bytes``.
    Never deletes ``current_dir``. Returns the list of removed dirs."""
    removed = []
    try:
        entries = [os.path.join(studies_root, d) for d in os.listdir(studies_root)]
    except OSError:
        return removed
    studies = [d for d in entries if os.path.isdir(d)]

    def _mtime(d):
        try:
            return os.path.getmtime(_marker_path(d))
        except OSError:
            try:
                return os.path.getmtime(d)
            except OSError:
                return 0.0

    # newest first
    studies.sort(key=_mtime, reverse=True)
    current = os.path.normcase(os.path.abspath(current_dir))

    kept = []
    running_total = 0
    for d in studies:
        is_current = os.path.normcase(os.path.abspath(d)) == current
        _c, size = dir_stats(d)
        over_count = len(kept) >= keep
        over_size = (running_total + size) > max_bytes
        if is_current:
            kept.append(d)
            running_total += size
            continue
        if over_count or over_size:
            try:
                shutil.rmtree(d, ignore_errors=True)
                removed.append(d)
            except Exception:
                pass
        else:
            kept.append(d)
            running_total += size
    return removed


# ---------------------------------------------------------------------------
# Copy / launch
# ---------------------------------------------------------------------------

def _robocopy(src: str, dest: str, xd=(), xf=()) -> None:
    """Mirror ``src``→``dest`` incrementally (skips unchanged files; retries ride
    out flaky optical reads). Hidden — no console window."""
    try:
        os.makedirs(dest, exist_ok=True)
    except Exception:
        pass
    cmd = ["robocopy", src, dest, "/E", "/R:2", "/W:1", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
    for d in xd:
        cmd += ["/XD", os.path.join(src, d)]
    for f in xf:
        cmd += ["/XF", f]
    try:
        subprocess.run(cmd, creationflags=_CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)
    except Exception:
        # robocopy missing/blocked → best-effort python copy of the tree
        _py_copy_tree(src, dest, xd, xf)


def _py_copy_tree(src: str, dest: str, xd=(), xf=()) -> None:
    xd_l = {d.lower() for d in xd}
    xf_l = {f.lower() for f in xf}
    for dirpath, dirnames, files in os.walk(src):
        rel_dir = os.path.relpath(dirpath, src)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d.lower() not in xd_l]
        target_dir = dest if rel_dir == "." else os.path.join(dest, rel_dir)
        try:
            os.makedirs(target_dir, exist_ok=True)
        except Exception:
            continue
        for fn in files:
            if rel_dir == "." and fn.lower() in xf_l:
                continue
            try:
                shutil.copy2(os.path.join(dirpath, fn), os.path.join(target_dir, fn))
            except Exception:
                continue


def _viewer_cache_ready(viewer_cache: str, exe_name: str) -> bool:
    return (
        os.path.isfile(os.path.join(viewer_cache, exe_name))
        and os.path.isfile(os.path.join(viewer_cache, "_internal", "base_library.zip"))
    )


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


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _prepare(root: str, state: dict) -> None:
    """Background worker: build the local cache (viewer + study), then launch the
    viewer from the cache. Falls back to opening straight from the CD on any
    cache problem. Updates ``state`` for the splash UI."""
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
        has_internal = os.path.isdir(os.path.join(viewer_dir, "_internal"))

        if not os.path.isfile(src_exe):
            _open_folder(root)
            state["error"] = "Viewer was not found on this disc."
            state["done"] = True
            return

        run_exe = src_exe
        import_folder = root  # default: read straight from the CD (fallback)

        try:
            root_dir = cache_root()
            viewer_cache = os.path.join(root_dir, _VIEWER_CACHE_DIRNAME)
            studies_root = os.path.join(root_dir, _STUDIES_DIRNAME)
            os.makedirs(studies_root, exist_ok=True)

            key, file_count, total_bytes = compute_study_signature(root)
            study_dir = os.path.join(studies_root, key)
            state["study_dir"] = study_dir

            # Space we still need to copy (skip what is already cached & valid).
            need = 0
            study_ok = is_study_cache_valid(study_dir, key)
            if not study_ok:
                need += total_bytes
            viewer_ok = (not has_internal) or _viewer_cache_ready(viewer_cache, exe_name)
            if has_internal and not viewer_ok:
                _vc, vbytes = dir_stats(viewer_dir)
                need += vbytes

            if need > 0 and free_bytes(root_dir) < (need + _FREE_MARGIN_BYTES):
                prune_studies(studies_root, study_dir)
            if need > 0 and free_bytes(root_dir) < (need + _FREE_MARGIN_BYTES):
                raise RuntimeError("not enough free disk space for the local cache")

            # 1) Viewer runtime → local cache (onedir only; single-exe runs from CD).
            if has_internal:
                if not viewer_ok:
                    state["status"] = "Copying viewer…"
                    _robocopy(viewer_dir, viewer_cache)
                cached_exe = os.path.join(viewer_cache, exe_name)
                if os.path.isfile(cached_exe):
                    run_exe = cached_exe
                else:
                    raise RuntimeError("viewer cache incomplete")

            # 2) Study data (DICOMDIR + images) → local cache.
            if study_ok:
                state["status"] = "Using local cache…"
            else:
                state["status"] = "Copying images…"
                _robocopy(root, study_dir, xd=_STUDY_EXCLUDE_DIRS, xf=_STUDY_EXCLUDE_FILES)
                if not (os.path.isfile(os.path.join(study_dir, "DICOMDIR"))
                        or dir_stats(study_dir)[0] > 0):
                    raise RuntimeError("study cache incomplete")
                c2, b2 = dir_stats(study_dir)
                write_cache_marker(study_dir, key, c2, b2)
            import_folder = study_dir

            touch_cache(study_dir)
            prune_studies(studies_root, study_dir)
            state["mode"] = "cache"
        except Exception as cache_exc:
            # Graceful: cache could not be prepared → open straight from the CD.
            state["mode"] = "cd"
            state["cache_note"] = str(cache_exc)
            run_exe = (os.path.join(cache_root(), _VIEWER_CACHE_DIRNAME, exe_name)
                       if has_internal and _viewer_cache_ready(
                           os.path.join(cache_root(), _VIEWER_CACHE_DIRNAME), exe_name)
                       else src_exe)
            import_folder = root

        state["status"] = "Starting viewer…"
        if _launch(run_exe, import_folder):
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
    w, h = 470, 250
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass

    card = tk.Frame(win, bg=_CARD, highlightbackground=_BORDER, highlightthickness=1)
    card.place(relx=0.5, rely=0.5, anchor="center", width=w - 40, height=h - 40)
    tk.Label(card, text="AI-PACS", bg=_CARD, fg=_TITLE,
             font=("Segoe UI", 26, "bold")).pack(pady=(26, 0))
    tk.Label(card, text="DICOM VIEWER", bg=_CARD, fg=_SUBTLE,
             font=("Segoe UI", 9, "bold")).pack()
    msg = tk.Label(card, text=PREPARING_MESSAGE, bg=_CARD, fg=_TEXT,
                   font=("Segoe UI", 12))
    msg.pack(pady=(22, 4))
    detail = tk.Label(card, text="", bg=_CARD, fg=_MUTED, font=("Segoe UI", 9))
    detail.pack(pady=(0, 8))

    style = ttk.Style(win)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("AIP.Horizontal.TProgressbar", troughcolor=_TROUGH,
                    background=_ACCENT, bordercolor=_CARD, lightcolor=_ACCENT,
                    darkcolor=_ACCENT)
    bar = ttk.Progressbar(card, mode="indeterminate", length=320,
                          style="AIP.Horizontal.TProgressbar")
    bar.pack()
    bar.start(12)

    state: dict = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
    threading.Thread(target=_prepare, args=(root, state), daemon=True).start()

    def _show_error(text: str) -> None:
        try:
            bar.stop()
            bar.pack_forget()
        except Exception:
            pass
        detail.pack_forget()
        msg.configure(text=text, fg=_ERROR, justify="center")
        tk.Button(card, text="Close", command=win.destroy, bg=_ACCENT, fg="white",
                  activebackground="#1e40af", activeforeground="white", relief="flat",
                  bd=0, padx=20, pady=5, font=("Segoe UI", 10, "bold")).pack(pady=(4, 0))

    def _tick() -> None:
        if state["done"]:
            if state["ok"]:
                win.destroy()
            elif state["error"]:
                _show_error(state["error"])
            else:
                win.destroy()
            return
        # live progress detail (file count growing in the study cache)
        status = state.get("status") or ""
        sd = state.get("study_dir") or ""
        if sd and ("Copying images" in status):
            try:
                n, _b = dir_stats(sd)
                status = f"Copying images… {n} files"
            except Exception:
                pass
        detail.configure(text=status)
        win.after(200, _tick)

    win.after(150, _tick)
    win.mainloop()
    return 0


def main() -> int:
    root = _media_root()
    try:
        return _run_with_splash(root)
    except Exception:
        # No GUI available — do the work headless so the viewer still opens.
        state: dict = {"done": False, "ok": False, "error": "", "status": "", "study_dir": ""}
        _prepare(root, state)
        return 0 if state.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
