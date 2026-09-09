"""Bounded build subprocesses; fatal compiler errors cannot leave a live waiter."""
from __future__ import annotations

import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

FATAL_MEMORY = re.compile(r"^\s*MemoryError(?:\s|:|$)|fatal error C(?:1001|1002|1060):", re.I)


def terminate_owned_process(process):
    """Only terminate the child we created and its descendants, never a name match."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
    else:
        process.kill()
    process.wait(timeout=30)


def run_logged_build(command, *, cwd, log_path, env=None, timeout_seconds=8 * 3600,
                     idle_timeout_seconds=4 * 3600, on_start=None):
    if timeout_seconds <= 0 or idle_timeout_seconds <= 0:
        raise ValueError("Build timeouts must be positive")
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    child_env = dict(os.environ if env is None else env, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    process = subprocess.Popen(command, cwd=cwd, env=child_env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                               errors="replace", bufsize=1,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    events = queue.Queue()

    def read_output():
        try:
            for line in process.stdout:
                events.put(("line", line))
        finally:
            events.put(("end", ""))

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    started = last_output = time.monotonic()
    failure = 0
    try:
        if on_start is not None:
            on_start(process.pid)
        with log_path.open("a", encoding="utf-8") as log:
            while True:
                now = time.monotonic()
                if now - started > timeout_seconds or now - last_output > idle_timeout_seconds:
                    log.write("[FAIL] Build exceeded its execution or output-idle timeout\n")
                    failure = 124
                    break
                try:
                    kind, line = events.get(timeout=0.2)
                except queue.Empty:
                    continue
                if kind == "end":
                    break
                last_output = time.monotonic()
                log.write(line)
                log.flush()
                try:
                    print(line, end="", flush=True)
                except UnicodeEncodeError:
                    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
                    escaped = line.encode(encoding, errors="backslashreplace").decode(encoding)
                    print(escaped, end="", flush=True)
                if FATAL_MEMORY.search(line):
                    log.write("[FAIL] Fatal compiler memory error; terminating owned build process tree\n")
                    failure = 1
                    break
            if failure:
                terminate_owned_process(process)
            else:
                try:
                    process.wait(timeout=max(1, timeout_seconds - (time.monotonic() - started)))
                except subprocess.TimeoutExpired:
                    failure = 124
                    terminate_owned_process(process)
            result = failure or process.returncode
            log.write(f"[EXIT_CODE] {result}\n")
            return result
    finally:
        terminate_owned_process(process)
        reader.join(timeout=5)
        if not reader.is_alive():
            process.stdout.close()
