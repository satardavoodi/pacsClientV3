"""
Safe, env-gated COM call-site tracer — diagnoses the 0x8001010d
(RPC_E_WRONGTHREAD) first-chance fault by logging every *Python-initiated* COM
call with its thread, COM apartment, and Python stack.

READ-ONLY: it only logs; it never changes app behaviour. When the env var is
unset (the default), install() is a no-op.

Enable:   set AIPACS_COM_TRACE=1   then launch the app and reproduce the fault.
Output:   user_data/logs/com_trace.log

How to read it: when native_fault.log gains a `0x8001010d` entry, the LAST
`[COM-TRACE]` line in com_trace.log just before it is the culprit. Its
`thread=` / `apartment=` reveal the wrong-thread call (e.g. a COM object created
on the STA main thread but called from an MTA worker). If com_trace.log shows NO
COM call near the fault, the COM is native (Qt OLE/drag-drop, a C-extension) —
which itself rules out the Python layer and points the investigation at Qt.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import traceback

_installed = False
_log = logging.getLogger("aipacs.com_trace")


def _enabled() -> bool:
    return os.getenv("AIPACS_COM_TRACE", "").strip() in ("1", "true", "True", "yes", "on")


def _apartment_str() -> str:
    """Current thread's COM apartment (STA / MTA / NA / MAIN_STA), best-effort."""
    names = {0: "STA", 1: "MTA", 2: "NA", 3: "MAIN_STA"}
    try:
        import pythoncom  # type: ignore
        t, _q = pythoncom.CoGetApartmentType()
        return names.get(t, "type%s" % t)
    except Exception:
        pass
    try:
        import ctypes
        apt = ctypes.c_int(-1)
        qual = ctypes.c_int(-1)
        hr = ctypes.windll.ole32.CoGetApartmentType(ctypes.byref(apt), ctypes.byref(qual))
        if hr == 0:
            return names.get(apt.value, "type%s" % apt.value)
        return "hr=%#x" % (hr & 0xFFFFFFFF)
    except Exception:
        return "?"


def _record(label: str) -> None:
    try:
        th = threading.current_thread()
        # Drop the last frame (this wrapper) so the top is the real call site.
        stack = "".join(traceback.format_stack(limit=16)[:-1])
        _log.warning(
            "[COM-TRACE] call=%s thread=%s native_id=%s apartment=%s\n%s",
            label, th.name, getattr(th, "native_id", None), _apartment_str(), stack,
        )
    except Exception:
        pass


def _wrap(owner, attr: str, label: str) -> None:
    try:
        orig = getattr(owner, attr, None)
        if orig is None or getattr(orig, "_com_traced", False):
            return

        def wrapper(*a, **k):
            _record(label)
            return orig(*a, **k)

        wrapper._com_traced = True  # type: ignore[attr-defined]
        try:
            wrapper.__name__ = getattr(orig, "__name__", attr)
            wrapper.__doc__ = getattr(orig, "__doc__", None)
        except Exception:
            pass
        setattr(owner, attr, wrapper)
        _log.info("[COM-TRACE] wrapped %s", label)
    except Exception:
        pass


def _setup_file_handler() -> None:
    try:
        from PacsClient.utils.data_paths import LOGS_DIR  # type: ignore
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(LOGS_DIR / "com_trace.log"), encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
        _log.addHandler(fh)
        _log.setLevel(logging.INFO)
        _log.propagate = False
    except Exception:
        pass


def install() -> None:
    """Wrap Python COM entry points to trace calls. No-op unless AIPACS_COM_TRACE=1."""
    global _installed
    if _installed or not _enabled():
        return
    _installed = True
    _setup_file_handler()
    try:
        _log.warning(
            "[COM-TRACE] install: main_thread apartment=%s native_id=%s python=%s",
            _apartment_str(), getattr(threading.current_thread(), "native_id", None),
            sys.version.split()[0],
        )
    except Exception:
        pass

    # pywin32 core
    try:
        import pythoncom  # type: ignore
        for a, lbl in (
            ("CoInitialize", "pythoncom.CoInitialize"),
            ("CoInitializeEx", "pythoncom.CoInitializeEx"),
            ("CoCreateInstance", "pythoncom.CoCreateInstance"),
            ("CoCreateInstanceEx", "pythoncom.CoCreateInstanceEx"),
            ("CoGetObject", "pythoncom.CoGetObject"),
        ):
            _wrap(pythoncom, a, lbl)
    except Exception:
        pass

    # win32com.client
    try:
        import win32com.client as _wc  # type: ignore
        for a, lbl in (
            ("Dispatch", "win32com.Dispatch"),
            ("DispatchEx", "win32com.DispatchEx"),
            ("GetObject", "win32com.GetObject"),
            ("GetActiveObject", "win32com.GetActiveObject"),
        ):
            _wrap(_wc, a, lbl)
    except Exception:
        pass

    # comtypes
    try:
        import comtypes  # type: ignore
        for a, lbl in (("CoInitialize", "comtypes.CoInitialize"),
                       ("CoCreateInstance", "comtypes.CoCreateInstance")):
            _wrap(comtypes, a, lbl)
        import comtypes.client as _cc  # type: ignore
        for a, lbl in (("CreateObject", "comtypes.CreateObject"),
                       ("GetActiveObject", "comtypes.GetActiveObject"),
                       ("GetModule", "comtypes.GetModule")):
            _wrap(_cc, a, lbl)
    except Exception:
        pass

    # wmi convenience module
    try:
        import wmi  # type: ignore
        _wrap(wmi, "WMI", "wmi.WMI")
    except Exception:
        pass

    # audio COM (WASAPI) — only if already imported (avoid forcing the import)
    try:
        if "sounddevice" in sys.modules:
            import sounddevice as _sd  # type: ignore
            for a, lbl in (("query_devices", "sounddevice.query_devices"),
                           ("play", "sounddevice.play")):
                _wrap(_sd, a, lbl)
    except Exception:
        pass

    _log.warning("[COM-TRACE] installed — tracing Python COM entry points")
