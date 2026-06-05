# -*- coding: utf-8 -*-
"""App lifecycle automation for the aipacs-control MCP.

Standard launch/control workflow as MCP-callable functions:
launch (SOURCE build only) → dismiss startup notifications (e.g. the
low-disk-space alert → OK) → login (saved credentials pre-filled → Sign In)
→ move between monitors → confirm ready (test-server ping).

Implementation notes
--------------------
* Launch env is rebuilt from Win32/registry, NOT inherited blindly: agent
  shells miss WINDIR (qtawesome startup crash) and registry Machine scope
  carries USERNAME=SYSTEM (license hardware-id + test-socket name drift).
  COMPUTERNAME/USERNAME come from Win32 APIs, windir from
  GetWindowsDirectoryW.
* Dialog/login handling uses pywinauto UIA with the Invoke pattern
  (`.invoke()`), i.e. no synthetic mouse movement — it cannot collide with a
  concurrently running pointer-based test.
* HARD RULE: only `<repo>\\.venv\\Scripts\\python.exe main.py` is ever
  launched — never the frozen executable.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

REPO = Path(r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version")
VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"

APP_TITLE_FRAGMENT = "AIPacs"           # source-build main window title
DIALOG_TITLE_FRAGMENTS = (
    "Disk Space Alert",                  # low-disk warning → OK
    "Warning - AIPacs",
    "Notice - AIPacs",
)
LOGIN_BUTTON_TITLES = ("Sign In", "Sign in", "Login", "ورود")
DIALOG_OK_TITLES = ("OK", "Ok", "تایید")


# ── env construction ─────────────────────────────────────────────────
def build_launch_env() -> dict:
    env = dict(os.environ)
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.kernel32.GetWindowsDirectoryW(buf, 260)
    windir = buf.value or r"C:\Windows"
    env["SystemRoot"] = windir
    env["windir"] = windir
    env["WINDIR"] = windir
    env["SystemDrive"] = windir[:2]
    env.setdefault("ProgramFiles", windir[:2] + r"\Program Files")
    # Registry Machine + User env (PATH etc.), with the common expansions.
    try:
        import winreg
        for hive, path in (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, "Environment"),
        ):
            try:
                key = winreg.OpenKey(hive, path)
            except OSError:
                continue
            i = 0
            while True:
                try:
                    name, val, _typ = winreg.EnumValue(key, i)
                    i += 1
                except OSError:
                    break
                if not isinstance(val, str):
                    continue
                val = (val.replace("%SystemRoot%", windir)
                          .replace("%SYSTEMROOT%", windir)
                          .replace("%SystemDrive%", windir[:2]))
                if name.upper() == "PATH" and "PATH" in {k.upper() for k in env}:
                    cur = env.get("Path") or env.get("PATH") or ""
                    merged = cur + (";" if cur and not cur.endswith(";") else "") + val
                    env["Path"] = merged
                    continue
                env.setdefault(name, val)
    except Exception:
        pass
    # Identity vars from Win32 (NOT from a possibly-stripped env).
    try:
        import win32api  # pywin32 (pywinauto dependency)
        env["COMPUTERNAME"] = win32api.GetComputerName()
        env["USERNAME"] = win32api.GetUserName()
    except Exception:
        env.setdefault("COMPUTERNAME", os.environ.get("COMPUTERNAME", ""))
    env["AIPACS_TEST_SERVER"] = "1"
    sock = os.environ.get("AIPACS_TEST_SOCKET", "").strip()
    if sock:
        env["AIPACS_TEST_SOCKET"] = sock
    return env


# ── process discovery ────────────────────────────────────────────────
def find_app_processes() -> list[dict]:
    import psutil
    out = []
    for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            if not (p.info["name"] or "").lower().startswith("python"):
                continue
            cmd = " ".join(p.info["cmdline"] or [])
            if "main.py" in cmd and "ai-pacs" in cmd.lower() or (
                    "main.py" in cmd and str(REPO).lower() in cmd.lower()):
                out.append({"pid": p.info["pid"], "cmdline": cmd[:160],
                            "create_time": p.info["create_time"]})
        except Exception:
            continue
    return out


def _ping_test_server(timeout_ms: int = 1500) -> bool:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from client import AipacsControlClient
        c = AipacsControlClient(connect_timeout_ms=timeout_ms)
        ok = bool(c.send("ping", timeout_ms=timeout_ms).get("ok"))
        c.close()
        return ok
    except Exception:
        return False


# ── window helpers (pywinauto UIA) ───────────────────────────────────
def _desktop():
    from pywinauto import Desktop
    return Desktop(backend="uia")


def _app_windows():
    """Top-level windows belonging to the source-build app (by pid match)."""
    pids = {p["pid"] for p in find_app_processes()}
    wins = []
    try:
        for w in _desktop().windows():
            try:
                if w.process_id() in pids:
                    wins.append(w)
            except Exception:
                continue
    except Exception:
        pass
    return wins


def _buttons(window) -> list:
    """All Button descendants of a UIAWrapper window (wrapper-safe)."""
    try:
        return window.descendants(control_type="Button")
    except Exception:
        return []


def _invoke_button(window, titles) -> Optional[str]:
    wanted = {t.strip().lower() for t in titles}
    for btn in _buttons(window):
        try:
            name = (btn.window_text() or "").strip()
        except Exception:
            continue
        if name.lower() not in wanted:
            continue
        try:
            btn.invoke()                                # UIA Invoke — no mouse
        except Exception:
            try:
                btn.click_input()                       # fallback: real click
            except Exception:
                continue
        return name
    return None


def dismiss_startup_dialogs() -> dict:
    """Find known startup notification dialogs and press their OK button."""
    dismissed = []
    for w in _app_windows():
        try:
            title = w.window_text() or ""
        except Exception:
            continue
        if any(f in title for f in DIALOG_TITLE_FRAGMENTS):
            hit = _invoke_button(w, DIALOG_OK_TITLES)
            if hit:
                dismissed.append({"window": title, "button": hit})
    return {"ok": True, "dismissed": dismissed}


def do_login(username: str = "", password: str = "") -> dict:
    """Click Sign In on the login screen.

    Credentials are normally pre-filled (saved login). When *username* /
    *password* are given (or AIPACS_TEST_USER / AIPACS_TEST_PASS are set),
    they are typed into the edit fields first.
    """
    username = username or os.environ.get("AIPACS_TEST_USER", "")
    password = password or os.environ.get("AIPACS_TEST_PASS", "")
    wanted = {t.strip().lower() for t in LOGIN_BUTTON_TITLES}
    for w in _app_windows():
        try:
            has_btn = any(
                (b.window_text() or "").strip().lower() in wanted
                for b in _buttons(w)
            )
        except Exception:
            has_btn = False
        if not has_btn:
            continue
        try:
            if username or password:
                edits = w.descendants(control_type="Edit")
                if username and len(edits) >= 1:
                    edits[0].set_edit_text(username)
                if password and len(edits) >= 2:
                    edits[1].set_edit_text(password)
        except Exception:
            pass
        hit = _invoke_button(w, LOGIN_BUTTON_TITLES)
        if hit:
            return {"ok": True, "clicked": hit, "window": w.window_text()}
    return {"ok": False, "error_code": "LOGIN_WINDOW_NOT_FOUND",
            "message": "no window with a Sign In button"}


# ── monitors ─────────────────────────────────────────────────────────
def list_monitors() -> list[dict]:
    import win32api
    out = []
    for i, (hmon, _hdc, rect) in enumerate(win32api.EnumDisplayMonitors(None, None)):
        try:
            info = win32api.GetMonitorInfo(hmon)
            work = info.get("Work", rect)
            out.append({
                "index": i,
                "letter": chr(ord("A") + i),
                "device": info.get("Device", f"monitor{i}"),
                "primary": bool(info.get("Flags", 0) & 1),
                "rect": list(rect),
                "work": list(work),
            })
        except Exception:
            out.append({"index": i, "letter": chr(ord("A") + i), "rect": list(rect)})
    return out


def move_app_to_monitor(monitor: str = "A", maximize: bool = True) -> dict:
    """Move the app main window to a monitor ('A'/'B'/... or an index)."""
    import win32con
    import win32gui
    mons = list_monitors()
    sel = None
    m = str(monitor).strip().upper()
    for entry in mons:
        if m in (entry["letter"], str(entry["index"])) or m == str(entry.get("device", "")).upper():
            sel = entry
            break
    if sel is None:
        return {"ok": False, "error_code": "BAD_MONITOR",
                "message": f"monitor '{monitor}' not found", "monitors": mons}
    # Pick the largest app window (main window, not a dialog).
    target, area = None, -1
    for w in _app_windows():
        try:
            r = w.rectangle()
            a = max(0, r.width()) * max(0, r.height())
            if a > area:
                target, area = w, a
        except Exception:
            continue
    if target is None:
        return {"ok": False, "error_code": "NO_APP_WINDOW", "message": "app window not found"}
    hwnd = target.handle
    x0, y0, x1, y1 = sel.get("work", sel["rect"])
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(hwnd, 0, x0, y0, x1 - x0, y1 - y0,
                              win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        if maximize:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    except Exception as exc:
        return {"ok": False, "error_code": "MOVE_FAILED", "message": str(exc)}
    return {"ok": True, "moved_to": sel, "window": target.window_text()}


# ── lifecycle ────────────────────────────────────────────────────────
def app_status() -> dict:
    procs = find_app_processes()
    titles = []
    for w in _app_windows():
        try:
            t = w.window_text()
            if t:
                titles.append(t)
        except Exception:
            pass
    return {"ok": True, "processes": procs, "windows": titles,
            "test_server_ready": _ping_test_server()}


def wait_until_ready(timeout_s: int = 240, login_user: str = "",
                     login_pass: str = "") -> dict:
    """Drive startup to readiness: dismiss dialogs → login → test-server ping."""
    t0 = time.monotonic()
    log: list[str] = []
    login_done = False
    while time.monotonic() - t0 < timeout_s:
        if _ping_test_server():
            return {"ok": True, "ready_after_s": round(time.monotonic() - t0, 1),
                    "log": log}
        d = dismiss_startup_dialogs()
        for item in d.get("dismissed", []):
            log.append(f"dismissed: {item['window']}")
        if not login_done:
            res = do_login(login_user, login_pass)
            if res.get("ok"):
                log.append(f"login clicked ({res['clicked']})")
                login_done = True
        time.sleep(2.0)
    return {"ok": False, "error_code": "READY_TIMEOUT",
            "message": f"not ready within {timeout_s}s", "log": log}


def launch_app(wait_ready_s: int = 240, monitor: str = "",
               login_user: str = "", login_pass: str = "") -> dict:
    """Launch the SOURCE build with the test server enabled and drive it to
    ready. Refuses when an instance is already running (use stop_app first)."""
    existing = find_app_processes()
    if existing:
        return {"ok": False, "error_code": "ALREADY_RUNNING",
                "message": "an instance is already running (single-instance app)",
                "processes": existing}
    if not VENV_PY.exists():
        return {"ok": False, "error_code": "NO_VENV", "message": str(VENV_PY)}
    env = build_launch_env()
    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [str(VENV_PY), "main.py"], cwd=str(REPO), env=env,
        creationflags=DETACHED, close_fds=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    result: dict[str, Any] = {"launched_pid": proc.pid}
    ready = wait_until_ready(wait_ready_s, login_user, login_pass)
    result.update(ready)
    if ready.get("ok") and monitor:
        result["move"] = move_app_to_monitor(monitor)
    return result


def stop_app(force: bool = False, timeout_s: int = 25) -> dict:
    """Close the app (graceful WM_CLOSE first; kill on timeout or force)."""
    import psutil
    procs = find_app_processes()
    if not procs:
        return {"ok": True, "message": "not running"}
    if not force:
        for w in _app_windows():
            try:
                w.close()
            except Exception:
                pass
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            if not find_app_processes():
                return {"ok": True, "message": "closed gracefully"}
            time.sleep(1.0)
    for p in find_app_processes():
        try:
            psutil.Process(p["pid"]).kill()
        except Exception:
            pass
    time.sleep(1.5)
    left = find_app_processes()
    return {"ok": not left, "message": "killed", "remaining": left}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    fn = {
        "status": app_status, "launch": launch_app, "stop": stop_app,
        "dialogs": dismiss_startup_dialogs, "login": do_login,
        "monitors": list_monitors, "ready": wait_until_ready,
        "move": move_app_to_monitor,
    }.get(cmd)
    # Args as key=value pairs (shell-safe), e.g.:  launch monitor=A wait_ready_s=200
    arg: dict[str, Any] = {}
    for tok in sys.argv[2:]:
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        if v.lower() in ("true", "false"):
            arg[k] = v.lower() == "true"
        else:
            try:
                arg[k] = int(v)
            except ValueError:
                arg[k] = v
    print(json.dumps(fn(**arg) if fn else {"error": f"unknown cmd {cmd}"},
                     indent=2, default=str))
