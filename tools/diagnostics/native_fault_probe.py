"""Bounded, external-process native evidence probes (never a Qt bus handler).

Legacy faulthandler records have no per-event timestamp or trustworthy process
ownership. Compare append-only bytes from a real baseline, not file mtime or a
preceding session header. A recorded exception is not necessarily terminal.
Process-exclusive sinks carry filename identity. Keep the legacy sink as
unattributed history; discover new child sinks during a fixed observation window.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import time

from PacsClient.utils.native_fault_log import discover_native_fault_logs, native_fault_log_pid

MAX_LOG_BYTES = 16 * 1024 * 1024
_WINDOWS = re.compile(rb"^Windows fatal exception:", re.MULTILINE)
_PYTHON = re.compile(rb"^Fatal Python error:", re.MULTILINE)
_WATCHDOG = re.compile(rb"^Timeout \([^\r\n]*\)!", re.MULTILINE)
_COM = re.compile(rb"^Windows fatal exception:[^\r\n]*0x8001010d", re.MULTILINE)


def _read_log(path: Path) -> tuple[bytes, tuple[int, int]]:
    # Bound allocation and work even when the log has grown for months. Do not
    # silently truncate and turn missing evidence into a clean health receipt.
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > MAX_LOG_BYTES:
            raise ValueError("NATIVE_LOG_LIMIT")
        data = stream.read(before.st_size)
        after = os.fstat(stream.fileno())
        if len(data) != before.st_size or after.st_size < before.st_size:
            raise ValueError("NATIVE_LOG_CHANGED")
        if data and not data.endswith(b"\n"):
            raise ValueError("NATIVE_LOG_PARTIAL")
        return data, (before.st_dev, before.st_ino)


def _failure(code: str) -> dict:
    return {"ok": False, "error_code": code,
            "data": {"total": None, "verdict": "inconclusive"}}


def _error_code(exc: Exception) -> str:
    if isinstance(exc, FileNotFoundError):
        return "NATIVE_LOG_MISSING"
    if isinstance(exc, ValueError):
        return str(exc)
    # Do not return filesystem paths or native stack text through MCP.
    return "NATIVE_LOG_UNREADABLE"


def _counts(data: bytes) -> dict:
    windows = len(_WINDOWS.findall(data))
    python = len(_PYTHON.findall(data))
    return {"total": windows + python, "windows_exceptions": windows,
            "com_inhibit": len(_COM.findall(data)),
            "python_fatal_records": python,
            "watchdog_dumps": len(_WATCHDOG.findall(data)),
            "terminal_crash_count": None,
            "process_attribution": "unavailable_shared_log"}


class _FileWindow:
    """One fixed byte baseline; repeated checks are cumulative, not reset-on-read."""

    def __init__(self, path: Path, expected_pid: int | None = None, from_start: bool = False):
        self.path = Path(path)
        self.expected_pid = expected_pid
        self.started = time.monotonic()
        self.error = None
        try:
            data, self.identity = _read_log(self.path)
            if not data:
                raise ValueError("NATIVE_LOG_EMPTY")
            _validate_exclusive_header(self.path, data)
            if expected_pid is not None and not re.search(
                rb"^=== session start [^\r\n]*\bpid="
                + str(expected_pid).encode("ascii") + rb"\b", data, re.MULTILINE,
            ):
                # Presence proves only that capture started for this PID, NOT
                # ownership of subsequent interleaved exception records.
                raise ValueError("NATIVE_SESSION_UNVERIFIED")
            self.offset = 0 if from_start else len(data)
            self.last_size = len(data)
            self.last_digest = hashlib.sha256(data).digest()
        except (OSError, ValueError) as exc:
            self.error = _error_code(exc)

    def check(self) -> dict:
        if self.error:
            return _failure(self.error)
        try:
            data, identity = _read_log(self.path)
            _validate_exclusive_header(self.path, data)
            if (identity != self.identity or len(data) < self.last_size
                    or hashlib.sha256(data[:self.last_size]).digest() != self.last_digest):
                return _failure("NATIVE_LOG_REPLACED")
            delta = data[self.offset:]
            self.last_size = len(data)
            self.last_digest = hashlib.sha256(data).digest()
            return {"ok": True, "data": {
                **_counts(delta), "scope": "observed_byte_window",
                "bytes_read": len(data),
                "bytes_observed": len(delta),
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
            }}
        except (OSError, ValueError) as exc:
            return _failure(_error_code(exc))


def _validate_exclusive_header(path: Path, data: bytes) -> None:
    pid = native_fault_log_pid(path)
    if pid is None:
        return
    headers = re.findall(rb"^=== session start [^\r\n]*\bpid=(\d+)\b", data, re.MULTILINE)
    if headers != [str(pid).encode("ascii")]:
        raise ValueError("NATIVE_SESSION_UNVERIFIED")


def _sources(path: Path) -> list[Path]:
    # The legacy filename remains a compatible directory anchor for callers;
    # an explicitly named process log selects only that one source.
    if path.name == "native_fault.log":
        return discover_native_fault_logs(path.parent)
    return [path]


def _combine(samples: list[tuple[Path, dict]]) -> dict:
    fields = ("total", "windows_exceptions", "python_fatal_records", "watchdog_dumps", "com_inhibit")
    totals = {field: sum(data[field] for _, data in samples) for field in fields}
    legacy = any(native_fault_log_pid(path) is None for path, _ in samples)
    exclusive = any(native_fault_log_pid(path) is not None for path, _ in samples)
    return {**totals, "terminal_crash_count": None, "files_observed": len(samples),
            "process_attribution": ("mixed_exclusive_and_legacy" if exclusive and legacy else
                                    "process_exclusive_files" if exclusive else "unavailable_shared_log"),
            "process_records": [{"pid": native_fault_log_pid(path), "source_file": path.name,
                                 **{k: data[k] for k in fields}}
                                for path, data in samples]}


class NativeFaultWindow:
    """Fixed multi-file baseline. Disappearing sources fail; new child files count in full."""

    def __init__(self, path: Path, expected_pid: int | None = None):
        self.path = Path(path)
        self.expected_pid = expected_pid
        self.started = time.monotonic()
        self.error = None
        self.windows = {}
        try:
            paths = _sources(self.path)
            if not paths:
                raise ValueError("NATIVE_LOG_MISSING")
            verified = expected_pid is None
            size = 0
            for source in paths:
                window = _FileWindow(source)
                if window.error:
                    raise ValueError(window.error)
                size += window.offset
                if size > MAX_LOG_BYTES:
                    raise ValueError("NATIVE_LOG_LIMIT")
                self.windows[source] = window
                if expected_pid is not None:
                    owner = native_fault_log_pid(source)
                    if owner == expected_pid:
                        verified = True
                    elif owner is None:
                        # Only a presence check; never assign shared dumps to it.
                        verified = verified or _FileWindow(source, expected_pid).error is None
            if not verified:
                raise ValueError("NATIVE_SESSION_UNVERIFIED")
        except (OSError, ValueError) as exc:
            self.error = _error_code(exc)

    def check(self) -> dict:
        if self.error:
            return _failure(self.error)
        try:
            paths = _sources(self.path)
            if not set(self.windows).issubset(paths):
                raise ValueError("NATIVE_LOG_REPLACED")
            samples = []
            size = delta = 0
            for path in paths:
                if path not in self.windows:
                    candidate = _FileWindow(path, from_start=True)
                    if candidate.error:
                        return _failure(candidate.error)
                    self.windows[path] = candidate
                result = self.windows[path].check()
                if not result["ok"]:
                    return result
                data = result["data"]
                size += data["bytes_read"]
                delta += data["bytes_observed"]
                if size > MAX_LOG_BYTES:
                    raise ValueError("NATIVE_LOG_LIMIT")
                samples.append((path, data))
            return {"ok": True, "data": {**_combine(samples), "scope": "observed_byte_window",
                    "bytes_observed": delta, "elapsed_seconds": round(time.monotonic() - self.started, 3)}}
        except (OSError, ValueError) as exc:
            return _failure(_error_code(exc))


def native_fault_inventory(path: Path, requested_minutes: int) -> dict:
    """Historical inventory only: never certify a requested retrospective window."""
    try:
        paths = _sources(Path(path))
        if not paths:
            raise ValueError("NATIVE_LOG_MISSING")
        samples = []
        size = 0
        for source in paths:
            data, _ = _read_log(source)
            size += len(data)
            if size > MAX_LOG_BYTES:
                raise ValueError("NATIVE_LOG_LIMIT")
            _validate_exclusive_header(source, data)
            samples.append((source, _counts(data)))
        result = {"ok": True, "data": {**_combine(samples), "bytes_read": size}}
    except (OSError, ValueError) as exc:
        result = _failure(_error_code(exc))
    result["data"].update({
        "scope": "whole_file_inventory", "requested_minutes": requested_minutes,
        "requested_window_exact": False, "verdict": "inconclusive",
        "new_native_faults": None,
        "reason": "Untimed legacy records require a before/after byte baseline.",
    })
    return result
