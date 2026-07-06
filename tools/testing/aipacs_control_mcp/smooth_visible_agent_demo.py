# -*- coding: utf-8 -*-
r"""Smooth visible AI-PACS control demo.

This is intentionally paced for human observation. It focuses the app once,
then controls AI-PACS through the in-app CommandBus without repeated window
restore/maximize/focus calls. That avoids the blink/hiccup effect caused by
foreground-window manipulation before every action.

Run from the repo root:

    .\.venv\Scripts\python.exe tools\testing\aipacs_control_mcp\smooth_visible_agent_demo.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))

from client import AipacsControlClient  # noqa: E402


def _can_connect(timeout_ms: int = 1500) -> bool:
    try:
        c = AipacsControlClient(connect_timeout_ms=timeout_ms)
        try:
            return bool(c.send("ping", {}, timeout_ms=timeout_ms).get("ok"))
        finally:
            c.close()
    except Exception:
        return False


def _echomind_agent_runs_root() -> Path:
    try:
        sys.path.insert(0, str(REPO))
        from PacsClient.utils.data_paths import ECHOMIND_DIR
        root = Path(ECHOMIND_DIR)
    except Exception:
        root = REPO / "user_data" / "echomind"
    out = root / "agent_runs" / "smooth_visible_demo"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _yesterday_yyyymmdd() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")


def _rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data") or {}
    rows = data.get("rows") if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _modalities(row: dict[str, Any]) -> str:
    val = row.get("modalities", row.get("modality", ""))
    if isinstance(val, (list, tuple, set)):
        return ",".join(str(x) for x in val)
    return str(val or "")


def _patient_entities(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "patient_id": str(row.get("patient_id") or ""),
        "patient_name": str(row.get("patient_name") or ""),
        "study_uid": str(row.get("study_uid") or ""),
    }


def focus_once(maximize: bool = False) -> dict[str, Any]:
    """Bring the app forward once. No repeated focus during the workflow."""
    try:
        import win32con
        import win32gui
        from pywinauto import Desktop
        candidates = []
        for w in Desktop(backend="uia").windows():
            try:
                title = w.window_text() or ""
                if "AIPacs" not in title and "AI-PACS" not in title:
                    continue
                r = w.rectangle()
                candidates.append((r.width() * r.height(), w))
            except Exception:
                continue
        if not candidates:
            return {"ok": False, "error_code": "NO_WINDOW"}
        w = sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]
        hwnd = w.handle
        if maximize:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return {"ok": True, "title": w.window_text(), "pid": w.process_id()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error_code": "FOCUS_FAILED", "message": str(exc)}


class SmoothDemo:
    def __init__(self, client: AipacsControlClient, pause_s: float, out_dir: Path):
        self.client = client
        self.pause_s = max(0.2, float(pause_s))
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.commands_path = self.out / "commands.jsonl"
        self.conversation_path = self.out / "conversation.jsonl"
        self.report: dict[str, Any] = {
            "name": "smooth_visible_agent_demo",
            "started": datetime.now().isoformat(timespec="seconds"),
            "out_dir": str(self.out),
            "selected_patient": {},
            "selected_series": {},
            "steps": [],
            "status": "running",
        }
        self.write_report()

    def log(self, kind: str, payload: dict[str, Any]) -> None:
        rec = {"t": datetime.now().isoformat(timespec="seconds"), "kind": kind, **payload}
        with self.conversation_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def write_report(self) -> None:
        (self.out / "report.json").write_text(
            json.dumps(self.report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def send(self, action: str, entities: Optional[dict[str, Any]] = None,
             timeout_ms: int = 90000, pause_s: Optional[float] = None) -> dict[str, Any]:
        ent = entities or {}
        self.log("agent_says", {"text": f"Executing {action}", "action": action, "entities": ent})
        print(f"\n>>> {action} {json.dumps(ent, ensure_ascii=False)}", flush=True)
        result = self.client.send(action, ent, timeout_ms=timeout_ms)
        command_rec = {
            "action": action,
            "entities": ent,
            "reply": result,
        }
        with self.commands_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "t": datetime.now().isoformat(timespec="seconds"),
                **command_rec,
            }, ensure_ascii=False, default=str) + "\n")
        self.log("command", command_rec)
        self.report["steps"].append({
            "action": action,
            "ok": bool(result.get("ok")),
            "message": result.get("message"),
            "error_code": result.get("error_code"),
        })
        self.write_report()
        print(json.dumps({
            "ok": result.get("ok"),
            "action": result.get("action"),
            "message": result.get("message"),
            "error_code": result.get("error_code"),
            "elapsed_ms": result.get("elapsed_ms"),
        }, indent=2, ensure_ascii=False, default=str), flush=True)
        time.sleep(self.pause_s if pause_s is None else max(0.0, pause_s))
        return result

    def wait_for_series(self, timeout_s: float = 90.0) -> list[dict[str, Any]]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            result = self.client.send("get_series_info", {}, timeout_ms=30000)
            data = result.get("data") or {}
            series = data.get("series") or []
            if series:
                return [row for row in series if isinstance(row, dict)]
            time.sleep(1.5)
        return []

    def wait_for_stack(self, viewport: int, timeout_s: float = 90.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            result = self.client.send("query_viewport_state", {}, timeout_ms=30000)
            viewports = (result.get("data") or {}).get("viewports") or []
            for item in viewports:
                if int(item.get("viewport", -1)) == viewport and int(item.get("slice_count") or 0) > 0:
                    return item
            time.sleep(1.5)
        return {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", default=_yesterday_yyyymmdd(), help="study date YYYYMMDD")
    p.add_argument("--initial-modality", default="MR")
    p.add_argument("--target-modality", default="CT")
    p.add_argument("--patient-id", default="", help="optional fixed patient id")
    p.add_argument("--series-number", type=int, default=0, help="optional fixed series number")
    p.add_argument("--viewport", type=int, default=0)
    p.add_argument("--pause-s", type=float, default=2.5, help="human-observable pause between actions")
    p.add_argument("--out-dir", type=Path, help="artifact output directory")
    p.add_argument("--launch-app", action="store_true", help="launch AI-PACS with AIPACS_TEST_SERVER=1 before running")
    p.add_argument("--monitor", default="A", help="monitor letter/index for --launch-app")
    p.add_argument("--stop-existing", action="store_true", help="stop any existing source app before --launch-app")
    p.add_argument("--no-focus", action="store_true", help="do not focus the app window")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir or (_echomind_agent_runs_root() / time.strftime("%Y%m%d_%H%M%S"))
    launch_result: dict[str, Any] = {}
    if args.launch_app:
        import lifecycle
        if args.stop_existing:
            print("stop_existing:", json.dumps(
                lifecycle.stop_app(force=True, timeout_s=8),
                indent=2,
                default=str,
            ), flush=True)
        if not _can_connect():
            launch_result = lifecycle.launch_app(wait_ready_s=240, monitor=args.monitor)
            print("launch_app:", json.dumps(launch_result, indent=2, default=str), flush=True)
            if not launch_result.get("ok"):
                raise RuntimeError(
                    "Could not launch AI-PACS with test server. "
                    "If an old app is already running, rerun with --stop-existing --launch-app."
                )
    if not args.no_focus:
        focus = focus_once(maximize=False)
        print("focus_once:", json.dumps(focus, indent=2, default=str), flush=True)

    client = AipacsControlClient(connect_timeout_ms=5000)
    demo = SmoothDemo(client, pause_s=args.pause_s, out_dir=out_dir)
    demo.log("run_started", {
        "date": args.date,
        "initial_modality": args.initial_modality,
        "target_modality": args.target_modality,
        "out_dir": str(out_dir),
        "launch_app": bool(args.launch_app),
        "launch_result": launch_result,
    })
    if not args.no_focus:
        demo.log("focus_once", {"result": focus})
    try:
        demo.send("switch_tab", {"index": 0}, timeout_ms=30000, pause_s=args.pause_s)
        demo.send("list_patients", {
            "modality": args.initial_modality,
            "date_from": args.date,
            "date_to": args.date,
            "source": "server",
            "limit": 50,
        }, pause_s=args.pause_s * 1.8)
        target_list = demo.send("list_patients", {
            "modality": args.target_modality,
            "date_from": args.date,
            "date_to": args.date,
            "source": "server",
            "limit": 50,
        }, pause_s=args.pause_s * 1.8)
        candidates = [
            row for row in _rows(target_list)
            if args.target_modality.upper() in _modalities(row).upper()
        ]
        if args.patient_id:
            patient = next((row for row in _rows(target_list)
                            if str(row.get("patient_id")) == args.patient_id), None)
        else:
            candidates.sort(key=lambda row: -(int(row.get("series_count") or 0)))
            patient = candidates[0] if candidates else None
        if not patient:
            raise RuntimeError(f"No {args.target_modality} patient found for {args.date}")
        ent = _patient_entities(patient)
        print("selected_patient:", json.dumps(ent, ensure_ascii=False), flush=True)
        demo.report["selected_patient"] = ent
        demo.log("selection", {"selected_patient": ent})
        demo.write_report()
        demo.send("list_patients", {
            "patient_id": ent["patient_id"],
            "modality": args.target_modality,
            "date_from": args.date,
            "date_to": args.date,
            "source": "server",
            "limit": 50,
        }, pause_s=args.pause_s)
        demo.send("select_patient", ent, timeout_ms=60000, pause_s=args.pause_s * 1.5)
        demo.send("open_patient", ent, timeout_ms=90000, pause_s=args.pause_s * 2.5)

        series = demo.wait_for_series()
        if not series:
            raise RuntimeError("No series loaded")
        if args.series_number:
            selected_series = next(
                (row for row in series if int(row.get("series_number") or -1) == args.series_number),
                None,
            )
        else:
            selected_series = next((row for row in series if int(row.get("image_count") or 0) >= 20), series[0])
        if not selected_series:
            raise RuntimeError(f"Series {args.series_number} not found")
        print("selected_series:", json.dumps(selected_series, ensure_ascii=False), flush=True)
        demo.report["selected_series"] = selected_series
        demo.log("selection", {"selected_series": selected_series})
        demo.write_report()
        demo.send("change_series", {
            "series_number": selected_series["series_number"],
            "viewport": args.viewport,
        }, timeout_ms=90000, pause_s=args.pause_s * 3.0)

        stack = demo.wait_for_stack(args.viewport)
        count = int(stack.get("slice_count") or 0)
        print("stack:", json.dumps(stack, ensure_ascii=False), flush=True)
        if count > 1:
            for idx in (0, count // 2, count - 1):
                demo.send("scroll_slices", {
                    "viewport": args.viewport,
                    "index": idx,
                }, timeout_ms=30000, pause_s=args.pause_s * 1.4)
        demo.send("query_viewport_state", {}, timeout_ms=30000, pause_s=0.5)
    finally:
        client.close()
        demo.report["finished"] = datetime.now().isoformat(timespec="seconds")
        demo.report["status"] = "complete"
        demo.report["artifact_logs"] = {
            "commands": str(demo.commands_path),
            "conversation": str(demo.conversation_path),
        }
        demo.write_report()
    print("\nSMOOTH_VISIBLE_DEMO_DONE", flush=True)
    print("artifacts:", str(out_dir), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
