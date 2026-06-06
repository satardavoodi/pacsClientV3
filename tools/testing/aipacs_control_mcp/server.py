# -*- coding: utf-8 -*-
"""aipacs-control — MCP server for direct AI-PACS application control.

Bridges MCP tools → the in-app Test Control Server (QLocalServer, enabled by
launching AI-PACS with ``AIPACS_TEST_SERVER=1``) → the EchoMind CommandBus →
real application functions. See docs/reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md.

Run (Claude Desktop / any MCP client), using the app venv python:
    E:\\...\\.venv\\Scripts\\python.exe tools/testing/aipacs_control_mcp/server.py

Requires: ``pip install mcp`` into the app venv (PySide6 already present).
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from client import AipacsControlClient  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _exc:  # pragma: no cover
    raise SystemExit(
        "The 'mcp' package is missing. Install it into the app venv:\n"
        '  & "<repo>\\.venv\\Scripts\\python.exe" -m pip install mcp'
    ) from _exc

mcp = FastMCP("aipacs-control")

SESSIONS_DIR = _HERE / "sessions"
SCENARIOS_DIR = _HERE / "scenarios"

_client: Optional[AipacsControlClient] = None
_session_path: Optional[Path] = None


# ── plumbing ─────────────────────────────────────────────────────────
def _get_client() -> AipacsControlClient:
    global _client
    if _client is None:
        _client = AipacsControlClient()
    return _client


def _record(kind: str, payload: dict) -> None:
    global _session_path
    try:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        if _session_path is None:
            _session_path = SESSIONS_DIR / f"session_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        with open(_session_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, **payload},
                               default=str, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _send(action: str, entities: Optional[dict] = None, timeout_ms: int = 30000) -> dict:
    t0 = time.perf_counter()
    try:
        result = _get_client().send(action, entities or {}, timeout_ms=timeout_ms)
    except Exception as exc:
        global _client
        _client = None  # force reconnect next call
        result = {"ok": False, "action": action, "error_code": "TRANSPORT", "message": str(exc)}
    result["client_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    _record("command", {"action": action, "entities": entities or {}, "result": result})
    return result


def _j(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


# ── basic tools ──────────────────────────────────────────────────────
@mcp.tool()
def ping() -> str:
    """Check connectivity to the running AI-PACS test server."""
    return _j(_send("ping"))


@mcp.tool()
def list_actions() -> str:
    """List every command the in-app bus currently exposes."""
    return _j(_send("list_actions"))


@mcp.tool()
def raw_command(action: str, entities_json: str = "{}") -> str:
    """Send any bus action with a JSON entities object (escape hatch)."""
    return _j(_send(action, json.loads(entities_json or "{}")))


# ── workflow tools (requested command set) ───────────────────────────
@mcp.tool()
def open_patient(patient_id: str, patient_name: str = "", study_uid: str = "") -> str:
    """OpenPatient: open a patient tab via the real double-click handler."""
    ent: dict[str, Any] = {"patient_id": patient_id}
    if patient_name:
        ent["patient_name"] = patient_name
    if study_uid:
        ent["study_uid"] = study_uid
    return _j(_send("open_patient", ent, timeout_ms=60000))


@mcp.tool()
def select_patient(patient_id: str, patient_name: str = "", study_uid: str = "") -> str:
    """Single-click selection (real handler): marks selection + loads the
    home right-panel thumbnails via the fast-cache gate. Name/uid auto-resolve
    from the last search when omitted."""
    ent: dict[str, Any] = {"patient_id": patient_id}
    if patient_name:
        ent["patient_name"] = patient_name
    if study_uid:
        ent["study_uid"] = study_uid
    return _j(_send("select_patient", ent, timeout_ms=60000))


@mcp.tool()
def list_patients(limit: int = 25) -> str:
    """List patients currently shown on the home table."""
    return _j(_send("list_patients", {"limit": limit}))


@mcp.tool()
def drag_series(series_number: int, viewport: int = 0) -> str:
    """DragSeries (T1): load a series into a viewport via the exact function a
    real drop defers to (change_series_on_viewer). Async — pair with
    query_viewport_state to observe the load."""
    return _j(_send("change_series", {"series_number": series_number, "viewport": viewport}))


@mcp.tool()
def open_mpr(layout: str = "", preset: str = "") -> str:
    """OpenMPR: open MPR on the active viewer (real toggle_zeta_mpr route)."""
    ent: dict[str, Any] = {}
    if layout:
        ent["layout"] = layout
    if preset:
        ent["preset"] = preset
    return _j(_send("open_mpr", ent, timeout_ms=120000))


@mcp.tool()
def close_patient_tab(index: int = -1) -> str:
    """ClosePatient: emit tabCloseRequested (the real X-button path).
    index=-1 closes the active patient tab."""
    ent = {} if index < 0 else {"index": index}
    return _j(_send("close_patient_tab", ent))


@mcp.tool()
def switch_tab(index: int) -> str:
    """Switch the main tab widget to the given index (tab churn primitive)."""
    return _j(_send("switch_tab", {"index": index}))


@mcp.tool()
def trigger_download(patient_id: str) -> str:
    """TriggerDownload (study-level): enqueue the patient's study downloads."""
    return _j(_send("download_patient", {"patient_id": patient_id}, timeout_ms=60000))


@mcp.tool()
def query_download_state(study_uid: str = "") -> str:
    """QueryDownloadState: one study's status, or all downloads when empty."""
    if study_uid:
        return _j(_send("check_download_status", {"study_uid": study_uid}))
    return _j(_send("list_downloads", {}))


@mcp.tool()
def wait_for_download(study_uid: str, timeout_s: int = 300, poll_ms: int = 1000) -> str:
    """WaitForDownload: poll until the study reaches a terminal state."""
    deadline = time.monotonic() + timeout_s
    last: dict = {}
    while time.monotonic() < deadline:
        last = _send("check_download_status", {"study_uid": study_uid})
        status = str(((last.get("data") or {}) or {}).get("status", "")).lower()
        if status in ("completed", "complete", "done", "failed", "cancelled", "canceled"):
            return _j({"ok": status.startswith("comp") or status == "done",
                       "final_status": status, "last": last})
        time.sleep(max(poll_ms, 100) / 1000.0)
    return _j({"ok": False, "error_code": "TIMEOUT", "last": last})


@mcp.tool()
def query_viewport_state() -> str:
    """QueryViewportState: per-viewport series/slices/awaiting/progressive/spinner."""
    return _j(_send("query_viewport_state", {}))


@mcp.tool()
def query_thumbnail_state() -> str:
    """QueryThumbnailState: the active tab's series/thumbnail metadata."""
    return _j(_send("get_thumbnails_data", {}))


@mcp.tool()
def snapshot_health(since_minutes: int = 10) -> str:
    """SnapshotHealth: resources + native-fault count — the pass/fail probe."""
    res = _send("snapshot_resources", {})
    faults = _send("count_native_faults_since", {"minutes": since_minutes})
    return _j({"resources": res, "native_faults": faults})


# ── pressure tools ───────────────────────────────────────────────────
@mcp.tool()
def burst(commands_json: str, interval_ms: int = 0, seed: int = 0) -> str:
    """Fire a list of commands back-to-back (interval_ms apart, 0 = as fast as
    the pipe allows; they queue one-per-event-loop-turn inside the app).
    commands_json: JSON array of {"action": str, "entities": {...}}.
    Returns per-command results once all have answered."""
    cmds = json.loads(commands_json)
    rng = random.Random(seed) if seed else None
    client = _get_client()
    ids: list[int] = []
    t0 = time.perf_counter()
    for i, cmd in enumerate(cmds):
        ids.append(client.fire(str(cmd.get("action")), cmd.get("entities") or {}))
        if interval_ms and i < len(cmds) - 1:
            jitter = rng.uniform(0.8, 1.2) if rng else 1.0
            time.sleep(interval_ms * jitter / 1000.0)
    sent_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    results = client.drain(ids, timeout_ms=120000)
    ordered = [results.get(i, {"ok": False, "error_code": "NO_REPLY", "id": i}) for i in ids]
    summary = {"sent": len(cmds), "answered": len(results), "send_window_ms": sent_ms,
               "failed": sum(1 for r in ordered if not r.get("ok")), "results": ordered}
    _record("burst", {"commands": cmds, "summary": {k: summary[k] for k in
                                                    ("sent", "answered", "send_window_ms", "failed")}})
    return _j(summary)


@mcp.tool()
def run_scenario(path: str, seed: int = 0, loops: int = 0) -> str:
    """Run a scenario file (JSON). Steps: {"action", "entities", "after_ms"}
    plus pseudo-actions: wait_ms {ms}, wait_for_download {study_uid,timeout_s},
    assert_health {max_new_native_faults}. 'loops' overrides the file's loop
    count. Relative paths resolve against the scenarios/ folder. Returns a
    summary; full timeline goes to the session JSONL."""
    p = Path(path)
    if not p.is_absolute():
        p = SCENARIOS_DIR / path
    spec = json.loads(p.read_text(encoding="utf-8"))
    rng = random.Random(seed or spec.get("seed", 0))
    n_loops = loops or int(spec.get("loop", 1))
    steps = spec.get("steps", [])
    baseline = _send("count_native_faults_since", {"minutes": 1})
    failures: list[dict] = []
    executed = 0
    t_start = time.perf_counter()
    for loop_i in range(n_loops):
        for step in steps:
            action = str(step.get("action"))
            ent = dict(step.get("entities") or {})
            delay = step.get("after_ms", 0)
            if isinstance(delay, list) and len(delay) == 2:  # [min,max] jittered
                delay = rng.uniform(delay[0], delay[1])
            if delay:
                time.sleep(float(delay) / 1000.0)
            if action == "wait_ms":
                time.sleep(float(ent.get("ms", 100)) / 1000.0)
                continue
            if action == "wait_for_download":
                json.loads(wait_for_download(str(ent.get("study_uid", "")),
                                             int(ent.get("timeout_s", 120))))
                executed += 1
                continue
            if action == "assert_health":
                h = _send("count_native_faults_since", {"minutes": 30})
                executed += 1
                continue
            res = _send(action, ent, timeout_ms=int(step.get("timeout_ms", 60000)))
            executed += 1
            if not res.get("ok") and not step.get("allow_fail", False):
                failures.append({"loop": loop_i, "action": action,
                                 "error": res.get("error_code"), "message": res.get("message")})
    total_ms = round((time.perf_counter() - t_start) * 1000.0, 1)
    health = _send("count_native_faults_since", {"minutes": max(1, int(total_ms / 60000) + 2)})
    summary = {"scenario": spec.get("name", p.stem), "loops": n_loops,
               "steps_executed": executed, "total_ms": total_ms,
               "failures": failures, "native_faults_after": health.get("data"),
               "session_log": str(_session_path or "")}
    _record("scenario_summary", summary)
    return _j(summary)


# ── app lifecycle tools (launch / dialogs / login / monitors / ready) ─
@mcp.tool()
def launch_app(monitor: str = "", wait_ready_s: int = 240) -> str:
    """Launch the AI-PACS SOURCE build with the test server enabled, dismiss
    startup notifications (e.g. the low-disk-space alert), click Sign In
    (saved credentials), optionally move to a monitor ('A'/'B'/index), and
    wait until the test server answers. Refuses if already running."""
    import lifecycle
    res = lifecycle.launch_app(wait_ready_s=wait_ready_s, monitor=monitor)
    _record("lifecycle", {"tool": "launch_app", "result": res})
    return _j(res)


@mcp.tool()
def stop_app(force: bool = False) -> str:
    """Close the app (graceful first; force-kill when force=True)."""
    import lifecycle
    res = lifecycle.stop_app(force=force)
    _record("lifecycle", {"tool": "stop_app", "result": res})
    return _j(res)


@mcp.tool()
def app_status() -> str:
    """Processes, top-level windows, and test-server readiness."""
    import lifecycle
    return _j(lifecycle.app_status())


@mcp.tool()
def wait_app_ready(timeout_s: int = 240) -> str:
    """Drive a starting app to readiness: dismiss notification dialogs,
    click Sign In, then wait for the test-server ping."""
    import lifecycle
    return _j(lifecycle.wait_until_ready(timeout_s=timeout_s))


@mcp.tool()
def dismiss_startup_dialogs() -> str:
    """Detect known startup notifications (Disk Space Alert, …) and press OK."""
    import lifecycle
    return _j(lifecycle.dismiss_startup_dialogs())


@mcp.tool()
def login(username: str = "", password: str = "") -> str:
    """Click Sign In on the login screen (saved credentials are pre-filled;
    optional username/password are typed first, or AIPACS_TEST_USER/PASS)."""
    import lifecycle
    return _j(lifecycle.do_login(username, password))


@mcp.tool()
def list_monitors() -> str:
    """List monitors as A/B/… with geometry and primary flag."""
    import lifecycle
    return _j(lifecycle.list_monitors())


@mcp.tool()
def move_app_to_monitor(monitor: str = "A", maximize: bool = True) -> str:
    """Move the app main window to monitor 'A'/'B'/… (or an index)."""
    import lifecycle
    res = lifecycle.move_app_to_monitor(monitor, maximize=maximize)
    _record("lifecycle", {"tool": "move_app_to_monitor", "result": res})
    return _j(res)


if __name__ == "__main__":
    mcp.run()
